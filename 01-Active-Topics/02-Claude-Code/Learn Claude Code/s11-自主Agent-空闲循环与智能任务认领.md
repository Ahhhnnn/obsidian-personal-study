# s11: 自主 Agent - 空闲循环与智能任务认领

> *"队友自己看看板，有活就认领"* -- 不需要领导逐个分配，自组织。

## 问题背景

### s09-s10 的局限

队友只在被明确指派时才动：

```
Lead: "Alice，做任务 1"
Alice: [完成任务 1]

Lead: "Alice，做任务 2"
Alice: [完成任务 2]

... 领导得给每个队友写 prompt
... 任务看板上 10 个未认领的任务得手动分配
```

**问题**：
- 扩展性差 - 领导成为瓶颈
- 队友被动 - 等待指令
- 效率低 - 手动分配消耗资源

### 真正的自治

> **队友自己扫描任务看板，认领没人做的任务，做完再找下一个。**

### 另一个细节：身份遗忘

上下文压缩 (s06) 后，智能体可能忘记自己是谁。

## 解决方案：WORK/IDLE 两阶段循环

### 生命周期变化

```
s09 Teammate (被动):
spawn → work → idle → (等待 Lead 指派) → work → ...

s11 Autonomous (主动):
spawn → work → idle → (轮询任务看板) → 自动认领 → work → ...
                              ↓
                         60 秒无任务 → shutdown
```

### 状态机

```
     spawn
       ↓
   +-------+
   | WORK  | ← tool_use (继续工作)
   +---+---+
       |
       | stop_reason != tool_use 或 idle 工具
       ↓
   +--------+  每 5 秒轮询
   | IDLE   | ──────────────────────────┐
   +---+----+                           │
       │                                │
       +---> 检查收件箱 → 有消息? → resume WORK
       │                                │
       +---> 扫描 .tasks/ → 未认领? → 认领 → resume WORK
       │                                │
       +---> 超时 (60秒) → shutdown ─────┘
```

## 核心组件

### 1. 任务看板扫描

```python
def scan_unclaimed_tasks() -> list:
    """扫描未认领的任务"""
    TASKS_DIR.mkdir(exist_ok=True)
    unclaimed = []
    for f in sorted(TASKS_DIR.glob("task_*.json")):
        task = json.loads(f.read_text())
        # 条件：pending + 无 owner + 无依赖
        if (task.get("status") == "pending"
                and not task.get("owner")
                and not task.get("blockedBy")):
            unclaimed.append(task)
    return unclaimed
```

**扫描条件**：
- `status == "pending"` - 任务未开始
- `owner == null` - 无人认领
- `blockedBy == []` - 无依赖阻塞

### 2. 任务认领（带并发控制）

```python
_claim_lock = threading.Lock()  # 防止并发认领冲突

def claim_task(task_id: int, owner: str) -> str:
    with _claim_lock:
        path = TASKS_DIR / f"task_{task_id}.json"
        if not path.exists():
            return f"Error: Task {task_id} not found"
        task = json.loads(path.read_text())
        task["owner"] = owner
        task["status"] = "in_progress"
        path.write_text(json.dumps(task, indent=2))
    return f"Claimed task #{task_id} for {owner}"
```

**锁的作用**：防止两个队友同时认领同一任务。

### 3. 主循环：WORK + IDLE 两阶段

