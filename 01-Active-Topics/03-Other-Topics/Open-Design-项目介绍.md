---
tags:
  - AI
  - Agent
  - Design
  - OpenSource
created: 2026-05-03
---
![[Pasted image 20260503212348.webp]]
# Open Design

> **[Claude Design][cd] 的开源替代品**

## 概述

Open Design（OD）是一个本地优先、可部署到 Vercel 的开源设计工具，每一层都支持 BYOK（自带 Key）。它的核心思路是：不重新造 agent 轮子，而是把用户已有的最强 coding-agent 接进一个 skill 驱动的设计工作流。

**本质**：将 design 提示词封装为 skill，提供可视化界面选择，底层委托已存在的 code agent 执行。

**一句话总结**：Open Design 是一个将 design 提示词封装为可组合 Skill 的开源工具，通过本地 Daemon 委托用户已有的 coding-agent CLI执行，最终生成可预览的 artifact——本质是一个 design wrapper，而不是新的 agent。

## 核心特性

| 特性                | 说明                                                                                                |
| ----------------- | ------------------------------------------------------------------------------------------------- |
| **Coding Agent**  | 10 套 CLI 自动检测（Claude Code、Codex、Cursor Agent、Gemini CLI、OpenCode、Qwen、Copilot CLI、Hermes、Kimi、Pi） |
| **Design System** | 72 套品牌级系统（Linear、Stripe、Vercel、Notion、Apple 等）                                                    |
| **内置 Skill**      | 31 个可组合技能（27 个 prototype + 4 个 deck 模式）                                                           |
| **媒体生成**          | gpt-image-2 做图、Seedance 2.0 做视频、HyperFrames 做动态图形                                                 |
| **设备外壳**          | iPhone 15 Pro、Pixel、iPad Pro、MacBook 等像素级精确外壳                                                     |
| **导入**            | 支持直接拖入 Claude Design 导出的 ZIP 继续编辑                                                                 |

## 技术架构

```
┌─────────────── 浏览器（Next.js 16）─────────────────────────────┐
│  chat · 文件工作区 · iframe 预览 · 设置 · 导入                  │
└──────────────┬─────────────────────────────────┬───────────────┘
               │ /api/*                           │
               ▼                                  ▼
    ┌─────────────────────────────┐  /api/proxy/stream (SSE)
    │  本地 daemon（Express + SQLite）│  ─→ 任意 OpenAI 兼容
    │                               │      端点（BYOK）
    │  /api/agents    /api/skills   │
    │  /api/design-systems /projects/…
    └─────────┬───────────────────────┘
              │ spawn(cli, [...], { cwd: .od/projects/<id> })
              ▼
    ┌──────────────────────────────────────────────────────────────────┐
    │  claude · codex · gemini · opencode · cursor-agent · qwen        │
    │  copilot · hermes · kimi · pi                                    │
    └──────────────────────────────────────────────────────────────────┘
```

### 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Next.js 16 + React 18 + TypeScript |
| Daemon | Node 24 + Express + SQLite + SSE |
| Agent 传输 | child_process.spawn，多种 CLI 适配器 |
| BYOK 代理 | OpenAI 兼容端点透传，含 SSRF 防御 |
| 存储 | 本地文件 + SQLite |
| 部署 | 本地 / Vercel / 可选 Electron |

## 六大设计理念

### 1. 不带 agent，你的就够好
PATH 扫描自动检测 10 种 coding-agent CLI，一个都没装时 BYOK 代理兜底。

### 2. Skill 是文件夹
遵循 Claude Code SKILL.md 规范，丢进 `skills/` 目录重启即生效。

### 3. Design System 是 Markdown
72 套品牌级 `DESIGN.md`，切换 system → 下次渲染自动使用新 token。

### 4. 初始化问题表单
每个设计任务从 `<question-form>` 开始，30 秒锁死方向，错方向的代价是一轮对话。

### 5. Daemon 让 agent 作用于真实文件系统
`spawn` CLI 时 `cwd` 设到真实项目目录，生成的 `.html`/`.pdf` 直接落盘。

### 6. 提示词栈可组合
```
DISCOVERY 指令 + 身份与工作流宪章 + 激活的 DESIGN.md + 激活的 SKILL.md + 项目元数据
```

## 与其他产品的区别

| 特性 | Open Design | Claude Design | OpenCode Design |
|---|---|---|---|
| 部署 | 本地 / Vercel | 仅云端 | 桌面 Electron |
| Agent | 委托用户已有 CLI | 绑定云端 | 打包 `pi-ai` |
| Skill | 开放、文件夹式 | 闭源内部 | 不开放 |
| Design System | 72 套 Markdown | 闭源 | 有限 |
| BYOK | 支持 | 不支持 | 不支持 |
| License | Apache-2.0 | 闭源付费 | 开源 |

## 本地安装

### 环境要求
- Node.js ~24
- pnpm 10.33.x
- macOS / Linux / WSL2

### 安装步骤

```bash
# 1. 安装 Node 24
nvm install 24 && nvm use 24

# 2. 启用 Corepack
corepack enable
corepack pnpm --version  # 确认 10.33.2

# 3. 安装依赖
pnpm install

# 4. 启动服务
pnpm tools-dev run web   # 前台运行
# 或
pnpm tools-dev           # 后台运行
```

### 常用命令

```bash
pnpm tools-dev status    # 查看状态
pnpm tools-dev logs      # 查看日志
pnpm tools-dev restart   # 重启
pnpm tools-dev stop      # 停止
```

## 价值总结

Open Design 的本质是一个 **coding-agent 的 design wrapper**：

- 输入：从 UI 拿到结构化的 design intent
- 输出：通过 agent 生成可预览的 artifact
- 价值：把「AI freestyle 画图」变成「在约束下系统化出稿」

这是一种工程化的设计方法，而不是模型能力的堆叠。

---

## 参考项目

Open Design 站在四个开源项目的肩膀上：

| 项目                                                  | 贡献                                                                                                                                                          |
| --------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [**alchaincyf/huashu-design**][huashu]（花叔的画术）       | 设计哲学指南针。Junior-Designer 工作流、5 步品牌资产协议、anti-AI-slop checklist、五维自评审、「5 流派 × 20 种设计哲学」方向选择器思路                                                                 |
| [**op7418/guizang-ppt-skill**][guizang]（歸藏的杂志风 PPT） | Deck 模式，原样捆绑在 `skills/guizang-ppt/`，原 LICENSE 保留；杂志版式、WebGL hero、P0/P1/P2 checklist                                                                         |
| [**OpenCoworkAI/open-codesign**][codesign]          | UX 北极星，首个开源 Claude-Design 替代品。借鉴了流式 artifact 循环、沙盒 iframe 预览、实时 agent 面板（todos + tool calls + 可中断生成）、5 种导出格式。形态上刻意分流——它们是桌面 Electron，我们做 Web + local daemon |
| [**multica-ai/multica**][multica]                   | Daemon 与运行时架构。PATH 扫描式 agent 检测，local daemon 作为唯一特权进程，agent-as-teammate 世界观                                                                                 |

## 相关链接

- GitHub: https://github.com/nexu-io/open-design
- 姊妹项目: https://github.com/OpenCoworkAI/open-codesign

[cd]: https://docs.anthropic.com/en/docs/claude-design
[huashu]: https://github.com/alchaincyf/huashu-design
[guizang]: https://github.com/op7418/guizang-ppt-skill
[codesign]: https://github.com/OpenCoworkAI/open-codesign
[multica]: https://github.com/multica-ai/multica

[cd]: https://docs.anthropic.com/en/docs/claude-design
