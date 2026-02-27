# 代码审查报告

**审查日期**: 2026-02-26
**审查对象**: `src/maestro/telegram_bot.py`、`src/maestro/cli.py`（以及关联的 `src/maestro/orchestrator.py`）
**本次改动范围**:
1. `_launch_worker` 移除 Zellij 分支，Daemon 始终用 subprocess 模式
2. `_on_abort` 改为同时检查 registry 和 session 目录，abort 时自动取消关注
3. `_monitor_loop` 将 `_push_focused_turns()` 移到状态变更检测之前
4. 新增 `/cd` 命令设置默认工作目录
5. `/run` 简化为只需 `/run <需求>`（需先 /cd）
6. `/status`、`/ask`、`/abort`、`/report` 支持省略 task_id，默认用 focused task
7. CLI 版 `_handle_abort` 同步修复

---

## 1. 审查摘要表

| 级别 | 数量 | 说明 |
|------|------|------|
| Critical | 0 | 无 |
| High | 2 | task_id 识别逻辑有误、/cd 路径穿越风险 |
| Medium | 4 | `_default_working_dir` 无持久化说明、_monitor_loop 顺序改动引入细微竞态、`_on_chat` 未适配 focused_task_id、帮助文本 `/ask /chat /abort /report` 参数说明未更新 |
| Low | 3 | `_handle_abort` 缺少 focused_task_id 同步能力、`_launch_worker` 文件句柄泄漏风险、测试中 _create_daemon 缺少 `_default_working_dir` 字段 |
| Info | 2 | turns.jsonl 异常行静默跳过、`_monitor_loop` 中进程健康检查的 OSError 未处理 |

**整体评估**: REQUEST CHANGES（2 个 High 问题必须修复后通过）

---

## 2. 详细发现

### High

#### [CR-001] `_on_ask` task_id 识别逻辑有假阴性漏洞

**文件**: `src/maestro/telegram_bot.py:301`

**问题描述**:
```python
if len(args) >= 2 and len(first) == 8 and all(c in "0123456789abcdef" for c in first):
    task_id = first
    message = " ".join(args[1:])
elif self._focused_task_id:
    task_id = self._focused_task_id
    message = " ".join(args)
else:
    await update.message.reply_text("用法: /ask <task_id> <消息>（或先 /focus 一个任务）")
    return
```

`uuid.uuid4()[:8]` 生成的 task_id 是 UUID 前 8 位，包含 `0-9` 和 `a-f`，但 **UUID 中可能包含大写字母**（虽然 Python `uuid4()` 默认小写，但这是实现细节，不是契约保证）。此处仅检查小写十六进制字符集 `"0123456789abcdef"`，若 UUID 实现变更或 task_id 以其他方式生成（例如 `str(uuid.uuid4())[:8].upper()`），识别将失败，消息会被路由到错误任务。

更严重的问题：如果用户消息的**第一个词**恰好是 8 位十六进制字符串（如密码 `abc123de`），会被误识别为 task_id，导致消息被发送到该 task（可能是不存在或其他任务）而非关注任务，用户无反馈提示。

**修复建议**: 使用 registry 或 session 目录存在性来验证 task_id，而非依赖格式猜测：

```python
first = args[0]
# 尝试将第一个参数作为 task_id 验证（检查 session 目录是否存在）
maybe_task_id_path = (
    Path("~/.maestro/sessions").expanduser() / first
)
if len(args) >= 2 and maybe_task_id_path.is_dir():
    task_id = first
    message = " ".join(args[1:])
elif self._focused_task_id:
    task_id = self._focused_task_id
    message = " ".join(args)
else:
    await update.message.reply_text("用法: /ask <task_id> <消息>（或先 /focus 一个任务）")
    return
```

此方式的语义更清晰：只要 session 目录存在就认为是有效 task_id，不依赖字符格式假设。

---

#### [CR-002] `/cd` 命令路径处理不防御路径穿越

**文件**: `src/maestro/telegram_bot.py:456-466`

