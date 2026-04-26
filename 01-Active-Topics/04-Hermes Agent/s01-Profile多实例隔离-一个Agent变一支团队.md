# s01: Profile 多实例隔离 - 一个 Agent 变一支团队

> *"换一个目录，就是换一个人"* - HERMES_HOME 切换实现完全隔离的多 Agent 架构

## 问题背景

### 单 Agent 的局限

一个 Hermes Agent 实例只有一个人格（SOUL.md）、一套配置、一份记忆。如果你想让 Agent 扮演不同角色（数据工程师、技术写手、CEO），单实例做不到。

|| 需求 | 单实例限制 |
|------|------|----------|
| **不同人格** | Writer 温和细腻，Data Engineer 直接粗暴 | 只有 1 个 SOUL.md |
| **不同模型** | 写作用 Claude Opus 4.6（贵但强），数据抓取用 Qwen3.6（便宜够用） | 只有 1 个 config.yaml |
| **不同技能** | Writer 只要写作技能，Data Engineer 只要爬虫技能 | 共享同一个 skills/ |
| **不同 API Key** | 按 Agent 分开计费 | 只有 1 个 .env |
| **独立记忆** | 各自积累各自的经验 | 共享 memories/ |

### delegate_task 子 Agent 的局限

Hermes 有 `delegate_task` 工具可以创建子 Agent，但它是**临时工模式**：

```
spawn → execute → return summary → destroyed（销毁）
```

子 Agent 的硬限制（源码 `tools/delegate_tool.py` 第 32-38 行）：

```python
DELEGATE_BLOCKED_TOOLS = frozenset([
    "delegate_task",   # 禁止递归委派
    "clarify",         # 禁止与用户交互
    "memory",          # 禁止写入持久记忆
    "send_message",    # 禁止跨平台发消息
    "execute_code",    # 禁止写脚本
])
```

子 Agent 没有 SOUL.md、没有记忆、没有技能，任务完成后立即销毁。你需要的是全职员工，不是临时工。

## 解法：Profile（目录隔离）

Profile 的思路很直接：每个 Agent 有自己的 HERMES_HOME 目录。

```
~/.hermes/                           ← default profile（默认）
├── config.yaml
├── .env
├── SOUL.md
├── memories/
├── sessions/
├── skills/
├── cron/
├── home/
└── profiles/
    ├── kourou/                      ← named profile
    │   ├── config.yaml              # 独立模型配置
    │   ├── .env                     # 独立 API Key
    │   ├── SOUL.md                  # 独立人格
    │   ├── memories/                # 独立记忆
    │   ├── sessions/                # 独立会话
    │   ├── skills/                  # 独立技能
    │   ├── cron/                    # 独立定时任务
    │   ├── home/                    # 独立子进程 HOME
    │   └── logs/
    └── cayenne/
        ├── config.yaml
        ├── .env
        ├── SOUL.md
        └── ...
```

### 实现原理

Profile 切换做的事就是改一个环境变量：

```python
# hermes_cli/main.py 第 125 行
os.environ["HERMES_HOME"] = hermes_home  # "~/.hermes/profiles/kourou/"
```

这行代码在所有模块 import 之前执行（第 138 行模块级调用），保证后续组件读到的路径都是正确的：

```
hermes -p kourou chat
         │
         ▼
_apply_profile_override()           # 在 import 之前执行
    解析 -p kourou
    → resolve_profile_env("kourou")
    → os.environ["HERMES_HOME"] = "~/.hermes/profiles/kourou/"
         │
         ▼
所有模块从新的 HERMES_HOME 读取:
    config    → ~/.hermes/profiles/kourou/config.yaml
    .env      → ~/.hermes/profiles/kourou/.env
    SOUL.md   → ~/.hermes/profiles/kourou/SOUL.md
    memories  → ~/.hermes/profiles/kourou/memories/
    skills    → ~/.hermes/profiles/kourou/skills/
    sessions  → ~/.hermes/profiles/kourou/sessions/
```

### Wrapper 别名机制

创建 Profile 时自动生成 Shell 包装脚本：

```bash
# ~/.local/bin/kourou
#!/bin/sh
exec hermes -p kourou "$@"
```

