"""
ToolEvent 数据模型单元测试

覆盖：
  - ToolEvent 构造和字段默认值
  - tool_event_to_dict() 序列化正确性
  - RunResult.events 默认空列表、向后兼容
  - 7 个 EVENT_* 常量值正确
  - _emit_chunk_event 截断逻辑（超过 2000 字符截断）
  - _parse_stream_json 解析：正常/空行/无 result 降级
  - _should_fallback_to_json 三条件检测
"""

import json
import types
import pytest
from unittest.mock import MagicMock

from maestro.tool_runner import (
    ToolEvent,
    tool_event_to_dict,
    RunResult,
    ToolRunner,
    EVENT_TOOL_STARTED,
    EVENT_TOOL_OUTPUT_CHUNK,
    EVENT_TOOL_COMPLETED,
    EVENT_MANAGER_DECIDING,
    EVENT_MANAGER_DECIDED,
    EVENT_BREAKER_WARNING,
    EVENT_ERROR,
)
from maestro.config import CodingToolConfig


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def claude_config():
    """Claude 模式的 CodingToolConfig（command 不需要真实存在）"""
    return CodingToolConfig(type="claude", command="claude", timeout=60)


@pytest.fixture
def runner(claude_config, tmp_path):
    """创建 ToolRunner 实例"""
    return ToolRunner(config=claude_config, working_dir=str(tmp_path))


# ============================================================
# 常量正确性测试
# ============================================================

class TestEventConstants:
    """验证 7 个 EVENT_* 常量的字符串值符合预期"""

    def test_event_tool_started_value(self):
        """EVENT_TOOL_STARTED 值为 'tool_started'"""
        assert EVENT_TOOL_STARTED == "tool_started"

    def test_event_tool_output_chunk_value(self):
        """EVENT_TOOL_OUTPUT_CHUNK 值为 'tool_output_chunk'"""
        assert EVENT_TOOL_OUTPUT_CHUNK == "tool_output_chunk"

    def test_event_tool_completed_value(self):
        """EVENT_TOOL_COMPLETED 值为 'tool_completed'"""
        assert EVENT_TOOL_COMPLETED == "tool_completed"

    def test_event_manager_deciding_value(self):
        """EVENT_MANAGER_DECIDING 值为 'manager_deciding'"""
        assert EVENT_MANAGER_DECIDING == "manager_deciding"

    def test_event_manager_decided_value(self):
        """EVENT_MANAGER_DECIDED 值为 'manager_decided'"""
        assert EVENT_MANAGER_DECIDED == "manager_decided"

    def test_event_breaker_warning_value(self):
        """EVENT_BREAKER_WARNING 值为 'breaker_warning'"""
        assert EVENT_BREAKER_WARNING == "breaker_warning"

    def test_event_error_value(self):
        """EVENT_ERROR 值为 'error'"""
        assert EVENT_ERROR == "error"

    def test_all_constants_are_unique(self):
        """7 个常量值不重复"""
        constants = [
            EVENT_TOOL_STARTED, EVENT_TOOL_OUTPUT_CHUNK, EVENT_TOOL_COMPLETED,
            EVENT_MANAGER_DECIDING, EVENT_MANAGER_DECIDED, EVENT_BREAKER_WARNING,
            EVENT_ERROR,
        ]
        assert len(constants) == len(set(constants))


# ============================================================
# ToolEvent 构造与字段测试
# ============================================================

class TestToolEventConstruction:
    """验证 ToolEvent dataclass 的构造和字段行为"""

    def test_tool_event_basic_construction(self):
        """正常构造 ToolEvent，四个字段均可读取"""
        event = ToolEvent(
            type=EVENT_TOOL_STARTED,
            timestamp="2024-01-01T10:00:00",
            turn=1,
            data={"command": "claude"},
        )
        assert event.type == EVENT_TOOL_STARTED
        assert event.timestamp == "2024-01-01T10:00:00"
        assert event.turn == 1
        assert event.data == {"command": "claude"}

    def test_tool_event_turn_zero_placeholder(self):
        """turn=0 是合法的占位值（ToolRunner 内部使用）"""
        event = ToolEvent(
            type=EVENT_ERROR,
            timestamp="2024-01-01T10:00:00",
            turn=0,
            data={"reason": "timeout"},
        )
        assert event.turn == 0

    def test_tool_event_data_accepts_empty_dict(self):
        """data 字段接受空字典"""
        event = ToolEvent(
            type=EVENT_TOOL_COMPLETED,
            timestamp="2024-01-01T10:00:00",
            turn=5,
            data={},
        )
        assert event.data == {}

    def test_tool_event_data_accepts_nested_dict(self):
        """data 字段接受嵌套字典"""
        nested = {"level1": {"level2": [1, 2, 3]}}
        event = ToolEvent(
            type=EVENT_MANAGER_DECIDED,
            timestamp="2024-01-01T10:00:00",
            turn=3,
            data=nested,
        )
        assert event.data == nested


