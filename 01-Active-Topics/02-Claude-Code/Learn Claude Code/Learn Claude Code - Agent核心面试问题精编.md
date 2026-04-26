# Agent 开发核心面试问题精编

> 基于 learn-claude-code 项目提炼，直指 Agent 开发核心与本质

---

## 一、本质与哲学 (The Fundamentals)

### Q1: 什么是 Agent？它的核心本质是什么？

**核心考察**: 对 Agent 最本质的理解，能否剥离表象看内核

**参考回答**:
```
Agent = LLM + Tools + Loop

但这个公式只是表象。本质上是：

Agent 是一个能够"感知-决策-行动-观察"的自主系统。

让我用更本质的方式描述：

1. **感知**: LLM 理解用户意图和当前状态
2. **决策**: 基于理解选择下一步行动（调用工具）
3. **行动**: 执行工具，与外部世界交互
4. **观察**: 将执行结果反馈回 LLM，形成闭环

所以 Agent 的本质是：**将 LLM 的推理能力与外部世界的执行能力连接起来的反馈循环**。

这个循环有三个关键特征：
- **自主性**: LLM 自己决定下一步做什么
- **适应性**: 根据执行结果调整策略
- **目标性**: 循环直到达成目标（stop_reason != tool_use）

这也是 Agent 和传统程序的最大区别：传统程序是"你告诉它每一步做什么"，Agent 是"你告诉它目标，它自己探索怎么做"。
```

**追问方向**:
- Agent 和自动化脚本的区别？
- Agent 和 Chatbot 的边界在哪里？
- 为什么说 Loop 是 Agent 的灵魂？

---

### Q2: 为什么 Agent 需要 Loop？不能一次性完成吗？

**核心考察**: 对反馈循环必要性的理解

**参考回答**:
```
因为现实世界的问题无法一次性解决。

让我从三个角度解释：

**1. 信息不对称**
用户说"修复这个 bug"时：
- LLM 不知道代码在哪里 → 需要执行 find 命令
- 找到后不知道内容 → 需要执行 read 命令
- 看到后不确定根因 → 可能需要运行测试

每次执行都获得新信息，这些信息影响下一次决策。

**2. 试错与迭代**
LLM 的决策可能：
- 选错工具（用 grep 而不是 find）
- 参数错误（路径不对）
- 依赖问题（需要先安装包）

没有 Loop，一次失败就结束了。有 Loop，失败只是反馈的一部分。

**3. 复杂任务分解**
"部署应用到生产环境"涉及：
1. 检查当前状态
2. 运行测试
3. 构建镜像
4. 推送到仓库
5. 更新 K8s 配置
6. 验证部署

每一步的输出决定下一步怎么做。中间可能失败、回滚、重试。

**本质**: Loop 让 Agent 从"一次性预测"变成"持续适应的智能体"。

这是生物智能的模拟：感知→决策→行动→反馈→再决策...
```

**追问方向**:
- Loop 的终止条件如何设计？
- 如何防止无限循环？
- Loop 和递归的区别？

---

### Q3: Tool 在 Agent 中的角色是什么？为什么需要 Tool？

**核心考察**: 对 Tool 本质的理解，而非表面功能

**参考回答**:
```
Tool 是 Agent 的"手"和"感官"。

**LLM 的局限**:
- 只能训练时的知识，不知道实时信息
- 只能生成文本，不能执行操作
- 只能推理，不能验证

**Tool 的价值**:

1. **扩展感知能力**
   - read_file: "看"到文件内容
   - search: "搜索"互联网信息
   - get_weather: "感知"当前天气

2. **扩展行动能力**
   - bash: 执行任何命令
   - write_file: 修改代码
   - send_email: 发送邮件

3. **桥接数字与物理世界**
   - API 调用: 与其他服务交互
   - IoT 控制: 操作智能设备
   - 机器人控制: 移动机械臂

**本质**: Tool 将 LLM 从"文本生成器"变成"世界交互者"。

没有 Tool，LLM 只能"谈论"世界。
有了 Tool，LLM 可以"改变"世界。

这也是 Tool 和普通函数的区别：
- 普通函数: 参数确定，输出确定
- Tool: LLM 自主决定何时调用、用什么参数、调用几次

这个"自主决策"才是 Tool 的核心。
```

