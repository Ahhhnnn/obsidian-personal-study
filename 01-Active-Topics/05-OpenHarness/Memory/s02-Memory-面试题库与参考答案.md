# Memory 系统面试题库与参考答案

> **使用说明：** 按难度分三档，涵盖 OpenHarness 源码级理解和行业通用知识。部分问题需要结合代码理解，部分需要方案设计能力。每个问题附评分标准。

---

## 第一部分：基础认知（入门级，2-3 分钟回答）

### Q1. 简述 OpenHarness Memory 系统和 Agent 工作记忆（tool_metadata）的区别。

**考察点：** 理解两类记忆的定位和生命周期。

**参考答案：**

| | Memory 系统 | tool_metadata |
|--|-----------|--------------|
| 生命周期 | **持久化**，跨会话存储 | **会话级**，session 结束后消失 |
| 存储位置 | 本地磁盘 `~/.openharness/data/memory/` | 内存中的 dict |
| 内容 | 项目决策、团队约定、历史经验 | 最近读过的文件、调用过的工具、任务目标 |
| 写入方式 | 用户/模型通过 `/memory add` 命令 | 模型执行工具时自动更新 |
| 用途 | "上次定的 Python 用 pytest" | "上一轮我读取了哪个文件" |

简单说：**tool_metadata 是 Agent 的短期工作记忆，Memory 是它的长期记忆**。Agent 重启后 tool_metadata 丢失，但 Memory 仍在。

---

### Q2. OpenHarness 的记忆文件存储在哪里？为什么要用 SHA1 哈希？

**考察点：** 路径策略和哈希消歧的必要性。

**参考答案：**

存储路径：
```
~/.openharness/data/memory/<项目名>-<SHA1前12位>/
```

例如：`~/.openharness/data/memory/OpenHarness-a3f2c8d1e5b9/`

**为什么需要 SHA1 哈希：**

只用项目名不足以区分不同路径的同名项目：
```
/work/myapp    → myapp-?????
/personal/myapp → myapp-?????
```
如果只用 `myapp` 作为目录名，这两个项目会错误地共享同一份记忆。两个路径的 SHA1 哈希不同，所以被映射到不同的目录。

**为什么用 SHA1 而不用 MD5？**
- 不需要密码学强度（碰撞唯一后果是错误共享记忆，概率 ≈ 1/16¹²）
- SHA1 在 Python 标准库中直接可用，无需引入额外依赖

---

### Q3. Memory 文件支持哪几种格式？请按优先级说明解析顺序。

**考察点：** frontmatter 解析的实现细节。

**参考答案：**

**格式一：YAML Frontmatter（优先）**
```markdown
---
name: deploy-strategy
description: Kubernetes 部署策略
type: pattern
---

正文内容...
```

**格式二：无 frontmatter（fallback）**
```markdown
Redis cache invalidation strategy

Details about TTL and invalidation patterns.
```

解析优先级：
1. `name` → MemoryHeader.title
2. `description` → MemoryHeader.description
3. `type` → MemoryHeader.memory_type
4. 无 frontmatter 时：文件名 stem → title
5. 无 frontmatter 时：首段非标题行 → description

---

### Q4. 什么是 frontmatter？在 Memory 文件中它起到什么作用？

**考察点：** 理解元数据标注的价值。

**参考答案：**

Frontmatter 是 Markdown 文件顶部的 YAML 块，用 `---` 包裹。

**作用：**
- **语义浓缩**：title + description 是用户刻意写的摘要，比正文更能代表文件主题
- **搜索加权来源**：description 命中权重 ×2.0，正文命中权重 ×1.0
- **可扩展性**：`type` 字段预留，支持未来按类型过滤（如 `type=decision`）
- **结构化组织**：`memory_type` 可分类记忆（pattern/context/reference）

---

### Q5. 请对比 Claude Code、OpenHarness 和 AutoGPT 三者的 Memory 设计思路。

**考察点：** 行业主流方案的理解和对比。

**参考答案：**

| 维度 | Claude Code | OpenHarness | AutoGPT |
|------|------------|-------------|---------|
| 存储位置 | `~/.claude/memory/` | `~/.openharness/data/memory/` | Pinecone（云端） |
| 存储格式 | Markdown | Markdown | 向量 + 原始文本 |
| 搜索方式 | 无自动搜索，LLM 主动读 | Token 启发式匹配 | Embedding + cosine |
| 索引机制 | MEMORY.md 固定格式 | MEMORY.md + Backend 抽象 | Pinecone 自动索引 |
| 并发安全 | 无（单进程假设） | 锁 + 原子写 | 云服务天然处理 |
| 跨设备共享 | 不支持 | 不支持 | 支持（云端） |

