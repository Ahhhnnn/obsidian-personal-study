# OpenHarness Hooks 系统面试题库

> 生成时间：2026/05/09
> 文档来源：s01-Hooks-系统深度解析.md
> 题目数量：10 道

---

## 题目总览

| # | 问题 | 类型 | 难度 | 考察知识点 |
|---|------|------|------|------------|
| 1 | Hooks 系统的核心价值是什么？ | 概念题 | L1 | Hook 定位与价值 |
| 2 | 列举 10 个 HookEvent 并说明触发时机 | 概念题 | L2 | 事件体系 |
| 3 | 四种 Hook 类型各有何特点？如何选型？ | 理解题 | L2 | Hook 类型对比 |
| 4 | CommandHook 如何实现危险命令阻断？ | 实现题 | L3 | 命令执行与安全 |
| 5 | $ARGUMENTS 注入机制的原理是什么？ | 理解题 | L2 | 模板注入 |
| 6 | Hot Reload 如何实现无需重启更新？ | 理解题 | L3 | 热更新设计 |
| 7 | HookExecutor 的执行模型是怎样的？ | 理解题 | L3 | 执行引擎 |
| 8 | 对比 CommandHook 和 AgentHook 的适用场景 | 对比题 | L4 | 选型对比 |
| 9 | 如何设计一个生产环境审计 Hook？ | 设计题 | L5 | 系统设计 |
| 10 | Hooks 与 Skills/Tools/Prompts 的关系是什么？ | 对比题 | L4 | 架构定位 |

---

## 题目详情

### Q1. Hooks 系统的核心价值是什么？

**考察点：** Hook 系统定位与核心价值
**类型：** 概念题
**难度：** L1（概念题）
**对应文档位置：** 概览

**问题：**
OpenHarness 中的 Hooks 系统是什么？它的核心价值在哪里？与 Skills（知识）和 Tools（动作）有何本质区别？

**参考答案：**

Hooks 是 OpenHarness 的**事件驱动自动化引擎**——在 Agent 运行过程中的关键节点插入自定义逻辑，实现门禁、审计、监控、路由等跨系统联动。

**核心价值：干预时机**

| 模块 | 职责 | 类比 |
|------|------|------|
| **Skills** | 提供知识（能做什么） | 知识库 |
| **Tools** | 执行动作（能用什么） | 四肢 |
| **Prompts** | 塑造响应（怎么说话） | 语气/人格 |
| **Hooks** | 自动化干预（何时触发） | 神经系统 |

Skills/Tools/Prompts 定义了 Agent 的**能力边界**，Hooks 则负责**事件驱动**地连接和扩展这些能力。

**本质区别**：Hooks 的核心不是"提供能力"，而是在既有能力执行过程中**干预时机**——可以在事件发生前阻断行为，在事件发生后触发副作用。

---

### Q2. 列举 10 个 HookEvent 并说明触发时机

**考察点：** 事件体系记忆
**类型：** 概念题
**难度：** L2（理解题）
**对应文档位置：** 10 个触发事件

**问题：**
`events.py` 中定义了哪 10 个 HookEvent？分别在什么时机触发？

**参考答案：**

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

**触发位置速查表：**

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

### Q3. 四种 Hook 类型各有何特点？如何选型？

**考察点：** Hook 类型理解与选型
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** 四种 Hook 类型

**问题：**
OpenHarness 支持哪四种 Hook 类型？它们各自的特点、适用场景和关键配置项是什么？

**参考答案：**

| 类型 | 特点 | 适用场景 | 关键配置 |
|------|------|----------|----------|
| **CommandHook** | 执行 shell 命令，最灵活 | 文件系统检查、进程管理、简单判断 | `command`, `matcher`, `timeout_seconds`, `block_on_failure` |
| **PromptHook** | 调用 LLM 语义判断 | 需要语义理解的审查（如判断是否涉及生产环境） | `prompt`, `model`, `timeout_seconds`, `block_on_failure`（默认 True） |
| **HttpHook** | POST webhook 到外部系统 | 审计日志、告警通知、外部审批流 | `url`, `headers`, `timeout_seconds`, `block_on_failure` |
| **AgentHook** | 深度 agent 验证，timeout 60s | 复杂的安全审查，多步推理 | `prompt`, `model`, `timeout_seconds`（最长 1200s）, `block_on_failure`（默认 True） |

**选型决策树：**

