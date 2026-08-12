# OpenHarness Hooks 系统深度解析 — 面试题库

> 生成时间：2026/05/09
> 文档来源：01-Active-Topics/05-OpenHarness/Hooks/s01-Hooks-系统深度解析.md
> 题目数量：12 道

---

## 题目总览

| # | 问题 | 类型 | 难度 | 考察知识点 |
|---|------|------|------|------------|
| 1 | OpenHarness Hooks 的核心价值是什么？ | 概念题 | L1 | Hooks 核心定位 |
| 2 | HookEvent 定义了哪些触发事件？ | 概念题 | L1 | 10个HookEvent |
| 3 | 四种 Hook 类型分别是什么？适用场景有哪些？ | 理解题 | L2 | Hook类型对比 |
| 4 | 为什么 CommandHookDefinition 需要做 shell 转义？ | 理解题 | L2 | shlex.quote原理 |
| 5 | $ARGUMENTS 注入机制是如何工作的？ | 理解题 | L2 | $ARGUMENTS模板 |
| 6 | PRE_TOOL_USE 阻断流程的完整链路是什么？ | 实现题 | L3 | 阻断流程实现 |
| 7 | HookExecutor 如何执行多种类型的 Hook？ | 实现题 | L3 | 执行引擎核心逻辑 |
| 8 | HookReloader 热更新为何使用 st_mtime_ns 而不是 st_mtime？ | 理解题 | L2 | mtime_ns精度 |
| 9 | CommandHook vs AgentHook 有何区别？何时该用 AgentHook？ | 对比题 | L4 | Hook类型对比 |
| 10 | 如果让你为 Hook 系统设计 plugin 扩展机制，如何实现？ | 设计题 | L5 | Plugin架构设计 |
| 11 | Hook 执行失败时 block_on_failure 如何决定是否阻断？ | 理解题 | L2 | 阻断逻辑 |
| 12 | 如何设计一个多级门禁系统，利用 Hook 顺序执行特性？ | 设计题 | L5 | 顺序执行设计 |

---

## 题目详情

### Q1. OpenHarness Hooks 的核心价值是什么？

**考察点：** Hooks 核心定位 + 记忆能力
**类型：** 概念题
**难度：** L1（概念题）
**对应文档位置：** 概览章节

**问题：**
OpenHarness Hooks 的核心价值是什么？它与 Skills（知识加载）和 Tools（动作执行）有什么区别？

**参考答案：**

Hooks 是 OpenHarness 的**事件驱动自动化引擎**，核心价值在于**干预时机**：
- **Skills**：提供知识（能做什么），相当于知识库
- **Tools**：执行动作（能用什么），相当于四肢
- **Prompts**：塑造响应（怎么说话），相当于语气/人格
- **Hooks**：自动化干预（何时触发），相当于神经系统

关键区别在于：Hooks 可以在事件发生前阻断行为，在事件发生后触发副作用，而无需修改核心 Agent Loop。

```
用户提交 prompt → Agent Loop 运行
                 ├── [PRE_TOOL_USE] ──→ 阻断危险工具调用
                 ├── [POST_TOOL_USE] ──→ 推送执行日志到外部系统
                 ├── [SESSION_END] ──→ 生成会话摘要存入记忆
                 └── [SUBAGENT_STOP] ──→ 清理子 agent 资源
```

---

### Q2. HookEvent 定义了哪些触发事件？

**考察点：** 10个HookEvent + 记忆能力
**类型：** 概念题
**难度：** L1（概念题）
**对应文档位置：** events.py:8-20

**问题：**
列出 HookEvent 定义的全部 10 个触发事件，并说明每个事件的触发位置。

**参考答案：**

```python
class HookEvent(str, Enum):
    SESSION_START      # 会话开始时 → ui/runtime.py:351
    SESSION_END        # 会话结束时 → ui/runtime.py:370
    PRE_COMPACT        # 上下文压缩前 → services/compact/__init__.py:1068
    POST_COMPACT       # 上下文压缩后 → services/compact/__init__.py:1238-1252
    PRE_TOOL_USE       # 工具执行前 ← 最常用 → engine/query.py:698-705
    POST_TOOL_USE      # 工具执行后 → engine/query.py:817-827
    USER_PROMPT_SUBMIT  # 用户提交 prompt 时 → engine/query_engine.py:158-163
    NOTIFICATION        # 通知事件（如权限请求）→ engine/query.py:756-763
    STOP               # Agent Loop 停止 → engine/query.py:617-624
    SUBAGENT_STOP      # 派生的子 agent 停止时 → tools/agent_tool.py:109-123
```

