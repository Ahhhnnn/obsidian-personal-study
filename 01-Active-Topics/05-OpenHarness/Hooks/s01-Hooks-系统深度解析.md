# OpenHarness Hooks 系统深度解析

## 概览

Hooks 是 OpenHarness 的**事件驱动自动化引擎**——在 Agent 运行过程中的关键节点插入自定义逻辑，实现门禁、审计、监控、路由等跨系统联动。

与 Skills（知识加载）和 Tools（动作执行）不同，Hooks 的核心价值在于**干预时机**：你可以在事件发生前阻断行为，在事件发生后触发副作用，而无需修改核心 Agent Loop。

```
用户提交 prompt
       │
       ▼
  Agent Loop 运行
       │
       ├── [PRE_TOOL_USE]  ──→ 阻断危险工具调用
       │
       ├── [POST_TOOL_USE] ──→ 推送执行日志到外部系统
       │
       ├── [SESSION_END]   ──→ 生成会话摘要存入记忆
       │
       └── [SUBAGENT_STOP] ──→ 清理子 agent 资源
```

---

## 核心文件结构

```
src/openharness/hooks/
├── __init__.py           # 公共导出
├── events.py             # HookEvent 枚举（10 个事件）
├── schemas.py            # 四种 Hook 类型定义
├── types.py              # HookResult / AggregatedHookResult
├── loader.py             # HookRegistry 注册表 + load_hook_registry()
├── executor.py           # HookExecutor 执行引擎（核心逻辑）
└── hot_reload.py         # HookReloader 文件监听热更新
```

---

## 10 个触发事件

`events.py:8-20` 定义了全部事件：

```python
class HookEvent(str, Enum):
    SESSION_START      # 会话开始时
    SESSION_END        # 会话结束时
    PRE_COMPACT        # 上下文压缩前
    POST_COMPACT       # 上下文压缩后
    PRE_TOOL_USE       # 工具执行前  ← 最常用
    POST_TOOL_USE      # 工具执行后
    USER_PROMPT_SUBMIT  # 用户提交 prompt 时
    NOTIFICATION        # 通知事件（如权限请求）
    STOP               # Agent Loop 停止
    SUBAGENT_STOP      # 派生的子 agent 停止时
```

### 触发位置速查

| 事件 | 触发位置 | 行号 |
|------|---------|------|
| `SESSION_START` | `ui/runtime.py` | 351 |
| `SESSION_END` | `ui/runtime.py` | 370 |
| `USER_PROMPT_SUBMIT` | `engine/query_engine.py` | 158-163 |
| `PRE_TOOL_USE` | `engine/query.py` | 698-705 |
| `POST_TOOL_USE` | `engine/query.py` | 817-827 |
| `NOTIFICATION` | `engine/query.py` | 756-763 |
| `STOP` | `engine/query.py` | 617-624 |
| `SUBAGENT_STOP` | `tools/agent_tool.py` | 109-123 |
| `PRE_COMPACT` | `services/compact/__init__.py` | 1068 |
| `POST_COMPACT` | `services/compact/__init__.py` | 1238-1252 |

---

## 四种 Hook 类型

`schemas.py:10-58` 定义了四种 Hook 类型，统一使用 Pydantic BaseModel 验证：

### CommandHookDefinition

执行任意 shell 命令，最灵活，适用于文件系统检查、进程管理等。

```python
class CommandHookDefinition(BaseModel):
    type: Literal["command"] = "command"
    command: str                    # shell 命令，支持 $ARGUMENTS 注入
    timeout_seconds: int = 30       # 上限 600s
    matcher: str | None = None       # glob 模式过滤（如 "bash", "write_file"）
    block_on_failure: bool = False  # 失败时是否阻断
```

### PromptHookDefinition

调用 LLM 语义判断，适用于需要语义理解的审查（如判断操作是否涉及生产环境）。

```python
class PromptHookDefinition(BaseModel):
    type: Literal["prompt"] = "prompt"
    prompt: str                     # 注入 $ARGUMENTS 的模板
    model: str | None = None        # 可覆盖默认模型
    timeout_seconds: int = 30       # 上限 600s
    block_on_failure: bool = True   # prompt 默认阻断
```

### HttpHookDefinition

POST webhook 到外部系统，适用于审计日志、告警通知、外部审批流。