**核心差异：**
- **Claude Code**：最简洁，几乎不做主动搜索，依赖 LLM 自己决定读哪些文件
- **OpenHarness**：在 Claude Code 基础上加了 token 预筛选和 MemoryCommandBackend 多后端抽象
- **AutoGPT**：完全云端化，用向量相似度替代子串匹配，能处理同义词和跨语言，但依赖外部服务

---

### Q6. 什么是 RAG（Retrieval-Augmented Generation）？它和 Agent 的 Memory 系统有什么关系？

**考察点：** RAG 概念和 Agent Memory 的关系。

**参考答案：**

**RAG = 检索增强生成**：将外部知识库的检索结果作为 context 注入 LLM，提升回答的准确性和时效性。

```
用户问题 → 向量化 → 在知识库中检索相似文档 → 注入 prompt → LLM 生成
```

**与 Agent Memory 的关系：**

Memory 系统本质上是一个**面向 Agent 的垂直 RAG 系统**：

| RAG 通用架构 | 对应 Memory 组件 |
|-------------|----------------|
| 文档存储 | `.md` 记忆文件 |
| 向量索引 | `find_relevant_memories`（OpenHarness 是 token 版 RAG） |
| 检索增强 | 注入 system prompt |
| LLM 生成 | Agent Loop 消费检索结果 |

**关键区别：**
- RAG 面向**开放域问答**（企业知识库、法律文档）
- Agent Memory 面向**项目私有上下文**（决策、约定、经验）
- RAG 常需要向量数据库，Agent Memory 可以用更简单的文件方案

---

## 第二部分：核心机制（中级，5-8 分钟回答）

### Q7. `find_relevant_memories` 的评分公式是什么？为什么要对 metadata 加倍权重？

**考察点：** 搜索评分机制的理解。

**参考答案：**

```python
score = meta_hits × 2.0 + body_hits × 1.0
```

**权重加倍的原因：**

metadata 是用户**刻意标注**的，语义密度高。比如 description 写了 "Redis caching strategy"，说明这个文件就是关于 Redis 缓存的。正文里偶然提到 "redis" 的文件不一定相关。

```
文件A: description="Redis caching strategy" → "redis" 在 metadata ✓ → score×2
文件B: body="...use redis for sessions..."   → "redis" 只在 body ✓ → score×1
→ A 排前，B 排后
```

这保证了搜索结果优先返回"明确相关"的文件，而非"碰巧提及"的文件。

---

### Q8. `_tokenize` 函数如何处理中英文混合输入？请说明设计理由。

**考察点：** 分词策略和跨语言处理。

**参考答案：**

```python
def _tokenize(text):
    # ASCII: 3+ 字符的单词 token（过滤 "a", "is", "to"）
    ascii_tokens = {t for t in re.findall(r"[A-Za-z0-9_]+", text.lower()) if len(t) >= 3}
    # CJK: 逐字提取（中文每个字独立有义）
    han_chars = set(re.findall(r"[\u4e00-\u9fff\u3400-\u4dbf]", text))
    return ascii_tokens | han_chars
```

**设计理由：**

- **ASCII 最小 3 字符**：过滤无意义高频词（`"a"`, `"is"`, `"to"`, `"in"`），保留有义短词（`"fix"`, `"bug"`, `"api"`）
- **中文逐字不逐词**：中文词边界模糊（"数据库"是一个词还是"数据"+"库"？），不引入 jieba 等额外依赖，效果可靠

**局限性：** 英文无法匹配纯中文记忆，中文无法匹配纯英文记忆——纯子串匹配无语义层。

---

### Q9. 在 Memory 文件中，`body_preview` 为什么不能包含已用作 `description` 的那行？请从评分公平性角度分析。

**考察点：** 理解 `desc_line_idx` 排除机制和评分公平性。

**参考答案：**

如果不排除，同一文本会在两个地方被计分：

```python
# description 来自 body 首段 "Redis cache invalidation"
# 不排除时，body_preview 仍包含这一行
body_preview = "Redis cache invalidation strategy Details here."

# 搜索 "redis"
"redis" in description  → meta_hits=1  → score += 2.0
"redis" in body_preview → body_hits=1 → score += 1.0
total = 3.0  ← 同一内容被计了 3 分，虚高！
```

