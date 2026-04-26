# Tools 系统深度解析

## 概览

OpenHarness 的 Tools 系统是 Agent 的"双手"。模型通过调用工具读写文件、执行命令、搜索代码、派生子 Agent——系统有 43+ 内置工具，支持通过 MCP 协议动态扩展。

整个工具系统的核心设计哲学是：**工具是纯异步的、上下文无关的、受权限系统管理的执行单元**。

```
src/openharness/tools/
├── base.py              # BaseTool 抽象基类 + ToolRegistry
├── bash_tool.py         # Shell 命令执行
├── file_read_tool.py    # 文件读取
├── file_write_tool.py   # 文件写入
├── file_edit_tool.py    # 文件编辑（字符串替换）
├── skill_tool.py        # Skill 加载
├── agent_tool.py        # 子 Agent 派生
├── send_message_tool.py # 向运行中的 Agent 发消息
├── mcp_tool.py          # MCP 工具适配器
└── ...                  # 共 43+ 工具
```

---

## 核心抽象

### BaseTool：工具的抽象基类

```python
# tools/base.py
class BaseTool(ABC):
    name: str                                    # 工具名称（API 调用标识）
    description: str                              # 供模型理解工具用途
    input_model: type[BaseModel]                  # Pydantic 参数模型

    @abstractmethod
    async def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> ToolResult:
        """执行工具，返回标准化结果"""

    def is_read_only(self, arguments: BaseModel) -> bool:
        """声明工具是否为只读（供权限检查用）"""
        return False

    def to_api_schema(self) -> dict[str, Any]:
        """生成 Anthropic Messages API 格式的 tool schema"""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_model.model_json_schema(),
        }
```

### 三个核心类型

| 类型                     | 职责                                | 所在文件      |
| ---------------------- | --------------------------------- | --------- |
| `BaseTool`             | 工具的抽象基类，定义接口                      | `base.py` |
| `ToolExecutionContext` | 执行上下文（cwd、metadata、hook_executor） | `base.py` |
| `ToolResult`           | 标准化返回值（output、is_error、metadata）  | `base.py` |
| `ToolRegistry`         | 工具的注册表（name → instance 映射）        | `base.py` |

每个工具通过 `input_model.model_json_schema()` 自动生成 API schema。Pydantic 的 Field description 同时用于参数验证、API 文档生成、模型提示——单一数据源。

```python
class FileReadToolInput(BaseModel):
    path: str = Field(description="Path of the file to read")
    offset: int = Field(default=0, ge=0, description="Zero-based starting line")
    limit: int = Field(default=200, ge=1, le=2000, description="Number of lines to return")
```

---

## 工具执行全流程

### 入口：QueryEngine → run_query → _execute_tool_call

```
用户输入
    │
    ▼
QueryEngine.submit_message()
    │
    ▼
run_query(context, messages)
    │
    ├─ api_client.stream_message() → final_message（含 tool_use blocks）
    │
    └─ _execute_tool_call(context, tool_name, tool_use_id, tool_input)
            │
            ├─ 1. PRE_TOOL_USE hook（可 block 工具执行）
            │
            ├─ 2. 权限检查 PermissionChecker.evaluate()
            │         │
            │         ├─ 敏感路径硬拦截（~/.ssh/*, ~/.aws/credentials, ...）
            │         ├─ denied/allowed_tools 黑白名单
            │         ├─ path_rules glob 规则
            │         ├─ denied_commands 模式
            │         └─ mode 策略（FULL_AUTO / PLAN / DEFAULT）
            │
            ├─ 3. 工具查找 context.tool_registry.get(tool_name)
            │
            ├─ 4. 输入验证 tool.input_model.model_validate(tool_input)
            │
            ├─ 5. 实际执行 await tool.execute(parsed_input, ToolExecutionContext)
            │
            ├─ 6. _record_tool_carryover() 更新 tool_metadata
            │
            ├─ 7. POST_TOOL_USE hook
            │
            └─ 8. 返回 ToolResultBlock(tool_use_id, content, is_error)
```

### 并发工具执行策略

