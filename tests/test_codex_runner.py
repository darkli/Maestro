"""
Codex CLI 模式单元测试

覆盖：
  - CodingToolConfig type="codex" 构造（含 Codex 专用字段）
  - ToolRunner.run() 路由到 _run_codex()
  - _run_codex() 命令构建（首轮 / 后续轮 / auto_approve / Codex 参数）
  - _parse_codex_jsonl() 解析：正常 / 空行 / 无结果降级 / turn.failed / 多 agent_message
  - _estimate_codex_cost() 费用估算（模型感知定价）
  - resume_session() 在 codex 模式下的行为
  - command_not_found 错误处理
"""

import json
import pytest
from unittest.mock import MagicMock, patch, call

from maestro.tool_runner import (
    ToolRunner,
    RunResult,
    EVENT_TOOL_STARTED,
    EVENT_TOOL_OUTPUT_CHUNK,
    EVENT_TOOL_COMPLETED,
    EVENT_ERROR,
)
from maestro.config import CodingToolConfig


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def codex_config():
    """Codex 模式的 CodingToolConfig"""
    return CodingToolConfig(type="codex", command="codex", timeout=60, auto_approve=True)


@pytest.fixture
def codex_config_no_approve():
    """Codex 模式，auto_approve=False"""
    return CodingToolConfig(type="codex", command="codex", timeout=60, auto_approve=False)


@pytest.fixture
def codex_runner(codex_config, tmp_path):
    """创建 Codex 模式的 ToolRunner 实例"""
    return ToolRunner(config=codex_config, working_dir=str(tmp_path))


@pytest.fixture
def codex_runner_no_approve(codex_config_no_approve, tmp_path):
    """创建 auto_approve=False 的 Codex ToolRunner"""
    return ToolRunner(config=codex_config_no_approve, working_dir=str(tmp_path))


# ============================================================
# CodingToolConfig 构造测试
# ============================================================

class TestCodexConfig:
    """验证 CodingToolConfig type=codex 的构造"""

    def test_codex_config_type(self, codex_config):
        """type 字段为 'codex'"""
        assert codex_config.type == "codex"

    def test_codex_config_command(self, codex_config):
        """command 字段为 'codex'"""
        assert codex_config.command == "codex"

    def test_codex_config_auto_approve(self, codex_config):
        """auto_approve 默认 True"""
        assert codex_config.auto_approve is True

    def test_codex_config_timeout(self, codex_config):
        """timeout 字段正常"""
        assert codex_config.timeout == 60

    def test_codex_config_sandbox_default(self):
        """sandbox 字段默认为空"""
        config = CodingToolConfig(type="codex")
        assert config.sandbox == ""

    def test_codex_config_model_default(self):
        """model 字段默认为空"""
        config = CodingToolConfig(type="codex")
        assert config.model == ""

    def test_codex_config_skip_git_check_default(self):
        """skip_git_check 字段默认为 False"""
        config = CodingToolConfig(type="codex")
        assert config.skip_git_check is False

    def test_codex_config_all_fields(self):
        """所有 Codex 专用字段可正常设置"""
        config = CodingToolConfig(
            type="codex", command="codex",
            sandbox="net-disabled", model="o4-mini",
            skip_git_check=True,
        )
        assert config.sandbox == "net-disabled"
        assert config.model == "o4-mini"
        assert config.skip_git_check is True


# ============================================================
# run() 路由测试
# ============================================================

class TestRunRouting:
    """验证 run() 在 type=codex 时路由到 _run_codex()"""

    def test_run_routes_to_codex(self, codex_runner):
        """type=codex 时调用 _run_codex()"""
        with patch.object(codex_runner, '_run_codex', return_value=RunResult(output="测试")) as mock:
            codex_runner.run("测试指令")
            mock.assert_called_once_with("测试指令", None)

    def test_run_routes_to_codex_with_callback(self, codex_runner):
        """type=codex 时，on_event 回调正确传递"""
        callback = MagicMock()
        with patch.object(codex_runner, '_run_codex', return_value=RunResult(output="测试")) as mock:
            codex_runner.run("测试指令", on_event=callback)
            mock.assert_called_once_with("测试指令", callback)

    def test_run_resets_aborted_flag_for_codex(self, codex_runner):
        """run() 开头重置 _aborted 标记"""
        codex_runner._aborted = True
        with patch.object(codex_runner, '_run_codex', return_value=RunResult(output="测试")):
            codex_runner.run("测试")
            assert codex_runner._aborted is False


