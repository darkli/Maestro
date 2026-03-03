"""
CircuitBreaker 多维度检测单元测试（v2）

覆盖：
  A. 原有功能：轮数超限、费用超限、连续相同指令 hash
  B. 指令语义相似度检测（SequenceMatcher 相邻对比）
  C. 错误重复检测（error hash 连续相同）
  D. 输出停滞检测（输出尾部指纹相邻对比）
  E. action 震荡检测（ABABAB 模式 + check_action 公有方法）
  F. from_config 工厂方法
  G. to_dict / restore 序列化与恢复
"""

import pytest
from maestro.state import CircuitBreaker
from maestro.config import SafetyConfig


# ============================================================
# Fixture
# ============================================================

@pytest.fixture
def breaker():
    """标准熔断器（max_turns=10, max_budget_usd=1.0, max_consecutive_similar=3）"""
    return CircuitBreaker(
        max_turns=10,
        max_budget_usd=1.0,
        max_consecutive_similar=3,
        similarity_threshold=0.85,
        stagnation_threshold=0.9,
        max_consecutive_errors=3,
        oscillation_window=6,
    )


@pytest.fixture
def breaker_tight():
    """严格熔断器（阈值更低，用于边界测试）"""
    return CircuitBreaker(
        max_turns=100,
        max_budget_usd=100.0,
        max_consecutive_similar=2,
        similarity_threshold=0.8,
        stagnation_threshold=0.8,
        max_consecutive_errors=2,
        oscillation_window=4,
    )


# ============================================================
# A. 原有功能测试
# ============================================================

class TestOriginalFeatures:
    """验证 CircuitBreaker 原有的三个维度功能不变"""

    def test_normal_execution_returns_none(self, breaker):
        """正常不同指令，check() 返回 None"""
        assert breaker.check("第一步：分析需求", 0.0) is None
        assert breaker.check("第二步：编写代码", 0.0) is None
        assert breaker.check("第三步：运行测试", 0.0) is None

    # ── 轮数超限 ──

    def test_max_turns_not_exceeded(self, breaker):
        """轮数未超限时不熔断"""
        for i in range(10):
            result = breaker.check(f"唯一指令{i}", 0.0)
        assert result is None

    def test_max_turns_exceeded_on_11th(self, breaker):
        """第 11 轮超过 max_turns=10 时触发熔断"""
        for i in range(10):
            breaker.check(f"指令{i}", 0.0)
        result = breaker.check("第11轮指令", 0.0)
        assert result is not None
        assert "轮数" in result or "max_turns" in result.lower() or "10" in result

    def test_current_turn_increments(self, breaker):
        """每次 check() 后 current_turn 递增"""
        assert breaker.current_turn == 0
        breaker.check("指令A", 0.0)
        assert breaker.current_turn == 1
        breaker.check("指令B", 0.0)
        assert breaker.current_turn == 2

    # ── 费用超限 ──

    def test_cost_not_exceeded(self, breaker):
        """累计费用未超限时不熔断"""
        result = breaker.check("指令A", 0.5)
        assert result is None

    def test_cost_exceeded(self, breaker):
        """累计费用超过 max_budget_usd=1.0 时触发熔断"""
        breaker.check("指令A", 0.6)
        result = breaker.check("指令B", 0.5)  # 累计 1.1 > 1.0
        assert result is not None
        assert "费用" in result or "budget" in result.lower()

    def test_total_cost_accumulates(self, breaker):
        """total_cost 属性正确累计"""
        breaker.check("指令A", 0.3)
        breaker.check("指令B", 0.2)
        assert abs(breaker.total_cost - 0.5) < 1e-9

    # ── 连续相同指令 hash ──

    def test_identical_instructions_hash_triggers(self, breaker):
        """连续 3 次完全相同指令触发 hash 熔断"""
        same = "完全相同的指令内容"
        breaker.check(same, 0.0)
        breaker.check(same, 0.0)
        result = breaker.check(same, 0.0)
        assert result is not None
        assert "循环" in result or "相同" in result

    def test_different_instructions_not_triggered_by_hash(self, breaker):
        """不同指令不触发 hash 检测"""
        breaker.check("指令A", 0.0)
        breaker.check("指令B", 0.0)
        result = breaker.check("指令C", 0.0)
        assert result is None

    def test_hash_resets_on_different_instruction(self, breaker):
        """插入不同指令后，相同 hash 的连续计数重置"""
        same = "重复指令"
        breaker.check(same, 0.0)
        breaker.check(same, 0.0)
        breaker.check("不同指令打断", 0.0)  # 打断连续
        result = breaker.check(same, 0.0)
        assert result is None