**追问方向**:
- Tool 的参数验证重要吗？
- 如何设计 Tool 的 description？
- Tool 的错误如何处理？

---

## 二、核心机制 (Core Mechanisms)

### Q4: messages 数组在 Agent Loop 中扮演什么角色？为什么不断追加？

**核心考察**: 对上下文管理的理解

**参考回答**:
```
messages 数组是 Agent 的"短期记忆"和"思维链"。

**它的作用**:

1. **维护对话上下文**
   - 用户最初的意图
   - LLM 的所有决策过程
   - 所有工具调用的结果

2. **支持推理链**
   LLM 需要知道：
   - "我之前调用了 bash 'ls'"
   - "结果是 main.py, utils.py"
   - "所以我下一步应该读取 main.py"

3. **实现反馈循环**
   每次追加 = 一次新的观察
   LLM 基于完整的观察历史做决策

**为什么不断追加而不是替换？**

因为 LLM 是"上下文学习者"，它需要完整的序列：
```
[用户: "修复 bug"]
  ↓
[LLM: 我先看看文件 → 调用 read]
  ↓
[read 结果: "代码是这样..."]
  ↓
[LLM: 我看到问题了 → 调用 edit]
  ↓
[edit 结果: "修改成功"]
  ↓
[LLM: 我再验证一下 → 调用 test]
```

如果你删掉中间的 read 结果，LLM 就不知道为什么要 edit。

**本质**: messages 数组是 Agent 的"意识流"，记录了它思考的所有过程。

这也带来了挑战：
- 越来越长 → 需要 context compact (s06)
- 压缩丢失细节 → 需要 task system (s07) 持久化
```

**追问方向**:
- messages 的上限是多少？
- 如何精简 messages 而不丢失关键信息？
- RAG 和 messages 的关系？

---

### Q5: stop_reason 是什么？为什么它是 Loop 的终止条件？

**核心考察**: 对控制流的理解

**参考回答**:
```
stop_reason 是 LLM 告诉我们"我话还没说完/我做完了"的信号。

**Claude API 的 stop_reason 类型**:
- `tool_use`: "我还要继续调用工具" → 继续 Loop
- `end_turn`: "我说完了，不需要更多工具" → 退出 Loop
- `max_tokens`: "我达到输出上限了" → 退出或继续

**为什么它是终止条件？**

因为只有 LLM 知道自己是否完成任务：
- 如果 LLM 说"我要用 bash"，我们必须执行后给它结果
- 如果 LLM 说"修复完成"，我们应该结束并返回

**这个设计的巧妙之处**:

1. **LLM 自主控制**
   不是我们告诉 LLM"只能用3次工具"
   而是 LLM 自己决定"我需要用几次工具"

2. **灵活适应任务复杂度**
   - 简单任务: 1 次工具调用
   - 复杂任务: 10+ 次工具调用
   - LLM 自己调整

3. **自然对话终止**
   LLM 说"完成了"就像人说"我做完了"
   而不是计数器到 0 强制停止

**但这也带来风险**:
- LLM 可能陷入死循环
- 需要兜底机制: max_iterations, timeout

**本质**: stop_reason 是 LLM 和运行时的"协议"，定义了循环的语义。
```

**追问方向**:
- 如何检测 LLM 陷入循环？
- max_iterations 设多少合适？
- 如果 stop_reason 是 max_tokens 怎么办？

---

### Q6: Subagent 的核心价值是什么？什么时候应该用？

**核心考察**: 对上下文隔离的理解

