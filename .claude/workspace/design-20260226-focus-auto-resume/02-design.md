# 系统设计：Focus 自动恢复

## 1. 架构概览

### 核心思路

**在消息发送环节加一层"进程存活检测 + 自动 resume"逻辑**，复用现有的 `_launch_resume_background()` 和 `orchestrator.resume()` 机制。

```
当前行为:
  用户发消息 → 写 inbox.txt → 完
  （如果进程已死，inbox 无人消费）

改动后:
  用户发消息 → 写 inbox.txt → 检测进程是否存活
    ├─ 存活 → 完（与现在一致）
    └─ 已死 + 状态可恢复 → 自动启动 resume → 通知用户
```

改动集中在 `telegram_bot.py`，`orchestrator.py` 只需小幅调整 resume notice 逻辑。

## 2. 详细设计

### 2.1 telegram_bot.py: 新增 `_auto_resume_if_needed()` 方法

核心方法，被 `/ask`、直接回复、focus 后发消息三个入口共享调用。

```python
async def _auto_resume_if_needed(self, task_id: str, update) -> bool:
    """
    检测任务进程是否已死，如果是则自动恢复。

    返回 True 表示已触发恢复，False 表示进程存活无需处理。
    """
    state = self._read_state(task_id)
    if not state:
        return False

    status = state.get("status", "")

    # 只对可恢复状态触发
    if status not in ("failed", "waiting_user"):
        return False

    # 检测进程是否存活
    pid = state.get("worker_pid")
    if pid:
        try:
            os.kill(pid, 0)
            return False  # 进程存活，无需恢复
        except ProcessLookupError:
            pass  # 进程已死，继续恢复
        except PermissionError:
            return False  # 进程存在但无权限检查，视为存活

    # 防重入：避免连续消息触发多次 resume
    if task_id in self._resuming_tasks:
        return False
    self._resuming_tasks.add(task_id)

    # 启动后台 resume
    try:
        session_dir = Path("~/.maestro/sessions").expanduser() / task_id
        working_dir = state.get("working_dir", os.getcwd())

        _launch_resume_background(
            self.config, task_id, working_dir, self._config_path
        )

        await update.message.reply_text(
            f"任务 [{task_id}] 已自动恢复，你的消息已送达"
        )
        return True
    except Exception as e:
        logger.error(f"自动恢复任务 [{task_id}] 失败: {e}")
        self._resuming_tasks.discard(task_id)
        await update.message.reply_text(
            f"自动恢复失败: {e}\n手动恢复: maestro resume {task_id}"
        )
        return False
```

### 2.2 telegram_bot.py: 新增 `_resuming_tasks` 状态

防止连续消息触发多次 resume。

```python
class TelegramDaemon:
    def __init__(self, ...):
        ...
        # 自动恢复防重入
        self._resuming_tasks: set[str] = set()
```

在 `_monitor_loop` 中，当检测到任务重新变为 `executing` 状态时，从 set 中移除：

```python
# 在 _monitor_loop 中状态变更检测处
if current_status == "executing" and task_id in self._resuming_tasks:
    self._resuming_tasks.discard(task_id)
```

### 2.3 telegram_bot.py: 修改 `_on_ask()` — 集成自动恢复

在写入 inbox 后，检测是否需要自动恢复。

```python
async def _on_ask(self, update, context):
    """处理 /ask 命令"""
    ...  # 现有参数解析逻辑不变

    # 写入 inbox（不变）
    _write_inbox(str(inbox_path), "telegram", message)

    # 新增：检测是否需要自动恢复
    resumed = await self._auto_resume_if_needed(task_id, update)
    if not resumed:
        await update.message.reply_text(
            f"已向任务 [{task_id}] 发送反馈: {message}"
        )
```

### 2.4 telegram_bot.py: 修改 `_on_message()` — 直接回复 + focus 消息集成自动恢复

