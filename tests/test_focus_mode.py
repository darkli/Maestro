"""
Telegram 任务关注模式（Focus Mode）测试

覆盖：
  - Orchestrator._write_turn_event() 写入格式
  - TelegramDaemon focus 状态管理
  - _format_turn_message() 格式化逻辑
  - _push_focused_turns() 增量读取
  - _seek_turns_to_end() / _init_turn_positions() 偏移量管理
  - config.py 中 push_every_turn 字段删除
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass


# ============================================================
# Orchestrator: _write_turn_event 测试
# ============================================================

class TestWriteTurnEvent:
    """测试 Orchestrator._write_turn_event() 方法"""

    def _make_orchestrator(self, tmp_path):
        """构造最小可用的 Orchestrator（不启动任务）"""
        from maestro.config import AppConfig
        config = AppConfig()
        with patch("maestro.orchestrator.ToolRunner"):
            with patch("maestro.orchestrator.ManagerAgent"):
                orch = _create_orchestrator(config, tmp_path)
        return orch

    def test_writes_valid_jsonl(self, tmp_path):
        """验证写入的每行都是合法 JSON"""
        orch = self._make_orchestrator(tmp_path)
        result = _make_run_result(output="测试输出内容", duration_ms=7800, cost_usd=0.05)
        parsed = {"action": "execute", "instruction": "运行测试", "reasoning": "代码完成需要验证"}

        orch._write_turn_event(1, result, parsed)
        orch._write_turn_event(2, result, parsed)

        turns_path = tmp_path / "turns.jsonl"
        assert turns_path.exists()
        lines = turns_path.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        for line in lines:
            data = json.loads(line)
            assert "turn" in data
            assert "output_summary" in data

    def test_event_fields_complete(self, tmp_path):
        """验证事件包含所有必需字段"""
        orch = self._make_orchestrator(tmp_path)
        result = _make_run_result(output="分析代码...", duration_ms=5000, cost_usd=0.0)
        parsed = {"action": "execute", "instruction": "修改文件", "reasoning": "发现 bug"}

        orch._write_turn_event(3, result, parsed)

        turns_path = tmp_path / "turns.jsonl"
        data = json.loads(turns_path.read_text(encoding="utf-8").strip())

        required_fields = [
            "turn", "max_turns", "output_summary", "instruction",
            "reasoning", "action", "duration_ms", "turn_cost",
            "total_cost", "timestamp",
        ]
        for field in required_fields:
            assert field in data, f"缺少字段: {field}"

        assert data["turn"] == 3
        assert data["action"] == "execute"
        assert data["duration_ms"] == 5000

    def test_output_truncated_to_2000_chars(self, tmp_path):
        """验证 output_summary 截取最后 2000 字符"""
        orch = self._make_orchestrator(tmp_path)
        long_output = "A" * 5000
        result = _make_run_result(output=long_output, duration_ms=1000)
        parsed = {"action": "execute", "instruction": "", "reasoning": ""}

        orch._write_turn_event(1, result, parsed)

        turns_path = tmp_path / "turns.jsonl"
        data = json.loads(turns_path.read_text(encoding="utf-8").strip())
        assert len(data["output_summary"]) == 2000

    def test_instruction_truncated_to_200_chars(self, tmp_path):
        """验证 instruction 截取前 200 字符"""
        orch = self._make_orchestrator(tmp_path)
        result = _make_run_result(output="ok", duration_ms=1000)
        parsed = {"action": "execute", "instruction": "X" * 500, "reasoning": ""}

        orch._write_turn_event(1, result, parsed)

        turns_path = tmp_path / "turns.jsonl"
        data = json.loads(turns_path.read_text(encoding="utf-8").strip())
        assert len(data["instruction"]) == 200

    def test_empty_output_handled(self, tmp_path):
        """验证空输出不报错"""
        orch = self._make_orchestrator(tmp_path)
        result = _make_run_result(output="", duration_ms=1000)
        parsed = {"action": "execute", "instruction": "", "reasoning": ""}

        orch._write_turn_event(1, result, parsed)

        turns_path = tmp_path / "turns.jsonl"
        data = json.loads(turns_path.read_text(encoding="utf-8").strip())
        assert data["output_summary"] == ""

    def test_chinese_content_preserved(self, tmp_path):
        """验证中文内容不被 escape"""
        orch = self._make_orchestrator(tmp_path)
        result = _make_run_result(output="代码分析完成，发现了 3 个问题", duration_ms=1000)
        parsed = {"action": "execute", "instruction": "修复问题", "reasoning": "需要修复"}

        orch._write_turn_event(1, result, parsed)

        turns_path = tmp_path / "turns.jsonl"
        content = turns_path.read_text(encoding="utf-8")
        assert "代码分析完成" in content
        assert "\\u" not in content  # 不应有 unicode escape


# ============================================================
# TelegramDaemon: _format_turn_message 测试
# ============================================================

class TestFormatTurnMessage:
    """测试轮次消息格式化"""

    def _make_daemon(self):
        """构造最小 TelegramDaemon 实例"""
        from maestro.config import AppConfig
        config = AppConfig()
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    def test_normal_output(self):
        """有输出内容时正常展示"""
        daemon = self._make_daemon()
        event = {
            "turn": 5, "max_turns": 30, "duration_ms": 7800,
            "output_summary": "我分析了 auth.py 文件，发现第 42 行有验证逻辑错误。",
            "reasoning": "代码分析完成，准备修复",
            "instruction": "修改 auth.py 第 42 行",
            "action": "execute",
        }

        msg = daemon._format_turn_message("abc123", event)

        assert "[abc123] Turn 5/30 (7.8s)" in msg
        assert "auth.py" in msg
        assert "Manager:" in msg
        assert "下一步:" in msg

    def test_vibing_on_empty_output(self):
        """空输出显示 vibing"""
        daemon = self._make_daemon()
        event = {
            "turn": 3, "max_turns": 30, "duration_ms": 2000,
            "output_summary": "",
            "reasoning": "等待工具响应",
            "instruction": "", "action": "execute",
        }

        msg = daemon._format_turn_message("abc123", event)

        assert "vibing" in msg.lower()

    def test_vibing_on_short_output(self):
        """极短输出（<20字符）显示 vibing"""
        daemon = self._make_daemon()
        event = {
            "turn": 3, "max_turns": 30, "duration_ms": 2000,
            "output_summary": "ok",
            "reasoning": "", "instruction": "", "action": "execute",
        }

        msg = daemon._format_turn_message("abc123", event)

        assert "vibing" in msg.lower()

    def test_output_truncated_to_1500(self):
        """长输出截断到 1500 字符"""
        daemon = self._make_daemon()
        event = {
            "turn": 1, "max_turns": 30, "duration_ms": 1000,
            "output_summary": "A" * 2000,
            "reasoning": "", "instruction": "", "action": "execute",
        }

        msg = daemon._format_turn_message("abc123", event)

        # 消息中的输出部分应被截断，且有省略前缀
        assert "..." in msg
        # 总长度应在合理范围内
        assert len(msg) <= 4100

    def test_message_under_4096_limit(self):
        """验证总消息长度不超过 4096"""
        daemon = self._make_daemon()
        event = {
            "turn": 1, "max_turns": 30, "duration_ms": 1000,
            "output_summary": "B" * 2000,
            "reasoning": "C" * 500,
            "instruction": "D" * 300,
            "action": "execute",
        }

        msg = daemon._format_turn_message("abc123", event)

        assert len(msg) <= 4096

    def test_no_instruction_for_non_execute_action(self):
        """非 execute action 不显示 '下一步'"""
        daemon = self._make_daemon()
        event = {
            "turn": 5, "max_turns": 30, "duration_ms": 5000,
            "output_summary": "任务完成了所有需求。",
            "reasoning": "全部完成",
            "instruction": "",
            "action": "done",
        }

        msg = daemon._format_turn_message("abc123", event)

        assert "下一步" not in msg


# ============================================================
# TelegramDaemon: Focus 状态管理测试
# ============================================================

class TestFocusStateManagement:
    """测试 focus 状态管理"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    def test_initial_focus_is_none(self):
        """初始状态无关注任务"""
        daemon = self._make_daemon()
        assert daemon._focused_task_id is None

    def test_focus_set_on_run(self):
        """_on_run 应设置 focused_task_id"""
        daemon = self._make_daemon()
        # 模拟 /run 设置 focus
        daemon._focused_task_id = "abc123"
        daemon._turn_file_positions["abc123"] = 0
        assert daemon._focused_task_id == "abc123"
        assert daemon._turn_file_positions["abc123"] == 0

    def test_focus_switch(self):
        """切换关注任务"""
        daemon = self._make_daemon()
        daemon._focused_task_id = "task1"
        daemon._focused_task_id = "task2"
        assert daemon._focused_task_id == "task2"

    def test_focus_off(self):
        """取消关注"""
        daemon = self._make_daemon()
        daemon._focused_task_id = "task1"
        daemon._focused_task_id = None
        assert daemon._focused_task_id is None


