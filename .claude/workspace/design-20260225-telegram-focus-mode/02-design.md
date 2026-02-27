# 系统设计：Telegram 任务关注模式

## 1. 架构概览

### 核心思路

**通知通道从双通道合并为单通道**：Orchestrator 不再直接调用 Telegram API，所有通知数据写入文件，由 Daemon 统一读取并推送。

```
改动前（双通道，有重复推送问题）:
  Orchestrator ──直推──→ Telegram API    （每轮数字 + 关键事件）
  Daemon ──轮询 state.json──→ Telegram API  （状态变更）

改动后（单通道，Daemon 统一推送）:
  Orchestrator ──写入──→ turns.jsonl（每轮详细数据）
  Daemon ──读取 turns.jsonl──→ Telegram API  （关注任务的每轮详情）
  Daemon ──轮询 state.json──→ Telegram API   （所有任务的状态变更）
```

Orchestrator 彻底不再调用 Telegram API。`_telegram_push` 和 `_telegram_push_turn` 方法全部删除。

### 为什么不直接增强 Orchestrator 直推

Orchestrator 是独立的 worker 进程，不知道哪个任务被关注。让 Orchestrator 读取 focus 状态文件虽然可行，但引入了 Daemon → Orchestrator 的反向 IPC，破坏了现有单向数据流设计。

### 为什么不只用 state.json 轮询

state.json 只保留最后一轮的快照（`last_output_summary` 500 字符），快速轮次可能被跳过。JSONL 追加文件确保每轮数据不丢失。

## 2. 详细设计

### 2.1 新增文件：turns.jsonl

**路径**: `~/.maestro/sessions/<task_id>/turns.jsonl`

**格式**: 每行一个 JSON 对象，追加写入（Orchestrator 端）。

```json
{"turn": 1, "max_turns": 30, "output_summary": "我来分析登录模块...", "instruction": "修改 auth.py 第 42 行", "reasoning": "代码分析完成，发现验证逻辑有误", "action": "execute", "duration_ms": 7800, "turn_cost": 0.0, "total_cost": 0.0, "timestamp": "2026-02-25T16:42:00"}
```

**字段说明**:

| 字段 | 类型 | 说明 |
|------|------|------|
| turn | int | 轮次序号 |
| max_turns | int | 最大轮次 |
| output_summary | str | Claude Code 输出摘要（截取最后 2000 字符） |
| instruction | str | Manager 给出的下一条指令（截取前 200 字符） |
| reasoning | str | Manager 的决策推理 |
| action | str | Manager 的 action（execute/done/blocked/ask_user/retry） |
| duration_ms | int | 本轮编码工具执行耗时 |
| turn_cost | float | 本轮编码工具费用 |
| total_cost | float | 累计费用（编码工具 + Manager） |
| timestamp | str | ISO 格式时间戳 |

### 2.2 orchestrator.py 改动

#### 2.2.1 新增 `_write_turn_event()` 方法

在主循环的 step (h) Manager 决策完成后调用，将本轮完整数据追加到 `turns.jsonl`。

```python
def _write_turn_event(self, turn: int, result: RunResult, parsed: dict):
    """将轮次事件写入 turns.jsonl（供 Daemon 读取推送）"""
    total_cost = self.breaker.total_cost + self.manager.total_cost
    event = {
        "turn": turn,
        "max_turns": self.config.manager.max_turns,
        "output_summary": result.output[-2000:] if result.output else "",
        "instruction": parsed.get("instruction", "")[:200],
        "reasoning": parsed.get("reasoning", ""),
        "action": parsed.get("action", ""),
        "duration_ms": result.duration_ms,
        "turn_cost": result.cost_usd,
        "total_cost": total_cost,
        "timestamp": datetime.now().isoformat(),
    }
    turns_path = self.session_dir / "turns.jsonl"
    with open(turns_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")
```

#### 2.2.2 删除 Telegram 直推相关代码

**彻底删除以下方法**（不是保留不调用，而是从类中移除）：
- `_telegram_push()` — 原关键事件直推
- `_telegram_push_turn()` — 原每轮数字直推

**移除所有 `_telegram_push` 调用点**：
- `_main_loop` step (e): 移除 `self._telegram_push_turn(...)` 调用
- `_handle_done`: 移除 `self._telegram_push(...)` 调用
- `_handle_blocked`: 移除 `self._telegram_push(...)` 调用
- `_handle_ask_user`: 移除 `self._telegram_push(...)` 调用
- `_handle_breaker`: 移除 `self._telegram_push(...)` 调用
- `_handle_max_turns`: 移除 `self._telegram_push(...)` 调用
- `_handle_timeout`: 移除 `self._telegram_push(...)` 调用