这样你可以直接用 `kourou chat` 代替 `hermes -p kourou chat`。

## Profile CRUD 操作

### 创建

```bash
# 创建空白 Profile
hermes profile create kourou

# 克隆配置（复制 config.yaml + .env + SOUL.md）
hermes profile create cayenne --clone

# 完整克隆（复制所有状态）
hermes profile create cayenne --clone-all
```

创建时自动初始化 8 个子目录（源码 `_PROFILE_DIRS`）：

```python
_PROFILE_DIRS = [
    "memories",     # 记忆
    "sessions",     # 会话
    "skills",       # 技能
    "skins",        # 皮肤主题
    "logs",         # 日志
    "plans",        # 计划
    "workspace",    # 工作空间
    "cron",         # 定时任务
    "home",         # 子进程 HOME（隔离 git/ssh/gh 凭证）
]
```

### 查看

```bash
hermes profile list
```

输出示例：
```
Profile: default
  Path:    ~/.hermes
  Model:   anthropic/claude-sonnet-4 (openrouter)
  Skills:  12
  Gateway: running

Profile: kourou
  Path:    ~/.hermes/profiles/kourou
  Model:   qwen/qwen3.6-plus:free (openrouter)
  Skills:  4
  Gateway: running

Profile: cayenne
  Path:    ~/.hermes/profiles/cayenne
  Model:   anthropic/claude-opus-4.6 (openrouter)
  Skills:  3
  Gateway: stopped
```

### 使用

```bash
# 方式 1：通过 -p 标志
hermes -p kourou chat

# 方式 2：通过 wrapper 别名（等价）
kourou chat

# 方式 3：设置为默认 Profile
hermes profile use kourou
hermes chat  # 现在默认使用 kourou

# 非交互式单次查询（适合自动化）
kourou chat -q "抓取最新加密新闻"
```

### 删除

```bash
hermes profile delete kourou
# 会同时删除: 目录 + wrapper 脚本 + gateway 服务
```

### 命名规则

```python
# 源码：profiles.py 第 33 行
_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
```

- 小写字母、数字、连字符、下划线
- 长度 1-64 字符
- 不能与系统命令冲突（会检查 `which`）
- `default` 是保留名（指向 `~/.hermes`）

## 隔离维度详解

Profile 之间的隔离是物理级的：不是标记隔离，是真正分开的文件目录。

### 1. 配置隔离

```yaml
# kourou 的 config.yaml — 便宜模型 + 爬虫工具
model:
  default: qwen/qwen3.6-plus:free
  provider: openrouter
toolsets:
  enabled: [terminal, file, web]

# cayenne 的 config.yaml — 昂贵模型 + 创意写作
model:
  default: anthropic/claude-opus-4.6
  provider: openrouter
toolsets:
  enabled: [terminal, file, web, browser]
```

### 2. API Key 隔离

每个 Profile 有独立的 `.env`，可以为不同 Agent 使用不同的 API Key（方便计费管理）：

```bash
# kourou/.env
OPENROUTER_API_KEY=sk-or-v1-aaaa...    # Key A

# cayenne/.env
OPENROUTER_API_KEY=sk-or-v1-bbbb...    # Key B
```

### 3. 人格隔离

每个 Profile 有独立的 `SOUL.md`，定义 Agent 的性格、行为准则：

```markdown
# kourou/SOUL.md
你是 Kourou，一个数据工程师。直接、高效，专注于数据抓取和清洗。

# cayenne/SOUL.md
你是 Cayenne，一个技术写手。善于将复杂信息转化为易读文章，注重可读性。
```

### 4. 技能隔离

```
~/.hermes/profiles/kourou/skills/
├── crypto-scraper/
│   └── SKILL.md          # 加密货币爬虫技能
└── supabase-upload/
    └── SKILL.md          # Supabase 上传技能

~/.hermes/profiles/cayenne/skills/
├── newsletter-writer/
│   └── SKILL.md          # Newsletter 写作技能
└── image-generator/
    └── SKILL.md          # 封面图生成技能
```

### 5. 子进程凭证隔离