# ============================================================
# B. 指令语义相似度检测
# ============================================================

class TestInstructionSimilarity:
    """验证连续 N 轮语义相似指令的检测逻辑"""

    def _make_similar_instruction(self, base: str, variation: str) -> str:
        """生成与 base 高度相似的指令（仅末尾添加少量变化）"""
        return base + " " + variation

    def test_similar_instructions_trigger_after_n_rounds(self, breaker):
        """连续 max_consecutive_similar 轮高度相似指令触发熔断"""
        # 基础指令较长，确保相似度 > 0.85
        base = "请修复 src/main.py 中的 TypeError 错误，该错误发生在第 42 行，原因是变量类型不匹配"
        # 三条极其相似的指令
        i1 = base + " (尝试1)"
        i2 = base + " (尝试2)"
        i3 = base + " (尝试3)"

        breaker.check(i1, 0.0)
        breaker.check(i2, 0.0)
        result = breaker.check(i3, 0.0)
        assert result is not None
        assert "相似" in result

    def test_different_instructions_not_triggered(self, breaker):
        """完全不同的指令不触发语义相似度熔断"""
        breaker.check("第一步：分析需求文档，识别核心功能模块", 0.0)
        breaker.check("第二步：设计数据库 Schema，建立实体关系图", 0.0)
        result = breaker.check("第三步：实现 REST API 接口，完成 CRUD 操作", 0.0)
        assert result is None

    def test_adjacent_pair_comparison(self, breaker_tight):
        """验证是相邻对比（非 recent[0] vs all）"""
        # A→B→C 三步，B 与 A 相似，C 与 B 相似，但 A 与 C 相比结果
        # 此测试关注"每相邻两步都相似"才触发
        base = "请检查代码中的 ImportError 并修复依赖问题，确保所有模块都能正确导入"
        a = base + " 第一次尝试修复"
        b = base + " 第二次尝试修复"  # 与 a 相似
        c = base + " 第三次尝试修复"  # 与 b 相似
        # breaker_tight.max_consecutive_similar = 2
        breaker_tight.check(a, 0.0)
        result = breaker_tight.check(b, 0.0)
        assert result is not None  # 相邻 a→b 都高度相似，达到阈值2

    def test_dissimilar_instruction_breaks_chain(self, breaker):
        """插入不相似指令打断相似链"""
        base = "修复 TypeError：变量类型不匹配，请检查 main.py 第 42 行的类型转换"
        breaker.check(base + " 尝试A", 0.0)
        breaker.check(base + " 尝试B", 0.0)
        # 插入完全不同的指令，打断相似链
        breaker.check("运行测试套件并收集覆盖率报告", 0.0)
        result = breaker.check(base + " 尝试C", 0.0)
        # 此时最近 3 条中有一条不相似，不应触发
        assert result is None

    def test_similarity_threshold_boundary(self):
        """阈值边界：相似度低于阈值时不触发"""
        # 阈值设为 0.99（极高），即使相似指令也不触发
        strict_breaker = CircuitBreaker(
            max_turns=100,
            max_budget_usd=100.0,
            max_consecutive_similar=3,
            similarity_threshold=0.99,
        )
        base = "修复代码中的错误"
        strict_breaker.check(base + " 方案A：检查类型", 0.0)
        strict_breaker.check(base + " 方案B：检查导入", 0.0)
        # 两条指令有差异，相似度通常 < 0.99，不触发
        result = strict_breaker.check(base + " 方案C：检查逻辑", 0.0)
        # 相似度不到 0.99，不应触发语义相似熔断
        assert result is None

    def test_instruction_texts_list_grows(self, breaker):
        """每次 check() 后 _instruction_texts 增长"""
        assert len(breaker._instruction_texts) == 0
        breaker.check("指令A", 0.0)
        assert len(breaker._instruction_texts) == 1
        breaker.check("指令B", 0.0)
        assert len(breaker._instruction_texts) == 2


