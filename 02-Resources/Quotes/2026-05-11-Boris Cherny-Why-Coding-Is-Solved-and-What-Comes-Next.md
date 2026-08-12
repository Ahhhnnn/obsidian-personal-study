---
source: https://www.youtube.com/watch?v=SlGRN8jh2RI
date: 2026-05-11
tags: [Claude-Code, AI, programming, Boris-Cherny, Anthropic]
---

# Boris Cherny 访谈：Claude Code 与软件开发的未来

> 来自某个技术大会的访谈，主持人 Lauren Reader，Boris Cherny 是 Claude Code 的创始人。

## 一、Claude Code 的诞生故事

Boris 在 2024 年底加入 Anthropic 的内部孵化团队 **Anthropic Labs**，该团队先后创建了 Claude Code、MCP 和桌面应用。创立初衷是意识到存在**产品 overhang**——模型能力超出当时任何产品的实现水平。当时 coding 的SOTA还是"type ahead"（按 Tab 补全一行代码），但团队认为可以走得远得多。

最初 6 个月产品**几乎无法使用**，Boris 本人也就用大约 10% 的代码是 AI 写的。直到 **Opus 4（2024年5月）** 才出现指数级增长拐点，之后每次模型更新（4.5、4.6、4.7）都继续拉升。

## 二、"Coding is solved"

Boris 本人现在 **100% 的代码由 AI 编写**（他自己只写 commit message），高峰期一天提交了 150 个 PR。他坦言自己的代码库（TypeScript + React）选型就是考虑模型当时的推理能力——需要"on distribution"的语言。随着模型越来越强，语言/框架选型已不再重要。

但他也承认对大型复杂代码库、模型不擅长的奇怪语言，还有很多未解决的场景。

## 三、个人工作流

Boris 大部分工作现在**从手机完成**：
- Claude App 左侧有代码 tab，通常同时运行 **5-10 个 session**
- 每个 session 下有几十个子 agent，总共数百个 agent 并行运转
- 大量使用 **`/loop`** 功能（用 cron 调度循环任务）——如自动修 CI、监控 PR 状态、抓 Twitter 反馈每30分钟聚类等
- 最近还上线了 **routines**（server 侧的 loop，即使关电脑也继续运行）

> "I sort of feel like loops are the future at this point."

## 四、未来团队形态

Anthropic 的 Claude Code 团队已经非常独特——**每个人都在写代码**：工程经理、产品经理、设计师、数据科学家、财务、用户研究员，无一例外。他们是跨学科的 generalist。

Boris 预测未来会看到更多**跨领域 generalist**：既懂工程又懂产品，或既懂工程又懂设计/数据科学。

## 五、SaaS Apocalypse 讨论

Boris 引用了 **Hamilton 的"7 powers"框架** 来分析 AI 如何重塑商业：
- **变弱**： switching costs（可以轻松迁移）、process power（模型很擅长优化流程、hill climb 目标）
- **不变**： network effects、scale economies、cornered resources 等

第二点：未来 10 年创业公司的数量会**增加 10 倍**，因为小公司可以用 AI 原生架构从零构建，直接与有历史包袱的大公司竞争。

> "I think it's the best time to build. It's the best time to be a startup."

## 六、民主化类比：印刷术

Boris 认为软件能力民主化会**比大多数人想象的快得多**，用了 15 世纪印刷术的类比：
- 印刷术出现后 50 年，欧洲出版量超过之前一千年总和，书价下降 100 倍
- 之后几百年识字率从 10% 升到 70%
- 今天软件开发会走类似的路——不需要"专业程序员"学位也能写软件，就像不需要文学学位也会读写一样
- 最好的会计软件应该由最懂会计的人写，而不是最懂编程的人

## 七、内部与外部的差距

Anthropic 内部用的是**和外部一样的模型**，真正的差距在于**组织流程**：
- 所有 Slack 消息都是 AI 之间的通信
- 完全没有手动写代码的地方，SQL 也全是模型写的
- Claude 们通过 Slack 互相通信协调工作

大公司转型会很慢（"5年才迁移完开发环境"），而这正是初创公司的优势。

## 八、多 agent 与并行化

在产品层面，并行化能力的提升主要靠 **prompting 优化**。但随着模型变强，4.7 已经开始**自然地**发现可以并行的场景并主动发起 loop。长远看，这不是用户需要操心的事，而是产品设计的责任。

## 九、本地 vs 云端 AI

Boris 认为这个问题**最终不重要**——再过几年，模型会自动决定用本地还是云端，所有决策都由模型自己做。

MCP（Model Context Protocol）是连接工具的标准方式，无论是 Salesforce、Google Docs 还是编程工具都通过 MCP 接入。

**Computer use** 是另一个方向，Anthropic 在这个方向上目前领先——Co-work 通过它可以让模型操作电脑上任何软件（虽然慢，但在快速进步）。

## 十、未来产品方向

Boris 暗示了几个正在做的方向：
- **Claude Design**：现在已经有一定能力，会越来越强
- **Loop / Batch / sub teams**：大规模并行 agent 会变得更好
- **Computer use**：让 AI 操作任何软件的能力

---

**总结**：这是一场信息密度很高的访谈，Boris 分享了 Claude Code 诞生背后的故事、个人 AI 工作流、未来团队形态、商业格局变化等重要洞察。他对 AI 编程的未来非常乐观，同时指出了组织流程才是真正的护城河。