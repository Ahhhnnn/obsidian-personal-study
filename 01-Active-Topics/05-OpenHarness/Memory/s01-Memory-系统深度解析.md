# OpenHarness Memory 系统深度解析

## 概览

Memory 系统是 OpenHarness 的**持久化项目知识层**，让 AI Agent 在**跨会话**之间保留和检索项目上下文。与 Agent Loop 中的工作记忆（tool_metadata）不同，Memory 的设计目标是**持久存储**——模型重启后仍然知道项目的重要决策、团队约定和历史经验。

```
会话 A：用户告诉模型 "以后 Python 项目统一用 pytest"
    → 模型通过 /memory add 创建了一条记忆
    → 下次会话 B：用户说 "帮我写个测试"，模型从记忆中读到了 pytest 约定
```

Memory 系统采用**纯文件存储**架构，不依赖外部数据库。设计哲学是：**零网络依赖、零额外依赖、即时响应**。所有记忆以 Markdown 文件形式存在，支持 YAML frontmatter 元数据标注。

---

## 核心文件结构

```
src/openharness/memory/
├── __init__.py        # 公共导出（8 个 API）
├── types.py           # MemoryHeader 数据模型
├── paths.py           # 路径解析（最底层，零依赖）
├── scan.py            # 目录扫描 + frontmatter 解析
├── search.py          # 启发式 token 匹配搜索
├── manager.py         # CRUD 操作 + 并发安全
└── memdir.py          # System Prompt 片段生成
```

模块依赖图：

```
__init__.py   ── 统一导出
    │
paths.py      ── 零依赖（最底层）
    │
types.py      ── 零依赖（纯数据模型）
    │
scan.py       ──→ paths.py + types.py
search.py     ──→ scan.py + types.py
manager.py    ──→ paths.py + file_lock + fs
memdir.py     ──→ paths.py
```

依赖方向单一，无循环引用。

---

## 数据模型

### MemoryHeader

`types.py` 定义了记忆文件的元数据结构：

```python
@dataclass(frozen=True)
class MemoryHeader:
    path: Path                    # .md 文件的完整路径
    title: str                    # 记忆标题（frontmatter name 或文件名 stem）
    description: str              # 记忆摘要（frontmatter description 或首段内容）
    modified_at: float            # 文件修改时间戳（st_mtime）
    memory_type: str = ""         # frontmatter type 字段（预留）
    body_preview: str = ""        # 排除标题后的正文预览（≤300 字符）
```

**设计要点：**

- `frozen=True`：不可变 dataclass，作为只读数据传输对象（DTO）在模块间传递，避免意外修改
- `body_preview` 是预计算字段：在 `scan` 阶段一次 IO 提取，后续搜索打分不再需要开文件
- `modified_at` 用于同分排序：当 token 匹配分数相同时，优先返回最新修改的记忆
- `memory_type` 预留但未使用：可扩展为 `type: reference|pattern|context` 等分类体系

---

## 模块详解

### 1. paths.py — 存储路径策略

```python
def get_project_memory_dir(cwd: str | Path) -> Path:
    path = Path(cwd).resolve()
    digest = sha1(str(path).encode("utf-8")).hexdigest()[:12]
    return get_data_dir() / "memory" / f"{path.name}-{digest}"

def get_memory_entrypoint(cwd: str | Path) -> Path:
    return get_project_memory_dir(cwd) / "MEMORY.md"
```

**路径映射策略：**

```
项目路径: /Users/work/my-project
    │
    ▼ SHA1[:12] = "a3f2c8d1e5b9"
~/.openharness/data/memory/my-project-a3f2c8d1e5b9/
    ├── MEMORY.md              ← 索引文件（入口）
    ├── deploy_notes.md        ← 记忆文件 1
    ├── auth_patterns.md       ← 记忆文件 2
    └── ...
```

两个关键设计决策：

**① SHA1 哈希消歧同名项目。** 只用 `path.name` 无法区分 `/work/myapp` 和 `/personal/myapp`。SHA1 前 12 位 hex 将路径的全局唯一性内嵌到目录名中。密码学强度不需要——碰撞的唯一后果是两个不同项目共享记忆，概率在 12 hex chars 空间内 ≈ 1/16¹²，可忽略。

**② `resolve()` 消除符号链接和相对路径歧义。** `~/project` 和 `/Users/x/project` 被视为同一项目，避免软链接导致记忆目录重复创建。

### 2. scan.py — 目录扫描与 frontmatter 解析

这是整个模块中逻辑密度最高的文件，包含两个核心函数。

#### scan_memory_files

```python
def scan_memory_files(cwd, *, max_files=50) -> list[MemoryHeader]:
    memory_dir = get_project_memory_dir(cwd)
    headers = []
    for path in memory_dir.glob("*.md"):
        if path.name == "MEMORY.md":     # 跳过索引文件自身
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue                     # 容忍损坏文件，scan 不因此失败
        headers.append(_parse_memory_file(path, text))
    headers.sort(key=lambda h: h.modified_at, reverse=True)
    return headers[:max_files]
```

