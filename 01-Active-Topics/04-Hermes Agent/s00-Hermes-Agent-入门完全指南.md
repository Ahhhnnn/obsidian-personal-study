# s00: Hermes Agent 入门完全指南 - 从安装到深度定制

> *"定制本身不是技能，用它完成事情才是"* - Hermes Agent 核心理念

## 项目概览

Hermes Agent 是 Nous Research 开源的 AI Agent 框架，GitHub 10.7 万 stars，MIT 协议，Python 开发。

| 指标 | 数据 |
|------|------|
| Stars | 107,500+ |
| Forks | 15,439 |
| License | MIT |
| 语言 | Python |
| 最新版本 | v2026.4.16 |
| 官方文档 | https://hermes-agent.nousresearch.com/docs/ |

## 为什么需要 Hermes Agent

### 从 OpenClaw 迁移的原因

视频嘉宾 Imran 列举了三个：

| 问题 | OpenClaw | Hermes |
|------|----------|--------|
| 记忆 | 每次对话重复背景 | 自动保存成功任务 |
| 稳定性 | 每小时重启 | 一周不用重启 |
| 成本 | 黑盒 | OpenRouter 可视化 |

迁移后 token 花费从 $130/5天 降到 $10/5天。

### 记忆系统的意义

Hermes 和其他 Agent 的核心区别在于有记忆：

```
任务完成 → 自动保存到记忆
         ↓
    主动保存知识（不是每次都问你要不要保存）
         ↓
    下次遇到类似任务 → 检索 → 复用
```

第一周用的时候它什么都不知道。两三周后，它记住了你的工作风格、常用流程、偏好设置。

## 技术架构

### Agent Loop 流程

```
用户输入
    │
    ▼
┌─────────────────────┐
│  Personality Filter │  ← SOUL.md 人格设定
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Memory Retrieval   │  ← 检索相关记忆
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│   LLM Reasoning     │  ← 选择模型推理
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Tool Execution     │  ← 调用工具
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Memory Update      │  ← 保存新知识
└─────────┬───────────┘
          │
          ▼
┌─────────────────────┐
│  Skill Creation     │  ← 复杂任务自动生成技能
└─────────────────────┘
          │
          ▼
      用户响应
```

### 核心组件

| 组件 | 说明 |
|------|------|
| Gateway | 消息网关，连接 Telegram/Discord/Slack 等平台 |
| Agent Loop | 主循环，处理用户请求的核心引擎 |
| Memory System | 三层记忆系统（会话、技能、用户模型） |
| Skills System | 技能系统，支持自然语言创建 |
| Tools System | 40+ 内置工具 |
| Personality | 人格系统（SOUL.md） |
| MCP Client | Model Context Protocol 客户端 |

### 目录结构

```
~/.hermes/
├── config.yaml           # 主配置
├── .env                  # API Keys
├── SOUL.md              # 人格设定
├── memories/            # 记忆存储（SQLite）
│   ├── sessions/       # 会话历史
│   └── user_profiles/  # 用户模型
├── skills/              # 技能目录
│   └── */              # 每个 skill 一个文件夹
├── cron/                # 定时任务定义
├── home/                # 子进程 HOME（git/ssh 凭证隔离）
├── profiles/            # 多实例（详见 s01）
└── logs/                # 日志
```

### 消息网关架构

```
                    ┌─────────────┐
                    │   Telegram   │
                    │   Discord    │
                    │   Slack      │
                    │   WhatsApp   │
                    │   Signal     │
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │   Gateway   │  ← 单进程处理所有平台
                    └──────┬──────┘
                           │
                           ▼
                    ┌─────────────┐
                    │ Agent Loop  │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
         Memory        Skills        Tools
```

### 记忆系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    Memory System                        │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  Layer 1: Session Memory                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │  SQLite + FTS5 全文搜索                          │   │
│  │  LLM Summarization 压缩                         │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                              │
│                         ▼                              │
│  Layer 2: Skills Memory                               │
│  ┌─────────────────────────────────────────────────┐   │
│  │  持久化技能                                      │   │
│  │  执行时自动改进                                   │   │
│  └─────────────────────────────────────────────────┘   │
│                         │                              │
│                         ▼                              │
│  Layer 3: User Model (Honcho)                         │
│  ┌─────────────────────────────────────────────────┐   │
│  │  方言用户建模                                    │   │
│  │  学习沟通风格、偏好、工作习惯                     │   │
│  └─────────────────────────────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## 安装部署

### 一键安装（Linux/macOS/WSL2）