这些事件全部由 Daemon 的 `_push_status_change` 通过 state.json 轮询检测并推送，不再重复。

#### 2.2.3 在主循环 step (h) 之后新增 step

```python
# (h2) 写入轮次事件文件
self._write_turn_event(turn, result, parsed)
```

### 2.3 telegram_bot.py 改动

#### 2.3.1 新增状态字段

```python
class TelegramDaemon:
    def __init__(self, ...):
        ...
        # 关注模式
        self._focused_task_id: Optional[str] = None
        # 各任务的 turns.jsonl 读取位置（字节偏移）
        self._turn_file_positions: dict[str, int] = {}
```

#### 2.3.2 新增 `/focus` 命令

```python
async def _on_focus(self, update, context):
    """处理 /focus 命令"""
    if not self._check_auth(update.effective_chat.id):
        await update.message.reply_text("未授权")
        return

    args = context.args
    if not args:
        # 查看当前关注
        if self._focused_task_id:
            state = self._read_state(self._focused_task_id)
            req = state.get("requirement", "未知")[:40] if state else "未知"
            turn = state.get("current_turn", 0) if state else 0
            max_t = state.get("max_turns", 0) if state else 0
            await update.message.reply_text(
                f"当前关注: [{self._focused_task_id}]\n"
                f"需求: {req}\n"
                f"进度: Turn {turn}/{max_t}"
            )
        else:
            await update.message.reply_text("当前未关注任何任务")
        return

    # /focus off — 取消关注
    if args[0] in ("off", "none"):
        self._focused_task_id = None
        await update.message.reply_text("已取消关注")
        return

    # /focus <task_id> — 切换关注
    task_id = args[0]
    state = self._read_state(task_id)
    if not state:
        await update.message.reply_text(f"任务 {task_id} 不存在")
        return

    self._focused_task_id = task_id
    # 跳过历史轮次，只推送切换后的新轮次
    self._seek_turns_to_end(task_id)

    req = state.get("requirement", "")[:40]
    turn = state.get("current_turn", 0)
    max_t = state.get("max_turns", 0)
    await update.message.reply_text(
        f"已关注任务 [{task_id}]\n"
        f"需求: {req}\n"
        f"当前进度: Turn {turn}/{max_t}"
    )
```

辅助方法：

```python
def _seek_turns_to_end(self, task_id: str):
    """将 turns.jsonl 读取位置设到文件末尾（跳过历史）"""
    turns_path = (
        Path("~/.maestro/sessions").expanduser()
        / task_id / "turns.jsonl"
    )
    if turns_path.exists():
        self._turn_file_positions[task_id] = turns_path.stat().st_size
    else:
        self._turn_file_positions[task_id] = 0
```

注册：`app.add_handler(CommandHandler("focus", self._on_focus))`

#### 2.3.3 修改 `_on_run` 自动关注

在 `_on_run` 末尾，启动 worker 之后：

```python
# 自动关注新任务
self._focused_task_id = task_id
# 新任务还没有 turns.jsonl，偏移量初始化为 0
self._turn_file_positions[task_id] = 0

await update.message.reply_text(
    f"任务 [{task_id}] 已启动（已自动关注）\n"
    f"目录: {real_dir}\n"
    f"需求: {requirement}\n\n"
    f"查看状态: /status {task_id}\n"
    f"终止任务: /abort {task_id}\n"
    f"切换关注: /focus <其他任务ID>"
)
```

#### 2.3.4 增强 `_monitor_loop` — 读取 turns.jsonl

在现有的 `_monitor_loop` 中，对关注任务额外读取 `turns.jsonl` 新增条目并推送：

```python
async def _monitor_loop(self, context):
    """定期轮询所有任务状态 + 关注任务的轮次输出"""
    sessions_dir = Path("~/.maestro/sessions").expanduser()
    if not sessions_dir.exists():
        return

    for task_dir in sessions_dir.iterdir():
        ...  # 现有的状态变更检测逻辑不变

    # 关注任务：读取新的轮次事件
    if self._focused_task_id:
        await self._push_focused_turns(context)
```

新增方法：