三个防御设计：

- **跳过 MEMORY.md**：索引文件不是记忆内容，不应参与搜索匹配
- **`except OSError: continue`**：一个损坏的 `.md` 不导致整个 scan 失败（覆盖 TOCTOU 场景）
- **max_files=50**：防御性上限，防止大量文件导致 IO 和内存爆炸

#### _parse_memory_file — 三层 fallback 解析

将 Markdown 文件内容转换为 MemoryHeader。解析链路：

```
文件内容
    │
    ▼ 第一层：YAML frontmatter ────────┐
    │ lines[0] == "---"                │ 否
    │ 找到第二个 "---" 界定范围        ▼
    │ 解析 key: value                  第二层：文件名 stem → title
    │   name → title                   第三层：首段非标题行 → description
    │   description → description
    │   type → memory_type
    └──────────────────────────────────┘
    │
    ▼ 构建 body_preview
    │ - 跳过 frontmatter 范围
    │ - 跳过标题行（# 开头）
    │ - 跳过已用作 description 的那行（避免重复）
    │ - 其余行用空格拼接，截断 300 字符
    │
    ▼ MemoryHeader(...)
```

**最精妙的设计：`desc_line_idx` 排除机制。**

```python
body_lines = [
    line.strip()
    for idx, line in enumerate(lines[body_start:], body_start)
    if line.strip()
    and not line.strip().startswith("#")
    and idx != desc_line_idx       # ← 关键：排除已用作 description 的行
]
```

如果 description 从 body 首段提取，这行就不应再进入 `body_preview`。否则同一文本在 metadata（2x 权重）和 body（1x 权重）中重复命中，导致评分虚高。排除后保证 token 命中只来自文件的不同区域。

**Frontmatter 解析的容错设计：**

```python
# 未闭合的 frontmatter（如 "---\nname: oops\nActual content"）
# 不会把 "---" 泄漏到 description 中
# 循环只找第一个完整 "---" ... "---" 块，找不到则完全跳过 frontmatter 解析
```

---

### 3. search.py — 启发式 token 匹配

#### find_relevant_memories

```python
def find_relevant_memories(query, cwd, *, max_results=5) -> list[MemoryHeader]:
    tokens = _tokenize(query)
    if not tokens:
        return []
    scored = []
    for header in scan_memory_files(cwd, max_files=100):
        meta = f"{header.title} {header.description}".lower()
        body = header.body_preview.lower()
        meta_hits = sum(1 for t in tokens if t in meta)
        body_hits = sum(1 for t in tokens if t in body)
        score = meta_hits * 2.0 + body_hits * 1.0
        if score > 0:
            scored.append((score, header))
    scored.sort(key=lambda item: (-item[0], -item[1].modified_at))
    return [header for _, header in scored[:max_results]]
```

#### _tokenize — 中英混合分词

```python
def _tokenize(text: str) -> set[str]:
    # ASCII: 单词 token，最小 3 字符（过滤 "a", "is", "to" 等无意义词）
    ascii_tokens = {t for t in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(t) >= 3}
    # CJK: 逐字 token（中文每个字都有独立语义，避免引入 jieba 等依赖）
    han_chars = set(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    return ascii_tokens | han_chars
```

#### 评分机制

| 匹配来源                    | 权重   | 原因            |
| ----------------------- | ---- | ------------- |
| `title` + `description` | ×2.0 | 用户刻意标注，语义浓缩度高 |
| `body_preview`          | ×1.0 | 自动提取，可能只是偶然提及 |

同分时按 `modified_at` 降序作为 tie-breaker。

#### 完整流程与评分细节

```
query 字符串
    │
    ▼
_tokenize(query)              ① 拆成 token 集合
    │
    ▼
scan_memory_files(cwd, max_files=100)   ② 获取所有记忆
    │
    ▼
对每个 MemoryHeader 打分：
  meta = f"{title} {description}".lower()
  body = body_preview.lower()

  meta_hits = sum(1 for t in tokens if t in meta)
  body_hits = sum(1 for t in tokens if t in body)
  score = meta_hits × 2.0 + body_hits × 1.0
    │
    ▼
过滤 score > 0 的项
    │
    ▼
按 (score↓, modified_at↓) 排序，取 top-N
```

#### 分词详解：`_tokenize`

```python
def _tokenize(text: str) -> set[str]:
    # ① ASCII 单词：3+ 字符，提取英文/数字/下划线组合
    ascii_tokens = {t for t in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(t) >= 3}
    # ② CJK 汉字：逐字符提取（中文每个字独立有义）
    han_chars = set(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    return ascii_tokens | han_chars
```

**ASCII 最小 3 字符的理由：** 过滤掉无意义的高频词（`"a"`, `"is"`, `"to"`, `"in"`, `"an"`），同时允许 `"fix"`, `"bug"`, `"api"` 等短而有义的词通过。2 字符会误判（`"db"`, `"io"`），3 是经验阈值。