```python
# query.py:606-654
if len(tool_calls) == 1:
    # 单工具：串行流式，立即 yield 事件（用户体验好）
    yield ToolExecutionStarted(tool_name=tc.name, tool_input=tc.input)
    result = await _execute_tool_call(context, tc.name, tc.id, tc.input)
    yield ToolExecutionCompleted(tool_name=tc.name, output=result.content, ...)

else:
    # 多工具：并发执行
    for tc in tool_calls:
        yield ToolExecutionStarted(...)  # 先发出所有 start 事件

    raw_results = await asyncio.gather(
        *[_execute_tool_call(context, tc.name, tc.id, tc.input) for tc in tool_calls],
        return_exceptions=True,  # 单个失败不影响其他工具
    )

    for tc, result in zip(tool_calls, raw_results):
        yield ToolExecutionCompleted(...)  # 再发出所有 complete 事件
```

`asyncio.gather` 是 Python 标准库 `asyncio` 中的并发工具，用于同时等待多个协程完成：

```python
results = await asyncio.gather(
    coroutine1(),
    coroutine2(),
    coroutine3(),
)
# results = [result1, result2, result3]
# 总耗时 = max(t1, t2, t3)，而非 t1 + t2 + t3
```

| 参数                       | 作用                          |
| ------------------------ | --------------------------- |
| `*coroutines`            | 要并发执行的协程列表                  |
| `return_exceptions=True` | 单个协程抛异常不取消其他协程，异常对象作为结果之一返回 |
|                          |                             |

`return_exceptions=True` 是必须的——Anthropic API 要求每个 `tool_use` 都必须有对应 result。如果某个工具抛异常但没有这个参数，`asyncio.gather` 会抛出 `CancelledError`，取消所有其他协程，导致部分工具无法返回结果，进而破坏会话状态。加上这个参数后，失败的工具返回 `Exception` 对象，代码将其转换为错误 `ToolResultBlock`。

---

## 权限系统

详见 [[03-Permissions 权限系统]]，这里只说明与工具的协作点。

`PermissionChecker.evaluate()` 在 `_execute_tool_call` 的第 2 步被调用：

```python
decision = context.permission_checker.evaluate(
    tool_name,
    is_read_only=tool.is_read_only(parsed_input),  # 工具自己声明
    file_path=_file_path,                           # 从工具输入中提取
    command=_command,                                # 从工具输入中提取
)
```

工具自己声明是否只读（`is_read_only()`），PermissionChecker 只做判断，不推断工具是否为写操作。

---

## tool_metadata Carryover 机制

`_record_tool_carryover()` 让 Engine 和工具互相传递信息。工具执行后，Engine 根据工具类型更新 `tool_metadata`：

| 工具 | 记录的 metadata |
|------|----------------|
| `read_file` | `read_file_state`（最近 6 个文件 + 行号范围） |
| `bash` | `recent_work_log`、`recent_verified_work` |
| `skill` | `invoked_skills`、`active_artifacts` |
| `agent` / `send_message` | `async_agent_tasks`（含 task_id/agent_id 映射） |
| `web_fetch` | `active_artifacts`（URL） |
| `web_search` / `grep` / `glob` | `recent_verified_work` |
| `enter_plan_mode` / `exit_plan_mode` | `permission_mode` 切换 |
| `enter_worktree` / `exit_worktree` | worktree 状态 |

这些状态通过 `ToolExecutionContext.metadata` 传递，最终注入 System Prompt，让模型感知"上下文历史"。

---

## MCP 工具适配器：插件扩展机制

```python
# tools/mcp_tool.py
class McpToolAdapter(BaseTool):
    def __init__(self, manager: McpClientManager, tool_info: McpToolInfo):
        self._manager = manager
        self._tool_info = tool_info
        # 名称格式: mcp__{server_name}__{tool_name}
        self.name = f"mcp__{sanitize(server)}__{sanitize(tool)}"
        self.description = tool_info.description
        # 动态从 MCP schema 构建 Pydantic input model
        self.input_model = _input_model_from_schema(tool_name, tool_info.input_schema)

    async def execute(self, arguments, context):
        output = await self._manager.call_tool(
            self._tool_info.server_name,
            self._tool_info.name,
            arguments.model_dump(mode="json"),
        )
        return ToolResult(output=output)
```

