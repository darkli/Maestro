# 代码审查报告：Focus 自动恢复功能

- 审查日期：2026-02-26
- 审查范围：`src/maestro/telegram_bot.py`（新增自动恢复逻辑）、`src/maestro/orchestrator.py`（resume 方法增强）
- 参考文档：`01-requirements.md`、`02-design.md`

---

## 审查摘要表

| 级别     | 数量 | 说明 |
|----------|------|------|
| Critical | 0    | 无   |
| High     | 3    | 防重入泄露、进程检测漏洞、状态不一致 |
| Medium   | 5    | 设计偏差、边界条件、错误消息遗漏、资源泄露、注释缺失 |
| Low      | 4    | 代码风格、重复代码、响应体验、文档提示偏差 |
| Info     | 2    | 正向评价 |

---

## 整体评估

**REQUEST CHANGES**

核心自动恢复流程逻辑清晰，与设计文档高度吻合，orchestrator.py 的修改简洁正确。
但存在 3 个 High 问题需要修复：`_resuming_tasks` 永不清理的泄露路径、进程 PID 为 0 时的错误判断，以及 `/ask` 对 `ABORTED` 状态的错误恢复触发。

---

## 一、需求覆盖核对（对照 01-requirements.md）

| 需求编号 | 需求描述 | 实现状态 | 说明 |
|----------|----------|----------|------|
| FR-1 | 向死任务发消息时自动恢复 | 已实现 | `/ask`、直接回复、focus 消息三路均已集成 |
| FR-2 | `/focus` 死任务时提示可恢复 | 已实现 | `_on_focus` 已根据状态生成 hint |
| FR-3 | 恢复时注入用户消息到 Manager 上下文 | 已实现 | `orchestrator.resume()` 已读取 inbox 并构建增强 notice |
| FR-4 | 进程存活检测 | 已实现 | `_is_worker_alive()` 使用 `os.kill(pid, 0)` |
| NFR-1 | 自动恢复只触发一次 | **部分实现** | `_resuming_tasks` 有永不清理的泄露场景（见 CR-001） |
| NFR-2 | 恢复后 focus 状态保持 | 已实现 | 消息路由后未清除 `_focused_task_id` |
| NFR-3 | 不影响运行中任务的 `/ask` | **部分实现** | ABORTED 任务也会被 `_auto_resume_if_needed` 尝试检查（见 CR-003） |

---

## 二、设计一致性核对（对照 02-design.md）

| 设计点 | 设计要求 | 实现情况 | 差异 |
|--------|----------|----------|------|
| 2.1 `_auto_resume_if_needed` 签名 | 设计中防重入返回 `False` 而不提示 | 实现中返回 `True` 并提示"正在恢复中" | 行为更优，但与设计不符（见 CR-006） |
| 2.2 `_resuming_tasks` 清理时机 | `_monitor_loop` 检测到 `executing` 时清理 | 已实现（第 658–659 行） | 一致 |
| 2.3 `_on_ask` 集成 | 写 inbox 后调用 `_auto_resume_if_needed` | 已实现 | 一致 |
| 2.4 `_on_message` 集成 | 直接回复 + focus 消息两路 | 已实现 | 一致 |
| 2.5 `_on_focus` 提示 | waiting_user + 进程死时提示恢复 | 已实现，但 `_is_worker_alive` 逻辑更健壮 | 一致（正向差异） |
| 2.6 orchestrator resume notice | 读取 inbox 并区分有/无回复两种 notice | 已实现 | 一致 |
| 2.7 设计建议 import `_launch_resume_background` | 设计建议从 `cli.py` import | 实现中在 `telegram_bot.py` 内重新定义了 `_launch_resume()` 方法 | **偏差（见 CR-007）** |

---

## 三、异常场景覆盖核对（对照 02-design.md §5 边界情况）