这行在两个地方同时命中，对其他只命中一次的文件不公平。排除后，该行只在 metadata 中计分（×2），body 中只计 body 分（×1），评分更准确。

---

### Q10. Memory 系统如何保证并发安全？请描述文件锁和原子写的协作关系。

**考察点：** 并发控制和崩溃恢复。

**参考答案：**

两层机制解决两个不同问题：

**① 文件锁（`exclusive_file_lock`）— 防多进程竞态**

```
进程A: /memory add "决策A"  ← 同时
进程B: /memory add "决策B"  ← 同时
    ↓
同时读取 MEMORY.md → 都看到空索引
同时写入 MEMORY.md → 进程B 覆盖进程A
→ 决策A 的索引丢失
```

用 `fcntl.flock`（POSIX）或 `msvcrt.locking`（Windows）实现排他锁，确保 read-modify-write 串行化。

**② 原子写（`atomic_write_text`）— 防单进程崩溃截断**

```
进程A: 写入中（只写了 "长期有"）
进程A: 崩溃 → 文件停留在 "长期有"（截断）
```

用临时文件 + `fsync` + `os.replace` 实现原子替换——写操作先写到临时文件，刷盘，然后原子替换目标文件。崩溃最多导致临时文件残留，不会破坏目标文件。

**两者配合：** 锁解决多进程竞态；原子写解决单进程崩溃。单独用锁不防崩溃，单独用原子写不防并发。

---

### Q11. Memory 系统在 System Prompt 中是如何装配的？为什么要分两级？

**考察点：** prompt 注入策略和层级设计。

**参考答案：**

```
用户输入
    │
    ▼
Layer 1: load_memory_prompt(cwd)       ← 每次都注入
    读取 MEMORY.md 索引（最多 200 行）
    → 告诉模型"记忆目录在哪、有哪些文件"

Layer 2: find_relevant_memories(query)  ← 仅当 memory.enabled=True 且 query 非空
    Token 匹配搜索（最多 max_files=5 个）
    注入匹配文件全文（每个最多 8000 字符）
    → 告诉模型"和当前任务相关的具体内容"
```

**分两级的原因：**

| | Layer 1 | Layer 2 |
|--|---------|---------|
| 目的 | 元认知 | 上下文 |
| 信息量 | ~200 行索引 | 匹配文件全文 |
| 触发 | 每次对话 | 仅当相关 |

如果只有 Layer 1：模型知道记忆在哪但不知道具体内容，需要主动搜索读取。
如果只有 Layer 2：无法知道没匹配到的记忆是否存在，模型无法主动探索。

---

### Q12. 在 Memory 检索中，Token 子串匹配和向量相似度搜索各自适合什么场景？

**考察点：** 搜索技术选型的理解。

**参考答案：**

| 标准 | Token 匹配 ✅ | 向量搜索 ✅ |
|------|-------------|------------|
| 数据类型 | 英文/中文为主 | 多语言混合 |
| 查询特点 | 关键字精确 | 语义模糊/同义词多 |
| 延迟要求 | <10ms 必须 | 50ms+ 可接受 |
| 部署约束 | 离线/单机优先 | 有网络/云服务 |
| 专业术语密度 | 高（如代码、项目名） | 低 |

**典型场景：**

✅ Token 匹配适合：
- 开发工具记忆（"pytest"、"kubectl"、"Redis"）
- 项目特定术语（"OpenHarness"、"memory system"）
- 用户明确提到了具体工具/概念

✅ 向量搜索适合：
- 知识库问答（"怎么部署应用到 K8s" → 匹配 "kubernetes rollout"）
- 多语言混合（"how to cache data" → 匹配 "数据缓存策略"）
- 同义词场景（"fix bug" → 匹配 "修复缺陷"）

---

### Q13. 如果用户在 MEMORY.md 索引文件中写入了大量内容（几千行），会发生什么？系统如何防御？

**考察点：** 防御性编程和边界处理。

**参考答案：**

`load_memory_prompt` 中有截断：
```python
content_lines = entrypoint.read_text(...).splitlines()[:max_entrypoint_lines]
```

`max_entrypoint_lines` 默认为 200 行，超出部分被截断，模型看不到。

**防御的理由：**
- 每次构建 system prompt 都要读大量文本，token 成本增加
- 可能导致 context window 紧张