**中文逐字不逐词的理由：** 中文分词引入 jieba 等额外依赖，且词边界模糊（"数据库"是一个词还是"数据"+"库"？）。逐字匹配效果可靠——"数据库迁移"→`{"数","据","库","迁","移"}`，与"数据库"→`{"数","据","库"}` 可共享 3 个字。

#### 评分示例

**场景：记忆目录有 3 个文件**

```
# deploy_notes.md
---
name: deploy-guide
description: Kubernetes deployment strategy
---
Use helm charts for production. Rolling update with maxSurge=1.

# testing_patterns.md
---
name: test-patterns
description: Pytest fixture patterns for Python projects
---
Use conftest.py for shared fixtures. Parametrize tests with @pytest.mark.parametrize.

# redis_cache.md
---
name: redis-cache
description: Redis cache invalidation strategy
---
Use cache-aside pattern. TTL 5 minutes. Delete keys on data update.
```

**用户输入：** `"deploy kubernetes"`

```
Step 1: _tokenize("deploy kubernetes")
→ ascii_tokens: {"deploy", "kubernetes"}
→ han_chars:   {}  (空)
→ tokens: {"deploy", "kubernetes"}
```

```
Step 2: 逐文件打分

文件 deploy_notes.md:
  meta = "deploy-guide kubernetes deployment strategy"
  body = "Use helm charts for production. Rolling update with maxSurge=1."
  命中: "deploy" 在 meta ✓, "kubernetes" 在 meta ✓
  → meta_hits = 2, body_hits = 0
  → score = 2 × 2.0 + 0 = 4.0

文件 testing_patterns.md:
  meta = "test-patterns pytest fixture patterns for Python projects"
  body = "Use conftest.py for shared fixtures. Parametrize tests..."
  命中: 无
  → meta_hits = 0, body_hits = 0
  → score = 0 (过滤)

文件 redis_cache.md:
  meta = "redis-cache redis cache invalidation strategy"
  body = "Use cache-aside pattern. TTL 5 minutes. Delete keys on data update."
  命中: "cache" 在 meta ✓ (redis-cache 包含 "cache")
  → meta_hits = 1, body_hits = 0 (body 里的 "cache" 也要算)
  → 但 meta_hits = 1 不是 deploy 不是 kubernetes...等等
  重新看：tokens = {"deploy", "kubernetes"}
  meta = "redis-cache redis cache invalidation strategy"
  "deploy" in meta? False
  "kubernetes" in meta? False
  → meta_hits = 0, body_hits = 0, score = 0
```

排序结果：`[deploy_notes.md (4.0)]`，其余过滤。

---

**场景：中文查询匹配中文记忆**

```
用户输入: "数据库 迁移 问题"
tokens: {"数","据","库","迁","移","问","题"}

文件 redis_cache.md:
  title = "redis-cache"  (无中文)
  description = "Redis cache invalidation strategy"  (无中文)
  → meta_hits = 0

但假设有另一个文件:
# db_migration.md
---
name: 数据库迁移
description: 生产环境数据库迁移注意事项
---
上次把主库锁了30分钟。迁移前先做备份，回滚方案要提前测试。

  meta = "数据库迁移 生产环境数据库迁移注意事项"
  body = "上次把主库锁了30分钟。迁移前先做备份，回滚方案要提前测试。"
  命中: "数"✓ "据"✓ "库"✓ "迁"✓ "移"✓
  → meta_hits = 5, body_hits = 0 ("问" "题" 没命中)
  → score = 5 × 2.0 = 10.0
```

逐字匹配在此场景完全有效。

---

**场景：权重 ×2 的实际效果**

```
# 文件A: description 里写了 "Redis caching strategy"
# 文件B: description 里写 "Infrastructure overview"，body 里碰巧有一句 "We use redis"

用户输入: "redis"

文件A:
  meta = "redis-caching-strategy Redis caching strategy"  → "redis" ✓
  body = "..."  → 无 redis
  → meta_hits = 1, body_hits = 0
  → score = 1 × 2.0 = 2.0

文件B:
  meta = "infrastructure overview"  → 无 redis
  body = "We use redis for caching"  → "redis" ✓
  → meta_hits = 0, body_hits = 1
  → score = 0 × 2.0 + 1 = 1.0

排序: A (2.0) > B (1.0)  ✓ metadata 优先生效
```

这就是测试 `test_search_prefers_metadata_over_body` 验证的核心行为。

---

**局限性：纯子串匹配，无语义理解。** `"redis"` 不会匹配 `"缓存"`，英文输入无法匹配纯中文记忆，驼峰词如 `"RedisCache"` 不会被拆成 `["redis", "cache"]`。这是设计取舍——零外部依赖、零延迟，语义能力需要引入 embedding 层。

---

### 4. manager.py — CRUD 操作与并发安全

#### add_memory_entry