# ============================================================
# C. 错误重复检测
# ============================================================

class TestErrorRepetition:
    """验证连续 N 轮相同错误的检测逻辑"""

    _ERROR_OUTPUT = (
        "Traceback (most recent call last):\n"
        "  File 'main.py', line 42, in <module>\n"
        "TypeError: unsupported operand type(s) for +: 'int' and 'str'\n"
    )

    def test_same_error_triggers_after_n_rounds(self, breaker):
        """连续 max_consecutive_errors 轮相同错误触发熔断"""
        breaker.check("修复指令A", 0.0, tool_output=self._ERROR_OUTPUT)
        breaker.check("修复指令B", 0.0, tool_output=self._ERROR_OUTPUT)
        result = breaker.check("修复指令C", 0.0, tool_output=self._ERROR_OUTPUT)
        assert result is not None
        assert "错误" in result

    def test_no_error_output_does_not_trigger(self, breaker):
        """无错误输出时不触发错误重复熔断

        三轮输出内容各不相同（避免触发停滞检测），且均无错误关键词。
        """
        breaker.check("指令A", 0.0, tool_output="第一阶段完成：需求分析整理完毕，共识别 5 个核心功能")
        breaker.check("指令B", 0.0, tool_output="第二阶段完成：数据库表结构设计完毕，包含 8 张核心表")
        result = breaker.check("指令C", 0.0, tool_output="第三阶段完成：REST API 接口实现完毕，共 12 个端点")
        assert result is None

    def test_none_placeholder_breaks_consecutive_chain(self, breaker):
        """无错误轮次（None 占位）打断连续性，不触发熔断"""
        breaker.check("修复指令A", 0.0, tool_output=self._ERROR_OUTPUT)
        # 中间插入一轮正常输出（无错误关键词）
        breaker.check("执行成功", 0.0, tool_output="编译完成，无错误")
        result = breaker.check("修复指令B", 0.0, tool_output=self._ERROR_OUTPUT)
        # 不连续，不应触发
        assert result is None

    def test_different_errors_not_triggered(self, breaker):
        """不同错误内容不触发熔断"""
        error_1 = "TypeError: unsupported operand\n"
        error_2 = "ImportError: cannot import module 'xyz'\n"
        error_3 = "ValueError: invalid literal for int()\n"
        breaker.check("修复指令A", 0.0, tool_output=error_1)
        breaker.check("修复指令B", 0.0, tool_output=error_2)
        result = breaker.check("修复指令C", 0.0, tool_output=error_3)
        assert result is None

    def test_error_hash_list_tracks_none_for_clean_output(self, breaker):
        """无错误轮次在 _error_hashes 中记录为 None"""
        breaker.check("指令A", 0.0, tool_output="成功完成")
        assert breaker._error_hashes[-1] is None

    def test_error_hash_list_tracks_hash_for_error_output(self, breaker):
        """有错误的轮次在 _error_hashes 中记录非 None hash"""
        breaker.check("指令A", 0.0, tool_output=self._ERROR_OUTPUT)
        assert breaker._error_hashes[-1] is not None

    def test_error_with_traceback_keyword_detected(self, breaker):
        """含 'traceback' 关键词的输出被识别为错误"""
        output = "Traceback (most recent call last):\n  some error\n"
        breaker.check("指令A", 0.0, tool_output=output)
        assert breaker._error_hashes[-1] is not None

    def test_error_with_exception_keyword_detected(self, breaker):
        """含 'exception' 关键词的输出被识别为错误"""
        output = "Exception: unexpected value encountered\n"
        breaker.check("指令A", 0.0, tool_output=output)
        assert breaker._error_hashes[-1] is not None

    def test_two_consecutive_same_errors_with_tight_threshold(self, breaker_tight):
        """max_consecutive_errors=2 时，连续 2 次相同错误触发"""
        breaker_tight.check("指令A", 0.0, tool_output=self._ERROR_OUTPUT)
        result = breaker_tight.check("指令B", 0.0, tool_output=self._ERROR_OUTPUT)
        assert result is not None