**潜在问题：** 重要索引信息写在 200 行之后会被意外截断丢失。当前设计优先保证 prompt 长度可控，而非保留所有索引——这是取舍，不是 bug。

---

### Q14. 什么是"向量维度灾难"？它如何影响 Memory 系统的 embedding 策略选择？

**考察点：** 向量理论和对系统设计的影响。

**参考答案：**

**维度灾难（Curse of Dimensionality）：**

随着向量维度增加，数据在高维空间中变得极度稀疏，点与点之间的距离趋向无区分度。

```
维度 4：  数据点分布相对均匀，距离有区分度
维度 16： 稀疏性开始出现
维度 64：  大部分点之间距离趋于相等
维度 384： 几乎无法区分相关与不相关
```

**对 Memory 系统的具体影响：**

| 记忆规模 | 推荐维度 | 原因 |
|---------|---------|------|
| <1000 条 | 384 维（all-MiniLM-L6-v2） | 小规模用轻量模型，避免过度拟合 |
| 1000-10万 | 768 维 | 中等规模，平衡精度和维度 |
| 10万+ | 1536 维 + HNSW 索引 | 大规模需要更高维度和优化索引 |

**核心结论：** 不是维度越高越好。对于 OpenHarness 级别的记忆量（通常几十到几百条），384 维甚至更低的模型完全够用，引入超高维度模型反而可能降低效果。

---

### Q15. 假设要改进 Memory 搜索但不能引入外部服务，你会怎么做？请设计一个混合方案。

**考察点：** 系统设计能力和工程取舍。

**参考答案：**

**方案：Token 初筛 + Embedding 精排（Hybrid）**

```
query
    │
    ├─ Token 匹配 → 快速初筛 → top-20 候选
    │
    └─ Embedding 精排 → top-5 结果
          ├─ 本地模型（如 sentence-transformers/all-MiniLM-L6-v2）
          ├─ 首次加载 ~2-5 秒，后续 <50ms
          └─ 只对候选文件做向量计算，避免全量 embedding
```

**为什么这样设计：**
- **Token 初筛做守卫**：专业术语（"Kubernetes"、"pytest"）的字面匹配是 token 的强项
- **Embedding 做精排**：解决同义词、跨语言、语义相近的排序问题
- **只对候选文件 embedding**：避免对所有记忆做 embedding，减少计算量

**实现要点：**
1. `find_relevant_memories` 先用 token 匹配选出 20 个候选
2. 对这 20 个文件做 embedding（全文或 title+description）
3. 混合排序：`final_score = token_score × 0.3 + cosine_score × 0.7`
4. 返回 top-5

**引入的复杂度：**
- 新增 `sentence-transformers` 依赖（~80MB 模型文件）
- 首次冷启动延迟 2-5 秒
- 需要持久化存储文件的 embedding（避免每次重启重新计算）

---

## 第三部分：深度理解（高级，10-15 分钟回答）

### Q16. 记忆分层是 Agent 系统中的经典设计。请画出四层记忆架构，并说明 OpenHarness 当前各层的实现状态。

**考察点：** 记忆分层理论和系统现状分析。

**参考答案：**