每个 Profile 有独立的 `home/` 目录，作为子进程（git, ssh, gh, npm）的 HOME：

```
~/.hermes/profiles/kourou/home/
├── .gitconfig            # kourou 的 git 配置
├── .ssh/                 # kourou 的 SSH 密钥
└── .config/gh/           # kourou 的 GitHub 凭证
```

这意味着即使两个 Profile 同时操作不同 Git 仓库，凭证也不会混淆。

### 6. Gateway 隔离

每个 Profile 运行独立的 Gateway 进程，连接不同的 Telegram Bot：

```bash
# 启动三个独立的 Gateway 服务
systemctl --user start hermes-gateway                # default → @dad_half_bot
systemctl --user start hermes-gateway-kourou          # kourou → @kourou_data_bot
systemctl --user start hermes-gateway-cayenne         # cayenne → @cayenne_writer_bot
```

## Profile vs delegate_task 对比

两种多 Agent 方式解决不同层面的问题：

```
Profile 方式："雇佣全职员工"
┌─────────────────────────────────────────────────────┐
│ 独立进程  │  独立配置  │  独立人格  │  独立记忆  │  长驻运行  │
└─────────────────────────────────────────────────────┘

delegate_task 方式："叫临时工帮忙"
┌─────────────────────────────────────────────────────┐
│ 同进程线程 │  共享配置  │  无人格   │  无记忆   │  用完销毁  │
└─────────────────────────────────────────────────────┘
```

### 详细对比

| 维度 | Profile | delegate_task |
|------|---------|--------------|
| 进程模型 | 独立进程（各自 Gateway） | 同进程线程（ThreadPoolExecutor） |
| 配置隔离 | 完全独立（config.yaml, .env） | 共享父 Agent 配置 |
| API Key | 各自独立 | 共享父 Agent 的 Key |
| 模型选择 | 各自独立 | 可配置但默认继承父 |
| 人格 SOUL | 各自独立 | 无（`skip_context_files=True`） |
| 记忆系统 | 各自独立 | 不写入（`skip_memory=True`） |
| 技能系统 | 各自独立 | 无（`skip_context_files=True`） |
| 工具权限 | 各自独立配置 | 受限（5 类工具被禁止） |
| 通信方式 | 外部中间件（数据库/Telegram） | 进程内函数返回值 |
| 生命周期 | 长驻服务 | 任务完成即销毁 |
| 嵌套深度 | 无限制 | 最多 1 层（MAX_DEPTH=2） |
| 并行能力 | 天然并行（独立进程） | ThreadPoolExecutor，默认最多 3 并发 |
| 适用场景 | 长期角色分工 | 会话内任务拆解 |

### delegate_task 子 Agent 的构建过程

```
Parent Agent（完整的 Agent）
  │
  ├── SOUL.md, MEMORY.md, skills, 全部工具
  │
  └── _build_child_agent() 构建子 Agent
       │
       ├── 临时系统提示（基于 goal + context 生成）
       ├── 无 SOUL.md（skip_context_files=True）
       ├── 无记忆（skip_memory=True）
       ├── 工具集裁剪（移除 blocked tools）
       ├── 继承父的 API Key 和工作目录
       └── 完成后 child.close() 销毁
```

## Profile 间通信

Profile 之间**没有内置的直接 RPC 机制**。但有三种间接通信路径：

### 路径 1：外部数据库（推荐）

```
[Kourou] ──写入──→ Supabase ──读取──→ [Cayenne]
                      ↑
              共享数据库作为消息中间件
```

这是最灵活的方式：一个 Profile 写，另一个读，通过数据库解耦。

### 路径 2：Telegram/Discord 群组

```
[Dad Half Bot] ──send_message──→ Telegram 群组 ──触发──→ [Kourou]
```

每个 Profile 绑定不同的 Bot，通过群组消息间接通信。

### 路径 3：Terminal 调用（理论可行）

```bash
# Dad Half Bot 通过 terminal 工具调用 Kourou
# 利用 hermes chat -q 的非交互模式
kourou chat -q "抓取最新加密新闻"
```

底层是启动一个新的 hermes 进程（以 kourou profile 运行），执行完后返回 stdout。

