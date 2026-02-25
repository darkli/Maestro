"""
ManagerAgent Prompt 加载集成测试

测试 ManagerAgent 中 prompt 加载优先级、热加载注入点、
standalone_chat/free_chat 的 prompt 外置化。
对应功能点 6-12 和验收标准 AC-8 ~ AC-14。
"""

import time
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from maestro.config import ManagerConfig

# 注意：以下导入的常量/类在阶段 4 实现后生效
# 当前阶段（TDD）预期所有测试均 FAIL
from maestro.manager_agent import (
    ManagerAgent,
    PromptLoader,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_CHAT_PROMPT,
    DEFAULT_FREE_CHAT_PROMPT,
    DECISION_STYLES,
)


# ============================================================
# Prompt 加载优先级
# ============================================================

class TestManagerAgentPromptPriority:
    """测试 system prompt 的加载优先级：文件 > 内联字符串 > 默认常量"""

    @patch.object(ManagerAgent, '_init_client')
    def test_no_config_uses_default_prompt(self, mock_init):
        """AC-11: 不配置时使用 DEFAULT_SYSTEM_PROMPT"""
        config = ManagerConfig()
        agent = ManagerAgent(config)

        assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT

    @patch.object(ManagerAgent, '_init_client')
    def test_inline_prompt_overrides_default(self, mock_init):
        """配置 system_prompt 内联字符串时使用内联值"""
        inline_prompt = "自定义内联 prompt"
        config = ManagerConfig(system_prompt=inline_prompt)
        agent = ManagerAgent(config)

        assert agent.system_prompt == inline_prompt

    @patch.object(ManagerAgent, '_init_client')
    def test_file_prompt_overrides_inline(self, mock_init, tmp_path):
        """AC-8: 配置 system_prompt_file 时文件优先于内联字符串"""
        file_content = "文件中的 prompt 内容"
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text(file_content, encoding="utf-8")

        config = ManagerConfig(
            system_prompt="这个应该被忽略",
            system_prompt_file=str(prompt_file),
        )
        agent = ManagerAgent(config)

        assert agent.system_prompt == file_content

    @patch.object(ManagerAgent, '_init_client')
    def test_file_prompt_without_inline(self, mock_init, tmp_path):
        """仅配置 system_prompt_file（无内联字符串）"""
        file_content = "仅文件的 prompt"
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text(file_content, encoding="utf-8")

        config = ManagerConfig(system_prompt_file=str(prompt_file))
        agent = ManagerAgent(config)

        assert agent.system_prompt == file_content

    @patch.object(ManagerAgent, '_init_client')
    def test_nonexistent_file_generates_default(self, mock_init, tmp_path):
        """AC-10: prompt 文件不存在时自动生成默认内容并使用"""
        prompt_file = tmp_path / "prompts" / "system.md"
        config = ManagerConfig(system_prompt_file=str(prompt_file))
        agent = ManagerAgent(config)

        # 应该使用 DEFAULT_SYSTEM_PROMPT（自动生成的文件内容）
        assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT
        # 文件应该已被生成
        assert prompt_file.exists()


# ============================================================
# 决策风格（decision_style）
# ============================================================