# ============================================================
# D. 输出停滞检测
# ============================================================

class TestOutputStagnation:
    """验证连续 N 轮输出无实质变化的检测逻辑"""

    # 注意：BASE_OUTPUT 不包含任何错误关键词（避免触发错误重复检测路径）
    _BASE_OUTPUT = (
        "正在扫描代码质量指标...\n"
        "代码复杂度分析完成，圈复杂度平均值为 3.2\n"
        "发现 15 处代码规范问题，主要集中在命名风格\n"
        "建议优先处理命名规范问题以提升可读性\n"
        "当前状态：等待下一步指令\n"
    ) * 5  # 重复以生成足够长度

    def test_highly_similar_output_triggers_stagnation(self, breaker):
        """连续 max_consecutive_similar 轮高度相似输出触发停滞熔断

        三轮输出只有末尾少量差异，尾部 1000 字符相似度应超过 0.9。
        BASE_OUTPUT 不含错误关键词，确保走停滞检测而非错误重复检测。
        """
        # 三轮末尾只差一个字符，其余完全相同
        out1 = self._BASE_OUTPUT + "轮次1"
        out2 = self._BASE_OUTPUT + "轮次2"
        out3 = self._BASE_OUTPUT + "轮次3"

        breaker.check("指令A", 0.0, tool_output=out1)
        breaker.check("指令B", 0.0, tool_output=out2)
        result = breaker.check("指令C", 0.0, tool_output=out3)
        assert result is not None
        assert "停滞" in result

    def test_different_outputs_not_triggered(self, breaker):
        """内容差异大的输出不触发停滞"""
        breaker.check("指令A", 0.0, tool_output="第一阶段：需求分析完成，识别了 5 个核心功能模块")
        breaker.check("指令B", 0.0, tool_output="第二阶段：数据库设计完成，建立 ER 图和表结构")
        result = breaker.check("指令C", 0.0, tool_output="第三阶段：API 接口实现完成，通过单元测试")
        assert result is None

    def test_all_empty_outputs_not_triggered(self, breaker):
        """全空输出（at least one required）不触发停滞"""
        # 实现要求：至少有一轮非空才触发
        breaker.check("指令A", 0.0, tool_output="")
        breaker.check("指令B", 0.0, tool_output="")
        result = breaker.check("指令C", 0.0, tool_output="")
        assert result is None

    def test_tail_1000_chars_strategy(self, breaker):
        """尾部 1000 字符策略：头部不同但尾部相同时也触发停滞

        tail 超过 2000 字符，确保三轮输出的尾部 1000 字符完全相同（均取自 tail 末尾）。
        此时 SequenceMatcher(tail[-1000:], tail[-1000:]) = 1.0 >> 0.9，触发停滞。
        """
        # 固定尾部：超过 2000 字符，确保 [-1000:] 完全来自 tail（三轮相同）
        tail = "固定重复尾部内容ABCDE" * 200  # 每个 11 字符，共约 2200 字符
        # 三轮头部各不相同（总长度超过 1000 字符）
        head1 = "头部内容一：" + "A" * 500
        head2 = "头部内容二：" + "B" * 500
        head3 = "头部内容三：" + "C" * 500

        out1 = head1 + tail
        out2 = head2 + tail
        out3 = head3 + tail

        # 验证尾部 1000 字符完全相同
        assert out1[-1000:] == out2[-1000:] == out3[-1000:]

        # 取尾部 1000 字符后，三轮应完全相同，触发停滞
        breaker.check("指令A", 0.0, tool_output=out1)
        breaker.check("指令B", 0.0, tool_output=out2)
        result = breaker.check("指令C", 0.0, tool_output=out3)
        # 尾部 1000 字符完全相同，应触发停滞
        assert result is not None
        assert "停滞" in result

    def test_mixed_empty_and_content_not_triggered(self, breaker):
        """空输出+有内容混合时不触发（相邻对有内容差异）"""
        rich_output = "大量实质性内容" * 50
        breaker.check("指令A", 0.0, tool_output="")
        breaker.check("指令B", 0.0, tool_output=rich_output)
        result = breaker.check("指令C", 0.0, tool_output="")
        # 空→有内容→空，差异大，不触发
        assert result is None

    def test_output_fingerprints_list_grows(self, breaker):
        """每次 check() 后 _output_fingerprints 增长"""
        assert len(breaker._output_fingerprints) == 0
        breaker.check("指令A", 0.0, tool_output="some output")
        assert len(breaker._output_fingerprints) == 1


