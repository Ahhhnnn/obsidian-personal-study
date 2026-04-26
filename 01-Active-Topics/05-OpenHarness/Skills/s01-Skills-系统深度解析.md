# OpenHarness Skills 系统深度解析

## 概览

OpenHarness 的 Skills 系统是整个 Agent 基础设施中最接近 Claude Code 体验的部分。它的核心职责是：按需加载专家级知识指南，让模型在执行特定任务时获得详细的工作流程和决策建议。

Skills 系统采用**两层注入架构**：

```
System Prompt (Layer 1 — 始终存在):
+----------------------------------+
| Skills available:                |
|   - commit: Create clean commits  |  ~100 tokens/skill
|   - review: Review code changes   |
+----------------------------------+

SkillTool 调用 (Layer 2 — 按需加载):
+----------------------------------+
| tool_result:                     |
|   Full commit workflow guide...   |  ~2000 tokens
+----------------------------------+
```

**第一层**：系统提示词中只列出 Skill 的名称和简短描述（~100 tokens/skill）。

**第二层**：当用户请求匹配某个 Skill 时，模型通过 `skill(name="...")` 工具按需获取完整内容（~2000 tokens）。

系统提示词保持简洁，需要时又能加载详细专业知识。

---

## 核心文件结构

```
openharness/skills/
├── __init__.py          # 懒加载模块导出
├── types.py             # SkillDefinition 数据模型
├── registry.py          # SkillRegistry 注册表
├── loader.py            # 核心加载逻辑
└── bundled/
    ├── __init__.py      # 内置 skill 加载
    └── content/         # 内置 skill 文件 (*.md)
        ├── commit.md
        ├── debug.md
        ├── diagnose.md
        ├── plan.md
        ├── review.md
        ├── simplify.md
        └── test.md
```

---

## 数据模型

### SkillDefinition

`types.py` 的 SkillDefinition 数据结构：

```python
# src/openharness/skills/types.py

@dataclass(frozen=True)
class SkillDefinition:
    """A loaded skill."""

    name: str           # 唯一标识符
    description: str   # 简短描述（用于系统提示词列出）
    content: str       # 完整 markdown 内容
    source: str        # 来源：bundled | user | plugin
    path: str | None   # 文件路径（调试用）
```

`frozen=True` 的 dataclass 意味着 Skill 定义不可变，多线程/异步环境中不会被意外修改。

---

## 注册机制：SkillRegistry

`registry.py` 是一个内存注册表：

```python
# src/openharness/skills/registry.py

class SkillRegistry:
    """Store loaded skills by name."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillDefinition] = {}

    def register(self, skill: SkillDefinition) -> None:
        """Register one skill."""
        self._skills[skill.name] = skill  # key 唯一，后者覆盖前者

    def get(self, name: str) -> SkillDefinition | None:
        """Return a skill by name."""
        return self._skills.get(name)

    def list_skills(self) -> list[SkillDefinition]:
        """Return all skills sorted by name."""
        return sorted(self._skills.values(), key=lambda skill: skill.name)
```

覆盖规则：同名 Skill，后注册的覆盖先注册的。plugin skills 可以 override bundled skills。

---

## 加载流程：load_skill_registry

`loader.py` 按优先级从 4 个来源加载 Skill：

```python
# src/openharness/skills/loader.py

def load_skill_registry(
    cwd: str | Path | None = None,
    *,
    extra_skill_dirs: Iterable[str | Path] | None = None,
    extra_plugin_roots: Iterable[str | Path] | None = None,
    settings=None,
) -> SkillRegistry:
    """Load bundled and user-defined skills."""
    registry = SkillRegistry()

    # 优先级从低到高
    for skill in get_bundled_skills():
        registry.register(skill)          # 1. bundled (内置)
    for skill in load_user_skills():
        registry.register(skill)          # 2. user (~/.config/openharness/skills/)
    for skill in load_skills_from_dirs(extra_skill_dirs):
        registry.register(skill)          # 3. extra_skill_dirs
    if cwd is not None:
        from openharness.plugins.loader import load_plugins
        resolved_settings = settings or load_settings()
        for plugin in load_plugins(resolved_settings, cwd, extra_roots=extra_plugin_roots):
            if not plugin.enabled:
                continue
            for skill in plugin.skills:
                registry.register(skill)   # 4. plugin skills (最高优先级)

    return registry
```