```python
async def _on_message(self, update, context):
    """处理普通消息"""
    ...

    # 回复任务通知消息 → inbox 路由
    reply_to = update.message.reply_to_message
    if reply_to:
        task_id = self._message_task_map.get(reply_to.message_id)
        if task_id:
            inbox_path = (
                Path("~/.maestro/sessions").expanduser()
                / task_id / "inbox.txt"
            )
            if inbox_path.parent.exists():
                _write_inbox(str(inbox_path), "telegram-reply", update.message.text)
                # 新增：自动恢复检测
                resumed = await self._auto_resume_if_needed(task_id, update)
                if not resumed:
                    await update.message.reply_text(f"已转发到任务 [{task_id}]")
            return

    # 新增：focus 模式下普通消息 → 视为对 focused 任务的回复
    if self._focused_task_id:
        task_id = self._focused_task_id
        state = self._read_state(task_id)
        status = state.get("status", "") if state else ""

        # 只有任务处于可恢复状态时，才将普通消息当作任务回复
        if status in ("failed", "waiting_user"):
            inbox_path = (
                Path("~/.maestro/sessions").expanduser()
                / task_id / "inbox.txt"
            )
            if inbox_path.parent.exists():
                _write_inbox(str(inbox_path), "telegram-focus", update.message.text)
                await self._auto_resume_if_needed(task_id, update)
                return

    # 其他消息 → 自由聊天（不变）
    await self._handle_free_chat(update)
```

### 2.5 telegram_bot.py: 修改 `_on_focus()` — 提示可恢复

在 `/focus <task_id>` 切换关注时，如果任务已停止，额外提示。

```python
# 在 _on_focus 的 "切换关注" 分支中，现有回复之后增加状态提示

status = state.get("status", "")
error = state.get("error_message", "")

if status == "failed":
    hint = f"\n状态: 失败（{error}）\n直接发消息即可自动恢复任务"
elif status == "aborted":
    hint = f"\n状态: 已终止\n如需恢复请使用 /resume {task_id}"
elif status == "completed":
    hint = "\n状态: 已完成"
elif status == "waiting_user":
    # 检测进程是否存活
    pid = state.get("worker_pid")
    process_alive = False
    if pid:
        try:
            os.kill(pid, 0)
            process_alive = True
        except (ProcessLookupError, PermissionError):
            pass
    if process_alive:
        hint = "\n状态: 等待你的回复\n直接发消息即可回复"
    else:
        hint = "\n状态: 等待回复（进程已退出）\n直接发消息即可自动恢复任务"
else:
    hint = f"\n状态: {status}"

await update.message.reply_text(
    f"已关注任务 [{task_id}]\n"
    f"需求: {req}\n"
    f"当前进度: Turn {turn}/{max_t}"
    f"{hint}"
)
```

### 2.6 orchestrator.py: 增强 resume notice — 注入 inbox 消息

修改 `resume()` 方法，在发送 resume notice 给 Manager 之前，先检查 inbox.txt 是否有待处理消息。

```python
def resume(self):
    """恢复崩溃的任务"""
    ...  # 现有的 checkpoint/state 加载不变

    # 5. 检查是否有用户待处理消息
    messages = _read_and_clear_inbox(self.inbox_path)
    user_reply = ""
    if messages:
        user_reply = "\n".join(_parse_inbox_message(m) for m in messages)

    # 6. 构建 resume notice（增强版）
    if user_reply:
        resume_notice = (
            f"[系统通知] 任务从第 {checkpoint['current_turn']} 轮恢复。"
            f"上一条指令是：{checkpoint.get('last_instruction', '未知')}。\n"
            f"用户回复了：{user_reply}\n"
            f"请基于用户的回复决定下一步操作。"
        )
    else:
        resume_notice = (
            f"[系统通知] 任务从第 {checkpoint['current_turn']} 轮崩溃恢复。"
            f"上一条指令是：{checkpoint.get('last_instruction', '未知')}。"
            f"请决定下一步操作。"
        )

    decision = self.manager.decide(resume_notice)
    ...  # 后续逻辑不变
```