| 场景 | 设计处理 | 代码是否处理 | 说明 |
|------|----------|-------------|------|
| 5.1 连续发多条消息 | `_resuming_tasks` 防重入 | 是，但有泄露 | 见 CR-001 |
| 5.2 ABORTED 不恢复 | `status not in ("failed", "waiting_user")` | **是** | 但 `/ask` 路径在 inbox 写入后才检查，已写消息不可撤回 |
| 5.3 COMPLETED 不恢复 | 同上 | 是 | 正确 |
| 5.4 inbox 不被 monitor_loop 消费 | Daemon 只读 turns.jsonl | 是 | 正确 |
| 5.5 Daemon 重启后 `_resuming_tasks` 丢失 | 可接受 | — | 设计已知行为 |
| 5.6 focus 后消息 vs 自由聊天区分 | 只在 failed/waiting_user 时视为任务回复 | 是 | 正确 |
| 额外场景：checkpoint 不存在时恢复 | 未在设计中明确 | 是，有处理（第 914–925 行）| 正确，实现优于设计 |
| 额外场景：pid=None 时检测 | 未在设计中明确 | **存在逻辑问题**（见 CR-002）| |
| 额外场景：resume 进程启动失败后重试 | 未明确 | `_resuming_tasks.discard` 在失败时清理 | 正确，允许重试 |

---

## 四、详细发现（按级别分组）

### HIGH

---

#### [CR-001] `_resuming_tasks` 在 `_monitor_loop` 中永不清理的泄露路径

- **文件**：`src/maestro/telegram_bot.py`，第 657–659 行
- **问题描述**：

  `_monitor_loop` 仅在 `current_status == "executing"` 时才清理 `_resuming_tasks`。但如果 resume 进程启动失败（进程 Popen 成功但 `maestro resume` 立即崩溃，状态从未变为 `executing`），或 resume 后任务直接进入 `completed`/`failed`（跳过 `executing` 状态更新），则 `task_id` 永远留在 `_resuming_tasks` 中，导致该任务后续所有恢复请求均被阻断，用户无法再触发恢复。

  ```python
  # 当前代码（第 658-659 行）
  if current_status == "executing" and task_id in self._resuming_tasks:
      self._resuming_tasks.discard(task_id)
  ```

- **修复建议**：扩大清理条件，涵盖所有终态：

  ```python
  # 修复：executing 进入清理，或任务已到终态时也清理
  if task_id in self._resuming_tasks:
      if current_status in ("executing", "completed", "failed", "aborted"):
          self._resuming_tasks.discard(task_id)
  ```

  同时建议对 `_resuming_tasks` 中的条目添加时间戳，超过 5 分钟未清理时强制清除，作为兜底保障。

---

#### [CR-002] `_is_worker_alive` 对 `pid=0` 的错误判断

- **文件**：`src/maestro/telegram_bot.py`，第 870–883 行
- **问题描述**：

  `os.kill(0, 0)` 在 POSIX 系统中是合法的，它向进程组内所有进程发信号，始终成功（不会抛出 `ProcessLookupError`）。因此当 `state.json` 中 `worker_pid` 为 `0` 时（理论上不应发生但可能因 JSON 解析异常或手动编辑产生），函数会错误返回 `True`，认为进程存活，阻止自动恢复。

  ```python
  def _is_worker_alive(self, state: Optional[dict]) -> bool:
      pid = state.get("worker_pid")
      if not pid:          # <-- pid=0 时走这里返回 False，实际上没问题
          return False
      try:
          os.kill(pid, 0)  # pid=0 时不抛出异常
          return True      # 错误地返回 True
  ```

  注意：`if not pid` 在 `pid=0` 时为 `True`，实际返回 `False`，这部分是正确的。但问题在于 `pid` 为负数（如 `-1`）时，`os.kill(-1, 0)` 会向所有进程发信号，始终成功，返回 `True` —— 这是真正的漏洞。负数 PID 在异常场景下可能出现。

- **修复建议**：

  ```python
  def _is_worker_alive(self, state: Optional[dict]) -> bool:
      """检测任务的 worker 进程是否存活"""
      if not state:
          return False
      pid = state.get("worker_pid")
      # pid 必须为正整数
      if not isinstance(pid, int) or pid <= 0:
          return False
      try:
          os.kill(pid, 0)
          return True
      except ProcessLookupError:
          return False
      except PermissionError:
          return True  # 进程存在但无权限，视为存活
  ```

