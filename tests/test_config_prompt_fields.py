"""
ManagerConfig 新增字段测试

测试 system_prompt_file、chat_prompt_file、free_chat_prompt_file、
decision_style 四个新增字段的默认值和 dataclass 行为。
对应功能点 6、8、9、12 和验收标准 AC-11、AC-13。
"""

import pytest
from dataclasses import fields as dataclass_fields

from maestro.config import ManagerConfig, load_config, _dict_to_dataclass


# ============================================================
# 新增字段存在性和默认值
# ============================================================

class TestManagerConfigNewFields:
    """测试 ManagerConfig 新增的 prompt 相关字段"""

    def test_system_prompt_file_field_exists(self):
        """ManagerConfig 包含 system_prompt_file 字段"""
        field_names = {f.name for f in dataclass_fields(ManagerConfig)}
        assert "system_prompt_file" in field_names

    def test_chat_prompt_file_field_exists(self):
        """ManagerConfig 包含 chat_prompt_file 字段"""
        field_names = {f.name for f in dataclass_fields(ManagerConfig)}
        assert "chat_prompt_file" in field_names

    def test_free_chat_prompt_file_field_exists(self):
        """ManagerConfig 包含 free_chat_prompt_file 字段"""
        field_names = {f.name for f in dataclass_fields(ManagerConfig)}
        assert "free_chat_prompt_file" in field_names

    def test_decision_style_field_exists(self):
        """ManagerConfig 包含 decision_style 字段"""
        field_names = {f.name for f in dataclass_fields(ManagerConfig)}
        assert "decision_style" in field_names

    def test_default_system_prompt_file_is_empty(self):
        """system_prompt_file 默认值为空字符串"""
        config = ManagerConfig()
        assert config.system_prompt_file == ""

    def test_default_chat_prompt_file_is_empty(self):
        """chat_prompt_file 默认值为空字符串"""
        config = ManagerConfig()
        assert config.chat_prompt_file == ""

    def test_default_free_chat_prompt_file_is_empty(self):
        """free_chat_prompt_file 默认值为空字符串"""
        config = ManagerConfig()
        assert config.free_chat_prompt_file == ""

    def test_default_decision_style_is_empty(self):
        """decision_style 默认值为空字符串"""
        config = ManagerConfig()
        assert config.decision_style == ""


# ============================================================
# 与现有字段兼容
# ============================================================

class TestManagerConfigCompatibility:
    """测试新字段不影响现有字段"""

    def test_existing_fields_unchanged(self):
        """现有字段的默认值不受影响"""
        config = ManagerConfig()
        assert config.provider == "deepseek"
        assert config.model == "deepseek-chat"
        assert config.api_key == ""
        assert config.base_url is None
        assert config.max_turns == 30
        assert config.max_budget_usd == 5.0
        assert config.request_timeout == 60
        assert config.retry_count == 3
        assert config.system_prompt == ""

    def test_dict_to_dataclass_with_new_fields(self):
        """_dict_to_dataclass 正确处理新字段"""
        data = {
            "provider": "openai",
            "system_prompt_file": "prompts/system.md",
            "decision_style": "conservative",
        }
        config = _dict_to_dataclass(ManagerConfig, data)
        assert config.provider == "openai"
        assert config.system_prompt_file == "prompts/system.md"
        assert config.decision_style == "conservative"

    def test_dict_to_dataclass_without_new_fields(self):
        """AC-11: 旧配置文件（无新字段）正常工作"""
        # 模拟旧版 config.yaml 只有原有字段
        data = {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "api_key": "test-key",
            "max_turns": 50,
        }
        config = _dict_to_dataclass(ManagerConfig, data)
        assert config.provider == "deepseek"
        assert config.system_prompt_file == ""  # 使用默认值
        assert config.chat_prompt_file == ""    # 使用默认值
        assert config.decision_style == ""      # 使用默认值

    def test_dict_to_dataclass_ignores_unknown_fields(self):
        """未知字段被忽略（不崩溃）"""
        data = {
            "provider": "openai",
            "unknown_field": "should be ignored",
        }
        config = _dict_to_dataclass(ManagerConfig, data)
        assert config.provider == "openai"
        assert not hasattr(config, "unknown_field")

    def test_all_new_fields_are_optional(self):
        """所有新字段都有默认值，不是必填"""
        # 无参数构造应该成功
        config = ManagerConfig()
        assert config is not None

        # 仅传原有字段也应该成功
        config = ManagerConfig(provider="openai", model="gpt-4o")
        assert config.system_prompt_file == ""
        assert config.chat_prompt_file == ""
        assert config.free_chat_prompt_file == ""
        assert config.decision_style == ""