```python
class HttpHookDefinition(BaseModel):
    type: Literal["http"] = "http"
    url: str                        # POST 目标
    headers: dict[str, str] = {}     # 自定义请求头
    timeout_seconds: int = 30       # 上限 600s
    block_on_failure: bool = False
```

### AgentHookDefinition

深度 agent 验证，timeout 60s（比 prompt 更长），会进行多步推理，适用于复杂的安全审查。

```python
class AgentHookDefinition(BaseModel):
    type: Literal["agent"] = "agent"
    prompt: str
    model: str | None = None
    timeout_seconds: int = 60      # 上限 1200s（比其他类型长）
    block_on_failure: bool = True
```

---

## 执行引擎：HookExecutor

`executor.py:41-78` 是 Hook 系统的核心。

### 主入口

```python
class HookExecutor:
    def __init__(self, registry: HookRegistry, context: HookExecutionContext) -> None:
        self._registry = registry
        self._context = context

    async def execute(self, event: HookEvent, payload: dict[str, Any]) -> AggregatedHookResult:
        results: list[HookResult] = []
        for hook in self._registry.get(event):       # ① 按事件取出所有 hook
            if not _matches_hook(hook, payload):      # ② matcher glob 过滤
                continue
            if isinstance(hook, CommandHookDefinition):
                results.append(await self._run_command_hook(hook, event, payload))
            elif isinstance(hook, HttpHookDefinition):
                results.append(await self._run_http_hook(hook, event, payload))
            elif isinstance(hook, PromptHookDefinition):
                results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=False))
            elif isinstance(hook, AgentHookDefinition):
                results.append(await self._run_prompt_like_hook(hook, event, payload, agent_mode=True))
        return AggregatedHookResult(results=results)
```

**关键设计**：
- **顺序执行**（`for` + `await`），非并行 — hook 之间可存在依赖关系
- 返回 `AggregatedHookResult`，调用方只需判断 `.blocked` 和 `.reason`

### 命令执行：_run_command_hook

`executor.py:80-136`：

```python
async def _run_command_hook(self, hook, event, payload):
    command = _inject_arguments(hook.command, payload, shell_escape=True)
    # 额外注入环境变量
    env = {
        **os.environ,
        "OPENHARNESS_HOOK_EVENT": event.value,
        "OPENHARNESS_HOOK_PAYLOAD": json.dumps(payload),
    }
    process = await create_shell_subprocess(command, cwd=self._context.cwd, ...)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=hook.timeout_seconds)
    success = process.returncode == 0
    return HookResult(
        hook_type=hook.type,
        success=success,
        output=output,
        blocked=hook.block_on_failure and not success,   # 阻断逻辑
        reason=output or f"command hook failed with exit code {process.returncode}",
    )
```

### HTTP 执行：_run_http_hook

`executor.py:138-167`：POST JSON `{"event": "...", "payload": {...}}` 到指定 URL，通过 `response.is_success` 判断成功。

### Prompt/Agent 执行：_run_prompt_like_hook

`executor.py:169-212`：统一处理 `prompt` 和 `agent` 两种类型：

```python
async def _run_prompt_like_hook(self, hook, event, payload, *, agent_mode):
    prompt = _inject_arguments(hook.prompt, payload)
    prefix = (
        "You are validating whether a hook condition passes in OpenHarness. "
        "Return strict JSON: {\"ok\": true} or {\"ok\": false, \"reason\": \"...\"}."
    )
    if agent_mode:
        prefix += " Be more thorough and reason over the payload before deciding."
    request = ApiMessageRequest(
        model=hook.model or self._context.default_model,
        messages=[ConversationMessage.from_user_text(prompt)],
        system_prompt=prefix,
        max_tokens=512,
    )
    # 流式调用 API...
    parsed = _parse_hook_json(text)
    # 返回 HookResult，blocked = hook.block_on_failure and not parsed["ok"]
```

---

## 注册与加载

### HookRegistry

`loader.py:10-37`：

```python
class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[HookEvent, list[HookDefinition]] = defaultdict(list)

    def register(self, event: HookEvent, hook: HookDefinition) -> None:
        self._hooks[event].append(hook)

    def get(self, event: HookEvent) -> list[HookDefinition]:
        return list(self._hooks.get(event, []))
```

### load_hook_registry

`loader.py:40-60`：从两个来源加载 hooks：

