# OpenHarness Prompt 系统深度解析

## 1. 概述

OpenHarness 的 Prompt 系统采用分层架构，从底层到顶层包含：环境检测层 → 基础 Prompt 层 → 项目指令层 → 运行时组装层。这种设计可以根据项目、用户、任务动态构建系统提示词，而不是套用一个固定模板。

---

## 2. 环境检测层：上下文感知的基础

### 2.1 为什么需要环境检测？

AI 编码助手必须知道自己在哪里、周围有什么。环境检测层负责收集：

- **操作系统信息**：Linux/macOS/Windows，不同平台命令不同
- **Python 环境**：版本、虚拟环境、项目依赖
- **Git 状态**：当前分支、仓库状态
- **Shell 类型**：影响命令语法和行为

### 2.2 EnvironmentInfo 数据结构

```python
@dataclass
class EnvironmentInfo:
    os_name: str              # 操作系统名称
    os_version: str           # 系统版本
    platform_machine: str     # 架构 (x86_64, arm64)
    shell: str                # 用户 shell (bash, zsh)
    cwd: str                  # 当前工作目录
    home_dir: str             # 用户主目录
    date: str                 # 当前日期
    python_version: str       # Python 版本
    python_executable: str    # Python 可执行文件路径
    virtual_env: str | None   # 虚拟环境路径
    is_git_repo: bool         # 是否在 git 仓库中
    git_branch: str | None    # 当前 git 分支
    hostname: str             # 主机名
    extra: dict[str, str]     # 扩展字段
```

### 2.3 关键检测逻辑

#### OS 检测：跨平台兼容性

```python
def detect_os() -> tuple[str, str]:
    if platform.system() == "Linux":
        return "Linux", distro.name(pretty=True)  # 需要 distro 库
    elif platform.system() == "Darwin":
        version = platform.mac_ver()[0]
        return "macOS", version
    elif platform.system() == "Windows":
        return "Windows", platform.version()
```

#### Git 状态：5 秒超时保护

```python
def detect_git_info() -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, timeout=5  # 5秒超时，防止阻塞
        )
        if result.returncode == 0:
            return True, result.stdout.decode().strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return False, None
```

注意这个 5 秒超时设计——网络驱动器或大型仓库里 Git 命令可能很慢，超时机制防止整个系统被卡住。

#### 虚拟环境检测：多层检测策略

```python
def detect_virtual_env() -> str | None:
    # 策略1：检查 VIRTUAL_ENV 环境变量
    if venv := os.environ.get("VIRTUAL_ENV"):
        return venv

    # 策略2：检查 pyvenv.cfg（Python 3.3+ 原生虚拟环境）
    pyvenv_cfg = Path(cwd) / "pyvenv.cfg"
    if pyvenv_cfg.exists():
        return str(cwd)

    return None
```

---

## 3. 基础 Prompt 层：AI 的行为准则

### 3.1 系统身份定义

```markdown
You are OpenHarness, an open-source AI coding assistant CLI.
You are an interactive agent that helps users with software engineering tasks.
Use the instructions below and the tools available to you to assist the user.
```

三句话定义了身份、开源 CLI 工具，以及工作方式：基于指令和工具协作。

### 3.2 安全边界：最重要的指令

```markdown
IMPORTANT: You must NEVER generate or guess URLs for the user unless you are confident that the URLs are for helping the user with programming. You may use URLs provided by the user in their messages or local files.
```

这条指令背后有一个重要的安全考量：**防止钓鱼攻击**。恶意用户可能通过对话注入虚假 URL，AI 如果不加甄别地转发可能危害用户安全。OpenHarness 明确禁止生成 URL，除非确信其目的。

### 3.3 工具使用哲学：能用专用工具就不用 shell

```markdown
# Using your tools
 - Do NOT use Bash to run commands when a relevant dedicated tool is provided:
   - Read files: use read_file instead of cat/head/tail
   - Edit files: use edit_file instead of sed/awk
   - Write files: use write_file instead of echo/heredoc
   - Search files: use glob instead of find/ls
   - Search content: use grep instead of grep/rg
   - Reserve Bash exclusively for system commands that require shell execution.
```