# ============================================================
# _run_codex() 命令构建测试
# ============================================================

class TestRunCodexCommandBuild:
    """验证 _run_codex() 构建的命令行参数"""

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_first_run_command(self, mock_popen, codex_runner):
        """首轮执行：codex exec --json --full-auto '<instruction>'"""
        # 模拟进程
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        codex_runner._run_codex("实现用户登录功能")

        # 检查命令行参数
        cmd = mock_popen.call_args[0][0]
        assert cmd[0] == "codex"
        assert cmd[1] == "exec"
        assert "--json" in cmd
        assert "--full-auto" in cmd
        assert "resume" not in cmd
        assert cmd[-1] == "实现用户登录功能"

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_resume_command(self, mock_popen, codex_runner):
        """后续轮次：codex exec --json --full-auto resume <session_id> '<instruction>'"""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        codex_runner.session_id = "0199a213-81c0-7800-8aa1-bbab2a035a53"
        codex_runner._run_codex("继续修改")

        cmd = mock_popen.call_args[0][0]
        assert "resume" in cmd
        resume_idx = cmd.index("resume")
        assert cmd[resume_idx + 1] == "0199a213-81c0-7800-8aa1-bbab2a035a53"
        assert cmd[-1] == "继续修改"

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_no_full_auto_when_auto_approve_false(self, mock_popen, codex_runner_no_approve):
        """auto_approve=False 时不添加 --full-auto"""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        codex_runner_no_approve._run_codex("测试")

        cmd = mock_popen.call_args[0][0]
        assert "--full-auto" not in cmd

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_sandbox_flag_in_command(self, mock_popen, tmp_path):
        """sandbox 配置映射到 --sandbox 参数"""
        config = CodingToolConfig(type="codex", command="codex", timeout=60,
                                  auto_approve=True, sandbox="net-disabled")
        runner = ToolRunner(config=config, working_dir=str(tmp_path))

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        runner._run_codex("测试")
        cmd = mock_popen.call_args[0][0]
        assert "--sandbox" in cmd
        idx = cmd.index("--sandbox")
        assert cmd[idx + 1] == "net-disabled"

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_model_flag_in_command(self, mock_popen, tmp_path):
        """model 配置映射到 --model 参数"""
        config = CodingToolConfig(type="codex", command="codex", timeout=60,
                                  auto_approve=False, model="o4-mini")
        runner = ToolRunner(config=config, working_dir=str(tmp_path))

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        runner._run_codex("测试")
        cmd = mock_popen.call_args[0][0]
        assert "--model" in cmd
        idx = cmd.index("--model")
        assert cmd[idx + 1] == "o4-mini"

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_skip_git_check_flag_in_command(self, mock_popen, tmp_path):
        """skip_git_check=True 映射到 --skip-git-check 参数"""
        config = CodingToolConfig(type="codex", command="codex", timeout=60,
                                  auto_approve=True, skip_git_check=True)
        runner = ToolRunner(config=config, working_dir=str(tmp_path))

        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        runner._run_codex("测试")
        cmd = mock_popen.call_args[0][0]
        assert "--skip-git-check" in cmd

    def test_command_not_found(self, codex_runner):
        """codex 命令不存在时返回 command_not_found 错误"""
        # 使用不存在的命令
        codex_runner.config.command = "/nonexistent/codex_binary"
        result = codex_runner._run_codex("测试")

        assert result.is_error is True
        assert result.error_type == "command_not_found"
        assert "找不到命令" in result.output


# ============================================================
# _parse_codex_jsonl() 解析测试
# ============================================================

