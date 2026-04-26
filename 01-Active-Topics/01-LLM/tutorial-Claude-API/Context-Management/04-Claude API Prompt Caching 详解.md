# Claude API Prompt Caching 详解

> 本文基于 [Anthropic 官方 Prompt Caching 文档](https://docs.anthropic.com/en/docs/build-with-claude/prompt-caching) 整理，结合实际案例深入讲解工作原理与最佳实践。

---

## 一、什么是 Prompt Caching

Prompt Caching 通过缓存 prompt 的前缀部分（prefix），在后续请求中复用已处理的内容，从而：

- **降低延迟**：跳过已缓存的 token 处理
- **节省成本**：缓存命中仅为基础输入价格的 10%
- **适用场景**：多轮对话、大文档问答、大量 few-shot 示例、Agent 工具调用

### 核心机制

系统通过密码学哈希（cryptographic hash）匹配 prompt 前缀。缓存写入发生在标记 `cache_control` 的断点位置，缓存读取时从断点向前回溯查找已写入的条目。

---

## 二、两种启用方式

### 2.1 自动缓存（Automatic Caching）

在请求顶层加一个 `cache_control` 字段，系统自动将断点放在最后一个可缓存 block 上。

```python
response = client.messages.create(
    model="claude-sonnet-4-5-20250514",
    max_tokens=1024,
    cache_control={"type": "ephemeral"},  # 顶层，自动模式
    system="你是一个客服助手...",
    messages=[
        {"role": "user", "content": "你们支持退货吗？"}
    ],
)
```

**特点：**
- 最简方式，一行配置
- 断点随对话增长自动前移
- 适合标准多轮对话
- 也可指定 1 小时 TTL：`cache_control={"type": "ephemeral", "ttl": "1h"}`

### 2.2 显式断点（Explicit Cache Breakpoints）

在具体 content block 上标记 `cache_control`，精确控制缓存粒度。

```python
response = client.messages.create(
    model="claude-sonnet-4-5-20250514",
    max_tokens=1024,
    tools=[
        {"name": "search", "input_schema": {...}},
        {"name": "get_doc", "input_schema": {...},
         "cache_control": {"type": "ephemeral"}}  # 断点在最后一个 tool 上
    ],
    system=[
        {"type": "text", "text": "你是研究助手...",
         "cache_control": {"type": "ephemeral"}},  # 断点在指令上
        {"type": "text", "text": "知识库：[大量文档]",
         "cache_control": {"type": "ephemeral"}}   # 断点在文档上
    ],
    messages=[...],
)
```

**特点：**
- 最多 4 个断点，分别缓存不同部分
- 各部分独立缓存，互不影响
- 适合工具 + 指令 + 文档 + 对话，各部分变化频率不同的场景

### 2.3 两种方式对比

| | 自动缓存 | 显式断点 |
|--|---------|---------|
| 断点位置 | 系统自动放最后一个可缓存 block | 手动指定任意 block |
| 断点数量 | 1 个（自动管理） | 最多 4 个 |
| 适用场景 | 简单多轮对话 | 多层缓存，各层变化频率不同 |
| 混合使用 | 可以和显式断点组合（自动缓存占 1 个断点槽位） | — |

---

## 三、缓存层级：tools → system → messages

### 3.1 什么是层级

Claude 处理请求时，按固定顺序拼接内容：

```
[tools 定义] → [system prompt] → [messages 对话历史]
```

缓存也按这个顺序建立前缀。**任何一层的内容变了，它自身和后面所有层的缓存全部失效。**

### 3.2 实际案例

假设你构建了一个文档问答助手：

```json
{
  "tools": [
    {"name": "search_docs", ...},
    {"name": "get_doc", ..., "cache_control": {"type": "ephemeral"}}
  ],
  "system": [
    {"type": "text", "text": "你是研究助手...", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "知识库：[50页文档]", "cache_control": {"type": "ephemeral"}}
  ],
  "messages": [
    {"role": "user", "content": "火星有什么发现？"},
    {"role": "assistant", "content": "..."},
    {"role": "user", "content": "详细说说好奇号", "cache_control": {"type": "ephemeral"}}
  ]
}
```

缓存结构：

```
┌─────────────────────────────┐
│  tools (search_docs, get_doc)│ ← 断点①：缓存所有工具定义
├─────────────────────────────┤
│  system (指令)               │ ← 断点②：缓存系统指令
├─────────────────────────────┤
│  system (50页知识库文档)      │ ← 断点③：缓存文档内容
├─────────────────────────────┤
│  messages (对话历史)          │ ← 断点④：缓存对话
└─────────────────────────────┘
```

### 3.3 缓存失效传播

| 变更内容 | tools 缓存 | system 缓存 | messages 缓存 |
|----------|:----------:|:-----------:|:-------------:|
| 工具定义变更 | ✘ | ✘ | ✘ |
| web search/citations 开关 | ✓ | ✘ | ✘ |
| tool_choice 变更 | ✓ | ✓ | ✘ |
| 图片增删 | ✓ | ✓ | ✘ |
| thinking 参数变更 | ✓ | ✓ | ✘ |

**核心原则：前面的层一变，后面所有层的缓存都失效，不管后面那些层的内容有没有实际改变。**

这就是显式断点的价值——tools 和 system 分别缓存，文档更新时 tools 和指令的缓存保住了。

---

## 四、自动缓存在多轮对话中的工作原理

### 4.1 机制概述

自动缓存每轮在末尾写入缓存条目，下一轮回溯查找时找到上一轮写入的条目后命中，只处理新增部分。

### 4.2 逐轮详解

假设 system prompt 5000 tokens，每轮对话约 200 tokens。

**第一轮：用户提问"支持退货吗？"**

```
┌──────────────────────────────┐
│ system: "你是客服助手..."     │  5000 tokens
│                              │
├──────────────────────────────┤
│ user: "你们支持退货吗？"      │  50 tokens    ◀ 自动缓存断点
└──────────────────────────────┘
```

- `cache_creation_input_tokens`: 5050（全部写入缓存）
- `cache_read_input_tokens`: 0

系统写入一条缓存条目：`hash(整个前缀到 user 消息末尾)`

**第二轮：用户继续问"退货流程是什么？"**

```
┌──────────────────────────────┐
│ system: "你是客服助手..."     │  ← 从缓存读取 ✓
├──────────────────────────────┤
│ user(1): "支持退货吗？"       │  ← 从缓存读取 ✓
├──────────────────────────────┤
│ assistant(1): "是的，我们..." │  ← 新写入
├──────────────────────────────┤
│ user(2): "退货流程？"         │  ← 新写入 + 自动断点 ◀
└──────────────────────────────┘
```

系统执行过程：
1. 计算 user(2) 处的前缀哈希 → 未命中
2. 回溯到 assistant(1) → 未命中
3. 回溯到 user(1) → **命中第一轮的缓存条目**
4. 从缓存读取 system + user(1)（5050 tokens）
5. 只处理 assistant(1) + user(2)（200 tokens）
6. 在 user(2) 处写入新缓存条目

- `cache_creation_input_tokens`: 200
- `cache_read_input_tokens`: 5050

**第三轮：用户追问"需要保留包装吗？"**

```
┌──────────────────────────────┐
│ system                       │  ← 缓存命中 ✓
├──────────────────────────────┤
│ user(1)                      │  ← 缓存命中 ✓
├──────────────────────────────┤
│ assistant(1)                 │  ← 缓存命中 ✓
├──────────────────────────────┤
│ user(2)                      │  ← 缓存命中 ✓（第二轮写入的条目）
├──────────────────────────────┤
│ assistant(2)                 │  ← 新写入
├──────────────────────────────┤
│ user(3): "保留包装？"         │  ← 新写入 + 自动断点 ◀
└──────────────────────────────┘
```

- `cache_creation_input_tokens`: 200
- `cache_read_input_tokens`: 5250
- `input_tokens`: 0

### 4.3 成本对比（Claude Sonnet 4.5，基础 $3/MTok）

| 轮次 | 无缓存成本 | 有缓存成本 | 节省 |
|------|-----------|-----------|------|
| 第1轮 | $0.015 | $0.019（写入贵 25%） | -26% |
| 第2轮 | $0.016 | $0.00225 | **86%** |
| 第3轮 | $0.016 | $0.00233 | **85%** |

第一轮因写入缓存贵 25%，但从第二轮起每轮节省 85%+。对话越长省越多。

---

## 五、显式断点工作原理

### 5.1 三条核心规则

**规则 1：缓存写入只发生在标记断点的地方**

```
block1 → block2 → block3[断点] → block4 → block5
                      ↑
               只在这里写入缓存
               哈希 = hash(block1 + block2 + block3)
```

没标记 `cache_control` 的位置永远不会写入缓存条目。

**规则 2：缓存读取时回溯查找之前写入过的条目**

系统从断点向前回溯，寻找之前某个请求在那里**写入过**的缓存条目。它找的是"有没有人写过"，不是"内容是否稳定"。

**规则 3：回溯窗口最多 20 block**

从断点自身算起，向前最多看 20 个位置。超过就找不到了。

### 5.2 完整示例：文档问答 Agent

假设有：
- 2 个工具定义（几乎不变）~1000 tokens
- 系统指令（几乎不变）~500 tokens
- 知识库文档（每天更新）~8000 tokens
- 对话历史（每轮变化）~200 tokens/轮

设置 4 个显式断点：

```json
{
  "tools": [
    {"name": "search", "input_schema": {...}},
    {"name": "get_doc", "input_schema": {...}, "cache_control": {"type": "ephemeral"}}
  ],
  "system": [
    {"type": "text", "text": "你是研究助手...", "cache_control": {"type": "ephemeral"}},
    {"type": "text", "text": "知识库：[8000 tokens文档]", "cache_control": {"type": "ephemeral"}}
  ],
  "messages": [
    {"role": "user", "content": "火星有什么发现？", "cache_control": {"type": "ephemeral"}}
  ]
}
```

**第 1 次请求：4 个断点全部 miss，写入 4 条缓存条目**

```
条目A: hash(tools全部) = "abc123"           → 写入
条目B: hash(tools+指令) = "def456"          → 写入
条目C: hash(tools+指令+文档) = "ghi789"      → 写入
条目D: hash(tools+指令+文档+对话) = "jkl000"  → 写入
```

**第 2 次请求：用户继续追问"好奇号呢？"**

```
┌─────────────────────────────┐
│ tools                       │ ← 断点①：hash("abc123") → 命中 ✓
├─────────────────────────────┤
│ system (指令)               │ ← 断点②：hash("def456") → 命中 ✓
├─────────────────────────────┤
│ system (文档)               │ ← 断点③：hash("ghi789") → 命中 ✓
├─────────────────────────────┤
│ messages                    │
│   user(1)                   │ ← 回溯找到上轮断点④ → 命中 ✓
│   assistant(1)              │
│   user(2) ◀ 断点④           │ ← 新写入条目E
└─────────────────────────────┘
```

- `cache_read_input_tokens`: 9500（tools + 指令 + 文档 + user1）
- `cache_creation_input_tokens`: 350（assistant1 + user2）
- 只花了 350 tokens 的缓存写入钱

**第 3 次请求：文档更新了（知识库变了）**

```
┌─────────────────────────────┐
│ tools (没变)                │ ← 断点①：hash("abc123") → 命中 ✓
├─────────────────────────────┤
│ system (指令，没变)          │ ← 断点②：hash("def456") → 命中 ✓
├─────────────────────────────┤
│ system (新文档，变了)        │ ← 断点③：hash 变了 → 未命中 ✘ → 重新写入
├─────────────────────────────┤
│ messages (虽然没变)          │ ← 断点④：前缀哈希全变了 → 未命中 ✘ → 重新写入
└─────────────────────────────┘
```

- `cache_read_input_tokens`: 1500（只命中 tools + 指令）
- `cache_creation_input_tokens`: 8400（文档 + 对话重新写入）

**关键：tools 和指令的缓存保住了。如果只有一个断点在末尾，这 1500 tokens 也得重写。这就是多个断点的意义。**

---

## 六、常见错误与排查

### 6.1 断点放在每轮变化的内容上

```python
# 错误：消息里包含时间戳，每轮都变
{"role": "user", "content": "当前时间：10:30:52，请问...",
 "cache_control": {"type": "ephemeral"}}
```

结果：每次请求哈希都不同，零命中，每次全量写入。

**修正：** 断点放在不变的部分末尾（如 system prompt 上），消息不加 `cache_control`。

### 6.2 对话超过 20 block 导致缓存失效

如果每轮添加很多 block（如多张图片、多个 tool_result），对话快速增长可能超过 20 block 的回溯窗口。

**修正：** 在对话中间加一个额外的显式断点，确保回溯窗口内有写入过的条目。

### 6.3 最小 token 数未达标

| 模型 | 最小可缓存 token 数 |
|------|-------------------|
| Claude Opus 4.6 / 4.5 | 4096 |
| Claude Sonnet 4.6 | 2048 |
| Claude Sonnet 4.5 / 4 / 3.7 | 1024 |
| Claude Haiku 4.5 | 4096 |
| Claude Haiku 3.5 / 3 | 2048 |

低于此值缓存静默失败（请求正常，但 `cache_creation_input_tokens` 和 `cache_read_input_tokens` 都为 0）。

### 6.4 tool_use 的 key 顺序不稳定

Swift、Go 等语言 JSON 序列化可能随机化 map 的 key 顺序，导致"相同内容"产生不同的哈希值，缓存永远命中不了。

**修正：** 确保 JSON 序列化时 key 顺序稳定。

### 6.5 不再需要 beta 前缀

Prompt Caching 已正式发布，直接用标准 API 调用即可：

```python
# 错误（旧写法）
client.beta.prompt_caching.messages.create(...)

# 正确
client.messages.create(...)
```

---

## 七、定价一览

### 7.1 计费规则

| 计费项 | 价格倍率（相对基础输入价格） |
|--------|:---:|
| 5 分钟缓存写入 | **1.25x** |
| 1 小时缓存写入 | **2x** |
| 缓存命中/刷新 | **0.1x**（90% 折扣） |

### 7.2 各模型定价（美元/百万 token）

| 模型 | 基础输入 | 5m 写入 | 1h 写入 | 缓存命中 | 输出 |
|------|---------|---------|---------|---------|------|
| Claude Opus 4.6 / 4.5 | $5.00 | $6.25 | $10.00 | **$0.50** | $25.00 |
| Claude Opus 4.1 / 4 | $15.00 | $18.75 | $30.00 | **$1.50** | $75.00 |
| Claude Sonnet 4.6 / 4.5 / 4 | $3.00 | $3.75 | $6.00 | **$0.30** | $15.00 |
| Claude Haiku 4.5 | $1.00 | $1.25 | $2.00 | **$0.10** | $5.00 |
| Claude Haiku 3.5 | $0.80 | $1.00 | $1.60 | **$0.08** | $4.00 |
| Claude Haiku 3 | $0.25 | $0.30 | $0.50 | **$0.03** | $1.25 |

---

## 八、1 小时缓存 TTL

### 8.1 何时使用

默认 5 分钟 TTL 适合高频请求。以下场景考虑 1 小时 TTL：

- 请求间隔可能超过 5 分钟但不到 1 小时（如 Agent 子任务耗时较长）
- 用户对话间隔不确定（如聊天机器人）
- 希望改善 rate limit 利用率（缓存命中不计入 rate limit）

### 8.2 使用方式

```json
{"cache_control": {"type": "ephemeral", "ttl": "1h"}}
```

### 8.3 混合 TTL 规则

同一请求可混用 5 分钟和 1 小时 TTL，但有约束：

- 1 小时断点必须出现在 5 分钟断点**之前**
- 混合时计费分三段：缓存读取 → 1 小时写入 → 5 分钟写入

---

## 九、缓存与 Extended Thinking

- thinking blocks **不能**直接标记 `cache_control`
- 但 thinking blocks 会随其他内容一起被缓存（如传递 tool_result 时）
- 缓存命中时 thinking blocks 计入 input tokens
- 传入非 tool_result 的 user 内容会导致所有之前的 thinking blocks 被剥离，缓存失效

---

## 十、数据隐私

- 缓存条目通过密码学哈希匹配，只有完全相同的 prompt 前缀才能命中
- 缓存按组织隔离（2026-02-05 起改为 workspace 级隔离）
- KV 缓存仅存于内存，不落盘
- 缓存到期后自动删除
- 支持 Zero Data Retention (ZDR)

---

## 十一、最佳实践速查

1. **多轮对话优先用自动缓存**，零配置，系统自动管理断点
2. **显式断点放在跨请求不变的内容末尾**，不要放在每轮变化的内容上
3. **静态内容放 prompt 开头**（工具、指令、文档），对话放后面
4. **对话超过 20 block 增长时，加中间断点**，确保回溯窗口内有缓存条目
5. **多个断点适合各层变化频率不同的场景**（工具不变、指令不变、文档每天更新、对话每轮更新）
6. **通过 usage 字段追踪效果**：`cache_read_input_tokens` 和 `cache_creation_input_tokens` 都为 0 说明缓存没生效
7. **首次请求贵 25%**，但从第二次起每次节省 85%+，长期收益远大于首笔开销

---

## 十二、监控缓存效果

响应 `usage` 中的三个关键字段：

```
total_input_tokens = cache_read_input_tokens + cache_creation_input_tokens + input_tokens
```

| 字段 | 含义 |
|------|------|
| `cache_read_input_tokens` | 从缓存读取的 token（最后一个断点之前，已缓存） |
| `cache_creation_input_tokens` | 新写入缓存的 token（断点处写入） |
| `input_tokens` | 最后一个断点**之后**的 token（不参与缓存） |

注意：`input_tokens` 不代表全部输入 token，只代表断点之后的部分。有效使用缓存时，这个值通常很小。

---

*最后更新：2026-04-01*