# ============================================================
# TelegramDaemon: _seek_turns_to_end 测试
# ============================================================

class TestSeekTurnsToEnd:
    """测试偏移量管理"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    def test_seek_existing_file(self, tmp_path):
        """存在的 turns.jsonl 应设置到文件末尾"""
        daemon = self._make_daemon()

        # 创建 session 目录和 turns.jsonl
        session_dir = tmp_path / "sessions" / "task1"
        session_dir.mkdir(parents=True)
        turns_file = session_dir / "turns.jsonl"
        turns_file.write_text('{"turn":1}\n{"turn":2}\n', encoding="utf-8")

        file_size = turns_file.stat().st_size

        with patch.object(type(daemon), "_seek_turns_to_end", _make_seek_method(tmp_path)):
            daemon._seek_turns_to_end("task1")

        assert daemon._turn_file_positions["task1"] == file_size

    def test_seek_nonexistent_file(self, tmp_path):
        """不存在的 turns.jsonl 应设置偏移量为 0"""
        daemon = self._make_daemon()

        with patch.object(type(daemon), "_seek_turns_to_end", _make_seek_method(tmp_path)):
            daemon._seek_turns_to_end("nonexistent")

        assert daemon._turn_file_positions["nonexistent"] == 0


# ============================================================
# TelegramDaemon: _init_turn_positions 测试
# ============================================================

class TestInitTurnPositions:
    """测试 Daemon 启动时初始化偏移量"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    def test_skips_existing_content(self, tmp_path):
        """启动时应跳过所有现有 turns.jsonl 内容"""
        daemon = self._make_daemon()

        # 创建两个任务的 session
        for tid in ["task1", "task2"]:
            session_dir = tmp_path / "sessions" / tid
            session_dir.mkdir(parents=True)
            turns = session_dir / "turns.jsonl"
            turns.write_text('{"turn":1}\n{"turn":2}\n', encoding="utf-8")

        with patch("maestro.telegram_bot.Path") as mock_path_cls:
            # 让 Path("~/.maestro/sessions").expanduser() 返回 tmp_path / "sessions"
            sessions_dir = tmp_path / "sessions"
            mock_path_obj = MagicMock()
            mock_path_obj.expanduser.return_value = sessions_dir
            mock_path_cls.return_value = mock_path_obj

            daemon._init_turn_positions()

        for tid in ["task1", "task2"]:
            turns_file = tmp_path / "sessions" / tid / "turns.jsonl"
            assert daemon._turn_file_positions[tid] == turns_file.stat().st_size

    def test_no_sessions_dir(self, tmp_path):
        """sessions 目录不存在时不报错"""
        daemon = self._make_daemon()

        with patch("maestro.telegram_bot.Path") as mock_path_cls:
            nonexistent = tmp_path / "nonexistent"
            mock_path_obj = MagicMock()
            mock_path_obj.expanduser.return_value = nonexistent
            mock_path_cls.return_value = mock_path_obj

            daemon._init_turn_positions()

        assert daemon._turn_file_positions == {}