```python
def _loop(self, name: str, role: str, prompt: str):
    team_name = self.config["team_name"]
    sys_prompt = (
        f"You are '{name}', role: {role}, team: {team_name}, at {WORKDIR}. "
        f"Use idle tool when you have no more work. You will auto-claim new tasks."
    )
    messages = [{"role": "user", "content": prompt}]
    tools = self._teammate_tools()

    while True:
        # ========== WORK PHASE: 标准 agent loop ==========
        self._set_status(name, "working")

        for _ in range(50):
            # 检查收件箱
            inbox = BUS.read_inbox(name)
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    self._set_status(name, "shutdown")
                    return
                messages.append({"role": "user", "content": json.dumps(msg)})

            # LLM 调用
            response = client.messages.create(...)
            messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason != "tool_use":
                break  # 完成，进入 IDLE

            # 执行工具
            results = []
            idle_requested = False
            for block in response.content:
                if block.type == "tool_use":
                    if block.name == "idle":
                        idle_requested = True
                        output = "Entering idle phase..."
                    else:
                        output = self._exec(name, block.name, block.input)
                    results.append({...})

            messages.append({"role": "user", "content": results})

            if idle_requested:
                break  # 进入 IDLE 阶段

        # ========== IDLE PHASE: 轮询收件箱和任务 ==========
        self._set_status(name, "idle")
        resume = False
        polls = IDLE_TIMEOUT // max(POLL_INTERVAL, 1)  # 60 / 5 = 12 次

        for _ in range(polls):
            time.sleep(POLL_INTERVAL)  # 等待 5 秒

            # 1. 检查收件箱
            inbox = BUS.read_inbox(name)
            if inbox:
                for msg in inbox:
                    if msg.get("type") == "shutdown_request":
                        self._set_status(name, "shutdown")
                        return
                    messages.append({"role": "user", "content": json.dumps(msg)})
                resume = True
                break

            # 2. 扫描任务看板
            unclaimed = scan_unclaimed_tasks()
            if unclaimed:
                task = unclaimed[0]  # ← 问题：直接取第一个！
                claim_task(task["id"], name)

                # 构造任务提示
                task_prompt = (
                    f"<auto-claimed>Task #{task['id']}: {task['subject']}\n"
                    f"{task.get('description', '')}</auto-claimed>"
                )

                messages.append({"role": "user", "content": task_prompt})
                messages.append({"role": "assistant", "content": f"Claimed task #{task['id']}. Working on it."})

                resume = True
                break

        # 3. 超时无工作 → shutdown
        if not resume:
            self._set_status(name, "shutdown")
            return

        # 4. 有工作 → 回到 WORK 阶段
        # 循环继续...
```

### 4. 身份重新注入

```python
def make_identity_block(name: str, role: str, team_name: str) -> dict:
    return {
        "role": "user",
        "content": f"<identity>You are '{name}', role: {role}, team: {team_name}. Continue your work.</identity>",
    }

# 在认领任务时检查
if len(messages) <= 3:  # 上下文太短（可能被压缩过）
    messages.insert(0, make_identity_block(name, role, team_name))
    messages.insert(1, {"role": "assistant", "content": f"I am {name}. Continuing."})
```

**问题**：上下文压缩后，代理可能忘记"我是谁"

**解决**：在 messages 开头注入身份信息

## 问题分析：随机认领

### 当前实现的问题

```python
unclaimed = scan_unclaimed_tasks()
if unclaimed:
    task = unclaimed[0]  # ← 直接取第一个，没有任何匹配逻辑！
    claim_task(task["id"], name)
```

### 问题场景

```
任务看板：
├── task_1: "修复前端 CSS" (需要 frontend)
├── task_2: "编写 API 文档" (需要 writer)
└── task_3: "优化数据库查询" (需要 backend)

队友：
├── Alice (role: frontend)
└── Bob (role: backend)

s11 认领结果：
Alice → 认领 task_1 ✓ (运气好，恰好匹配)
Bob →   认领 task_2 ✗ (backend 做文档)
Alice → 认领 task_3 ✗ (frontend 做数据库)
```

### 为什么这样设计？

| 原因 | 可能性 |
|-----|--------|
| **教学简化** | ⭐⭐⭐ 重点在自主性，不在匹配算法 |
| **假设简单场景** | ⭐⭐ 假设任务都是通用的"编码任务" |
| **留作改进空间** | ⭐ 让读者思考如何优化 |

## 改进方案：让 LLM 判断

### 核心思路

> **"让 LLM 自己判断任务是否适合自己，然后决定是否认领"**

```
当前 s11：
扫描 → task[0] → 直接认领

改进方案：
扫描 → 展示任务 → LLM 判断 → 适合？认领 : 跳过
```

### 方案 1：添加 judge_task 工具

