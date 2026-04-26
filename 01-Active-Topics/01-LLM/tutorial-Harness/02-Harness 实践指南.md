# Harness 实践指南

> 基于 Anthropic、OpenAI、Martin Fowler、雪踏乌云四篇文章的实践提炼。
> 前置阅读：[[Harness Engineering 驾驭工程]]

---

## 一、实践全景图

```
你（人类工程师）
  │
  │  不是写代码，而是设计环境
  │
  ├─ 事前：Guides（引导）
  │   ├─ 项目知识库（文档、架构、约定）
  │   ├─ 规则文件（CLAUDE.md / AGENTS.md）
  │   └─ 代码模板与脚手架
  │
  ├─ 事中：执行编排
  │   ├─ 任务拆解与分配
  │   ├─ Agent 分工（规划器 / 生成器 / 评估器）
  │   └─ 上下文管理
  │
  └─ 事后：Sensors（感知）
      ├─ 自动化检查（Linter、测试、结构验证）
      ├─ Agent 审查（AI 评审 AI）
      └─ 人类审核（只在关键节点介入）
```

---

## 二、Guides 实践：事前预防

### 2.1 规则文件：给一张地图，不是一本百科全书

**反面教材：** 把所有规则塞进一个巨大的 `CLAUDE.md`。

**问题：**
- 巨大文件挤掉真正需要的上下文（代码、任务描述）
- 当所有规则都"重要"时，没有规则真正重要
- 大文件会腐烂——规则过时了但 agent 无法判断

**正确做法：**

```
CLAUDE.md（~100行）→ 只当"目录"
      ↓ 指向
docs/ 目录 → 结构化知识库
      ↓ 包含
架构文档、设计文档、执行计划、技术债务记录、编码规范
```

**你的 CLAUDE.md 应该长这样：**

```markdown
# 项目概况
这是一个 [什么项目]，使用 [技术栈]。

# 架构
- 详细架构文档见 docs/architecture.md
- 模块边界见 docs/module-boundaries.md

# 编码规范
- 详见 docs/coding-standards.md
- 核心规则：[只写 3-5 条最重要的]

# 工作流程
- 新功能开发：见 docs/how-to-feature.md
- Bug 修复：见 docs/how-to-bugfix.md

# 注意事项
- [最关键的禁忌，不超过 5 条]
```

**关键原则：** 渐进式披露。Agent 从小入口开始，被引导去需要的地方。

---

### 2.2 架构约束：agent 的氧气，不是枷锁

OpenAI 的发现：严格的架构分层在人类团队中通常需要数百人才值得推行，但对 agent 来说这是**早期先决条件**。

**具体做法：**

```
每个业务域内：
Types → Config → Repo → Service → Runtime → UI
（只能"向前"依赖，不能反向）

横切关注点（认证、遥测、功能标志）
→ 只能通过 Providers 的单一显式接口进入

其他一切 → 禁止，由自动化工具强制执行
```

**为什么对 agent 特别重要？**
- 人类工程师有直觉，知道"这团代码不该碰"
- Agent 没有直觉，只会模式匹配——没有硬约束，它会在百万行代码里复制任何模式，包括坏模式

**落地方式：** 用自定义 Linter + 结构测试（如 ArchUnit）机械执行。

---

### 2.3 Sprint Contract（冲刺合约）

Anthropic 的实践：在每个功能开工前，生成器和评估器先协商"什么叫做完"。

**你可以这样用：**

在给 agent 分配任务时，先让它写一份**完成定义**：

```markdown
## 任务：实现用户登录功能

### 完成标准（由 agent 提议，你审核）
1. 用户可以用邮箱 + 密码登录
2. 登录失败时显示具体错误信息（用户不存在 / 密码错误）
3. 连续失败 5 次锁定账号 15 分钟
4. 登录成功后跳转到 dashboard
5. 有对应的单元测试和集成测试
```

这比直接说"帮我做登录功能"效果好得多。

---

## 三、执行编排：事中管理

### 3.1 三种编排模式

根据任务复杂度选择：