```
┌─────────────────────────────────────────────────────────────┐
│                         用户输入                             │
│                           │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ L1 工作记忆 (Working Memory)                           │  │
│  │  - 内容: 变量/token，session 内存中                    │  │
│  │  - 容量: ~4K tokens                                   │  │
│  │  - 保留: 会话结束即消失                                │  │
│  │  - OpenHarness: tool_metadata ✅                      │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ L2 场景记忆 (Episodic Memory)                          │  │
│  │  - 内容: 近期会话的叙事性摘要                           │  │
│  │  - 容量: ~20K tokens                                  │  │
│  │  - 保留: 最近 7 天                                     │  │
│  │  - OpenHarness: session snapshot + /resume ⚠️         │  │
│  │    现状: 有快照，无自动摘要生成                          │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ L3 语义记忆 (Semantic Memory)                         │  │
│  │  - 内容: 长期项目知识和事实                             │  │
│  │  - 容量: 无限制                                        │  │
│  │  - 保留: 永久                                          │  │
│  │  - OpenHarness: memory/ 目录 ✅（token 搜索）         │  │
│  │    缺口: 无向量搜索，无自动抽象                          │  │
│  └───────────────────────────────────────────────────────┘  │
│                           │                                  │
│                           ▼                                  │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ L4 程序记忆 (Procedural Memory)                       │  │
│  │  - 内容: Skill 定义、工作流模板、最佳实践               │  │
│  │  - 容量: 无限制                                        │  │
│  │  - 保留: 永久                                          │  │
│  │  - OpenHarness: skills/ 目录 ✅                        │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**OpenHarness 的核心缺口：**

- **L2 场景记忆**：当前有 `/resume` 恢复会话快照，但没有"自动生成叙事摘要"的机制。会话结束后不会生成"今天完成了 X，遇到了 Y，解决方案是 Z"的摘要存入 L3
- **L3 语义记忆**：有持久化文件存储，但 token 搜索无法做语义关联。如果用户说"上次遇到的那个缓存问题"，系统可能无法关联到"redis_cache_strategy.md"（除非明确提到 "redis"）

---

### Q17. 在并发场景下，`add_memory_entry` 如果不用锁，会有什么问题？请详细分析 TOCTOU 风险。

**考察点：** 并发安全、TOCTOU 问题理解。

**参考答案：**

**TOCTOU（Time-of-Check to Time-of-Use）问题：**

```python
# 无锁版本的危险场景
def add_memory_entry(cwd, title, content):
    path = memory_dir / f"{slug}.md"
    # ① CHECK: 检查 MEMORY.md 是否包含此路径
    existing = entrypoint.read_text()  # T1: 读到 "没有 path.name"
    if path.name not in existing:
        # ② USE: 写入文件 + 更新索引
        path.write_text(content)                        # T2: 写文件成功
        entrypoint.write_text(existing + f"\n- [{title}]({path.name})\n")  # T3: 写索引
```

**两个进程同时执行的场景：**

```
时刻 T0: MEMORY.md = "index only"
时刻 T1: 进程A 读 → existing = "index only"  ← 进程B 也读到相同内容
时刻 T2: 进程A 写文件A.md ✓
时刻 T3: 进程A 写索引 → "index only\n- [A](A.md)"
时刻 T4: 进程B 读 → existing = "index only\n- [A](A.md)"
时刻 T5: 进程B 写文件B.md ✓
时刻 T6: 进程B 写索引 → "index only\n- [A](A.md)\n- [B](B.md)"  ← 看起来正确
```

这个场景恰好没出问题是因为两次写入没有冲突。但如果有第三个操作——

```
时刻 T3: 进程C 在此期间也执行了 add_memory_entry → 索引变成 "index only\n- [C](C.md)"
时刻 T4: 进程A 写索引覆盖了 C 的改动 → C 的索引丢失！
```

**核心问题：** 读-修改-写三步不是原子的。多进程同时修改时，后写覆盖先写，导致丢失更新（Lost Update）。

**锁的作用：** 把读-修改-写变成一个原子临界区，同一时刻只有一个进程能进入。

---

### Q18. 在向量搜索中，余弦相似度（Cosine Similarity）和点积（Dot Product）有什么区别？各自适合什么场景？

**考察点：** 向量算法原理和选型。

**参考答案：**

```
Cosine Similarity = (A · B) / (||A|| × ||B||)    # 衡量方向相似性
Dot Product       = A · B                        # 衡量量级 + 方向
```

| | Cosine Similarity | Dot Product |
|--|------------------|-------------|
| 取值范围 | [-1, 1] | [-∞, +∞] |
| 是否归一化 | 是（除以模长） | 否 |
| 对向量模长敏感 | ✗ 不敏感 | ✓ 敏感 |
| 适合场景 | 语义相似性（方向最重要） | 检索 + 排序（考虑"重要性"） |

**典型场景：**

```python
# 搜索"机器学习教程"
向量A = 教程文档（短，模长短）
向量B = 机器学习全书（长，模长长）

Cosine：都讲 ML → 相似度高 ✓（只看方向）
Dot Product：A·B 可能很小（模长差太大）

# 搜索"高权重权威文档"
向量A = 普通博客（模长小）
向量B = 官方文档（embedding 模型赋予更大模长）