**问题描述**:
```python
path = " ".join(args)
real_path = os.path.realpath(
    os.path.expanduser(os.path.expandvars(path))
)
if not os.path.isdir(real_path):
    await update.message.reply_text(f"目录不存在: {real_path}")
    return
self._default_working_dir = real_path
```

`os.path.expandvars(path)` 会展开用户传入路径中的 **Shell 环境变量**（如 `$HOME`、`$PATH`）。Telegram Bot 运行在服务器上，攻击者（即便是授权用户）若知道服务器上存在某环境变量，可以通过 `/cd $SECRET_DIR` 来探测敏感路径是否存在（通过"目录不存在"的错误反馈即可判断）。

虽然 `_check_auth` 限制了访问，但在多用户场景（`chat_id` 留空时 `_check_auth` 返回 `True`，允许所有人）这是高风险行为。即使单用户场景，遭遇账号被盗或 Bot Token 泄露时也会放大危害。

**修复建议**: 移除 `expandvars`，仅保留 `expanduser`：

```python
path = " ".join(args)
real_path = os.path.realpath(
    os.path.expanduser(path)  # 只展开 ~ ，不展开 $VAR
)
```

---

### Medium

#### [CR-003] `_default_working_dir` 无持久化——用户体验问题未在帮助文本中说明

**文件**: `src/maestro/telegram_bot.py:59-60, 147-167`

**问题描述**:
`_default_working_dir` 存储在内存中，Daemon 重启后丢失（与 `_focused_task_id` 一致，需先 `/cd` 后才能 `/run`）。但 `/start` 帮助文本仅写 `/cd <路径> - 设置工作目录` 和 `/run <需求> - 启动任务（需先 /cd）`，没有说明重启后需要重新 `/cd`。

用户重启 Daemon 后直接 `/run <需求>`，会收到 `请先设置工作目录` 提示，可能造成困惑——上次明明设过。

**修复建议**: 在 `/run` 的错误提示和帮助文本中补充说明：

```python
# _on_run 中
await update.message.reply_text(
    "请先设置工作目录:\n/cd /home/user/project\n\n"
    "注意: Daemon 重启后工作目录需要重新设置"
)
```

---

#### [CR-004] `_monitor_loop` 顺序改动引入细微竞态：最后几轮可能漏推送

**文件**: `src/maestro/telegram_bot.py:570-626`

**问题描述**:
当前顺序：
```
(1) _push_focused_turns()     ← 先读 turns.jsonl
(2) 遍历所有任务检测状态变更
(3) _push_status_change() 如果状态变为 completed/failed/aborted
    └─ _focused_task_id = None  ← 清除关注
```

这个顺序的意图是"在状态变更清除关注之前先推送完最后几轮"，逻辑正确。

但存在一个边界问题：`_push_focused_turns()` 读取的是当前循环**开始时**的 `_focused_task_id`，而 turns.jsonl 中可能还没有最后一轮（Orchestrator 在写完 turns.jsonl 之后才写 state.json 标记 completed）。因此：

- 第 N 次 monitor_loop：`_push_focused_turns()` 推送了 Turn 1..K，但 Turn K+1（最后轮）还没写入；随后 state 变为 completed，`_focused_task_id = None`
- 第 N+1 次 monitor_loop：`_focused_task_id` 为 None，`_push_focused_turns()` 跳过；Turn K+1 永远丢失

这是设计级别的已知限制（原设计文档 section 5.1 也提及），但**当前的顺序改动并没有完全解决它，只是稍微缓解了**（减少了一次轮询延迟）。

**修复建议**: 在 `_push_status_change` 将 `_focused_task_id` 清空**之前**，额外再调用一次 `_push_focused_turns()`，确保在清除关注前抢读最后几轮：

```python
async def _push_status_change(self, context, task_id, state, old, new):
    ...
    # 关注任务结束时：先推完最后几轮，再清除关注
    if task_id == self._focused_task_id and new in (
        "completed", "failed", "aborted"
    ):
        await self._push_focused_turns(context)   # 抢读最后几轮
        self._focused_task_id = None
```