```python
# 新增工具
{
    "name": "judge_task",
    "description": "Judge if a task is suitable for you before claiming.",
    "input_schema": {
        "properties": {
            "task_id": {"type": "integer"},
            "suitable": {"type": "boolean"},
            "reason": {"type": "string"}
        },
        "required": ["task_id", "suitable"]
    }
}

# 工具处理器
def _exec(self, sender: str, tool_name: str, args: dict) -> str:
    ...
    if tool_name == "judge_task":
        task_id = args["task_id"]
        suitable = args["suitable"]
        reason = args.get("reason", "")

        if suitable:
            return claim_task(task_id, sender)
        else:
            return f"Task #{task_id} skipped: {reason}"
```

### 方案 2：批量判断（推荐）

```python
# IDLE PHASE 中
unclaimed = scan_unclaimed_tasks()

if unclaimed:
    # 展示前 5 个任务给 LLM 判断
    tasks_text = "\n".join([
        f"- Task #{t['id']}: {t['subject']} - {t.get('description', '')}"
        for t in unclaimed[:5]  # 最多展示 5 个
    ])

    judgment_prompt = f"""
You are {name}, role: {role}, at {WORKDIR}.

Available unclaimed tasks (showing first 5):
{tasks_text}

Review these tasks and claim one that suits you:
- Use claim_task(task_id=X) to claim a suitable task
- Use idle() to skip all and continue waiting

Only claim ONE task. If none are suitable, call idle().
"""

    # 注入判断提示
    if len(messages) <= 3:
        messages.insert(0, make_identity_block(name, role, team_name))

    messages.append({"role": "user", "content": judgment_prompt})

    # LLM 会调用 claim_task(task_id=X) 或 idle()
    resume = True
```

### 方案对比

| 方案 | 优点 | 缺点 |
|-----|------|------|
| **规则匹配** | 快速、确定 | 需要预定义规则 |
| **LLM 逐个判断** | 灵活、无需规则 | 慢、消耗 token |
| **LLM 批量判断** | 平衡 | 任务多时上下文长 |
| **排序 + LLM 确认** | 高效 + 灵活 | 实现稍复杂 |

## LLM 判断的优势

### 1. 灵活性

```python
# 不同角色有不同的判断标准

Alice (frontend):
"Task #5: Fix CSS bug" → suitable=true (匹配)
"Task #6: Write SQL query" → suitable=false (不匹配)

Bob (backend):
"Task #5: Fix CSS bug" → suitable=false (不匹配)
"Task #6: Write SQL query" → suitable=true (匹配)
```

### 2. 上下文感知

LLM 可以考虑：
- 之前做过类似任务
- 当前工作负载
- 自己的技能和经验
- 任务的紧急程度

### 3. 无需预定义规则

不需要维护复杂的匹配规则表：

```python
# 不需要这样的规则
ROLE_TASK_MAP = {
    "frontend": ["css", "html", "javascript"],
    "backend": ["sql", "api", "database"],
    ...
}
```

## 完整的智能认领流程

```python
def _idle_poll(self, name: str, role: str, messages: list) -> bool:
    """空闲阶段：检查收件箱和任务看板"""
    polls = IDLE_TIMEOUT // max(POLL_INTERVAL, 1)

    for _ in range(polls):
        time.sleep(POLL_INTERVAL)

        # 1. 检查收件箱（优先级高）
        inbox = BUS.read_inbox(name)
        if inbox:
            for msg in inbox:
                if msg.get("type") == "shutdown_request":
                    return False  # shutdown
                messages.append({"role": "user", "content": json.dumps(msg)})
            return True  # resume work

        # 2. 扫描任务看板
        unclaimed = scan_unclaimed_tasks()
        if unclaimed:
            # 展示给 LLM 判断
            return self._present_tasks_for_judgment(
                unclaimed[:5], name, role, messages
            )

    return False  # timeout


def _present_tasks_for_judgment(
    self, tasks: list, name: str, role: str, messages: list
) -> bool:
    """展示任务给 LLM 判断"""
    tasks_text = "\n".join([
        f"- Task #{t['id']}: {t['subject']}"
        f"  Description: {t.get('description', 'N/A')}"
        for t in tasks
    ])

    judgment_prompt = f"""
You are {name}, role: {role}, at {WORKDIR}.

Available unclaimed tasks:
{tasks_text}

Review these tasks and claim one that suits you:
- Consider your role, skills, and current workload
- Use claim_task(task_id=X) to claim a suitable task
- Use idle() to skip all and continue waiting

Only claim ONE task at a time.
"""

    # 身份重新注入（如果需要）
    if len(messages) <= 3:
        messages.insert(0, make_identity_block(name, role, team_name))
        messages.insert(1, {"role": "assistant", "content": f"I am {name}. Ready."})

    messages.append({"role": "user", "content": judgment_prompt})

    # 返回 True，让 WORK PHASE 处理 LLM 的响应
    return True
```

