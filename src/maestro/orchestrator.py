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
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

from maestro.config import AppConfig, load_config
from maestro.state import (
    TaskStatus, CircuitBreaker, atomic_write_json, read_json_safe,
)
from maestro.context import ContextManager
from maestro.tool_runner import ToolRunner
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
        self.manager = ManagerAgent(config.manager)
        self.breaker = CircuitBreaker.from_config(
            config.safety,
            max_turns=config.manager.max_turns,
            max_budget_usd=config.manager.max_budget_usd,
        )
        self.context_mgr = ContextManager(config.context)

        # 文件路径
        self.state_path = str(self.session_dir / "state.json")
        self.checkpoint_path = str(self.session_dir / "checkpoint.json")
        self.inbox_path = str(self.session_dir / "inbox.txt")
        self.report_path = str(self.session_dir / "report.md")
        Path(self.inbox_path).touch()

        # 运行时状态
        self._last_instruction: str = ""
        self._requirement: str = ""

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

        # 2. 启动 Zellij Session（可选）
        zellij = self._setup_zellij()

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
            self._update_state(TaskStatus.FAILED, error_message=str(e))
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
        logger.info(
            f"恢复任务 [{self.task_id}] "
            f"从第 {checkpoint['current_turn']} 轮"
        )

        # 1. 恢复 Runner 会话
        tool_session_id = checkpoint.get("tool_session_id", "")
        if tool_session_id:
            self.runner.resume_session(tool_session_id)

        # 2. 恢复 Manager 对话历史
        self.manager.conversation_history = checkpoint.get(
            "manager_conversation_history", []
        )

        # 3. 恢复熔断器状态
        self.breaker.restore(checkpoint.get("breaker_state", {}))

        # 4. 更新状态
        self._update_state(TaskStatus.EXECUTING, worker_pid=os.getpid())

        # 5. 让 Manager 基于恢复上下文决定下一步
        resume_notice = (
            f"[系统通知] 任务从第 {checkpoint['current_turn']} 轮崩溃恢复。"
            f"上一条指令是：{checkpoint.get('last_instruction', '未知')}。"
            f"请决定下一步操作。"
        )
        decision = self.manager.decide(resume_notice)
        instruction = decision.get("instruction", "")

        if not instruction:
            self._handle_non_execute(decision, checkpoint['current_turn'])
            return

        # 6. 继续主循环
        self._main_loop(
            start_turn=checkpoint['current_turn'] + 1,
            first_instruction=instruction,
        )

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
                self._log_event(f"任务已终止")
                self._telegram_push(f"[{self.task_id}] 已终止")
                return

            self._last_instruction = instruction
            self._log_event(f"--- Turn {turn}/{self.config.manager.max_turns} ---")
            self._log_event(f"指令: {instruction[:100]}")

            # (b) 执行编码工具
            result = self.runner.run(instruction)
            self._log_event(
                f"编码工具返回: {len(result.output)} 字符, "
                f"耗时 {result.duration_ms}ms, "
                f"费用 ${result.cost_usd:.4f}"
            )

            # (c) 熔断检查
            breaker_reason = self.breaker.check(instruction, result.cost_usd)
            if breaker_reason:
                self._handle_breaker(breaker_reason, turn)
                return

            # (d) 更新状态
            self._update_state(
                TaskStatus.EXECUTING,
                current_turn=turn,
                total_cost_usd=self.breaker.total_cost,
                tool_session_id=result.session_id,
                last_turn_duration_ms=result.duration_ms,
                last_instruction=instruction[:200],
                last_output_summary=result.output[-500:],
            )

            # (e) 通知
            total_cost = self.breaker.total_cost + self.manager.total_cost
            self._telegram_push_turn(turn, result.cost_usd, total_cost, result.duration_ms)

            # (f) 读取 inbox（在 Manager 决策前，而非编码工具执行前）
            user_messages = _read_and_clear_inbox(self.inbox_path)
            user_feedback = ""
            if user_messages:
                user_feedback = "\n".join(
                    _parse_inbox_message(m) for m in user_messages
                )
                self._log_event(f"收到用户反馈: {user_feedback[:100]}")

            # (g) Manager 决策：同时看到编码工具输出 + 用户反馈
            truncated_output = self.context_mgr.truncate_output(result.output)
            if user_feedback:
                parsed = self.manager.decide_with_feedback(
                    truncated_output, user_feedback
                )
            else:
                parsed = self.manager.decide(truncated_output)

            # (h) 更新 state 中的 Manager 信息
            self._update_state(
                TaskStatus.EXECUTING,
                last_manager_action=parsed.get("action", ""),
                last_manager_reasoning=parsed.get("reasoning", ""),
            )

            self._log_event(
                f"Manager 决策: {parsed['action']} | "
                f"{parsed.get('reasoning', '')[:80]}"
            )

            # (i) 路由 action
            action = parsed.get("action", "execute")

            if action == "done":
                self._handle_done(parsed, turn)
                return
            elif action == "blocked":
                self._handle_blocked(parsed)
                return
            elif action == "ask_user":
                instruction = self._handle_ask_user(parsed)
                if instruction is None:
                    # 超时无回复
                    self._handle_timeout()
                    return
            elif action == "retry":
                pass  # instruction 不变，重试
            else:  # execute
                instruction = parsed.get("instruction", instruction)

            # (j) 保存 checkpoint
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
            result = self._handle_ask_user(parsed)
            if result:
                self._main_loop(start_turn=1, first_instruction=result)
            else:
                self._handle_timeout()

    def _handle_done(self, parsed: dict, turn: int):
        """处理任务完成"""
        summary = parsed.get("summary", parsed.get("reasoning", ""))
        logger.info(f"任务完成！共 {turn} 轮")
        self._update_state(TaskStatus.COMPLETED)
        self._log_event(f"任务完成: {summary}")
        self._telegram_push(
            f"[{self.task_id}] 任务完成！\n"
            f"轮数: {turn}\n"
            f"总费用: ${self.breaker.total_cost + self.manager.total_cost:.2f}\n"
            f"摘要: {summary[:200]}"
        )
        self._generate_report(turn, summary)

    def _handle_blocked(self, parsed: dict):
        """处理任务阻塞"""
        reason = parsed.get("reasoning", "未知原因")
        logger.warning(f"任务阻塞: {reason}")
        self._update_state(TaskStatus.FAILED, error_message=f"阻塞: {reason}")
        self._log_event(f"任务阻塞: {reason}")
        self._telegram_push(f"[{self.task_id}] 任务阻塞: {reason[:200]}")

    def _handle_ask_user(self, parsed: dict) -> Optional[str]:
        """
        处理 ASK_USER：通知用户并等待回复

        返回用户回复内容，超时返回 None。
        """
        question = parsed.get("question", parsed.get("reasoning", "需要你的决定"))
        self._update_state(TaskStatus.WAITING_USER)
        self._log_event(f"等待用户回复: {question}")
        self._telegram_push(
            f"[{self.task_id}] 需要你的回复:\n{question}\n\n"
            f"请用 /ask {self.task_id} <你的回复> 回复"
        )
        return self._wait_for_user_reply()

    def _handle_breaker(self, reason: str, turn: int):
        """处理熔断"""
        logger.warning(f"熔断触发: {reason}")
        # 超预算时通知用户确认（而非直接 abort）
        if "费用超限" in reason:
            self._telegram_push(
                f"[{self.task_id}] {reason}\n"
                f"是否继续？回复 /ask {self.task_id} 继续 或 /abort {self.task_id}"
            )
            self._update_state(TaskStatus.WAITING_USER,
                               error_message=reason)
            reply = self._wait_for_user_reply()
            if reply and "继续" in reply:
                # 用户确认继续，提升预算
                self.breaker.max_budget_usd *= 2
                self._log_event(f"用户确认继续，预算提升到 ${self.breaker.max_budget_usd}")
                return  # 继续执行
        # 其他熔断或超预算超时
        self._update_state(TaskStatus.FAILED, error_message=reason)
        self._log_event(f"熔断: {reason}")
        self._telegram_push(f"[{self.task_id}] 熔断: {reason}")

    def _handle_max_turns(self):
        """处理超过最大轮数"""
        msg = f"超过最大轮数 {self.config.manager.max_turns}"
        logger.warning(msg)
        self._update_state(TaskStatus.FAILED, error_message=msg)
        self._log_event(msg)
        self._telegram_push(f"[{self.task_id}] {msg}")

    def _handle_timeout(self):
        """处理 ASK_USER 超时"""
        msg = "等待用户回复超时"
        self._update_state(TaskStatus.FAILED, error_message=msg)
        self._log_event(msg)
        self._telegram_push(f"[{self.task_id}] {msg}，任务已停止")

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
        """检查是否有 abort 信号文件"""
        abort_file = self.session_dir / "abort"
        if abort_file.exists():
            abort_file.unlink()
            return True
        return False

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
        if "requirement" in kwargs:
            state["requirement"] = kwargs["requirement"]
            state["created_at"] = datetime.now().isoformat()
            state["started_at"] = datetime.now().isoformat()
            state["working_dir"] = os.getcwd()
            state["coding_tool_type"] = self.config.coding_tool.type
            state["max_turns"] = self.config.manager.max_turns
            state["max_budget_usd"] = self.config.manager.max_budget_usd
            state["zellij_session"] = f"maestro-{self.task_id}"
        for key in [
            "worker_pid", "current_turn", "total_cost_usd",
            "tool_session_id", "last_turn_duration_ms",
            "last_instruction", "last_output_summary",
            "last_manager_action", "last_manager_reasoning",
            "error_message",
        ]:
            if key in kwargs:
                state[key] = kwargs[key]

        atomic_write_json(self.state_path, state)

    # ============================================================
    # checkpoint 管理
    # ============================================================

    def _save_checkpoint(self, turn: int):
        """保存 checkpoint，用于崩溃恢复"""
        data = {
            "task_id": self.task_id,
            "saved_at": datetime.now().isoformat(),
            "current_turn": turn,
            "tool_session_id": self.runner.session_id or "",
            "total_cost_usd": self.breaker.total_cost,
            "manager_conversation_history": self.manager.conversation_history,
            "last_instruction": self._last_instruction,
            "breaker_state": self.breaker.to_dict(),
        }
        atomic_write_json(self.checkpoint_path, data)

    # ============================================================
    # 通知（内联实现）
    # ============================================================

    def _log_event(self, msg: str):
        """写入日志（兼容 Zellij 面板 tail -f）"""
        timestamp = time.strftime("%H:%M:%S")
        log_line = f"[{timestamp}] {msg}"
        logger.info(msg)

        # 写入任务日志文件（供 Zellij tail -f）
        log_dir = Path(self.config.logging.dir).expanduser() / "tasks" / self.task_id
        log_dir.mkdir(parents=True, exist_ok=True)
        with open(log_dir / "manager.log", "a", encoding="utf-8") as f:
            f.write(log_line + "\n")

    def _telegram_push(self, message: str):
        """推送 Telegram 通知（最简实现）"""
        if not self.config.telegram.enabled:
            return
        if not self.config.telegram.bot_token or not self.config.telegram.chat_id:
            return

        try:
            import urllib.request
            import urllib.parse
            url = (
                f"https://api.telegram.org/bot{self.config.telegram.bot_token}"
                f"/sendMessage"
            )
            data = urllib.parse.urlencode({
                "chat_id": self.config.telegram.chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }).encode()
            req = urllib.request.Request(url, data=data, method="POST")
            urllib.request.urlopen(req, timeout=10)
        except Exception as e:
            logger.warning(f"Telegram 推送失败: {e}")

    def _telegram_push_turn(self, turn: int, turn_cost: float,
                            total_cost: float, duration_ms: int):
        """推送每轮进度通知"""
        if not self.config.telegram.push_every_turn:
            return
        self._telegram_push(
            f"[{self.task_id}] Turn {turn}/{self.config.manager.max_turns}\n"
            f"本轮: ${turn_cost:.4f} | {duration_ms}ms\n"
            f"累计: ${total_cost:.2f}"
        )

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
    # Zellij Session（可选）
    # ============================================================

    def _setup_zellij(self):
        """初始化 Zellij Session（如果启用）"""
        if not self.config.zellij.enabled:
            return None

        try:
            from maestro.session import ZellijSession
            session = ZellijSession(
                task_id=self.task_id,
                log_dir=self.config.logging.dir,
                auto_install=self.config.zellij.auto_install,
            )
            if session.launch():
                self._log_event(f"Zellij 界面已启动: {session.session_name}")
                self._log_event(f"在另一个终端运行: zellij attach {session.session_name}")
                return session
        except Exception as e:
            logger.warning(f"Zellij 初始化失败: {e}")
        return None

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