```bash
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash
source ~/.bashrc
hermes
```

### Android/Termux

```bash
# 装好 Termux（F-Droid 版本）后执行上面那条命令
# Termux 版用的是 .[termux] 子集，跳过了一些语音相关的依赖
```

### 装完之后的配置

```bash
hermes setup        # 交互式向导，一步一步配完
hermes model        # 选模型
hermes tools        # 选工具
hermes update       # 更新
hermes doctor       # 有问题先跑这个诊断
```

### 从 OpenClaw 迁移

```bash
hermes claw migrate              # 交互式迁移
hermes claw migrate --dry-run   # 先看看会迁移什么
```

会迁移：SOUL.md、记忆、技能、API Keys（可选）、平台配置、命令白名单。

## 模型支持

支持 OpenRouter（200+ 模型，含免费）、OpenAI、Anthropic、NVIDIA NIM、Hugging Face、Google、Kimi、MiniMax、自托管等。

切模型很直接：

```bash
hermes model                    # 交互式选
/model openrouter:qwen/qwen-3-6-plus       # 直接指定
```

OpenRouter 上 Qwen 3.6 Plus 输入 $0.33/百万 tokens，Claude Sonnet 约 $3。差十倍。

## Skills 与 Tools

### Skills vs Tools

| | Tools | Skills |
|--|-------|--------|
| 用途 | 单一操作 | 多步骤工作流 |
| 记忆 | 无 | 有，可学习 |
| 创建 | 预定义 | 自然语言生成 |

直接说"帮我创建一个银行流水分析的 skill"，它就能生成。

### Skills 工作流

```
自然语言请求
    │
    ▼
Agent 分析任务需求
    │
    ▼
生成 SKILL.md 结构
    │
    ▼
写入 ~/.hermes/skills/[skill-name]/
    │
    ▼
首次执行时学习优化
```

推荐先装的技能：Obsidian（笔记）、GStack（YC 创业方法论）、Honcho Dev Memory（扩展记忆）。

## 消息网关

支持 Telegram、Discord、Slack、WhatsApp、Signal、Email。

```bash
hermes gateway setup     # 配置
hermes gateway start    # 启动
```

配置完就能在 Telegram 上和 Agent 对话，不用守着终端。

## 定时任务

直接说人话：

```
"每天早上 9 点给我发一份邮件摘要"
"每周一早上 8 点生成周报"
```

支持推送到 Telegram、Discord、Email、Slack。

## 多后端部署

| 后端 | 适用场景 |
|------|----------|
| Local | 日常开发、调试 |
| Docker | 生产隔离部署 |
| SSH | 远程服务器 |
| Daytona | GPU 集群 |
| Singularity | HPC |
| Modal | Serverless，闲置时几乎零成本 |

Modal 的特点：闲置时休眠、零成本，收到消息自动唤醒。

## Android 部署

Termox API 可以访问电池、WiFi、摄像头、屏幕亮度、振动。

实际用途：社交媒体矩阵（每个手机有独立设备指纹）、2FA 短信接收、永驻设备。

## 常用命令

CLI：

```bash
hermes              # 启动
hermes model        # 选模型
hermes tools        # 配工具
hermes gateway      # 网关
```

对话中：

| 命令 | 作用 |
|------|------|
| `/new` | 新对话 |
| `/reset` | 重置 |
| `/model [provider:model]` | 切模型 |
| `/retry` | 重试上一步 |
| `/usage` | 看 token 消耗 |
| `/stop` | 停掉当前任务 |

## 每日 Prompt 建议

1. "What have I been procrastinating?"
2. "What's the most important thing to work on today?"
3. "What tasks am I doing every day that I could automate?"
4. "What is one tool you can build tonight that would make my life easier tomorrow?"

不要做的事：沉迷配置、追求完美工具链、第一天就想搞定一切。

## Profile 多实例

详见 s01。简单说就是每个 Profile 独立运行，有自己的配置、人格、记忆、技能、API Key。

```bash
hermes profile create mybot   # 创建
hermes -p mybot chat         # 用这个 profile
hermes profile list           # 看看有哪些
```

## 资源

- 官网：https://hermes-agent.nousresearch.com
- 文档：https://hermes-agent.nousresearch.com/docs/
- GitHub：https://github.com/NousResearch/hermes-agent
- Discord：https://discord.gg/NousResearch
- Skills Hub：https://agentskills.io
- 橙皮书（中文）：https://github.com/alchaincyf/hermes-agent-orange-book