## 与 s09 的对比

| 特性 | s09 | s11 |
|-----|-----|-----|
| **任务分配** | Lead 手动指派 | 自动认领 |
| **空闲行为** | 等待消息 | 轮询任务看板 |
| **生命周期** | 无限期（除非 shutdown） | 60 秒超时 |
| **idle 工具** | ❌ | ✅ |
| **claim_task** | ❌ | ✅ |
| **身份注入** | ❌ | ✅ |
| **自主性** | 被动接收 | 主动寻找 |

## 参数配置

```python
POLL_INTERVAL = 5   # 每 5 秒轮询一次
IDLE_TIMEOUT = 60   # 60 秒无任务后 shutdown
```

**轮询次数**：60 / 5 = 12 次

### 轮询 vs 事件驱动

| 方式 | 优点 | 缺点 |
|-----|------|------|
| **轮询 (s11)** | 简单、可靠 | 资源浪费 |
| **事件驱动** | 高效 | 复杂、需要消息队列 |

s11 选择轮询是因为：
- 简单直接
- 不需要额外基础设施
- 5 秒间隔对教学项目足够

## 并发认领冲突

```python
_claim_lock = threading.Lock()

def claim_task(task_id: int, owner: str) -> str:
    with _claim_lock:  # 防止两个队友同时认领同一任务
        task["owner"] = owner
        task["status"] = "in_progress"
```

**场景**：
```
t=0: Alice 和 Bob 同时进入 IDLE 阶段
t=1: 两者都扫描看板，发现 task_5 未认领
t=2: Alice 获取锁 → 认领成功
t=3: Bob 获取锁 → 任务已被认领
```

## 核心洞察

### 1. 从被动到主动

```
s09: Lead → "Alice，做这个任务" → Alice 工作
s11: Alice 扫描看板 → "我认领这个任务" → Alice 工作
```

### 2. 自组织的本质

> **"不需要中央协调器，每个个体根据局部信息做出决策"**

- 任务看板 = 全局信息源
- 每个队友 = 自主决策者
- 无需 Lead 逐个分配

### 3. 简单胜过复杂

> **"文件系统是最简单的共享状态"**

- `.tasks/` 目录 = 任务看板
- JSON 文件 = 任务状态
- 文件锁 = 并发控制

## 总结

### s11 的核心创新

1. **WORK/IDLE 两阶段循环** - 工作完成后进入轮询状态
2. **任务看板扫描** - 主动查找未认领任务
3. **自动认领** - 无需 Lead 分配
4. **身份重新注入** - 压缩后保持身份
5. **空闲超时** - 60 秒无工作自动退出

### 认领机制的改进方向

| 当前实现 | 改进方案 |
|---------|---------|
| 随机认领（第一个） | LLM 判断适合度 |
| 无角色匹配 | 考虑角色和技能 |
| 无优先级 | 按优先级排序 |
| 无负载均衡 | 限制同时任务数 |

### 关键要点

- **自主性 > 完美匹配** - s11 要展示的是自主性，而不是生产级的任务分配
- **LLM 是决策者** - 利用 LLM 的理解能力，而不是硬编码规则
- **简单可扩展** - 从最简单的实现开始，按需求演进

> **"代理从被动接收者变成主动寻找者"**

这为更高级的自主代理系统奠定了基础 —— 代理可以自主决定做什么，而不是等待指令。