# ============================================================
# tool_event_to_dict 序列化测试
# ============================================================

class TestToolEventToDict:
    """验证 tool_event_to_dict() 的序列化行为"""

    def test_serialize_returns_dict_with_all_keys(self):
        """序列化结果包含 type/timestamp/turn/data 四个键"""
        event = ToolEvent(
            type=EVENT_TOOL_STARTED,
            timestamp="2024-01-01T10:00:00.123456",
            turn=2,
            data={"command": "claude"},
        )
        result = tool_event_to_dict(event)
        assert set(result.keys()) == {"type", "timestamp", "turn", "data"}

    def test_serialize_values_match_event_fields(self):
        """序列化字典中的值与 ToolEvent 字段一一对应"""
        event = ToolEvent(
            type=EVENT_TOOL_COMPLETED,
            timestamp="2024-06-15T08:30:00",
            turn=7,
            data={"duration_ms": 1500, "cost_usd": 0.05, "is_error": False},
        )
        result = tool_event_to_dict(event)
        assert result["type"] == EVENT_TOOL_COMPLETED
        assert result["timestamp"] == "2024-06-15T08:30:00"
        assert result["turn"] == 7
        assert result["data"]["duration_ms"] == 1500
        assert result["data"]["cost_usd"] == 0.05
        assert result["data"]["is_error"] is False

    def test_serialize_result_is_json_serializable(self):
        """序列化结果可以通过 json.dumps() 不报错"""
        event = ToolEvent(
            type=EVENT_ERROR,
            timestamp="2024-01-01T00:00:00",
            turn=0,
            data={"reason": "timeout"},
        )
        result = tool_event_to_dict(event)
        # 不应抛出异常
        json_str = json.dumps(result)
        parsed = json.loads(json_str)
        assert parsed["type"] == EVENT_ERROR

    def test_serialize_does_not_mutate_original_event(self):
        """序列化操作不修改原始 ToolEvent 对象的顶层键

        注意：tool_event_to_dict 直接引用 event.data（浅拷贝语义），
        修改序列化结果的顶层键（如 type/turn）不影响原始对象，
        但修改 data 字典内部是共享引用，属于已知浅拷贝行为。
        此测试验证顶层键的独立性，而非 data 内部的深度拷贝。
        """
        data = {"text": "hello"}
        event = ToolEvent(
            type=EVENT_TOOL_OUTPUT_CHUNK,
            timestamp="2024-01-01T00:00:00",
            turn=1,
            data=data,
        )
        result = tool_event_to_dict(event)
        # 修改序列化结果的顶层 type 键，不影响原始 event
        result["type"] = "other_type"
        assert event.type == EVENT_TOOL_OUTPUT_CHUNK
        # 序列化结果的 turn 修改也不影响原始 event
        result["turn"] = 99
        assert event.turn == 1


# ============================================================
# RunResult 字段测试
# ============================================================

class TestRunResultFields:
    """验证 RunResult dataclass 的默认值和向后兼容性"""

    def test_run_result_minimal_construction(self):
        """只提供必填字段 output，其余字段使用默认值"""
        result = RunResult(output="任务完成")
        assert result.output == "任务完成"
        assert result.session_id == ""
        assert result.cost_usd == 0.0
        assert result.duration_ms == 0
        assert result.is_error is False
        assert result.error_type == ""

    def test_run_result_events_default_empty_list(self):
        """events 默认值为空列表（向后兼容：老代码不传 events 仍可运行）"""
        result = RunResult(output="")
        assert result.events == []
        assert isinstance(result.events, list)

    def test_run_result_events_not_shared_between_instances(self):
        """不同 RunResult 实例的 events 列表不共享（dataclass field 陷阱验证）"""
        r1 = RunResult(output="a")
        r2 = RunResult(output="b")
        r1.events.append("x")
        assert r2.events == []  # 确认两个实例不共享同一个列表

    def test_run_result_events_can_hold_tool_events(self):
        """events 列表可以存储 ToolEvent 对象"""
        event = ToolEvent(
            type=EVENT_TOOL_STARTED,
            timestamp="2024-01-01T00:00:00",
            turn=1,
            data={},
        )
        result = RunResult(output="完成")
        result.events.append(event)
        assert len(result.events) == 1
        assert result.events[0].type == EVENT_TOOL_STARTED

    def test_run_result_full_construction(self):
        """完整字段构造 RunResult"""
        result = RunResult(
            output="完整输出",
            session_id="sess-abc123",
            cost_usd=0.15,
            duration_ms=3000,
            is_error=True,
            error_type="timeout",
        )
        assert result.output == "完整输出"
        assert result.session_id == "sess-abc123"
        assert result.cost_usd == 0.15
        assert result.duration_ms == 3000
        assert result.is_error is True
        assert result.error_type == "timeout"