---

#### [CR-005] `_on_chat` 未支持省略 task_id 使用 focused_task_id

**文件**: `src/maestro/telegram_bot.py:324-365`

**问题描述**:
本次改动中 `/status`、`/ask`、`/abort`、`/report` 均已支持省略 task_id 使用 focused_task_id，但 `_on_chat` 仍要求必须提供 task_id（`if len(args) < 2`），没有适配：

```python
args = context.args
if len(args) < 2:
    await update.message.reply_text("用法: /chat <task_id> <问题>")
    return
task_id = args[0]
user_message = " ".join(args[1:])
```

与改动目标不一致（需求文档 NFR-3 "不影响现有命令" 可理解为不破坏，但从用户体验一致性角度，`/chat` 也应支持省略 task_id）。

**修复建议**: 与 `/ask` 的处理方式保持一致：

```python
args = context.args
if not args:
    await update.message.reply_text("用法: /chat <问题>（已 focus 时）或 /chat <task_id> <问题>")
    return

first = args[0]
maybe_task_id_path = Path("~/.maestro/sessions").expanduser() / first
if len(args) >= 2 and maybe_task_id_path.is_dir():
    task_id = first
    user_message = " ".join(args[1:])
elif self._focused_task_id:
    task_id = self._focused_task_id
    user_message = " ".join(args)
else:
    await update.message.reply_text("用法: /chat <task_id> <问题>（或先 /focus 一个任务）")
    return
```

---

#### [CR-006] 帮助文本 `/status`、`/ask`、`/abort`、`/report` 说明未更新

**文件**: `src/maestro/telegram_bot.py:152-167`

**问题描述**:
```python
"/status <id> - 查看任务详情\n"
"/ask <id> <消息> - 发送反馈\n"
"/chat <id> <问题> - 与 Agent 对话\n"
"/abort <id> - 终止任务\n"
"/report <id> - 查看报告\n"
```

帮助文本中这些命令仍写 `<id>`，但实际上 `/status`、`/ask`、`/abort`、`/report` 均已支持省略 id。帮助文本与实际行为不符，会引导用户做不必要的操作。

**修复建议**:
```python
"/status [id] - 查看任务详情（省略 id 用关注任务）\n"
"/ask [id] <消息> - 发送反馈（省略 id 用关注任务）\n"
"/chat <id> <问题> - 与 Agent 对话\n"
"/abort [id] - 终止任务（省略 id 用关注任务）\n"
"/report [id] - 查看报告（省略 id 用关注任务）\n"
```

---

### Low

#### [CR-007] CLI `_handle_abort` 缺少 focused_task_id 联动——设计上与 Telegram 版不对称

**文件**: `src/maestro/cli.py:360-382`

**问题描述**:
CLI 版 `_handle_abort` 已同步了"检查 registry + session 目录"的修复，这是正确的。但 CLI 版本不存在 `_focused_task_id` 概念（CLI 是无状态命令行），这是设计上应有的差异，无需修复。

然而，`_handle_abort` 在 registry 中更新状态时，没有处理 `registry.update_task(task_id, ...)` 静默失败的情况——当 task_id 只有 session 目录而不在 registry 中时，`update_task` 因 `if task_id not in registry: return` 而静默忽略，但用户仍收到"已终止"的成功消息：

```python
if not task_exists and not session_dir.exists():
    print(f"任务 {args.task_id} 不存在")
    return

if session_dir.exists():
    abort_file = session_dir / "abort"
    abort_file.touch()

registry.update_task(args.task_id, status="aborted")  # 可能静默失败
print(f"已终止任务 [{args.task_id}]")
```

此行为（只有 session 目录、不在 registry 中的孤儿任务）可能发生在 registry.json 损坏或手动创建 session 目录的场景。abort 信号文件已写入是有效的，所以实际 abort 会生效；但 registry 未更新是已知不一致。

