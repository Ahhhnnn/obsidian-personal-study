# OpenHarness 项目详解

## 简介

**OpenHarness** 是由香港大学数据科学实验室 (HKUDS) 开发的核心轻量级 AI Agent 基础设施，定位为 **Claude Code 的开源替代方案**。

> **核心理念**: "The model is the agent. The code is the harness."
> 模型提供智能，harness 提供双手、眼睛、记忆和安全边界。

### 主要产品

| 产品                     | 说明                                                                |
| ---------------------- | ----------------------------------------------------------------- |
| **OpenHarness** (`oh`) | 核心基础设施：工具系统、Skills 加载、Memory、权限控制、多 Agent 协调                      |
| **ohmo**               | 基于 OpenHarness 的个人 AI Agent，通过飞书/Slack/Telegram/Discord 等 IM 渠道接入 |

### 技术栈

**完全手写 Agent Loop，不使用 LangChain。** 只使用底层 SDK：

```toml
# 核心 AI API 调用
anthropic>=0.40.0    # Claude SDK
openai>=1.0.0        # OpenAI SDK (兼容 API)

# 数据验证
pydantic>=2.0.0      # 工具输入模型验证

# HTTP / WebSocket
httpx>=0.27.0
websockets>=12.0

# MCP 协议
mcp>=1.0.0           # Model Context Protocol

# TUI / CLI 界面
rich>=13.0.0
prompt-toolkit>=3.0.0
textual>=0.80.0
typer>=0.12.0

# IM 渠道集成
slack-sdk>=3.0.0
python-telegram-bot>=21.0.0
discord.py>=2.0.0
lark-oapi>=1.5.0
```

---

## 核心架构（10 大子系统）

```
openharness/
  engine/          # 🧠 Agent Loop — query → stream → tool-call → loop
  tools/           # 🔧 43 Tools — file I/O, shell, search, web, MCP
  skills/          # 📚 Knowledge — on-demand skill loading (.md files)
  plugins/         # 🔌 Extensions — commands, hooks, agents, MCP servers
  permissions/     # 🛡️ Safety — multi-level modes, path rules, command deny
  hooks/           # ⚡ Lifecycle — PreToolUse/PostToolUse event hooks
  commands/        # 💬 54 Commands — /help, /commit, /plan, /resume, ...
  mcp/             # 🌐 MCP — Model Context Protocol client
  memory/          # 🧠 Memory — persistent cross-session knowledge
  tasks/           # 📋 Tasks — background task management
  coordinator/     # 🤝 Multi-Agent — subagent spawning, team coordination
  prompts/         # 📝 Context — system prompt assembly, CLAUDE.md, skills
  config/          # ⚙️ Settings — multi-layer config, migrations
  ui/              # 🖥️ React TUI — backend protocol + frontend
```

---

## Agent Loop 核心机制

> *"一个循环 + 工具调用 = 最小可行智能体"* -- while + tool_use 就是全部

### 要解决的问题

Agent 需要持续与模型交互：发请求 → 拿响应 → 判断是否需要工具 → 执行工具 → 继续发请求。这个循环本身不难，但需要处理：流式输出、并行工具、权限检查、Hook 生命周期、错误恢复、自动压缩、token 计数……

### 核心流程

```
while 模型请求工具:
    执行工具 → 返回结果
    追加到消息历史
    继续循环

没有工具请求 → 结束本次交互
```

核心文件位于 `src/openharness/engine/`：`query_engine.py` 提供高层接口管理 conversation history，`query.py` 实现核心循环 `run_query()`。

详见：[[01-Agent Loop 核心实现]]

## System Prompt 组装

> *"Context 会填满，你需要按需组装"* -- 不是一股脑塞进去

### 要解决的问题

Agent 需要多种上下文信息：角色定义、环境信息、可用技能、项目规则、历史记忆……如果全部硬编码塞进 system prompt，不仅 token 浪费，修改也不灵活。

### 组装架构