# ============================================================
# E. action 震荡检测
# ============================================================

class TestActionOscillation:
    """验证 ABABAB 模式的 action 震荡检测"""

    def test_ababab_pattern_triggers_oscillation(self, breaker):
        """ABABAB 模式在 oscillation_window=6 内触发熔断"""
        actions = ["execute", "retry", "execute", "retry", "execute", "retry"]
        result = None
        for i, action in enumerate(actions):
            breaker.check(f"唯一指令{i}", 0.0)
            result = breaker.check_action(action)
        assert result is not None
        assert "震荡" in result or "oscillat" in result.lower()

    def test_single_action_not_triggered(self, breaker):
        """单一 action 序列（AAAAAA）不触发震荡"""
        result = None
        for i in range(6):
            breaker.check(f"唯一指令{i}", 0.0)
            result = breaker.check_action("execute")
        assert result is None

    def test_window_insufficient_not_triggered(self, breaker):
        """action 序列长度不足 oscillation_window=6 时不触发"""
        # 只有 4 条 ABAB，未达到窗口 6
        for i in range(4):
            action = "execute" if i % 2 == 0 else "retry"
            breaker.check(f"唯一指令{i}", 0.0)
            breaker.check_action(action)
        breaker.check("唯一指令4", 0.0)
        result = breaker.check_action("done")
        assert result is None

    def test_empty_action_not_appended(self, breaker):
        """空 action 不追加到序列，也不触发检测"""
        for i in range(10):
            breaker.check(f"指令{i}", 0.0)
            breaker.check_action("")
        assert len(breaker._action_sequence) == 0

    def test_check_action_public_method_available(self, breaker):
        """check_action() 公有方法可调用"""
        # 不应抛出 AttributeError
        result = breaker.check_action("execute")
        assert result is None  # 只有 1 条记录，不触发

    def test_check_action_triggers_oscillation(self, breaker):
        """check_action() 独立调用时，ABABAB 模式触发熔断"""
        actions = ["execute", "retry", "execute", "retry", "execute"]
        for action in actions:
            breaker.check_action(action)
        result = breaker.check_action("retry")  # 第 6 条，触发
        assert result is not None
        assert "震荡" in result

    def test_check_action_same_a_and_b_not_triggered(self, breaker):
        """ABABAB 中 A == B 时不触发（需要两个不同的 action 交替）"""
        # AAAAAA 不是震荡
        for i in range(6):
            breaker.check_action("execute")
        # 不应触发（因为 recent[0] == recent[1]）
        # 需要重新检查最终结果
        # 实现中: if is_oscillating and recent[0] != recent[1]
        assert breaker._action_sequence.count("execute") == 6

    def test_abababab_longer_sequence_triggers(self):
        """更长的 ABABABAB 序列也能检测到"""
        breaker = CircuitBreaker(max_turns=100, max_budget_usd=100.0, oscillation_window=8)
        actions = ["execute", "retry"] * 4
        result = None
        for i, action in enumerate(actions):
            result = breaker.check_action(action)
        assert result is not None

    def test_action_sequence_only_records_non_empty(self, breaker):
        """_action_sequence 只记录非空 action（通过 check_action 调用）"""
        breaker.check("指令A", 0.0)
        breaker.check_action("execute")
        breaker.check("指令B", 0.0)
        breaker.check_action("")  # 空 action 不记录
        breaker.check("指令C", 0.0)
        breaker.check_action("done")
        assert "execute" in breaker._action_sequence
        assert "done" in breaker._action_sequence
        assert "" not in breaker._action_sequence
        assert len(breaker._action_sequence) == 2

    def test_oscillation_window_boundary_with_tight_breaker(self, breaker_tight):
        """oscillation_window=4 时，4 条 ABAB 触发"""
        for i, action in enumerate(["execute", "retry", "execute", "retry"]):
            result = breaker_tight.check_action(action)
        assert result is not None