**参考回答**:
```
Subagent 的核心价值是**上下文隔离**。

**问题场景**:
你问 Agent："这个项目用什么测试框架？"

Agent 的执行过程：
1. ls → 看到 10 个文件
2. read setup.py → 看到依赖
3. read pytest.ini → 找到 pytest
4. read tox.ini → 确认是 pytest
5. 返回："用的是 pytest"

如果这些步骤都在主 messages 里，你的上下文就被污染了：
- 下次对话时，LLM 要重新处理这些信息
- 浪费 token，噪音干扰

**Subagent 的解决方案**:
```
主 Agent: "用一个子任务去查测试框架"
  ↓
Subagent: [全新上下文] → 执行上面 5 步
  ↓
Subagent: 返回 "pytest"
  ↓
主 Agent: 收到 "pytest"，上下文干净
```

**什么时候用 Subagent？**

✅ **适合**:
- 探索性任务（搜索、查找）
- 信息聚合（读多文件总结）
- 独立子任务（不依赖主上下文）

❌ **不适合**:
- 需要主上下文信息的任务
- 需要共享状态的任务
- 简单到不值得的开销

**本质**: Subagent 是"用完即丢"的一次性助手，用新上下文换主上下文的干净。

**但注意**: Subagent 不是万能的：
- 无法访问主对话历史
- 无法与主 Agent 共享状态
- 调用有额外开销（一次新的 LLM 调用）
```

**追问方向**:
- Subagent 和缓存有什么区别？
- Subagent 可以嵌套吗？
- 如何监控 Subagent 的执行？

---

## 三、状态与记忆 (State & Memory)

### Q7: 为什么需要 Context Compact？不压缩会怎样？

**核心考察**: 对上下文窗口限制的理解

**参考回答**:
```
因为 LLM 的上下文窗口是有限的。

**问题**:
假设你的 Agent 跑了 100 轮：
- 每轮调用 2 个工具
- 每个工具返回 1000 tokens
- 100 轮 × 2 × 1000 = 200,000 tokens

但 Claude 的上下文窗口是 200K，你还没开始新对话就满了。

**不压缩的后果**:
1. **无法继续对话**: API 返回错误
2. **速度变慢**: 每个 token 都要处理
3. **成本增加**: 按输入 token 计费

**Context Compact 的本质**: "战略遗忘"

保留什么？丢弃什么？

✅ **保留**:
- 当前目标
- 最近的操作（3-5 轮）
- 关键决策
- 当前状态

❌ **丢弃**:
- 中间步骤的详细输出
- 已读取的文件内容
- 临时调试信息

**三层策略的智慧**:
- Layer 1 (micro_compact): 无感渐进，每次只清理一点点
- Layer 2 (auto_compact): 触发式，超过阈值才压缩
- Layer 3 (manual): LLM 自己决定什么时候需要压缩

**本质**: Compact 是在"信息完整性"和"上下文限制"之间的平衡艺术。

这是一个工程问题，不是技术问题：
- 压缩太少 → 很快又满
- 压缩太频繁 → 丢失太多信息
- 压缩太狠 → Agent 忘记了重要细节
```

**追问方向**:
- 压缩后的信息如何恢复？
- 压缩会导致 Agent 行为不一致吗？
- 有没有办法不用压缩？

---

### Q8: Task System 和 TodoManager 的本质区别是什么？

**核心考察**: 对状态持久化的理解