```python
def add_memory_entry(cwd, title, content) -> Path:
    slug = sub(r"[^a-zA-Z0-9]+", "_", title.strip().lower()).strip("_") or "memory"
    path = memory_dir / f"{slug}.md"
    with exclusive_file_lock(_memory_lock_path(cwd)):
        atomic_write_text(path, content.strip() + "\n")    # ① 写记忆文件
        entrypoint = get_memory_entrypoint(cwd)
        existing = entrypoint.read_text(...) if entrypoint.exists() else "# Memory Index\n"
        if path.name not in existing:                     # ② 更新索引
            existing = existing.rstrip() + f"\n- [{title}]({path.name})\n"
            atomic_write_text(entrypoint, existing)
    return path
```

#### remove_memory_entry

```python
def remove_memory_entry(cwd, name) -> bool:
    matches = [path for path in memory_dir.glob("*.md")
               if path.stem == name or path.name == name]
    path = matches[0]
    with exclusive_file_lock(_memory_lock_path(cwd)):
        if path.exists():
            path.unlink()
        entrypoint = get_memory_entrypoint(cwd)
        if entrypoint.exists():
            lines = [line for line in entrypoint.read_text().splitlines()
                     if path.name not in line]   # ③ 从索引中移除
            atomic_write_text(entrypoint, "\n".join(lines).rstrip() + "\n")
    return True
```

#### 两层安全保障

**① `exclusive_file_lock` — 防并发冲突**

```python
# POSIX (macOS/Linux/WSL): fcntl.flock()
with lock_path.open("a+b") as lock_file:
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)  # 排他锁
    try:
        yield
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
```

**② `atomic_write_text` — 防崩溃截断**

```python
fd, tmp = tempfile.mkstemp(prefix=".file.", dir=parent)
os.write(fd, data)
os.fsync(fd)              # 确保刷到磁盘
os.replace(tmp, dst)      # 原子替换
```

两个机制解决两个不同问题：锁 → 多进程竞态；原子写 → 单进程崩溃。

---

### 5. memdir.py — System Prompt 片段生成

```python
def load_memory_prompt(cwd, *, max_entrypoint_lines=200) -> str | None:
    lines = [
        "# Memory",
        f"- Persistent memory directory: {memory_dir}",
        "- Use this directory to store durable user or project context...",
        "- Prefer concise topic files plus an index entry in MEMORY.md.",
    ]
    if entrypoint.exists():
        content_lines = entrypoint.read_text(...).splitlines()[:max_entrypoint_lines]
        lines.extend(["", "## MEMORY.md", "```md", *content_lines, "```"])
    return "\n".join(lines)
```

输出示例：

```markdown
# Memory
- Persistent memory directory: ~/.openharness/data/memory/Project-a3f2c8d1e5b9
- Use this directory to store durable user or project context...
- Prefer concise topic files plus an index entry in MEMORY.md.

## MEMORY.md
```md
# Memory Index
- [Deploy Notes](deploy_notes.md)
- [Testing Patterns](testing_patterns.md)
```
```

三条使用提示的价值：

- **路径提示**：让模型知道记忆存在哪里（模型本身不写磁盘，由命令代理）
- **场景提示**：指导模型何时建议创建记忆（用户说"以后每次..."时）
- **格式提示**：指导模型采用分离文件的组织方式

---

## 系统 Prompt 装配流程

Memory 在 `prompts/context.py:build_runtime_system_prompt()` 中通过**两级注入**集成到 Agent 运行时：

```
用户输入
    │
    ▼
build_runtime_system_prompt()
    │
    ├─ Layer 1: load_memory_prompt(cwd)        ← 始终注入
    │   读取 MEMORY.md 索引（最多 200 行）
    │   告诉模型"记忆目录在哪、有什么文件"
    │
    ├─ Layer 2: find_relevant_memories(query)   ← 仅当 memory.enabled=True 且 query 非空
    │   搜索匹配的 .md 文件（最多 max_files=5 个）
    │   注入每个文件的前 8000 字符
    │   告诉模型"当前任务相关的具体记忆内容"
    │
    └─ 拼接到 system prompt sections
```

```python
# prompts/context.py:134-161

if include_project_memory and settings.memory.enabled:
    memory_section = load_memory_prompt(cwd, max_entrypoint_lines=...)
    sections.append(memory_section)          # Layer 1: 索引

    if latest_user_prompt:
        relevant = find_relevant_memories(latest_user_prompt, cwd, max_results=...)
        for header in relevant:
            content = header.path.read_text(...).strip()
            sections.append(f"## {header.path.name}\n```md\n{content[:8000]}\n```")
                                          # Layer 2: 匹配全文
```

**两级策略的区分：**

| | Layer 1 (索引) | Layer 2 (搜索) |
|--|---------------|---------------|
| 触发 | 每次对话 | 仅当查询相关 |
| 内容 | MEMORY.md 索引 | 匹配文件全文 |
| 目的 | 元认知 | 上下文 |
| 大小 | ~200 行 | 每个最多 8000 字符 |