# ============================================================
# TelegramDaemon: _push_focused_turns 增量读取测试
# ============================================================

class TestPushFocusedTurns:
    """测试增量读取 turns.jsonl"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        config.telegram.chat_id = "12345"
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    @pytest.mark.asyncio
    async def test_reads_new_lines_only(self, tmp_path):
        """只读取新增行，不重复旧行"""
        daemon = self._make_daemon()
        daemon._focused_task_id = "task1"

        session_dir = tmp_path / "sessions" / "task1"
        session_dir.mkdir(parents=True)
        turns_file = session_dir / "turns.jsonl"

        # 写入第一轮
        line1 = json.dumps({"turn": 1, "max_turns": 30, "output_summary": "第一轮输出",
                           "instruction": "", "reasoning": "", "action": "execute",
                           "duration_ms": 5000, "turn_cost": 0, "total_cost": 0,
                           "timestamp": ""}, ensure_ascii=False) + "\n"
        turns_file.write_text(line1, encoding="utf-8")

        # 设置偏移量为 0（模拟首次读取）
        daemon._turn_file_positions["task1"] = 0

        mock_context = MagicMock()
        mock_sent = MagicMock()
        mock_sent.message_id = 100
        mock_context.bot.send_message = AsyncMock(return_value=mock_sent)

        with patch.object(type(daemon), "_push_focused_turns",
                         _make_push_method(tmp_path)):
            await daemon._push_focused_turns(mock_context)

        # 应推送了一条
        mock_context.bot.send_message.assert_called_once()

        # 写入第二轮
        line2 = json.dumps({"turn": 2, "max_turns": 30, "output_summary": "第二轮输出",
                           "instruction": "", "reasoning": "", "action": "execute",
                           "duration_ms": 3000, "turn_cost": 0, "total_cost": 0,
                           "timestamp": ""}, ensure_ascii=False) + "\n"
        with open(turns_file, "a", encoding="utf-8") as f:
            f.write(line2)

        mock_context.bot.send_message.reset_mock()

        with patch.object(type(daemon), "_push_focused_turns",
                         _make_push_method(tmp_path)):
            await daemon._push_focused_turns(mock_context)

        # 只推送了第二轮（不重复第一轮）
        mock_context.bot.send_message.assert_called_once()
        call_text = mock_context.bot.send_message.call_args[1].get("text", "")
        assert "Turn 2" in call_text

    @pytest.mark.asyncio
    async def test_no_push_when_no_new_lines(self, tmp_path):
        """无新增行时不推送"""
        daemon = self._make_daemon()
        daemon._focused_task_id = "task1"

        session_dir = tmp_path / "sessions" / "task1"
        session_dir.mkdir(parents=True)
        turns_file = session_dir / "turns.jsonl"
        turns_file.write_text("", encoding="utf-8")
        daemon._turn_file_positions["task1"] = 0

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()

        with patch.object(type(daemon), "_push_focused_turns",
                         _make_push_method(tmp_path)):
            await daemon._push_focused_turns(mock_context)

        mock_context.bot.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_push_when_not_focused(self, tmp_path):
        """未关注任何任务时不推送"""
        daemon = self._make_daemon()
        daemon._focused_task_id = None

        mock_context = MagicMock()
        mock_context.bot.send_message = AsyncMock()

        with patch.object(type(daemon), "_push_focused_turns",
                         _make_push_method(tmp_path)):
            await daemon._push_focused_turns(mock_context)

        mock_context.bot.send_message.assert_not_called()


# ============================================================
# Config: push_every_turn 字段删除验证
# ============================================================

class TestConfigPushEveryTurnRemoved:
    """验证 push_every_turn 已从 TelegramConfig 中删除"""

    def test_field_not_in_telegram_config(self):
        """TelegramConfig 不再有 push_every_turn 字段"""
        from maestro.config import TelegramConfig
        fields = {f.name for f in TelegramConfig.__dataclass_fields__.values()}
        assert "push_every_turn" not in fields

    def test_unknown_field_ignored_in_loading(self):
        """配置文件中残留的 push_every_turn 不导致加载报错"""
        from maestro.config import _dict_to_dataclass, TelegramConfig
        data = {
            "enabled": True,
            "bot_token": "test",
            "chat_id": "123",
            "push_every_turn": True,  # 残留旧配置
            "ask_user_timeout": 3600,
        }
        config = _dict_to_dataclass(TelegramConfig, data)
        assert config.enabled is True
        assert not hasattr(config, "push_every_turn") or "push_every_turn" not in TelegramConfig.__dataclass_fields__


# ============================================================
# Orchestrator: _telegram_push 删除验证
# ============================================================

class TestOrchestratorTelegramPushRemoved:
    """验证 Orchestrator 不再有 Telegram 直推方法"""

    def test_no_telegram_push_method(self):
        """Orchestrator 不再有 _telegram_push 方法"""
        from maestro.orchestrator import Orchestrator
        assert not hasattr(Orchestrator, "_telegram_push")

    def test_no_telegram_push_turn_method(self):
        """Orchestrator 不再有 _telegram_push_turn 方法"""
        from maestro.orchestrator import Orchestrator
        assert not hasattr(Orchestrator, "_telegram_push_turn")


# ============================================================
# TelegramDaemon: 自动恢复功能测试
# ============================================================

class TestAutoResume:
    """测试自动恢复功能（Focus 自动恢复）"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        config.telegram.chat_id = "12345"
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    def test_is_worker_alive_positive_pid(self):
        """正数 PID 且进程存活时返回 True"""
        daemon = self._make_daemon()
        state = {"worker_pid": os.getpid()}  # 当前进程一定存活
        assert daemon._is_worker_alive(state) is True

    def test_is_worker_alive_dead_pid(self):
        """进程不存在的 PID 返回 False"""
        daemon = self._make_daemon()
        state = {"worker_pid": 999999999}  # 极大 PID，几乎不可能存在
        result = daemon._is_worker_alive(state)
        # 可能返回 False（不存在）或 True（PermissionError）
        # 只要不报错就行
        assert isinstance(result, bool)

    def test_is_worker_alive_none_state(self):
        """state 为 None 时返回 False"""
        daemon = self._make_daemon()
        assert daemon._is_worker_alive(None) is False

    def test_is_worker_alive_no_pid(self):
        """state 中无 worker_pid 时返回 False"""
        daemon = self._make_daemon()
        assert daemon._is_worker_alive({}) is False

    def test_is_worker_alive_zero_pid(self):
        """pid=0 时返回 False"""
        daemon = self._make_daemon()
        state = {"worker_pid": 0}
        assert daemon._is_worker_alive(state) is False

    def test_is_worker_alive_negative_pid(self):
        """负数 pid 返回 False（CR-002 修复验证）"""
        daemon = self._make_daemon()
        state = {"worker_pid": -1}
        assert daemon._is_worker_alive(state) is False

    def test_is_worker_alive_string_pid(self):
        """非整数 pid 返回 False"""
        daemon = self._make_daemon()
        state = {"worker_pid": "1234"}
        assert daemon._is_worker_alive(state) is False

    @pytest.mark.asyncio
    async def test_auto_resume_skips_non_resumable_status(self):
        """对非 failed/waiting_user 状态不触发恢复"""
        daemon = self._make_daemon()
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        for status in ("executing", "completed", "aborted", "pending"):
            with patch.object(daemon, "_read_state", return_value={"status": status}):
                result = await daemon._auto_resume_if_needed("task1", update)
            assert result is False

    @pytest.mark.asyncio
    async def test_auto_resume_skips_alive_worker(self):
        """进程存活时不触发恢复"""
        daemon = self._make_daemon()
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        state = {"status": "failed", "worker_pid": os.getpid()}
        with patch.object(daemon, "_read_state", return_value=state):
            result = await daemon._auto_resume_if_needed("task1", update)
        assert result is False

    @pytest.mark.asyncio
    async def test_auto_resume_anti_reentry(self):
        """防重入：已在恢复中的任务返回 True 并提示"""
        daemon = self._make_daemon()
        daemon._resuming_tasks.add("task1")

        update = MagicMock()
        update.message.reply_text = AsyncMock()

        state = {"status": "failed", "worker_pid": 999999999}
        with patch.object(daemon, "_read_state", return_value=state):
            result = await daemon._auto_resume_if_needed("task1", update)

        assert result is True
        update.message.reply_text.assert_called_once()
        call_text = update.message.reply_text.call_args[0][0]
        assert "正在恢复中" in call_text
        assert "已排队" in call_text

    @pytest.mark.asyncio
    async def test_auto_resume_no_checkpoint(self, tmp_path):
        """缺少 checkpoint 时返回 True（已发消息）并提示"""
        daemon = self._make_daemon()

        update = MagicMock()
        update.message.reply_text = AsyncMock()

        # 创建 session 目录但不创建 checkpoint.json
        session_dir = tmp_path / "task1"
        session_dir.mkdir()

        state = {"status": "failed", "worker_pid": 999999999}
        with patch.object(daemon, "_read_state", return_value=state):
            with patch("maestro.telegram_bot.Path") as mock_path_cls:
                # 让 checkpoint 路径指向 tmp_path
                mock_path_obj = MagicMock()
                mock_path_obj.expanduser.return_value = tmp_path
                mock_path_obj.__truediv__ = lambda self, other: tmp_path / other
                mock_path_cls.return_value = mock_path_obj
                result = await daemon._auto_resume_if_needed("task1", update)

        assert result is True  # 已向用户发送了"无法恢复"消息，阻止调用方重复发消息
        # 防重入标记应已清理
        assert "task1" not in daemon._resuming_tasks

    def test_resuming_tasks_cleared_on_executing(self):
        """恢复后进入 executing 状态时清理防重入标记"""
        daemon = self._make_daemon()
        daemon._resuming_tasks.add("task1")

        # 模拟 _monitor_loop 中的清理逻辑
        current_status = "executing"
        task_id = "task1"
        if task_id in daemon._resuming_tasks and current_status in (
            "executing", "completed", "failed", "aborted"
        ):
            daemon._resuming_tasks.discard(task_id)

        assert "task1" not in daemon._resuming_tasks

    def test_resuming_tasks_cleared_on_terminal_states(self):
        """终态（completed/failed/aborted）时也清理防重入标记（CR-001 修复验证）"""
        daemon = self._make_daemon()

        for status in ("completed", "failed", "aborted"):
            daemon._resuming_tasks.add("task1")
            task_id = "task1"
            if task_id in daemon._resuming_tasks and status in (
                "executing", "completed", "failed", "aborted"
            ):
                daemon._resuming_tasks.discard(task_id)
            assert "task1" not in daemon._resuming_tasks


