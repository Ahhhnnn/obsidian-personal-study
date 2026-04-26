# CoPaw - 个人 AI 助理

> 懂你所需，伴你左右
>
> GitHub: [agentscope-ai/CoPaw](https://github.com/agentscope-ai/CoPaw)
>
> 标签: #AI #Agent #个人助理 #开源

## 项目概述

**CoPaw** 是由 AgentScope 团队开发的开源个人 AI 助理。它的设计理念是简单易用、隐私可控、能力可扩展。

**CoPaw** 的名字含义：
- 「你的搭档小爪子」（co-paw）- 温暖的伙伴
- **Co Personal Agent Workstation**（协同个人智能体工作台）

## 核心特性

### 全域触达
支持多种聊天平台接入：
- 钉钉
- 飞书
- QQ
- Discord
- iMessage

### 隐私可控
- 可本地部署或云端部署
- 记忆与个性化由用户掌控
- 支持本地大模型，无需 API Key

### 能力扩展
- Skills 系统：轻松扩展功能
- 内置定时任务
- MCP (Model Context Protocol) 客户端支持
- 无绑定，自由定制

## 应用场景

| 场景       | 功能                                    |
| -------- | ------------------------------------- |
| **社交媒体** | 每日热帖摘要（小红书、知乎、Reddit）、B站/YouTube新视频摘要 |
| **生产力**  | 邮件与Newsletter精华推送、邮件与日历整理联系人          |
| **创意构建** | 睡前设定目标、次日获得雏形                         |
| **研究学习** | 追踪科技与AI资讯、个人知识库检索                     |
| **文件管理** | 本地文件整理搜索、文档摘要                         |

## 快速开始

### pip 安装（推荐）

```bash
pip install copaw
copaw init --defaults
copaw app
```

安装后打开 `http://127.0.0.1:8088/` 即可使用 Web 控制台。

### 一键安装

无需预装 Python：

```bash
# macOS / Linux
curl -fsSL https://copaw.agentscope.io/install.sh | bash

# Windows (PowerShell)
irm https://copaw.agentscope.io/install.ps1 | iex
```

### Docker 部署

```bash
docker pull agentscope/copaw:latest
docker run -p 127.0.0.1:8088:8088 -v copaw-data:/app/working agentscope/copaw:latest
```

### 源码安装（适合学习与开发）

```bash
# 1. 克隆仓库
git clone https://github.com/agentscope-ai/CoPaw.git
cd CoPaw

# 2. 构建前端控制台（Web 界面必需）
cd console && npm ci && npm run build
cd ..

# 3. 将控制台构建产物复制到包目录
mkdir -p src/copaw/console
cp -R console/dist/. src/copaw/console/

# 4. 安装 Python 包（开发模式）
pip install -e .

# 5. 初始化并启动
copaw init --defaults
copaw app
```

**开发模式安装**（包含测试、格式化工具）：

```bash
pip install -e ".[dev]"
```

#### 项目结构概览

```
CoPaw/
├── console/           # 前端 Web 控制台（React/Vue）
├── src/copaw/        # 核心 Python 源码
│   ├── console/      # 前端构建产物（静态文件）
│   ├── agents/       # Agent 定义与实现
│   ├── channels/     # 各平台频道适配器
│   ├── skills/       # 内置 Skills
│   └── ...
├── scripts/          # 构建与部署脚本
└── website/          # 文档站点
```

#### 学习路径建议

1. **先跑起来**：完成源码安装，确保服务正常启动
2. **浏览控制台**：打开 `http://127.0.0.1:8088/` 熟悉 UI
3. **阅读源码**：
   - `src/copaw/agents/` - 理解 Agent 如何工作
   - `src/copaw/channels/` - 了解各平台接入实现
   - `src/copaw/skills/` - 学习如何扩展 Skills
4. **调试修改**：尝试添加简单的自定义 Skill
5. **参与贡献**：查看 [Issues](https://github.com/agentscope-ai/CoPaw/issues) 和 [Discussions](https://github.com/agentscope-ai/CoPaw/discussions)

## 本地模型支持

支持多种本地模型后端，无需 API Key：

| 后端 | 适用场景 | 安装 |
|------|----------|------|
| **llama.cpp** | 跨平台 | `pip install 'copaw[llamacpp]'` |
| **MLX** | Apple Silicon (M1/M2/M3/M4) | `pip install 'copaw[mlx]'` |
| **Ollama** | 跨平台（需Ollama服务） | `pip install 'copaw[ollama]'` |

## 项目信息

- **GitHub Stars**: 9.3k+
- **Forks**: 1k+
- **许可证**: Apache 2.0
- **Python 版本**: 3.10+
- **最新版本**: v0.0.5 (2026-03-06)

## 最新更新 (v0.0.5)

### 新增功能
- Daemon 模式
- Twilio 语音频道
- DeepSeek Reasoner 支持
- 智能体中断 API
- 版本更新提醒

### 优化改进
- 记忆系统升级
- 控制台界面改进
- Windows 一键安装脚本

### Bug 修复
- Docker 配置持久化
- Ollama base URL
- Windows 兼容性
- MCP 客户端稳定性

## 路线图

| 方向 | 状态 |
|------|------|
| 更多频道、模型、Skills、MCP | 征集中（欢迎贡献） |
| 控制台 Web UI 优化 | 进行中 |
| 应用级打包（.dmg、.exe） | 进行中 |
| 多智能体支持 | 计划中 |
| 语音/视频通话与实时交互 | 进行中 |
| 安全加固（Shell执行确认） | 计划中 |
| 大小模型协同 | 长期规划 |

## 相关链接

- [GitHub 仓库](https://github.com/agentscope-ai/CoPaw)
- [官方文档](https://copaw.agentscope.io/)
- [AgentScope](https://github.com/modelscope/agentscope)

## 标签
#LLM #AI-Agent #个人助理 #开源工具 #Python