### 优先级总结

| 优先级 | 来源 | 路径 |
|------|------|------|
| 1 (最低) | bundled | `openharness/skills/bundled/content/*.md` |
| 2 | user | `~/.config/openharness/skills/<name>/SKILL.md` |
| 3 | extra_skill_dirs | 用户指定目录 |
| 4 (最高) | plugin | `<plugin>/skills/<name>/SKILL.md` |

---

## 四层加载来源详解

### 1. Bundled Skills（内置）

```python
# src/openharness/skills/bundled/__init__.py

_CONTENT_DIR = Path(__file__).parent / "content"

def get_bundled_skills() -> list[SkillDefinition]:
    """Load all bundled skills from the content/ directory."""
    skills: list[SkillDefinition] = []
    for path in sorted(_CONTENT_DIR.glob("*.md")):
        content = path.read_text(encoding="utf-8")
        name, description = _parse_frontmatter(path.stem, content)
        skills.append(SkillDefinition(name=name, description=description,
                                     content=content, source="bundled", path=str(path)))
    return skills
```

内置 Skill 文件直接以文件名（去掉 `.md`）作为默认 name，读取后解析 frontmatter。

### 2. User Skills（用户自定义）

```python
def get_user_skills_dir() -> Path:
    """Return the user skills directory."""
    path = get_config_dir() / "skills"
    path.mkdir(parents=True, exist_ok=True)
    return path

def load_user_skills() -> list[SkillDefinition]:
    """Load markdown skills from the user config directory."""
    return load_skills_from_dirs([get_user_skills_dir()], source="user")
```

布局要求：`~/.config/openharness/skills/<name>/SKILL.md`

### 3. 目录结构解析（load_skills_from_dirs）

```python
def load_skills_from_dirs(
    directories: Iterable[str | Path] | None,
    *,
    source: str = "user",
) -> list[SkillDefinition]:
    """Load markdown skills from one or more directories.

    Supported layout:
    - ``<root>/<skill-dir>/SKILL.md``
    """
    skills: list[SkillDefinition] = []
    if not directories:
        return skills
    seen: set[Path] = set()
    for directory in directories:
        root = Path(directory).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        candidates: list[Path] = []
        for child in sorted(root.iterdir()):
            if child.is_dir():
                skill_path = child / "SKILL.md"
                if skill_path.exists():
                    candidates.append(skill_path)
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            content = path.read_text(encoding="utf-8")
            default_name = path.parent.name
            name, description = _parse_skill_markdown(default_name, content)
            skills.append(SkillDefinition(...))
    return skills
```

### 4. Plugin Skills（插件扩展）

插件扩展是 Skills 系统的重要扩展方式。`LoadedPlugin` 的数据结构中包含 `skills` 字段：

```python
# src/openharness/plugins/types.py

@dataclass(frozen=True)
class LoadedPlugin:
    manifest: PluginManifest
    path: Path
    enabled: bool
    skills: list[SkillDefinition] = field(default_factory=list)
    commands: list[PluginCommandDefinition] = field(default_factory=list)
    agents: list[AgentDefinition] = field(default_factory=list)
    hooks: dict[str, list] = field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = field(default_factory=dict)
```

Plugin 的 Skill 加载逻辑在 `plugins/loader.py` 的 `_load_plugin_skills`：

```python
def _load_plugin_skills(path: Path) -> list[SkillDefinition]:
    """Load plugin skills using Claude Code's directory SKILL.md layout."""
    if not path.exists():
        return []
    skills: list[SkillDefinition] = []
    direct_skill = path / "SKILL.md"
    if direct_skill.exists():
        # 情况A: <plugin>/skills/SKILL.md → name = 目录名
        content = direct_skill.read_text(encoding="utf-8")
        name, description = _parse_skill_markdown(path.name, content)
        skills.append(SkillDefinition(name=name, description=description, ...))
        return skills
    # 情况B: <plugin>/skills/<name>/SKILL.md → name = 子目录名
    for child in sorted(path.iterdir()):
        if not child.is_dir():
            continue
        skill_path = child / "SKILL.md"
        if not skill_path.exists():
            continue
        content = skill_path.read_text(encoding="utf-8")
        name, description = _parse_skill_markdown(child.name, content)
        skills.append(SkillDefinition(...))
    return skills
```