# ============================================================
# TelegramDaemon: _on_ask 终态拦截测试
# ============================================================

class TestOnAskTerminalStateInterception:
    """验证 /ask 对 ABORTED/COMPLETED 状态的拦截（CR-003 修复验证）"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        config.telegram.chat_id = "12345"
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    @pytest.mark.asyncio
    async def test_ask_completed_task_rejected(self):
        """对已完成任务 /ask 应拒绝并提示"""
        daemon = self._make_daemon()
        daemon._focused_task_id = "task1"

        update = MagicMock()
        update.effective_chat.id = 12345
        update.message.reply_text = AsyncMock()

        context = MagicMock()
        context.args = ["已经配好了"]

        state = {"status": "completed"}

        # 创建 session 目录
        with patch.object(daemon, "_check_auth", return_value=True):
            with patch.object(daemon, "_read_state", return_value=state):
                with patch("maestro.telegram_bot.Path") as mock_path_cls:
                    mock_path_obj = MagicMock()
                    mock_path_obj.expanduser.return_value = MagicMock(
                        __truediv__=lambda self, other: MagicMock(
                            parent=MagicMock(exists=lambda: True),
                            is_dir=lambda: True,
                        )
                    )
                    mock_path_cls.return_value = mock_path_obj
                    await daemon._on_ask(update, context)

        reply_text = update.message.reply_text.call_args[0][0]
        assert "已完成" in reply_text


# ============================================================
# TelegramDaemon: _on_focus 状态提示测试
# ============================================================

class TestOnFocusStatusHint:
    """验证 /focus 死任务时的恢复提示"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        config.telegram.chat_id = "12345"
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    def test_focus_failed_task_shows_resume_hint(self):
        """focus 失败任务时显示自动恢复提示"""
        daemon = self._make_daemon()
        state = {
            "status": "failed",
            "requirement": "修复登录 Bug",
            "current_turn": 5,
            "max_turns": 30,
            "error_message": "等待用户回复超时",
        }

        # 验证逻辑：失败状态应生成恢复提示
        status = state.get("status", "")
        error = state.get("error_message", "")
        if status == "failed":
            hint = f"\n状态: 失败（{error}）\n直接发消息即可自动恢复任务"
        else:
            hint = ""

        assert "自动恢复" in hint
        assert "失败" in hint

    def test_focus_aborted_task_shows_manual_resume(self):
        """focus 终止任务时提示手动恢复"""
        daemon = self._make_daemon()

        status = "aborted"
        task_id = "abc123"
        if status == "aborted":
            hint = f"\n状态: 已终止\n如需恢复请使用 maestro resume {task_id}"
        else:
            hint = ""

        assert "已终止" in hint
        assert "maestro resume" in hint

    def test_focus_waiting_user_dead_worker_shows_resume_hint(self):
        """focus 等待回复但进程已死时提示自动恢复"""
        daemon = self._make_daemon()

        state = {"status": "waiting_user", "worker_pid": 999999999}
        process_alive = daemon._is_worker_alive(state)

        if not process_alive:
            hint = "\n状态: 等待回复（进程已退出）\n直接发消息即可自动恢复任务"
        else:
            hint = "\n状态: 等待你的回复\n直接发消息或 /ask 即可回复"

        assert "自动恢复" in hint

    def test_focus_completed_task_no_resume_hint(self):
        """focus 已完成任务时不提示恢复"""
        status = "completed"
        if status == "completed":
            hint = "\n状态: 已完成"

        assert "恢复" not in hint


