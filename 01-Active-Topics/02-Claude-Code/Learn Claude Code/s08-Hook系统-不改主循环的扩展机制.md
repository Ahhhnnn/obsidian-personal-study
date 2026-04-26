# s08: Hook 系统 - 不改主循环的扩展机制

> *"主循环暴露时机，附加行为从外部接入"*

## 要解决的问题

s07 有了权限系统，工具执行前能做"允许/拒绝"。但很多需求不属于这条线：

- 会话开始时初始化环境
- 工具执行后写审计日志
- write_file 前自动备份
- bash 执行前改写参数里的危险路径

这些需求有个共性：需要在固定时机触发，但不属于主循环的核心逻辑。每来一个需求就去改循环体，最后谁都不敢动那坨代码。

Hook 的思路：主循环不变，扩展行为从外部接入。

## 三个事件 + 三种退出码

教学版只讲 3 个事件，不是系统永远只有 3 个，而是先跑通这 3 个再扩展也不会乱。

| 事件 | 时机 |
|------|------|
| `SessionStart` | 会话开始 |
| `PreToolUse` | 工具执行前 |
| `PostToolUse` | 工具执行后 |

所有事件共享同一套退出码：

| 退出码 | 效果 |
|-------|------|
| 0 | 观察后放行 |
| 1 | 阻止，工具不执行 |
| 2 | 补一条消息给模型，继续 |

观察、拦截、补充。三个词记住就行。

## Hook 配置

`.hooks.json` 文件：

```json
{
  "hooks": {
    "SessionStart": [{"command": "echo 'Welcome!'"}],
    "PreToolUse": [
      {"matcher": "bash", "command": "check-dangerous.sh"},
      {"matcher": "*", "command": "audit-log.sh"}
    ],
    "PostToolUse": [
      {"matcher": "write_file", "command": "backup.sh"}
    ]
  }
}
```

`matcher` 按工具名过滤，`*` 匹配所有。不写 matcher 也匹配所有。

## HookManager 做了什么

### 加载

启动时读 `.hooks.json`，按事件名分组。文件不存在或解析失败不报错，静默跳过。

### 工作区信任

```python
TRUST_MARKER = WORKDIR / ".claude" / ".claude_trusted"
```

hooks 执行前检查这个标记文件。不存在说明工作区未受信任，所有 hooks 跳过。防止 clone 了别人的项目后被恶意 hook 脚本注入。SDK 模式下默认信任。

### 超时

教学版统一 30 秒。源码注释提到真实 Claude Code 的设置：工具 hook 10 分钟，SessionEnd hook 1.5 秒。不同事件用不同超时，SessionEnd 不该卡太久。

## Hook 执行的完整链路

### subprocess 层面

每个 hook 定义最终走到 `subprocess.run`：

```python
r = subprocess.run(
    hook_def["command"],   # .hooks.json 里的命令字符串
    shell=True,            # 通过 shell 执行，支持管道和重定向
    cwd=WORKDIR,
    env=env,               # 带上下文的环境变量
    capture_output=True,   # 捕获 stdout 和 stderr
    text=True,
    timeout=HOOK_TIMEOUT,  # 30 秒
)
```

执行前把上下文塞进环境变量：

| 变量 | 内容 | 何时有 |
|------|------|-------|
| `HOOK_EVENT` | 事件名 | 所有 |
| `HOOK_TOOL_NAME` | 工具名 | PreToolUse / PostToolUse |
| `HOOK_TOOL_INPUT` | 工具输入（JSON，截断 10000 字符） | PreToolUse / PostToolUse |
| `HOOK_TOOL_OUTPUT` | 工具输出（截断 10000 字符） | 仅 PostToolUse |

hook 脚本不需要解析参数，直接 `echo $HOOK_TOOL_INPUT` 拿上下文。截断是为了防止环境变量溢出。

### 退出码 0：放行，但可能暗藏高级操作

```python
if r.returncode == 0:
    try:
        hook_output = json.loads(r.stdout)
        if "updatedInput" in hook_output:
            context["tool_input"] = hook_output["updatedInput"]
        if "additionalContext" in hook_output:
            result["messages"].append(hook_output["additionalContext"])
        if "permissionDecision" in hook_output:
            result["permission_override"] = hook_output["permissionDecision"]
    except (json.JSONDecodeError, TypeError):
        pass  # 不是 JSON，正常放行
```

退出码 0 不只是"放行"。stdout 如果是合法 JSON，还能做三件事：

- **改写工具输入**：`{"updatedInput": {"command": "rm -rf /tmp/old --dry-run"}}`，替换危险参数
- **注入补充上下文**：`{"additionalContext": "此目录下有 500 个文件"}`，追加到 messages
- **覆盖权限决策**：`{"permissionDecision": "allow"}`，hook 替用户做了允许判断