```python
def load_hook_registry(settings, plugins=None) -> HookRegistry:
    registry = HookRegistry()
    # 来源 1：settings.json
    for raw_event, hooks in settings.hooks.items():
        event = HookEvent(raw_event)
        for hook in hooks:
            registry.register(event, hook)
    # 来源 2：plugin.json（插件贡献）
    for plugin in plugins or []:
        if not plugin.enabled:
            continue
        for raw_event, hooks in plugin.hooks.items():
            event = HookEvent(raw_event)
            for hook in hooks:
                registry.register(event, hook)
    return registry
```

### Hot Reload

`hot_reload.py:11-31` 的 `HookReloader` 监听 settings 文件的 mtime 变化，修改后自动重新加载 hook registry，无需重启 harness。

---

## $ARGUMENTS 注入机制

`executor.py:223-229`：这是 Hook 系统的核心灵活 性来源。

```python
def _inject_arguments(
    template: str, payload: dict[str, Any], *, shell_escape: bool = False
) -> str:
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)   # 命令 hook 做 shell 转义
    return template.replace("$ARGUMENTS", serialized)
```

`$ARGUMENTS` 会被替换为 JSON 序列化的完整 payload。在 **command hook** 中会做 `shlex.quote` 转义，防止 shell 注入攻击。

### Matcher 过滤

`executor.py:215-220`：

```python
def _matches_hook(hook: HookDefinition, payload: dict[str, Any]) -> bool:
    matcher = getattr(hook, "matcher", None)
    if not matcher:
        return True
    subject = str(
        payload.get("tool_name") or
        payload.get("prompt") or
        payload.get("event") or ""
    )
    return fnmatch.fnmatch(subject, matcher)
```

`matcher` 是 glob 模式，从 payload 的 `tool_name` / `prompt` / `event` 中取非空值进行匹配。

---

## Payload 示例

### PRE_TOOL_USE

```python
{
    "tool_name": "bash",
    "tool_input": {"command": "rm -rf /"},
    "event": "pre_tool_use"
}
```

### POST_TOOL_USE

```python
{
    "tool_name": "bash",
    "tool_input": {"command": "ls"},
    "tool_output": "README.md\nsrc/\ntests/",
    "tool_is_error": False,
    "event": "post_tool_use"
}
```

### SUBAGENT_STOP

```python
{
    "event": "subagent_stop",
    "agent_id": "agent_123",
    "task_id": "task_456",
    "backend_type": "anthropic",
    "status": "completed",
    "return_code": 0,
    "description": "Subagent finished",
    "subagent_type": "Explore",
    "team": "default",
    "mode": "auto"
}
```

### PRE_COMPACT

```python
{
    "event": "pre_compact",
    "trigger": "token_limit",
    "model": "claude-sonnet-4-6",
    "pre_compact_message_count": 50,
    "post_compact_message_count": 15,
    "pre_compact_tokens": 180000,
    "post_compact_tokens": 60000,
    "attachments": [],
    "discovered_tools": ["bash", "read_file", "write_file"]
}
```

---

## 结果聚合

`types.py:9-38`：

```python
@dataclass(frozen=True)
class HookResult:
    hook_type: str
    success: bool
    output: str = ""
    blocked: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass(frozen=True)
class AggregatedHookResult:
    results: list[HookResult]

    @property
    def blocked(self) -> bool:
        return any(result.blocked for result in self.results)  # 任一阻断 → 整体阻断

    @property
    def reason(self) -> str:
        for result in self.results:
            if result.blocked:
                return result.reason or result.output  # 返回第一个阻断原因
        return ""
```

---

## 阻断流程：PRE_TOOL_USE 实战

`query.py:697-711` 展示了 hook 阻断的完整链路：

```python
async def _execute_tool_call(context, tool_name, tool_use_id, tool_input):
    if context.hook_executor is not None:
        pre_hooks = await context.hook_executor.execute(
            HookEvent.PRE_TOOL_USE,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "event": HookEvent.PRE_TOOL_USE.value,
            },
        )
        if pre_hooks.blocked:           # ← 任一 hook 阻断就停止
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=pre_hooks.reason or f"pre_tool_use hook blocked {tool_name}",
                is_error=True,
            )
    # ... 继续正常执行工具
```

---

## 真实配置示例

### 阻断所有 bash 调用

