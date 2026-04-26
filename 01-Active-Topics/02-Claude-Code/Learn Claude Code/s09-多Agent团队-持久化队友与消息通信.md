# s09: 多 Agent 团队 - 持久化队友与消息通信

> *"任务太大一个人干不完，要能分给队友"* -- 持久化队友 + JSONL 邮箱

## 问题背景

### s04 Subagent 的局限

子智能体是**一次性的**：
```
spawn → execute → return summary → destroyed
```

| 问题      | 影响             |
| ------- | -------------- |
| **无身份** | 无法跨调用记住"我是谁"   |
| **无记忆** | 每次调用都是全新上下文    |
| **无状态** | 完成后立即销毁，无法继续工作 |
|         |                |

### s08 后台任务的局限

后台任务只能运行 shell 命令，**做不了 LLM 引导的决策**：
```python
# s08 只能这样
background_run("npm test")  # 固定命令

# 想要这样？做不到
background_agent("分析测试结果，如果失败则修复代码")  # 需要决策
```

### 真正的团队协作需要

1. **持久化智能体** - 能跨多轮对话存活
2. **身份和生命周期** - 知道"我是谁"、"我在什么状态"
3. **通信通道** - 智能体之间能互相交谈

## 解决方案架构

### 队友生命周期

```
spawn → WORKING → IDLE → WORKING → ... → SHUTDOWN
  ↑                                           ↓
  └─────────────── 可重新 spawn ───────────────┘
```

### 目录结构

```
.team/
  config.json           # 团队名册 + 状态
  inbox/
    alice.jsonl         # 追加写入，读取时清空
    bob.jsonl
    lead.jsonl
```

### 通信模型

```
              +--------+    send("alice","bob","...")    +--------+
              | alice  | -----------------------------> |  bob   |
              | loop   |    bob.jsonl << {json_line}    |  loop  |
              +--------+                                +--------+
                   ^                                         |
                   |        BUS.read_inbox("alice")          |
                   +---- alice.jsonl -> read + drain ---------+
```

## 核心组件

### 1. TeammateManager - 团队管理

```python
class TeammateManager:
    def __init__(self, team_dir: Path):
        self.dir = team_dir
        self.config_path = self.dir / "config.json"
        self.config = self._load_config()  # 持久化配置
        self.threads = {}  # name -> thread
```

#### config.json 结构

```json
{
  "team_name": "default",
  "members": [
    {"name": "alice", "role": "coder", "status": "working"},
    {"name": "bob", "role": "tester", "status": "idle"},
    {"name": "lead", "role": "coordinator", "status": "idle"}
  ]
}
```

#### spawn() - 创建队友

```python
def spawn(self, name: str, role: str, prompt: str) -> str:
    # 1. 查找或创建成员
    member = self._find_member(name)
    if member:
        if member["status"] not in ("idle", "shutdown"):
            return f"Error: '{name}' is currently {member['status']}"
        member["status"] = "working"
        member["role"] = role
    else:
        member = {"name": name, "role": role, "status": "working"}
        self.config["members"].append(member)

    # 2. 保存配置
    self._save_config()

    # 3. 启动独立线程
    thread = threading.Thread(
        target=self._teammate_loop,
        args=(name, role, prompt),
        daemon=True,  # 主线程退出时自动终止
    )
    self.threads[name] = thread
    thread.start()

    return f"Spawned '{name}' (role: {role})"
```

**关键点**：每个队友在自己的 `daemon` 线程中运行完整的 agent loop。

#### _teammate_loop() - 队友的主循环

```python
def _teammate_loop(self, name: str, role: str, prompt: str):
    # 独立的系统提示
    sys_prompt = (
        f"You are '{name}', role: {role}, at {WORKDIR}. "
        f"Use send_message to communicate. Complete your task."
    )

    # 独立的上下文
    messages = [{"role": "user", "content": prompt}]
    tools = self._teammate_tools()

    for _ in range(50):  # 最多 50 轮
        # 1. 检查收件箱
        inbox = BUS.read_inbox(name)
        for msg in inbox:
            messages.append({"role": "user", "content": json.dumps(msg)})

        # 2. LLM 调用
        response = client.messages.create(
            model=MODEL,
            system=sys_prompt,
            messages=messages,
            tools=tools,
            max_tokens=8000,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            break

        # 3. 执行工具
        results = []
        for block in response.content:
            if block.type == "tool_use":
                output = self._exec(name, block.name, block.input)
                results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": str(output),
                })
        messages.append({"role": "user", "content": results})

    # 4. 完成，设为 idle
    member = self._find_member(name)
    if member and member["status"] != "shutdown":
        member["status"] = "idle"
        self._save_config()
```

**关键点**：
- 每个队友有**独立的 `messages` 列表**
- 每次循环开始时**检查收件箱**
- 完成后状态变为 `idle`（不是销毁）

### 2. MessageBus - JSONL 收件箱