---

## /memory 命令

命令注册在 `commands/registry.py:402-440`，由 `MemoryCommandBackend` 接口统一抽象：

```python
class MemoryCommandBackend:
    label: str
    get_memory_dir: Callable[[], Path]
    get_entrypoint: Callable[[], Path]
    list_files: Callable[[], list[Path]]
    add_entry: Callable[[str, str], Path]
    remove_entry: Callable[[str], bool]
```

支持 5 个子命令：

| 命令 | 行为 |
|------|------|
| `/memory` | 显示存储路径和入口文件 |
| `/memory list` | 列出所有 .md 记忆文件 |
| `/memory show <name>` | 查看指定文件内容 |
| `/memory add TITLE :: CONTENT` | 创建新记忆（`::` 分隔标题和内容） |
| `/memory remove <name>` | 删除记忆 |

**后端切换机制：**

```python
def _memory_backend_for_context(context: CommandContext) -> MemoryCommandBackend:
    if context.memory_backend is not None:
        return context.memory_backend      # ohmo 模式 → .ohmo/ 个人记忆
    return MemoryCommandBackend(
        get_memory_dir=lambda: get_project_memory_dir(cwd),  # OpenHarness 模式 → ~/.openharness/...
        ...
    )
```

同一个 `/memory` 命令，在 ohmo 和 OpenHarness 模式下操作不同的存储位置。

---

## ohmo 个人记忆层

`ohmo/memory.py` 是 OpenHarness 项目记忆的镜像实现，存储在项目目录的 `.ohmo/` 下：

| 维度 | OpenHarness（项目记忆） | ohmo（个人记忆） |
|------|----------------------|----------------|
| 存储路径 | `~/.openharness/data/memory/` | `<project>/.ohmo/` |
| 搜索 | 有（token-based） | 无（仅列表 + 全文） |
| 并发安全 | 锁 + 原子写 | 无（单进程假设） |
| Prompt 注入 | 索引 + 搜索匹配 | 索引 + 最近 N 个全文 |

ohmo 缺少搜索和并发安全是因为个人 workspace 通常只有一个进程在操作，设计上做了简化。

---

## 关键设计决策

### 1. 依赖图单向无环

`paths` 和 `types` 零依赖，上层单向依赖下层。这保证了模块可以独立测试——`scan.py` 只依赖 `paths` 和 `types`，不需要 mock 其他 memory 子模块。

### 2. 分层防御

- **文件损坏**：`except OSError: continue` — scan 不因单个文件失败
- **并发写**：`exclusive_file_lock` — read-modify-write 串行化
- **崩溃截断**：`atomic_write_text` — temp file + fsync + replace
- **路径穿越**：`relative_to()` 检查 — `/memory show` 命令防止读取目录外文件

### 3. 零外部依赖

整个 memory 模块只依赖标准库（`pathlib`, `re`, `hashlib`）和内部模块（`openharness.utils.*`）。没有数据库、无需网络、不引入 ML 库。

### 4. fallback 链完善

frontmatter → 文件名 → 首段 → 全部 body。每一层都是前一层的兜底，不会因某个字段缺失而完全失败。

### 5. memory_type 预留

`MemoryHeader.memory_type` 目前只提取不参与搜索，可扩展为按类型过滤或分类展示。

---

## 配置项

`config/settings.py` 中的 `MemorySettings` 控制行为：

```python
class MemorySettings(BaseModel):
    enabled: bool = True               # 全局开关
    max_files: int = 5                # Layer 2 最多注入的记忆数
    max_entrypoint_lines: int = 200   # Layer 1 索引截断行数
    context_window_tokens: int | None = None   # 预留（未使用）
    auto_compact_threshold_tokens: int | None = None  # 预留（未使用）
```

---

## 测试覆盖

`tests/test_memory/test_memdir.py` 覆盖：

| 测试                                                           | 验证内容                               |
| ------------------------------------------------------------ | ---------------------------------- |
| `test_memory_paths_are_stable`                               | 同项目路径始终返回相同目录                      |
| `test_load_memory_prompt_includes_entrypoint`                | 提示包含 MEMORY.md 索引内容                |
| `test_find_relevant_memories`                                | token 匹配返回正确文件                     |
| `test_parse_frontmatter_extracts_fields`                     | YAML frontmatter 正确提取              |
| `test_parse_frontmatter_falls_back_without_frontmatter`      | 无 frontmatter 时 fallback 到文件名和首段   |
| `test_parse_malformed_frontmatter_does_not_return_delimiter` | 畸形 frontmatter 不泄漏分隔符到 description |
| `test_parse_frontmatter_handles_quoted_values`               | 引号包裹的值正确解析                         |
| `test_scan_memory_files_with_frontmatter`                    | frontmatter 元数据被 scan 捕获           |
| `test_search_prefers_metadata_over_body`                     | metadata 命中权重高于 body               |
| `test_search_handles_cjk_queries`                            | 中文查询能匹配中文记忆                        |
|                                                              |                                    |