```
需要执行检查？
    │
    ├── 简单命令/文件检查 → CommandHook
    │
    ├── 需要语义理解？
    │       ├── 单步判断 → PromptHook
    │       └── 多步推理 → AgentHook
    │
    └── 外部系统集成 → HttpHook
```

**设计细节：**
- AgentHook 的 timeout 默认 60s，最长可达 1200s（比其他类型长）
- PromptHook 的 `block_on_failure` 默认为 True（更安全）
- CommandHook 的 `block_on_failure` 默认为 False

---

### Q4. CommandHook 如何实现危险命令阻断？

**考察点：** 安全机制实现
**类型：** 实现题
**难度：** L3（实现题）
**对应文档位置：** 命令执行 + 真实配置示例

**问题：**
假设要阻断用户执行 `rm -rf /` 或修改敏感文件（如 `config.py`），如何配置 CommandHook？请写出配置示例并解释执行流程。

**参考答案：**

**示例 1：阻断所有 bash 调用**

```python
hook_reg.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(
    type="command",
    command="exit 1",        # 永远失败
    matcher="bash",          # 只匹配 bash 工具
    block_on_failure=True,   # 失败时阻断
    timeout_seconds=5,
))
```

**示例 2：保护敏感文件**

```python
hook_reg.register(HookEvent.PRE_TOOL_USE, CommandHookDefinition(
    type="command",
    command='echo "$TOOL_INPUT" | grep -q "config.py" && exit 1 || exit 0',
    matcher="write_file",    # 匹配 write_file 工具
    block_on_failure=True,
    timeout_seconds=5,
))
```

**settings.json 格式：**

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
    ]
  }
}
```

**执行流程：**

```
用户执行危险命令
        │
        ▼
HookExecutor.execute(PRE_TOOL_USE, payload)
        │
        ├── $ARGUMENTS 被替换为 JSON payload
        │   {
        │     "tool_name": "bash",
        │     "tool_input": {"command": "rm -rf /"},
        │     "event": "pre_tool_use"
        │   }
        │
        ├── CommandHook 执行: exit 1（永远失败）
        │
        ├── HookResult: success=False, blocked=True
        │
        └── AggregatedHookResult.blocked=True
                │
                ▼
        ToolResultBlock(is_error=True)
                │
                ▼
        模型收到错误，自适应改用其他工具
```

**追问提示：**
- `shlex.quote` 在其中起到什么作用？
- 如果 command 执行超时，会发生什么？

---

### Q5. $ARGUMENTS 注入机制的原理是什么？

**考察点：** 模板注入原理
**类型：** 理解题
**难度：** L2（理解题）
**对应文档位置：** $ARGUMENTS 注入机制

**问题：**
`$ARGUMENTS` 在 Hook 配置中代表什么？它是如何被替换的？为什么 CommandHook 需要 shell 转义？

**参考答案：**

**$ARGUMENTS 的作用：**

`$ARGUMENTS` 是 Hook 系统中的**模板占位符**，会被替换为 JSON 序列化的完整 payload。

**替换原理（`executor.py:223-229`）：**

```python
def _inject_arguments(
    template: str, payload: dict[str, Any], *, shell_escape: bool = False
) -> str:
    serialized = json.dumps(payload, ensure_ascii=True)
    if shell_escape:
        serialized = shlex.quote(serialized)   # 命令 hook 做 shell 转义
    return template.replace("$ARGUMENTS", serialized)
```

**示例：**

配置：`echo $ARGUMENTS | jq '.tool_name'`

实际 payload：
```json
{"tool_name": "bash", "tool_input": {"command": "ls"}, "event": "pre_tool_use"}
```

替换后：
```
echo '{"tool_name": "bash", "tool_input": {"command": "ls"}, "event": "pre_tool_use"}' | jq '.tool_name'
```

**为什么需要 shell 转义？**

payload 中可能包含恶意内容，如：
```json
{"command": "$(whoami)"}
```

如果不转义，直接拼接会导致命令注入：
```bash
# 未转义（危险）
echo '{"command": "$(whoami)"}'  → 执行 whoami