```python
class MessageBus:
    def __init__(self, inbox_dir: Path):
        self.dir = inbox_dir
        self.dir.mkdir(parents=True, exist_ok=True)
```

#### send() - 发送消息

```python
def send(self, sender: str, to: str, content: str,
         msg_type: str = "message", extra: dict = None) -> str:
    # 1. 验证消息类型
    if msg_type not in VALID_MSG_TYPES:
        return f"Error: Invalid type '{msg_type}'. Valid: {VALID_MSG_TYPES}"

    # 2. 构造消息
    msg = {
        "type": msg_type,
        "from": sender,
        "content": content,
        "timestamp": time.time(),
    }
    if extra:
        msg.update(extra)

    # 3. 追加到收件箱
    inbox_path = self.dir / f"{to}.jsonl"
    with open(inbox_path, "a") as f:  # append 模式
        f.write(json.dumps(msg) + "\n")

    return f"Sent {msg_type} to {to}"
```

**JSONL 格式示例**：
```
{"type":"message","from":"lead","content":"fix bug","timestamp":1234567890.123}
{"type":"broadcast","from":"alice","content":"done","timestamp":1234567891.456}
{"type":"shutdown_request","from":"lead","content":"shutdown","timestamp":1234567892.789}
```

#### read_inbox() - 读取并清空

```python
def read_inbox(self, name: str) -> list:
    inbox_path = self.dir / f"{name}.jsonl"
    if not inbox_path.exists():
        return []

    # 1. 读取所有行
    messages = []
    for line in inbox_path.read_text().strip().splitlines():
        if line:
            messages.append(json.loads(line))

    # 2. 清空文件（drain 模式）
    inbox_path.write_text("")

    return messages
```

**关键点**：
- **追加写入**：`open(..., "a")` 模式
- **读取清空**：消息只处理一次

#### broadcast() - 广播

```python
def broadcast(self, sender: str, content: str, teammates: list) -> str:
    count = 0
    for name in teammates:
        if name != sender:  # 不发给自己
            self.send(sender, name, content, "broadcast")
            count += 1
    return f"Broadcast to {count} teammates"
```

### 3. 消息类型

```python
VALID_MSG_TYPES = {
    "message",                  # 普通消息
    "broadcast",                # 广播给所有人
    "shutdown_request",         # 请求关闭 (s10)
    "shutdown_response",        # 同意/拒绝关闭 (s10)
    "plan_approval_response",   # 同意/拒绝计划 (s10)
}
```

### 4. 工具接口对比

| 工具 | Lead | Teammate | 说明 |
|-----|------|----------|------|
| spawn_teammate | ✅ | ❌ | 只有 Lead 能生成队友 |
| list_teammates | ✅ | ❌ | 只有 Lead 能列出队友 |
| send_message | ✅ | ✅ | 双向通信 |
| read_inbox | ✅ | ✅ | 双向通信 |
| broadcast | ✅ | ✅ | 双向广播 |
| bash | ✅ | ✅ | 都能执行 |
| read_file | ✅ | ✅ | 都能读取 |
| write_file | ✅ | ✅ | 都能写入 |
| edit_file | ✅ | ✅ | 都能编辑 |

## 通信流程示例

### 场景：协作修复 bug

```
t=0:   Lead: spawn_teammate("alice", "coder", "修复登录 bug")
t=1:   [alice 线程启动，开始工作]

t=10:  Lead: spawn_teammate("bob", "tester", "准备测试")
t=11:  [bob 线程启动]

t=20:  alice: send_message("lead", "修复完成，请测试")
       [写入 lead.jsonl]

t=21:  [Lead 下次循环时读取收件箱]
t=21:  Lead 收到消息

t=22:  Lead: send_message("bob", "测试登录功能")
       [写入 bob.jsonl]

t=23:  [bob 下次循环时读取收件箱]
t=23:  bob 收到消息，开始测试
```

### 消息流图

```
┌─────────┐         ┌─────────┐         ┌─────────┐
│  Lead   │────────>│  Alice  │────────>│   Bob   │
│         │<────────│         │<────────│         │
└─────────┘         └─────────┘         └─────────┘
    ↑                   ↑                   ↑
    │                   │                   │
  lead.jsonl        alice.jsonl         bob.jsonl
```

## 与其他方案对比

### Subagent (s04) vs Teammate (s09)

| 特性 | Subagent | Teammate |
|-----|----------|----------|
| **生命周期** | spawn → execute → return → destroyed | spawn → work → idle → work → ... → shutdown |
| **状态** | 无 | idle/working/shutdown |
| **记忆** | 每次调用独立 | 跨调用保留 |
| **通信** | 返回摘要 | JSONL 收件箱 |
| **线程** | 函数调用（同步） | 独立线程（异步） |
| **适用场景** | 一次性任务 | 持久协作 |

### s08 后台任务 vs s09 团队

| 特性 | s08 | s09 |
|-----|-----|-----|
| **执行内容** | shell 命令 | 完整 agent loop |
| **决策能力** | 无（固定命令） | 有（LLM 驱动） |
| **通信** | 通知队列 | 收件箱 |
| **状态** | running/completed | idle/working/shutdown |
| **数量** | 多个任务 | 多个持久 agent |