**修复建议**: 可在 registry 更新失败时加日志，或在 abort 成功后调用 `registry.rebuild()` 重建；至少加注释说明此设计意图：

```python
# 注意：若任务不在 registry 但有 session 目录（孤儿任务），
# update_task 会静默忽略，但 abort 信号文件已写入，Worker 会响应
registry.update_task(args.task_id, status="aborted")
print(f"已终止任务 [{args.task_id}]")
```

---

#### [CR-008] `_launch_worker` 文件句柄在异常时可能泄漏

**文件**: `src/maestro/telegram_bot.py:834-841`

**问题描述**:
```python
with open(log_dir / "worker.log", "a") as f:
    subprocess.Popen(
        cmd,
        stdout=f,
        stderr=f,
        start_new_session=True,
        cwd=working_dir,
    )
```

使用 `with` 上下文管理器，`f` 会在 `with` 块结束时关闭，但此时 `subprocess.Popen` 已将 `f` 作为子进程的 stdout/stderr。子进程仍在运行，而父进程端已关闭文件描述符。

在 Linux/macOS 上，子进程持有 fd 的副本，父进程关闭自己的 fd 不影响子进程写入，所以**实际上不会有数据丢失**。但这是一个令人困惑的写法，也与 `cli.py:_launch_worker_background`（同样结构）一致，不算严重问题。

注意：`cli.py` 版本的 `_launch_worker_background`（第 546-553 行）写法相同，两者保持了一致性，此低级问题不影响功能。

---

#### [CR-009] 测试辅助函数 `_create_daemon` 缺少 `_default_working_dir` 字段

**文件**: `tests/test_focus_mode.py:551-563`

**问题描述**:
```python
def _create_daemon(config):
    daemon = TelegramDaemon.__new__(TelegramDaemon)
    daemon.config = config
    daemon._config_path = "config.yaml"
    daemon.registry = MagicMock()
    daemon._last_states = {}
    daemon._message_task_map = {}
    daemon._free_chat_history = []
    daemon._focused_task_id = None
    daemon._turn_file_positions = {}
    # 缺少: daemon._default_working_dir = None
    return daemon
```

本次改动新增了 `_default_working_dir` 字段，但测试的辅助构造函数未同步添加。如果测试用例未来访问该字段（如测试 `_on_run` 命令），会抛出 `AttributeError`。当前测试恰好未触发该路径，但这是潜在的测试脆弱点。

**修复建议**: 在 `_create_daemon` 中添加：
```python
daemon._default_working_dir = None
```

---

### Info

#### [CR-010] turns.jsonl 格式错误行静默跳过，无监控日志

**文件**: `src/maestro/telegram_bot.py:711-714`

**问题描述**:
```python
try:
    event = json.loads(line)
except json.JSONDecodeError:
    continue
```

当 turns.jsonl 中出现 JSON 格式错误（如 Orchestrator 崩溃导致写了一半的行），会静默跳过。对于生产环境，建议至少记录 warning 日志，便于排查问题：

```python
except json.JSONDecodeError as e:
    logger.warning(f"turns.jsonl 解析失败 [{task_id}]: {e} — 行内容: {line[:50]}")
    continue
```

---

#### [CR-011] `_monitor_loop` 进程健康检查未处理 `OSError`（非 `ProcessLookupError`）

**文件**: `src/maestro/telegram_bot.py:600-614`

**问题描述**:
```python
try:
    os.kill(pid, 0)
except ProcessLookupError:
    ...  # 进程不存在
```

`os.kill(pid, 0)` 在以下情况会抛出不同异常：
- `ProcessLookupError`（ESRCH）：进程不存在 — 已处理
- `PermissionError`（EPERM）：进程存在但无权限发送信号 — 未处理，会冒泡到 job_queue 的异常处理

在 Daemon 以非 root 运行但 Worker 以其他用户运行的场景（不常见但可能）下，`PermissionError` 会导致 `_monitor_loop` 的整个调用失败，所有任务的状态监控暂停一次。建议捕获 `PermissionError`：

