# s05: Skill 加载 - 两层按需知识注入机制分析

> *"用到什么知识，临时加载什么知识"* -- 不塞 system prompt，通过 tool_result 按需注入

## 问题背景

Agent 需要遵循特定领域的工作流：git 约定、测试模式、代码审查清单、PDF 处理……如果全部塞进系统提示，10 个 Skill 每个 2000 token 就是 20,000 token，大部分跟当前任务毫无关系。

### Token 浪费示例

| 方案 | Token 消耗 | 问题 |
|-----|-----------|------|
| 10 个 Skill 全量注入 system prompt | ~20,000 | 大部分与当前任务无关 |
| 只放名称，按需加载 | ~1,000 (元数据) + ~2,000 (按需) | 精准、高效 |

## 两层注入架构

```
System prompt (Layer 1 -- always present):
+--------------------------------------+
| You are a coding agent.              |
| Skills available:                    |
|   - pdf: Process PDF files...        |  ~100 tokens/skill
|   - code-review: Review code...      |
|   - agent-builder: Build agents...   |
|   - mcp-builder: Build MCP servers.. |
+--------------------------------------+

When model calls load_skill("pdf"):
+--------------------------------------+
| tool_result (Layer 2 -- on demand):  |
| <skill name="pdf">                   |
|   Full PDF processing instructions   |  ~2000 tokens
|   Step 1: ...                        |
|   Step 2: ...                        |
| </skill>                             |
+--------------------------------------+
```

第一层：系统提示中只放 Skill 名称和简短描述。第二层：模型通过 `load_skill` 工具按需获取完整内容。

## 核心实现

### 1. Skill 文件组织

每个 Skill 是一个目录，包含 `SKILL.md` 文件，使用 YAML frontmatter：

```
skills/
  pdf/
    SKILL.md
  code-review/
    SKILL.md
  agent-builder/
    SKILL.md
  mcp-builder/
    SKILL.md
```

一个典型的 SKILL.md 文件（以 code-review 为例）：

```yaml
---
name: code-review
description: Perform thorough code reviews with security, performance,
             and maintainability analysis.
---

# Code Review Skill

You now have expertise in conducting comprehensive code reviews.

## Review Checklist
### 1. Security (Critical)
- Injection vulnerabilities
- Authentication issues
...
```

frontmatter 提供**元数据**（Layer 1 用），正文提供**完整知识**（Layer 2 用）。

### 2. SkillLoader - 扫描与解析

```python
class SkillLoader:
    def __init__(self, skills_dir: Path):
        self.skills_dir = skills_dir
        self.skills = {}
        self._load_all()

    def _load_all(self):
        if not self.skills_dir.exists():
            return
        for f in sorted(self.skills_dir.rglob("SKILL.md")):
            text = f.read_text()
            meta, body = self._parse_frontmatter(text)
            name = meta.get("name", f.parent.name)
            self.skills[name] = {"meta": meta, "body": body, "path": str(f)}
```

设计要点：
- 递归扫描：`rglob("SKILL.md")` 支持嵌套目录结构
- 排序：`sorted()` 确保加载顺序稳定可预测
- 降级处理：frontmatter 中没有 `name` 则用目录名

### 3. Frontmatter 解析

```python
def _parse_frontmatter(self, text: str) -> tuple:
    match = re.match(r"^---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    if not match:
        return {}, text
    try:
        meta = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, match.group(2).strip()
```

- 正则 `re.DOTALL` 让 `.` 匹配换行，支持多行 frontmatter
- `yaml.safe_load` 安全解析，避免任意代码执行
- 解析失败时降级：返回空 meta + 原始文本

### 4. Layer 1：系统提示中的元数据

```python
def get_descriptions(self) -> str:
    if not self.skills:
        return "(no skills available)"
    lines = []
    for name, skill in self.skills.items():
        desc = skill["meta"].get("description", "No description")
        tags = skill["meta"].get("tags", "")
        line = f"  - {name}: {desc}"
        if tags:
            line += f" [{tags}]"
        lines.append(line)
    return "\n".join(lines)
```

注入到系统提示：

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
Use load_skill to access specialized knowledge before tackling unfamiliar topics.