# shlex.quote 转义后（安全）
echo '"{\"command\": \"$(whoami)\"}"'  → 只输出字符串，不执行
```

**三种 Hook 的 $ARGUMENTS 处理：**

| Hook 类型 | shell_escape | 原因 |
|-----------|-------------|------|
| CommandHook | ✅ True | 执行 shell 命令，需要防护注入 |
| PromptHook | ❌ False | 发送给 LLM，不需要 shell 处理 |
| AgentHook | ❌ False | 发送给 LLM，不需要 shell 处理 |

---

### Q6. Hot Reload 如何实现无需重启更新？

**考察点：** 热更新设计
**类型：** 理解题
**难度：** L3（实现题）
**对应文档位置：** Hot Reload

**问题：**
`HookReloader` 实现了修改 settings.json 后无需重启即可热更新。请解释其设计原理，为什么不用 watchdog？`st_mtime_ns` 和 `st_mtime` 有何区别？

**参考答案：**

**设计原理：被动触发式检查**

```python
class HookReloader:
    def __init__(self, settings_path: Path) -> None:
        self._settings_path = settings_path
        self._last_mtime_ns = -1      # 初始值：未知
        self._registry = HookRegistry()

    def current_registry(self) -> HookRegistry:
        try:
            stat = self._settings_path.stat()
        except FileNotFoundError:           # 文件被删了 → 清空 registry
            self._registry = HookRegistry()
            self._last_mtime_ns = -1
            return self._registry

        if stat.st_mtime_ns != self._last_mtime_ns:   # 纳秒级精度检测
            self._last_mtime_ns = stat.st_mtime_ns
            self._registry = load_hook_registry(load_settings(self._settings_path))
        return self._registry
```

**执行流程：**

```
用户启动 oh（进入 TUI）
        │
        ▼
HookReloader(get_config_file_path())
        │
        ▼
TUI 运行中，用户修改 settings.json 添加新 hook
        │
        ▼
下次调用 hook_executor.execute() → current_registry()
        │
        ├── mtime 变化？→ 重新 load_hook_registry()
        └── 无变化？→ 返回缓存的 registry
```

**三个关键实现细节：**

1. **`st_mtime_ns` vs `st_mtime`**：
   - `st_mtime`：秒级精度
   - `st_mtime_ns`：纳秒级精度
   - 在快速修改场景下（如连续两次保存），秒级可能检测不到变化

2. **懒加载**：不立即加载，首次调用 `current_registry()` 时才做第一次检测

3. **文件不存在安全处理**：如果 settings 文件被删除，清空 registry 并重置状态

**为什么不用 watchdog？**

| 方案 | 优点 | 缺点 |
|------|------|------|
| watchdog | 实时通知 | 需要额外依赖、管理后台线程 |
| **当前方案** | 零依赖、简单可靠 | 略有延迟（下次执行前检查） |

当前方案适合 TUI 单用户、低频检查场景。

---

### Q7. HookExecutor 的执行模型是怎样的？

**考察点：** 执行引擎核心逻辑
**类型：** 理解题
**难度：** L3（实现题）
**对应文档位置：** 执行引擎

**问题：**
请描述 `HookExecutor` 的执行模型：如何调度四种 Hook 类型？如何聚合结果？阻断逻辑是怎样的？

**参考答案：**

**主入口（`executor.py:41-78`）：**

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

**执行模型特点：**

| 特性 | 说明 |
|------|------|
| **顺序执行** | `for` + `await`，非并行 — hook 之间可存在依赖关系 |
| **类型分发** | 通过 `isinstance` 判断类型，调用对应执行方法 |
| **Matcher 过滤** | glob 模式匹配，决定是否跳过当前 hook |

**结果聚合（`types.py`）：**

```python
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

**阻断逻辑：**

```
HookResult.blocked = hook.block_on_failure AND NOT success

示例：
- CommandHook: block_on_failure=True, exit code=1 → blocked=True
- CommandHook: block_on_failure=False, exit code=1 → blocked=False
- PromptHook: block_on_failure=True, LLM 返回 {"ok": false} → blocked=True
```