---

#### [CR-003] `_on_ask` 对 `ABORTED` 状态任务先写 inbox 后调用自动恢复检查，顺序有逻辑漏洞

- **文件**：`src/maestro/telegram_bot.py`，第 322–329 行
- **问题描述**：

  `_on_ask` 的当前逻辑：先无条件写入 `inbox.txt`，再调用 `_auto_resume_if_needed`。
  `_auto_resume_if_needed` 内部检查 `status not in ("failed", "waiting_user")` 时返回 `False`，对 `ABORTED` 不触发恢复 —— 这部分是正确的。

  但问题在于：对 `ABORTED` 状态的任务，消息已经写入了 `inbox.txt`。如果用户之后手动执行 `maestro resume`，inbox 中会包含这条"旧消息"，可能导致意外行为。更重要的是，当前 `_on_ask` 对 `ABORTED` 任务既不恢复也不提示用户"任务已被终止，消息无法送达"，而是沉默地什么都不说（因为 `resumed` 为 `False`，代码走到第 327–329 行打印"已向任务发送反馈"）。

  ```python
  _write_inbox(str(inbox_path), "telegram", message)  # 先写入

  resumed = await self._auto_resume_if_needed(task_id, update)
  if not resumed:
      await update.message.reply_text(          # ABORTED 也走这里，给用户错误反馈
          f"已向任务 [{task_id}] 发送反馈: {message}"
      )
  ```

  用户以为消息送达，但实际上 `ABORTED` 状态下没有 Orchestrator 消费该消息。

- **修复建议**：在写入 inbox 前先读取状态，对终态提前拦截：

  ```python
  async def _on_ask(self, update, context):
      ...
      # 读取当前状态，终态提前拦截
      state = self._read_state(task_id)
      if state:
          status = state.get("status", "")
          if status == "aborted":
              await update.message.reply_text(
                  f"任务 [{task_id}] 已被终止，消息无法送达。\n"
                  f"如需重启，请使用 /run 发起新任务。"
              )
              return
          if status == "completed":
              await update.message.reply_text(
                  f"任务 [{task_id}] 已完成，消息无法送达。"
              )
              return

      _write_inbox(str(inbox_path), "telegram", message)
      resumed = await self._auto_resume_if_needed(task_id, update)
      if not resumed:
          await update.message.reply_text(
              f"已向任务 [{task_id}] 发送反馈: {message}"
          )
  ```

---

### MEDIUM

---

#### [CR-004] `_on_message` 中 focus 消息路径对 `waiting_user` + 进程存活时无响应

- **文件**：`src/maestro/telegram_bot.py`，第 579–594 行
- **问题描述**：

  在 `_on_message` 中，当 `focused_task` 状态为 `waiting_user` 且进程**存活**时，代码没有特殊分支处理 —— 既不走自动恢复，也没有回退到 inbox 路由，而是直接落入"其他所有消息 → 自由聊天"分支。

  这意味着：用户正在 focus 一个 `waiting_user` 状态的任务，直接发消息（不用 `/ask`），消息会被当成自由聊天处理，而不是送达 Orchestrator。

  ```python
  if self._focused_task_id:
      task_id = self._focused_task_id
      state = self._read_state(task_id)
      status = state.get("status", "") if state else ""
      if status in ("failed", "waiting_user"):
          if not self._is_worker_alive(state):   # 进程死才进这个分支
              ...
              return
      # 进程存活的 waiting_user → 落入自由聊天 ← 逻辑问题
  ```

  根据 FR-1 和设计文档 §2.4：`waiting_user` + 进程存活时，普通消息**应当**路由到 inbox（不触发 resume）。