Skills available:
{SKILL_LOADER.get_descriptions()}"""
```

### 5. Layer 2：tool_result 中的完整内容

```python
def get_content(self, name: str) -> str:
    skill = self.skills.get(name)
    if not skill:
        return f"Error: Unknown skill '{name}'. Available: {', '.join(self.skills.keys())}"
    return f"<skill name=\"{name}\">\n{skill['body']}\n</skill>"
```

工具注册：

```python
TOOL_HANDLERS = {
    "load_skill": lambda **kw: SKILL_LOADER.get_content(kw["name"]),
}

TOOLS = [
    {"name": "load_skill",
     "description": "Load specialized knowledge by name.",
     "input_schema": {
         "type": "object",
         "properties": {"name": {"type": "string", "description": "Skill name to load"}},
         "required": ["name"]
     }},
]
```

## 工作流程全貌

```
用户: "帮我 review 一下这段代码"
    |
    v
[模型看到 Layer 1]
  Skills available:
    - pdf: Process PDF files...
    - code-review: Review code...      ← 识别到相关 Skill
    - agent-builder: Build agents...
    |
    v
[模型调用 load_skill("code-review")]
    |
    v
[tool_result 返回完整 code-review 知识]
  <skill name="code-review">
    # Code Review Skill
    ## Review Checklist
    ...
  </skill>
    |
    v
[模型按照 checklist 执行审查]
```

## 几个值得注意的问题

### 问题 1：Skill 与系统提示的边界

| 内容 | 放在哪 | 为什么 |
|-----|-------|-------|
| Agent 角色定义 | 系统提示 | 始终需要 |
| 通用工具使用说明 | 系统提示 | 每次都用 |
| PDF 处理工作流 | Skill | 按需使用 |
| 代码审查 checklist | Skill | 按需使用 |
| Git 约定 | 看情况 | 高频可放提示，低频放 Skill |

### 问题 2：模型会不会跳过加载直接回答？

模型有时会跳过 `load_skill`，直接凭已有知识回答，质量可能差一截。

系统提示里加一句引导就行：

```python
SYSTEM = f"""You are a coding agent at {WORKDIR}.
IMPORTANT: Before tackling any task, check if a relevant skill is available.
Use load_skill to access specialized knowledge.

Skills available:
{SKILL_LOADER.get_descriptions()}"""
```

或者给 `load_skill` 的 description 加提示：

```python
{"name": "load_skill",
 "description": "Load specialized knowledge by name. ALWAYS load relevant skills before attempting unfamiliar tasks.",
 ...}
```

### 问题 3：加载的 Skill 会占用上下文窗口

每次 `load_skill` 返回的内容（可能 2000+ token）会留在消息历史中。频繁加载多个 Skill，上下文增长很快。

| 方案 | 实现 | 优点 | 缺点 |
|-----|------|------|------|
| 限制单次加载数量 | 系统提示约束 | 简单 | 可能不够灵活 |
| Skill 互斥 | 加载新的同时卸载旧的 | 控制总量 | 可能需要同时用多个 |
| 结合 s06 压缩 | micro_compact 压缩旧 Skill | 自动化 | 可能丢掉还需要的内容 |
| 精简 Skill 内容 | 只保留关键步骤 | Token 少 | 信息可能不够 |

### 问题 4：Skill 的动态发现

当前实现靠目录扫描，Skill 是静态的。运行时动态添加也不难：

```python
class SkillLoader:
    def reload(self):
        self.skills = {}
        self._load_all()

    def register(self, name: str, meta: dict, body: str):
        self.skills[name] = {"meta": meta, "body": body}
```

## Token 消耗对比

| 场景 | 全量注入 | 两层加载 | 节省 |
|-----|---------|---------|------|
| 4 个 Skill，只用 1 个 | ~8000 | ~3000 | 62.5% |
| 10 个 Skill，只用 1 个 | ~20000 | ~3000 | 85% |
| 4 个 Skill，全部用到 | ~8000 | ~9000 | -12.5% |

Skill 数量越多、单次使用越少，收益越大。

## 相对 s04 的变更

| 组件 | 之前 (s04) | 之后 (s05) |
|------|-----------|-----------|
| Tools | 5 (基础 + task) | 5 (基础 + load_skill) |
| 系统提示 | 静态字符串 | + Skill 描述列表 |
| 知识库 | 无 | skills/\*/SKILL.md 文件 |
| 注入方式 | 无 | 两层（系统提示 + tool_result） |

## 实际 Skill 示例

### pdf/SKILL.md

```yaml
---
name: pdf
description: Process PDF files - extract text, create PDFs, merge documents.
---
```

- 完整的 PDF 工作流：读取、创建、合并、拆分
- 包含多种方案（bash 命令行 vs Python 库）
- 附带依赖安装表和最佳实践

### code-review/SKILL.md

```yaml
---
name: code-review
description: Perform thorough code reviews with security, performance,
             and maintainability analysis.
---
```

- 结构化 checklist：安全 > 正确性 > 性能 > 可维护性 > 测试
- 包含反模式代码示例（Python/JS）
- 定义标准输出格式

## 总结

### 两层加载的本质

| 层级 | 内容 | Token 成本 | 注入方式 |
|-----|------|-----------|---------|
| Layer 1 (元数据) | name + description | ~100/skill | 系统提示（常驻） |
| Layer 2 (完整知识) | 工作流、checklist、示例 | ~2000/skill | tool_result（按需） |

### 设计要点

- 按需加载，不预加载用不到的知识
- 元数据常驻系统提示，让模型知道有哪些可用
- frontmatter 分离元数据和内容，结构清晰
- `yaml.safe_load` 安全解析，`name` 缺失时用目录名兜底

### 写在最后

> 两层加载的收益跟 Skill 使用率成反比。

> 每个 SKILL.md 是一个独立的知识模块，添加新能力只需创建目录和文件，不用改核心代码。跟插件系统的思路一样。