# ============================================================
# _emit_chunk_event 截断逻辑测试
# ============================================================

class TestEmitChunkEvent:
    """验证 _emit_chunk_event 的截断保护逻辑"""

    def test_short_line_not_truncated(self, runner):
        """短行（< 2000 字符）不被截断"""
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), "短行内容\n")
        assert len(captured) == 1
        assert captured[0].data["text"] == "短行内容"

    def test_exact_2000_chars_not_truncated(self, runner):
        """恰好 2000 字符时不截断"""
        line = "x" * 2000 + "\n"
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), line)
        assert len(captured[0].data["text"]) == 2000

    def test_over_2000_chars_truncated_to_2000(self, runner):
        """超过 2000 字符时截断到 2000 字符"""
        line = "a" * 3000 + "\n"
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), line)
        assert len(captured[0].data["text"]) == 2000

    def test_truncation_keeps_prefix(self, runner):
        """截断保留前 2000 字符（而非后缀）"""
        # 前 2000 个 'A'，后面 1000 个 'B'
        line = "A" * 2000 + "B" * 1000 + "\n"
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), line)
        text = captured[0].data["text"]
        assert len(text) == 2000
        assert all(c == "A" for c in text)

    def test_newline_stripped_from_chunk(self, runner):
        """行末换行符被去除"""
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), "内容\n")
        assert "\n" not in captured[0].data["text"]

    def test_chunk_event_type_is_correct(self, runner):
        """chunk 事件类型为 EVENT_TOOL_OUTPUT_CHUNK"""
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), "内容\n")
        assert captured[0].type == EVENT_TOOL_OUTPUT_CHUNK

    def test_empty_line_emits_empty_text(self, runner):
        """空行产生 text='' 的 chunk 事件"""
        captured = []
        runner._emit_chunk_event(lambda e: captured.append(e), "\n")
        assert captured[0].data["text"] == ""

    def test_no_callback_still_appends_to_collected_events(self, runner):
        """on_event=None 时事件仍追加到 _collected_events"""
        runner._collected_events = []
        runner._emit_chunk_event(None, "内容\n")
        assert len(runner._collected_events) == 1


# ============================================================
# _parse_stream_json 解析测试
# ============================================================