| 模式                                  | 适用场景                                                                                                                  | 做法              |
| ----------------------------------- | --------------------------------------------------------------------------------------------------------------------- | --------------- |
| **Solo**                            | 简单、边界清晰的任务                                                                                                            | 单 agent 直接执行    |
| **Generator + Evaluator**           | 主观质量重要的任务（设计、文案）<br><br>比如：<br>1、文章生成 Agent 等，设计一个生成 Agent + 审查 Agent<br>2、报告撰写 Agent，设计一个生成报告的 Agent + 报告质量检查的 Agent | 一个生成，一个评审，循环迭代  |
| **Planner + Generator + Evaluator** | 复杂全栈应用                                                                                                                | 规划 → 开发 → 测试，多轮 |

---

### 3.2 GAN 式对抗循环（Anthropic 核心方法）

适用于设计、内容生成等主观质量重要的场景：

```
Generator（生成器）
  │ 产出初版
  ↓
Evaluator（评估器）
  │ 按评分标准打分 + 写详细批评
  ↓
Generator
  │ 根据反馈改进（分数趋势好→微调；不好→转向）
  ↓
Evaluator
  │ 再次评估
  ↓
  ... 循环 5-15 次
```

**评分标准的设计原则：**

| 原则          | 说明                                    |
| ----------- | ------------------------------------- |
| 主观→客观转化     | "设计美吗"→"设计是否遵循了我们的 4 条设计原则"           |
| 权重区分        | Claude 默认好的维度（如工艺）权重低，默认差的维度（如原创性）权重高 |
| 惩罚 AI 模式    | 明确惩罚"紫色渐变白卡片"等 AI 生成痕迹                |
| Few-shot 校准 | 给评估器几个带详细分数的样本，对齐你的品味                 |

---

### 3.3 上下文管理

| 策略 | 适用场景 | 做法 |
|---|---|---|
| **上下文压缩**（Compaction） | 中等任务、单 agent | 在同一 agent 内做摘要 |
| **上下文重置**（Reset） | 长任务、多 agent | 完全清空上下文，通过 handoff 文件传递状态 |

**Anthropic 的发现：** 上下文重置 > 上下文压缩。压缩保留了连续性但模型仍有"上下文焦虑"（接近上限时过早结束工作）。重置给模型干净的起点。

**Handoff 文件应该包含：**
- 当前项目状态（哪些已完成，哪些进行中）
- 关键决策及其理由
- 下一步待办
- 已知问题和风险

---

### 3.4 一功能一 Sprint

Anthropic 的经验：让 agent 一次做一个功能，做完评估，再做下一个。

**不要：** "帮我一次性把整个电商系统做完"
**要：** "先做用户注册功能"→ 验证通过 → "再做商品列表"→ 验证通过 → ...

**Sprint 的粒度：** 一个 agent 可能在单次运行中连续工作 2+ 小时（Opus 4.6），但仍需在功能边界处停下来接受评估。

---

## 四、Sensors 实践：事后纠错

### 4.1 Linter：最划算的 Sensor

OpenAI 的精妙设计——**Linter 报错信息中注入修复指令**：

```javascript
// 普通 Linter 报错：
// ❌ "Unexpected any. Use a specific type."

// 带修复指令的 Linter 报错：
// ❌ "Unexpected any. Replace with a specific type from types/domain.ts.
//    If no matching type exists, define a new one in types/domain.ts
//    following the pattern of existing types."
```

Agent 读到这条报错时，不需要猜测怎么改——指令已经告诉它了。

**构建成本：** 一次投入，所有未来运行永久受益。而且可以让 agent 帮你写 Linter 规则。

---

### 4.2 结构测试：守住架构边界

用工具（ArchUnit、dependency-cruiser）检查模块间的依赖方向：

```javascript
// dependency-cruiser 配置示例
module.exports = {
  forbidden: [
    {
      name: "no-ui-to-data-layer",
      comment: "UI 层不能直接访问数据层",
      from: { path: "src/ui/" },
      to:   { path: "src/data/" },
    },
  ],
};
```

比在文档里写"UI 层不能依赖数据层"有效 100 倍——因为 agent 会读代码，不会读你的心。