**完整执行流程图：**

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
```

---

### Q8. 对比 CommandHook 和 AgentHook 的适用场景

**考察点：** 选型对比分析
**类型：** 对比题
**难度：** L4（对比题）
**对应文档位置：** 四种 Hook 类型

**问题：**
在设计一个安全审查 Hook 时，何时该用 CommandHook，何时该用 AgentHook？请从能力边界、延迟、适用场景三个维度对比。

**参考答案：**

| 维度 | CommandHook | AgentHook |
|------|-------------|-----------|
| **本质能力** | 执行预定义 shell 命令 | 调用 LLM 进行多步推理 |
| **判断方式** | 命令返回码（0 成功，非 0 失败） | 自然语言推理 + JSON 输出 |
| **超时时间** | 默认 30s，最长 600s | 默认 60s，最长 1200s |
| **语义理解** | ❌ 无法理解命令含义 | ✅ 可理解上下文和意图 |
| **配置复杂度** | 低（写命令） | 中（写 prompt） |
| **外部依赖** | 无 | 需要 API 调用 |

**典型场景对比：**

**✅ CommandHook 适合：**

| 场景 | 示例 |
|------|------|
| 文件是否存在 | `test -f sensitive.json && exit 1 || exit 0` |
| 文件路径匹配 | `echo "$ARGUMENTS" | grep -q "/prod/"` |
| 进程检查 | `pgrep -f "mysql" > /dev/null && exit 1` |
| 简单模式匹配 | 检查命令是否包含特定模式 |

**✅ AgentHook 适合：**

| 场景 | 示例 |
|------|------|
| 判断是否生产环境 | "分析这个命令是否会在生产环境执行" |
| 安全风险评估 | "这个文件修改是否可能导致数据泄露" |
| 多步推理 | "检查这个 SQL 是否有注入风险" |
| 语义判断 | "这个操作是否符合团队规范" |

**决策树：**

```
需要判断？
    │
    ├── 可以用正则/字符串匹配 → CommandHook
    │
    └── 需要语义理解/上下文 → AgentHook
            │
            ├── 单步简单判断 → PromptHook
            └── 多步复杂推理 → AgentHook
```

---

### Q9. 如何设计一个生产环境审计 Hook？

**考察点：** 系统设计能力
**类型：** 设计题
**难度：** L5（设计题）
**对应文档位置：** 完整执行流程

**问题：**
假设你需要为团队设计一个生产环境审计系统，要求：
1. 记录所有 PRE_TOOL_USE 和 POST_TOOL_USE 事件
2. 识别并阻断可疑的 production 操作
3. 异步发送审计日志到外部 SIEM 系统
4. 支持查询历史审计记录

请设计这个 Hook 系统，包括配置示例和架构图。

**参考答案：**

**架构设计：**

```
┌─────────────────────────────────────────────────────────────────┐
│                        OpenHarness Agent                        │
│                                                                 │
│  用户执行命令                                                     │
│       │                                                         │
│       ▼                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              HookExecutor (PRE_TOOL_USE)                │    │
│  │                                                         │    │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │    │
│  │  │ Matcher     │  │ Production  │  │ Audit       │    │    │
│  │  │ Filter      │→ │ Detector    │→ │ Logger      │    │    │
│  │  │ (glob)      │  │ (AgentHook) │  │ (HttpHook)  │    │    │
│  │  └─────────────┘  └─────────────┘  └─────────────┘    │    │
│  └─────────────────────────────────────────────────────────┘    │
│       │                    │                    │               │
│       │ 阻断               │ 识别               │ 异步发送       │
│       ▼                    ▼                    ▼               │
│  ┌──────────┐      ┌──────────────┐    ┌──────────────┐     │
│  │ Tool     │      │ Block if      │    │ SIEM         │     │
│  │ Blocked  │      │ prod detected │    │ (HTTP POST)  │     │
│  └──────────┘      └──────────────┘    └──────────────┘     │
│                                                    │            │
└────────────────────────────────────────────────────────────│────┘
                                                             │
                                                             ▼
                                                    ┌──────────────┐
                                                    │ Elasticsearch │
                                                    │ / Splunk      │
                                                    └──────────────┘