---

## 已知局限

| 局限                  | 说明                                  |
| ------------------- | ----------------------------------- |
| **跨语言无法匹配**         | 英文 query 无法匹配纯中文记忆，纯 token 子串匹配无语义层 |
| **无向量搜索**           | 无法做同义词匹配（如 "cache" ≈ "Redis"）       |
| **body_preview 截断** | 300 字符硬截断可能在词中间断开                   |
| **无存储配额**           | 记忆目录无大小限制，可无限膨胀                     |
| **ohmo 无原子写**       | ohmo 个人记忆缺少崩溃保护                     |

---

## 主流 Memory 方案对比

Memory 系统的设计空间广泛，按存储和检索策略可分为**四类主流架构**。了解这些方案有助于理解 OpenHarness 的设计取舍和演进方向。

### 方案一：纯文件型（与 OpenHarness 同路）

**核心思路：** 记忆以 Markdown/纯文本文件存储在本地磁盘，通过约定文件名和格式实现组织，检索依赖关键字匹配或 LLM 主动读取。

**代表方案：**

| 方案              | 存储位置                          | 搜索方式            | 特点                             |
| --------------- | ----------------------------- | --------------- | ------------------------------ |
| **Claude Code** | `~/.claude/memory/`           | 无自动搜索，LLM 主动读文件 | 最简洁，几乎不主动匹配                    |
| **OpenHarness** | `~/.openharness/data/memory/` | Token 启发式匹配     | 有 `find_relevant_memories` 预筛选 |
| **Aider**       | `~/.aider.memories/`          | 线性扫描            | 简单，基于文件名约定                     |
| **Cursor**      | 项目内 `.cursor/memory/`         | 全文搜索            | 本地索引，与项目绑定                     |

**典型交互模式：**

```
用户: "以后 Python 项目统一用 pytest"
    → 模型创建 ~/.openharness/data/memory/pytest_convention.md
    → 模型追加到 MEMORY.md 索引

用户: "帮我写个测试"
    → Layer 1: load_memory_prompt() 告知记忆目录位置
    → Layer 2: find_relevant_memories("pytest") 搜索匹配文件
    → 模型读取 pytest_convention.md 内容，注入上下文
```

**关键设计特征：**

- **本地优先**：存储在磁盘，零网络依赖，零外部服务依赖
- **Markdown 格式**：人类可读，可 git 追踪变更历史
- **约定优于配置**：通过固定文件名（`MEMORY.md`）和目录结构而非数据库 schema 组织
- **命令驱动写入**：用户通过 `/memory` 或 LLM 代理间接写入，无独立写入 API

**优势：**
- 部署极简：无需安装任何额外服务
- 延迟极低：本地 IO，< 5ms
- 可审计：文件即历史，`git log memory/` 可追溯所有变更
- 可移植：复制整个目录即可迁移

**局限：**
- 无法跨设备共享（除非手动同步目录）
- 并发写入需要额外锁机制
- 无语义理解（纯子串匹配）
- 无结构化查询（只能按文件名或全文扫描）

---

### 方案二：向量数据库型

**核心思路：** 所有记忆通过 embedding 模型转为高维向量，存入向量数据库（Vector DB）。检索时将 query 转为向量，通过余弦相似度找回最相似的记忆。

**检索流程：**

```
用户输入 → embedding 模型 → query 向量
                                 ↓
                     cosine_similarity(query_vec, memory_vecs)
                                 ↓
                           Top-N 相似记忆
                                 ↓
                          注入 context
```

**主流向量数据库：**

| 数据库 | 特点 | 适用场景 |
|--------|------|---------|
| **Pinecone** | 云托管，按使用量收费 | 快速上线，无运维 |
| **Weaviate** | 支持混合搜索（向量+BM25） | 需要结构化过滤 |
| **Qdrant** | 自托管，Rust 实现，性能高 | 私有化部署，延迟敏感 |
| **ChromaDB** | 轻量，Python 原生 | 本地开发，小规模 |
| **Milvus** | 超大规模，支持分布式 | 亿级向量 |
| **pgvector** | PostgreSQL 插件 | 已有 PG 基础设施 |

**代表性实现：**

- **LangChain** `VectorStoreRetrieverMemory`：将对话历史和记忆向量化存储
- **LlamaIndex** `VectorMemory`：文档记忆抽象，支持多种向量后端
- **AutoGPT** 长期记忆：使用 Pinecone 存储任务结果和经验
- **Notion AI** 知识库：向量搜索 + 全文搜索混合

**优势：**
- **语义相似**：能匹配同义词（"cache" ≈ "Redis"）、跨语言（英文匹配中文）
- **可扩展**：PB 级向量存储，分布式检索
- **自动聚类**：相似记忆自然聚集，无需人工分类

**局限：**
- 依赖外部服务（云服务或自建集群）
- 额外延迟（embedding 生成 10-50ms + 向量搜索 5-20ms）
- 成本（ Pinecone \$0.10/GB/月 + embedding API 调用费）
- 黑盒调试困难：为什么这条记忆被匹配/没被匹配难以解释

