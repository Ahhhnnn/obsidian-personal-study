# Claude API Context Window 与 Extended Thinking 详解

> 文档来源：[Context Windows - Claude API Docs](https://docs.anthropic.com/en/docs/build-with-claude/context-windows)
> 整理日期：2026-04-02

---

## 一、Context Window 基础概念

	### 1.1 什么是 Context Window

Context Window（上下文窗口）是模型的**工作记忆**——模型在单次请求中能"看到"的全部内容，包括：

- 系统提示词（System Prompt）
- 所有历史对话消息
- 工具定义（Tools）
- 当前请求的输出（包括 Thinking Tokens）

它与训练数据（Training Data）完全不同。训练数据是模型学习过的海量语料，而 Context Window 是每次 API 调用时模型的"临时工作台"。

### 1.2 各模型的 Context Window 大小

| 模型 | Context Window |
|------|---------------|
| Claude Opus 4.6 | **1M tokens** |
| Claude Sonnet 4.6 | **1M tokens** |
| Claude Sonnet 4.5 | 200k tokens |
| Claude Sonnet 4 | 200k tokens |
| Claude Haiku 4.5 | 200k tokens |

单个请求最多可包含 **600 张图片或 PDF 页面**（200k 模型限制为 100 张）。发送大量图片/文档时，可能先达到请求大小限制而非 token 限制。

### 1.3 线性增长与 Context Rot

每个 turn 的输入输出都会**完整保留**并累积到 context 中，呈现线性增长模式：

```
Turn 1: [User₁] → [Assistant₁]                        = N tokens
Turn 2: [User₁][Assistant₁][User₂] → [Assistant₂]    = 2N+ tokens
Turn 3: ...                                            = 3N+ tokens
```

**核心洞察：更多 context 不等于更好。**

随着 token 数量增长，模型会出现 **Context Rot（上下文腐烂）**——准确率和召回率逐渐下降。Claude 在长上下文检索基准测试（如 MRCR、GraphWalks）上取得了 SOTA 结果，但这些优势依赖于 context 中放的是什么内容，而不仅仅是能装多少。

> **因此，管理 context 中放什么和管理有多少空间可用，同样重要。**
>
> 深入了解：[Effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)

---

## 二、Extended Thinking（扩展思考）

### 2.1 核心机制

Extended Thinking 让 Claude 在回答前先进行一段"内心独白"——类似人类回答复杂问题前先打草稿。这段思考过程消耗额外的 output tokens，但能显著提升推理质量。

**关键参数说明：**

- `thinking.budget_tokens` 是 `max_tokens` 参数的**子集**，不是额外增加的
- Thinking tokens 按 **output tokens** 计费
- 开启 **Adaptive Thinking** 后，Claude 会动态决定每轮的思考量，实际用量可能不同

### 2.2 无工具调用场景

#### 单轮对话

```
User: "请分析这段代码的时间复杂度"

API Response:
  ├── thinking block (50k tokens)    ← 思考过程，计费一次
  └── text block (2k tokens)         ← 最终回答

Context Window 消耗 = input_tokens + 50k(thinking) + 2k(text)
```

#### 多轮对话 — 自动剥离机制

这是 Extended Thinking 最精妙的架构设计之一。在多轮对话中，**之前所有轮次的 thinking blocks 会被 API 自动剥离**，不占用后续轮次的 context 空间：

```
╔══════════════════════════════════════════════════════════════╗
║  Turn 1                                                     ║
║  Input:  [User Message 1]                                   ║
║  Output: [Thinking Block 🧠 100k] + [Text Response 1]      ║
║  Context 消耗: input + 100k(thinking) + text               ║
╠══════════════════════════════════════════════════════════════╣
║  Turn 2                                                     ║
║  Input:  [User1] + [Text Response 1] + [User Message 2]    ║
║          ⚠️ Thinking Block 被 API 自动剥离，不传入模型！      ║
║  Output: [Thinking Block 🧠 80k] + [Text Response 2]       ║
║  Context 消耗: input(不含上轮thinking) + 80k + text         ║
╠══════════════════════════════════════════════════════════════╣
║  Turn 3                                                     ║
║  Input:  [User1][Text1][User2][Text2][User3]                ║
║          ⚠️ Turn2 的 Thinking 同样被自动剥离                ║
║  Output: [Thinking Block 🧠 60k] + [Text Response 3]       ║
╚══════════════════════════════════════════════════════════════╝
```

**关键规则：**

- 你传回 thinking blocks 也行，API 会自动帮你**剥离**后再传给模型
- 你不传 thinking blocks 也行，完全没影响
- 每轮都能生成**新的** thinking block
- 计费只发生在**生成那一轮**，后续轮次不重复计费

**有效 Context Window 计算：**

```python
effective_context = (input_tokens - all_previous_thinking_tokens) + current_turn_tokens
```

> 这意味着即使每轮思考 10 万 token，下一轮这些空间全部释放，**不会累积浪费**。

### 2.3 有工具调用场景（三阶段模型）

这是文档中最复杂也最容易出错的部分。工具调用引入了"工具调用周期"的概念，thinking block 的处理规则在周期不同阶段完全不同。

#### 完整三阶段流程

```
╔═══════════════════════════════════════════════════════════════════╗
║  阶段一：发起工具调用                                              ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  Input:  [Tools定义] + [User Message]                              ║
║  Output: [Thinking🧠] + [Text] + [Tool Use Request 🔧]           ║
║          ─────────────────────────────────────────                 ║
║          全部计入 context，全部按 output 计费                       ║
║                                                                   ║
║  Context: tools + user_msg + thinking + text + tool_request       ║
╚═══════════════════════════════════════════════════════════════════╝
                              │
                              ▼
╔═══════════════════════════════════════════════════════════════════╗
║  阶段二：返回工具结果                                              ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  Input:  [Thinking🧠 必须保留!] + [Text] + [Tool Request]         ║
║          + [Tool Result 📦]                                       ║
║          ─────────────────────────────────────────                 ║
║          ⚠️ 这是唯一必须保留 thinking block 的场景！               ║
║                                                                   ║
║  Output: [Text only] ← 注意：没有新的 thinking block              ║
║                                                                   ║
║  Context: thinking + text + tool_req + tool_result + new_text    ║
╚═══════════════════════════════════════════════════════════════════╝
                              │
                              ▼
╔═══════════════════════════════════════════════════════════════════╗
║  阶段三：周期结束，进入下一轮对话                                   ║
╠═══════════════════════════════════════════════════════════════════╣
║                                                                   ║
║  Input:  [所有input] + [阶段二的Text] + [新的User Message]        ║
║          ─────────────────────────────────────────                 ║
║          Thinking🧠 可以丢弃了（工具调用周期已结束）               ║
║          API 也会自动帮你剥离                                      ║
║                                                                   ║
║  Output: [New Thinking🧠] + [Text Response]                      ║
║          ← 新的 user turn 触发新的 thinking                       ║
║                                                                   ║
║  Context: 所有input(无thinking) + new_thinking + text             ║
╚═══════════════════════════════════════════════════════════════════╝
```

#### 阶段二必须保留 Thinking Block 的原因

两个关键原因：

1. **推理连贯性**：Claude 在发起工具调用前已经形成了一条推理链（例如："我需要查数据库 → 查什么字段 → 怎么分析结果"）。返回工具结果时，如果丢失了这条推理链，Claude 就像失忆了一样，无法将结果与原始推理对接。

2. **加密签名验证**：Thinking block 包含密码学签名（`signature` 字段），API 会验证其真实性。任何修改（哪怕一个字符）都会导致 API 返回错误。

#### 阶段二的 Messages 结构示例

```json
{
  "messages": [
    {
      "role": "user",
      "content": "帮我查北京天气"
    },
    {
      "role": "assistant",
      "content": [
        {
          "type": "thinking",
          "thinking": "用户问天气，我需要调用天气工具...",
          "signature": "ErUB6p...（加密签名）"
        },
        {
          "type": "text",
          "text": "我来帮你查一下"
        },
        {
          "type": "tool_use",
          "id": "toolu_01",
          "name": "get_weather",
          "input": { "city": "北京" }
        }
      ]
    },
    {
      "role": "user",
      "content": [
        {
          "type": "tool_result",
          "tool_use_id": "toolu_01",
          "content": "北京今天25°C，晴"
        }
      ]
    }
  ]
}
```

#### 多次连续工具调用的处理

如果 Claude 在一个周期内连续调用多个工具：

```
Turn 1: User → [Thinking🧠] + ToolCall_A
Turn 2: [Thinking🧠保留] + ToolResult_A → ToolCall_B     ← 还在周期内
Turn 3: [Thinking🧠保留] + ToolResult_B → ToolCall_C     ← 还在周期内
Turn 4: [Thinking🧠保留] + ToolResult_C → FinalText       ← 周期结束
Turn 5: [Thinking🧠可丢弃] + NewUser → [NewThinking🧠]   ← 新周期开始
```

**规则：在整个工具调用周期内，最开始那个 thinking block 必须一直保留。** 直到收到新的 `user` 消息（非 `tool_result` 类型），周期才算结束。

#### 无工具调用 vs 有工具调用对比

```
                    无工具调用              有工具调用
─────────────────────────────────────────────────────────
Thinking 保留？     从不需要保留           阶段二必须保留
                                          （在工具调用周期内）
自动剥离时机       每轮自动剥离           工具调用周期结束后才剥离
篡改 Thinking      无所谓（反正被剥离）    ❌ 绝对不行！
                                          有加密签名验证
Context 计算       减去所有历史 thinking   阶段二不减（需保留）
                                          阶段三减去（周期结束）
```

### 2.4 Claude 4 的改进：Interleaved Thinking（交织思考）

Claude 4 系列模型支持 **Interleaved Thinking**，是对上述三阶段模型的重要增强：

```
Claude Sonnet 3.7（不支持交织）:
  User → Thinking → ToolCall → ToolResult → Text（无thinking）
  必须等到新 user turn 才能再次 thinking

Claude 4 系列（支持交织）:
  User → Thinking → ToolCall → ToolResult → Thinking → ToolCall → ...
  在工具调用周期内也能继续 thinking！
```

这意味着 Claude 4 可以在收到工具结果后**继续深入推理**，而不是直接跳到下一个操作，推理质量更高。

> 注意：Claude Sonnet 3.7 **不支持** Interleaved Thinking，两次 thinking 之间必须有非 `tool_result` 的 user turn。

---

## 三、Context Awareness（上下文感知）

### 3.1 支持的模型

Claude Sonnet 4.6、Claude Sonnet 4.5、Claude Haiku 4.5 具备 Context Awareness 能力。

### 3.2 工作机制

模型能**感知自己的 token 预算**，知道还剩多少空间可用：

```xml
<!-- 对话开始时，告知总预算 -->
<budget:token_budget>1000000</budget:token_budget>

<!-- 每次工具调用后，更新剩余容量 -->
<system_warning>Token usage: 35000/1000000; 965000 remaining</system_warning>
```

### 3.3 解决的问题

之前模型不知道自己还剩多少 token——就像参加烹饪比赛但没有计时器。现在模型能精确规划：是继续深入任务，还是开始收尾。

### 3.4 适用场景

- **长时间运行的 Agent 会话**：需要持续关注任务进度
- **跨 Context Window 的工作流**：状态转换需要精确管理
- **复杂任务**：需要精细的 token 管理

> **提示**：对于跨多个 session 的 agent，应设计好状态持久化方案，让新 session 能快速恢复 context。参考 [memory tool 的 multi-session 模式](https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/memory-tool#multi-session-software-development-pattern)。

---

## 四、Context 管理策略

### 4.1 三层策略体系

从轻到重，文档提供了三层管理策略：

| 策略 | 适用场景 | 复杂度 | 说明 |
|------|---------|--------|------|
| **Server-side Compaction** | 长对话自动压缩 | 低（服务端自动） | 推荐首选，目前 Beta，仅 Opus 4.6 和 Sonnet 4.6 |
| **Tool Result Clearing** | 清理旧的工具返回结果 | 中 | 在 agentic 工作流中清理不再需要的 tool_result |
| **Thinking Block Clearing** | 管理 thinking blocks | 中 | 手动清理 thinking blocks 释放空间 |

### 4.2 溢出处理

新版模型（Sonnet 3.7+）的行为变更：

- **旧行为**：静默截断超出 context 的内容
- **新行为**：返回**验证错误**

这意味着需要更主动地管理 token 用量。可以使用 [Token Counting API](https://docs.anthropic.com/en/docs/build-with-claude/token-counting) 在发送请求前预估用量。

### 4.3 实践建议速查

| 场景 | 建议操作 |
|------|---------|
| 构建长对话 Agent | 优先使用 Compaction，突破 context 限制 |
| 使用 Extended Thinking | 放心让模型深度思考，不会浪费后续 context |
| 工具调用中返回 tool_result | **必须**原封不动传回 thinking block（含 signature） |
| 工具调用周期结束 | 可以丢弃 thinking，或不管它让 API 自动剥离 |
| 手动清理 thinking | 仅在工具调用周期外安全，周期内绝对不能动 |
| 使用 Claude 4 模型 | 利用 Interleaved Thinking 获得更强的推理能力 |
| 多 Session Agent | 设计状态持久化方案，确保 context 快速恢复 |

---

## 五、关键要点总结

1. **Context Window 是工作记忆**，不是训练数据；大小有限，需要精心管理
2. **Context Rot 是真实问题**：token 越多，准确率越低，内容管理比容量更重要
3. **Extended Thinking 的自动剥离**是多轮对话的救星：每轮思考不会累积浪费 context
4. **工具调用场景下 Thinking 必须保留**：直到整个工具调用周期结束才能丢弃
5. **Thinking Block 有加密签名**，任何篡改都会导致 API 报错
6. **Claude 4 的 Interleaved Thinking** 打破了"工具调用周期内不能 thinking"的限制
7. **Context Awareness** 让模型像有计时器一样，知道还剩多少空间
8. **Compaction 是推荐的首选策略**，服务端自动处理，集成成本低