---

### 4.3 AI 审查 AI

OpenAI 的实践：随着时间推移，几乎所有审查都变成了 agent 对 agent。

```
Codex 本地自己审一遍
  ↓
请求其他 agent 审查
  ↓
循环直到所有 agent 审查员满意
  ↓
（可选）人类抽查
```

Anthropic 的实践更激进——评估器用 Playwright MCP 实际点击运行中的应用，像真实用户一样测试。

---

### 4.4 垃圾回收式技术债管理

**问题：** Agent 会复制代码库中已有的模式，包括坏模式。随时间推移产生"AI 残渣"。

**初期做法：** 人工定期清理。不可扩展。

**可持续做法：**

1. 将"黄金原则"编码进仓库（偏向共享工具包、不 YOLO 式探测数据、验证边界等）
2. 定期运行**后台 agent 任务**扫描偏差、更新质量等级、发起重构 PR
3. 大多数清理 PR 一分钟内审查并自动合并

> 像垃圾回收（GC）一样——不断以小额方式偿还技术债，而不是让它累积到需要大重构。

---

## 五、个人开发者的起步清单

不需要一上来就搭三 agent 架构。按优先级逐步添加：

### 第 1 周：最小可行 Harness

- [ ] 创建 `CLAUDE.md`，写 3-5 条最重要的规则
- [ ] 配置项目 Linter（已有则确认 agent 能看到报错）
- [ ] 确保有基本的测试，agent 修改代码后能自动跑

### 第 2-4 周：加固 Guides

- [ ] 把 CLAUDE.md 精简为目录，详细规则移到 docs/
- [ ] 写一份架构文档（哪怕只有几行）
- [ ] 记录 agent 犯过的错误，提炼为规则

### 第 2-3 月：添加 Sensors

- [ ] 添加结构测试（dependency-cruiser / ArchUnit）
- [ ] 自定义 Linter 规则，报错信息包含修复指令
- [ ] 配置 pre-commit hooks，agent 每次提交自动检查

### 第 3-6 月：进阶编排

- [ ] 尝试 Generator + Evaluator 模式做设计任务
- [ ] 引入 agent 对 agent 的 Code Review
- [ ] 建立上下文重置 + handoff 机制处理长任务

---

## 六、核心原则速查

| #   | 原则                                             | 来源            |
| --- | ---------------------------------------------- | ------------- |
| 1   | Agent = Model + Harness，模型只提供智能，Harness 决定如何释放 | Martin Fowler |
| 2   | Guides（预防）和 Sensors（纠错）必须结合                    | Martin Fowler |
| 3   | 给地图，不给百科全书——渐进式披露                              | OpenAI        |
| 4   | 架构约束是 agent 的氧气，不是枷锁                           | OpenAI        |
| 5   | 把"做工作的 agent"和"评判工作的 agent"分开                  | Anthropic     |
| 6   | 主观判断转化为可评分的标准                                  | Anthropic     |
| 7   | Linter 报错信息注入修复指令                              | OpenAI        |
| 8   | 垃圾回收式技术债管理——持续小额偿还                             | OpenAI        |
| 9   | 上下文重置 > 上下文压缩                                  | Anthropic     |
| 10  | 不能跳过踩坑阶段——Harness 的每条规则都来自真实失败                 | 雪踏乌云          |
| 11  | 随模型进化简化 Harness，不是永远膨胀                         | Anthropic     |
| 12  | 人类输入引导到最重要的地方，而非完全消除                           | Martin Fowler |

---

## 参考资源

- [[Harness Engineering 驾驭工程]] — 理论框架
- [Harness design for long-running apps — Anthropic](https://www.anthropic.com/engineering/harness-design-long-running-apps)
- [Harness Engineering: Leveraging Codex — OpenAI](https://openai.com/index/harness-engineering/)
- [Harness engineering for coding agent users — Martin Fowler](https://martinfowler.com/articles/harness-engineering.html)
- [Harness Engineering 零基础入门教程 — 雪踏乌云](https://x.com/Pluvio9yte/status/2040453746497302871)