class TestParseStreamJson:
    """验证 _parse_stream_json 对 Claude Code stream-json 输出的解析"""

    def _make_lines(self, *objs):
        """辅助：将多个 dict 转为 JSON 行列表"""
        return [json.dumps(obj) + "\n" for obj in objs]

    def test_parse_normal_stream_json_with_result(self, runner):
        """正常 stream-json：system init + result 两条记录"""
        lines = self._make_lines(
            {"type": "system", "subtype": "init", "session_id": "sess-123"},
            {"type": "result", "subtype": "success", "result": "任务完成",
             "cost_usd": 0.10, "session_id": "sess-123", "is_error": False},
        )
        result = runner._parse_stream_json(lines, [], 2000)

        assert result.output == "任务完成"
        assert result.session_id == "sess-123"
        assert result.cost_usd == 0.10
        assert result.is_error is False
        assert result.duration_ms == 2000

    def test_parse_extracts_session_id_from_system_init(self, runner):
        """system/init 行中的 session_id 被正确提取"""
        lines = self._make_lines(
            {"type": "system", "subtype": "init", "session_id": "sess-abc"},
        )
        result = runner._parse_stream_json(lines, [], 500)
        assert result.session_id == "sess-abc"

    def test_parse_result_overrides_system_session_id(self, runner):
        """result 行中的 session_id 优先于 system/init 中的 session_id"""
        lines = self._make_lines(
            {"type": "system", "subtype": "init", "session_id": "sess-old"},
            {"type": "result", "result": "输出", "session_id": "sess-new",
             "cost_usd": 0.0, "is_error": False},
        )
        result = runner._parse_stream_json(lines, [], 1000)
        assert result.session_id == "sess-new"

    def test_parse_tolerates_empty_lines(self, runner):
        """空行被跳过，不影响解析结果"""
        lines = [
            "\n",
            "",
            json.dumps({"type": "result", "result": "输出", "cost_usd": 0.0,
                        "session_id": "", "is_error": False}) + "\n",
            "\n",
        ]
        result = runner._parse_stream_json(lines, [], 1000)
        assert result.output == "输出"

    def test_parse_tolerates_non_json_lines(self, runner):
        """非 JSON 行被跳过，不触发异常"""
        lines = [
            "这不是 JSON\n",
            "also not json {broken\n",
            json.dumps({"type": "result", "result": "正常输出", "cost_usd": 0.0,
                        "session_id": "", "is_error": False}) + "\n",
        ]
        result = runner._parse_stream_json(lines, [], 500)
        assert result.output == "正常输出"

    def test_parse_no_result_event_fallback_to_stderr(self, runner):
        """无 result 事件时，用 stderr 内容作为 output 并标记 is_error=True"""
        lines = [
            json.dumps({"type": "system", "subtype": "init", "session_id": ""}) + "\n",
        ]
        stderr = ["Error: something went wrong\n", "详细错误信息\n"]
        result = runner._parse_stream_json(lines, stderr, 100)

        assert result.is_error is True
        assert "Error" in result.output or "详细" in result.output

    def test_parse_no_result_no_stderr_returns_empty_output(self, runner):
        """无 result 事件且无 stderr 时，output 为空字符串"""
        lines = [json.dumps({"type": "system", "subtype": "init", "session_id": ""}) + "\n"]
        result = runner._parse_stream_json(lines, [], 100)
        assert result.output == ""

    def test_parse_is_error_from_result_event(self, runner):
        """is_error 值从 result 事件中提取"""
        lines = self._make_lines(
            {"type": "result", "result": "失败输出", "cost_usd": 0.0,
             "session_id": "", "is_error": True},
        )
        result = runner._parse_stream_json(lines, [], 500)
        assert result.is_error is True

    def test_parse_ignores_non_result_non_system_events(self, runner):
        """assistant 等其他类型行不影响最终结果"""
        lines = self._make_lines(
            {"type": "assistant", "message": {"content": "中间状态"}},
            {"type": "result", "result": "最终结果", "cost_usd": 0.03,
             "session_id": "s1", "is_error": False},
        )
        result = runner._parse_stream_json(lines, [], 800)
        assert result.output == "最终结果"

    def test_parse_updates_runner_session_id(self, runner):
        """解析后更新 runner.session_id"""
        runner.session_id = "old-session"
        lines = self._make_lines(
            {"type": "result", "result": "输出", "cost_usd": 0.0,
             "session_id": "new-session", "is_error": False},
        )
        runner._parse_stream_json(lines, [], 100)
        assert runner.session_id == "new-session"

    def test_parse_session_id_default_to_existing_when_not_in_result(self, runner):
        """result 行没有 session_id 时保留 runner 当前的 session_id"""
        runner.session_id = "existing-session"
        lines = self._make_lines(
            {"type": "result", "result": "输出", "cost_usd": 0.0, "is_error": False},
        )
        runner._parse_stream_json(lines, [], 100)
        assert runner.session_id == "existing-session"


# ============================================================
# _should_fallback_to_json 三条件测试
# ============================================================