```python
hook_reg.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(
    type="command",
    command="exit 1",        # 永远失败
    matcher="bash",
    block_on_failure=True,
    timeout_seconds=5,
))
```

### 保护敏感文件

```python
# 保护 config.py 不被写入
hook_reg.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(
    type="command",
    command='echo "$TOOL_INPUT" | grep -q "config.py" && exit 1 || exit 0',
    matcher="write_file",
    block_on_failure=True,
    timeout_seconds=5,
))
```

### LLM 语义审查

```python
registry.register(
    HookEvent.PRE_TOOL_USE,
    PromptHookDefinition(
        prompt="Check if this operation targets production environment",
        matcher="bash",
    ),  # block_on_failure 默认为 True
)
```

### settings.json 格式

```json
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "echo $ARGUMENTS | jq '.tool_name'",
        "matcher": "bash",
        "block_on_failure": false,
        "timeout_seconds": 5
      }
    ],
    "post_tool_use": [
      {
        "type": "http",
        "url": "https://audit.example.com/webhook",
        "headers": {"Authorization": "Bearer $TOKEN"},
        "matcher": "bash",
        "block_on_failure": false,
        "timeout_seconds": 10
      }
    ]
  }
}
```

---

## Plugin 扩展

插件通过 `plugin.json` 的 `hooks` 字段贡献 hooks：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "echo 'plugin hook'",
        "matcher": "bash",
        "block_on_failure": false
      }
    ]
  }
}
```

由 `plugins/loader.py:596,624` 的 `_load_plugin_hooks()` 和 `_load_plugin_hooks_structured()` 加载。

---

## 完整执行流程

```
settings.json / plugin.json
        │
        ▼
load_hook_registry()
        │
        ▼
HookRegistry._hooks: {HookEvent: [HookDefinition, ...]}
        │
        │  工具调用前 → query.py:697
        ▼
HookExecutor.execute(PRE_TOOL_USE, payload)
        │
        ├─── for hook in registry.get(PRE_TOOL_USE):
        │       │
        │       ├── _matches_hook(hook, payload)?
        │       │       └── glob 不匹配 → 跳过
        │       │
        │       ├── Command → _run_command_hook()
        │       │       └── shell 进程 / timeout
        │       │
        │       ├── HTTP    → _run_http_hook()
        │       │       └── httpx POST
        │       │
        │       ├── Prompt  → _run_prompt_like_hook(agent_mode=False)
        │       │       └── API call → {"ok": true/false}
        │       │
        │       └── Agent   → _run_prompt_like_hook(agent_mode=True)
        │               └── API call（更长超时，更深度推理）
        │
        ▼
AggregatedHookResult(results=[HookResult, ...])
        │
        ├── .blocked → any(r.blocked for r in results)
        └── .reason  → first blocking reason
                │
                ▼  blocked=True
        ToolResultBlock(is_error=True)
                │
                ▼  模型收到错误，自适应改用其他工具
```

---

## 设计亮点

1. **统一返回模型**：四种 hook 类型统一返回 `HookResult`，调用方无需关心类型差异
2. **$ARGUMENTS 模板注入**：shell/prompt/agent 三种 hook 都能获取完整 payload，配置即代码
3. **Shell 转义防护**：`shlex.quote` 确保恶意 payload（如 `$(whoami)`）不会在命令 hook 中被意外执行
4. **双重超时保护**：全局 `timeout_seconds` + `asyncio.wait_for` 硬超时，防止 hook 永久阻塞 Agent Loop
5. **Matcher 避免过度触发**：同一 hook 定义 + glob 过滤，避免为每个工具写单独 hook
6. **顺序执行**：hook 之间可存在依赖，适合构建多级门禁
7. **Hot Reload**：修改 settings 文件无需重启 harness
8. **Plugin 生态**：hooks 是插件贡献的主要机制之一

---

## 与 Skills/Tools/Prompts 的关系

| 模块 | 职责 | 类比 |
|------|------|------|
| **Skills** | 提供知识（能做什么） | 知识库 |
| **Tools** | 执行动作（能用什么） | 四肢 |
| **Prompts** | 塑造响应（怎么说话） | 语气/人格 |
| **Hooks** | 自动化干预（何时触发） | 神经系统 |

Skills/Tools/Prompts 定义了 Agent 的**能力边界**，Hooks 则负责**事件驱动**地连接和扩展这些能力。