| 专用工具 | Bash | 优势 |
| --- | --- | --- |
| read_file | cat/head/tail | 语义清晰，不会误用参数 |
| edit_file | sed/awk | 精确替换，不会意外修改其他内容 |
| glob | find/ls | 跨平台兼容，模式匹配更直观 |
| grep | grep/rg | 一致的接口，避免混淆 |

### 3.4 代码质量观：克制与精准

```markdown
 - Don't add features, refactor code, or make "improvements" beyond what was asked.
   A bug fix doesn't need surrounding code cleaned up.
 - Don't add error handling, fallbacks, or validation for scenarios that can't happen.
   Trust internal code and framework guarantees. Only validate at system boundaries.
 - Don't create helpers, utilities, or abstractions for one-time operations.
   Three similar lines of code is better than a premature abstraction.
```

三个原则：用户要什么就给什么，不要画蛇添足；信任内部代码，但只在系统边界验证；重复代码在短期内比错误抽象更好维护。

### 3.5 风险操作警告

```markdown
# Executing actions with care
Carefully consider the reversibility and blast radius of actions. Freely take local, reversible actions like editing files or running tests. For hard-to-reverse actions, check with the user first.

Examples of risky actions requiring confirmation:
- Destructive operations: deleting files/branches, dropping tables, rm -rf
- Hard-to-reverse: force-pushing, git reset --hard, amending published commits
- Shared state: pushing code, creating/commenting on PRs/issues, sending messages
```

这部分的粒度非常细，甚至列出了具体的危险命令（`rm -rf`、`git reset --hard`），让 AI 能够识别并主动确认。

---

## 4. 项目指令层：让 AI 理解你的项目

### 4.1 CLAUDE.md 的发现策略

OpenHarness 支持从当前目录向上遍历，查找项目级自定义指令：

```
当前目录/CLAUDE.md                      ← 优先级最高
当前目录/.claude/CLAUDE.md
当前目录/.claude/rules/*.md             ← 多个规则文件
向上遍历直到根目录
```

