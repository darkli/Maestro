"""
Telegram Bot + Daemon 模块

包含：
  - TelegramDaemon: 常驻进程，接收 Telegram 命令 + 监控任务状态
  - 命令处理: /run /list /status /ask /chat /abort /report
  - state 监控: 定期轮询 state.json，推送变更通知
  - 直接回复路由: 用户回复通知消息时自动关联到对应 task

架构：全部使用 asyncio 协程，文件 IO 不需要 run_in_executor（极快）。
"""

import os
import sys
import asyncio
import argparse
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Optional

from maestro.config import load_config, AppConfig
from maestro.registry import TaskRegistry
from maestro.state import read_json_safe
from maestro.orchestrator import _write_inbox

logger = logging.getLogger(__name__)


class TelegramDaemon:
    """
    Telegram Bot 守护进程

    职责：
    1. 接收 Telegram 命令并路由处理
    2. 定期轮询 state.json 推送任务状态变更
    3. ASK_USER 通知 + 直接回复路由
    """

    def __init__(self, config: AppConfig, config_path: str = "config.yaml"):
        self.config = config
        self._config_path = os.path.abspath(config_path)
        self.registry = TaskRegistry(
            max_parallel_tasks=config.safety.max_parallel_tasks
        )
        # 缓存各任务的上次状态（用于检测变更）
        self._last_states: dict[str, dict] = {}
        # 消息 ID → task_id 映射（用于直接回复路由）
        self._message_task_map: dict[int, str] = {}
        # 自由聊天对话历史（最近 20 条消息）
        self._free_chat_history: list[dict] = []

    async def start(self):
        """启动 Daemon"""
        try:
            from telegram import Update
            from telegram.ext import (
                Application, CommandHandler, MessageHandler,
                ContextTypes, filters,
            )
        except ImportError:
            logger.error(
                "python-telegram-bot 未安装，请运行: "
                "pip install python-telegram-bot>=21.0"
            )
            return

        if not self.config.telegram.bot_token:
            logger.error("未配置 telegram.bot_token")
            return

        logger.info("Telegram Daemon 启动中...")

        app = Application.builder().token(
            self.config.telegram.bot_token
        ).build()

        # 注册命令处理器
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(CommandHandler("help", self._on_help))
        app.add_handler(CommandHandler("run", self._on_run))
        app.add_handler(CommandHandler("list", self._on_list))
        app.add_handler(CommandHandler("status", self._on_status))
        app.add_handler(CommandHandler("ask", self._on_ask))
        app.add_handler(CommandHandler("chat", self._on_chat))
        app.add_handler(CommandHandler("abort", self._on_abort))
        app.add_handler(CommandHandler("report", self._on_report))
        app.add_handler(CommandHandler("new", self._on_new))

        # 普通消息处理（用于直接回复路由）
        app.add_handler(MessageHandler(
            filters.TEXT & ~filters.COMMAND, self._on_message
        ))

        # 启动 state 监控任务
        app.job_queue.run_repeating(self._monitor_loop, interval=5)

        logger.info("Telegram Daemon 已启动")

        # 使用低级 API 启动，避免 run_polling 与 asyncio.run 事件循环冲突
        import signal
        async with app:
            await app.start()
            await app.updater.start_polling(drop_pending_updates=True)

            # 优雅退出：捕获 SIGINT/SIGTERM
            stop_event = asyncio.Event()
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, stop_event.set)

            await stop_event.wait()

            await app.updater.stop()
            await app.stop()

    # ============================================================
    # 鉴权
    # ============================================================

    def _check_auth(self, chat_id: int) -> bool:
        """检查 chat_id 是否授权"""
        allowed = self.config.telegram.chat_id
        if not allowed:
            return True
        return str(chat_id) == str(allowed)

    # ============================================================
    # 命令处理
    # ============================================================

    async def _on_start(self, update, context):
        """处理 /start 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return
        await update.message.reply_text(
            "Maestro Bot 已就绪！\n\n"
            "可用命令:\n"
            "/run <目录> <需求> - 启动任务\n"
            "/list - 查看任务列表\n"
            "/status <id> - 查看任务详情\n"
            "/ask <id> <消息> - 发送反馈\n"
            "/chat <id> <问题> - 与 Agent 对话\n"
            "/abort <id> - 终止任务\n"
            "/report <id> - 查看报告\n"
            "/new - 重置聊天上下文\n"
            "直接发消息 - 自由聊天"
        )

    async def _on_help(self, update, context):
        """处理 /help 命令"""
        await self._on_start(update, context)

    async def _on_run(self, update, context):
        """处理 /run 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text(
                "用法: /run <工作目录> <需求描述>\n"
                "示例: /run /home/user/project 帮我实现登录模块"
            )
            return

        working_dir = args[0]
        requirement = " ".join(args[1:])

        # 验证目录：展开 ~ 和环境变量（如 $HOME）
        real_dir = os.path.realpath(
            os.path.expanduser(os.path.expandvars(working_dir))
        )
        if not os.path.isdir(real_dir):
            await update.message.reply_text(f"目录不存在: {real_dir}")
            return

        # 并发检查
        can_start, reason = self.registry.can_start_new_task()
        if not can_start:
            await update.message.reply_text(f"无法启动: {reason}")
            return

        # 创建任务
        task_id = TaskRegistry.generate_task_id()
        self.registry.create_task(task_id, requirement, real_dir)

        # 启动 worker
        self._launch_worker(task_id, real_dir, requirement)

        await update.message.reply_text(
            f"任务 [{task_id}] 已启动\n"
            f"目录: {real_dir}\n"
            f"需求: {requirement}\n\n"
            f"查看状态: /status {task_id}\n"
            f"终止任务: /abort {task_id}"
        )

    async def _on_list(self, update, context):
        """处理 /list 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        tasks = self.registry.list_tasks()
        if not tasks:
            await update.message.reply_text("暂无任务")
            return

        status_icons = {
            "pending": "...",
            "executing": ">>>",
            "waiting_user": "???",
            "completed": "[OK]",
            "failed": "[!!]",
            "aborted": "[XX]",
        }

        lines = []
        for t in tasks[:10]:  # 最多显示 10 个
            icon = status_icons.get(t.get("status", ""), "   ")
            req = t.get("requirement", "")[:30]
            lines.append(f"{icon} [{t['task_id']}] {req}")

        await update.message.reply_text("\n".join(lines))

    async def _on_status(self, update, context):
        """处理 /status 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if not args:
            await update.message.reply_text("用法: /status <task_id>")
            return

        task_id = args[0]
        state = self._read_state(task_id)
        if not state:
            await update.message.reply_text(f"任务 {task_id} 不存在")
            return

        msg = (
            f"[{task_id}] {state.get('requirement', '')[:40]}\n\n"
            f"状态: {state.get('status', '未知')}\n"
            f"进度: Turn {state.get('current_turn', 0)}/{state.get('max_turns', 0)}\n"
            f"费用: ${state.get('total_cost_usd', 0):.2f}\n"
            f"目录: {state.get('working_dir', '')}\n"
        )

        if state.get("last_instruction"):
            msg += f"\n上一轮指令:\n  {state['last_instruction'][:150]}\n"
        if state.get("last_output_summary"):
            summary = state["last_output_summary"][-200:]
            msg += f"\n最近输出:\n  {summary}\n"
        if state.get("last_manager_reasoning"):
            msg += f"\nManager 思路:\n  {state['last_manager_reasoning'][:150]}\n"
        if state.get("error_message"):
            msg += f"\n错误: {state['error_message']}\n"

        await update.message.reply_text(msg)

    async def _on_ask(self, update, context):
        """处理 /ask 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text("用法: /ask <task_id> <消息>")
            return

        task_id = args[0]
        message = " ".join(args[1:])

        inbox_path = (
            Path("~/.maestro/sessions").expanduser()
            / task_id / "inbox.txt"
        )
        if not inbox_path.parent.exists():
            await update.message.reply_text(f"任务 {task_id} 不存在")
            return

        _write_inbox(str(inbox_path), "telegram", message)
        await update.message.reply_text(
            f"已向任务 [{task_id}] 发送反馈: {message}"
        )

    async def _on_chat(self, update, context):
        """处理 /chat 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if len(args) < 2:
            await update.message.reply_text("用法: /chat <task_id> <问题>")
            return

        task_id = args[0]
        user_message = " ".join(args[1:])

        state = self._read_state(task_id)
        if not state:
            await update.message.reply_text(f"任务 {task_id} 不存在")
            return

        # 构建上下文
        context_summary = (
            f"当前任务: {state.get('requirement', '')}\n"
            f"状态: {state.get('status', '')}, "
            f"第 {state.get('current_turn', 0)}/{state.get('max_turns', 0)} 轮\n"
            f"费用: ${state.get('total_cost_usd', 0):.2f}\n"
            f"最近 Manager 决策: {state.get('last_manager_action', '')}\n"
            f"Manager 思路: {state.get('last_manager_reasoning', '')}\n"
        )
        if state.get("last_output_summary"):
            context_summary += (
                f"\n最近编码工具输出:\n"
                f"{state['last_output_summary'][-300:]}\n"
            )

        # 调用 Manager LLM 做独立问答（不影响任务循环）
        from maestro.manager_agent import ManagerAgent
        manager = ManagerAgent(self.config.manager)
        reply = manager.standalone_chat(context_summary, user_message)

        sent = await update.message.reply_text(f"[{task_id}]\n\n{reply}")
        # 记录消息 ID 用于直接回复路由
        self._message_task_map[sent.message_id] = task_id

    async def _on_abort(self, update, context):
        """处理 /abort 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if not args:
            await update.message.reply_text("用法: /abort <task_id>")
            return

        task_id = args[0]
        session_dir = (
            Path("~/.maestro/sessions").expanduser() / task_id
        )
        if not session_dir.exists():
            await update.message.reply_text(f"任务 {task_id} 不存在")
            return

        abort_file = session_dir / "abort"
        abort_file.touch()
        self.registry.update_task(task_id, status="aborted")

        await update.message.reply_text(f"已发送终止信号到任务 [{task_id}]")

    async def _on_report(self, update, context):
        """处理 /report 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if not args:
            await update.message.reply_text("用法: /report <task_id>")
            return

        task_id = args[0]
        report_path = (
            Path("~/.maestro/sessions").expanduser()
            / task_id / "report.md"
        )
        if not report_path.exists():
            await update.message.reply_text(f"任务 [{task_id}] 暂无报告")
            return

        report = report_path.read_text(encoding="utf-8")
        # Telegram 消息限制 4096 字符
        if len(report) > 4000:
            report = report[:4000] + "\n...(已截断)"
        await update.message.reply_text(report)

    async def _on_new(self, update, context):
        """处理 /new 命令：重置自由聊天上下文"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return
        self._free_chat_history = []
        await update.message.reply_text("对话已重置")

    async def _on_message(self, update, context):
        """处理普通消息：回复任务通知 → inbox 路由，其他 → 自由聊天"""
        if not self._check_auth(update.effective_chat.id):
            return

        # 优先检查：回复任务通知消息 → inbox 路由
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
                    await update.message.reply_text(
                        f"已转发到任务 [{task_id}]"
                    )
                return

        # 其他所有消息 → 自由聊天
        await self._handle_free_chat(update)

    async def _handle_free_chat(self, update):
        """处理自由聊天消息"""
        user_text = update.message.text

        # 发送 typing 状态提示
        await update.message.chat.send_action("typing")

        # 调用 LLM
        from maestro.manager_agent import ManagerAgent
        manager = ManagerAgent(self.config.manager)
        reply = manager.free_chat(self._free_chat_history, user_text)

        # 更新历史
        self._free_chat_history.append({"role": "user", "content": user_text})
        self._free_chat_history.append({"role": "assistant", "content": reply})

        # 保留最近 20 条消息（10 轮对话）
        if len(self._free_chat_history) > 20:
            self._free_chat_history = self._free_chat_history[-20:]

        # 发送回复（处理 Telegram 4096 字符限制）
        if len(reply) > 4000:
            reply = reply[:4000] + "\n...(已截断)"
        await update.message.reply_text(reply)

    # ============================================================
    # state 监控
    # ============================================================

    async def _monitor_loop(self, context):
        """定期轮询所有任务的 state.json，推送变更通知"""
        sessions_dir = Path("~/.maestro/sessions").expanduser()
        if not sessions_dir.exists():
            return

        for task_dir in sessions_dir.iterdir():
            if not task_dir.is_dir():
                continue

            task_id = task_dir.name
            state = self._read_state(task_id)
            if not state:
                continue

            last = self._last_states.get(task_id, {})
            current_status = state.get("status", "")
            last_status = last.get("status", "")

            # 检测状态变更
            if current_status != last_status:
                await self._push_status_change(
                    context, task_id, state, last_status, current_status
                )

            # 检测 Worker 进程健康
            if current_status == "executing":
                pid = state.get("worker_pid")
                if pid:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        state["status"] = "failed"
                        state["error_message"] = "Worker 进程意外退出"
                        from maestro.state import atomic_write_json
                        atomic_write_json(
                            str(task_dir / "state.json"), state
                        )
                        self.registry.update_task(
                            task_id, status="failed"
                        )
                        if self.config.telegram.chat_id:
                            await context.bot.send_message(
                                chat_id=self.config.telegram.chat_id,
                                text=(
                                    f"[{task_id}] Worker 崩溃！\n"
                                    f"可用 maestro resume {task_id} 恢复"
                                ),
                            )

            # 同步 registry
            self.registry.sync_from_state(task_id)
            self._last_states[task_id] = state.copy()

    async def _push_status_change(self, context, task_id: str,
                                   state: dict, old: str, new: str):
        """推送状态变更通知"""
        if not self.config.telegram.chat_id:
            return

        if new == "completed":
            msg = (
                f"[{task_id}] 任务完成！\n"
                f"轮数: {state.get('current_turn', 0)}\n"
                f"费用: ${state.get('total_cost_usd', 0):.2f}\n"
                f"查看报告: /report {task_id}"
            )
        elif new == "failed":
            msg = (
                f"[{task_id}] 任务失败\n"
                f"原因: {state.get('error_message', '未知')}\n"
                f"恢复: maestro resume {task_id}"
            )
        elif new == "waiting_user":
            msg = (
                f"[{task_id}] 需要你的回复\n"
                f"Manager 思路: {state.get('last_manager_reasoning', '')[:200]}\n\n"
                f"回复: /ask {task_id} <你的回复>"
            )
        elif new == "aborted":
            msg = f"[{task_id}] 任务已终止"
        else:
            return  # 其他状态变更不推送

        try:
            sent = await context.bot.send_message(
                chat_id=self.config.telegram.chat_id,
                text=msg,
            )
            self._message_task_map[sent.message_id] = task_id
        except Exception as e:
            logger.warning(f"Telegram 推送失败: {e}")

    # ============================================================
    # 辅助方法
    # ============================================================

    def _read_state(self, task_id: str) -> Optional[dict]:
        """读取任务的 state.json"""
        path = (
            Path("~/.maestro/sessions").expanduser()
            / task_id / "state.json"
        )
        return read_json_safe(str(path))

    def _launch_worker(self, task_id: str, working_dir: str,
                       requirement: str):
        """启动 worker 进程"""
        cmd = [
            sys.executable, "-m", "maestro.cli",
            "_worker", task_id, working_dir, requirement,
            "-c", self._config_path,
        ]

        import shutil
        zellij = shutil.which("zellij")
        if zellij and self.config.zellij.enabled:
            zellij_cmd = [
                zellij, "--session", f"maestro-{task_id}",
                "--", *cmd,
            ]
            subprocess.Popen(
                zellij_cmd,
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            log_dir = (
                Path(self.config.logging.dir).expanduser()
                / "tasks" / task_id
            )
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / "worker.log", "a") as f:
                subprocess.Popen(
                    cmd,
                    stdout=f,
                    stderr=f,
                    start_new_session=True,
                    cwd=working_dir,
                )


# ============================================================
# 入口
# ============================================================

def main():
    """Telegram Daemon 入口"""
    parser = argparse.ArgumentParser(description="Maestro Telegram Daemon")
    parser.add_argument(
        "--config", "-c", default="config.yaml", help="配置文件路径"
    )
    args = parser.parse_args()

    config = load_config(args.config)

    # 初始化日志
    log_dir = Path(config.logging.dir).expanduser()
    log_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_dir / "daemon.log", encoding="utf-8"),
        ]
    )

    daemon = TelegramDaemon(config, config_path=args.config)
    asyncio.run(daemon.start())


if __name__ == "__main__":
    main()