在 `create_default_tool_registry()` 中注册：

```python
if mcp_manager is not None:
    for tool_info in mcp_manager.list_tools():
        registry.register(McpToolAdapter(mcp_manager, tool_info))
```

外部 MCP 工具无需修改内置代码，通过适配器自动接入。名称空间隔离（`mcp__` 前缀）防止命名冲突。

---

## ToolRegistry：注册与查找

```python
# tools/base.py
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def to_api_schema(self) -> list[dict[str, Any]]:
        """生成所有工具的 API schema，一次性传给模型"""
        return [tool.to_api_schema() for tool in self._tools.values()]
```

`to_api_schema()` 在 `run_query()` 每次调用模型前生成 schema：

```python
async for event in context.api_client.stream_message(
    ApiMessageRequest(
        model=context.model,
        messages=messages,
        system_prompt=context.system_prompt,
        max_tokens=context.max_tokens,
        tools=context.tool_registry.to_api_schema(),  # ← 一次性传所有工具
    )
):
```

---

## 工具与 UI 的协作

UI 层（TUI / CLI / API Server）不直接调用工具，而是通过 `engine.submit_message()` 间接触发：

```
用户输入
    │
    ▼
handle_line(bundle, line)
    │
    ▼
engine.submit_message(line)
    │
    ▼
run_query() → _execute_tool_call("read_file", ...)
    │
    ▼
yield StreamEvent
  ├─ ToolExecutionStarted(...)
  ├─ ToolExecutionCompleted(...)
  └─ ...
    │
    ▼
render_event(event)  ← UI 渲染或 headless 输出
```

`StreamEvent` 让 Engine 与 UI 解耦，Engine 只管 yield 事件。

---

## 关键设计模式

| 模式                             | 体现                                                   |
| ------------------------------ | ---------------------------------------------------- |
| **Abstract Base Class**        | `BaseTool` 定义工具接口                                    |
| **Registry / Service Locator** | `ToolRegistry` 集中管理工具实例                              |
| **Adapter**                    | `McpToolAdapter` 将外部 MCP 工具适配为 BaseTool              |
| **Template Method**            | `BaseTool.execute()` 子类实现具体逻辑                        |
| **Strategy**                   | `PermissionChecker.evaluate()` 支持多种权限策略              |
| **Observer / Listener**        | `register_completion_listener()` 在 AgentTool 中实现异步通知 |
| **Defence in Depth**           | 敏感路径硬拦截，独立于 permission mode                            |

---

## 编写自定义工具

```python
from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

class MyToolInput(BaseModel):
    query: str = Field(description="Search query")
    limit: int = Field(default=10, ge=1, le=100)

class MyTool(BaseTool):
    name = "my_tool"
    description = "Search something useful"
    input_model = MyToolInput

    def is_read_only(self, arguments: MyToolInput) -> bool:
        return True  # 声明为只读，权限检查直接放行

    async def execute(self, arguments: MyToolInput, context: ToolExecutionContext) -> ToolResult:
        # context.cwd: 当前工作目录
        # context.metadata: 包含 ask_user_prompt、tool_registry 等
        # context.hook_executor: 可触发 hook

        result = await do_something(arguments.query, arguments.limit)

        return ToolResult(
            output=result,
            is_error=False,
            metadata={"custom": "extra info"},  # 可通过 metadata 向上传递信息
        )
```

注册到 `ToolRegistry`：

```python
registry.register(MyTool())
```

---

## 工具沙箱感知

`FileReadTool`、`FileWriteTool`、`FileEditTool` 等文件操作工具内置 Docker 沙箱检查：

```python
from openharness.sandbox.session import is_docker_sandbox_active

if is_docker_sandbox_active():
    allowed, reason = validate_sandbox_path(path, context.cwd)
    if not allowed:
        return ToolResult(output=f"Sandbox: {reason}", is_error=True)
```

每个工具自己负责自己的沙箱约束——这是**工具自治**的设计原则，不是 Engine 层统一处理。