class TestShouldFallbackToJson:
    """验证 _should_fallback_to_json 的三条件检测逻辑"""

    def _make_proc(self, returncode: int):
        """辅助：创建带 returncode 属性的 Mock 进程对象"""
        proc = MagicMock()
        proc.returncode = returncode
        return proc

    def test_returncode_zero_returns_false(self, runner):
        """条件1不满足（returncode=0）时直接返回 False"""
        proc = self._make_proc(0)
        result = runner._should_fallback_to_json(
            proc,
            stdout_lines=["some output\n"],
            stderr_lines=["unknown format error\n"],
            duration_ms=100,
        )
        assert result is False

    def test_duration_over_5000ms_returns_false(self, runner):
        """条件2不满足（duration > 5000ms）时返回 False（即使1和3满足）"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc,
            stdout_lines=[],
            stderr_lines=["unknown format error\n"],
            duration_ms=5001,
        )
        assert result is False

    def test_stderr_no_keywords_returns_false(self, runner):
        """条件3不满足（stderr 无关键词）时返回 False（即使1和2满足）"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc,
            stdout_lines=[],
            stderr_lines=["regular error occurred\n"],
            duration_ms=100,
        )
        assert result is False

    def test_all_three_conditions_returns_true(self, runner):
        """三条件同时满足时返回 True"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc,
            stdout_lines=[],
            stderr_lines=["stream-json not supported\n"],
            duration_ms=100,
        )
        assert result is True

    def test_keyword_unknown_format_triggers_fallback(self, runner):
        """stderr 含 'unknown format' 时触发 fallback"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc, [], ["Error: unknown format specified\n"], 200
        )
        assert result is True

    def test_keyword_invalid_format_triggers_fallback(self, runner):
        """stderr 含 'invalid format' 时触发 fallback"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc, [], ["invalid format: stream-json\n"], 200
        )
        assert result is True

    def test_keyword_unsupported_triggers_fallback(self, runner):
        """stderr 含 'unsupported' 时触发 fallback"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc, [], ["unsupported output format\n"], 200
        )
        assert result is True

    def test_keyword_unrecognized_option_triggers_fallback(self, runner):
        """stderr 含 'unrecognized option' 时触发 fallback"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc, [], ["unrecognized option: --output-format\n"], 200
        )
        assert result is True

    def test_keyword_case_insensitive(self, runner):
        """关键词匹配不区分大小写"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(
            proc, [], ["UNKNOWN FORMAT in stream\n"], 200
        )
        assert result is True

    def test_duration_exactly_5000ms_still_returns_true(self, runner):
        """duration=5000ms（边界值）时，条件2通过（<=5000才满足条件，但实现是>5000返回False）"""
        proc = self._make_proc(1)
        # 实现: if duration_ms > 5000: return False
        # 所以 5000 不触发 False，仍然继续检测
        result = runner._should_fallback_to_json(
            proc, [], ["unknown format\n"], 5000
        )
        assert result is True

    def test_empty_stderr_returns_false_even_if_conditions_1_2_met(self, runner):
        """stderr 为空时（无关键词）返回 False"""
        proc = self._make_proc(1)
        result = runner._should_fallback_to_json(proc, [], [], 100)
        assert result is False

    def test_negative_returncode_returns_false(self, runner):
        """负 returncode（信号 kill，如 SIGTERM=-15）不触发 fallback"""
        proc = self._make_proc(-15)  # SIGTERM
        result = runner._should_fallback_to_json(
            proc, [], ["unknown format\n"], 100
        )
        assert result is False

    def test_sigkill_returncode_returns_false(self, runner):
        """SIGKILL(-9) 的 returncode 不触发 fallback"""
        proc = self._make_proc(-9)
        result = runner._should_fallback_to_json(
            proc, [], ["stream-json not supported\n"], 50
        )
        assert result is False

    def test_none_returncode_returns_false(self, runner):
        """returncode=None（进程未退出）不触发 fallback"""
        proc = self._make_proc(None)
        result = runner._should_fallback_to_json(
            proc, [], ["unknown format\n"], 100
        )
        assert result is False


# ============================================================
# consume_abort 公有接口测试
# ============================================================

class TestConsumeAbort:
    """验证 consume_abort() 的检查+重置语义"""

    def test_consume_abort_returns_false_initially(self, runner):
        """初始状态下 consume_abort() 返回 False"""
        assert runner.consume_abort() is False

    def test_consume_abort_returns_true_after_abort(self, runner):
        """abort() 后 consume_abort() 返回 True"""
        runner._aborted = True
        assert runner.consume_abort() is True

    def test_consume_abort_resets_flag(self, runner):
        """consume_abort() 调用后 _aborted 重置为 False"""
        runner._aborted = True
        runner.consume_abort()
        assert runner._aborted is False

    def test_consume_abort_second_call_returns_false(self, runner):
        """连续调用两次，第二次返回 False（已被消费）"""
        runner._aborted = True
        assert runner.consume_abort() is True
        assert runner.consume_abort() is False

    def test_run_resets_aborted_flag(self, runner):
        """run() 方法开头重置 _aborted 标记"""
        runner._aborted = True
        # run() 会因为找不到命令而快速返回，但重置已发生
        result = runner.run("测试指令")
        assert runner._aborted is False