---

### 方案三：图数据库型

**核心思路：** 将记忆建模为实体-关系图（Entity-Relation Graph），而非平面文档。记忆内容被解析为节点（实体）和边（关系），检索通过图遍历实现。

**数据模型：**

```
节点: 记忆片段
  - id: 唯一标识
  - content: 原始文本
  - timestamp: 创建时间
  - source: 来源（对话/手动/自动生成）
  - tags: 标签列表
  - entities: 实体列表

边: 关系
  - references: 引用关系（A 引用了 B）
  - similar_to: 相似关系
  - caused_by: 因果关系
  - part_of: 层级关系
```

**应用场景：**

- **研究笔记工具**（如 Obsidian + Graph View）：可视化记忆间的链接关系
- **复杂推理任务**：多跳推理（"A 和 B 相关，B 影响 C，C 导致 D"）
- **因果追溯**：从结果记忆反向追溯原因链

**代表性工具：**

- **Neo4j**：主流图数据库，LangChain/LlamaIndex 均支持
- **Memex**（OSAF 项目）：研究笔记工具，以图结构组织记忆
- **KAG（蚂蚁金服）**：知识图谱增强 RAG，结合知识图谱和向量搜索

**优势：**
- 支持多跳推理和关系查询
- 可解释性强：检索路径透明
- 适合结构化知识（如实体-关系明确的领域）

**局限：**
- 实体抽取依赖 NER/embedding 模型
- 图查询复杂度高，大图遍历成本大
- 部署和调优成本高
- 不适合非结构化记忆（大多数日常对话）

---

### 方案四：混合分层架构（前沿方向）

**核心思路：** 将记忆分为多个层次，每层用最适合的存储和检索策略，取长补短。

**经典四层模型：**

```
┌─────────────────────────────────────────────────────────┐
│ 用户输入                                                 │
│    │                                                    │
│    ▼                                                    │
│ 工作记忆层 (Working Memory)                              │
│   - 内容: 变量/token，在 session 内持久                  │
│   - 容量: ~4K tokens                                    │
│   - 保留: 当前会话，结束时丢弃                            │
│   - 技术: Python 变量 + tool_metadata                    │
├─────────────────────────────────────────────────────────┤
│ 场景记忆层 (Episodic Memory)                             │
│   - 内容: 最近 N 条交互的摘要                            │
│   - 容量: ~20K tokens                                   │
│   - 保留: 最近 7 天                                     │
│   - 技术: LLM 生成摘要 + 分数或向量                       │
├─────────────────────────────────────────────────────────┤
│ 语义记忆层 (Semantic Memory)                             │
│   - 内容: 向量化长期记忆                                 │
│   - 容量: 无限制                                        │
│   - 保留: 永久                                          │
│   - 技术: 向量数据库 (Pinecone/Qdrant)                   │
├─────────────────────────────────────────────────────────┤
│ 程序记忆层 (Procedural Memory)                           │
│   - 内容: Skill 定义、工作流模板、最佳实践                 │
│   - 容量: 无限制                                        │
│   - 保留: 永久                                          │
│   - 技术: 文件系统 + 结构化 Markdown                     │
└─────────────────────────────────────────────────────────┘
```

**代表性系统：**

- **MemGPT**：多层记忆系统，将 GPT 的上下文窗口模拟为 CPU 寄存器，语义记忆层模拟为 RAM，向外溢出到向量存储
- **KAG**（蚂蚁）：知识图谱+向量混合，用于金融领域问答
- **AgentScope**：多代理记忆管理，场景间共享语义记忆

**OpenHarness 的当前对应：**

| 层级   | OpenHarness 组件                 | 状态           |
| ---- | ------------------------------ | ------------ |
| 工作记忆 | `tool_metadata`                | ✅ 完整实现       |
| 场景记忆 | `session snapshot` + `/resume` | ⚠️ 有快照，无自动摘要 |
| 语义记忆 | `memory/` 目录                   | ⚠️ 有文件存储，无向量 |
| 程序记忆 | `skills/`                      | ✅ 完整实现       |

**缺口分析：**
- 场景记忆层缺少**自动摘要生成**：每次会话结束后，没有 LLM 生成叙事性摘要（如"今天完成了登录模块，修复了 3 个 bug"）存入语义记忆
- 语义记忆层缺少**向量搜索**：token 匹配在语义相似度上远弱于 embedding

---

### 方案五：结构化记忆型

**核心思路：** 超越纯文本文件，为记忆引入结构化 schema。每个记忆不只是文本，而是带类型、带字段的结构化对象，支持精确查询和过滤。

**扩展 frontmatter 设计：**