两种插件 Skill 布局：

```
# 布局A: 单个 skill（目录名作为 name）
my-plugin/
└── skills/
    └── SKILL.md         → name = "my-plugin"

# 布局B: 多个 skills（Claude Code 标准 SKILL.md 布局）
my-plugin/
└── skills/
    ├── commit/
    │   └── SKILL.md     → name = "commit"
    └── diagnose/
        └── SKILL.md     → name = "diagnose"
```

---

## Skill 文件格式解析

### YAML Frontmatter（优先）

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
2. Draft concise commit message
...
```

### Fallback 解析

没有 YAML frontmatter 时，fallback 到 heading + 首段落解析：

```python
def _parse_skill_markdown(default_name: str, content: str) -> tuple[str, str]:
    name = default_name
    description = ""

    lines = content.splitlines()

    # 尝试 YAML frontmatter
    if content.startswith("---\n"):
        end_index = content.find("\n---\n", 4)
        if end_index != -1:
            try:
                metadata = yaml.safe_load(content[4:end_index])
                if isinstance(metadata, dict):
                    name = metadata.get("name", default_name)
                    description = metadata.get("description", "")
            except yaml.YAMLError:
                pass

    # Fallback: 第一个 # heading 作为 name
    if not name or name == default_name:
        for line in lines:
            if stripped.startswith("# "):
                name = stripped[2:].strip() or default_name
                break

    # Fallback: 首段非注释文本作为 description
    if not description:
        for line in lines:
            if stripped and not stripped.startswith("---") and not stripped.startswith("#"):
                description = stripped[:200]
                break

    return name, description or f"Skill: {name}"
```

---

## Skill 使用方式

### 1. SkillTool（LLM 按需调用）

```python
# src/openharness/tools/skill_tool.py

class SkillTool(BaseTool):
    """Return the content of a loaded skill."""

    name = "skill"
    description = "Read a bundled, user, or plugin skill by name."
    input_model = SkillToolInput

    async def execute(self, arguments: SkillToolInput, context: ToolExecutionContext) -> ToolResult:
        registry = load_skill_registry(
            context.cwd,
            extra_skill_dirs=context.metadata.get("extra_skill_dirs"),
            extra_plugin_roots=context.metadata.get("extra_plugin_roots"),
        )
        # 大小写不敏感 fallback
        skill = (registry.get(arguments.name)
                 or registry.get(arguments.name.lower())
                 or registry.get(arguments.name.title()))
        if skill is None:
            return ToolResult(output=f"Skill not found: {arguments.name}", is_error=True)
        return ToolResult(output=skill.content)