```python
async def _push_focused_turns(self, context):
    """读取关注任务的 turns.jsonl 新增条目并推送"""
    task_id = self._focused_task_id
    if not task_id:
        return

    turns_path = (
        Path("~/.maestro/sessions").expanduser()
        / task_id / "turns.jsonl"
    )
    if not turns_path.exists():
        return

    # 获取上次读取位置
    last_pos = self._turn_file_positions.get(task_id, 0)

    try:
        with open(turns_path, "r", encoding="utf-8") as f:
            f.seek(last_pos)
            new_lines = f.readlines()
            new_pos = f.tell()
    except OSError:
        return

    if not new_lines:
        return

    self._turn_file_positions[task_id] = new_pos

    # 解析并推送每个新轮次
    for line in new_lines:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg = self._format_turn_message(task_id, event)
        try:
            sent = await context.bot.send_message(
                chat_id=self.config.telegram.chat_id,
                text=msg,
            )
            self._message_task_map[sent.message_id] = task_id
        except Exception as e:
            logger.warning(f"关注任务推送失败: {e}")
```

#### 2.3.5 轮次消息格式化

```python
def _format_turn_message(self, task_id: str, event: dict) -> str:
    """格式化轮次事件为 Telegram 消息"""
    turn = event.get("turn", 0)
    max_turns = event.get("max_turns", 0)
    duration = event.get("duration_ms", 0)
    duration_s = duration / 1000
    output = event.get("output_summary", "")
    reasoning = event.get("reasoning", "")
    instruction = event.get("instruction", "")
    action = event.get("action", "")

    # 构建消息
    header = f"[{task_id}] Turn {turn}/{max_turns} ({duration_s:.1f}s)"

    # 输出内容（vibing 判断）
    if not output or len(output.strip()) < 20:
        output_section = "Claude Code vibing..."
    else:
        # 截断到 1500 字符（给 header + reasoning + instruction 留约 500 字符空间）
        max_output_len = 1500
        if len(output) > max_output_len:
            output = output[-max_output_len:]
            output = "..." + output
        output_section = output

    # Manager 决策
    parts = [header, "", output_section]

    if reasoning:
        parts.append(f"\nManager: {reasoning[:300]}")
    if instruction and action == "execute":
        parts.append(f"下一步: {instruction[:150]}")

    msg = "\n".join(parts)

    # Telegram 4096 字符限制
    if len(msg) > 4000:
        msg = msg[:4000] + "\n...(已截断)"

    return msg
```

#### 2.3.6 关注任务结束时自动取消关注

在 `_push_status_change` 中，检测关注任务的终结状态：

```python
async def _push_status_change(self, context, task_id, state, old, new):
    ...  # 现有逻辑不变

    # 关注任务结束时自动取消关注
    if task_id == self._focused_task_id and new in ("completed", "failed", "aborted"):
        self._focused_task_id = None
```

#### 2.3.7 Daemon 启动时初始化轮次偏移量

避免重启后重放历史轮次：

```python
async def start(self):
    ...
    # 跳过现有 turns.jsonl 的历史内容
    self._init_turn_positions()
    ...
```

```python
def _init_turn_positions(self):
    """初始化时跳过已有的 turns.jsonl 内容"""
    sessions_dir = Path("~/.maestro/sessions").expanduser()
    if not sessions_dir.exists():
        return
    for task_dir in sessions_dir.iterdir():
        if not task_dir.is_dir():
            continue
        turns_path = task_dir / "turns.jsonl"
        if turns_path.exists():
            self._turn_file_positions[task_dir.name] = turns_path.stat().st_size
```

#### 2.3.8 更新帮助文本

`_on_start` 中新增 `/focus` 说明：

```
"/focus [id] - 查看/切换关注任务\n"
"/focus off - 取消关注\n"
```

### 2.4 config.py 改动

删除 `push_every_turn` 字段。Orchestrator 不再直接推送 Telegram，该配置已无意义。

```python
@dataclass
class TelegramConfig:
    """Telegram Bot 配置"""
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""                 # 授权用户 chat_id
    ask_user_timeout: int = 3600      # ASK_USER 等待超时（秒）
    # push_every_turn 已删除，Daemon 统一管理推送
```

同步更新 `config.example.yaml` 移除 `push_every_turn` 字段。

## 3. 数据流图