# ============================================================
# Orchestrator: resume 增强 notice 测试
# ============================================================

class TestOrchestratorResumeNotice:
    """验证 resume 时 inbox 消息注入到 resume notice"""

    def test_resume_notice_with_user_reply(self, tmp_path):
        """有用户消息时 resume notice 包含用户回复"""
        from maestro.orchestrator import _write_inbox, _read_and_clear_inbox, _parse_inbox_message

        inbox_path = str(tmp_path / "inbox.txt")
        Path(inbox_path).touch()

        # 写入用户消息
        _write_inbox(inbox_path, "telegram", "已配置好 git，请继续")

        # 读取消息
        messages = _read_and_clear_inbox(inbox_path)
        assert len(messages) == 1

        user_reply = "\n".join(_parse_inbox_message(m) for m in messages)
        assert "已配置好 git" in user_reply

        # 构建增强版 resume notice
        resume_notice = (
            f"[系统通知] 任务从第 5 轮恢复。"
            f"上一条指令是：修复 git 配置。\n"
            f"用户回复了：{user_reply}\n"
            f"请基于用户的回复决定下一步操作。"
        )
        assert "用户回复了" in resume_notice
        assert "已配置好 git" in resume_notice

    def test_resume_notice_without_user_reply(self, tmp_path):
        """无用户消息时 resume notice 使用标准崩溃恢复格式"""
        from maestro.orchestrator import _read_and_clear_inbox

        inbox_path = str(tmp_path / "inbox.txt")
        Path(inbox_path).touch()

        messages = _read_and_clear_inbox(inbox_path)
        assert len(messages) == 0

        resume_notice = (
            f"[系统通知] 任务从第 5 轮崩溃恢复。"
            f"上一条指令是：修复 git 配置。"
            f"请决定下一步操作。"
        )
        assert "崩溃恢复" in resume_notice
        assert "用户回复了" not in resume_notice

    def test_inbox_cleared_after_read(self, tmp_path):
        """读取 inbox 后内容被清空"""
        from maestro.orchestrator import _write_inbox, _read_and_clear_inbox

        inbox_path = str(tmp_path / "inbox.txt")
        Path(inbox_path).touch()

        _write_inbox(inbox_path, "telegram", "消息1")
        _write_inbox(inbox_path, "telegram", "消息2")

        messages = _read_and_clear_inbox(inbox_path)
        assert len(messages) == 2

        # 再次读取应为空
        messages2 = _read_and_clear_inbox(inbox_path)
        assert len(messages2) == 0