```python
try:
    os.kill(pid, 0)
except ProcessLookupError:
    # 进程不存在，标记为失败
    ...
except PermissionError:
    # 进程存在但无权限检查，假设进程仍在运行
    pass
```

---

## 3. 需求覆盖核对（对照 01-requirements.md）

| 需求 | 状态 | 说明 |
|------|------|------|
| FR-1: 任务关注模式，一次只能关注一个 | 已实现 | `_focused_task_id` 单值字段 |
| FR-1: /run 自动成为关注任务 | 已实现 | `_on_run` 末尾设置 `_focused_task_id` |
| FR-1: 非关注任务只在状态变更时推送 | 已实现 | `_monitor_loop` 状态变更检测路径 |
| FR-1: 关注任务结束后自动取消关注 | 已实现 | `_push_status_change` 末尾 |
| FR-2: 每轮推送 Turn 序号/进度/输出/决策/耗时 | 已实现 | `_push_focused_turns` + `_format_turn_message` |
| FR-2: vibing 判断（<20 字符） | 已实现 | `telegram_bot.py:741` |
| FR-3: /focus 查看当前关注 | 已实现 | `_on_focus` 无参数分支 |
| FR-3: /focus <task_id> 切换 | 已实现 | `_on_focus` task_id 分支 |
| FR-3: /focus off 取消 | 已实现 | `_on_focus` off/none 分支 |
| FR-4: 通知通道统一，Orchestrator 不再直推 | 已实现 | `orchestrator.py` 中无 `_telegram_push` 方法 |
| NFR-1: 快速轮次不丢 | 已实现（部分） | 存在最后一轮竞态，见 CR-004 |
| NFR-2: Telegram 消息 ≤4096 字符 | 已实现 | `_format_turn_message` 末尾截断 |
| NFR-3: 向后兼容 `/status /chat /ask /abort` | 已实现 | 保留原有参数形式，省略 id 为新增行为 |
| NFR-4: focus 状态无需持久化 | 已实现 | 存内存 |

---

## 4. 设计一致性核对（对照 02-design.md）

| 设计点 | 状态 | 说明 |
|--------|------|------|
| `_focused_task_id` / `_turn_file_positions` 字段 | 一致 | |
| `_init_turn_positions()` 启动时跳过历史 | 一致 | |
| `_on_focus` 命令实现 | 一致 | |
| `_push_focused_turns()` 增量读取逻辑 | 一致 | |
| `_format_turn_message()` 格式 | 一致 | |
| `_seek_turns_to_end()` 切换关注跳过历史 | 一致 | |
| `_push_status_change` 关注任务结束取消 | 一致 | |
| `/run` 自动关注并初始化偏移量为 0 | 一致 | |
| `turns.jsonl` 写入（orchestrator.py） | 一致 | |
| `config.py` 删除 `push_every_turn` | 一致 | |
| `config.example.yaml` 移除 `push_every_turn` | 一致 | |
| **`_on_run` 新格式（/run <需求>，需先 /cd）** | **偏差** | 设计文档 US-1 仍显示 `/run /home/user/project 修复登录 Bug`（带目录），实现已改为 /cd + /run 分离模式。这是设计演进而非错误，建议更新设计文档 |
| **`_on_chat` 支持省略 task_id** | **未实现** | 设计未要求，但与同批改动中其他命令的一致性不符，见 CR-005 |

---

## 5. 异常场景覆盖核对（对照 03-tests.md）

