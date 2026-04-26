# Claude API Context Compaction 详解

> 文档来源：
> 1、[Compaction - Claude API Docs](https://docs.anthropic.com/en/docs/build-with-claude/compaction) 
> 2、[Effective Context Engineering - Anthropic Engineering Blog](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
> 整理日期：2026-04-08

---

## 一、Compaction 解决什么问题

### 1.1 两大核心痛点

LLM 的上下文窗口是有限的。当对话越来越长，会面临两个问题：

1. **硬限制**：input tokens 超过上下文窗口上限，API 直接报错
2. **软退化（Context Rot）**：即使没超限，模型在超长上下文中注意力分散，回复质量下降

Compaction 解决的就是这两个问题——**自动把旧对话压缩成摘要，腾出空间给新内容**。

### 1.2 适用场景

- **长对话聊天**：用户使用一个 chat 进行长时间多轮对话
- **任务导向的 Agent 工作流**：需要大量工具调用迭代，可能超出上下文窗口

### 1.3 当前状态

- 目前为 **Beta** 阶段，需要 beta header `compact-2026-01-12`
- 仅支持 **Claude Opus 4.6** 和 **Claude Sonnet 4.6**
- 支持 Zero Data Retention (ZDR)

---

## 二、Compaction 的本质：模型给自己写备忘录

### 2.1 它不是"压缩算法"

API 文档只讲了"怎么用"，对内部机制讲得很薄。但结合 Anthropic 工程博客和 API 行为细节，可以还原完整机制：

**Compaction = 用同一个模型，做一次额外的采样调用，把全量对话历史变成一份摘要。**

没有特殊编码、没有小模型、没有向量量化——就是 Claude 读一遍完整历史，写一份 summary 给未来的自己。

### 2.2 为什么"自己给自己写备忘录"是最优策略？

Anthropic 在工程博客中阐明了核心洞察：

> "The art of compaction lies in the selection of **what to keep versus what to discard**, as overly aggressive compaction can result in the loss of subtle but critical context whose importance only becomes apparent later."
>
> （压缩的艺术在于"保留什么 vs 丢弃什么"的选择——过度激进的压缩可能导致丢失微妙但关键的上下文，而这些信息的重要性往往要到后来才会显现。）

模型比任何外部算法都更清楚**在自己的上下文中什么信息对未来推理最重要**。这就是为什么 Anthropic 选择让模型自己做摘要，而不是用小模型或启发式规则。

---

## 三、完整的请求生命周期（6 步还原）

### 3.1 流程图

```
客户端发请求（messages 数组含 100 轮对话，约 180K tokens）
    ↓
① Token 计数检查：input_tokens >= trigger 阈值？
    ↓ 是
②【第一次采样 — Compaction Iteration】
   实际构造的 prompt：
   ┌──────────────────────────────────────────┐
   │ [System Prompt]                          │
   │ [消息1...消息100]                         │
   │ + 默认/自定义摘要指令 prompt               │
   │   "Write a summary of transcript..."     │
   └──────────────────────────────────────────┘
   模型输出：<summary>...关键信息...</summary>
   计费：180K input + 3.5K output（正常 token 价格）
    ↓
③ API 解析 <summary> 标签，构造 compaction block：
   { "type": "compaction", "content": "摘要文本..." }
    ↓
④ 如果 pause_after_compaction=true → 此处暂停，返回给客户端
   如果 pause_after_compaction=false → 继续下一步
    ↓
⑤【第二次采样 — Message Iteration】
   实际构造的 prompt（已经压缩）：
   ┌──────────────────────────────────────────┐
   │ [System Prompt]                          │
   │ [compaction block（替代之前100轮）]       │
   │ [compaction block 之后的少量消息]          │
   └──────────────────────────────────────────┘
   模型输出：正常回复
   计费：~23K input + 1K output
    ↓
⑥ 返回 response（content 含 compaction block + text block）
```

### 3.2 两次采样的 usage 数据

**这就是为什么 `usage.iterations` 里有两条记录**：

```json
{
  "usage": {
    "input_tokens": 23000,
    "output_tokens": 1000,
    "iterations": [
      {
        "type": "compaction",
        "input_tokens": 180000,
        "output_tokens": 3500
      },
      {
        "type": "message",
        "input_tokens": 23000,
        "output_tokens": 1000
      }
    ]
  }
}
```

| 字段 | 含义 |
|------|------|
| 第一条 `compaction` iteration | 读全部 180K tokens，写 3.5K 摘要 |
| 第二条 `message` iteration | 读压缩后的 23K tokens，写 1K 回复 |
| 顶层 `input_tokens` / `output_tokens` | **仅非 compaction 迭代的总和**，不含压缩消耗 |

### 3.3 费用陷阱

**真实总消耗 = compaction iteration + message iteration**：

```
180K(input) + 3.5K(output) + 23K(input) + 1K(output) = 207.5K tokens
```

但顶层 `usage.input_tokens` 只显示 23K。如果你的成本监控系统依赖顶层字段，启用 compaction 后**必须**改为遍历 `usage.iterations` 数组求和。

---

## 四、默认摘要 Prompt 深度解析

### 4.1 原文与逐句翻译

Compaction 的默认摘要 prompt：

```
You have written a partial transcript for the initial task above.
Please write a summary of the transcript.
The purpose of this summary is to provide continuity so you can continue
to make progress towards solving the task in a future context,
where the raw history above may not be accessible and will be replaced
with this summary. Write down anything that would be helpful,
including the state, next steps, learnings etc.
You must wrap your summary in a <summary></summary> block.
```

**中文翻译：**

```
你已经为上面的初始任务撰写了一份部分记录。
请为这份记录写一份摘要。
这份摘要的目的是提供连续性，以便你在未来的上下文中
（原始历史记录可能无法访问，将被此摘要替代）
能够继续推进任务的解决。
请写下任何有帮助的内容，包括当前状态、下一步计划、经验教训等。
你必须将摘要包裹在 <summary></summary> 标签中。
```

### 4.2 设计意图逐句分析

| 原文片段 | 设计意图 |
|----------|---------|
| `"You have written a partial transcript"` | 让模型切换到"记录者"角色，不是"参与者"。避免自引用冗余 |
| `"The purpose of this summary is to provide continuity"` | 核心目标——不是为了复述对话，而是让未来的自己能**接续工作** |
| `"where the raw history above may not be accessible and will be replaced with this summary"` | 告诉模型"删了就没了"——制造紧迫感，避免偷懒只写高层概述 |
| `"Write down anything that would be helpful, including the state, next steps, learnings etc."` | 明确三个保留维度：当前状态（在哪）、下一步（去哪）、经验教训（怎么去） |
| `"You must wrap your summary in a <summary></summary> block."` | 结构化输出，让 API 可靠地解析和提取摘要内容 |

### 4.3 这个 Prompt 的局限性

- **通用设计**：适用于大多数任务，但不针对特定领域优化
- **保留粒度不可控**：你无法指定"必须保留第37条消息的第三句话"
- **依赖模型判断力**：模型可能忽略看似不重要但实际关键的信息

这就是 `instructions` 参数存在的原因——用自定义指令弥补通用 prompt 的不足。

---

## 五、API 参数详解

### 5.1 参数总览

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `type` | string | 必填 | 固定值 `"compact_20260112"` |
| `trigger` | object | 150,000 tokens | 触发阈值，最小 50,000 |
| `pause_after_compaction` | boolean | `false` | 压缩后是否暂停 |
| `instructions` | string | `null` | 自定义摘要提示词（**完全替换**默认 prompt） |

### 5.2 trigger — 触发阈值配置

```python
{
    "type": "compact_20260112",
    "trigger": {"type": "input_tokens", "value": 100000},
}
```

- 默认 150,000 tokens，最小 50,000 tokens
- 当 input tokens 达到阈值时触发压缩
- Agentic 工具调用密集场景可降到 100K 甚至 50K

### 5.3 instructions — 自定义摘要指令

**关键：这是完全替换默认 prompt，不是追加。** 你要写完整的指令。

```python
{
    "type": "compact_20260112",
    "instructions": "Focus on preserving code snippets, variable names, and technical decisions.",
}
```

### 5.4 pause_after_compaction — 压缩后暂停

这是整个 API **最精妙的设计**。开启后 API 在生成摘要后暂停，返回 `stop_reason: "compaction"`，允许你在继续之前手动构造 messages。

---

## 六、不同场景的自定义保留策略

Anthropic 的调优建议是：先最大化**召回率**（确保不遗漏重要信息），再迭代提升**精确率**（消除冗余内容）。以下是各场景的推荐策略：

### 6.1 代码 Agent

```python
"instructions": """Preserve the following in order of priority:
1. All file paths and directory structures mentioned
2. All function signatures, variable names, and class definitions
3. All architectural decisions and their rationale
4. All unresolved bugs and error messages
5. Current implementation state (what's done, what's pending)
6. All code snippets and their locations

You may discard:
- Tool call results that have already been incorporated
- Repeated explanations of the same concept
- Intermediate exploration steps that led nowhere"""
```

### 6.2 数据分析 Agent

```python
"instructions": """Preserve the following:
1. All SQL queries and their results (especially statistics)
2. All column names, table schemas, and data types
3. All statistical findings and conclusions drawn
4. All visualization decisions and their parameters
5. Data quality issues discovered
6. The current analysis pipeline state

You may discard:
- Raw data samples that have been summarized
- Failed query attempts (unless they reveal schema insights)
- Repetitive status updates"""
```

### 6.3 客服/对话 Agent

```python
"instructions": """Preserve the following:
1. All facts the user has shared (name, account details, preferences)
2. All unresolved issues and their current status
3. All promises or commitments made to the user
4. All actions already taken (tickets created, refunds processed)
5. User's emotional state and communication preferences
6. Any escalation history

You may discard:
- Greetings and pleasantries
- Repeated confirmations of the same information
- Small talk not relevant to the user's issue"""
```

### 6.4 研究助手

```python
"instructions": """Preserve the following:
1. All citations, paper titles, and authors mentioned
2. Key findings from each source
3. Methodology decisions and their rationale
4. Open questions and hypotheses
5. Comparison tables or matrices built during research
6. Current research direction and next steps

You may discard:
- Detailed methodologies of papers not directly relevant
- Full abstracts (keep only key findings)
- Search queries that returned no useful results"""
```

### 6.5 写作/内容创作 Agent

```python
"instructions": """Preserve the following:
1. The overall narrative structure and outline
2. Character names, settings, and world-building details
3. Tone and style decisions
4. Specific word choices or phrases the user approved/rejected
5. Current draft state and revision history
6. Feedback notes and revision priorities

You may discard:
- Earlier draft versions that have been superseded
- Brainstorming options that were explicitly rejected
- Formatting details that can be reconstructed"""
```

---

## 七、pause_after_compaction 的设计哲学与用法

### 7.1 为什么需要暂停？

默认模式下，compaction 会压缩整个对话历史。但最近几轮对话可能包含关键上下文（用户刚提的需求、刚得到的工具调用结果），你不希望它们被摘要化而丢失精度。

### 7.2 基础用法

```python
response = client.beta.messages.create(
    betas=["compact-2026-01-12"],
    model="claude-opus-4-6",
    max_tokens=4096,
    messages=messages,
    context_management={
        "edits": [{"type": "compact_20260112", "pause_after_compaction": True}]
    },
)

# 检查是否触发了压缩暂停
if response.stop_reason == "compaction":
    # 暂停后，你可以手动构造新的 messages
    messages.append({"role": "assistant", "content": response.content})

    # 继续请求
    response = client.beta.messages.create(
        betas=["compact-2026-01-12"],
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=messages,
        context_management={"edits": [{"type": "compact_20260112"}]},
    )
```

### 7.3 高级用法：保留最近对话的原始精度

```python
if response.stop_reason == "compaction":
    compaction_block = response.content[0]

    # 保留最近一轮完整对话（3条消息：用户问+助手答+用户追问）
    preserved_messages = messages[-3:] if len(messages) >= 3 else messages

    # 构造新消息列表：摘要 + 保留的原始消息
    messages_after_compaction = [
        {"role": "assistant", "content": [compaction_block]}
    ] + preserved_messages

    # 用压缩后的上下文继续请求
    response = client.beta.messages.create(
        betas=["compact-2026-01-12"],
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=messages_after_compaction,
        context_management={"edits": [{"type": "compact_20260112"}]},
    )

    # 更新消息列表
    messages.clear()
    messages.extend(messages_after_compaction)
```

### 7.4 Token 预算控制

结合 compaction 次数计数，可以实现总 token 预算管理：

```python
TRIGGER_THRESHOLD = 100_000
TOTAL_TOKEN_BUDGET = 3_000_000
n_compactions = 0

# ... 在压缩暂停后
if response.stop_reason == "compaction":
    n_compactions += 1
    messages.append({"role": "assistant", "content": response.content})

    # 估算总消耗，超预算则提示模型收尾
    if n_compactions * TRIGGER_THRESHOLD >= TOTAL_TOKEN_BUDGET:
        messages.append({
            "role": "user",
            "content": "Please wrap up your current work and summarize the final state.",
        })
```

---

## 八、Claude Code 的实际做法分析

### 8.1 工程博客揭示的实现细节

Anthropic 工程博客透露了 Claude Code 的实际 Compaction 实现：

> "In Claude Code, we implement this by passing the message history to the model to summarize and compress the most critical details. The model preserves architectural decisions, unresolved bugs, and implementation details while discarding redundant tool outputs or messages. **The agent can then continue with this compressed context plus the five most recently accessed files.**"

翻译成技术方案，Claude Code 使用的正是 `pause_after_compaction` 模式：

```python
# Claude Code 的实际压缩流程（推断还原）
if response.stop_reason == "compaction":
    compaction_block = response.content[0]

    # 加载最近访问的 5 个文件作为额外上下文
    recent_files = load_recent_files(5)

    messages_after_compaction = [
        # 摘要替代全量历史
        {"role": "assistant", "content": [compaction_block]},
        # 注入最近文件内容
        {"role": "user", "content": format_files(recent_files)},
        # 保留最近几轮原始对话
        *messages[-3:]
    ]
```

### 8.2 Claude Code 策略的三层保障

```
第一层：摘要（保留架构决策、未解决 bug、实现细节）
第二层：最近 5 个文件（保持当前工作上下文的精确性）
第三层：最近几轮原始对话（保持对话连贯性）
```

**这就是 `pause_after_compaction` 存在的真正原因**——Anthropic 自己的产品就需要这个能力。不只是依赖摘要，而是**摘要 + 保留最近的工作上下文**。

---

## 九、compaction block 在后续请求中的角色

### 9.1 数据结构

当 compaction 触发时，API 返回如下结构：

```json
{
  "content": [
    {
      "type": "compaction",
      "content": "Summary of the conversation: The user requested help building a web scraper..."
    },
    {
      "type": "text",
      "text": "Based on our conversation so far..."
    }
  ]
}
```

### 9.2 API 的处理逻辑

收到含 compaction block 的 messages 时：

```
扫描 messages → 找到最后一个 type:"compaction" 的 block
             → 丢弃它之前的所有内容
             → 用 compaction block + 之后的内容构建实际输入
```

**关键规则**：

- **多次 compaction 只有最后一次生效**：每次新的 compaction 都会基于全量历史重新生成
- **可以保留旧消息**：API 自动忽略 compaction block 之前的所有内容，不删也不影响正确性
- **也可以手动清理**：删掉旧消息可以省带宽（但不省钱，API 端已经忽略了）

### 9.3 最简集成方式

你只需要做一件事：把 response.content **原样** append 到 messages 里：

```python
messages.append({"role": "assistant", "content": response.content})
```

不需要手动过滤 compaction block，SDK/API 会自动处理。这是设计上最优雅的地方——**集成成本极低**。

---

## 十、Streaming 模式下的 Compaction

### 10.1 Compaction Block 的流式行为

与普通 text block 不同，compaction block 在流式中有特殊行为：

```
content_block_start   → 事件类型为 "compaction"
content_block_delta   → 只有一个！整块摘要一次性推送，不逐字流式
content_block_stop    → 结束
```

Text block 跟在后面，正常流式输出。

### 10.2 Python 流式示例

```python
with client.beta.messages.stream(
    betas=["compact-2026-01-12"],
    model="claude-opus-4-6",
    max_tokens=4096,
    messages=messages,
    context_management={"edits": [{"type": "compact_20260112"}]},
) as stream:
    for event in stream:
        if event.type == "content_block_start":
            if event.content_block.type == "compaction":
                print("Compaction started...")
            elif event.content_block.type == "text":
                print("Text response started...")

        elif event.type == "content_block_delta":
            if event.delta.type == "compaction_delta":
                print(f"Compaction complete: {len(event.delta.content)} chars")
            elif event.delta.type == "text_delta":
                print(event.delta.text, end="", flush=True)

    # 获取最终的累积消息
    message = stream.get_final_message()
    messages.append({"role": "assistant", "content": message.content})
```

---

## 十一、与 Prompt Caching 的配合

### 11.1 问题

Compaction 发生时，摘要成为新内容，需要写入缓存。如果不加额外处理，这会使 system prompt 的缓存也失效，需要一起重新写入。

### 11.2 解决方案：分离缓存

在 system prompt 末尾加 `cache_control` 断点，让 system prompt **单独缓存**：

```python
response = client.beta.messages.create(
    betas=["compact-2026-01-12"],
    model="claude-opus-4-6",
    max_tokens=4096,
    system=[
        {
            "type": "text",
            "text": "You are a helpful coding assistant...",
            "cache_control": {"type": "ephemeral"},  # 关键：单独缓存 system prompt
        }
    ],
    messages=messages,
    context_management={"edits": [{"type": "compact_20260112"}]},
)
```

### 11.3 效果

```
未分离缓存：
  compaction 发生 → summary 是新内容 → system prompt 缓存失效 → 全部重写

分离缓存后：
  compaction 发生 → summary 是新内容 → 但 system prompt 缓存仍然有效 ✓
  → 只有 summary 需要写入新缓存条目
```

这对**长 system prompt** 场景特别有价值——system prompt 跨多次 compaction 事件始终保持缓存。

---

## 十二、与其他 Context 管理策略的关系

### 12.1 Anthropic 推荐的压缩梯度

Compaction 不是唯一的上下文管理手段。从轻到重，Anthropic 提供了三层策略：

```
最轻量 ──────────────────────────────────────→ 最重量

Tool Result Clearing → Thinking Block 剥离 → Compaction（摘要替换）
     ↓                      ↓                       ↓
删掉 tool 调用结果      删掉 thinking tokens     全部历史替换为摘要
   安全                    安全且自动             有信息损失风险
  省少                     省多                  省最多
```

Anthropic 工程博客的原话：

> "Tool result clearing is one of the safest, lightest touch forms of compaction."

推荐策略：**先用最轻量的手段，不够再用重量级的**。

### 12.2 三大长程上下文策略

Anthropic 在工程博客中还揭示了 Compaction 只是三大策略之一：

| 策略 | 机制 | 最佳场景 |
|------|------|---------|
| **Compaction** | 摘要替换旧历史 | 需要大量来回交互的任务 |
| **Structured Note-Taking** | Agent 主动写笔记到外部存储 | 有明确里程碑的迭代开发 |
| **Sub-Agent** | 专门子 Agent 处理子任务，只返回精简结果 | 需要并行探索的复杂研究 |

选择指南：

- **Compaction** → 大量来回交互的任务（如 Claude Code 的编码会话）
- **Note-Taking** → 有明确里程碑的迭代开发（如 Todo list、NOTES.md）
- **Multi-Agent** → 需要并行探索的复杂研究（如多 Agent 研究系统）

### 12.3 与 Token 计数端点的配合

Token 计数端点（`/v1/messages/count_tokens`）会应用已有的 compaction block，但**不会触发新的压缩**：

```python
count_response = client.beta.messages.count_tokens(
    betas=["compact-2026-01-12"],
    model="claude-opus-4-6",
    messages=messages,
    context_management={"edits": [{"type": "compact_20260112"}]},
)

print(f"Current tokens: {count_response.input_tokens}")           # 压缩后的 token 数
print(f"Original tokens: {count_response.context_management.original_input_tokens}")  # 压缩前的 token 数
```

### 12.4 与 Server Tools 的交互

使用 web search 等 server tool 时，compaction 在**每次采样迭代开始时**检查触发条件。根据 trigger 阈值和输出量，可能一次请求内触发**多次压缩**。

---

## 十三、完整的实战代码模板

### 13.1 最简模式（推荐入门）

```python
import anthropic

client = anthropic.Anthropic()
messages = [{"role": "user", "content": "Help me build a website"}]

response = client.beta.messages.create(
    betas=["compact-2026-01-12"],
    model="claude-opus-4-6",
    max_tokens=4096,
    messages=messages,
    context_management={"edits": [{"type": "compact_20260112"}]},
)

# 唯一需要的操作：原样 append
messages.append({"role": "assistant", "content": response.content})
```

### 13.2 长对话聊天函数

```python
import anthropic

client = anthropic.Anthropic()
messages: list[dict] = []

def chat(user_message: str) -> str:
    messages.append({"role": "user", "content": user_message})

    response = client.beta.messages.create(
        betas=["compact-2026-01-12"],
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=messages,
        context_management={
            "edits": [{
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": 100000},
            }]
        },
    )

    # Append response（compaction blocks 自动包含）
    messages.append({"role": "assistant", "content": response.content})

    # 提取文本内容
    return next(block.text for block in response.content if block.type == "text")

# 可以无限对话下去
print(chat("Help me build a Python web scraper"))
print(chat("Add support for JavaScript-rendered pages"))
print(chat("Now add rate limiting and error handling"))
```

### 13.3 生产级模式（pause + 保留最近对话 + 预算控制）

```python
import anthropic
from typing import Any

client = anthropic.Anthropic()
messages: list[dict[str, Any]] = []

TRIGGER_THRESHOLD = 100_000
TOTAL_TOKEN_BUDGET = 3_000_000
n_compactions = 0

def chat(user_message: str) -> str:
    global n_compactions
    messages.append({"role": "user", "content": user_message})

    response = client.beta.messages.create(
        betas=["compact-2026-01-12"],
        model="claude-opus-4-6",
        max_tokens=4096,
        messages=messages,
        context_management={
            "edits": [{
                "type": "compact_20260112",
                "trigger": {"type": "input_tokens", "value": TRIGGER_THRESHOLD},
                "pause_after_compaction": True,
            }]
        },
    )

    if response.stop_reason == "compaction":
        n_compactions += 1
        compaction_block = response.content[0]

        # 预算检查
        if n_compactions * TRIGGER_THRESHOLD >= TOTAL_TOKEN_BUDGET:
            messages.append({"role": "assistant", "content": response.content})
            messages.append({
                "role": "user",
                "content": "Please wrap up your current work and summarize the final state.",
            })
            # 继续最后一次请求（不再触发压缩暂停）
            response = client.beta.messages.create(
                betas=["compact-2026-01-12"],
                model="claude-opus-4-6",
                max_tokens=4096,
                messages=messages,
                context_management={"edits": [{"type": "compact_20260112"}]},
            )
        else:
            # 保留最近一轮完整对话（3条消息）
            preserved_messages = messages[-3:] if len(messages) >= 3 else messages

            messages_after_compaction = [
                {"role": "assistant", "content": [compaction_block]}
            ] + preserved_messages

            response = client.beta.messages.create(
                betas=["compact-2026-01-12"],
                model="claude-opus-4-6",
                max_tokens=4096,
                messages=messages_after_compaction,
                context_management={"edits": [{"type": "compact_2026012"}]},
            )

            messages.clear()
            messages.extend(messages_after_compaction)

    messages.append({"role": "assistant", "content": response.content})
    return next(block.text for block in response.content if block.type == "text")
```

---

## 十四、常见 Context 压缩方案对比

| 策略 | 压缩比 | 信息损失 | 额外成本 | 实现复杂度 | 适用场景 |
|------|--------|---------|---------|-----------|---------|
| **Anthropic Compaction** | ~10x | 低（可自定义） | 一次摘要采样 | 极低 | Claude 长对话 |
| OpenAI Compaction API | ~5-10x | 黑盒（加密） | 一次压缩调用 | 低 | GPT 长对话 |
| Thinking Block 剥离 | 视推理长度 | 推理细节 | 零 | 零 | Extended Thinking |
| 滑动窗口/消息裁剪 | 视窗口大小 | 高（不可控） | 零 | 极低 | 简单聊天 |
| 对话摘要化 | ~5-10x | 中等 | LLM 调用 | 低 | 多轮对话 |
| LLMLingua | ~20x | 中等 | 小模型推理 | 中 | 长 prompt 预处理 |
| RAG + Contextual Compression | N/A | 取决于检索 | 向量存储+检索 | 高 | 大知识库 |
| LangGraph 长期记忆 | 视设计 | 可控 | 存储+检索 | 高 | Agent 系统 |

**最务实的组合**：

```
Anthropic Compaction（管理对话历史）
  + Prompt Caching（缓存 system prompt）
  + Thinking Block 剥离（推理链不占空间）
  + RAG（外部知识按需加载）
```

四层配合可以最大化利用有限的上下文窗口。

---

## 十五、当前限制

- **只能用同一模型做摘要**：不能用便宜模型（如 Haiku）为贵模型（如 Opus）做摘要
- **仅 Beta**：API 可能在未来版本中变更
- **仅 Opus 4.6 / Sonnet 4.6**：其他模型暂不支持
- **摘要质量不可精确控制**：你无法指定"必须保留某条消息的某个细节"，只能通过 `instructions` 引导方向

---

## 十六、关键要点总结

1. **Compaction 的本质**是"让模型自己决定什么对未来的自己最重要"，不是压缩算法
2. **内部机制**是两次采样：第一次读全量历史写摘要，第二次读摘要写回复
3. **默认摘要 Prompt** 精心设计了角色切换、紧迫感、三维度保留（状态/下一步/教训）
4. **`instructions` 参数完全替换默认 prompt**，不同场景必须自定义保留策略
5. **`pause_after_compaction`** 允许在摘要之外保留最近对话的原始精度
6. **Claude Code** 用的是 pause 模式：摘要 + 最近 5 个文件 + 最近几轮对话
7. **配合 Prompt Caching** 时要在 system prompt 加 cache_control 断点，避免缓存失效
8. **费用追踪**必须看 `usage.iterations` 数组，顶层字段不含 compaction 消耗
9. **压缩梯度**：先用 Tool Result Clearing（最轻），再用 Thinking Block 剥离，最后才用 Compaction（最重）
10. **三大长程策略**：Compaction（交互型）+ Note-Taking（里程碑型）+ Sub-Agent（研究型）

---

*最后更新：2026-04-08*