**参考回答**:
```
本质区别：**易失性 vs 持久性**

| 维度 | TodoManager (s03) | TaskManager (s07) |
|------|------------------|-------------------|
| 存储 | 内存（字典） | 磁盘（JSON 文件） |
| 生命周期 | 程序结束丢失 | 程序重启保留 |
| 结构 | 扁平列表 | DAG（依赖图） |
| 关系 | 无 | blockedBy/blocks |
| 多 Agent | 单 Agent 独占 | 多 Agent 共享 |

**为什么需要持久化？**

场景 1: 上下文压缩
- Agent 跑了 50 轮，触发 compact
- messages 被压缩成摘要
- 但任务状态在磁盘，不会丢失

场景 2: 程序崩溃
- Agent 执行到一半崩溃
- 重启后从磁盘恢复任务
- 可以继续未完成的工作

场景 3: 多 Agent 协作
- Agent A 创建任务
- Agent B 认领任务
- Agent C 完成任务
- 需要共享状态

**DAG 的价值**:

```
扁平清单:
- [ ] task A
- [ ] task B
- [ ] task C

无法知道:
- 谁先谁后？
- 有依赖吗？
- 能并行吗？

DAG:
- [ ] task A
- [ ] task B (blockedBy: [A])
- [ ] task C (blockedBy: [A])
- [ ] task D (blockedBy: [B, C])

可以知道:
- A 先做
- B 和 C 可以并行
- D 等待 B 和 C 完成
```

**本质**: Task System 将"Agent 的记忆"从 LLM 的上下文中解放出来，变成独立的外部状态。

这让 Agent 可以：
- 跨越上下文压缩存活
- 与其他 Agent 协作
- 从崩溃中恢复
```

**追问方向**:
- 什么时候用 Todo，什么时候用 Task？
- DAG 如何防止循环依赖？
- 如何保证多 Agent 并发安全？

---

### Q9: 多个 Agent 如何协作？为什么需要 Team？

**核心考察**: 对协作模式的理解

**参考回答**:
```
多 Agent 协作的核心是**通信机制**。

**协作模式演进**:

```
s04 Subagent: 一次性父子关系
  ↓
s09 Teammate: 持久化队友 + inbox 通信
  ↓
s11 Autonomous: 队友自己找活干
```

**为什么需要 Team？**

场景：你需要构建一个复杂功能，涉及：
- 后端开发
- 前端开发
- 测试编写
- 文档撰写

**单 Agent 的问题**:
- 上下文切换频繁（一会后端，一会前端）
- 不可能同时精通所有领域
- 无法并行工作

**多 Agent 的价值**:
```
Lead: "构建用户认证功能"
  ↓
Coder (队友1): 实现后端 API
  ↓
Frontender (队友2): 实现登录页面
  ↓
Tester (队友3): 编写测试用例
  ↓
并行执行，通过 inbox 同步
```

**通信机制**: JSONL inbox

```python
# 发送消息
inbox/alice.jsonl:
  {"from": "bob", "content": "API ready at /api/login"}

# 读取消息
def read_inbox(name):
    messages = parse_jsonl(f"inbox/{name}.jsonl")
    clear_file(f"inbox/{name}.jsonl")  # drain
    return messages
```

**本质**: Team 让 Agent 从"独狼"变成"团队"，通过消息传递实现协作。

这带来了：
- **并行性**: 多个任务同时进行
- **专业化**: 每个 Agent 专注一个领域
- **容错性**: 一个失败不影响其他
- **可扩展性**: 轻松添加新队友

但也带来了复杂度：
- 需要协议（s10）
- 需要协调（谁来做什么？）
- 需要容错（队友失败怎么办？）
```

**追问方向**:
- inbox 和消息队列有什么区别？
- 如何防止队友冲突？
- 团队规模上限是多少？

---

```
## 四、工程实践 (Engineering)

### Q10: 如何防止 Agent 陷入无限循环？

**核心考察**: 对控制流安全的理解

**参考回答**:
无限循环是 Agent 的高频问题，需要多层防护。

**问题类型**:

1. **真·无限循环**: LLM 重复调用同一工具
   ```
   bash: "ls" → 返回结果
   bash: "ls" → 返回结果
   bash: "ls" → ...
   ```

2. **假·死循环**: LLM 在两个选项间摇摆
   ```
   尝试方案 A → 失败
   尝试方案 B → 失败
   回到方案 A → ...
   ```

3. **状态停滞**: LLM 重复无效操作
   ```
   运行测试 → 失败
   运行测试 → 失败
   运行测试 → ...
   ```

**防护机制**:

**第一层: 最大迭代次数**
```python
MAX_ITERATIONS = 50
for i in range(MAX_ITERATIONS):
    response = llm_call()
    if response.stop_reason != "tool_use":
        break