```

**配置实现：**

```json
{
  "hooks": {
    "pre_tool_use": [
      {
        "type": "agent",
        "prompt": "分析以下工具调用是否针对生产环境：\n$ARGUMENTS\n\n生产环境特征包括：\n- 目标为 production/prod 环境\n- 涉及核心数据库\n- 高风险操作（delete, drop, truncate）\n\n返回 JSON：{\"ok\": true/false, \"reason\": \"...\", \"severity\": \"low/medium/high\"}",
        "matcher": "bash",
        "block_on_failure": true,
        "timeout_seconds": 60
      },
      {
        "type": "http",
        "url": "https://audit.company.com/api/v1/hooks/log",
        "headers": {"Authorization": "Bearer $AUDIT_TOKEN", "X-Hook-Source": "openharness"},
        "matcher": "*",
        "block_on_failure": false,
        "timeout_seconds": 10
      }
    ],
    "post_tool_use": [
      {
        "type": "http",
        "url": "https://audit.company.com/api/v1/hooks/log",
        "headers": {"Authorization": "Bearer $AUDIT_TOKEN"},
        "matcher": "*",
        "block_on_failure": false,
        "timeout_seconds": 10
      }
    ]
  }
}
```

**审计日志格式：**

```json
{
  "event": "pre_tool_use",
  "timestamp": "2026-05-09T10:30:00Z",
  "agent_id": "agent_123",
  "tool_name": "bash",
  "tool_input": {
    "command": "kubectl delete pod --all -n production"
  },
  "detection": {
    "is_production": true,
    "severity": "high",
    "reason": "在 production namespace 执行删除操作"
  },
  "action": "blocked",
  "session_id": "sess_abc123"
}
```

**扩展设计：**

| 组件 | 实现方式 | 说明 |
|------|----------|------|
| **历史查询** | HttpHook → Audit DB | 存储到 Elasticsearch |
| **实时告警** | HttpHook → PagerDuty | 高 severity 触发告警 |
| **慢查询分析** | POST_TOOL_USE + 分析 | 识别异常模式 |
| **审计报表** | 定期汇总 | 统计高频操作、高风险时段 |

---

### Q10. Hooks 与 Skills/Tools/Prompts 的关系是什么？

**考察点：** 架构定位理解
**类型：** 对比题
**难度：** L4（对比题）
**对应文档位置：** 与 Skills/Tools/Prompts 的关系

**问题：**
OpenHarness 的四大扩展机制（Hooks、Skills、Tools、Prompts）各自的定位是什么？它们如何协同工作？请用架构图说明。

**参考答案：**

**四者定位对比：**

| 模块 | 职责 | 类比 | 触发方式 |
|------|------|------|----------|
| **Skills** | 提供知识（能做什么） | 知识库 | 按需加载 |
| **Tools** | 执行动作（能用什么） | 四肢 | 按需调用 |
| **Prompts** | 塑造响应（怎么说话） | 语气/人格 | 预定义 |
| **Hooks** | 自动化干预（何时触发） | 神经系统 | 事件驱动 |

**架构关系图：**

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户输入                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Prompts（塑造人格）                           │
│   - System Prompt                                               │
│   - Context Building                                            │
│   - Response Style                                              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Brain（LLM）                           │
│   - 决策推理                                                    │
│   - 工具选择                                                    │
│   - 响应生成                                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│   Tools（执行）   │ │   Skills（知识）  │ │   Hooks（干预）   │
│                  │ │                  │ │                  │
│ - bash           │ │ - 文档知识        │ │ - 事件触发        │
│ - read_file      │ │ - API 文档       │ │ - PRE_TOOL_USE   │
│ - write_file     │ │ - 最佳实践       │ │ - POST_TOOL_USE  │
│ - ...            │ │ - ...            │ │ - ...            │
└──────────────────┘ └──────────────────┘ └──────────────────┘
                              │               │
                              │               │
                              └───────┬───────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                      外部系统集成                                │
│   - Webhook（审计、告警）                                        │
│   - 文件系统（检查、日志）                                        │
│   - LLM API（语义判断）                                          │
└─────────────────────────────────────────────────────────────────┘
```

**协同工作示例：**

```
用户：帮我删掉生产数据库里的测试数据

1. Prompts 塑造角色：
   "你是一个谨慎的 DevOps 助手，删除操作需要二次确认"

2. Agent 决策（Skills 提供知识）：
   - Skills: "生产数据库删除是高危操作"
   - LLM 判断：这可能是危险操作

3. Hooks 干预（事件触发）：
   - PRE_TOOL_USE: AgentHook 检测到 production 关键字
   - 阻断并返回："检测到生产环境操作，已被阻断"

4. Tools 执行（如未被阻断）：
   - bash: 执行删除命令
   - POST_TOOL_USE: 记录审计日志
```

**本质区别：**

- **Skills/Tools/Prompts**：声明式定义，Agent 按需使用
- **Hooks**：事件驱动，在特定时机自动执行，无需 Agent 显式调用

---

## 学习建议

| 难度 | 建议 |
|------|------|
| **L1-L2** | 熟记 10 个事件名称和触发位置，理解四种 Hook 类型的特点和选型 |
| **L3** | 掌握 HookExecutor 执行流程、$ARGUMENTS 注入原理、Hot Reload 设计 |
| **L4-L5** | 能对比分析不同方案的 trade-off，能设计完整的 Hook 系统解决方案 |