Cosine：两篇方向相似，相似度可能一样
Dot Product：官方文档模长大 → Dot Product 更高 → 排前 ✓
```

**实践建议：** 文本语义搜索用 Cosine；推荐系统/需要考虑权威性的场景用 Dot Product。

---

### Q19. 假设你要为 Memory 系统设计一个"记忆遗忘"机制，你会如何实现？为什么 AI Agent 需要主动遗忘？

**考察点：** 记忆管理策略和系统可持续性。

**参考答案：**

**为什么需要遗忘：**

```
不遗忘的问题：
- Memory 无限增长 → 搜索变慢、存储成本增加
- 旧记忆可能过时 → "上次服务器 IP 是 192.168.1.100" → 早已变更
- 干扰相关性 → 大量低价值记忆稀释真正相关的内容
```

**遗忘策略对比：**

| 策略 | 原理 | 适用场景 |
|------|------|---------|
| **LRU**（最近最少使用） | 最久未访问的记忆先遗忘 | 访问频率不均匀 |
| **时间衰减** | 按时间线性/指数衰减 | 时效性强的记忆 |
| **重要性加权** | 高价值记忆寿命长，低价值遗忘快 | 有明确价值评估 |
| **主动重评** | 定期用 LLM 评估记忆是否还有效 | 通用场景 |

**实现方案（主动重评，推荐）：**

```python
async def reevaluate_memory(header: MemoryHeader) -> dict:
    prompt = f"""
    评估以下记忆是否仍然有效：
    - 标题: {header.title}
    - 内容: {header.path.read_text()[:500]}

    回答 JSON:
    {{"still_valid": true/false, "reason": "...", "priority": "high/medium/low"}}
    """
    result = await llm.predict(prompt)
    return json.loads(result)

# 简单时间衰减作为兜底
def should_forget(header: MemoryHeader, now: float) -> bool:
    age_days = (now - header.modified_at) / 86400
    decay = math.exp(-0.0077 * age_days)  # 半衰期 90 天
    access_bonus = 1 + math.log1p(header.access_count)
    return decay * access_bonus < 0.1
```

**OpenHarness 中的实践：** 当前系统没有遗忘机制，可以考虑在 `scan_memory_files` 时过滤过期记忆，或提供 `/memory gc` 命令手动清理。

---

### Q20. 请解释 HNSW 算法是如何加速向量搜索的？为什么大多数向量数据库默认使用它？

**考察点：** 向量索引算法原理。

**参考答案：**

**核心思想：用多层图结构实现近似最近邻的 O(log N) 搜索。**

**结构：**

```
Layer 2:  ○───────○───────○───────○    ← 最稀疏，跳跃距离大
          │               │
Layer 1:  ○───○───○───○───○───○───○    ← 中等密度
          │   │   │       │   │   │
Layer 0:  ○───○───○───○───○───○───○    ← 最密集，所有点都在这层
```

**搜索过程：**

```
1. 从顶层随机一个入口点
2. 找最近邻居 → 如果找不到更近的 → 下降到下一层
3. 重复直到 Layer 0
4. 在 Layer 0 做贪婪搜索找到最近邻
```

**为什么快：**

- **顶层跳跃**：节点稀疏，一跳能跨越大范围，快速缩小搜索空间
- **下层精细**：到了底层再做精确搜索，但搜索范围已经很小
- **平均复杂度 O(log N)**：代替暴力搜索的 O(N)

**与 Memory 系统的关系：**

| 记忆规模 | 搜索策略 | 原因 |
|---------|---------|------|
| <1000 条 | 线性扫描 | 简单方案足够，无需 HNSW |
| 1000-10万 | 简单索引 | HNSW 构建成本高 |
| >10万 | HNSW | 需要 O(log N) 搜索效率 |

**HNSW 的代价：** 构建索引慢，内存占用高，不适合频繁更新的数据。

---

### Q21. 如果让你为 Memory 系统设计一套评估指标（Metrics），你会关注哪些？

**考察点：** 数据驱动思维和系统可观测性。

**参考答案：**

**四个核心指标：**

| 指标 | 定义 | 测量方式 | 健康值 |
|------|------|---------|-------|
| **命中率 (Hit Rate)** | 搜索后模型实际使用记忆的比例 | hook 拦截工具调用 | >60% |
| **召回率 (Recall)** | 用户意图需要记忆时，系统找到相关记忆的比例 | 用户会话后评估 | >70% |
| **精确率 (Precision)** | 搜索返回的记忆中，真正相关的比例 | 人工评估 top-5 | >80% |
| **注入延迟** | 从用户输入到记忆注入 system prompt 的耗时 | 计时 `find_relevant_memories` | <10ms |

**可观测性实现：**

```python
def find_relevant_memories(query, cwd, *, max_results=5):
    start = time.monotonic()
    tokens = _tokenize(query)
    headers = scan_memory_files(cwd, max_files=100)
    scored = _score_headers(headers, tokens)
    results = scored[:max_results]
    elapsed = time.monotonic() - start

    if settings.telemetry.enabled:
        report_metric("memory.search.latency_ms", elapsed * 1000)
        report_metric("memory.search.result_count", len(results))
        report_metric("memory.search.token_count", len(tokens))

    return results