class TestDecisionStyle:
    """测试决策风格追加到 system prompt"""

    def test_decision_styles_dict_exists(self):
        """DECISION_STYLES 字典包含预定义风格"""
        assert "default" in DECISION_STYLES
        assert "conservative" in DECISION_STYLES
        assert "aggressive" in DECISION_STYLES

    def test_default_style_appends_nothing(self):
        """default 风格不追加额外内容"""
        assert DECISION_STYLES["default"] == ""

    def test_conservative_style_has_content(self):
        """conservative 风格有预定义的决策原则"""
        assert len(DECISION_STYLES["conservative"]) > 0
        assert "ask_user" in DECISION_STYLES["conservative"]

    def test_aggressive_style_has_content(self):
        """aggressive 风格有预定义的决策原则"""
        assert len(DECISION_STYLES["aggressive"]) > 0

    @patch.object(ManagerAgent, '_init_client')
    def test_conservative_style_appended_to_prompt(self, mock_init):
        """配置 conservative 风格时追加到 prompt 末尾"""
        config = ManagerConfig(decision_style="conservative")
        agent = ManagerAgent(config)

        assert DEFAULT_SYSTEM_PROMPT in agent.system_prompt
        assert DECISION_STYLES["conservative"] in agent.system_prompt

    @patch.object(ManagerAgent, '_init_client')
    def test_aggressive_style_appended_to_prompt(self, mock_init):
        """配置 aggressive 风格时追加到 prompt 末尾"""
        config = ManagerConfig(decision_style="aggressive")
        agent = ManagerAgent(config)

        assert DEFAULT_SYSTEM_PROMPT in agent.system_prompt
        assert DECISION_STYLES["aggressive"] in agent.system_prompt

    @patch.object(ManagerAgent, '_init_client')
    def test_default_style_no_change(self, mock_init):
        """配置 default 风格时 prompt 不变"""
        config = ManagerConfig(decision_style="default")
        agent = ManagerAgent(config)

        assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT

    @patch.object(ManagerAgent, '_init_client')
    def test_empty_style_no_change(self, mock_init):
        """不配置 decision_style 时 prompt 不变"""
        config = ManagerConfig(decision_style="")
        agent = ManagerAgent(config)

        assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT

    @patch.object(ManagerAgent, '_init_client')
    def test_unknown_style_no_change(self, mock_init):
        """未知的 decision_style 值不追加内容"""
        config = ManagerConfig(decision_style="unknown_style")
        agent = ManagerAgent(config)

        assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT

    @patch.object(ManagerAgent, '_init_client')
    def test_style_appended_to_file_prompt(self, mock_init, tmp_path):
        """文件 prompt + 决策风格组合"""
        file_content = "自定义 prompt"
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text(file_content, encoding="utf-8")

        config = ManagerConfig(
            system_prompt_file=str(prompt_file),
            decision_style="conservative",
        )
        agent = ManagerAgent(config)

        assert file_content in agent.system_prompt
        assert DECISION_STYLES["conservative"] in agent.system_prompt


# ============================================================
# 热加载注入点
# ============================================================

class TestHotReloadInjection:
    """测试 decide() 和 start_task() 中的热加载触发"""

    @patch.object(ManagerAgent, '_init_client')
    @patch.object(ManagerAgent, '_call_llm_with_retry')
    def test_decide_triggers_prompt_reload(self, mock_llm, mock_init, tmp_path):
        """AC-9: decide() 调用时自动检查并重新加载 prompt"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("初始 prompt", encoding="utf-8")

        config = ManagerConfig(system_prompt_file=str(prompt_file))
        agent = ManagerAgent(config)
        assert agent.system_prompt == "初始 prompt"

        # 模拟 LLM 返回
        mock_llm.return_value = '{"action":"done","instruction":"","reasoning":"完成"}'

        # 修改 prompt 文件
        time.sleep(0.1)
        prompt_file.write_text("更新后的 prompt", encoding="utf-8")

        # 初始化对话历史以避免 decide() 内部逻辑问题
        agent.conversation_history = [
            {"role": "user", "content": "测试"}
        ]

        # 调用 decide 应该触发热加载
        agent.decide("")
        assert agent.system_prompt == "更新后的 prompt"

    @patch.object(ManagerAgent, '_init_client')
    def test_start_task_triggers_prompt_reload(self, mock_init, tmp_path):
        """start_task() 调用时重新加载 prompt"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("初始 prompt", encoding="utf-8")

        config = ManagerConfig(system_prompt_file=str(prompt_file))
        agent = ManagerAgent(config)
        assert agent.system_prompt == "初始 prompt"

        # 修改 prompt 文件
        time.sleep(0.1)
        prompt_file.write_text("任务启动时的新 prompt", encoding="utf-8")

        agent.start_task("新任务需求")
        assert agent.system_prompt == "任务启动时的新 prompt"

    @patch.object(ManagerAgent, '_init_client')
    def test_no_file_config_skip_reload(self, mock_init):
        """未配置 system_prompt_file 时 decide/start_task 不执行文件 IO"""
        config = ManagerConfig(system_prompt="固定 prompt")
        agent = ManagerAgent(config)

        original_prompt = agent.system_prompt
        agent.start_task("需求")

        assert agent.system_prompt == original_prompt


# ============================================================
# standalone_chat prompt 外置
# ============================================================