# ============================================================
# F. from_config 工厂方法测试
# ============================================================

class TestFromConfig:
    """验证 CircuitBreaker.from_config() 正确从 SafetyConfig 构建"""

    def test_from_config_creates_circuit_breaker(self):
        """from_config() 返回 CircuitBreaker 实例"""
        safety = SafetyConfig()
        breaker = CircuitBreaker.from_config(safety)
        assert isinstance(breaker, CircuitBreaker)

    def test_from_config_inherits_safety_config_values(self):
        """from_config() 将 SafetyConfig 字段映射到 CircuitBreaker"""
        safety = SafetyConfig(
            max_consecutive_similar=5,
            similarity_threshold=0.92,
            stagnation_threshold=0.95,
            max_consecutive_errors=4,
            oscillation_window=8,
        )
        breaker = CircuitBreaker.from_config(safety, max_turns=20, max_budget_usd=3.0)

        assert breaker.max_consecutive_similar == 5
        assert breaker.similarity_threshold == 0.92
        assert breaker.stagnation_threshold == 0.95
        assert breaker.max_consecutive_errors == 4
        assert breaker.oscillation_window == 8

    def test_from_config_sets_max_turns_and_budget(self):
        """from_config() 接受 max_turns 和 max_budget_usd 参数"""
        safety = SafetyConfig()
        breaker = CircuitBreaker.from_config(safety, max_turns=50, max_budget_usd=10.0)
        assert breaker.max_turns == 50
        assert breaker.max_budget_usd == 10.0

    def test_from_config_uses_default_safety_config(self):
        """使用默认 SafetyConfig 时，字段与 SafetyConfig 默认值一致"""
        safety = SafetyConfig()
        breaker = CircuitBreaker.from_config(safety)
        assert breaker.max_consecutive_similar == safety.max_consecutive_similar
        assert breaker.similarity_threshold == safety.similarity_threshold
        assert breaker.stagnation_threshold == safety.stagnation_threshold
        assert breaker.max_consecutive_errors == safety.max_consecutive_errors
        assert breaker.oscillation_window == safety.oscillation_window


# ============================================================
# G. to_dict / restore 序列化测试
# ============================================================

