"""
测试公共 Fixture

提供 PromptLoader、ManagerConfig、ManagerAgent 等的通用测试工具。
"""

import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from maestro.config import ManagerConfig


@pytest.fixture
def tmp_prompts_dir(tmp_path):
    """创建临时 prompts 目录"""
    prompts_dir = tmp_path / "prompts"
    prompts_dir.mkdir()
    return prompts_dir


@pytest.fixture
def sample_prompt_content():
    """示例 prompt 内容"""
    return "你是资深工程师助手，负责分析编码工具的输出并决定下一步操作。"


@pytest.fixture
def sample_system_prompt_file(tmp_prompts_dir, sample_prompt_content):
    """创建一个包含 prompt 内容的临时文件"""
    prompt_file = tmp_prompts_dir / "system.md"
    prompt_file.write_text(sample_prompt_content, encoding="utf-8")
    return prompt_file


@pytest.fixture
def default_manager_config():
    """默认 ManagerConfig（无任何 prompt 文件配置）"""
    return ManagerConfig()


@pytest.fixture
def manager_config_with_prompt_file(sample_system_prompt_file):
    """配置了 system_prompt_file 的 ManagerConfig"""
    return ManagerConfig(
        system_prompt_file=str(sample_system_prompt_file),
    )


@pytest.fixture
def manager_config_with_inline_prompt():
    """配置了 system_prompt 内联字符串的 ManagerConfig"""
    return ManagerConfig(
        system_prompt="这是内联的 system prompt。",
    )


@pytest.fixture
def mock_openai_client():
    """Mock 的 OpenAI 客户端"""
    client = MagicMock()
    response = MagicMock()
    response.choices = [MagicMock()]
    response.choices[0].message.content = '{"action":"done","instruction":"","reasoning":"完成"}'
    response.usage = MagicMock()
    response.usage.prompt_tokens = 100
    response.usage.completion_tokens = 50
    client.chat.completions.create.return_value = response
    return client