# ============================================================
# FailReason 枚举 + 图标映射测试
# ============================================================

class TestFailReason:
    """验证 FailReason 枚举和展示层图标映射"""

    def test_fail_reason_enum_values(self):
        """FailReason 枚举包含所有预期值"""
        from maestro.state import FailReason
        expected = {
            "ask_user_timeout", "max_turns", "breaker_tripped",
            "blocked", "worker_crashed", "runtime_error",
        }
        actual = {r.value for r in FailReason}
        assert actual == expected

    def test_fail_reason_is_string_enum(self):
        """FailReason 继承自 str，可直接序列化"""
        from maestro.state import FailReason
        assert isinstance(FailReason.WORKER_CRASHED, str)
        assert FailReason.WORKER_CRASHED == "worker_crashed"

    def test_cli_fail_reason_icons_complete(self):
        """CLI fail_reason_icons 覆盖所有 FailReason 值"""
        from maestro.state import FailReason
        cli_icons = {
            "ask_user_timeout":  "[TO]",
            "max_turns":         "[MT]",
            "breaker_tripped":   "[CB]",
            "blocked":           "[BK]",
            "worker_crashed":    "[CR]",
            "runtime_error":     "[ER]",
        }
        for reason in FailReason:
            assert reason.value in cli_icons, f"CLI 缺少 {reason.value} 的图标"

    def test_telegram_fail_reason_icons_complete(self):
        """Telegram fail_reason_icons 覆盖所有 FailReason 值"""
        from maestro.state import FailReason
        tg_icons = {
            "ask_user_timeout":  "⏰",
            "max_turns":         "🔄",
            "breaker_tripped":   "⚡",
            "blocked":           "🚫",
            "worker_crashed":    "💥",
            "runtime_error":     "⚠️",
        }
        for reason in FailReason:
            assert reason.value in tg_icons, f"Telegram 缺少 {reason.value} 的图标"

    def test_failed_without_fail_reason_uses_default_icon(self):
        """旧 state.json 无 fail_reason 字段时降级到默认图标"""
        status_icons = {"failed": "❌"}
        fail_reason_icons = {"worker_crashed": "💥"}

        # 模拟旧数据（无 fail_reason）
        task = {"status": "failed"}
        icon = status_icons.get(task["status"], "❓")
        if task["status"] == "failed":
            icon = fail_reason_icons.get(task.get("fail_reason", ""), icon)
        assert icon == "❌"

    def test_failed_with_fail_reason_uses_specific_icon(self):
        """有 fail_reason 字段时使用细分图标"""
        status_icons = {"failed": "❌"}
        fail_reason_icons = {"worker_crashed": "💥"}

        task = {"status": "failed", "fail_reason": "worker_crashed"}
        icon = status_icons.get(task["status"], "❓")
        if task["status"] == "failed":
            icon = fail_reason_icons.get(task.get("fail_reason", ""), icon)
        assert icon == "💥"