不是 JSON 也不报错，简单脚本和高级脚本都能跑。

### 退出码 1：拦截

```python
elif r.returncode == 1:
    result["blocked"] = True
    reason = r.stderr.strip() or "Blocked by hook"
    result["block_reason"] = reason
```

拦截原因从 stderr 取。stdout 留给 JSON 高级操作，stderr 留给人读的文本。

### 退出码 2：注入消息

```python
elif r.returncode == 2:
    msg = r.stderr.strip()
    if msg:
        result["messages"].append(msg)
```

同样从 stderr 取。这条消息后续会追加到模型的上下文里。

## 结果怎么回到上下文

`run_hooks` 返回 `{"blocked": bool, "messages": [str]}`。主循环处理 Pre 和 Post 两种情况的方式不同。

### PreToolUse：补充消息是独立的 tool_result

```python
pre_result = hooks.run_hooks("PreToolUse", {
    "tool_name": block.name,
    "tool_input": tool_input,
})

# 退出码 2 的消息 → 单独一条 tool_result
for msg in pre_result.get("messages", []):
    results.append({
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": f"[Hook message]: {msg}",
    })

# 退出码 1 → 也是一条 tool_result，但内容是阻止原因
if pre_result.get("blocked"):
    results.append({
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": f"Tool blocked by PreToolUse hook: {reason}",
    })
    continue  # 跳过工具执行
```

模型收到 "[Hook message]: ..." 或 "Tool blocked: ..." 这条 tool_result，知道发生了什么，可以据此调整策略。

### PostToolUse：补充消息拼在原始输出后面

```python
# 工具先执行完
output = handler(**tool_input)

# PostToolUse hook，把工具输出也传进去
post_result = hooks.run_hooks("PostToolUse", {
    "tool_name": block.name,
    "tool_input": tool_input,
    "tool_output": output,
})

# 消息追加到 output 字符串里，不是单独的 tool_result
for msg in post_result.get("messages", []):
    output += f"\n[Hook note]: {msg}"

results.append({
    "type": "tool_result",
    "tool_use_id": block.id,
    "content": str(output),  # 原始输出 + hook 追加的说明
})
```

两种方式的区别：
- PreToolUse：单独一条 tool_result，语义是"执行前补充信息"
- PostToolUse：拼在原始 output 后面，语义是"执行完后附上说明"

### 完整数据流示例

```
模型生成 tool_use:
  name: "bash", input: {"command": "rm -rf /tmp/old"}
      |
      v
PreToolUse hook 执行:
  脚本检查目录，返回退出码 2, stderr="此目录下有重要文件"
      |
      v
主循环处理:
  results += tool_result("[Hook message]: 此目录下有重要文件")
      |
      v
(没被阻止) 执行工具 → output = "removed 50 files"
      |
      v
PostToolUse hook 执行:
  审计脚本记录日志，返回退出码 2, stderr="已记录审计日志"
      |
      v
主循环处理:
  output += "\n[Hook note]: 已记录审计日志"
  results += tool_result("removed 50 files\n[Hook note]: 已记录审计日志")
      |
      v
模型下一轮推理时看到:
  - [Hook message]: 此目录下有重要文件    (PreToolUse 注入)
  - removed 50 files                       (工具原始输出)
  - [Hook note]: 已记录审计日志             (PostToolUse 追加)
```

两个细节：
1. 被阻止时 `continue` 跳过工具执行，结果里只有阻止消息
2. `tool_input = dict(block.input or {})` 拷贝一份，PreToolUse hook 通过 `updatedInput` 改写它时不影响原始 block

## 和权限系统的边界

s07 的权限系统在主循环内部，做"允许/拒绝"这条主线。Hook 在主循环外部，做旁路附加行为：审计、通知、参数改写。两者协作但不替代。

## 几个容易忽略的点

**hook 挂了不阻塞主流程。** `try/except` 捕获异常和超时，打印错误后继续。hook 是附加行为，不该拖垮主循环。

**多个 hook 按数组顺序执行。** 遇到退出码 1 后续 hook 仍然跑完，但阻止状态已经设定。没有优先级字段，教学版够用。

**`shell=True` 有安全风险。** `.hooks.json` 被恶意修改的话（比如 clone 了别人的项目），hook 脚本能执行任意命令。工作区信任是第一道防线，但已信任的工作区没有额外校验。

**matcher 只支持精确匹配和 `*`。** 不支持正则或 `bash|write_file` 这种多选。

## 相对 s07 的变更

| 组件 | s07 | s08 |
|------|-----|-----|
| 主循环 | 内联权限检查 | + hook 接入点 |
| 扩展方式 | 改代码 | 改 .hooks.json |
| 返回语义 | 允许/拒绝 | 退出码 0/1/2 |
| 能力 | 二元决策 | 观察 + 拦截 + 补充 + 改写 |