**记忆口诀：** "SESSPRE/POST + USER_NOTI + STOP_SUB"

---

### Q3. 四种 Hook 类型分别是什么？适用场景有哪些？

**考察点：** Hook类型定义 + 理解能力
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** schemas.py:10-58

**问题：**
OpenHarness 定义了哪四种 Hook 类型？分别适用于什么场景？

**参考答案：**

| 类型 | 定义 | 适用场景 | timeout |
|------|------|----------|---------|
| **CommandHookDefinition** | 执行任意 shell 命令 | 文件系统检查、进程管理、简单条件判断 | ≤600s |
| **PromptHookDefinition** | 调用 LLM 语义判断 | 需要语义理解的审查（如判断是否涉及生产环境） | ≤600s |
| **HttpHookDefinition** | POST webhook 到外部系统 | 审计日志、告警通知、外部审批流 | ≤600s |
| **AgentHookDefinition** | 深度 agent 验证 | 复杂的安全审查，多步推理 | ≤1200s（更长） |

```python
# CommandHook - 最灵活
class CommandHookDefinition(BaseModel):
    command: str                    # shell 命令，支持 $ARGUMENTS 注入
    matcher: str | None = None       # glob 模式过滤（如 "bash", "write_file"）
    block_on_failure: bool = False

# AgentHook - 最深度
class AgentHookDefinition(BaseModel):
    prompt: str
    timeout_seconds: int = 60      # 比其他类型长
    block_on_failure: bool = True
```

**行业实践：Claude Code Hook 类型对比**

Claude Code 也使用三种 Hook 类型（command/prompt/agent），但没有 http hook：

```json
// Claude Code settings.json
{
  "hooks": {
    "PostToolUse": [
      {
        "type": "command",
        "matcher": "Edit|Write",
        "command": "你的 shell 命令",
        "timeout": 30000
      }
    ]
  }
}
```

| 维度 | OpenHarness | Claude Code |
|------|-------------|-------------|
| http hook | ✅ 有 | ❌ 无 |
| 事件数量 | 10 个 | 8 个 |
| 热更新 | ✅ 支持 | ❌ 需要重启 |
| Plugin 扩展 | ✅ 支持 | 有限 |

---

### Q4. 为什么 CommandHookDefinition 需要做 shell 转义？

**考察点：** shell转义原理 + 安全意识
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** executor.py:223-229

**问题：**
在 CommandHookDefinition 中，payload 会被 `shlex.quote` 转义后再插入命令。为什么需要这样做？请解释原理并给出安全攻击示例。

**参考答案：**

`shlex.quote` 防止 **shell 注入攻击**。当 payload 包含恶意内容时，未转义的字符串会被 shell 解释执行。

**原理：**
```python
def _inject_arguments(template, payload, shell_escape=False):
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)   # 转义！
    return template.replace("$ARGUMENTS", serialized)
```

**攻击示例：**
假设 payload 为 `{"tool_name": "bash", "tool_input": {"command": "rm -rf /tmp"}`：

- 未转义：`echo '{"command": "rm -rf /tmp"}'` → 被注入执行
- 已转义：`echo '"{\"command\": \"rm -rf /tmp\"}"'` → 仅为字符串

**典型攻击场景：**
```json
{
  "tool_input": {
    "command": "echo $ARGUMENTS; cat /etc/passwd"
  }
}
```
`$ARGUMENTS` 若未转义，`;` 后的命令会被执行。

---

### Q5. $ARGUMENTS 注入机制是如何工作的？

**考察点：** 模板注入原理
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** executor.py:223-229

**问题：**
$ARGUMENTS 在 Hook 配置中代表什么？它是如何被替换为实际 payload 的？

**参考答案：**

`$ARGUMENTS` 是 Hook 系统中的**模板占位符**，会被替换为 JSON 序列化的完整 payload：

```python
def _inject_arguments(template, payload, shell_escape=False):
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)
    return template.replace("$ARGUMENTS", serialized)
```

**示例（PRE_TOOL_USE payload）：**
```python
payload = {
    "tool_name": "bash",
    "tool_input": {"command": "ls"},
    "event": "pre_tool_use"
}
```

配置 `"command": "echo $ARGUMENTS"` 会变成：
```bash
echo '{"tool_name': 'bash', 'tool_input': {'command': 'ls'}, ...}'
```