```

模型在系统提示词中收到指引：

> *"When a user's request matches a skill, invoke it with `skill(name=\"<skill_name>\")` to load detailed instructions before proceeding."*

### 2. 系统提示词注入

`prompts/context.py` 中的 `_build_skills_section()` 在每次构建系统提示词时列出所有可用 Skill：

```python
def _build_skills_section(...) -> str | None:
    registry = load_skill_registry(cwd, extra_skill_dirs=extra_skill_dirs,
                                   extra_plugin_roots=extra_plugin_roots, settings=settings)
    skills = registry.list_skills()
    if not skills:
        return None
    lines = [
        "# Available Skills",
        "",
        "The following skills are available via the `skill` tool. "
        "When a user's request matches a skill, invoke it with `skill(name=\"<skill_name>\")` "
        "to load detailed instructions before proceeding.",
        "",
    ]
    for skill in skills:
        lines.append(f"- **{skill.name}**: {skill.description}")
    return "\n".join(lines)
```

### 3. CLI 命令

`/skills` 命令（`commands/registry.py`）允许用户直接查看 Skill：

```python
async def _skills_handler(args: str, context: CommandContext) -> CommandResult:
    skill_registry = load_skill_registry(
        context.cwd,
        extra_skill_dirs=context.extra_skill_dirs,
        extra_plugin_roots=context.extra_plugin_roots,
    )
    if args:
        skill = skill_registry.get(args)
        if skill is None:
            return CommandResult(message=f"Skill not found: {args}")
        return CommandResult(message=skill.content)
    skills = skill_registry.list_skills()
    lines = ["Available skills:"]
    for skill in skills:
        source = f" [{skill.source}]"
        lines.append(f"- {skill.name}{source}: {skill.description}")
    return CommandResult(message="\n".join(lines))
```

---

## 完整数据流

```
用户启动 OpenHarness
    │
    ▼
build_runtime_system_prompt()
    │  extra_skill_dirs / extra_plugin_roots 传入
    ▼
load_skill_registry(cwd, extra_skill_dirs, extra_plugin_roots)
    │
    ├── 1. get_bundled_skills()
    │       → 扫描 bundled/content/*.md
    │       → 注册 commit, debug, diagnose, plan, review, simplify, test
    │
    ├── 2. load_user_skills()
    │       → 扫描 ~/.config/openharness/skills/*/SKILL.md
    │       → 注册用户自定义 skills
    │
    ├── 3. load_skills_from_dirs(extra_skill_dirs)
    │       → 扫描用户指定目录下的 SKILL.md
    │
    └── 4. load_plugins()
            → discover_plugin_paths()  扫描插件目录
            → load_plugin(path)         加载单个插件
            │     └─ _load_plugin_skills()
            │             └─ 扫描 <plugin>/skills/*/SKILL.md
            │
            └─ for plugin in plugins:
                    if plugin.enabled:
                        for skill in plugin.skills:
                            registry.register(skill)
                                    │
                                    ▼
                    SkillRegistry._skills {name: SkillDefinition}
                                    │
                    ┌────────────────┴────────────────┐
                    ▼                                 ▼
        list_skills()                           get(name)
                    │                                 │
                    ▼                                 ▼
        注入系统提示词 # Available Skills    SkillTool.execute()
```

---

## 关键设计决策

### 1. 不可变数据模型

`frozen=True` 的 dataclass 意味着 Skill 定义不可变，多线程/异步环境中不会被意外修改。这也表明"这是输入数据，不是内部状态"。

### 2. 懒加载模块

```python
# src/openharness/skills/__init__.py

def __getattr__(name: str):
    if name in {"get_user_skills_dir", "load_skill_registry"}:
        from openharness.skills.loader import ...
    if name == "SkillRegistry":
        from openharness.skills.registry import SkillRegistry
        return SkillRegistry
    ...
```

`__getattr__` 实现模块级懒加载，import 时不立即加载 `yaml`、`pathlib` 等依赖，首次访问更快。

### 3. 双层解析 frontmatter/heading

优先用 YAML frontmatter 解析 name 和 description，失败时 fallback 到 heading + 首段落。有 frontmatter 时：精确控制 metadata；没有 frontmatter 时：用文件名和首段作为默认值。

### 4. 覆盖机制

按注册顺序，后者覆盖前者。用户可以覆盖 bundled skills（通过在 user skills 目录放置同名 skill），插件可以覆盖 bundled 和 user skills（plugin 优先级最高）。

### 5. SkillTool 只读设计

`SkillTool.is_read_only() = True`，只读操作，不会影响 LLM 的工具决策行为。

### 6. source 字段溯源

每个 Skill 都有 `source` 字段（bundled | user | plugin），调试时能快速知道 Skill 的来源。

---

## 自定义 Skill 开发指南

### 创建 User Skill

在 `~/.config/openharness/skills/` 下创建目录结构：

```
~/.config/openharness/skills/my-skill/
└── SKILL.md
```

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

## Rules
- Rule 1
- Rule 2
```

### 创建 Plugin Skill

在插件目录下创建 Skill：

```
~/.config/openharness/plugins/pdf-tools/
├── plugin.json
└── skills/
    └── pdf/
        └── SKILL.md
```

`plugin.json` 示例：

```json
{
  "name": "pdf-tools",
  "description": "PDF processing utilities",
  "enabled_by_default": true,
  "skills_dir": "skills"
}
```