| 测试场景 | 代码中是否有处理逻辑 | 说明 |
|----------|----------------------|------|
| turns.jsonl 写入格式正确（2 轮） | 已处理 | `_write_turn_event` |
| output_summary 截取最后 2000 字符 | 已处理 | `orchestrator.py:536` |
| instruction 截取前 200 字符 | 已处理 | `orchestrator.py:537` |
| 空输出不报错 | 已处理 | `if result.output else ""` |
| 中文内容不被 escape | 已处理 | `ensure_ascii=False` |
| Telegram 消息不超过 4096 字符 | 已处理 | `telegram_bot.py:762-763` |
| vibing on empty / short output | 已处理 | `telegram_bot.py:741` |
| 增量读取不重复旧行 | 已处理 | 字节偏移量机制 |
| Daemon 重启不重放历史 | 已处理 | `_init_turn_positions()` |
| focus 切换跳过历史 | 已处理 | `_seek_turns_to_end()` |
| push_every_turn 字段删除 | 已处理 | `config.py` |
| Orchestrator 无直推方法 | 已处理 | 确认已删除 |
| **最后一轮竞态（任务完成前 turns 未写入）** | 部分处理 | `_monitor_loop` 顺序调整有改善，但不完全（CR-004） |

---

## 6. 亮点

1. **`_monitor_loop` 顺序调整设计合理**：将 `_push_focused_turns()` 移到状态变更检测之前，减少了最后几轮丢失的概率，思路正确。

2. **`_launch_worker` 简化合理**：Daemon 以 nohup 模式后台运行，没有 TTY，Zellij 无法启动，移除 Zellij 分支是正确的工程判断，代码注释也清晰说明了原因（`telegram_bot.py:817-821`）。

3. **`_on_abort` 双重检查逻辑**：同时检查 registry 和 session 目录，比原来只检查 registry 更健壮，能处理"孤儿任务"场景。

4. **`_on_cd` 路径展开规范**：使用 `realpath` + `expanduser` + `expandvars` 组合（虽然 `expandvars` 有风险，见 CR-002），整体思路是把用户传入的路径标准化后存储，避免后续 `/run` 的相对路径问题。

5. **`/ask` 省略 task_id 的格式判断**：通过 8 位十六进制格式识别 task_id 的思路直观（虽然存在 CR-001 描述的边界问题），是一个实用的启发式方案。

---

## 下游摘要

### 整体评估
REQUEST CHANGES

### 未修复问题
#### Critical
无

#### High
- [CR-001] `_on_ask` task_id 识别逻辑有假阴性漏洞（`src/maestro/telegram_bot.py:301`）
- [CR-002] `/cd` 命令 `expandvars` 展开敏感环境变量，存在信息探测风险（`src/maestro/telegram_bot.py:457`）

#### Medium
- [CR-003] `_default_working_dir` 重启丢失未在帮助/提示文本中说明（`telegram_bot.py:185-187`）
- [CR-004] `_monitor_loop` 顺序改动后仍存在最后一轮竞态，`_push_status_change` 应在清除 focus 前再调用一次 `_push_focused_turns`（`telegram_bot.py:667-671`）
- [CR-005] `_on_chat` 未适配省略 task_id 使用 focused_task_id，与同批改动的其他命令不一致（`telegram_bot.py:331`）
- [CR-006] `/start` 帮助文本中 `/status /ask /abort /report` 说明未更新为可选 id（`telegram_bot.py:155-162`）

### 修复建议（优先级排序）

1. **[CR-001] 最高优先级**：`_on_ask` 的 task_id 识别改用 session 目录存在性校验，避免假阳性误路由和假阴性漏识别。
2. **[CR-002] 高优先级**：`_on_cd` 移除 `expandvars`，仅保留 `expanduser`，防止环境变量探测。
3. **[CR-004] 中优先级**：`_push_status_change` 在清除 `_focused_task_id` 之前额外调用 `_push_focused_turns(context)`，减少最后一轮丢失。
4. **[CR-005] 中优先级**：`_on_chat` 补充省略 task_id 支持，与其他命令保持一致。
5. **[CR-006] 中优先级**：更新帮助文本，`<id>` 改为 `[id]` 并注明"省略 id 用关注任务"。
6. **[CR-009] 低优先级**：测试辅助函数 `_create_daemon` 补充 `_default_working_dir = None` 字段。