**matcher 过滤：**
```python
def _matches_hook(hook, payload):
    matcher = getattr(hook, "matcher", None)
    if not matcher:
        return True
    subject = str(payload.get("tool_name") or payload.get("prompt") or payload.get("event") or "")
    return fnmatch.fnmatch(subject, matcher)
```

---

### Q6. PRE_TOOL_USE 阻断流程的完整链路是什么？

**考察点：** 阻断流程实现
**类型：** 实现题
**难度：** L3（实现题）
**对应文档位置：** query.py:697-711

**问题：**
请描述 PRE_TOOL_USE 阻断的完整链路，从用户调用工具到被阻断的整个过程，并画出流程图。

**参考答案：**

```python
async def _execute_tool_call(context, tool_name, tool_use_id, tool_input):
    # 1. 检查是否有 hook_executor
    if context.hook_executor is not None:
        # 2. 执行 PRE_TOOL_USE hooks
        pre_hooks = await context.hook_executor.execute(
            HookEvent.PRE_TOOL_USE,
            {
                "tool_name": tool_name,
                "tool_input": tool_input,
                "event": HookEvent.PRE_TOOL_USE.value,
            },
        )
        # 3. 任一 hook 阻断就停止
        if pre_hooks.blocked:
            return ToolResultBlock(
                tool_use_id=tool_use_id,
                content=pre_hooks.reason or f"pre_tool_use hook blocked {tool_name}",
                is_error=True,
            )
    # ... 继续正常执行工具
```

**完整流程图：**
```
工具调用请求
     │
     ▼
hook_executor.execute(PRE_TOOL_USE, payload)
     │
     ├── for hook in registry.get(PRE_TOOL_USE):
     │       │
     │       ├── _matches_hook(hook, payload)? → glob 不匹配则跳过
     │       │
     │       ├── Command → _run_command_hook()
     │       ├── HTTP → _run_http_hook()
     │       ├── Prompt → _run_prompt_like_hook(agent_mode=False)
     │       └── Agent → _run_prompt_like_hook(agent_mode=True)
     │
     ▼
AggregatedHookResult(results=[HookResult, ...])
     │
     ├── .blocked = any(result.blocked for result in results)
     └── .reason = first blocking reason
              │
              ▼ blocked=True
        ToolResultBlock(is_error=True)
              │
              ▼ 模型收到错误，自适应改用其他工具
```

---

### Q7. HookExecutor 如何执行多种类型的 Hook？

**考察点：** 执行引擎核心逻辑
**类型：** 实现题
**难度：** L3（实现题）
**对应文档位置：** executor.py:41-78

**问题：**
请阅读 HookExecutor 的源码，解释它如何统一处理 CommandHook、HttpHook、PromptHook、AgentHook 四种不同类型的 Hook。

**参考答案：**

**核心入口：**
```python
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

**统一返回模型：**
```python
@dataclass(frozen=True)
class HookResult:
    hook_type: str
    success: bool
    output: str = ""
    blocked: bool = False       # 阻断标志
    reason: str = ""

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
                return result.reason or result.output
        return ""
```

**关键设计决策：**
1. **顺序执行**（`for` + `await`）：hook 之间可存在依赖关系
2. **统一返回模型**：调用方无需关心类型差异
3. **Prompt/Agent 统一处理**：通过 `agent_mode` 布尔参数区分

---

### Q8. HookReloader 热更新为何使用 st_mtime_ns 而不是 st_mtime？

**考察点：** 文件监控精度 + 设计权衡
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** hot_reload.py:11-31

**问题：**
HookReloader 使用 `st_mtime_ns`（纳秒级）而非 `st_mtime`（秒级）来检测文件变化。为什么这样设计？这样做的优势是什么？

**参考答案：**

```python
class HookReloader:
    def __init__(self, settings_path: Path) -> None:
        self._last_mtime_ns = -1      # 初始值：未知

    def current_registry(self) -> HookRegistry:
        stat = self._settings_path.stat()
        if stat.st_mtime_ns != self._last_mtime_ns:   # 纳秒级精度检测
            self._last_mtime_ns = stat.st_mtime_ns
            self._registry = load_hook_registry(load_settings(self._settings_path))
        return self._registry