运行时 system prompt 由 `build_runtime_system_prompt()` 逐段拼接：

| 层级 | 来源 | 说明 |
|------|------|------|
| 1 | Base System Prompt | 角色定义 + 环境信息 |
| 2 | Fast Mode / Reasoning Settings | 运行时配置 |
| 3 | Skills Registry | 可用技能列表 |
| 4 | Delegation Section | 子 agent 使用说明 |
| 5 | CLAUDE.md | 项目级指令（自动向上搜索） |
| 6 | Local Rules | 本地环境规则 |
| 7 | Project Context | issue、PR comments 等 |
| 8 | Memory | MEMORY.md + 相关记忆搜索 |

详见：[[02-System Prompt 组装机制]]

## 工具系统（43+）

| 类别 | 工具 | 说明 |
|------|------|------|
| **文件 I/O** | Bash, Read, Write, Edit, Glob, Grep | 核心文件操作 |
| **搜索** | WebFetch, WebSearch, ToolSearch, LSP | Web 和代码搜索 |
| **笔记本** | NotebookEdit | Jupyter notebook 编辑 |
| **Agent** | Agent, SendMessage, TeamCreate/Delete | 子 agent 派生与协调 |
| **任务** | TaskCreate/Get/List/Update/Stop/Output | 后台任务管理 |
| **MCP** | MCPTool, ListMcpResources, ReadMcpResource | MCP 集成 |
| **模式** | EnterPlanMode, ExitPlanMode, Worktree | 工作流模式切换 |
| **定时** | CronCreate/List/Delete, RemoteTrigger | 定时和远程执行 |
| **元** | Skill, Config, Brief, Sleep, AskUser | 知识加载、配置、交互 |

### 工具基类

```python
class BaseTool:
    name: str
    description: str
    input_model: type[BaseModel]

    async def execute(
        self,
        arguments: BaseModel,
        context: ToolExecutionContext,
    ) -> ToolResult:
        ...

    def is_read_only(self, arguments: BaseModel) -> bool:
        return False
```

---

## Skills 系统

### 两层注入架构

```
System prompt (Layer 1 -- always present):
+----------------------------------+
| Skills available:                |
|   - pdf: Process PDF files...    |  ~100 tokens/skill
|   - code-review: Review code...  |
+----------------------------------+

When model calls load_skill("pdf"):
+----------------------------------+
| tool_result (Layer 2 -- on demand):
|   Full PDF processing guide...   |  ~2000 tokens
+----------------------------------+
```

**第一层**：系统提示中只放 Skill 名称和简短描述。
**第二层**：模型通过 `load_skill` 工具按需获取完整内容。

### 兼容 anthropics/skills

Skill 文件格式：

```markdown
---
name: commit
description: Create clean, well-structured git commits
---

# Commit Skill

## When to use
Use when the user asks to commit changes...

## Workflow
1. Review staged changes
2. Write concise commit message
...
```

---

## 权限控制

### 三级权限模式

| 模式 | 行为 | 适用场景 |
|------|------|----------|
| **Default** | 写入/执行前询问 | 日常开发 |
| **Auto** | 允许所有操作 | 沙箱环境 |
| **Plan Mode** | 阻止所有写入 | 大型重构、审查优先 |

### 路径规则

```json
{
  "permission": {
    "mode": "default",
    "path_rules": [
      {"pattern": "/etc/*", "allow": false},
      {"pattern": "~/.ssh/*", "allow": false}
    ],
    "denied_commands": ["rm -rf /", "DROP TABLE *"]
  }
}
```

---

## Hook 系统

### 事件类型

| 事件 | 时机 |
|------|------|
| `USER_PROMPT_SUBMIT` | 用户提交 prompt |
| `PRE_TOOL_USE` | 工具执行前 |
| `POST_TOOL_USE` | 工具执行后 |
| `NOTIFICATION` | 通知事件 |
| `STOP` | 循环结束 |

### Hook 退出码

