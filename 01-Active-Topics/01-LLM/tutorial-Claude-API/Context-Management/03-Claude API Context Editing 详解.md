# Claude API Context Editing 详解

> 文档来源：[Context editing - Claude API Docs](https://docs.anthropic.com/en/docs/build-with-claude/context-editing)
> 整理日期：2026-04-08

---

## 一、Context Editing 是什么

### 1.1 定位：Compaction 的手术刀
如果说Compaction 是"主力"，那么Context Editing 就是"手术刀"。

Context Editing 和 Context Compaction（见 `02-` 系列文档）是**两个不同的特性**：

| 维度          | Compaction           | Context Editing                  |
| ----------- | -------------------- | -------------------------------- |
| 核心思路        | 全量历史 → 摘要替换          | 选择性删除特定类型内容                      |
| 信息损失        | 有（摘要可能丢失细节）          | 低（只删不需要的）                        |
| 执行位置        | 服务端                  | 服务端（前两个策略）+ 客户端（SDK）             |
| 适用场景        | 通用长对话                | 工具密集型 Agent、Extended Thinking 场景 |
| Beta Header | `compact-2026-01-12` | `context-management-2025-06-27`  |

官方定位：**Compaction 是主力，Context Editing 是手术刀。**

### 1.2 核心理念

官方文档的核心观点：

> "Context is a finite resource with diminishing returns, and irrelevant content degrades model focus. Context editing gives you fine-grained runtime control over that curation."
>
> （上下文是收益递减的有限资源，无关内容会降低模型注意力。Context Editing 给你对内容筛选的细粒度运行时控制。）

Context Editing 给你**运行时的细粒度控制**，主动管理 Claude 看到什么——不只是"能装多少"，而是"装的是什么"。

### 1.3 三大策略

| 策略                          | 执行位置    | 类型标识                       | 工作方式                     |
| --------------------------- | ------- | -------------------------- | ------------------------ |
| **Tool Result Clearing**    | 服务端 API | `clear_tool_uses_20250919` | 清除对话历史中的旧工具结果            |
| **Thinking Block Clearing** | 服务端 API | `clear_thinking_20251015`  | 管理 thinking blocks 的保留数量 |
| **SDK Compaction**          | 客户端 SDK | `compaction_control`       | 生成摘要替换完整对话历史             |

当前状态：**Beta** 阶段，支持 Opus 4.6/4.5/4.1/4、Sonnet 4.6/4.5/4、Haiku 4.5。

---

## 二、服务端执行的架构设计

所有服务端策略共享一个关键架构：

> "Context editing is applied server-side before the prompt reaches Claude. Your client application maintains the full, unmodified conversation history. You do not need to sync your client state with the edited version."
>
> （上下文编辑在 prompt 到达 Claude 之前在服务端执行。你的客户端应用维护完整、未修改的对话历史。你不需要将客户端状态与编辑后的版本同步。）

```
客户端：[完整对话历史，100 轮，包含所有 tool results]
                ↓ 发送到 API
API 服务端：[检测触发条件] → [清除旧 tool results] → [只把精简版传给模型]
                ↓
模型：看到的是精简后的上下文
                ↓
客户端：继续维护完整历史，不需要做任何修改
```

**你的代码不需要维护两套状态。** 客户端永远持有完整历史，服务端自动做"视图裁剪"。

---

## 三、Tool Result Clearing（工具结果清除）

### 3.1 解决什么问题

Agent 工作流中，工具调用产生大量结果（文件内容、搜索结果等），被 Claude 处理后不再需要，但一直占上下文空间。

> "Tool result clearing is one of the safest, lightest touch forms of compaction."
>
> （工具结果清除是最安全、最轻量的压缩手段之一。）

**Tool Result Clearing 自动回收这些"已用过的"工具结果。**

### 3.2 工作机制

按时间顺序，从最旧的开始清除，用**占位符文本替换**（Claude 知道这里曾有一个工具调用，只是内容被移除了）：

```
清除前：Tool_1(旧) → Tool_2 → Tool_3 → Tool_4 → Tool_5(最新)
清除后：[占位符]  → [占位符] → Tool_3 → Tool_4 → Tool_5
                                       ← 保留 keep=3 个 →
```

### 3.3 五个配置参数

| 参数 | 默认值 | 作用 |
|------|--------|------|
| `trigger` | 100,000 tokens | 何时触发清除（支持 `input_tokens` 或 `tool_uses` 两种维度） |
| `keep` | 3 个 | 清除后保留最近多少个工具调用/结果对 |
| `clear_at_least` | None | 每次至少清除多少 tokens |
| `exclude_tools` | None | 哪些工具的结果永远不被清除 |
| `clear_tool_inputs` | `false` | 是否同时清除工具调用参数（默认只清结果） |

### 3.4 `clear_at_least` 的设计意图

专为配合 **Prompt Caching** 设计。清除内容会导致缓存前缀失效，如果只清一点点，"拆了缓存却没省多少"不划算：

```
不加 clear_at_least：清除 500 tokens → 缓存失效 → 重写 8000 tokens → 净亏
加了 clear_at_least = 5000：
  清不到 5000 → 不执行（保护缓存）
  清得到 5000+ → 值得拆缓存
```

**核心：要么别清，要么清得足够多。**

### 3.5 `clear_tool_inputs` 的微妙设计

默认 `false` 的含义：

- **清除**：工具返回的结果（`tool_result` 内容）——Claude 已消化过
- **保留**：Claude 发起的工具调用参数（`tool_use` input）——记录推理意图

工具调用参数记录了 Claude 的**推理意图**（"我为什么调这个工具"），对维持推理链有价值。

### 3.6 `trigger` 的两种维度

```python
# 按 input tokens 数量触发
"trigger": {"type": "input_tokens", "value": 50000}

# 按工具调用次数触发（适合频繁小调用场景）
"trigger": {"type": "tool_uses", "value": 20}
```

---

## 四、Thinking Block Clearing（思考块清除）

### 4.1 关键发现：默认行为

> "When extended thinking is enabled without configuring the `clear_thinking_20251015` strategy, the API automatically keeps only the thinking blocks from the last assistant turn (equivalent to `keep: {type: "thinking_turns", value: 1}`)."
>
> （当开启 Extended Thinking 但未配置 `clear_thinking_20251015` 策略时，API 自动只保留最后一个 assistant turn 的 thinking blocks，等价于 `keep: {type: "thinking_turns", value: 1}`。）

**即使你不配置 Context Editing，开启 Extended Thinking 时 API 默认就只保留最近 1 轮的 thinking blocks。** 这个策略的 `keep` 参数实际上是在覆盖这个默认行为。

### 4.2 `keep` 参数

| 配置 | 效果 |
|------|------|
| `"all"` | 保留所有 thinking → 最大化缓存命中 |
| `{"type": "thinking_turns", "value": 1}` | 只保留最近 1 轮（默认） |
| `{"type": "thinking_turns", "value": N}` | 保留最近 N 轮（N > 0） |

### 4.3 缓存 vs 空间的权衡

```
keep = "all"     → thinking 不变 → 缓存命中率高 → 省钱但占空间
keep = 1（默认）  → 只保留 1 轮   → 空间占用小   → 省上下文但缓存可能失效
keep = 2~3       → 平衡方案
```

### 4.4 计数规则

一个 assistant turn 可能包含多个 thinking blocks（Interleaved Thinking 场景）。`value: 2` 表示保留最近 2 个 assistant turn 中的**所有** thinking blocks。

---

## 五、组合策略

**重要规则**：`clear_thinking` 必须排在 `clear_tool_uses` **前面**。

```python
context_management={
    "edits": [
        {"type": "clear_thinking_20251015", "keep": {"type": "thinking_turns", "value": 2}},
        {"type": "clear_tool_uses_20250919", "trigger": {"type": "input_tokens", "value": 50000}},
    ]
}
```

这暗示了服务端的处理顺序——先清理 thinking（结构简单、确定性强），再清理 tool results。

---

## 六、与 Prompt Caching 的交互

| 策略 | 缓存影响 |
|------|---------|
| Tool Result Clearing | 清除内容使缓存前缀失效 → 用 `clear_at_least` 确保值得 |
| Thinking Block Clearing（keep） | thinking 保留 → 缓存命中；清除 → 缓存失效 |
| system prompt | **不受影响**——在 system prompt 加 `cache_control` 断点可单独缓存 |

配合策略：system prompt 的缓存独立于 messages，即使 messages 被 Context Editing 修改也不影响 system prompt 的缓存命中。

---

## 七、与 Memory Tool 的组合

### 7.1 自动警告机制

> "When your conversation context approaches the configured clearing threshold, Claude receives an automatic warning to preserve important information."
>
> （当你的对话上下文接近配置的清除阈值时，Claude 会收到一个自动警告，提示它保存重要信息。）

```
上下文接近阈值 → API 警告 Claude → Claude 调用 Memory Tool 保存重要信息
→ Tool Results 被清除 → Claude 需要时可从 Memory 读取
```

### 7.2 三层存储架构

```
┌──────────────────────────────────────────┐
│ 第一层：活跃上下文（当前对话窗口）          │  最快、最贵、最有限
├──────────────────────────────────────────┤
│ 第二层：Memory 文件（持久化存储）           │  按需读取
├──────────────────────────────────────────┤
│ 第三层：原始数据源（文件系统 / API 等）     │  可重新获取
└──────────────────────────────────────────┘
```

Memory Tool + Tool Result Clearing 是黄金组合——清除前自动保存，确保信息不丢失。

---

## 八、Client-side SDK Compaction（客户端压缩）

### 8.1 本质

**不是你自己写压缩逻辑，而是 SDK 封装好的自动化流程。** 它在你的机器上运行，通过调用 Claude API 生成摘要，整个流程由 SDK 内部控制。

官方明确推荐服务端优先：

> "Anthropic recommends server-side compaction over SDK compaction. Server-side compaction handles context management automatically with less integration complexity, better token usage calculation, and no client-side limitations."
>
> （Anthropic 推荐服务端 Compaction 而非 SDK Compaction。服务端 Compaction 自动处理上下文管理，集成复杂度更低，token 用量计算更准确，且没有客户端限制。）

### 8.2 与服务端 Compaction 的核心区别

| 维度 | 服务端 | 客户端 SDK |
|------|--------|-----------|
| 执行位置 | API 服务端 | 你的应用内 |
| 调用方式 | `messages.create` | 必须用 `tool_runner` |
| 摘要模型 | 只能用同一模型 | **可以用不同模型**（如 Haiku 为 Opus 做摘要） |
| Token 计算 | 精确 | 使用 server tools 时可能不准确 |
| `pause_after_compaction` | 支持 | 不支持 |
| 推荐度 | **首选** | 仅在需要客户端控制时用 |

**你不用 `tool_runner`，就不会碰到客户端 Compaction。两者不会冲突。**

### 8.3 用便宜模型做摘要（唯一优势）

```python
runner = client.beta.messages.tool_runner(
    model="claude-opus-4-6",              # 主对话用 Opus
    tools=[read_file, search],
    compaction_control={
        "enabled": True,
        "context_token_threshold": 100000,
        "model": "claude-haiku-4-5",       # 摘要用 Haiku（省钱 9 倍）
    },
)
```

SDK 内部流程：正常用 Opus 对话 → 超阈值时自动切换 Haiku 生成摘要 → 替换 messages → 继续用 Opus 对话。

### 8.4 Server Tools 的 Token 计算陷阱（最严重问题）

web_search 等服务端工具的 `cache_read_input_tokens` 包含内部多次 API 调用的累积读取量：

```
SDK 计算：63K(input) + 270K(cache_read) = 333K → 超阈值 → 过早触发压缩
实际上下文：可能只有 63K tokens
```

**变通方案**：大量使用 server tools 时避免客户端 Compaction，或用 Token Counting 端点获取准确值。

### 8.5 服务端 Compaction 默认摘要 Prompt

服务端 Compaction 的默认摘要 prompt（详见 `02-` 系列文档）：

**原文：**

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

**设计意图：**
- 角色定位为"记录者"，避免自引用冗余
- 强调"原始历史将被替代"制造紧迫感，避免偷懒只写高层概述
- 三个保留维度：当前状态（在哪）、下一步（去哪）、经验教训（怎么去）

### 8.6 客户端 SDK 默认摘要 Prompt

客户端 Compaction 的默认摘要 prompt 更详细，包含 5 个结构化章节：

**原文：**

```
You have been working on the task described above but have not yet completed it.
Write a continuation summary that will allow you (or another instance of yourself)
to resume work efficiently in a future context window where the conversation history
will be replaced with this summary. Your summary should be structured, concise,
and actionable. Include:

1. Task Overview
The user's core request and success criteria
Any clarifications or constraints they specified

2. Current State
What has been completed so far
Files created, modified, or analyzed (with paths if relevant)
Key outputs or artifacts produced

3. Important Discoveries
Technical constraints or requirements uncovered
Decisions made and their rationale
Errors encountered and how they were resolved
What approaches were tried that didn't work (and why)

4. Next Steps
Specific actions needed to complete the task
Any blockers or open questions to resolve
Priority order if multiple steps remain

5. Context to Preserve
User preferences or style requirements
Domain-specific details that aren't obvious
Any promises made to the user

Be concise but complete — err on the side of including information that would
prevent duplicate work or repeated mistakes. Write in a way that enables immediate
resumption of the task.

Wrap your summary in <summary></summary> tags.
```

**中文翻译：**

```
你一直在处理上面描述的任务，但尚未完成。
请写一份续接摘要，使你（或另一个相同的实例）能够在未来的上下文窗口中
（对话历史将被此摘要替代）高效地恢复工作。
你的摘要应该结构化、简洁且可操作。包括：

1. 任务概览
用户的核心请求和成功标准
他们指定的任何澄清或约束

2. 当前状态
到目前为止已完成的工作
创建、修改或分析的文件（附带路径）
产出的关键输出或制品

3. 重要发现
发现的技术约束或要求
做出的决策及其理由
遇到的错误及解决方式
尝试过但失败的方案（及原因）

4. 下一步
完成任务所需的具体行动
需要解决的阻碍或开放问题
多个步骤时的优先级顺序

5. 需保留的上下文
用户偏好或风格要求
不明显的领域特定细节
对用户做出的任何承诺

要简洁但完整——宁可多保留那些能防止重复工作或重复错误的信息。
以一种能够立即恢复任务的方式来撰写。

你必须将摘要包裹在 <summary></summary> 标签中。
```

### 8.7 两个 Prompt 的设计对比

| 维度 | 服务端 | 客户端 SDK |
|------|--------|-----------|
| 角色定位 | "记录者"（You have written a partial transcript） | "工作者"（You have been working on the task） |
| 核心目标 | "提供连续性"（provide continuity） | "高效恢复工作"（resume work efficiently） |
| 结构 | 自由格式，3 维（state/next steps/learnings） | 5 个结构化章节（overview/state/discoveries/steps/context） |
| 风格 | 简洁 | "宁可多保留"（err on the side of including） |
| 信息保留维度 | 3 维 | 5 维 |

客户端 Prompt 更详细是因为：SDK 摘要后完全替换历史，没有 `pause_after_compaction` 保留最近对话原文，所以摘要必须更完整。

### 8.8 适用与不适用场景

**适合**：长时 Agent 任务、研究工作流、有明确进度的多步骤任务
**不适合**：需精确回忆早期细节、大量使用 server tools、需跨变量保持精确状态

---

## 九、Token Counting 端点配合

Token Counting 端点支持 Context Management，**预览**清除效果但不实际执行：

```json
{
  "input_tokens": 25000,                          // 清除后
  "context_management": {
    "original_input_tokens": 70000                 // 清除前
  }
}
// 节省了 45,000 tokens
```

---

## 十、响应监控

非流式响应的 `context_management.applied_edits` 告诉你实际执行了什么：

```json
{
  "context_management": {
    "applied_edits": [
      {"type": "clear_thinking_20251015", "cleared_thinking_turns": 3, "cleared_input_tokens": 15000},
      {"type": "clear_tool_uses_20250919", "cleared_tool_uses": 8, "cleared_input_tokens": 50000}
    ]
  }
}
```

流式响应在最后的 `message_delta` 事件中包含同样的信息。

---

## 十一、完整策略决策树

```
你的 Agent 上下文在增长，怎么办？

├── 场景一：大量工具调用
│   └── 优先：Tool Result Clearing（最轻量、最安全）
│
├── 场景二：长对话 / 通用 Agent
│   └── 优先：Server-side Compaction（推荐首选）
│
├── 场景三：需要便宜模型做摘要
│   └── Client-side SDK Compaction（配合 tool_runner）
│
├── 场景四：超长任务 + 重要信息持久化
│   └── Tool Result Clearing + Memory Tool
│
└── 最优组合（生产级 Agent）：
    ├── Server-side Compaction      ← 管理整体上下文
    ├── Tool Result Clearing        ← 回收工具结果空间
    ├── Thinking Block Clearing     ← 管理 thinking 空间
    ├── Prompt Caching              ← 缓存不变部分
    └── Memory Tool                 ← 关键信息持久化
```

### 压缩梯度（从轻到重）

```
Tool Result Clearing → Thinking Block 剥离 → Compaction（摘要替换）
     安全                    安全且自动             有信息损失风险
    省少                     省多                  省最多

原则：先用最轻量手段，不够再用重量级的。
```

---

## 十二、关键要点总结

1. **Context Editing ≠ Compaction**：Editing 是选择性清除（手术刀），Compaction 是全量摘要替换（回收站）
2. **Tool Result Clearing 是最安全的压缩手段**——只删除已消化过的工具结果，用占位符替换
3. **`clear_at_least` 是为 Prompt Caching 设计的**——确保拆缓存的代价值得
4. **`clear_tool_inputs` 默认 false**——保留推理意图（调用参数），只清结果
5. **Extended Thinking 默认只保留最近 1 轮 thinking**——`clear_thinking` 策略是在覆盖这个默认行为
6. **`keep` 参数是缓存 vs 空间的权衡**：`"all"` 最大化缓存，`1` 最大化空间
7. **组合策略时 thinking clearing 必须排在前面**
8. **服务端执行，客户端无需同步**——始终维护完整历史，API 自动视图裁剪
9. **Memory Tool + Tool Result Clearing 是黄金组合**——清除前自动保存重要信息
10. **客户端 Compaction 绑定在 `tool_runner` 上**——不用 `tool_runner` 就不会碰到它
11. **客户端 Compaction 唯一优势**：可用便宜模型（Haiku）为贵模型（Opus）做摘要，省约 9 倍
12. **客户端 Compaction 有 Server Tools token 陷阱**——`cache_read_input_tokens` 可能导致过早触发

---

*最后更新：2026-04-08*
