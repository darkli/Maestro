"""
调度核心模块（Orchestrator）

单任务调度核心，集成：
  - 主循环：编码工具执行 → Manager 决策 → 路由 action
  - inbox 路由：用户反馈交给 Manager 决策（而非直接拼到编码工具指令）
  - abort 检测：信号文件触发优雅停止
  - 状态更新：state.json 管理（含 worker_pid）
  - checkpoint：保存/恢复崩溃点
  - 通知：日志 + Telegram 推送（内联实现，不抽象为独立模块）
  - 报告：任务完成后生成 report.md
"""

import os
import json
import time
import uuid
import fcntl
import logging
import threading
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

from maestro.config import AppConfig, load_config
from maestro.state import (
    TaskStatus, FailReason, CircuitBreaker, atomic_write_json, read_json_safe,
    BREAKER_BUDGET_PREFIX,
)
from maestro.context import ContextManager
from maestro.tool_runner import (
    ToolRunner, ToolEvent, tool_event_to_dict,
    EVENT_MANAGER_DECIDING, EVENT_MANAGER_DECIDED,
)
from maestro.manager_agent import ManagerAgent

logger = logging.getLogger(__name__)


# ============================================================
# inbox 工具函数（内联，不抽象为独立模块）
# ============================================================

def _write_inbox(inbox_path: str, source: str, message: str):
    """线程/进程安全地写入 inbox"""
    timestamp = datetime.now().isoformat()
    line = f"{timestamp}|{source}|{message}\n"
    with open(inbox_path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f, fcntl.LOCK_UN)


def _read_and_clear_inbox(inbox_path: str) -> list[str]:
    """读取并清空 inbox，返回消息列表"""
    try:
        with open(inbox_path, "r+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            messages = f.readlines()
            f.truncate(0)
            f.seek(0)
            fcntl.flock(f, fcntl.LOCK_UN)
        return [m.strip() for m in messages if m.strip()]
    except FileNotFoundError:
        return []


def _parse_inbox_message(raw: str) -> str:
    """从 inbox 消息行中提取消息内容"""
    parts = raw.split("|", 2)
    if len(parts) >= 3:
        return parts[2]
    return raw


# ============================================================
# 日志初始化
# ============================================================

def setup_logging(config: AppConfig, task_id: str = ""):
    """初始化日志配置"""
    log_dir = Path(config.logging.dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)

    # 如果有任务 ID，创建任务专属日志目录
    if task_id:
        task_log_dir = log_dir / "tasks" / task_id
        task_log_dir.mkdir(parents=True, exist_ok=True)
        log_file = task_log_dir / "orchestrator.log"
    else:
        log_file = log_dir / "maestro.log"

    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_file, encoding="utf-8"),
        ]
    )


# ============================================================
# Orchestrator
# ============================================================