```

**为什么用 st_mtime_ns？**

| 精度 | 分辨率 | 问题场景 |
|------|--------|----------|
| `st_mtime` | 秒级 | 快速修改场景下可能漏检（如1秒内多次修改） |
| `st_mtime_ns` | 纳秒级 | 任何快速修改都能检测到 |

**场景示例：**
```
t=0.0s  →  写入 settings.json (mtime_ns = 1000000000)
t=0.5s  →  再次修改 settings.json (mtime_ns = 1000000001)
```
- 使用 `st_mtime`：两次都是 `1`，检测不到变化
- 使用 `st_mtime_ns`：能检测到变化

**其他关键设计：**
1. **被动触发式**：不启动后台线程，每次 `execute()` 前检查
2. **懒加载**：首次调用时才做检测和加载
3. **文件不存在安全处理**：文件被删时清空 registry

---

### Q9. CommandHook vs AgentHook 有何区别？何时该用 AgentHook？

**考察点：** Hook类型深度对比
**类型：** 对比题
**难度：** L4（对比题）
**对应文档位置：** schemas.py + executor.py:169-212

**问题：**
CommandHookDefinition 和 AgentHookDefinition 都用于验证判断，但有明显区别。请对比两者并说明何时应该使用 AgentHook。

**参考答案：**

| 维度 | CommandHookDefinition | AgentHookDefinition |
|------|----------------------|-------------------|
| **实现方式** | 执行 shell 命令 | 启动深度 agent 对话 |
| **timeout** | ≤600s | ≤1200s（是 command 的 2 倍） |
| **block_on_failure 默认值** | `False` | `True` |
| **适用场景** | 文件系统检查、进程管理 | 复杂安全审查、需要多步推理 |
| **判断能力** | 简单条件判断 | 语义理解、上下文理解 |

**代码对比：**
```python
# CommandHook - 简单命令检查
class CommandHookDefinition(BaseModel):
    command: str
    matcher: str | None = None
    block_on_failure: bool = False

# AgentHook - 深度推理
class AgentHookDefinition(BaseModel):
    prompt: str
    model: str | None = None
    timeout_seconds: int = 60      # 默认 60s，比 command 更长
    block_on_failure: bool = True  # 默认阻断
```

**AgentHook 的 Prompt 模板：**
```python
prefix = (
    "You are validating whether a hook condition passes in OpenHarness. "
    "Return strict JSON: {\"ok\": true} or {\"ok\": false, \"reason\": \"...\"}."
)
if agent_mode:
    prefix += " Be more thorough and reason over the payload before deciding."
```

**何时用 AgentHook：**
1. 需要理解语义上下文（如判断"这条命令是否指向生产环境"）
2. 需要多步推理（如"这个操作是否违反安全策略，需要交叉验证多个条件"）
3. 简单命令无法表达判断逻辑时

**行业实践：MCP 的 Agent 架构对比**

MCP 的 Server 可以暴露 Tool 给 AI 模型，但它的设计哲学不同：

```
MCP Server (轻量级程序)
    │
    ├── 实现 MCP 协议
    ├── 暴露特定功能（文件系统、数据库等）
    └── 通过 stdio 或 SSE 通信
```

OpenHarness AgentHook 更适合复杂审查，因为有 block_on_failure 控制、超时时间更长、返回结构化的 JSON 判断结果。

---

### Q10. 如果让你为 Hook 系统设计 plugin 扩展机制，如何实现？

**考察点：** Plugin架构设计
**类型：** 设计题
**难度：** L5（设计题）
**对应文档位置：** Plugin 扩展章节

**问题：**
OpenHarness 的 Plugin 可以通过 `plugin.json` 的 `hooks` 字段贡献 Hook。如果让你设计这个扩展机制，请描述你的架构设计。

**参考答案：**

**核心设计思路：**

```
plugin.json
    │
    ├── name: "my-plugin"
    ├── version: "1.0.0"
    └── hooks: {
        "pre_tool_use": [...],
        "post_tool_use": [...]
      }
```

**加载流程：**
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

**架构设计要点：**

1. **插件隔离**：每个插件贡献的 hooks 独立注册，不影响其他插件
2. **优先级机制**：支持 `priority` 字段控制执行顺序
3. **启用/禁用控制**：插件可动态启用/禁用
4. **版本兼容**：支持 API 版本检查
5. **依赖声明**：插件可声明对其他插件的依赖

**数据结构：**
```python
class PluginHookContribution(BaseModel):
    plugin_name: str
    plugin_version: str
    hooks: dict[HookEvent, list[HookDefinition]]
    priority: int = 0  # 越小越先执行
    enabled: bool = True
