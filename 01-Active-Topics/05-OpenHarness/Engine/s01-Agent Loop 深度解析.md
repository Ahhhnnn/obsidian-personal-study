# Agent Loop 深度解析

## 概览

OpenHarness 的 Agent Loop 是整个系统的心脏。它的职责是：接收用户输入 → 调用模型 → 执行工具 → 把结果喂回模型 → 循环，直到模型不再请求工具为止。

整个实现分两层：

```
QueryEngine (query_engine.py)     ← 高层封装，持有对话历史
    └── run_query() (query.py)    ← 核心循环，无状态的异步生成器
```

`QueryEngine` 是有状态的对象，管理 `messages` 历史和各种配置。`run_query` 是纯粹的循环逻辑，接收消息列表，`yield` 事件流。

---

## 入口：QueryEngine.submit_message

```python
# query_engine.py:147
async def submit_message(self, prompt: str | ConversationMessage) -> AsyncIterator[StreamEvent]:
```

调用链：

```
用户输入
  → submit_message()
      → remember_user_goal()          # 记录用户目标到 tool_metadata
      → hook: USER_PROMPT_SUBMIT      # 触发 hook
      → 构建 QueryContext             # 打包所有运行时依赖
      → run_query(context, messages)  # 进入核心循环
          → yield StreamEvent         # 事件流式返回给调用方
```

`QueryContext` 是一个 dataclass，把所有运行时依赖打包在一起传给 `run_query`：

```python
@dataclass
class QueryContext:
    api_client: SupportsStreamingMessages   # 模型 API 客户端
    tool_registry: ToolRegistry             # 已注册的工具集合
    permission_checker: PermissionChecker   # 权限检查器
    cwd: Path                               # 工作目录
    model: str                              # 模型 ID
    system_prompt: str                      # 系统提示词
    max_tokens: int                         # 单次最大输出 token
    max_turns: int | None = 200             # 最大 agentic 轮次
    hook_executor: HookExecutor | None      # Hook 执行器
    tool_metadata: dict | None              # 跨轮次状态（carryover）
    ...
```

---

## 核心循环：run_query

```python
# query.py:455
async def run_query(
    context: QueryContext,
    messages: list[ConversationMessage],
) -> AsyncIterator[tuple[StreamEvent, UsageSnapshot | None]]:
```

这是一个 `async generator`，每次 `yield` 一个 `(StreamEvent, UsageSnapshot)` 元组。

### 主循环结构

```python
turn_count = 0
while context.max_turns is None or turn_count < context.max_turns:
    turn_count += 1

    # 1. Auto-compact 检查
    async for event, usage in _stream_compaction(trigger="auto"):
        yield event, usage

    # 2. 调用模型 API（流式）
    async for event in context.api_client.stream_message(...):
        if isinstance(event, ApiTextDeltaEvent):
            yield AssistantTextDelta(text=event.text), None
        if isinstance(event, ApiMessageCompleteEvent):
            final_message = event.message

    # 3. 把模型回复追加到历史
    messages.append(final_message)
    yield AssistantTurnComplete(message=final_message, usage=usage), usage

    # 4. 没有 tool_use → 触发 STOP hook，退出循环
    if not final_message.tool_uses:
        await context.hook_executor.execute(HookEvent.STOP, ...)
        return

    # 5. 执行工具（单个串行 / 多个并发）
    tool_results = await _execute_tools(context, final_message.tool_uses)

    # 6. 把工具结果作为 user 消息追加，进入下一轮
    messages.append(ConversationMessage(role="user", content=tool_results))
```

**关键设计**：工具结果以 `role="user"` 的消息追加回 `messages`，这是 Anthropic API 的协议要求——`tool_result` 必须放在 user turn 里。

### 并发工具执行

当模型一次返回多个 `tool_use` 时，OpenHarness 并发执行：

```python
if len(tool_calls) == 1:
    # 单个工具：串行，立即 yield 事件
    result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
else:
    # 多个工具：asyncio.gather 并发执行
    raw_results = await asyncio.gather(
        *[_run(tc) for tc in tool_calls],
        return_exceptions=True   # 单个失败不影响其他工具
    )
```

`return_exceptions=True` 是关键——如果某个工具抛异常，不会取消其他工具的执行。原因：Anthropic API 要求每个 `tool_use` 都必须有对应的 `tool_result`，如果有工具没有返回结果，下一次 API 请求会被拒绝。

---

## 工具执行：_execute_tool_call

```python
# query.py:662
async def _execute_tool_call(
    context: QueryContext,
    tool_name: str,
    tool_use_id: str,
    tool_input: dict[str, object],
) -> ToolResultBlock:
```

执行一个工具调用的完整流程：

```
pre_tool_use hook
    ↓
权限检查 (PermissionChecker.evaluate)
    ↓
输入校验 (Pydantic model_validate)
    ↓
tool.execute()
    ↓
_record_tool_carryover()   # 更新 tool_metadata 状态
    ↓
post_tool_use hook
    ↓
返回 ToolResultBlock
```

### 权限检查

```python
decision = context.permission_checker.evaluate(
    tool_name,
    is_read_only=tool.is_read_only(parsed_input),
    file_path=_file_path,
    command=_command,
)
```

`PermissionChecker` 按优先级依次检查：

1. **敏感路径硬拦截**：`~/.ssh/`、`~/.aws/credentials`、`~/.kube/config` 等，无论任何模式都拒绝
2. **工具黑名单** (`denied_tools`)
3. **工具白名单** (`allowed_tools`)
4. **路径规则** (glob 模式匹配)
5. **命令黑名单** (`denied_commands`)
6. **权限模式**：
   - `FULL_AUTO` → 全部放行
   - 只读工具 → 放行
   - `PLAN` 模式 → 阻止所有写操作
   - 默认 → 弹出确认提示