- **修复建议**：

  ```python
  if self._focused_task_id:
      task_id = self._focused_task_id
      state = self._read_state(task_id)
      status = state.get("status", "") if state else ""
      if status in ("failed", "waiting_user"):
          inbox_path = (
              Path("~/.maestro/sessions").expanduser()
              / task_id / "inbox.txt"
          )
          if inbox_path.parent.exists():
              _write_inbox(str(inbox_path), "telegram-focus", update.message.text)
              if self._is_worker_alive(state):
                  # 进程存活，直接路由到 inbox，无需恢复
                  await update.message.reply_text(f"已转发到任务 [{task_id}]")
              else:
                  # 进程已死，自动恢复
                  await self._auto_resume_if_needed(task_id, update)
              return
  ```

---

#### [CR-005] `_monitor_loop` 中 Worker 崩溃检测的 `ProcessLookupError` 捕获不完整

- **文件**：`src/maestro/telegram_bot.py`，第 662–684 行
- **问题描述**：

  `_monitor_loop` 中对 `executing` 状态任务的 PID 检测只捕获了 `ProcessLookupError`，没有捕获 `PermissionError`。如果 Daemon 运行在与 Worker 不同的用户下（如 root 启动 Daemon，普通用户启动 Worker），`os.kill(pid, 0)` 会抛出 `PermissionError` 而不是 `ProcessLookupError`，此时代码会抛出未捕获异常，`_monitor_loop` 会崩溃，停止所有状态监控。

  相比之下，`_is_worker_alive()` 方法（第 878–883 行）正确地同时捕获了两种异常，但 `_monitor_loop` 中却没有复用它，而是重新实现了检测逻辑。

  ```python
  # _monitor_loop 中（第 665-667 行）—— 不完整
  try:
      os.kill(pid, 0)
  except ProcessLookupError:   # 缺少 PermissionError 处理
      ...
  ```

- **修复建议**：直接复用 `_is_worker_alive()` 方法：

  ```python
  if current_status == "executing":
      if not self._is_worker_alive(state):
          # Worker 进程已死，设为 failed
          state["status"] = "failed"
          ...
  ```

---

#### [CR-006] `_auto_resume_if_needed` 防重入行为与设计文档不一致

- **文件**：`src/maestro/telegram_bot.py`，第 906–909 行
- **问题描述**：

  设计文档 §2.1 中防重入的行为是返回 `False`（静默忽略）。实现中改为返回 `True` 并向用户发送"正在恢复中，请稍候"。

  这个改动方向是好的，但带来了一个副作用：在 `_on_message` 的 focus 消息路径中（第 593 行），`_auto_resume_if_needed` 返回 `True` 后直接 `return`，不再执行后续逻辑。但由于 `_on_message` 中调用方没有处理返回值（与 `_on_ask` 不同），这个返回值被丢弃了，行为上没问题，但语义上容易混淆。

  另外，防重入时向用户发送提示是好的，但消息写入 inbox 的操作已经在调用 `_auto_resume_if_needed` 之前完成，用户实际上消息已到达，只是进程还在启动中，提示语应更准确。

  ```python
  # 当前提示（第 907-909 行）
  await update.message.reply_text(
      f"任务 [{task_id}] 正在恢复中，请稍候..."
  )
  ```

- **修复建议**：改进提示语，明确消息已送达：

  ```python
  await update.message.reply_text(
      f"任务 [{task_id}] 正在恢复中，你的消息已排队，请稍候..."
  )
  ```

---

#### [CR-007] `telegram_bot.py` 的 `_launch_resume()` 与 `cli.py` 中的 `_launch_resume_background()` 重复实现

- **文件**：`src/maestro/telegram_bot.py`，第 943–963 行 / `src/maestro/cli.py`，第 556–576 行
- **问题描述**：

  设计文档 §2.7 明确建议直接 import `cli.py` 中的 `_launch_resume_background()` 函数。实现中改为在 `telegram_bot.py` 内重写了一个功能几乎相同的 `_launch_resume()` 方法。两者对比：

  ```python
  # cli.py: _launch_resume_background（第 556-576 行）
  cmd = [sys.executable, "-m", "maestro.cli", "resume", task_id, "-f", "-c", config_path]
  log_dir = Path(config.logging.dir).expanduser() / "tasks" / task_id
  ...

  # telegram_bot.py: _launch_resume（第 943-963 行）
  cmd = [sys.executable, "-m", "maestro.cli", "resume", task_id, "-f", "-c", self._config_path]
  log_dir = Path(self.config.logging.dir).expanduser() / "tasks" / task_id
  ...
  ```

  两者实质相同，但独立维护意味着将来修改一处容易忘记另一处（如增加环境变量、调整日志路径等）。