### 2.7 cli.py: 复用 `_launch_resume_background()`

Daemon 需要 import 该函数。当前该函数在 `cli.py` 中，Daemon 可直接 import：

```python
# telegram_bot.py 顶部
from maestro.cli import _launch_resume_background
```

但 `_launch_resume_background` 的参数需要 `AppConfig` 和 `config_path`，Daemon 已有这两个字段（`self.config` 和 `self._config_path`），可以直接传入。

## 3. 数据流图

```
用户通过 Telegram 发消息给死任务
    │
    ▼
_on_ask / _on_message（回复/focus 消息）
    │
    ├─ 写入 inbox.txt
    │
    ├─ _auto_resume_if_needed()
    │   ├─ 读 state.json → status == "failed"?
    │   ├─ os.kill(pid, 0) → ProcessLookupError?
    │   ├─ 防重入检查 → _resuming_tasks
    │   └─ _launch_resume_background()
    │       │
    │       ▼
    │   新 Orchestrator 进程
    │       ├─ 加载 checkpoint（含 Claude Code session ID）
    │       ├─ 读取 inbox.txt → 用户消息
    │       ├─ 构建增强版 resume notice（含用户回复）
    │       ├─ Manager.decide() → 基于用户回复决策
    │       ├─ ToolRunner.run(instruction, --resume session_id)
    │       └─ 继续主循环
    │
    └─ 回复用户："任务已自动恢复，你的消息已送达"
```

## 4. 改动文件清单

| 文件 | 改动类型 | 改动内容 |
|------|----------|----------|
| `telegram_bot.py` | 修改 | 新增 `_auto_resume_if_needed()` 方法 + `_resuming_tasks` 状态；修改 `_on_ask()`、`_on_message()`、`_on_focus()` 集成自动恢复；修改 `_monitor_loop()` 清理 `_resuming_tasks` |
| `orchestrator.py` | 修改 | 修改 `resume()` 方法，恢复前读取 inbox.txt 并注入用户消息到 resume notice |

## 5. 边界情况处理

### 5.1 连续发多条消息

用户快速发送多条消息时，`_resuming_tasks` set 防重入，只有第一条触发 resume。后续消息正常写入 inbox.txt，恢复后的 Orchestrator 会在首次读取 inbox 时合并获取所有消息。

### 5.2 ABORTED 状态不自动恢复

用户主动 abort 的任务不应自动恢复。如果 abort 是误操作，用户需显式执行 `/resume`（或未来新增 `/resume` Telegram 命令）。

### 5.3 COMPLETED 状态不自动恢复

已完成的任务不恢复。用户对已完成任务发消息走自由聊天或提示"任务已完成"。

### 5.4 resume 进程启动但 inbox 消息被 Daemon 的 _monitor_loop 先消费

不会发生。Daemon 只读取 turns.jsonl，不读取 inbox.txt。inbox.txt 只有 Orchestrator 会消费。

### 5.5 Daemon 重启后 _resuming_tasks 丢失

可接受。重启后用户再发一条消息，会重新触发检测和恢复。不会导致重复 resume，因为此时进程已经在运行（kill(pid,0) 返回存活）。

### 5.6 focus 后发消息时 vs 自由聊天的区分

当 focused 任务处于 `failed` / `waiting_user` 状态时，普通消息优先视为任务回复（触发恢复）。其他状态下的普通消息仍走自由聊天，避免误触发。

## 6. 测试要点

- 验证 `/ask` 对死任务触发自动恢复
- 验证直接回复通知消息对死任务触发自动恢复
- 验证 focus 后发普通消息对死任务触发自动恢复
- 验证 `/focus` 死任务时显示恢复提示
- 验证对运行中任务的 `/ask` 行为不变
- 验证连续发多条消息只触发一次 resume
- 验证 ABORTED/COMPLETED 状态不触发自动恢复
- 验证恢复后 Manager 的 resume notice 包含用户消息
- 验证恢复后 Claude Code 使用正确的 session ID