```yaml
---
name: redis-cache-strategy
type: pattern           # pattern | context | reference | decision
tags: [infrastructure, caching, redis]
entities:
  - service: payment-service
  - cache: Redis Cluster
  - pattern: cache-aside
decisions:
  - "使用 Redis Cluster 而非 Sentinel，避免脑裂"
  - "TTL 设为 5 分钟，过期后异步回源"
links:
  - memory:auth-patterns.md
  - pr:https://github.com/.../pull/123
created_at: 2025-03-15
author: claude
---
```

**结构化优势：**

- **按类型过滤**：`type=pattern` 只返回设计模式类记忆
- **精确查询**：`entities.service=payment-service` 精确匹配
- **直接注入字段**：可直接注入 `decisions` 字段而非全文
- **关系建模**：`links` 字段显式建模记忆间关系

**代表性实现：**
- **Memex**：结构化研究笔记，带实体和关系标注
- **Notion Database**：结构化笔记，表格视图
- **结构化 RAG**：将文档解析为 schema+content，存入向量库时保留结构

**OpenHarness 的现状：** `memory_type` 字段已预留，但未被 search 使用。frontmatter 只解析 `name/description/type`，不支持 `entities/decisions/links` 等扩展字段。

---

### 方案对比总览

| 方案         | 搜索方式               | 存储            | 跨语言 | 延迟       | 部署复杂度 | 适用场景            |
| ---------- | ------------------ | ------------- | --- | -------- | ----- | --------------- |
| **纯文件型**   | Token 匹配           | 本地 .md        | ✗   | <5ms     | 极简    | 单机个人用、简单项目      |
| **向量数据库型** | Embedding + cosine | 云/自建 VectorDB | ✓   | 50-200ms | 中-高   | 企业知识库、多语言场景     |
| **图数据库型**  | 图遍历                | Neo4j/图       | △   | 100ms+   | 高     | 复杂推理、因果追溯       |
| **混合分层**   | 层级路由               | 多层混合          | ✓   | 可变       | 中     | 大型 Agent、需要语义理解 |
| **结构化记忆**  | Schema 查询          | JSON/YAML     | △   | <10ms    | 低-中   | 精确过滤、关系建模       |

---

### OpenHarness 的定位与演进方向

从对比来看，OpenHarness 处于**纯文件型**的较完善端：

- 比 Claude Code 多了 token 搜索预筛选（`find_relevant_memories`）
- 比简单文件方案多了 `MemoryCommandBackend` 多后端抽象
- 锁+原子写的并发安全也做了

**当前架构的优势（与向量方案比）：**

| 维度 | OpenHarness | 向量数据库型 |
|------|------------|-------------|
| 部署 | 零额外依赖 | 需要 VectorDB 服务 |
| 延迟 | <5ms | 50-200ms |
| 成本 | $0 | 云服务 + embedding API |
| 调试 | 文件即状态，易追踪 | 黑盒，需额外工具 |
| 离线 | 完全可用 | 需网络 |

**演进方向（不加云端的前提下）：**

1. **向量搜索补充**：token 初筛 + embedding 精排（hybrid）— 兼顾精确和语义
2. **结构化 frontmatter**：真正使用 `memory_type`，增加 `tags`、`entities` 字段
3. **场景记忆摘要**：利用 LLM 自动生成会话摘要存入记忆层（补全四层架构）
4. **跨语言支持**：可选 embedding 模型处理中英混合场景
5. **ohmo 原子写**：补全 ohmo 个人记忆的崩溃保护

---

## 完整数据流

```
用户输入
    │
    ▼
build_runtime_system_prompt()
    │
    ├─ load_memory_prompt()
    │     │
    │     ├─ get_project_memory_dir()  → 解析记忆目录路径
    │     ├─ get_memory_entrypoint()   → 读取 MEMORY.md
    │     └─ 截断 200 行 → 注入 Layer 1（索引）
    │
    └─ find_relevant_memories(query)
          │
          ├─ _tokenize(query)          → {ascii tokens} ∪ {han chars}
          │
          ├─ scan_memory_files(max_files=100)
          │     │
          │     ├─ glob("*.md")
          │     ├─ _parse_memory_file()  → MemoryHeader
          │     │     ├─ 解析 frontmatter
          │     │     ├─ 构建 body_preview（排除 desc_line_idx）
          │     │     └─ 获取 st_mtime
          │     └─ 按 modified_at 降序
          │
          ├─ 逐 header 打分：meta_hits×2 + body_hits×1
          ├─ 过滤 score>0
          ├─ 排序 (score↓, modified_at↓)
          └─ 取 top-5 → 注入 Layer 2（匹配全文）

用户输入 /memory add TITLE :: CONTENT
    │
    ├─ _memory_backend_for_context()
    │     └─ 返回 MemoryCommandBackend（项目记忆或 ohmo 个人记忆）
    │
    ├─ backend.add_entry(title, content)
    │     │
    │     ├─ slugify(title)
    │     ├─ exclusive_file_lock()
    │     ├─ atomic_write_text(slug.md)
    │     └─ 更新 MEMORY.md 索引（atomic）
    │
    └─ 返回 "Added memory entry slug.md"
```