```

**指导意义：**

| 指标异常 | 原因 | 优化方向 |
|---------|------|---------|
| 命中率低 | 用户不信任记忆 | 改善 prompt 提示引导 |
| 召回率低 | 搜索精度不足 | 考虑向量搜索 |
| 精确率低 | token 匹配噪音大 | 考虑混合排序 |
| 延迟高 | 文件数量多 | 考虑缓存 MemoryHeader |

---

### Q22. 在多 Agent 协作场景中，Memory 系统如何处理"共享记忆"和"私有记忆"的冲突？请设计一个方案。

**考察点：** 多 Agent 记忆管理。

**参考答案：**

**问题定义：**

```
Agent A: 记录 "支付服务使用 Stripe"
Agent B: 记录 "支付服务迁移到 Adyen"
Agent C: 需要"当前支付服务是什么"
```

**方案一：版本化（乐观锁）**

```python
@dataclass
class MemoryEntry:
    content: str
    version: int
    created_by: str
    supersedes: str | None  # 被哪个版本替代

def update_memory(entry_id, new_content):
    old = get_memory(entry_id)
    atomic_write({
        **old,
        "content": new_content,
        "version": old["version"] + 1,
        "supersedes": old["id"],  # 标记被替代
    })
```

**方案二：优先级合并**

```python
def merge_conflicting(memories: list[MemoryEntry]) -> str:
    if strategy == "latest_timestamp":
        return max(memories, key=lambda m: m.timestamp).content
    elif strategy == "team_decision":
        team_memories = [m for m in memories if m.author in team_agents]
        return max(team_memories, key=lambda m: m.timestamp).content
    elif strategy == "union":
        return "\n\n".join(m.content for m in memories)
```

**方案三：共识机制（最适合多 Agent）**

```
1. Agent A 提出记忆: "支付使用 Stripe"
2. Agent B 提出冲突记忆: "支付使用 Adyen"
3. 系统检测冲突 → 触发讨论轮次
4. 各 Agent 提交理由
5. LLM 裁决 或 团队负责人确认
6. 胜出者标记 "canonical"，失败者标记 "deprecated"
```

**当前 OpenHarness 的状态：** 完全不支持多 Agent 共享记忆，所有记忆按项目目录隔离，不存在冲突问题但也没有协作能力。

---

### Q23. 你认为当前 AI Agent 的 Memory 系统最核心的未解决问题是什么？你的解决思路是什么？

**考察点：** 批判性思维和系统优化能力。

**参考答案：**

**最核心的问题：记忆的可信度和时效性无法保证。**

```
用户: "上次你说那个 API 地址是多少来着？"
模型: "是 https://api.example.com/v2"
实际: 那个 API 两周前就迁移到了 https://api.new.com/v3
```

**三个未解决的核心问题：**

**① 记忆不自动失效**
- 状态变更后，旧记忆仍然被检索和注入
- 没有 TTL 或状态绑定机制
- **解决思路**：记忆与外部数据源绑定——如果记忆涉及可验证的状态（如 API 地址），定期自动验证或标记为"待验证"

**② 记忆的价值无法量化**
- "这条记忆重要吗？"——无法回答
- "过去一年创建了 200 条记忆，哪些真正有用？"——无法评估
- **解决思路**：引入记忆"命中日志"——记录每次 `find_relevant_memories` 的结果，据此计算记忆价值分数

**③ 没有"遗忘的主动权"**
- 用户想让模型"忘记某件事"，但系统不提供这个能力
- GDPR 等隐私法规要求"被遗忘权"
- **解决思路**：`/memory forget <name>` 命令 + 确认机制 + 向量库同步删除

**综合方案：**

```
Memory System v2.0:
1. 记忆元数据扩展：
   - expires_at: 时间戳，过期后自动降权
   - verified: bool，标记是否经过验证
   - confidence: float，置信度

2. 定期验证机制：
   - 每次 session 开始前验证即将被使用的记忆的时效性
   - 如果 source_url 可访问，对比内容是否变化

3. 命中日志：
   - 记录每次检索结果
   - 用于计算 recall 率和优化搜索策略