- **修复建议**：

  ```python
  # telegram_bot.py 顶部
  from maestro.cli import _launch_resume_background

  # 删除 _launch_resume() 方法，在 _auto_resume_if_needed 中改为
  _launch_resume_background(
      self.config, task_id, working_dir, self._config_path
  )
  ```

---

#### [CR-008] `orchestrator.py` resume 方法中步骤编号注释错误

- **文件**：`src/maestro/orchestrator.py`，第 250 行
- **问题描述**：

  `resume()` 方法的步骤注释出现编号跳跃。步骤 5（读取 inbox）和步骤 6（构建 resume notice）之后，继续主循环的注释写的是"# 6. 继续主循环"，与上面的步骤 6 重复，应为步骤 7。

  ```python
  # 5. 检查是否有用户待处理消息
  ...
  # 6. 让 Manager 基于恢复上下文决定下一步
  ...
  # 6. 继续主循环   <-- 编号重复，应为 7
  self._main_loop(...)
  ```

- **修复建议**：将最后一个步骤注释改为 `# 7. 继续主循环`。

---

### LOW

---

#### [CR-009] `_on_focus` 中 `waiting_user` + 进程存活时提示语与帮助文档不一致

- **文件**：`src/maestro/telegram_bot.py`，第 539–542 行
- **问题描述**：

  当前提示：
  ```
  "直接发消息或 /ask 即可回复"
  ```

  而 `_on_start` 的帮助文档提示的是 `/ask [id] <消息>`。提示语中的"直接发消息"只在 focus 模式下有效，但提示没有说明前提。对于不了解 focus 模式的用户可能有歧义。

- **修复建议**：

  ```python
  hint = "\n状态: 等待你的回复\n直接发消息（已 focus）或 /ask 即可回复"
  ```

---

#### [CR-010] `_on_message` 中 focus 路径写入 inbox 后无"消息已送达"确认

- **文件**：`src/maestro/telegram_bot.py`，第 592–594 行
- **问题描述**：

  在 `_on_message` 的 focus 死任务路径中，调用 `_auto_resume_if_needed()` 后直接 `return`，若恢复成功则 `_auto_resume_if_needed` 内部已发送确认，但若 `_auto_resume_if_needed` 返回 `False`（如 checkpoint 不存在），则用户不会收到任何提示（消息写入了 inbox 但没有恢复，用户不知道发生了什么）。

  ```python
  _write_inbox(str(inbox_path), "telegram-focus", update.message.text)
  await self._auto_resume_if_needed(task_id, update)  # False 时无提示
  return
  ```

- **修复建议**：

  ```python
  _write_inbox(str(inbox_path), "telegram-focus", update.message.text)
  resumed = await self._auto_resume_if_needed(task_id, update)
  if not resumed:
      await update.message.reply_text(
          f"消息已记录，但任务 [{task_id}] 无法自动恢复（缺少 checkpoint）。\n"
          f"请手动运行: maestro resume {task_id}"
      )
  return
  ```

---

#### [CR-011] `_on_focus` 中 `ABORTED` 状态的恢复提示使用了未实现的命令

- **文件**：`src/maestro/telegram_bot.py`，第 535 行
- **问题描述**：

  当 focus 一个 `ABORTED` 任务时，提示"如需恢复请使用 `maestro resume {task_id}`"。但根据设计文档 §5.2，ABORTED 状态是终态，不允许自动恢复，而且 Telegram Bot 本身没有实现 `/resume` 命令（`_on_start` 帮助文档中也没有列出）。用户看到提示后需要去 SSH 到服务器执行 CLI，这对纯 Telegram 用户不友好，但在当前版本属于合理的设计范围，只需确保提示准确。

  ```python
  hint = f"\n状态: 已终止\n如需恢复请使用 maestro resume {task_id}"
  ```