- **CLAUDE.md**：项目根目录标准位置，适合放整体项目规范
- **.claude/rules/*.md**：支持规则拆分，便于维护
- **向上遍历**：支持 monorepo 结构，子目录也可以有自己的规则

### 4.2 内容加载格式

```markdown
# Project Instructions

## /path/to/CLAUDE.md
```md
[文件内容，最多 12000 字符]
```

## /path/to/.claude/rules/coding-style.md
```md
[文件内容]
```
```

使用 markdown 代码块包裹，便于 AI 区分项目指令和框架指令。

### 4.3 实际应用场景

假设项目根目录有 `CLAUDE.md`：

```markdown
# This Project

## Tech Stack
- Python 3.11+
- FastAPI for API
- React + TypeScript for frontend

## Code Style
- Use async/await, never callbacks
- Type hints required on all function signatures
- 100 line max per file

## Testing
- Write tests BEFORE committing
- Coverage must be above 80%
```

当开发者进入这个项目并请求 AI 帮助时，AI 会：
1. 检测到项目有 CLAUDE.md
2. 加载其内容并注入系统提示词
3. 遵循项目特定的编码规范

---

## 5. 运行时组装层：智能组合

### 5.1 核心函数：`build_runtime_system_prompt()`

这是整个系统最核心的函数，它的职责是**整合所有组件，生成最终的系统提示词**。

**输入参数**：

```python
def build_runtime_system_prompt(
    settings: Settings,              # 用户配置（fast_mode、effort、passes、memory等）
    cwd: str | Path,                 # 当前工作目录
    latest_user_prompt: str | None,  # 用户最新输入（用于记忆检索）
    extra_skill_dirs,                # 额外技能目录
    extra_plugin_roots,              # 额外插件根目录
) -> str:
```

### 5.2 分层组装流程

```
┌────────────────────────────────────────────┐
│ 1. 基础 Prompt 或协调器 Prompt              │
├────────────────────────────────────────────┤
│ 2. 会话模式标记（Fast Mode）                │
├────────────────────────────────────────────┤
│ 3. 推理设置（Effort + Passes）              │
├────────────────────────────────────────────┤
│ 4. 可用技能列表                             │
├────────────────────────────────────────────┤
│ 5. 委托说明（子代理使用指南）                │
├────────────────────────────────────────────┤
│ 6. 项目指令（CLAUDE.md）                    │
├────────────────────────────────────────────┤
│ 7. 本地环境规则                             │
├────────────────────────────────────────────┤
│ 8. 上下文文件（Issue、PR评论、活跃仓库）      │
├────────────────────────────────────────────┤
│ 9. 记忆系统（MEMORY.md + 相关记忆）          │
└────────────────────────────────────────────┘
                          ↓
              最终系统提示词（各层用 \n\n 连接）
```

### 5.3 协调器模式

```python
if is_coordinator_mode():
    sections = [get_coordinator_system_prompt()]
else:
    sections = [build_system_prompt(custom_prompt=settings.system_prompt, cwd=str(cwd))]
```

这是多代理架构的设计：协调器管理整体任务，分发给子代理；工作者执行具体子任务。

### 5.4 动态推理设置

```python
sections.append(
    "# Reasoning Settings\n"
    f"- Effort: {settings.effort}\n"
    f"- Passes: {settings.passes}\n"
)
```

用户可以通过 `effort` 和 `passes` 控制 AI 的思考深度：
- **effort**：低/中/高，决定单次推理的深度
- **passes**：迭代次数，决定反思和修正的轮数

这使得同一套系统可以适应简单问答和复杂代码重构两种场景。

### 5.5 技能系统

```markdown
# Available Skills

The following skills are available via the `skill` tool. When a user's request matches a skill, invoke it with `skill(name="<skill_name>")` to load detailed instructions before proceeding.

- **commit**: Create well-formatted commits with conventional commit messages
- **pr-merge**: Merge GitHub PRs while maximizing contributor attribution
- **harness-eval**: Test the harness with real LLM calls
- **architecture-diagram**: Create professional architecture diagrams as HTML files
- **frontend-design**: Create distinctive, production-grade frontend interfaces
```

技能系统是一种**按需加载的专业知识**：
- 预定义技能（commit、pr-merge 等）在系统提示词中列出
- 当用户请求匹配某个技能时，AI 使用 `skill()` 工具加载详细指令
- 支持用户自定义技能目录（`extra_skill_dirs`）

### 5.6 记忆系统：让 AI 记住重要的事

OpenHarness 的记忆系统采用**两层结构**：

#### 第一层：入口点（MEMORY.md）

```markdown
# Memory

See `/path/to/project/.claude/memory/MEMORY.md` for the memory index.
```

入口点始终加载，它告诉 AI 记忆索引在哪里。

#### 第二层：相关记忆（动态检索）

```python
if latest_user_prompt:
    relevant = find_relevant_memories(
        latest_user_prompt,
        cwd,
        max_results=settings.memory.max_files,
    )
```

基于用户最新的输入，动态检索相关的记忆文件。

**记忆文件示例**：

```markdown
---
name: User coding preferences
description: User prefers functional programming style and TypeScript
type: user
---

The user is a senior TypeScript developer who prefers:
- Functional programming patterns
- Immutable data structures
- Explicit type annotations
```

索引加检索的两层结构，避免每次都加载所有记忆。记忆文件用 YAML front matter 定义元数据（name、description、type），支持按类型过滤。

---

## 6. 关键设计亮点

### 6.1 分层解耦

每一层都可以独立使用和测试：

```python
# 单独获取环境信息
env = get_environment_info(cwd="/path/to/project")

# 单独获取基础 prompt
base_prompt = get_base_system_prompt()

# 单独加载项目指令
project_prompt = load_claude_md_prompt(cwd)
```

### 6.2 可扩展性

```python
def build_runtime_system_prompt(
    ...
    extra_skill_dirs,     # 用户可以添加自定义技能目录
    extra_plugin_roots,  # 用户可以添加插件
):
```

用户可以通过配置添加额外的技能和插件，满足定制化需求。

### 6.3 容错设计

```python
# Git 命令超时
result = subprocess.run(
    ["git", "rev-parse", "--abbrev-ref", "HEAD"],
    capture_output=True, timeout=5
)

# 文件读取保护
content = path.read_text(errors="replace")[:12000]

# 存在性检查
if path.exists():
    content = path.read_text()
```

### 6.4 智能截断

```python
# 单文件最大 12000 字符
content = path.read_text()[:12000]

# 记忆文件每个最大 8000 字符
entry_content = entry.read_text()[:8000]
```

防止单个大文件撑爆上下文窗口。

### 6.5 模式感知

```python
if settings.fast_mode:
    sections.append("# Session Mode\nFast mode is enabled...")

if is_coordinator_mode():
    sections = [get_coordinator_system_prompt()]
```

系统根据配置和模式动态调整提示词内容。

---

## 7. 完整数据流示意

```
用户: "帮我修复登录 bug"
                    ↓
    ┌───────────────────────────────────┐
    │  build_runtime_system_prompt()    │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 1. EnvironmentInfo (环境检测)      │
    │    - OS: macOS 14.0               │
    │    - Python: 3.11.5               │
    │    - Git branch: main             │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 2. 基础 Prompt (身份+行为准则)     │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 3. 环境信息 Section                │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 4. 推理设置 (effort=medium)        │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 5. 可用技能 (commit, pr-merge...) │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 6. 项目指令 (CLAUDE.md)           │
    │    - TypeScript 项目              │
    │    - 需要写测试                   │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 7. 上下文文件                      │
    │    - Issue #123: 登录按钮不工作    │
    └───────────────────────────────────┘
                    ↓
    ┌───────────────────────────────────┐
    │ 8. 记忆系统                        │
    │    - 检索相关: 用户偏好测试风格    │
    │    - 相关记忆: 不要 mock 数据库    │
    └───────────────────────────────────┘
                    ↓
         ┌─────────────────────┐
         │  完整的系统提示词    │
         └─────────────────────┘
                    ↓
              发送给 LLM
                    ↓
    ┌───────────────────────────────────┐
    │ LLM: "我将帮你修复登录 bug..."     │
    └───────────────────────────────────┘
```

---

## 8. 与传统 AI 助手的对比

| 维度    | 传统 AI 助手 | OpenHarness        |
| ----- | -------- | ------------------ |
| 系统提示词 | 固定不变     | 动态组装               |
| 环境感知  | 无        | 自动检测 OS、Python、Git |
| 项目规范  | 需要用户每次描述 | 自动加载 CLAUDE.md     |
| 工具使用  | 倾向用 Bash | 专用工具优先             |
| 记忆能力  | 无        | 两层记忆系统             |
| 推理控制  | 固定       | 用户可调 effort/passes |
| 技能扩展  | 无        | 技能注册表 + 按需加载       |

---

## 9. 总结

OpenHarness 的 Prompt 系统分为四层：

1. **环境检测层**提供了上下文感知的基础
2. **基础 Prompt 层**定义了 AI 的身份、行为准则和工具哲学
3. **项目指令层**实现了项目级的定制化
4. **运行时组装层**将所有组件智能组合，生成最终的系统提示词

关键设计理念：
- **专用工具优先**：减少 shell 误用风险
- **克制与精准**：不做多余的事，避免过早抽象
- **动态组合**：根据配置和场景自动调整
- **记忆系统**：让 AI 能够"记住"重要的上下文

这些设计使得 OpenHarness 能够像经验丰富的开发者一样，理解项目、遵循规范、使用正确的工具、处理复杂的任务。

---

## 参考文件

- `src/openharness/prompts/environment.py` - 环境检测
- `src/openharness/prompts/system_prompt.py` - 基础 Prompt 构建
- `src/openharness/prompts/claudemd.py` - 项目指令加载
- `src/openharness/prompts/context.py` - 运行时组装

---

*本文档基于 OpenHarness 源代码分析撰写*