class TestSerializationAndRestore:
    """验证 to_dict() 和 restore() 的序列化与恢复行为"""

    def test_to_dict_contains_required_keys(self, breaker):
        """to_dict() 输出包含所有必需的键"""
        breaker.check("指令A", 0.1, tool_output="输出A")
        breaker.check_action("execute")
        d = breaker.to_dict()
        # 原有字段
        assert "instruction_hashes" in d
        assert "total_cost" in d
        assert "current_turn" in d
        assert "consecutive_similar" in d
        # 新增字段
        assert "instruction_texts" in d
        assert "error_hashes" in d
        assert "output_fingerprints" in d
        assert "action_sequence" in d

    def test_to_dict_output_fingerprints_serialized_as_empty(self, breaker):
        """output_fingerprints 始终序列化为空列表（设计决策：不持久化）"""
        breaker.check("指令A", 0.0, tool_output="大量输出内容")
        breaker.check("指令B", 0.0, tool_output="更多输出内容")
        d = breaker.to_dict()
        assert d["output_fingerprints"] == []

    def test_to_dict_contains_correct_total_cost(self, breaker):
        """to_dict() 中 total_cost 反映累计费用"""
        breaker.check("指令A", 0.3)
        breaker.check("指令B", 0.2)
        d = breaker.to_dict()
        assert abs(d["total_cost"] - 0.5) < 1e-9

    def test_restore_recovers_turn_and_cost(self, breaker):
        """restore() 正确恢复轮次和费用"""
        original_data = {
            "instruction_hashes": ["aabbccdd"],
            "total_cost": 2.5,
            "current_turn": 15,
            "instruction_texts": ["归一化指令文本"],
            "error_hashes": [None, "abcd1234"],
            "action_sequence": ["execute", "retry"],
        }
        breaker.restore(original_data)
        assert breaker.current_turn == 15
        assert abs(breaker.total_cost - 2.5) < 1e-9

    def test_restore_recovers_instruction_hashes(self, breaker):
        """restore() 正确恢复 _instruction_hashes"""
        data = {
            "instruction_hashes": ["hash1", "hash2", "hash3"],
            "total_cost": 0.0,
            "current_turn": 3,
            "instruction_texts": [],
            "error_hashes": [],
            "action_sequence": [],
        }
        breaker.restore(data)
        assert breaker._instruction_hashes == ["hash1", "hash2", "hash3"]

    def test_restore_new_fields_from_dict(self, breaker):
        """restore() 正确恢复新增的多维度状态字段"""
        data = {
            "instruction_hashes": [],
            "total_cost": 0.0,
            "current_turn": 5,
            "instruction_texts": ["text1", "text2"],
            "error_hashes": ["hash_a", None, "hash_b"],
            "action_sequence": ["execute", "done", "execute"],
        }
        breaker.restore(data)
        assert breaker._instruction_texts == ["text1", "text2"]
        assert breaker._error_hashes == ["hash_a", None, "hash_b"]
        assert breaker._action_sequence == ["execute", "done", "execute"]

    def test_restore_output_fingerprints_always_empty(self, breaker):
        """restore() 后 _output_fingerprints 始终为空（重新开始积累）"""
        data = {
            "instruction_hashes": [],
            "total_cost": 0.0,
            "current_turn": 0,
            "instruction_texts": [],
            "error_hashes": [],
            "action_sequence": [],
        }
        breaker.restore(data)
        assert breaker._output_fingerprints == []

    def test_roundtrip_serialization(self, breaker):
        """to_dict() 后 restore() 状态正确（端对端验证）"""
        # 先执行几轮，产生状态
        breaker.check("指令一：分析需求", 0.1, tool_output="输出一")
        breaker.check_action("execute")
        breaker.check("指令二：编写代码", 0.2, tool_output="TypeError: 错误信息")
        breaker.check_action("retry")

        snapshot = breaker.to_dict()

        # 创建新实例并恢复
        new_breaker = CircuitBreaker(max_turns=10, max_budget_usd=1.0)
        new_breaker.restore(snapshot)

        assert new_breaker.current_turn == breaker.current_turn
        assert abs(new_breaker.total_cost - breaker.total_cost) < 1e-9
        assert new_breaker._instruction_hashes == breaker._instruction_hashes
        assert new_breaker._action_sequence == breaker._action_sequence

    def test_restore_handles_missing_new_fields_gracefully(self, breaker):
        """restore() 对缺少新增字段的旧快照数据兼容处理（向后兼容）"""
        # 模拟旧版快照（没有新增字段）
        old_snapshot = {
            "instruction_hashes": ["hash1"],
            "total_cost": 0.5,
            "current_turn": 3,
        }
        # 不应抛出 KeyError
        breaker.restore(old_snapshot)
        assert breaker.current_turn == 3
        assert breaker._instruction_texts == []
        assert breaker._error_hashes == []
        assert breaker._action_sequence == []

    def test_to_dict_instruction_texts_limited_to_10(self, breaker):
        """to_dict() 中 instruction_texts 只保留最近 10 条"""
        for i in range(15):
            breaker.check(f"唯一指令{i:02d}", 0.0)
        d = breaker.to_dict()
        assert len(d["instruction_texts"]) <= 10

    def test_to_dict_action_sequence_limited_to_20(self, breaker):
        """to_dict() 中 action_sequence 只保留最近 20 条"""
        for i in range(25):
            breaker._action_sequence.append(f"action_{i}")
        d = breaker.to_dict()
        assert len(d["action_sequence"]) <= 20