- **修复建议**：提示更完整，区分 Telegram 用户和 CLI 用户：

  ```python
  hint = f"\n状态: 已终止\n如需重启任务，请在服务器上执行: maestro resume {task_id}"
  ```

---

#### [CR-012] `_launch_resume` 方法未记录日志，恢复失败时调试困难

- **文件**：`src/maestro/telegram_bot.py`，第 943–963 行
- **问题描述**：

  `_launch_resume()` 调用 `subprocess.Popen` 后没有记录任何日志（启动参数、PID 等），仅依赖 worker.log 文件中的输出。当 resume 进程快速失败时，调试较困难。

- **修复建议**：

  ```python
  def _launch_resume(self, task_id: str, working_dir: str):
      """在后台启动 resume 进程"""
      cmd = [...]
      ...
      proc = subprocess.Popen(cmd, stdout=f, stderr=f, ...)
      logger.info(f"自动恢复任务 [{task_id}] 已启动，PID={proc.pid}，日志: {log_dir / 'worker.log'}")
  ```

---

## 五、正向评价

#### [INFO-001] checkpoint 缺失保护逻辑是设计外的改进

`_auto_resume_if_needed` 在调用 `_launch_resume` 前检查 `checkpoint.json` 是否存在（第 914–925 行），而设计文档并未要求此检查。这个改进防止了 resume 进程启动后立即因找不到 checkpoint 而崩溃的情况，实现比设计更健壮。

#### [INFO-002] `_is_worker_alive` 对 `PermissionError` 的处理符合最佳实践

正确将 `PermissionError` 视为"进程存在但无权限检查"，返回 `True` 而非 `False`，避免误判导致对存活进程重复发起 resume。这是正确且安全的处理方式。

---

## 六、修复优先级建议

### 必须修复（High）

1. **CR-001**：`_resuming_tasks` 清理扩展到终态，防止永久性防重入泄露
2. **CR-002**：`_is_worker_alive` 增加 `pid <= 0` 的合法性检查
3. **CR-003**：`_on_ask` 对 ABORTED/COMPLETED 状态提前拦截，避免无效 inbox 写入和错误确认提示

### 应尽快修复（Medium）

4. **CR-004**：`_on_message` focus 路径补充 `waiting_user` + 进程存活时的 inbox 路由
5. **CR-005**：`_monitor_loop` Worker 崩溃检测复用 `_is_worker_alive()`，防止未捕获异常崩溃监控循环
6. **CR-007**：删除重复的 `_launch_resume()` 方法，import 并复用 `cli.py` 中的 `_launch_resume_background()`

### 可选修复（Low）

7. **CR-008**：修正 `orchestrator.py` 步骤注释编号
8. **CR-010**：`_on_message` focus 路径 resume 失败时补充用户提示
9. **CR-012**：`_launch_resume` 增加进程启动日志

---

## 下游摘要

### 整体评估
REQUEST CHANGES

### 未修复问题
#### Critical
无

#### High
- [CR-001] `_resuming_tasks` 在 resume 进程崩溃或直接到终态时永不清理，导致后续恢复请求永久被阻断
- [CR-002] `_is_worker_alive` 未校验 pid 合法性（负数 PID 会导致 `os.kill(-1, 0)` 向所有进程发信号并返回存活）
- [CR-003] `_on_ask` 对 ABORTED/COMPLETED 状态不拦截，先写入 inbox 后告知用户"反馈已发送"，用户得到错误反馈

#### Medium
- [CR-004] focus + `waiting_user` + 进程存活时普通消息错误路由到自由聊天
- [CR-005] `_monitor_loop` Worker 崩溃检测缺少 `PermissionError` 捕获，可导致监控循环崩溃
- [CR-006] 防重入提示语不够准确（minor）
- [CR-007] `_launch_resume()` 与 `cli.py::_launch_resume_background()` 重复实现，维护风险
- [CR-008] orchestrator.py 步骤注释编号重复