```

**第二层: 超时保护**
```python
import time
start = time.time()
while time.time() - start < TIMEOUT_SECONDS:
    # agent loop
```

**第三层: 循环检测**
```python
# 检测重复的工具调用模式
recent_calls = messages[-10:]  # 最近 10 次
if len(set(c.tool_name for c in recent_calls)) <= 2:
    # 只用了 1-2 个工具，可能陷入循环
    inject_message("你似乎在重复操作，请尝试其他方法")
```

**第四层: 状态检测**
```python
# 检测是否有进展
def has_progress(messages):
    # 比较最近的状态是否有变化
    # 例如：文件是否被修改、测试是否通过
    pass

if not has_progress(recent_messages):
    return "无进展，可能需要人工介入"
```

**第五层: LLM 自我觉察**
```python
# 在 system prompt 中提醒
SYSTEM = """
如果你发现自己陷入重复操作，请：
1. 停止当前方法
2. 分析为什么失败
3. 尝试完全不同的方案
4. 或者请求人工帮助
"""
```

**本质**: 防止无限循环需要多层防护，就像安全网：
- 第一层拦截大多数情况
- 第二层处理边缘情况
- 第三、四、五层处理更复杂的情况

没有银弹，组合拳才有效。
```

**追问方向**:
- 如何区分"努力尝试"和"陷入循环"？
- max_iterations 设多少合适？
- 如何优雅地中断循环？

---
```
### Q11: Tool 执行失败时应该如何处理？

**核心考察**: 对错误处理的思考

**参考回答**:
Tool 失败是常态，不是异常。

**失败类型**:

1. **参数错误**: LLM 传了错参数
   ```
   read_file(path: "/non/exist/file")
   → Error: File not found
   ```

2. **权限错误**: 操作不被允许
   ```
   bash("rm -rf /")
   → Error: Dangerous command blocked
   ```

3. **执行错误**: 工具本身失败
   ```
   bash("pytest")
   → Error: Tests failed with exit code 1
   ```

4. **超时错误**: 执行时间过长
   ```
   bash("npm install")
   → Error: Timeout (120s)
   ```

**处理策略**:

**策略 1: 返回错误，让 LLM 决策**
```python
try:
    output = handler(**args)
except Exception as e:
    output = f"Error: {e}"  # 作为 tool_result 返回

# LLM 收到错误后：
# - 可能重试
# - 可能换方法
# - 可能放弃
```

**策略 2: 特定错误特殊处理**
```python
if "timeout" in str(error):
    return "操作超时，可以尝试：1) 用后台执行 2) 分批处理"
elif "permission denied" in str(error):
    return "权限不足，需要检查文件权限或使用 sudo"
```

**策略 3: 自动重试（需谨慎）**
```python
MAX_RETRIES = 3
for attempt in range(MAX_RETRIES):
    try:
        return handler(**args)
    except TemporaryError as e:
        if attempt == MAX_RETRIES - 1:
            return f"Error after {MAX_RETRIES} attempts: {e}"
```

**策略 4: 降级方案**
```python
# 工具失败时，用替代方法
def search_code(query):
    try:
        return ripgrep_search(query)
    except Exception:
        # ripgrep 失败，用 grep
        return grep_search(query)