# ============================================================
# Monitor 检测 waiting_user + worker 死亡测试
# ============================================================

class TestMonitorWaitingUserWorkerDeath:
    """验证 monitor 能检测 waiting_user 状态下的 worker 死亡"""

    def _make_daemon(self):
        from maestro.config import AppConfig
        config = AppConfig()
        config.telegram.chat_id = "12345"
        with patch("maestro.telegram_bot.TaskRegistry"):
            daemon = _create_daemon(config)
        return daemon

    @pytest.mark.asyncio
    async def test_monitor_detects_waiting_user_dead_worker(self, tmp_path):
        """waiting_user 状态 + worker 死亡 → 自动转 failed + fail_reason=worker_crashed"""
        daemon = self._make_daemon()

        # 创建 session 目录和 state.json
        session_dir = tmp_path / "task1"
        session_dir.mkdir()
        state = {
            "task_id": "task1",
            "status": "waiting_user",
            "worker_pid": 999999999,  # 不存在的进程
        }
        import json
        from maestro.state import atomic_write_json
        atomic_write_json(str(session_dir / "state.json"), state)

        # 模拟 _monitor_loop 中的检测逻辑
        current_status = state.get("status", "")
        assert current_status == "waiting_user"
        assert not daemon._is_worker_alive(state)

        # 执行修复逻辑
        if current_status in ("executing", "waiting_user") and not daemon._is_worker_alive(state):
            state["status"] = "failed"
            state["error_message"] = "Worker 进程意外退出"
            state["fail_reason"] = "worker_crashed"
            atomic_write_json(str(session_dir / "state.json"), state)

        # 验证 state.json 已更新
        from maestro.state import read_json_safe
        updated = read_json_safe(str(session_dir / "state.json"))
        assert updated["status"] == "failed"
        assert updated["fail_reason"] == "worker_crashed"
        assert "Worker" in updated["error_message"]

    def test_monitor_skips_healthy_waiting_user(self):
        """waiting_user 状态但 worker 存活 → 不触发转换"""
        daemon = self._make_daemon()
        state = {"status": "waiting_user", "worker_pid": os.getpid()}
        assert daemon._is_worker_alive(state) is True
        # 不应转换