### 修复建议
优先处理 CR-001（防重入泄露）和 CR-004（waiting_user + 进程存活时消息被吞），这两个问题会在正常使用场景中出现且没有提示，用户无感知，最难排查。CR-003 虽然行为错误但用户至少收到了回复，优先级稍低。

---

# 补充审查：状态展示改进 + deploy.sh 变更

**审查日期**：2026-02-26
**审查范围**：本次变更涉及 8 个文件，两个功能点的综合审查

## 补充审查摘要表

| 级别     | 数量 | 说明 |
|----------|------|------|
| Critical | 0    | 无   |
| High     | 2    | deploy.sh 残留变量；CLI abort 不同步 state.json |
| Medium   | 5    | updated_at 遗漏；rebuild 不同步；blocked 无提示；focus 终态无提示；monitor 双推竞争 |
| Low      | 3    | 内部 import；reasoning 无截断；测试内联逻辑 |
| Info     | 3    | 向后兼容性确认；枚举设计；序号正确 |

---

### HIGH（补充）

---

#### [CR-S01] deploy.sh：`HAD_ZELLIJ` 变量残留导致 do_clean 逻辑悬空

**文件**：`deploy.sh`，约第 996 行、第 1102 行

**问题描述**：
`do_clean()` 函数中第 996 行仍初始化了 `HAD_ZELLIJ=true`，第 1102 行仍将 `HAD_ZELLIJ` 注入到远端清理脚本中执行。但此次变更已删除了快照写入（第 310 行的 `-echo "HAD_ZELLIJ=..."` 已被移除），也删除了远端 Zellij 清理逻辑。

结果：新部署的 VPS 快照文件不再包含 `HAD_ZELLIJ` 字段，但 clean 时仍会注入 `HAD_ZELLIJ='true'` 到远端 bash 环境。这是一个悬空引用，变量生命周期与实际用途脱钩。

**修复建议**：
```bash
# 第 996 行：删除 HAD_ZELLIJ 初始化
- HAD_NODEJS=true; HAD_CLAUDE=true; HAD_ZELLIJ=true
+ HAD_NODEJS=true; HAD_CLAUDE=true

# 第 1099-1103 行：删除 HAD_ZELLIJ 注入
- HAD_ZELLIJ='${HAD_ZELLIJ}'
```

---

#### [CR-S02] CLI `_handle_abort` 未同步更新 state.json（与 Telegram `_on_abort` 不一致）

**文件**：`src/maestro/cli.py`，第 373-395 行

**问题描述**：
Telegram `_on_abort` 修复了竞争条件（同步写 state.json），但 CLI `_handle_abort` 只创建 abort 信号文件、更新 registry，未同步更新 state.json。如果用户通过 CLI abort，Telegram Daemon 的 monitor 在 worker 处理 abort 信号之前先轮询到 state.json（仍为 executing），就会误判 worker 崩溃并推送错误通知。

**修复建议**：CLI `_handle_abort` 补充 state.json 同步逻辑：
```python
if session_dir.exists():
    abort_file = session_dir / "abort"
    abort_file.touch()
    # 同步更新 state.json 防止 monitor 误判
    state_path = session_dir / "state.json"
    state = read_json_safe(str(state_path))
    if state:
        from datetime import datetime
        from maestro.state import atomic_write_json
        state["status"] = "aborted"
        state["updated_at"] = datetime.now().isoformat()
        atomic_write_json(str(state_path), state)
```

---

### MEDIUM（补充）

---

#### [CR-S03] `_on_abort`（Telegram）直接写 state.json 未更新 `updated_at`

**文件**：`src/maestro/telegram_bot.py`，第 440-445 行

```python
state["status"] = "aborted"
atomic_write_json(str(state_path), state)
# 缺少 state["updated_at"] = datetime.now().isoformat()
```

**修复建议**：补充 `state["updated_at"] = datetime.now().isoformat()`

---

#### [CR-S04] `rebuild()` 方法不同步 `fail_reason` 字段