class Orchestrator:
    """
    任务调度核心

    流程：
    1. 初始化状态 + 组件
    2. Manager 生成第一条指令
    3. 主循环：检查 abort → 执行编码工具 → 熔断检查 → 读 inbox →
       Manager 决策（含用户反馈）→ 路由 action → 保存 checkpoint
    4. 检测到 DONE/BLOCKED/ASK_USER/熔断/超轮次 时结束
    """

    def __init__(self, config: AppConfig, task_id: str = ""):
        self.config = config
        self.task_id = task_id or str(uuid.uuid4())[:8]
        self.session_dir = Path(f"~/.maestro/sessions/{self.task_id}").expanduser()
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # 核心组件
        working_dir = os.getcwd()
        self.runner = ToolRunner(config.coding_tool, working_dir)
        self.context_mgr = ContextManager(config.context)
        self.manager = ManagerAgent(config.manager, context_mgr=self.context_mgr)
        self.breaker = CircuitBreaker.from_config(
            config.safety,
            max_turns=config.manager.max_turns,
            max_budget_usd=config.manager.max_budget_usd,
        )

        # 文件路径
        self.state_path = str(self.session_dir / "state.json")
        self.checkpoint_path = str(self.session_dir / "checkpoint.json")
        self.inbox_path = str(self.session_dir / "inbox.txt")
        self.report_path = str(self.session_dir / "report.md")
        Path(self.inbox_path).touch()

        # 运行时状态
        self._last_instruction: str = ""
        self._requirement: str = ""
        self._current_turn: int = 0   # 当前轮次，供 _on_tool_event 回调使用

    def run(self, requirement: str):
        """执行任务的完整流程"""
        self._requirement = requirement
        logger.info(f"开始任务 [{self.task_id}]: {requirement[:80]}")

        # 1. 初始化状态
        self._update_state(
            TaskStatus.EXECUTING,
            requirement=requirement,
            worker_pid=os.getpid(),
        )

        try:
            # 3. Manager 初始化
            self.manager.start_task(requirement)
            self._log_event(f"需求: {requirement}")
            self._log_event("Manager 正在分析需求，生成第一条指令...")

            first_decision = self.manager.decide("")
            first_instruction = first_decision.get("instruction", "")
            if not first_instruction:
                # 如果 Manager 首轮返回非 execute action
                self._handle_non_execute(first_decision, 0)
                return

            self._log_event(f"首条指令: {first_instruction[:100]}")

            # 4. 主循环
            self._main_loop(start_turn=1, first_instruction=first_instruction)

        except KeyboardInterrupt:
            logger.info("用户中断")
            self._update_state(TaskStatus.ABORTED)
        except Exception as e:
            logger.error(f"运行出错: {e}", exc_info=True)
            self._update_state(TaskStatus.FAILED, error_message=str(e),
                               fail_reason=FailReason.RUNTIME_ERROR)
        finally:
            self._print_summary()

    def resume(self):
        """恢复崩溃的任务"""
        checkpoint = read_json_safe(self.checkpoint_path)
        if not checkpoint:
            logger.error(f"找不到 checkpoint: {self.checkpoint_path}")
            return

        state = read_json_safe(self.state_path)
        if not state:
            logger.error(f"找不到 state: {self.state_path}")
            return

        self._requirement = state.get("requirement", "")
        resume_turn = checkpoint.get("current_turn", 0)
        last_instruction = checkpoint.get("last_instruction", "未知")
        logger.info(f"恢复任务 [{self.task_id}] 从第 {resume_turn} 轮")

        try:
            # 1. 恢复 Runner 会话
            tool_session_id = checkpoint.get("tool_session_id", "")
            if tool_session_id:
                self.runner.resume_session(tool_session_id)

            # 2. 恢复 Manager 对话历史和累计费用
            self.manager.conversation_history = checkpoint.get(
                "manager_conversation_history", []
            )
            self.manager._total_cost = checkpoint.get("manager_cost_usd", 0.0)

            # 3. 恢复熔断器状态
            self.breaker.restore(checkpoint.get("breaker_state", {}))

            # 4. 更新状态（同时重置 sub_status，避免显示过时状态）
            self._update_state(TaskStatus.EXECUTING, worker_pid=os.getpid(), sub_status="")

            # 5. 检查是否有用户待处理消息（自动恢复场景下用户的回复）
            pending_messages = _read_and_clear_inbox(self.inbox_path)
            user_reply = ""
            if pending_messages:
                user_reply = "\n".join(
                    _parse_inbox_message(m) for m in pending_messages
                )
                self._log_event(f"恢复时发现用户消息: {user_reply[:100]}")

            # 6. 让 Manager 基于恢复上下文决定下一步
            if user_reply:
                resume_notice = (
                    f"[系统通知] 任务从第 {resume_turn} 轮恢复。"
                    f"上一条指令是：{last_instruction}。\n"
                    f"用户回复了：{user_reply}\n"
                    f"请基于用户的回复决定下一步操作。"
                )
            else:
                resume_notice = (
                    f"[系统通知] 任务从第 {resume_turn} 轮崩溃恢复。"
                    f"上一条指令是：{last_instruction}。"
                    f"请决定下一步操作。"
                )
            decision = self.manager.decide(resume_notice)
            instruction = decision.get("instruction", "")

            if not instruction:
                self._handle_non_execute(decision, resume_turn)
                return

            # 7. 继续主循环
            self._main_loop(
                start_turn=resume_turn + 1,
                first_instruction=instruction,
            )
        except Exception as e:
            logger.error(f"恢复任务失败: {e}", exc_info=True)
            self._update_state(TaskStatus.FAILED, error_message=f"恢复失败: {e}",
                               fail_reason=FailReason.RUNTIME_ERROR)

    # ============================================================
    # 主循环
    # ============================================================

    def _main_loop(self, start_turn: int, first_instruction: str):
        """任务主循环"""
        instruction = first_instruction

        for turn in range(start_turn, self.config.manager.max_turns + 1):
            # (a) 检查 abort
            if self._check_abort():
                self._update_state(TaskStatus.ABORTED)
                self._log_event("任务已终止")
                return

            self._last_instruction = instruction
            self._log_event(f"--- Turn {turn}/{self.config.manager.max_turns} ---")
            self._log_event(f"指令: {instruction[:100]}")

            # (b) 子状态：编码工具运行中
            self._update_state(
                TaskStatus.EXECUTING,
                sub_status="tool_running",
                current_turn=turn,
            )

            # (c) 执行编码工具（含 abort 监控）
            self._current_turn = turn   # 供 _on_tool_event 回调使用
            result = self._run_tool_with_abort_watch(instruction, turn)
            if result is None:   # abort 导致的 None 返回
                return

            # (c.1) 确保 result.events 中的 turn 值正确（覆盖占位值 0）
            self._on_tool_run_complete(result, turn)

            self._log_event(
                f"编码工具返回: {len(result.output)} 字符, "
                f"耗时 {result.duration_ms}ms, "
                f"费用 ${result.cost_usd:.4f}"
            )

            # (d) 熔断检查（action 震荡由步骤 k 的 check_action() 单独负责）
            # 注意：breaker.check() 内部只累计工具费用，Manager 费用在步骤 g 后才产生，
            # 总预算检查由步骤 j 补充完成
            breaker_reason = self.breaker.check(
                instruction, result.cost_usd,
                tool_output=result.output,
            )
            budget_already_handled = False
            if breaker_reason:
                if self._handle_breaker(breaker_reason, turn) != "continue":
                    return
                self._update_state(TaskStatus.EXECUTING, sub_status="")
                if breaker_reason.startswith(BREAKER_BUDGET_PREFIX):
                    budget_already_handled = True

            # (e) 子状态：Manager 思考中
            self._update_state(
                TaskStatus.EXECUTING,
                sub_status="manager_thinking",
                total_cost_usd=self.breaker.total_cost + self.manager.total_cost,
                tool_cost_usd=self.breaker.total_cost,
                manager_cost_usd=self.manager.total_cost,
                tool_session_id=result.session_id,
                last_turn_duration_ms=result.duration_ms,
                last_instruction=instruction[:200],
                last_output_summary=result.output[-500:],
            )

            # (f) 写 manager_deciding 事件
            self._write_event(EVENT_MANAGER_DECIDING, turn, {})

            # (g) 读取 inbox + Manager 决策：同时看到编码工具输出 + 用户反馈
            user_messages = _read_and_clear_inbox(self.inbox_path)
            user_feedback = ""
            if user_messages:
                user_feedback = "\n".join(
                    _parse_inbox_message(m) for m in user_messages
                )
                self._log_event(f"收到用户反馈: {user_feedback[:100]}")

            truncated_output = self.context_mgr.truncate_output(result.output)
            if user_feedback:
                parsed = self.manager.decide_with_feedback(
                    truncated_output, user_feedback
                )
            else:
                parsed = self.manager.decide(truncated_output)

            # (h) 写 manager_decided 事件
            self._write_event(EVENT_MANAGER_DECIDED, turn, {
                "action": parsed.get("action", ""),
                "reasoning": parsed.get("reasoning", "")[:200],
            })

            # (h2) 更新 Manager 信息，同时清空 sub_status
            self._update_state(
                TaskStatus.EXECUTING,
                sub_status="",
                last_manager_action=parsed.get("action", ""),
                last_manager_reasoning=parsed.get("reasoning", ""),
            )

            self._log_event(
                f"Manager 决策: {parsed['action']} | "
                f"{parsed.get('reasoning', '')[:80]}"
            )

            # (h3) 写入轮次事件文件（供 Daemon 读取推送）
            self._write_turn_event(turn, result, parsed)

            # (j) 补充预算检查：工具 + Manager 总费用是否超预算
            # breaker.check() 只累计工具费用，Manager 费用在决策后才产生，
            # 这里补充检查总费用，避免 Manager 费用导致的超预算遗漏
            if not budget_already_handled:
                total_cost = self.breaker.total_cost + self.manager.total_cost
                if total_cost > self.breaker.max_budget_usd:
                    budget_reason = (
                        f"{BREAKER_BUDGET_PREFIX}: "
                        f"${total_cost:.2f} > ${self.breaker.max_budget_usd}"
                    )
                    if self._handle_breaker(budget_reason, turn) != "continue":
                        return
                    self._update_state(TaskStatus.EXECUTING, sub_status="")

            # (k) 对本轮 action 补做震荡检测
            # （步骤 d 的 check() 在 Manager 决策前调用，action 传的是 ""，
            #   _check_action_oscillation("") 不会 append。
            #   现在 action 已知，调用 check_action 补做 append + 检测）
            action = parsed.get("action", "execute")
            oscillation = self.breaker.check_action(action)
            if oscillation:
                if self._handle_breaker(oscillation, turn) != "continue":
                    return
                self._update_state(TaskStatus.EXECUTING, sub_status="")

            # (l) 路由 action
            if action == "done":
                self._handle_done(parsed, turn)
                return
            elif action == "blocked":
                self._handle_blocked(parsed)
                return
            elif action == "ask_user":
                while action == "ask_user":
                    reply = self._handle_ask_user(parsed)
                    if reply is None:
                        self._handle_timeout()
                        return
                    # 用户回复送回 Manager 重新决策
                    parsed = self.manager.decide(
                        f"[用户回复了你的提问]\n用户的回答: {reply}"
                    )
                    action = parsed.get("action", "execute")
                    self._update_state(
                        TaskStatus.EXECUTING, sub_status="",
                        last_manager_action=action,
                        last_manager_reasoning=parsed.get("reasoning", ""),
                    )
                    self._log_event(
                        f"Manager 对用户回复的决策: {action} | "
                        f"{parsed.get('reasoning', '')[:80]}"
                    )
                    # 对 re-decision 补做 action 震荡检测
                    oscillation = self.breaker.check_action(action)
                    if oscillation:
                        if self._handle_breaker(oscillation, turn) != "continue":
                            return

                # while 结束后路由非 ask_user action
                if action == "done":
                    self._handle_done(parsed, turn)
                    return
                elif action == "blocked":
                    self._handle_blocked(parsed)
                    return
                elif action == "retry":
                    pass
                else:  # execute
                    instruction = parsed.get("instruction", instruction)
            elif action == "retry":
                pass  # instruction 不变，重试
            else:  # execute
                instruction = parsed.get("instruction", instruction)

            # (m) 保存 checkpoint
            self._save_checkpoint(turn)

        # 超过最大轮数
        self._handle_max_turns()

    # ============================================================
    # Action 处理
    # ============================================================

    def _handle_non_execute(self, parsed: dict, turn: int):
        """处理非 execute action（用于首轮决策）"""
        action = parsed.get("action", "")
        if action == "done":
            self._handle_done(parsed, turn)
        elif action == "blocked":
            self._handle_blocked(parsed)
        elif action == "ask_user":
            while action == "ask_user":
                reply = self._handle_ask_user(parsed)
                if reply is None:
                    self._handle_timeout()
                    return
                # 用户回复送回 Manager 重新决策
                parsed = self.manager.decide(
                    f"[用户回复了你的提问]\n用户的回答: {reply}"
                )
                action = parsed.get("action", "execute")
                self._update_state(
                    TaskStatus.EXECUTING, sub_status="",
                    last_manager_action=action,
                    last_manager_reasoning=parsed.get("reasoning", ""),
                )
                self._log_event(
                    f"Manager 对用户回复的决策: {action} | "
                    f"{parsed.get('reasoning', '')[:80]}"
                )

            # while 结束后路由非 ask_user action
            if action == "done":
                self._handle_done(parsed, turn)
            elif action == "blocked":
                self._handle_blocked(parsed)
            else:  # execute / retry
                instruction = parsed.get("instruction", "")
                if instruction:
                    self._main_loop(start_turn=1, first_instruction=instruction)

    def _handle_done(self, parsed: dict, turn: int):
        """处理任务完成"""
        summary = parsed.get("summary", parsed.get("reasoning", ""))
        logger.info(f"任务完成！共 {turn} 轮")
        self._update_state(TaskStatus.COMPLETED)
        self._log_event(f"任务完成: {summary}")
        self._generate_report(turn, summary)

    def _handle_blocked(self, parsed: dict):
        """处理任务阻塞"""
        reason = parsed.get("reasoning", "未知原因")
        logger.warning(f"任务阻塞: {reason}")
        self._update_state(TaskStatus.FAILED, error_message=f"阻塞: {reason}",
                           fail_reason=FailReason.BLOCKED)
        self._log_event(f"任务阻塞: {reason}")

    def _handle_ask_user(self, parsed: dict) -> Optional[str]:
        """
        处理 ASK_USER：通知用户并等待回复

        返回用户回复内容，超时返回 None。
        """
        question = parsed.get("question", parsed.get("reasoning", "需要你的决定"))
        self._update_state(
            TaskStatus.WAITING_USER,
            last_question=question,
            last_manager_reasoning=parsed.get("reasoning", ""),
        )
        self._log_event(f"等待用户回复: {question}")
        return self._wait_for_user_reply()

    def _handle_breaker(self, reason: str, turn: int) -> str:
        """处理熔断，返回 'continue'（用户确认继续）或 'stop'"""
        logger.warning(f"熔断触发: {reason}")
        # 超预算时通知用户确认（而非直接 abort）
        # 双重判定：总费用（工具 + Manager）比较 + reason 前缀校验，
        # 防止非费用熔断时因费用恰好超限而误入此分支
        total_cost = self.breaker.total_cost + self.manager.total_cost
        is_budget_breach = (
            total_cost > self.breaker.max_budget_usd
            and reason.startswith(BREAKER_BUDGET_PREFIX)
        )
        if is_budget_breach:
            self._update_state(TaskStatus.WAITING_USER,
                               error_message=reason)
            reply = self._wait_for_user_reply()
            if reply and "继续" in reply:
                # 用户确认继续，提升预算
                self.breaker.max_budget_usd *= 2
                self._log_event(f"用户确认继续，预算提升到 ${self.breaker.max_budget_usd}")
                return "continue"
        # 其他熔断或超预算超时
        self._update_state(TaskStatus.FAILED, error_message=reason,
                           fail_reason=FailReason.BREAKER_TRIPPED)
        self._log_event(f"熔断: {reason}")
        return "stop"

    def _handle_max_turns(self):
        """处理超过最大轮数"""
        msg = f"超过最大轮数 {self.config.manager.max_turns}"
        logger.warning(msg)
        self._update_state(TaskStatus.FAILED, error_message=msg,
                           fail_reason=FailReason.MAX_TURNS)
        self._log_event(msg)

    def _handle_timeout(self):
        """处理 ASK_USER 超时"""
        msg = "等待用户回复超时"
        self._update_state(TaskStatus.FAILED, error_message=msg,
                           fail_reason=FailReason.ASK_USER_TIMEOUT)
        self._log_event(msg)

    # ============================================================
    # 等待用户回复
    # ============================================================

    def _wait_for_user_reply(self) -> Optional[str]:
        """
        阻塞等待用户通过 inbox.txt 回复

        轮询间隔 5 秒，同时检查 abort 信号。
        超时返回 None。
        """
        timeout = self.config.telegram.ask_user_timeout
        deadline = time.time() + timeout
        self._log_event(f"等待用户回复（超时 {timeout}s）...")

        while time.time() < deadline:
            # 同时检查 abort
            if self._check_abort():
                return None

            messages = _read_and_clear_inbox(self.inbox_path)
            if messages:
                reply = "\n".join(_parse_inbox_message(m) for m in messages)
                self._log_event(f"收到用户回复: {reply[:100]}")
                self._update_state(TaskStatus.EXECUTING)
                return reply

            time.sleep(5)

        return None

    # ============================================================
    # abort 检测
    # ============================================================

    def _check_abort(self) -> bool:
        """检查是否有 abort 信号文件（消费并删除文件）"""
        abort_file = self.session_dir / "abort"
        if abort_file.exists():
            abort_file.unlink()
            return True
        return False

    def _check_abort_file(self) -> bool:
        """检查 abort 文件是否存在（只读检测，不删除）"""
        return (self.session_dir / "abort").exists()

    # ============================================================
    # 编码工具执行（含 abort 监控）
    # ============================================================

    def _run_tool_with_abort_watch(self, instruction: str, turn: int):
        """
        执行编码工具，同时在后台线程监控 abort 信号

        返回 RunResult，若因 abort 终止则返回 None。
        abort 监控线程每 2 秒检查一次 abort 文件（只读，不删除），
        检测到后调用 runner.abort() 中断子进程。
        文件删除由主循环开头的 _check_abort() 负责。
        """
        abort_event = threading.Event()

        def abort_watcher():
            """轮询 abort 信号文件（只读检测，不删除文件）"""
            while not abort_event.is_set():
                if self._check_abort_file():
                    self.runner.abort()
                    return
                abort_event.wait(timeout=2)   # 每 2 秒检查一次

        watcher = threading.Thread(target=abort_watcher, daemon=True)
        watcher.start()

        try:
            result = self.runner.run(instruction, on_event=self._on_tool_event)
        finally:
            abort_event.set()   # 通知 watcher 退出
            watcher.join(timeout=3)

        # 检查是否因 abort 终止（通过公有接口，避免访问私有字段）
        if self.runner.consume_abort():
            self._update_state(TaskStatus.ABORTED)
            self._log_event("任务已由用户终止（abort）")
            return None

        return result

    # ============================================================
    # 事件写入辅助方法
    # ============================================================

    def _on_tool_event(self, event: ToolEvent):
        """
        ToolRunner 事件实时回调

        设置正确的 turn 值后，立即追加写入 events.jsonl。
        注意：这里直接修改 event 对象（与 _collected_events 中的是同一引用），
        这是有意设计——确保内存和磁盘中的 turn 值一致。
        """
        event.turn = getattr(self, "_current_turn", 0)
        self._write_event_raw(event)

    def _on_tool_run_complete(self, result, turn: int):
        """
        run() 返回后确保 result.events 中所有事件都有正确的 turn 值并已写入磁盘

        on_event 回调存在时，事件已在回调中设置 turn 并写入 events.jsonl（turn >= 1）。
        若事件 turn 仍为 0（占位值），说明未经回调处理，需补设 turn 并写入磁盘。
        """
        for event in result.events:
            if event.turn == 0:
                event.turn = turn
                # 未经 on_event 回调处理的事件，补写磁盘
                self._write_event_raw(event)

    def _write_event(self, event_type: str, turn: int, data: dict):
        """Orchestrator 自产事件（如 manager_deciding/manager_decided）的写入"""
        event = ToolEvent(
            type=event_type,
            timestamp=datetime.now().isoformat(),
            turn=turn,
            data=data,
        )
        self._write_event_raw(event)

    def _write_event_raw(self, event: ToolEvent):
        """
        将 ToolEvent 追加写入 events.jsonl

        单进程单线程写入（on_event 回调在 ToolRunner 主线程中同步调用），
        无需文件锁。POSIX 上单行 < 4KB 的 append 是原子的，
        外部读者（Daemon）可安全读取完整行。
        """
        events_path = self.session_dir / "events.jsonl"
        line = json.dumps(tool_event_to_dict(event), ensure_ascii=False)
        with open(events_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ============================================================
    # state.json 管理
    # ============================================================

    def _update_state(self, status: TaskStatus, **kwargs):
        """更新 state.json"""
        state = read_json_safe(self.state_path) or {}
        state.update({
            "task_id": self.task_id,
            "status": status.value,
            "updated_at": datetime.now().isoformat(),
        })

        # 非 EXECUTING 状态时自动清空 sub_status
        if status != TaskStatus.EXECUTING:
            state["sub_status"] = ""

        if "requirement" in kwargs:
            state["requirement"] = kwargs["requirement"]
            state["created_at"] = datetime.now().isoformat()
            state["started_at"] = datetime.now().isoformat()
            state["working_dir"] = os.getcwd()
            state["coding_tool_type"] = self.config.coding_tool.type
            state["max_turns"] = self.config.manager.max_turns
            state["max_budget_usd"] = self.config.manager.max_budget_usd
        for key in [
            "worker_pid", "current_turn", "total_cost_usd",
            "tool_cost_usd", "manager_cost_usd",
            "tool_session_id", "last_turn_duration_ms",
            "last_instruction", "last_output_summary",
            "last_manager_action", "last_manager_reasoning",
            "last_question",
            "error_message", "fail_reason",
            "sub_status",   # 子状态：tool_running / manager_thinking / 空字符串
        ]:
            if key in kwargs:
                state[key] = kwargs[key]

        atomic_write_json(self.state_path, state)

    # ============================================================
    # checkpoint 管理
    # ============================================================

    def _save_checkpoint(self, turn: int):
        """保存 checkpoint，用于崩溃恢复"""
        # 从 state.json 读取当前 last_question（可能由 _handle_ask_user 写入）
        state = read_json_safe(self.state_path) or {}
        data = {
            "task_id": self.task_id,
            "saved_at": datetime.now().isoformat(),
            "current_turn": turn,
            "tool_session_id": self.runner.session_id or "",
            "total_cost_usd": self.breaker.total_cost + self.manager.total_cost,
            "manager_cost_usd": self.manager.total_cost,
            "manager_conversation_history": self.manager.conversation_history,
            "last_instruction": self._last_instruction,
            "last_question": state.get("last_question", ""),
            "breaker_state": self.breaker.to_dict(),
            # 不保存 sub_status：它是瞬时运行状态（tool_running/manager_thinking），
            # checkpoint 在轮次结束时保存，此时 sub_status 已被清空为 ""，无持久化价值。
            # resume() 会显式重置 sub_status=""。
        }
        atomic_write_json(self.checkpoint_path, data)

    # ============================================================
    # 通知（内联实现）
    # ============================================================

    def _log_event(self, msg: str):
        """写入日志"""
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {msg}"
        logger.info(msg)

        # 写入任务日志文件
        try:
            log_dir = Path(self.config.logging.dir).expanduser() / "tasks" / self.task_id
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "manager.log", "a", encoding="utf-8") as f:
                f.write(log_line + "\n")
        except OSError as e:
            logger.warning(f"写入任务日志失败: {e}")

    # ============================================================
    # 轮次事件写入（供 Daemon 读取推送）
    # ============================================================

    def _write_turn_event(self, turn: int, result, parsed: dict):
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

    # ============================================================
    # 报告生成（内联实现）
    # ============================================================

    def _generate_report(self, total_turns: int, summary: str):
        """生成任务报告"""
        state = read_json_safe(self.state_path) or {}
        total_cost = self.breaker.total_cost + self.manager.total_cost

        # 尝试获取 git diff 的修改文件列表
        modified_files = self._get_modified_files()
        files_section = "\n".join(f"- {f}" for f in modified_files) if modified_files else "（未检测到文件变更）"

        report = f"""# 任务报告: {self._requirement}

## 概要

| 项目 | 值 |
|------|-----|
| 任务 ID | {self.task_id} |
| 状态 | {state.get('status', '未知')} |
| 总轮数 | {total_turns} |
| 总费用 | ${total_cost:.2f} |
| 开始时间 | {state.get('started_at', '未知')} |
| 完成时间 | {datetime.now().isoformat()} |
| 编码工具 | {self.config.coding_tool.type} ({self.config.coding_tool.command}) |
| Manager | {self.config.manager.provider}/{self.config.manager.model} |

## 修改文件

{files_section}

## Manager 总结

{summary}
"""
        with open(self.report_path, "w", encoding="utf-8") as f:
            f.write(report)
        self._log_event(f"报告已生成: {self.report_path}")

    def _get_modified_files(self) -> list[str]:
        """通过 git diff 获取修改文件列表"""
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                capture_output=True, text=True, timeout=10,
                cwd=os.getcwd(),
            )
            if result.returncode == 0:
                return [f for f in result.stdout.strip().split("\n") if f]
        except Exception:
            pass
        return []

    # ============================================================
    # 摘要输出
    # ============================================================

    def _print_summary(self):
        """打印任务执行摘要"""
        state = read_json_safe(self.state_path) or {}
        total_cost = self.breaker.total_cost + self.manager.total_cost

        print(f"\n{'=' * 60}")
        print(f"任务总结")
        print(f"{'=' * 60}")
        print(f"任务 ID  : {self.task_id}")
        print(f"状态     : {state.get('status', '未知')}")
        print(f"轮数     : {state.get('current_turn', 0)}")
        print(f"总费用   : ${total_cost:.2f}")
        if state.get("error_message"):
            print(f"错误信息 : {state['error_message']}")
        print(f"{'=' * 60}\n")