| 退出码 | 效果 |
|-------|------|
| 0 | 观察后放行 |
| 1 | 阻止操作 |

---

## Memory 系统

### 持久化组件

| 组件 | 说明 |
|------|------|
| **CLAUDE.md Discovery** | 自动发现和注入项目说明 |
| **MEMORY.md** | 持久记忆（跨会话） |
| **Session Resume** | 会话恢复 |
| **Auto-Compaction** | 自动压缩上下文 |

### Auto-Compaction

上下文快满时触发压缩，分两种策略：

1. **Microcompact（快速）**：清除旧 tool result 内容
2. **Full LLM Summarization（彻底）**：用模型生成摘要

---

## Provider 兼容性

### 支持的后端

| 类型 | 典型后端 |
|------|---------|
| **Anthropic-Compatible** | Claude 官方、Moonshot/Kimi、Zhipu/GLM、MiniMax |
| **OpenAI-Compatible** | OpenAI、OpenRouter、DashScope、DeepSeek、GitHub Models、SiliconFlow、Gemini、Groq、Ollama |
| **订阅桥接** | Claude Subscription、Codex Subscription、GitHub Copilot |

---

## 快速开始

```bash
# 安装
curl -fsSL https://raw.githubusercontent.com/HKUDS/OpenHarness/main/scripts/install.sh | bash

# 配置
oh setup    # 交互式向导选择 provider 并认证

# 运行
oh                              # 交互模式
oh -p "Explain this codebase"   # 单次 prompt
oh --dry-run                    # 安全预览（不执行）

# ohmo 个人 Agent
ohmo init             # 初始化
ohmo config           # 配置渠道
ohmo gateway start    # 启动网关
```

---

## 测试覆盖

| 测试套件 | 测试数 | 状态 |
|----------|--------|------|
| 单元 + 集成测试 | 114 | ✅ 全部通过 |
| CLI Flags E2E | 6 | ✅ 真实模型调用 |
| Harness Features E2E | 9 | ✅ 重试、技能、并行、权限 |
| React TUI E2E | 3 | ✅ 欢迎、对话、状态 |
| TUI 交互 E2E | 4 | ✅ 命令、权限、快捷键 |
| 真实 Skills + Plugins | 12 | ✅ anthropics/skills + claude-code/plugins |

---

## 扩展方式

### 自定义工具

```python
from pydantic import BaseModel, Field
from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult

class MyToolInput(BaseModel):
    query: str = Field(description="Search query")

class MyTool(BaseTool):
    name = "my_tool"
    description = "Does something useful"
    input_model = MyToolInput

    async def execute(self, arguments: MyToolInput, context: ToolExecutionContext) -> ToolResult:
        return ToolResult(output=f"Result for: {arguments.query}")
```

### 自定义 Skill

创建 `~/.openharness/skills/my-skill.md`：

```markdown
---
name: my-skill
description: Expert guidance for my specific domain
---

# My Skill

## When to use
Use when the user asks about [your domain].

## Workflow
1. Step one
2. Step two
...
```

### 自定义 Plugin

创建 `.openharness/plugins/my-plugin/.claude-plugin/plugin.json`：

```json
{
  "name": "my-plugin",
  "version": "1.0.0",
  "description": "My custom plugin"
}
```

---

## 与 Claude Code 的关系

OpenHarness 是 Claude Code 的 Python 开源实现：

| 方面 | Claude Code | OpenHarness |
|------|-------------|------------|
| 语言 | TypeScript | Python |
| 许可证 | 专有 | MIT |
| 源码 | 闭源 | 开源 |
| 核心架构 | ✅ | ✅ 完全复用 |
| 工具生态 | ✅ | ✅ 兼容 |
| Plugin 生态 | ✅ | ✅ 兼容 |
| Skills 格式 | ✅ | ✅ 兼容 |
	
---

## 资源链接

- **GitHub**: https://github.com/HKUDS/OpenHarness
- **文档**: https://github.com/HKUDS/OpenHarness#readme
- **版本**: v0.1.7