## 实现细节分析

### 线程安全

```python
# MessageBus 的 send() 方法
with open(inbox_path, "a") as f:
    f.write(json.dumps(msg) + "\n")
```

**问题**：文件追加是原子操作吗？

- **Unix**：单次 `write()` < 4KB 是原子的
- **Windows**：不一定

**生产级改进**：需要文件锁或使用消息队列。

### daemon=True

```python
thread = threading.Thread(..., daemon=True)
```

**守护线程**：
- 主线程退出时自动终止
- 不会阻止程序退出
- 适合"可以随时丢弃"的后台任务

### 50 轮限制

```python
for _ in range(50):
    # ...
```

**为什么有限制**：
- 防止无限循环
- 防止资源泄漏
- 50 轮通常足够完成任务

**生产级改进**：应该基于任务完成度或超时。

## 这是一个完整的多 Agent 系统吗？

### ✅ 已实现的核心功能

| 功能 | 实现方式 |
|-----|---------|
| 多实例 | 每个队友独立线程 |
| 持久化 | config.json |
| 消息传递 | JSONL 收件箱 |
| 双向通信 | Lead ↔ Teammate |
| 广播 | 一对多消息 |
| 状态管理 | idle/working/shutdown |
| 独立上下文 | 每个 teammate 自己的 messages |

### ❌ 缺少的生产级功能

| 功能 | s09 | 生产级 |
|-----|-----|--------|
| 错误处理 | 基本 try/except | 重试、死信队列 |
| 消息可靠性 | 文件追加 | 确认机制、幂等性 |
| 并发控制 | 简单文件操作 | 分布式锁、事务 |
| 任务调度 | 手动认领 | 自动分配、负载均衡 |
| 监控 | print | 指标、追踪 |
| 安全 | 路径检查 | 认证、授权 |
| 扩展性 | 单机文件 | 分布式、消息队列 |

### 完整度评估

```
教学完整度：═══════════════════════ 80%
生产完整度：═══════════════ 40%

s09 的定位：完整的多 agent 系统骨架
            适合学习、原型、小团队工具
```

### 什么时候够用？

| 场景 | s09 是否足够 |
|-----|-------------|
| 学习多 agent 概念 | ✅ 完美 |
| 个人项目原型 | ✅ 够用 |
| 小团队内部工具 | ✅ 基本够用 |
| 生产环境部署 | ❌ 需要增强 |
| 高可靠性要求 | ❌ 需要重写 |
| 大规模部署 | ❌ 需要分布式 |

## 后续演进

### s10: 团队协议

- 关闭流程：shutdown_request → shutdown_response
- 计划审批：plan → plan_approval_response
- FSM 状态机

### s11: 自主代理

- 空闲循环：定时检查任务
- 自动认领：无需 Lead 分配
- 自主协调

### s12: Worktree 隔离

- 每个任务独立工作目录
- 防止文件冲突
- 并行执行

## 核心洞察

### 1. 持久化带来记忆

> **"队友不是一次性的，他们记得你是谁"**

config.json 和独立的 messages 列表让队友可以：
- 跨调用保持上下文
- 记住之前的工作
- 持续改进和学习

### 2. 异步通信解耦

> **"发送者不需要等待接收者在线"**

JSONL 收件箱是异步的：
- 发送者写入文件
- 接收者下次循环时读取
- 允许并行工作

### 3. 简单胜过复杂

> **"文件系统是最简单的消息队列"**

- 可观测：直接查看 `.jsonl` 文件
- 可调试：手动编辑消息
- 无依赖：不需要 Redis/RabbitMQ

**这正是教学项目的价值 —— 用最简单的方式展示核心概念。**

## 总结

### 多 Agent 团队的价值

| 维度 | 价值 |
|-----|------|
| **并行** | 多个任务同时进行 |
| **专业** | 不同角色专注不同领域 |
| **协作** | 互相通信、协调 |
| **持久** | 长期记忆和状态 |

### 设计权衡

| 选择 | 理由 |
|-----|------|
| JSONL 而非数据库 | 简单、可观测 |
| 文件系统而非消息队列 | 无外部依赖 |
| daemon 线程而非进程 | 简单的并发 |
| 50 轮限制 | 防止资源泄漏 |

### 使用建议

- **学习概念**：s09 是完美的起点
- **快速原型**：可以直接用
- **生产环境**：需要增强可靠性

### 与生产框架对比

| 框架 | 定位 |
|-----|------|
| **s09** | 教学原型 |
| **AutoGen** | 微软的多 agent 框架 |
| **CrewAI** | 角色驱动的多 agent |
| **LangGraph** | 状态机驱动的 agent |

**s09 不是要替代这些框架 —— 而是让你理解它们的核心原理。**

> **"最好的学习方式是从最简单的实现开始，然后逐步理解复杂框架的设计决策。"**