```

**关键原则**:

1. **永远不要吞掉错误**: 返回给 LLM，让它知道发生了什么
2. **错误信息要可操作**: 不只是"失败了"，要告诉 LLM 怎么办
3. **区分可重试和不可重试**: 临时错误重试，逻辑错误不重试
4. **保护系统资源**: 限制重试次数、超时、资源占用

**本质**: 错误处理不是"如何避免错误"，而是"如何从错误中恢复"。

LLM 的强大之处就是它能理解错误、调整策略、重新尝试。
```

**追问方向**:
- 如何判断错误是否可重试？
- 错误信息如何设计才对 LLM 友好？
- 如何防止 LLM 陷入"重试循环"？

---

### Q12: 如何设计 Tool 的 description？

**核心考察**: 对 Prompt 工程的理解

**参考回答**:
```
Tool 的 description 是 LLM 唯一了解这个工具的途径，至关重要。

**好的 description 要素**:

1. **清晰的功能说明**
   ❌ "读取文件"
   ✅ "读取文件内容，用于检查代码、查看配置"

2. **明确的使用场景**
   ❌ "运行命令"
   ✅ "执行 shell 命令，用于运行测试、安装依赖、查看系统信息"

3. **关键参数说明**
   ❌ "path: 文件路径"
   ✅ "path: 要读取的文件路径，支持相对路径和绝对路径"

4. **限制和注意事项**
   ❌ "bash: 执行命令"
   ✅ "bash: 执行 shell 命令。注意：危险命令会被阻止，有 120s 超时"

**对比示例**:

```python
# 差的 description
{
    "name": "search",
    "description": "搜索代码",
    "input_schema": {...}
}

# 好的 description
{
    "name": "search",
    "description": "在代码库中搜索文本或正则表达式。"
                "用于查找函数定义、变量使用、错误来源等。"
                "支持 grep 风格的正则，返回匹配的文件和行号。",
    "input_schema": {...}
}
```

**高级技巧**:

1. **说明返回格式**
   ```
   返回格式：每行一个匹配，格式为 "文件:行号:内容"
   ```

2. **给出使用示例**
   ```
   示例：search("def main") 查找 main 函数定义
   ```

3. **对比其他工具**
   ```
   与 find_files 的区别：search 搜索内容，find_files 搜索文件名
   ```

4. **说明性能特征**
   ```
   注意：大型仓库搜索可能较慢，建议先缩小范围
   ```

**本质**: description 是你和 LLM 的"契约"。

你告诉 LLM 这个工具做什么、怎么用、有什么限制。
LLM 根据这个信息决定何时调用、用什么参数。

写好 description = 提高 LLM 使用工具的准确率。
```

**追问方向**:
- description 太长会影响 LLM 吗？
- 如何描述有副作用的工具？
- 如何让 LLM 优先使用某些工具？

---

## 五、架构设计 (Architecture)

```
### Q13: 如何设计一个生产级的 Agent 系统？

**核心考察**: 架构思维和全局视野

**参考回答**:
生产级 Agent = 教学代码 + 企业级特性

让我从 8 个维度展开：

**1. 可观测性**
```python
# 三支柱：Logs, Metrics, Traces

# 结构化日志
logger.info("tool_called", tool_name="bash", duration_ms=123, success=True)

# 指标
metrics.increment("agent.tool_calls", tags={"tool": "bash"})
metrics.timing("agent.llm_latency", 500)

# 追踪
with tracer.span("agent_loop"):
    with tracer.span("tool_execution"):
        execute_tool()
```

**2. 安全性**
```python
# 沙箱执行
def run_bash_safely(command):
    # 使用 Docker 或 gvisor 隔离
    # 资源限制：CPU、内存、网络
    # 白名单：只允许特定命令

# 权限控制
def check_permission(agent, tool):
    if agent.role == "readonly":
        return tool in ["read_file", "search"]
    return True
```

**3. 可靠性**
```python
# 重试机制
@retry(max_attempts=3, backoff=exponential)
def llm_call():
    ...

