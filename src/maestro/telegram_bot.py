"""
Telegram Bot + Daemon 模块

包含：
  - TelegramDaemon: 常驻进程，接收 Telegram 命令 + 监控任务状态
  - 命令处理: /run /list /status /ask /chat /abort /report /focus
  - state 监控: 定期轮询 state.json，推送变更通知
  - focus 模式: 关注指定任务，推送每轮详细输出
  - 直接回复路由: 用户回复通知消息时自动关联到对应 task

架构：全部使用 asyncio 协程，文件 IO 不需要 run_in_executor（极快）。
"""

import json
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
from maestro.cli import _launch_resume_background

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
        # 关注模式：当前关注的任务 ID
        self._focused_task_id: Optional[str] = None
        # 各任务的 turns.jsonl 读取位置（字节偏移）
        self._turn_file_positions: dict[str, int] = {}
        # 默认工作目录（通过 /cd 设置）
        self._default_working_dir: Optional[str] = None
        # 自动恢复防重入（正在恢复中的任务 ID 集合）
        self._resuming_tasks: set[str] = set()

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

        # 初始化时跳过已有的历史内容，避免重启后重发通知
        self._init_turn_positions()
        self._init_last_states()

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
        app.add_handler(CommandHandler("focus", self._on_focus))
        app.add_handler(CommandHandler("cd", self._on_cd))

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
            "/cd <路径> - 设置工作目录\n"
            "/run <需求> - 启动任务（需先 /cd）\n"
            "/list - 查看任务列表\n"
            "/focus [id] - 查看/切换关注任务\n"
            "/focus off - 取消关注\n\n"
            "以下命令省略 id 时默认用 focus 的任务:\n"
            "/status [id] - 查看任务详情\n"
            "/ask [id] <消息> - 发送反馈\n"
            "/chat [id] <问题> - 与 Agent 对话\n"
            "/abort [id] - 终止任务\n"
            "/report [id] - 查看报告\n\n"
            "/new - 重置聊天上下文\n"
            "直接发消息 - 自由聊天"
        )

    async def _on_help(self, update, context):
        """处理 /help 命令"""
        await self._on_start(update, context)

    async def _on_run(self, update, context):
        """处理 /run 命令：/run <需求描述>（需先 /cd 设置工作目录）"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if not args:
            await update.message.reply_text("用法: /run <需求描述>")
            return

        if not self._default_working_dir:
            await update.message.reply_text(
                "请先设置工作目录:\n/cd /home/user/project"
            )
            return

        requirement = " ".join(args)
        real_dir = self._default_working_dir
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

        # 自动关注新任务
        self._focused_task_id = task_id
        self._turn_file_positions[task_id] = 0

        await update.message.reply_text(
            f"任务 [{task_id}] 已启动（已自动关注）\n"
            f"目录: {real_dir}\n"
            f"需求: {requirement}\n\n"
            f"查看状态: /status {task_id}\n"
            f"终止任务: /abort {task_id}\n"
            f"切换关注: /focus <其他任务ID>"
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
            "pending":      "⏳",
            "executing":    "⚙️",
            "waiting_user": "✋",
            "completed":    "✅",
            "failed":       "❌",
            "aborted":      "🛑",
        }

        # failed 细分图标
        fail_reason_icons = {
            "ask_user_timeout":  "⏰",
            "max_turns":         "🔄",
            "breaker_tripped":   "⚡",
            "blocked":           "🚫",
            "worker_crashed":    "💥",
            "runtime_error":     "⚠️",
        }

        lines = []
        for t in tasks[:10]:  # 最多显示 10 个
            status = t.get("status", "")
            icon = status_icons.get(status, "❓")
            if status == "failed":
                icon = fail_reason_icons.get(t.get("fail_reason", ""), icon)
            req = t.get("requirement", "")[:30]
            lines.append(f"{icon} [{t['task_id']}] {req}")

        await update.message.reply_text("\n".join(lines))

    async def _on_status(self, update, context):
        """处理 /status 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        task_id = args[0] if args else self._focused_task_id
        if not task_id:
            await update.message.reply_text("用法: /status <task_id>（或先 /focus 一个任务）")
            return

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
        if not args:
            await update.message.reply_text("用法: /ask <消息>（已 focus 时）或 /ask <task_id> <消息>")
            return

        # 判断第一个参数是 task_id 还是消息内容
        first = args[0]
        first_as_task = Path("~/.maestro/sessions").expanduser() / first
        if len(args) >= 2 and first_as_task.is_dir():
            task_id = first
            message = " ".join(args[1:])
        elif self._focused_task_id:
            task_id = self._focused_task_id
            message = " ".join(args)
        else:
            await update.message.reply_text("用法: /ask <task_id> <消息>（或先 /focus 一个任务）")
            return

        inbox_path = (
            Path("~/.maestro/sessions").expanduser()
            / task_id / "inbox.txt"
        )
        if not inbox_path.parent.exists():
            await update.message.reply_text(f"任务 {task_id} 不存在")
            return

        # 对终态任务拦截，避免写入无人消费的 inbox
        state = self._read_state(task_id)
        status = state.get("status", "") if state else ""
        if status == "completed":
            await update.message.reply_text(f"任务 [{task_id}] 已完成，无法发送反馈")
            return
        if status == "aborted":
            await update.message.reply_text(
                f"任务 [{task_id}] 已终止\n如需恢复: maestro resume {task_id}"
            )
            return

        _write_inbox(str(inbox_path), "telegram", message)

        # 检测是否需要自动恢复（进程已死的任务）
        resumed = await self._auto_resume_if_needed(task_id, update)
        if not resumed:
            await update.message.reply_text(
                f"已向任务 [{task_id}] 发送反馈: {message}"
            )

    async def _on_chat(self, update, context):
        """处理 /chat 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if not args:
            await update.message.reply_text("用法: /chat <问题>（已 focus 时）或 /chat <task_id> <问题>")
            return

        # 判断第一个参数是 task_id 还是问题内容
        first = args[0]
        first_as_task = Path("~/.maestro/sessions").expanduser() / first
        if len(args) >= 2 and first_as_task.is_dir():
            task_id = first
            user_message = " ".join(args[1:])
        elif self._focused_task_id:
            task_id = self._focused_task_id
            user_message = " ".join(args)
        else:
            await update.message.reply_text("用法: /chat <task_id> <问题>（或先 /focus 一个任务）")
            return

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
        task_id = args[0] if args else self._focused_task_id
        if not task_id:
            await update.message.reply_text("用法: /abort <task_id>（或先 /focus 一个任务）")
            return

        # 检查 registry 中是否存在该任务
        tasks = self.registry.list_tasks()
        task_exists = any(t.get("task_id") == task_id for t in tasks)

        session_dir = (
            Path("~/.maestro/sessions").expanduser() / task_id
        )

        if not task_exists and not session_dir.exists():
            await update.message.reply_text(f"任务 {task_id} 不存在")
            return

        # 如果 session 目录存在，创建 abort 信号文件通知 worker
        if session_dir.exists():
            abort_file = session_dir / "abort"
            abort_file.touch()

            # 同时更新 state.json，防止 monitor 在 worker 处理前误判为 worker_crashed
            state_path = session_dir / "state.json"
            state = read_json_safe(str(state_path))
            if state:
                state["status"] = "aborted"
                from maestro.state import atomic_write_json
                atomic_write_json(str(state_path), state)

        self.registry.update_task(task_id, status="aborted")

        # 如果被 abort 的是当前关注的任务，自动取消关注
        if self._focused_task_id == task_id:
            self._focused_task_id = None

        await update.message.reply_text(f"已终止任务 [{task_id}]")

    async def _on_report(self, update, context):
        """处理 /report 命令"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        task_id = args[0] if args else self._focused_task_id
        if not task_id:
            await update.message.reply_text("用法: /report <task_id>（或先 /focus 一个任务）")
            return

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

    async def _on_cd(self, update, context):
        """处理 /cd 命令：设置默认工作目录"""
        if not self._check_auth(update.effective_chat.id):
            await update.message.reply_text("未授权")
            return

        args = context.args
        if not args:
            if self._default_working_dir:
                await update.message.reply_text(
                    f"当前默认目录: {self._default_working_dir}"
                )
            else:
                await update.message.reply_text(
                    "未设置默认目录\n用法: /cd <路径>"
                )
            return

        path = " ".join(args)
        real_path = os.path.realpath(
            os.path.expanduser(path)
        )

        if not os.path.isdir(real_path):
            await update.message.reply_text(f"目录不存在: {real_path}")
            return

        self._default_working_dir = real_path
        await update.message.reply_text(f"默认工作目录已设置: {real_path}")

    async def _on_focus(self, update, context):
        """处理 /focus 命令：查看/切换/取消关注任务"""
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
        status = state.get("status", "")
        error = state.get("error_message", "")

        # 检查 checkpoint 是否存在（用于判断能否自动恢复）
        has_checkpoint = (
            Path("~/.maestro/sessions").expanduser()
            / task_id / "checkpoint.json"
        ).exists()

        # 根据任务状态生成提示
        if status == "failed":
            if has_checkpoint:
                hint = f"\n状态: 失败（{error}）\n直接发消息即可自动恢复任务"
            else:
                hint = f"\n状态: 失败（{error}）\n无 checkpoint，请重新运行任务"
        elif status == "aborted":
            hint = f"\n状态: 已终止\n如需恢复请使用 maestro resume {task_id}"
        elif status == "completed":
            hint = "\n状态: 已完成"
        elif status == "waiting_user":
            if self._is_worker_alive(state):
                hint = "\n状态: 等待你的回复\n直接发消息或 /ask 即可回复"
            elif has_checkpoint:
                hint = "\n状态: 等待回复（进程已退出）\n直接发消息即可自动恢复任务"
            else:
                hint = "\n状态: 等待回复（进程已退出）\n无 checkpoint，请重新运行任务"
        elif status == "executing":
            hint = "\n状态: 执行中"
        else:
            hint = f"\n状态: {status}"

        await update.message.reply_text(
            f"已关注任务 [{task_id}]\n"
            f"需求: {req}\n"
            f"当前进度: Turn {turn}/{max_t}"
            f"{hint}"
        )

    async def _on_message(self, update, context):
        """处理普通消息：回复任务通知 → inbox 路由，focus 死任务 → 自动恢复，其他 → 自由聊天"""
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
                    # 检测是否需要自动恢复
                    resumed = await self._auto_resume_if_needed(task_id, update)
                    if not resumed:
                        await update.message.reply_text(
                            f"已转发到任务 [{task_id}]"
                        )
                return

        # focus 模式下：关注的任务等待回复或已停止时，普通消息视为任务回复
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
                        # 进程存活，消息正常写入 inbox 等待消费
                        await update.message.reply_text(
                            f"已转发到任务 [{task_id}]"
                        )
                    else:
                        # 进程已死，自动恢复
                        resumed = await self._auto_resume_if_needed(task_id, update)
                        if not resumed:
                            await update.message.reply_text(
                                f"消息已记录到任务 [{task_id}]，"
                                f"但自动恢复未成功。\n"
                                f"手动恢复: maestro resume {task_id}"
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
        """定期轮询所有任务状态 + 关注任务的轮次输出"""
        sessions_dir = Path("~/.maestro/sessions").expanduser()
        if not sessions_dir.exists():
            return

        # 先推送关注任务的剩余轮次（确保最后几轮不被状态变更截断）
        if self._focused_task_id:
            await self._push_focused_turns(context)

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

            # 任务恢复后清理防重入标记（包括恢复后直接完成或再次失败的情况）
            if task_id in self._resuming_tasks and current_status in (
                "executing", "completed", "failed", "aborted"
            ):
                self._resuming_tasks.discard(task_id)

            # 检测 Worker 进程健康（同时覆盖 executing 和 waiting_user）
            if current_status in ("executing", "waiting_user") and not self._is_worker_alive(state):
                state["status"] = "failed"
                state["error_message"] = "Worker 进程意外退出"
                state["fail_reason"] = "worker_crashed"
                from maestro.state import atomic_write_json
                atomic_write_json(
                    str(task_dir / "state.json"), state
                )
                self.registry.update_task(
                    task_id, status="failed",
                    fail_reason="worker_crashed",
                )
                if self.config.telegram.chat_id:
                    await context.bot.send_message(
                        chat_id=self.config.telegram.chat_id,
                        text=(
                            f"💥 [{task_id}] Worker 崩溃！\n"
                            f"直接发消息或 /ask 即可自动恢复"
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
                f"✅ [{task_id}] 任务完成！\n"
                f"轮数: {state.get('current_turn', 0)}\n"
                f"费用: ${state.get('total_cost_usd', 0):.2f}\n"
                f"查看报告: /report {task_id}"
            )
        elif new == "failed":
            fail_reason = state.get("fail_reason", "")
            if fail_reason == "ask_user_timeout":
                reason_text = "等待回复超时"
            elif fail_reason == "max_turns":
                turn = state.get("current_turn", "?")
                max_t = state.get("max_turns", "?")
                reason_text = f"已用完所有轮数 ({turn}/{max_t})"
            elif fail_reason == "breaker_tripped":
                reason_text = f"熔断触发: {state.get('error_message', '未知')}"
            elif fail_reason == "worker_crashed":
                reason_text = "Worker 进程崩溃"
            else:
                reason_text = state.get("error_message", "未知")

            # 细分图标
            fail_icons = {
                "ask_user_timeout": "⏰", "max_turns": "🔄",
                "breaker_tripped": "⚡", "blocked": "🚫",
                "worker_crashed": "💥", "runtime_error": "⚠️",
            }
            fail_icon = fail_icons.get(fail_reason, "❌")

            msg = (
                f"{fail_icon} [{task_id}] 任务失败\n"
                f"原因: {reason_text}\n"
                f"恢复: maestro resume {task_id}"
            )
        elif new == "waiting_user":
            msg = (
                f"✋ [{task_id}] 需要你的回复\n"
                f"Manager 思路: {state.get('last_manager_reasoning', '')[:200]}\n\n"
                f"回复: /ask {task_id} <你的回复>"
            )
        elif new == "aborted":
            msg = f"🛑 [{task_id}] 任务已终止"
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

        # 关注任务结束时：先推送剩余轮次，再取消关注
        if task_id == self._focused_task_id and new in (
            "completed", "failed", "aborted"
        ):
            await self._push_focused_turns(context)
            self._focused_task_id = None

    # ============================================================
    # Focus 模式：轮次推送
    # ============================================================

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

        # 构建消息头
        header = f"[{task_id}] Turn {turn}/{max_turns} ({duration_s:.1f}s)"

        # 输出内容（vibing 判断）
        if not output or len(output.strip()) < 20:
            output_section = "Claude Code vibing..."
        else:
            # 截断到 1500 字符（给 header + reasoning + instruction 留空间）
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

    def _init_last_states(self):
        """初始化时预加载所有任务状态，避免重启后重发历史通知"""
        sessions_dir = Path("~/.maestro/sessions").expanduser()
        if not sessions_dir.exists():
            return
        for task_dir in sessions_dir.iterdir():
            if not task_dir.is_dir():
                continue
            task_id = task_dir.name
            state = self._read_state(task_id)
            if state:
                self._last_states[task_id] = state.copy()

    # ============================================================
    # 自动恢复
    # ============================================================

    def _is_worker_alive(self, state: Optional[dict]) -> bool:
        """检测任务的 worker 进程是否存活"""
        if not state:
            return False
        pid = state.get("worker_pid")
        if not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True  # 进程存在但无权限，视为存活

    async def _auto_resume_if_needed(self, task_id: str, update) -> bool:
        """
        检测任务进程是否已死，如果是则自动恢复。

        返回 True 表示已触发恢复，False 表示无需处理。
        """
        state = self._read_state(task_id)
        if not state:
            return False

        status = state.get("status", "")

        # 只对可恢复状态触发
        if status not in ("failed", "waiting_user"):
            return False

        # 进程仍存活则无需恢复
        if self._is_worker_alive(state):
            return False

        # 防重入：避免连续消息触发多次 resume
        if task_id in self._resuming_tasks:
            await update.message.reply_text(
                f"任务 [{task_id}] 正在恢复中，你的消息已排队，请稍候..."
            )
            return True

        self._resuming_tasks.add(task_id)

        # 检查 checkpoint 是否存在
        checkpoint_path = (
            Path("~/.maestro/sessions").expanduser()
            / task_id / "checkpoint.json"
        )
        if not checkpoint_path.exists():
            self._resuming_tasks.discard(task_id)
            await update.message.reply_text(
                f"任务 [{task_id}] 无法恢复（缺少 checkpoint）\n"
                f"请重新运行任务"
            )
            return True  # 已向用户发送了消息，阻止调用方再发"已发送反馈"

        # 启动后台 resume
        try:
            working_dir = state.get("working_dir", os.getcwd())
            _launch_resume_background(
                self.config, task_id, working_dir, self._config_path
            )
            logger.info(
                f"自动恢复任务 [{task_id}] 已启动，工作目录: {working_dir}"
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
        """启动 worker 进程

        Daemon 以 nohup 方式后台运行，没有 TTY，Zellij 无法启动。
        因此 Daemon 始终使用直接 subprocess 模式，日志写入文件。
        用户仍可通过 CLI 的 maestro run（有 TTY）获得 Zellij UI。
        """
        cmd = [
            sys.executable, "-m", "maestro.cli",
            "_worker", task_id, working_dir, requirement,
            "-c", self._config_path,
        ]

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