```

**追问：如果多个插件的 Hook 冲突怎么办？**
- 使用 priority 机制决定执行顺序
- 支持 `override` 字段允许高优先级 hook 覆盖低优先级
- 提供日志记录冲突供管理员决策

**行业实践：GitHub Agent HQ 的插件化思路**

微软 2025 年推出 Agent HQ，统一管理 AI 编程智能体。核心问题：
- 工具分散
- 上下文频繁切换
- 多订阅管理

**pre-commit 的插件生态值得借鉴：**
```yaml
# pre-commit-config.yaml - 远程 Hook 仓库
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: check-merge-conflict
```

---

### Q11. Hook 执行失败时 block_on_failure 如何决定是否阻断？

**考察点：** 阻断逻辑理解
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** executor.py + types.py

**问题：**
请解释 `block_on_failure` 字段在四种 Hook 类型中的工作原理，以及 `AggregatedHookResult.blocked` 是如何计算的。

**参考答案：**

**HookResult 中的阻断逻辑：**
```python
# Command hook
success = process.returncode == 0
return HookResult(
    hook_type=hook.type,
    success=success,
    output=output,
    blocked=hook.block_on_failure and not success,  # 关键：block_on_failure AND not success
    reason=output or f"command hook failed with exit code {process.returncode}",
)

# Prompt/Agent hook
parsed = _parse_hook_json(text)
return HookResult(
    hook_type=hook.type,
    success=parsed["ok"],
    blocked=hook.block_on_failure and not parsed["ok"],  # 关键
    reason=parsed.get("reason", ""),
)
```

**AggregatedHookResult 的聚合逻辑：**
```python
@dataclass(frozen=True)
class AggregatedHookResult:
    results: list[HookResult]

    @property
    def blocked(self) -> bool:
        return any(result.blocked for result in results)  # 任一阻断 → 整体阻断

    @property
    def reason(self) -> str:
        for result in self.results:
            if result.blocked:
                return result.reason or result.output  # 返回第一个阻断原因
        return ""
```

**示例：**
| hook | block_on_failure | success | blocked |
|------|-----------------|---------|---------|
| Hook A | False | False | False（不阻断） |
| Hook B | True | False | True（阻断） |
| Hook C | False | True | False |

`AggregatedHookResult.blocked = True`（任一为 True 即整体阻断）

---

### Q12. 如何设计一个多级门禁系统，利用 Hook 顺序执行特性？

**考察点：** 顺序执行设计
**类型：** 设计题
**难度：** L5（设计题）
**对应文档位置：** 设计亮点章节

**问题：**
OpenHarness 的 Hook 是顺序执行的（for + await），这意味着后续 Hook 可以依赖前面 Hook 的结果。请设计一个多级门禁系统，实现以下场景：
1. 第一级：检查命令是否涉及敏感文件
2. 第二级：检查命令是否涉及生产环境
3. 第三级：需要人工审批

**参考答案：**

**设计架构：**
```python
# settings.json 配置
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "command",
        "command": "check_sensitive_files.sh $ARGUMENTS",
        "matcher": "bash",
        "block_on_failure": false,    # 第一级：警告但不阻断
        "timeout_seconds": 5
      },
      {
        "type": "prompt",
        "prompt": "判断命令是否指向生产环境：$ARGUMENTS",
        "matcher": "bash",
        "block_on_failure": true,    # 第二级：阻断生产环境操作
        "timeout_seconds": 30
      },
      {
        "type": "agent",
        "prompt": "复杂安全审查，判断是否需要人工审批：$ARGUMENTS",
        "matcher": "bash",
        "block_on_failure": true,    # 第三级：需要审批
        "timeout_seconds": 60
      }
    ]
  }
}
```

**执行流程：**
```
工具调用
    │
    ├─── 第一级（CommandHook）────────┐
    │     检查敏感文件                │
    │     block_on_failure=false       │
    │     失败仅警告，不阻断          │
    └─────────────────────────────────┘
    │
    ├─── 第二级（PromptHook）────────┐
    │     LLM 判断是否生产环境        │
    │     block_on_failure=true       │
    │     是 → 立即阻断              │
    │     否 → 继续                  │
    └─────────────────────────────────┘
    │
    ├─── 第三级（AgentHook）─────────┐
    │     深度审查是否需要人工审批    │
    │     block_on_failure=true       │
    │     需要审批 → 阻断并通知      │
    │     不需要 → 通过              │
    └─────────────────────────────────┘