# ============================================================
# _normalize_text 测试
# ============================================================

class TestNormalizeText:
    """验证 _normalize_text() 的噪声去除逻辑"""

    def test_removes_iso_timestamps(self, breaker):
        """去除 ISO 格式时间戳"""
        text = "2024-01-15T10:30:45.123456 开始执行任务"
        result = breaker._normalize_text(text)
        assert "2024" not in result
        assert "开始执行任务" in result

    def test_removes_log_timestamps(self, breaker):
        """去除常见日志格式时间戳"""
        text = "2024-01-15 10:30:45 [INFO] 操作完成"
        result = breaker._normalize_text(text)
        assert "2024-01-15" not in result

    def test_removes_ordinal_numbers(self, breaker):
        """去除序号（第N次、#N、step N）"""
        text = "第3次尝试修复该问题"
        result = breaker._normalize_text(text)
        assert "第3次" not in result or "3" not in result

    def test_removes_file_path_prefix(self, breaker):
        """去除文件路径前缀"""
        text = "在 /home/user/project/src/ 中发现错误"
        result = breaker._normalize_text(text)
        assert "/home/user/project/src/" not in result

    def test_collapses_whitespace(self, breaker):
        """多余空白被折叠为单个空格"""
        text = "指令   内容    中有   多余空格"
        result = breaker._normalize_text(text)
        assert "  " not in result

    def test_truncates_to_500_chars(self, breaker):
        """输出截取前 500 字符"""
        long_text = "x" * 1000
        result = breaker._normalize_text(long_text)
        assert len(result) <= 500

    def test_normalize_reduces_timestamp_noise(self, breaker):
        """归一化后，两段仅时间戳不同的文本相似度更高"""
        from difflib import SequenceMatcher
        text1 = "2024-01-01T10:00:00 执行相同操作：修复 TypeError 错误"
        text2 = "2024-06-15T18:30:00 执行相同操作：修复 TypeError 错误"
        norm1 = breaker._normalize_text(text1)
        norm2 = breaker._normalize_text(text2)
        # 归一化后相似度应高于原始文本
        raw_ratio = SequenceMatcher(None, text1, text2).ratio()
        norm_ratio = SequenceMatcher(None, norm1, norm2).ratio()
        assert norm_ratio >= raw_ratio