class TestStandaloneChatPrompt:
    """测试 standalone_chat 方法的 prompt 外置化"""

    @patch.object(ManagerAgent, '_init_client')
    def test_standalone_chat_uses_default_prompt_when_no_file(self, mock_init):
        """AC-12: 不配置 chat_prompt_file 时使用 DEFAULT_CHAT_PROMPT"""
        config = ManagerConfig()
        agent = ManagerAgent(config)

        # 验证 DEFAULT_CHAT_PROMPT 常量存在且非空
        assert len(DEFAULT_CHAT_PROMPT) > 0
        assert "任务" in DEFAULT_CHAT_PROMPT or "AI" in DEFAULT_CHAT_PROMPT

    @patch.object(ManagerAgent, '_init_client')
    def test_standalone_chat_uses_file_prompt(self, mock_init, tmp_path):
        """AC-12: 配置 chat_prompt_file 时从文件加载 prompt"""
        chat_prompt = "自定义聊天 prompt"
        chat_file = tmp_path / "chat.md"
        chat_file.write_text(chat_prompt, encoding="utf-8")

        config = ManagerConfig(chat_prompt_file=str(chat_file))
        agent = ManagerAgent(config)
        agent._use_anthropic = False
        agent._openai_client = MagicMock()

        # 设置 mock 返回
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "测试回复"
        agent._openai_client.chat.completions.create.return_value = mock_response

        agent.standalone_chat("上下文", "用户消息")

        # 验证调用时使用了文件中的 prompt
        call_args = agent._openai_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == chat_prompt


# ============================================================
# free_chat prompt 外置
# ============================================================

class TestFreeChatPrompt:
    """测试 free_chat 方法的 prompt 外置化"""

    @patch.object(ManagerAgent, '_init_client')
    def test_free_chat_uses_default_prompt_when_no_file(self, mock_init):
        """不配置 free_chat_prompt_file 时使用 DEFAULT_FREE_CHAT_PROMPT"""
        config = ManagerConfig()
        agent = ManagerAgent(config)

        assert len(DEFAULT_FREE_CHAT_PROMPT) > 0

    @patch.object(ManagerAgent, '_init_client')
    def test_free_chat_uses_file_prompt(self, mock_init, tmp_path):
        """AC-12: 配置 free_chat_prompt_file 时从文件加载 prompt"""
        free_prompt = "自定义自由聊天 prompt"
        free_file = tmp_path / "free_chat.md"
        free_file.write_text(free_prompt, encoding="utf-8")

        config = ManagerConfig(free_chat_prompt_file=str(free_file))
        agent = ManagerAgent(config)
        agent._use_anthropic = False
        agent._openai_client = MagicMock()

        # 设置 mock 返回
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "测试回复"
        agent._openai_client.chat.completions.create.return_value = mock_response

        agent.free_chat([], "你好")

        # 验证调用时使用了文件中的 prompt
        call_args = agent._openai_client.chat.completions.create.call_args
        messages = call_args.kwargs.get("messages") or call_args[1].get("messages")
        system_msg = messages[0]
        assert system_msg["role"] == "system"
        assert system_msg["content"] == free_prompt


# ============================================================
# 向后兼容性
# ============================================================

class TestBackwardCompatibility:
    """测试 prompt 外置化的向后兼容性"""

    @patch.object(ManagerAgent, '_init_client')
    def test_no_new_config_same_behavior(self, mock_init):
        """AC-11: 不配置任何新字段时行为与改造前完全一致"""
        config = ManagerConfig()
        agent = ManagerAgent(config)

        assert agent.system_prompt == DEFAULT_SYSTEM_PROMPT

    @patch.object(ManagerAgent, '_init_client')
    def test_existing_inline_prompt_still_works(self, mock_init):
        """已有的 system_prompt 内联配置仍然有效"""
        custom = "已有的自定义 prompt"
        config = ManagerConfig(system_prompt=custom)
        agent = ManagerAgent(config)

        assert agent.system_prompt == custom

    @patch.object(ManagerAgent, '_init_client')
    def test_conflict_file_wins_over_inline(self, mock_init, tmp_path):
        """同时配置 file 和 inline 时，file 优先"""
        file_content = "文件优先"
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text(file_content, encoding="utf-8")

        config = ManagerConfig(
            system_prompt="内联应被忽略",
            system_prompt_file=str(prompt_file),
        )
        agent = ManagerAgent(config)

        assert agent.system_prompt == file_content

    def test_default_constants_unchanged(self):
        """DEFAULT_SYSTEM_PROMPT 常量保留且内容合理"""
        assert len(DEFAULT_SYSTEM_PROMPT) > 100
        assert "JSON" in DEFAULT_SYSTEM_PROMPT
        assert "action" in DEFAULT_SYSTEM_PROMPT