class TestParseCodexJsonl:
    """验证 _parse_codex_jsonl() 对 Codex CLI JSONL 输出的解析"""

    def _make_lines(self, *objs):
        """辅助：将多个 dict 转为 JSON 行列表"""
        return [json.dumps(obj) + "\n" for obj in objs]

    def test_parse_normal_codex_output(self, codex_runner):
        """正常 JSONL 输出：thread.started + item.completed + turn.completed"""
        lines = self._make_lines(
            {"type": "thread.started", "thread_id": "sess-codex-123"},
            {"type": "turn.started"},
            {"type": "item.completed", "item": {
                "id": "item_3", "type": "agent_message",
                "text": "代码修改完成，已实现用户登录功能。"
            }},
            {"type": "turn.completed", "usage": {
                "input_tokens": 24763, "cached_input_tokens": 24448,
                "output_tokens": 122
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 3000)

        assert result.output == "代码修改完成，已实现用户登录功能。"
        assert result.session_id == "sess-codex-123"
        assert result.is_error is False
        assert result.duration_ms == 3000
        assert result.cost_usd > 0  # 应有费用估算

    def test_parse_extracts_session_id_from_thread_started(self, codex_runner):
        """thread.started 中的 thread_id 被提取为 session_id"""
        lines = self._make_lines(
            {"type": "thread.started", "thread_id": "abc-def-ghi"},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 500)
        assert result.session_id == "abc-def-ghi"

    def test_parse_updates_runner_session_id(self, codex_runner):
        """解析后更新 runner.session_id"""
        codex_runner.session_id = "old-session"
        lines = self._make_lines(
            {"type": "thread.started", "thread_id": "new-session"},
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "完成"
            }},
        )
        codex_runner._parse_codex_jsonl(lines, [], 100)
        assert codex_runner.session_id == "new-session"

    def test_parse_takes_last_agent_message(self, codex_runner):
        """多个 agent_message 时取最后一个"""
        lines = self._make_lines(
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "中间消息"
            }},
            {"type": "item.completed", "item": {
                "id": "item_2", "type": "agent_message", "text": "最终结果"
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 1000)
        assert result.output == "最终结果"

    def test_parse_ignores_non_agent_message_items(self, codex_runner):
        """非 agent_message 类型的 item.completed 不影响 output"""
        lines = self._make_lines(
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "command_execution",
                "command": "bash -lc ls"
            }},
            {"type": "item.completed", "item": {
                "id": "item_2", "type": "agent_message", "text": "正确输出"
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 1000)
        assert result.output == "正确输出"

    def test_parse_tolerates_empty_lines(self, codex_runner):
        """空行被跳过"""
        lines = [
            "\n",
            "",
            json.dumps({"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "输出"
            }}) + "\n",
            "\n",
        ]
        result = codex_runner._parse_codex_jsonl(lines, [], 500)
        assert result.output == "输出"

    def test_parse_tolerates_non_json_lines(self, codex_runner):
        """非 JSON 行被跳过，不触发异常"""
        lines = [
            "这不是 JSON\n",
            json.dumps({"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "正常输出"
            }}) + "\n",
        ]
        result = codex_runner._parse_codex_jsonl(lines, [], 500)
        assert result.output == "正常输出"

    def test_parse_no_result_fallback_to_stderr(self, codex_runner):
        """无 agent_message 时降级到 stderr"""
        lines = self._make_lines(
            {"type": "thread.started", "thread_id": "sess-1"},
            {"type": "turn.started"},
        )
        stderr = ["Error: something went wrong\n"]
        result = codex_runner._parse_codex_jsonl(lines, stderr, 200)

        assert result.is_error is True
        assert "Error" in result.output

    def test_parse_no_result_no_stderr_returns_empty(self, codex_runner):
        """无 agent_message 且无 stderr 时，output 为空且非错误"""
        lines = self._make_lines(
            {"type": "thread.started", "thread_id": "sess-1"},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 100)
        assert result.output == ""
        assert result.is_error is False

    def test_parse_turn_failed_sets_error(self, codex_runner):
        """turn.failed 事件标记 is_error=True"""
        lines = self._make_lines(
            {"type": "thread.started", "thread_id": "sess-1"},
            {"type": "turn.failed", "error": "API rate limit exceeded"},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 500)
        assert result.is_error is True
        assert "rate limit" in result.output

    def test_parse_accumulates_token_usage(self, codex_runner):
        """多个 turn.completed 的 token 用量累加"""
        lines = self._make_lines(
            {"type": "turn.completed", "usage": {
                "input_tokens": 1000, "output_tokens": 100
            }},
            {"type": "turn.completed", "usage": {
                "input_tokens": 2000, "output_tokens": 200
            }},
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "完成"
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 1000)
        # 费用应精确基于 3000 input + 300 output tokens 的累加总量
        expected = codex_runner._estimate_codex_cost(3000, 300)
        assert result.cost_usd == pytest.approx(expected, rel=0.01)

    def test_parse_session_id_preserved_when_not_in_output(self, codex_runner):
        """无 thread.started 时保留 runner.session_id，且返回值一致"""
        codex_runner.session_id = "existing-session"
        lines = self._make_lines(
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "输出"
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 100)
        assert codex_runner.session_id == "existing-session"
        assert result.session_id == "existing-session"

    def test_parse_empty_agent_message_text_skipped(self, codex_runner):
        """空 text 的 agent_message 不覆盖之前的有效输出"""
        lines = self._make_lines(
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "有效输出"
            }},
            {"type": "item.completed", "item": {
                "id": "item_2", "type": "agent_message", "text": ""
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 1000)
        assert result.output == "有效输出"

    def test_parse_turn_failed_then_agent_message(self, codex_runner):
        """turn.failed 后跟 agent_message 时，output 被后者覆盖，但 is_error 保持 True
        设计决策：is_error 一旦为 True 不可恢复，但 result_text 取最后一个有效文本"""
        lines = self._make_lines(
            {"type": "turn.failed", "error": "部分失败"},
            {"type": "item.completed", "item": {
                "id": "item_1", "type": "agent_message", "text": "恢复后的输出"
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 500)
        assert result.is_error is True
        assert result.output == "恢复后的输出"

    def test_parse_turn_failed_nested_dict_error(self, codex_runner):
        """turn.failed 的 error 为嵌套 dict 时正确序列化"""
        lines = self._make_lines(
            {"type": "turn.failed", "error": {
                "code": "rate_limit_exceeded",
                "message": "Too many requests"
            }},
        )
        result = codex_runner._parse_codex_jsonl(lines, [], 300)
        assert result.is_error is True
        assert "rate_limit_exceeded" in result.output
        assert "Too many requests" in result.output



# ============================================================
# _estimate_codex_cost() 费用估算测试
# ============================================================

class TestEstimateCodexCost:
    """验证 _estimate_codex_cost() 的费用估算逻辑"""

    def test_zero_tokens_zero_cost(self, codex_runner):
        """0 token 时费用为 0"""
        cost = codex_runner._estimate_codex_cost(0, 0)
        assert cost == 0.0

    def test_positive_cost_for_tokens(self, codex_runner):
        """有 token 时费用大于 0"""
        cost = codex_runner._estimate_codex_cost(1000, 100)
        assert cost > 0

    def test_output_tokens_more_expensive(self, codex_runner):
        """output tokens 比 input tokens 更贵"""
        cost_input = codex_runner._estimate_codex_cost(1000, 0)
        cost_output = codex_runner._estimate_codex_cost(0, 1000)
        assert cost_output > cost_input

    def test_model_aware_pricing_o3(self, tmp_path):
        """o3 模型使用不同的定价"""
        config = CodingToolConfig(type="codex", command="codex", timeout=60, model="o3")
        runner = ToolRunner(config=config, working_dir=str(tmp_path))
        cost = runner._estimate_codex_cost(1_000_000, 0)
        assert cost == pytest.approx(2.00, rel=0.01)  # o3: $2.00/M input

    def test_model_aware_pricing_o4_mini(self, tmp_path):
        """o4-mini 模型定价"""
        config = CodingToolConfig(type="codex", command="codex", timeout=60, model="o4-mini")
        runner = ToolRunner(config=config, working_dir=str(tmp_path))
        cost = runner._estimate_codex_cost(1_000_000, 0)
        assert cost == pytest.approx(1.10, rel=0.01)  # o4-mini: $1.10/M input

    def test_unknown_model_uses_default_pricing(self, tmp_path):
        """未知模型使用默认保守定价"""
        config = CodingToolConfig(type="codex", command="codex", timeout=60, model="future-model")
        runner = ToolRunner(config=config, working_dir=str(tmp_path))
        cost = runner._estimate_codex_cost(1_000_000, 0)
        assert cost == pytest.approx(1.50, rel=0.01)  # 默认: $1.50/M input


# ============================================================
# resume_session() 测试
# ============================================================

class TestResumeSessionCodex:
    """验证 resume_session() 在 codex 模式下的行为"""

    def test_resume_session_sets_session_id(self, codex_runner):
        """codex 模式下 resume_session 正确设置 session_id"""
        codex_runner.resume_session("codex-sess-abc")
        assert codex_runner.session_id == "codex-sess-abc"

    def test_resume_session_overrides_existing(self, codex_runner):
        """覆盖已有的 session_id"""
        codex_runner.session_id = "old"
        codex_runner.resume_session("new")
        assert codex_runner.session_id == "new"


# ============================================================
# 事件发射测试
# ============================================================

class TestCodexEvents:
    """验证 codex 模式下的事件发射"""

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_tool_started_event_emitted(self, mock_popen, codex_runner):
        """_run_codex 发出 tool_started 事件"""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        captured = []
        codex_runner._run_codex("测试", on_event=lambda e: captured.append(e))

        started_events = [e for e in captured if e.type == EVENT_TOOL_STARTED]
        assert len(started_events) == 1
        assert started_events[0].data["command"] == "codex"

    @patch('maestro.tool_runner.subprocess.Popen')
    def test_tool_completed_event_emitted(self, mock_popen, codex_runner):
        """_run_codex 发出 tool_completed 事件"""
        mock_proc = MagicMock()
        mock_proc.stdout = iter([])
        mock_proc.stderr = MagicMock()
        mock_proc.stderr.__iter__ = MagicMock(return_value=iter([]))
        mock_proc.wait.return_value = None
        mock_proc.returncode = 0
        mock_proc.poll.return_value = 0
        mock_proc.pid = 12345
        mock_popen.return_value = mock_proc

        captured = []
        codex_runner._run_codex("测试", on_event=lambda e: captured.append(e))

        completed_events = [e for e in captured if e.type == EVENT_TOOL_COMPLETED]
        assert len(completed_events) == 1


# ============================================================
# 向后兼容测试
# ============================================================

class TestBackwardCompatibility:
    """验证 codex 类型不影响 claude 和 generic 类型"""

    def test_claude_type_still_routes_correctly(self, tmp_path):
        """type=claude 仍然路由到 _run_claude"""
        config = CodingToolConfig(type="claude", command="claude", timeout=60)
        runner = ToolRunner(config=config, working_dir=str(tmp_path))
        with patch.object(runner, '_run_claude', return_value=RunResult(output="claude")) as mock:
            runner.run("测试")
            mock.assert_called_once()

    def test_generic_type_still_routes_correctly(self, tmp_path):
        """type=generic 仍然路由到 _run_generic"""
        config = CodingToolConfig(type="generic", command="echo", timeout=60)
        runner = ToolRunner(config=config, working_dir=str(tmp_path))
        with patch.object(runner, '_run_generic', return_value=RunResult(output="generic")) as mock:
            runner.run("测试")
            mock.assert_called_once()

    def test_unknown_type_falls_to_generic(self, tmp_path):
        """未知类型仍然走 generic（else 分支）"""
        config = CodingToolConfig(type="unknown_tool", command="echo", timeout=60)
        runner = ToolRunner(config=config, working_dir=str(tmp_path))
        with patch.object(runner, '_run_generic', return_value=RunResult(output="generic")) as mock:
            runner.run("测试")
            mock.assert_called_once()