### 路径 4：Honcho 共享记忆

```
[Kourou] ──写入──→ Honcho Workspace ──读取──→ [Cayenne]
                      ↑
              语义层共享知识（非请求/响应式）
```

通过 Honcho 记忆插件，不同 Profile 可以共享同一个 Workspace 但拥有独立的 aiPeer 身份。Host key 按规则推导：default → `hermes`，kourou → `hermes.kourou`。

## 实战案例：Newsletter Pipeline

基于 Marco Rodrigues (@dadhalfdev) 的实际项目 "The Agentic Block"：

### 架构图

```
┌────────────────────────────────────────────────────────────────┐
│                        Marco（人类协调者）                        │
│                    Telegram 分别与三个 Agent 对话                  │
└──────────┬──────────────────┬──────────────────┬───────────────┘
           │                  │                  │
           ▼                  ▼                  ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │  Dad Half Bot │  │   Kourou     │  │   Cayenne    │
   │  (CEO/主力)   │  │ (数据工程师)  │  │  (写手)      │
   │  default     │  │  profile-1   │  │  profile-2   │
   ├──────────────┤  ├──────────────┤  ├──────────────┤
   │ Opus 4.6    │  │ Qwen3.6 free │  │ Opus 4.6    │
   │ 全部技能     │  │ 爬虫技能      │  │ 写作技能      │
   │ 全部仓库权限  │  │ 沙箱隔离      │  │ 沙箱隔离      │
   └──────────────┘  └──────┬───────┘  └──────┬───────┘
                             │                  │
                      写入   ▼    读取          │
                    ┌────────────────┐           │
                    │   Supabase     │           │
                    │  (共享数据库)    │           │
                    └────────────────┘           │
                                                  │
                      生成 Markdown + 封面图 ──────┘
                             │
                             ▼
                       Substack 发布
```

### 设计要点

- 数据层解耦：Kourou 写 Supabase，Cayenne 读 Supabase，Agent 之间不需要直接通信
- 成本控制：只有 Cayenne 用贵模型，其余用免费模型
- 技能裁剪：每个 Agent 只装 3-4 个技能，减少 token 消耗
- 独立 API Key：每个 Agent 单独的 OpenRouter Key，避免并发冲突
- 人工把关：Marco 最终审核文章再发布到 Substack

### 工作流程

```
1. Marco: "Kourou，去抓取本周 AI + Crypto 相关新闻"
2. Kourou: 爬取 CoinDesk/Decrypt/CryptoSlate → 过滤 AI 相关 → 上传 Supabase
3. Marco: "Cayenne，基于 Supabase 里最新数据写一篇 Newsletter"
4. Cayenne: 读取 Supabase → 生成 Markdown + 3 张封面图 → 输出到文件
5. Marco: 审核文章 → 手动复制到 Substack 发布
```

## 总结

Profile 是 Hermes Agent 的多实例隔离机制，核心是目录隔离而非进程隔离。切换一个 HERMES_HOME 环境变量，就能获得独立的人格、配置、记忆、技能、凭证和 Gateway。代价只是多了一个目录。

Profile 和 delegate_task 各管各的事：
- **Profile** 管组织架构，每个 Agent 长驻运行、各司其职
- **delegate_task** 管任务分解，临时工并行干活、用完即走

两者可以组合：一个 Profile 内部用 delegate_task 拆分子任务，多个 Profile 同时独立运行。

## 源码索引

| 文件 | 关键内容 |
|------|---------|
| `hermes_cli/profiles.py` | Profile CRUD，目录结构，wrapper 别名生成 |
| `hermes_cli/main.py` 第 83-138 行 | `_apply_profile_override()` — 解析 -p 标志，设置 HERMES_HOME |
| `hermes_constants.py` | `get_hermes_home()` — 所有模块的路径起点 |
| `tools/delegate_tool.py` | 子 Agent 委派（同进程线程池，受控工具集） |
| `tools/send_message_tool.py` | 跨平台消息发送（Telegram/Discord/Slack） |
| `plugins/memory/honcho/client.py` | Honcho 共享记忆，跨 Profile 语义层通信 |