```

---

### Q24. 结合行业实践，Memory 系统如何与上下文压缩（Compaction）机制协同工作？

**考察点：** Agent 系统中记忆与上下文的协同设计。

**参考答案：**

**两者的关系：**

Memory 和 Compaction 都解决"上下文有限"的问题，但作用于不同层级：

```
┌────────────────────────────────────────────────────────┐
│  LLM Context Window（有限）                             │
│                                                        │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │ System Prompt│  │  Conversation │  │ Tool Result │  │
│  └──────────────┘  └──────────────┘  └─────────────┘  │
│         │                  ↑                           │
│         │          压缩工具结果，释放空间                │
└─────────┼──────────────────────────────────────────────┘
          │
          ▼
┌────────────────────────────────────────────────────────┐
│  Memory（无限制，持久化）                                 │
│                                                        │
│  ┌──────────────────────────────────────────────────┐  │
│  │ L3 语义记忆 → 注入相关记忆到 system prompt         │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

**协同设计：**

**① Compaction 把历史对话中的重要信息提炼到 Memory**

```python
if should_compact():
    summary = await llm.summarize(conversation_history)
    memory_suggestions = await llm.extract_memory_candidates(conversation_history)
    for suggestion in memory_suggestions:
        if should_save(suggestion):
            add_memory_entry(cwd, suggestion.title, suggestion.content)
```

**② Memory 反向影响 Compaction 策略**

```python
# 如果当前上下文中已注入的相关记忆丰富，可降低 compaction 激进程度
if len(injected_memories) > 3:
    compaction.aggressiveness = "low"  # 减少信息丢失
else:
    compaction.aggressiveness = "high"  # 需要更激进压缩
```

**当前 OpenHarness 的现状：**
- auto-compaction 只压缩对话历史（tool_result 替换为占位符）
- 没有"从对话历史中提取记忆"的功能
- 这是 L2 场景记忆层缺失的表现

---

### Q25. 如果你的团队要为一个客服 AI Agent 设计 Memory 系统，请描述从需求分析到技术选型的完整过程。

**考察点：** 端到端系统设计能力。

**参考答案：**

**需求分析阶段：**

```
1. 谁在用？ → 客服 Agent（面向客户，24/7 运行）
2. 记住什么？ → 产品知识、常见问题解答、用户偏好、历史工单
3. 多长时间？ → 长期（产品知识）+ 短期（当前会话用户信息）
4. 精确度要求？ → 高（错误信息导致客户不满）
5. 延迟要求？ → 中等（可接受 200-500ms）
6. 离线需求？ → 无（始终在线）
```

**技术选型：**

| 组件 | 选型 | 理由 |
|------|------|------|
| 存储 | PostgreSQL + pgvector | 产品知识用向量搜索，用户偏好用结构化表 |
| 向量模型 | `text-embedding-3-small` | 成本低（$0.02/1M tokens），精度够用 |
| 短期记忆 | Redis | 会话级 KV 存储，TTL 自动过期 |
| 更新策略 | 增量更新 | 产品知识变化时只更新变化的部分 |

**架构设计：**

```
用户输入 → 意图识别
              │
              ├─ 产品咨询 → 向量搜索 → 注入相关产品知识
              ├─ 工单查询 → 结构化 DB → 注入历史记录
              └─ 偏好查询 → Redis → 注入用户画像
                        ↓
                  合并 Context → LLM 生成回复
                        ↓
                  回复结果 → 更新 Redis（短期） + 触发知识更新（长期）
```

**关键决策点：**

1. **为什么不用纯文件？** 客服 Agent 需要精确检索、结构化更新（产品信息变更是部分字段而非整个文件）、多租户隔离
2. **为什么用 Redis 做短期记忆？** 会话级 KV 存储，TTL 自动过期，适合用户上下文
3. **为什么用 pgvector 而非专用向量库？** 已有 PostgreSQL 基础设施，不需要额外运维

---

## 面试评估标准参考

| 难度 | 期望时间 | 期望表现 |
|------|---------|---------|
| 基础认知（Q1-Q6） | 2-3 分钟 | 能准确描述机制，说出关键字段和路径，可对比方案 |
| 核心机制（Q7-Q15） | 5-8 分钟 | 能解释评分公式、设计意图、并发保障，可举例说明 |
| 深度理解（Q16-Q25） | 10-15 分钟 | 能对比方案、画架构图、分析 trade-off、设计解决方案 |