# 状态恢复
def save_state():
    snapshot = {
        "messages": messages,
        "tasks": tasks,
        "checkpoint_time": time.time()
    }
    write_to_storage(snapshot)

def load_state():
    # 从断点恢复
    ...
```

**4. 性能优化**
```python
# 并行工具调用
parallel_tools = [bash, read_file, search]
results = await asyncio.gather(*[
    execute_tool(t) for t in parallel_tools
])

# 缓存
@lru_cache(maxsize=1000)
def read_file_cached(path):
    return read_file(path)

# 流式响应
for chunk in llm_stream():
    yield chunk
```

**5. 扩展性**
```python
# 插件系统
class Plugin:
    def register_tools(self):
        ...
    def on_task_complete(self, task):
        ...

# Hook 机制
hooks.register("pre_tool_use", validate_permission)
hooks.register("post_tool_use", log_metrics)
```

**6. 测试**
```python
# 单元测试
def test_tool_handler():
    result = run_bash("echo hello")
    assert result == "hello"

# 集成测试
def test_agent_loop():
    agent = Agent()
    response = agent.run("创建一个文件")
    assert os.path.exists("created_file")

# 混沌测试
def test_llm_failure():
    with mock_llm_failure():
        agent.run("do something")
        assert agent.has_fallback()
```

**7. 部署**
```python
# 容器化
# Dockerfile + K8s deployment

# 监控
# Prometheus + Grafana
# Loki for logs
# Jaeger for traces

# 告警
# Alertmanager: tool_failure_rate > 5%
```

**8. 运维**
```python
# 配置管理
# ConfigMap + Secrets

# 版本管理
# GitOps: Git → ArgoCD → K8s

# 故障排查
# Debug 模式：详细日志、追踪
# Replay 模式：重放历史对话
```

**本质**: 生产级 Agent 是系统工程问题，不只是代码问题。

需要考虑：
- 正常路径：功能实现
- 异常路径：错误处理、降级、恢复
- 边缘情况：资源限制、并发冲突、安全漏洞

就像造一辆车：
- 教学代码 = 能跑的原型车
- 生产级 = 经过测试、有安全带、有保险、可维修的车
```

**追问方向**:
- 哪些特性是最优先的？
- 如何平衡复杂度和开发速度？
- 如何渐进式从教学代码到生产级？

---
```
### Q14: 如何评估 Agent 的性能和质量？

**核心考察**: 对度量体系的理解

**参考回答**:
评估 Agent 需要多维度指标体系。

**1. 任务级指标**

```
成功率:
  - 完全成功: 完全达成目标
  - 部分成功: 达成部分目标
  - 失败: 未达成目标

效率:
  - 耗时: 从开始到完成的时间
  - Token 使用: 输入 + 输出 tokens
  - 工具调用次数: 总调用次数
  - 成本: Token 费用
  - 缓存命中率： 

质量:
  - 正确性: 输出是否正确
  - 健壮性: 遇到错误如何处理
  - 可维护性: 生成的代码质量
```

**2. 运行时指标**

```
性能:
  - LLM 延迟: p50, p95, p99
  - 工具延迟: 各工具的执行时间
  - 端到端延迟: 用户体验

资源:
  - CPU 使用率
  - 内存占用
  - 并发数
  - 队列长度

可靠性:
  - 错误率: 工具失败率、LLM 失败率
  - 可用性: 服务在线率
  - 恢复时间: MTTR
```

**3. 成本指标**

```
直接成本:
  - Token 费用
  - API 调用费用
  - 基础设施成本

间接成本:
  - 开发时间
  - 维护成本
  - 人力审查成本
```

**4. 用户满意度**

```
主观评价:
  - 评分: 1-5 星
  - 反馈: 文字反馈
  - NPS: 净推荐值

客观行为:
  - 使用频率
  - 留存率
  - 推荐率