如果需要用户确认，会触发 `NOTIFICATION` hook，然后调用 `permission_prompt` 回调等待用户响应。

### Hook 集成点

`_execute_tool_call` 内有两个 hook 触发点：

| Hook | 时机 | 可以做什么 |
|------|------|-----------|
| `PRE_TOOL_USE` | 工具执行前 | 可以 block 工具（返回 `blocked=True`） |
| `POST_TOOL_USE` | 工具执行后 | 审计、通知、副作用 |

`PRE_TOOL_USE` 如果返回 blocked，工具不会执行，直接返回错误 `ToolResultBlock`。

---

## tool_metadata：跨轮次状态

`tool_metadata` 是一个 `dict`，在整个 session 生命周期内持续存在，用于在多轮工具调用之间传递上下文。

每次工具执行完成后，`_record_tool_carryover` 会更新这个 dict：

```python
# 记录读过的文件（最近 6 个）
read_file_state: list[{path, span, preview, timestamp}]

# 记录调用过的 skill（最近 8 个）
invoked_skills: list[str]

# 记录异步 agent 任务状态
async_agent_tasks: list[{agent_id, task_id, description, status}]

# 任务焦点状态（目标、活跃文件、已验证工作）
task_focus_state: {
    goal: str,
    recent_goals: list[str],
    active_artifacts: list[str],
    verified_state: list[str],
    next_step: str,
}

# 最近工作日志（最近 10 条）
recent_work_log: list[str]
```

这些状态会被注入到 `ToolExecutionContext.metadata` 里，工具实现可以读取它们。系统提示词的动态部分（`build_runtime_system_prompt`）也会读取这些状态，让模型在每轮都能感知到"我最近做了什么"。

---

## Auto-Compact：上下文压缩

每轮循环开始前，`run_query` 都会检查是否需要压缩对话历史：

```python
async for event, usage in _stream_compaction(trigger="auto"):
    yield event, usage
messages, was_compacted = last_compaction_result
```

压缩有两种触发方式：

| 触发方式       | 时机                          | 策略                              |
| ---------- | --------------------------- | ------------------------------- |
| `auto`     | 每轮开始前，token 超过阈值            | 先 microcompact，不够再 full compact |
| `reactive` | API 返回 "prompt too long" 错误 | 强制 full compact，然后重试            |

**Microcompact**：清除旧的 `tool_result` 内容（替换为 `[Old tool result content cleared]`），成本低，不调用 LLM。

**Full compact**：调用 LLM 对旧消息生成结构化摘要，替换掉原始消息，大幅压缩 token。

压缩过程通过 `CompactProgressEvent` 流式上报进度，调用方可以实时展示给用户。

---

## Stream Events：事件流架构

`run_query` 是一个 async generator，所有输出都通过 `yield StreamEvent` 传递。调用方（TUI、CLI、API server）消费这个事件流来驱动 UI 更新：

```python
StreamEvent = (
    AssistantTextDelta        # 模型流式输出的文字片段
    | AssistantTurnComplete   # 一轮模型回复完成（含 usage）
    | ToolExecutionStarted    # 工具开始执行
    | ToolExecutionCompleted  # 工具执行完成（含输出）
    | ErrorEvent              # 错误（可恢复 / 不可恢复）
    | StatusEvent             # 系统状态消息（如"正在压缩..."）
    | CompactProgressEvent    # 压缩进度
)
```

这个设计让 engine 层完全与 UI 层解耦——engine 只管 yield 事件，不关心谁在消费。

---

## 完整数据流图

```
用户输入
    │
    ▼
QueryEngine.submit_message()
    │  记录 user goal 到 tool_metadata
    │  触发 USER_PROMPT_SUBMIT hook
    │
    ▼
run_query(context, messages)
    │
    ├─[每轮开始]─ Auto-compact 检查
    │                 │
    │                 ├─ token < 阈值 → 跳过
    │                 └─ token ≥ 阈值 → microcompact / full compact
    │
    ├─ stream_message(ApiMessageRequest)
    │       │
    │       ├─ yield AssistantTextDelta (流式文字)
    │       └─ ApiMessageCompleteEvent → final_message
    │
    ├─ messages.append(final_message)
    ├─ yield AssistantTurnComplete
    │
    ├─[无 tool_use]─ STOP hook → return
    │
    └─[有 tool_use]─ 执行工具
            │
            ├─ PRE_TOOL_USE hook（可 block）
            ├─ PermissionChecker.evaluate()
            ├─ tool.execute()
            ├─ _record_tool_carryover() → 更新 tool_metadata
            ├─ POST_TOOL_USE hook
            │
            ├─ messages.append(tool_results as user message)
            └─ 进入下一轮 ↑
```

---

## 关键设计决策

**1. 无状态的 run_query**
`run_query` 本身不持有状态，所有状态（messages、tool_metadata）由调用方传入。这使得它可以被 `QueryEngine.submit_message` 和 `QueryEngine.continue_pending` 复用，也方便测试。

**2. 工具结果作为 user 消息**
这是 Anthropic API 的协议约束，不是设计选择。`tool_result` 必须在 `user` turn 里，且每个 `tool_use` 都必须有对应的 `tool_result`，否则 API 报错。

**3. 并发工具 + return_exceptions**
多工具并发执行时用 `return_exceptions=True`，确保单个工具失败不会导致其他工具的结果丢失，从而避免 API 协议违规。

**4. tool_metadata 作为跨轮次记忆**
不依赖外部存储，用一个 dict 在内存中维护 session 级别的上下文。系统提示词动态注入这些状态，让模型在每轮都有"工作记忆"。