```
用户发送 /run
    │
    ▼
TelegramDaemon._on_run()
    ├─ 创建任务 + 启动 worker
    ├─ self._focused_task_id = task_id   ← 自动关注
    └─ 回复 "任务已启动（已自动关注）"

Worker 进程 (Orchestrator._main_loop)
    │
    ├─ (b) ToolRunner.run() → result
    ├─ (d) 更新 state.json
    ├─ (g) Manager.decide() → parsed
    ├─ (h) 更新 state.json（Manager 信息）
    ├─ (h2) 写入 turns.jsonl              ← 新增
    └─ 循环
    （Orchestrator 不再直接调用 Telegram API）

TelegramDaemon._monitor_loop() [每 5 秒]
    │
    ├─ 遍历所有任务 state.json
    │   └─ 检测状态变更 → 推送（completed/failed/waiting_user/aborted）
    │
    └─ 如果有 focused_task_id:
       └─ _push_focused_turns()
          ├─ 读取 turns.jsonl 新增行（基于字节偏移量）
          ├─ 格式化为详细消息（含 output + reasoning + instruction）
          └─ 推送到 Telegram
```

## 4. 改动文件清单

| 文件 | 改动类型 | 改动内容 |
|------|----------|----------|
| `orchestrator.py` | 修改 | 新增 `_write_turn_event()`；删除 `_telegram_push()`、`_telegram_push_turn()` 方法及所有调用点 |
| `telegram_bot.py` | 修改 | 新增 `_focused_task_id`/`_turn_file_positions` 状态；新增 `/focus` 命令（含 off）；新增 `_push_focused_turns()`/`_format_turn_message()`/`_seek_turns_to_end()`/`_init_turn_positions()`；修改 `_on_run`（自动关注）、`_monitor_loop`（读取 turns）、`_push_status_change`（自动取消关注）、`_on_start`（帮助文本） |
| `config.py` | 修改 | 删除 `push_every_turn` 字段 |
| `config.example.yaml` | 修改 | 移除 `push_every_turn` 配置项 |

## 5. 边界情况处理

### 5.1 快速轮次合并

如果 Daemon 5s 轮询间隔内有多个轮次完成，所有新增行都会被读取并逐条推送。Telegram 可能短时间收到多条消息，这是可接受的（比丢失信息好）。

### 5.2 Daemon 重启

`_turn_file_positions` 存内存，重启后通过 `_init_turn_positions()` 将所有现有 turns.jsonl 偏移量设到文件末尾，跳过历史，不会重放。

### 5.3 Focus 切换时跳过历史

`/focus <task_id>` 切换关注时，调用 `_seek_turns_to_end()` 将偏移量设到文件末尾。用户只看到切换后的新轮次，不会被历史信息淹没。

### 5.4 并发写入安全

`turns.jsonl` 只有一个写入者（Orchestrator worker），Daemon 只读取。无需文件锁。

### 5.5 磁盘清理

turns.jsonl 会持续增长，但每行约 200-2500 字节，30 轮最多约 75KB，不是问题。任务结束后随 session 目录整体清理。

### 5.6 关键事件延迟

移除 Orchestrator 直推后，关键事件（done/blocked/ask_user）由 Daemon 通过 state.json 轮询检测，最大延迟 5 秒。对于用户交互场景这完全可接受。

## 6. 测试要点

- 验证 turns.jsonl 写入格式正确
- 验证 Orchestrator 不再调用 Telegram API（`_telegram_push` 已删除）
- 验证 _push_focused_turns 能正确读取增量内容
- 验证 /focus 命令的查看、切换、off
- 验证 /focus 切换时跳过历史轮次
- 验证 /run 自动关注
- 验证关注任务结束后自动取消关注
- 验证非关注任务不推送每轮详情但推送状态变更
- 验证 output_summary 为空时显示 "vibing"
- 验证 Telegram 消息长度不超过 4096
- 验证 Daemon 重启后不重放历史轮次

## 7. Review 修复记录

| Issue | 级别 | 修复内容 |
|-------|------|----------|
| 关键事件重复推送 | HIGH | 删除 Orchestrator 所有 `_telegram_push` 调用，Daemon 统一推送 |
| push_every_turn 死代码 | MEDIUM | 删除该配置字段和方法，不保留无效代码 |
| focus 切换历史重放 | MEDIUM | 新增 `_seek_turns_to_end()`，切换时跳到文件末尾 |
| 缺少 /focus off | LOW | `/focus off` 或 `/focus none` 取消关注 |
| 截断上限不一致 | LOW | turns.jsonl 写入 2000 字符，格式化截断改为 1500 字符 |