```

**5. 如何测量**

```python
# 1. 自动化测试
test_cases = [
    ("创建 Python 文件", "创建文件", "验证文件存在"),
    ("运行测试", "执行 pytest", "检查测试结果"),
    ...
]

for task, input, verification in test_cases:
    result = agent.run(input)
    score = evaluate(result, verification)
    results.append(score)

# 2. A/B 测试
# 比较不同版本的 Agent

# 3. 人工评估
# 专家审查 Agent 的输出

# 4. 真实使用监控
# 收集生产环境数据
```

**本质**: 评估 Agent 是多目标优化问题。

没有单一指标，需要权衡：
- 成功 vs 成本
- 速度 vs 质量
- 自动化 vs 人工审查

关键是**找到对你最重要的指标，然后优化它**。
```

**追问方向**:
- 如何定义"成功"？
- 如何比较两个 Agent？
- 如何设定性能基准？

---
```
## 六、前沿思考 (Frontiers)

### Q15: Agent 的未来发展方向是什么？

**核心考察**: 对趋势的洞察力

**参考回答**:
我认为 Agent 有 5 个核心方向：

**1. 更强的规划能力**

当前 Agent 的局限：
- 短期规划：最多规划 5-10 步
- 调整困难：遇到新情况需要重新规划
- 优化不足：没有考虑效率

未来方向：
- 层次化任务网络 (HTN): 高层目标分解
- 强化学习: 从执行中学习规划策略
- Monte Carlo Tree Search: 搜索最优执行路径

**2. 更好的记忆系统**

当前 Agent 的局限：
- 短期记忆：messages 数组
- 长期记忆：没有跨会话记忆
- 知识记忆：依赖外部检索

未来方向：
- 向量数据库: 存储和检索历史对话
- 记忆网络: 动态记忆读写
- 知识图谱: 结构化知识记忆

**3. 多模态能力**

当前 Agent 的局限：
- 主要是文本输入输出
- 有限的图像理解
- 缺乏视频、音频处理

未来方向：
- 原生多模态 LLM: GPT-4V, Gemini
- 工具调用返回图像
- 视觉-语言-行动闭环

**4. 自我改进**

当前 Agent 的局限：
- 静态能力：无法从经验中学习
- 固定工具：无法创造新工具
- 被动执行：无法主动优化

未来方向：
- 元学习: 学习如何学习
- 工具生成: 自动创建新工具
- 自我反思: 分析失败并改进

**5. 协作生态**

当前 Agent 的局限：
- 单打独斗：一个 Agent 完成所有
- 固定角色：角色预定义
- 有限通信：inbox 协议简单

未来方向：
- Agent 市场: 买卖 Agent 服务
- 动态组队: 根据任务自动组建团队
- 协作协议: 标准化的 Agent 通信

**本质**: Agent 正从"工具"变成"伙伴"。

从你告诉它做什么 → 它自己规划、执行、学习、改进。

这不仅是技术进步，更是人机关系的重构。
```

**追问方向**:
- 哪个方向最有前景？
- 什么会最先实现？
- 最大的瓶颈是什么？

---
```

## 总结：这些问题的考察重点

| 问题类别    | 核心考察  | 对应会话    |
| ------- | ----- | ------- |
| Q1-Q3   | 本质理解  | s01-s02 |
| Q4-Q6   | 核心机制  | s01-s04 |
| Q7-Q9   | 状态管理  | s06-s09 |
| Q10-Q12 | 工程实践  | 全部      |
| Q13-Q15 | 架构与未来 | s09-s12 |

这些问题共同构建了一个完整的 Agent 知识体系：
- **是什么** (Q1-Q3)
- **怎么做** (Q4-Q6)
- **如何持久化** (Q7-Q9)
- **如何做好** (Q10-Q12)
- **如何做大规模** (Q13-Q15)

掌握这些问题，就掌握了 Agent 开发的核心要义。

---

*基于 learn-claude-code 项目整理*
*生成时间: 2026-03-15*