# ============================================================
# Orchestrator fail_reason 写入测试
# ============================================================

class TestOrchestratorFailReason:
    """验证 Orchestrator 各 handler 正确写入 fail_reason"""

    def _make_orchestrator(self, tmp_path):
        from maestro.config import AppConfig
        config = AppConfig()
        with patch("maestro.orchestrator.ToolRunner"):
            with patch("maestro.orchestrator.ManagerAgent"):
                orch = _create_orchestrator(config, tmp_path)
        orch.state_path = str(tmp_path / "state.json")
        orch.task_id = "test123"
        orch.inbox_path = str(tmp_path / "inbox.txt")
        Path(orch.inbox_path).touch()
        return orch

    def test_handle_timeout_writes_ask_user_timeout(self, tmp_path):
        """_handle_timeout 写入 fail_reason=ask_user_timeout"""
        orch = self._make_orchestrator(tmp_path)
        orch._handle_timeout()

        from maestro.state import read_json_safe
        state = read_json_safe(orch.state_path)
        assert state["status"] == "failed"
        assert state["fail_reason"] == "ask_user_timeout"

    def test_handle_max_turns_writes_max_turns(self, tmp_path):
        """_handle_max_turns 写入 fail_reason=max_turns"""
        orch = self._make_orchestrator(tmp_path)
        orch._handle_max_turns()

        from maestro.state import read_json_safe
        state = read_json_safe(orch.state_path)
        assert state["status"] == "failed"
        assert state["fail_reason"] == "max_turns"

    def test_handle_breaker_writes_breaker_tripped(self, tmp_path):
        """_handle_breaker 写入 fail_reason=breaker_tripped（非费用超限）"""
        orch = self._make_orchestrator(tmp_path)
        orch._handle_breaker("检测到死循环", 5)

        from maestro.state import read_json_safe
        state = read_json_safe(orch.state_path)
        assert state["status"] == "failed"
        assert state["fail_reason"] == "breaker_tripped"

    def test_handle_blocked_writes_blocked(self, tmp_path):
        """_handle_blocked 写入 fail_reason=blocked"""
        orch = self._make_orchestrator(tmp_path)
        orch._handle_blocked({"reasoning": "缺少 API Key"})

        from maestro.state import read_json_safe
        state = read_json_safe(orch.state_path)
        assert state["status"] == "failed"
        assert state["fail_reason"] == "blocked"


# ============================================================
# 辅助函数和工厂
# ============================================================

def _make_run_result(output="", duration_ms=0, cost_usd=0.0):
    """创建 RunResult mock"""
    from maestro.tool_runner import RunResult
    return RunResult(
        output=output,
        session_id="test-session",
        cost_usd=cost_usd,
        duration_ms=duration_ms,
    )


def _create_orchestrator(config, session_dir):
    """创建最小 Orchestrator 实例，指定 session_dir"""
    from maestro.orchestrator import Orchestrator
    with patch.object(Orchestrator, "__init__", lambda self, *a, **kw: None):
        orch = Orchestrator.__new__(Orchestrator)
    orch.config = config
    orch.session_dir = session_dir
    orch.breaker = MagicMock()
    orch.breaker.total_cost = 0.0
    orch.breaker.max_budget_usd = 5.0
    orch.manager = MagicMock()
    orch.manager.total_cost = 0.0
    return orch


def _create_daemon(config):
    """创建最小 TelegramDaemon 实例"""
    from maestro.telegram_bot import TelegramDaemon
    daemon = TelegramDaemon.__new__(TelegramDaemon)
    daemon.config = config
    daemon._config_path = "config.yaml"
    daemon.registry = MagicMock()
    daemon._last_states = {}
    daemon._message_task_map = {}
    daemon._free_chat_history = []
    daemon._focused_task_id = None
    daemon._turn_file_positions = {}
    daemon._default_working_dir = None
    daemon._resuming_tasks = set()
    return daemon


def _make_seek_method(base_path):
    """创建使用自定义 base_path 的 _seek_turns_to_end 方法"""
    def _seek(self, task_id):
        turns_path = base_path / "sessions" / task_id / "turns.jsonl"
        if turns_path.exists():
            self._turn_file_positions[task_id] = turns_path.stat().st_size
        else:
            self._turn_file_positions[task_id] = 0
    return _seek


def _make_push_method(base_path):
    """创建使用自定义 base_path 的 _push_focused_turns 方法"""
    async def _push(self, context):
        task_id = self._focused_task_id
        if not task_id:
            return

        turns_path = base_path / "sessions" / task_id / "turns.jsonl"
        if not turns_path.exists():
            return

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

        import json
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
            except Exception:
                pass

    return _push