**文件**：`src/maestro/registry.py`，第 118-143 行

`rebuild()` 重建 registry 时未包含 `fail_reason` 字段，registry 损坏恢复后所有 failed 任务的细分图标和差异化通知会退化。

**修复建议**：在 rebuild 的 entry dict 中添加：
```python
"fail_reason": state.get("fail_reason", ""),
```

---

#### [CR-S05] `_push_status_change` 对 `blocked` 和 `runtime_error` 缺少操作提示

**文件**：`src/maestro/telegram_bot.py`，第 758-785 行

`blocked` 和 `runtime_error` 两种失败原因走 `else` 分支，只显示 `error_message`，无操作建议。

**修复建议**：增加对应分支：
```python
elif fail_reason == "blocked":
    reason_text = f"任务被阻塞: {state.get('error_message', '未知')}\n建议补充所需信息后重新运行"
elif fail_reason == "runtime_error":
    reason_text = f"运行时错误: {state.get('error_message', '未知')}"
```

---

#### [CR-S06] `_on_message` focus 模式下 aborted/completed 任务无明确提示

**文件**：`src/maestro/telegram_bot.py`，第 629 行

focus 任务处于 `aborted` 或 `completed` 时，普通消息静默落入自由聊天，与 `/ask` 的拦截行为不一致。

**修复建议**：增加终态判断，显示提示后再转入自由聊天。

---

#### [CR-S07] `_monitor_loop` worker 崩溃检测与 `_push_status_change` 存在双重推送竞争条件

**文件**：`src/maestro/telegram_bot.py`，第 707-743 行

同一个 monitor 周期中，状态变更检测（第 708 行）和 worker 崩溃检测（第 720 行）读取同一份 state 对象。在特定时序下，可能同时触发 `_push_status_change("executing" → "failed")` 和独立的"💥 Worker 崩溃"通知，用户收到两条消息。

**修复建议**：使用 `worker_just_crashed` 标记跳过当次状态变更推送。

---

### LOW（补充）

---

#### [CR-S08] `_on_abort`（Telegram）内部 import 可移至文件顶部

**文件**：`src/maestro/telegram_bot.py`，第 444 行

`from maestro.state import atomic_write_json` 在函数体内局部导入，应移至文件顶部与 `read_json_safe` 合并。

---

#### [CR-S09] `_write_turn_event` 中 `reasoning` 字段无长度截断

**文件**：`src/maestro/orchestrator.py`，第 562 行

`output_summary` 和 `instruction` 都有截断，但 `reasoning` 没有，可能产生极长的 JSONL 行。

**修复建议**：`"reasoning": parsed.get("reasoning", "")[:500]`

---

#### [CR-S10] 测试文件中部分用例测试的是内联逻辑复制而非真实代码路径

**文件**：`tests/test_focus_mode.py`，`TestOnFocusStatusHint` 和 `TestMonitorWaitingUserWorkerDeath` 类

部分测试在函数体内复制了生产代码的 if/else 逻辑，实质上是在验证测试自身的逻辑而非调用真实方法，测试覆盖价值有限。建议改为直接 mock 并调用真实方法。

---

## 补充审查：向后兼容性确认

旧 state.json 无 `fail_reason` 字段时，所有读取处均使用 `.get("fail_reason", "")` 降级到默认图标/文案，向后兼容处理**正确**。

## 补充审查修复优先级

**Priority 1（建议本轮跟进）**：
- [CR-S01] deploy.sh `HAD_ZELLIJ` 残留清理（1 分钟修复）
- [CR-S02] CLI `_handle_abort` 补充 state.json 同步（5 分钟修复）

**Priority 2（下轮迭代）**：
- [CR-S04] `rebuild()` 补充 `fail_reason`
- [CR-S06] focus 终态无提示
- [CR-S07] monitor 双推竞争条件

**Priority 3（代码健康）**：
- [CR-S03] 补充 `updated_at`
- [CR-S08] 内部 import 移至顶部
- [CR-S09] reasoning 截断
- [CR-S10] 测试内联逻辑问题