```

**关键设计点：**

1. **顺序执行保证依赖**：第二级可以读取第一级的输出（如日志）
2. **逐级阻断策略**：越后面的 Hook 越严格
3. **不同类型组合**：Command（快速过滤）+ Prompt（语义判断）+ Agent（深度审查）
4. **状态共享**：可通过 payload 传递前面 Hook 的结果

**追问：如果第二级的判断依赖第一级的结果怎么办？**
- 通过 hook 之间的日志共享
- 或将多个检查合并到一个 AgentHook 中处理

**行业实践：Git pre-commit 的多级检查策略**

```yaml
# .pre-commit-config.yaml
fail_fast: false  # 继续检查所有问题，不在第一个失败时停止
repos:
  - repo: local
    hooks:
      - id: sensitive-file-check
        name: Check sensitive files
        entry: check_sensitive.sh
        files: '\\.(py|js)$'
      - id: production-check
        name: Check production commands
        entry: check_prod.sh
        files: '\\.py$'
```

**AI Agent 事件驱动架构的演进**

阿里云 2025 年 AIAgent 实践报告指出：
- 基于事件驱动的 Agent 架构成为主流
- 事件驱动实现松耦合和可扩展性
- Hook 机制是落地事件驱动的关键技术

---

## 难度分布统计

| 难度 | 数量 | 占比 |
|------|------|------|
| L1（概念题） | 2 | 17% |
| L2（理解题） | 5 | 42% |
| L3（实现题） | 2 | 17% |
| L4（对比题） | 1 | 8% |
| L5（设计题） | 2 | 17% |

**分布建议**：L1-L2 占 30%，L3 占 40%，L4-L5 占 30%

---

## 发散延伸（L4-L5 级别）

### Q10. 如果让你为 Hook 系统设计 plugin 扩展机制，如何实现？

**行业实践：**
- GitHub Agent HQ 统一管理 AI 编程智能体，解决工具分散问题
- pre-commit 生态支持远程仓库下载 Hook，实现标准化分发
- OpenHarness 通过 plugin.json 支持 hook 贡献，与上述设计思路一致

**发散思考：**
- 如果多个插件的 Hook 冲突，如何解决优先级问题？
- 如何实现 Hook 的版本兼容性，确保升级不破坏现有配置？
- 如何设计 Hook 的沙箱机制，防止恶意插件影响系统安全？

### Q12. 如何设计一个多级门禁系统，利用 Hook 顺序执行特性？

**行业实践：**
- Git pre-commit 的 `fail_fast: false` 策略确保检查所有问题
- 阿里云 AIAgent 实践报告：事件驱动实现松耦合和可扩展性
- Hook 机制是落地事件驱动的关键技术

**发散思考：**
- 如果需要在多台机器上同步门禁策略，如何实现分布式 Hook？
- 如何设计 Hook 执行结果的审计日志，满足合规要求？
- 如何与外部审批系统（如 Jira、Slack）集成，实现人工审批流？

---

## 相关技术对比

### 与 Claude Code Hooks 的对比

| 特性 | OpenHarness | Claude Code |
|------|-------------|-------------|
| 事件数量 | 10 个 | 8 个 |
| Hook 类型 | command/prompt/http/agent | command/prompt/agent |
| 热更新 | ✅ 支持（mtime_ns 检测） | ❌ 需要重启 |
| Plugin 扩展 | ✅ 完整支持 | 有限 |
| http hook | ✅ 有 | ❌ 无 |

### 与 Git pre-commit 的对比

| 特性 | OpenHarness Hooks | Git pre-commit |
|------|-------------------|----------------|
| 触发时机 | Agent 生命周期事件 | git commit |
| 阻断能力 | ✅ 可配置 block_on_failure | ✅ 可阻断提交 |
| 配置格式 | JSON | YAML |
| 执行顺序 | 顺序执行（可依赖） | 可配置 fail_fast |
| 远程 Hook | 通过 Plugin 机制 | ✅ 支持远程仓库 |

### 与 MCP 的互补关系

MCP（Model Context Protocol）是 Anthropic 主导的标准化协议：
- **核心价值**：像 USB-C 一样，为 AI 模型提供标准化的外部工具/数据源连接
- **架构**：Host ↔ Client ↔ Server 模式
- **OpenHarness 可以利用 MCP**：通过 HTTP Hook 调用外部 MCP 服务

**安全挑战（MCP 的教训）：**
- Context Poisoning：恶意工具描述污染 Agent 上下文
- Hook 系统需要对注入内容做严格校验
- OpenHarness 的 `shlex.quote` 是好的安全实践