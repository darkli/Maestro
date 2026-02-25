"""
PromptLoader 单元测试

测试 prompt 文件的加载、缓存、热加载、默认文件生成、异常处理。
对应功能点 6-11 和验收标准 AC-8 ~ AC-12。
"""

import os
import time
import pytest
from pathlib import Path
from unittest.mock import patch

# 注意：PromptLoader 尚未实现，以下导入在阶段 4 实现后生效
# 当前阶段（TDD）预期所有测试均 FAIL
from maestro.manager_agent import PromptLoader


# ============================================================
# 基本加载功能
# ============================================================

class TestPromptLoaderBasicLoad:
    """测试 PromptLoader 的基本文件加载功能"""

    def test_load_existing_file(self, tmp_path, sample_prompt_content):
        """加载已存在的 prompt 文件，返回文件内容"""
        # AC-8: 配置 system_prompt_file 后，ManagerAgent 从文件加载 prompt
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text(sample_prompt_content, encoding="utf-8")

        loader = PromptLoader()
        result = loader.load(str(prompt_file), "默认值")

        assert result == sample_prompt_content

    def test_load_returns_stripped_content(self, tmp_path):
        """加载文件时去除首尾空白"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("\n  内容  \n\n", encoding="utf-8")

        loader = PromptLoader()
        result = loader.load(str(prompt_file), "默认值")

        assert result == "内容"

    def test_load_with_absolute_path(self, tmp_path, sample_prompt_content):
        """使用绝对路径加载 prompt 文件"""
        prompt_file = tmp_path / "prompts" / "system.md"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(sample_prompt_content, encoding="utf-8")

        loader = PromptLoader()
        result = loader.load(str(prompt_file.absolute()), "默认值")

        assert result == sample_prompt_content


# ============================================================
# 默认文件生成
# ============================================================

class TestPromptLoaderDefaultGeneration:
    """测试 prompt 文件不存在时的自动生成"""

    def test_generate_default_when_file_not_exists(self, tmp_path):
        """AC-10: prompt 文件不存在时自动生成默认内容"""
        prompt_file = tmp_path / "prompts" / "system.md"
        default_content = "默认 system prompt 内容"

        loader = PromptLoader()
        result = loader.load(str(prompt_file), default_content)

        # 应该返回默认内容
        assert result == default_content
        # 应该自动创建文件
        assert prompt_file.exists()
        # 文件内容应该是默认内容（末尾有换行）
        assert prompt_file.read_text(encoding="utf-8").strip() == default_content

    def test_generate_default_creates_parent_dirs(self, tmp_path):
        """自动生成时创建必要的父目录"""
        prompt_file = tmp_path / "a" / "b" / "c" / "system.md"
        default_content = "深层目录的默认内容"

        loader = PromptLoader()
        loader.load(str(prompt_file), default_content)

        assert prompt_file.exists()
        assert prompt_file.parent.exists()

    def test_generate_default_on_permission_error(self, tmp_path):
        """无法创建默认文件时 fallback 到默认值（不崩溃）"""
        # 使用一个不可写的路径
        prompt_file = Path("/proc/nonexistent/system.md")
        default_content = "默认内容"

        loader = PromptLoader()
        result = loader.load(str(prompt_file), default_content)

        # 应该 fallback 到默认值而不是抛异常
        assert result == default_content


# ============================================================
# 缓存与热加载
# ============================================================

class TestPromptLoaderHotReload:
    """测试基于 mtime 的缓存和热加载机制"""

    def test_cache_hit_returns_same_content(self, tmp_path, sample_prompt_content):
        """文件未修改时命中缓存，不重新读取"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text(sample_prompt_content, encoding="utf-8")

        loader = PromptLoader()
        result1 = loader.load(str(prompt_file), "默认值")
        result2 = loader.load(str(prompt_file), "默认值")

        assert result1 == result2
        assert result1 == sample_prompt_content

    def test_hot_reload_on_file_change(self, tmp_path):
        """AC-9: 修改 prompt 文件后，下次加载自动使用新内容"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("原始内容", encoding="utf-8")

        loader = PromptLoader()
        result1 = loader.load(str(prompt_file), "默认值")
        assert result1 == "原始内容"

        # 修改文件（确保 mtime 变更）
        time.sleep(0.1)  # 确保文件系统 mtime 精度足够
        prompt_file.write_text("修改后的内容", encoding="utf-8")

        result2 = loader.load(str(prompt_file), "默认值")
        assert result2 == "修改后的内容"

    def test_cache_persists_across_multiple_loads(self, tmp_path):
        """多次加载同一文件，缓存持续有效"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("固定内容", encoding="utf-8")

        loader = PromptLoader()
        for _ in range(10):
            result = loader.load(str(prompt_file), "默认值")
            assert result == "固定内容"

    def test_multiple_files_cached_independently(self, tmp_path):
        """不同文件独立缓存"""
        file_a = tmp_path / "a.md"
        file_b = tmp_path / "b.md"
        file_a.write_text("内容 A", encoding="utf-8")
        file_b.write_text("内容 B", encoding="utf-8")

        loader = PromptLoader()
        assert loader.load(str(file_a), "默认") == "内容 A"
        assert loader.load(str(file_b), "默认") == "内容 B"

        # 修改 A 不影响 B 的缓存
        time.sleep(0.1)
        file_a.write_text("修改后 A", encoding="utf-8")

        assert loader.load(str(file_a), "默认") == "修改后 A"
        assert loader.load(str(file_b), "默认") == "内容 B"


# ============================================================
# 异常处理与 Fallback
# ============================================================

class TestPromptLoaderErrorHandling:
    """测试各种异常情况的处理"""

    def test_empty_file_fallback_to_default(self, tmp_path):
        """文件内容为空时使用默认值"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("", encoding="utf-8")

        loader = PromptLoader()
        result = loader.load(str(prompt_file), "默认内容")

        assert result == "默认内容"

    def test_whitespace_only_file_fallback_to_default(self, tmp_path):
        """文件仅含空白字符时使用默认值"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("   \n\n   \t  ", encoding="utf-8")

        loader = PromptLoader()
        result = loader.load(str(prompt_file), "默认内容")

        assert result == "默认内容"

    def test_non_utf8_file_fallback_to_default(self, tmp_path):
        """文件编码非 UTF-8 时 fallback 到默认值"""
        prompt_file = tmp_path / "system.md"
        # 写入 GBK 编码的中文，UTF-8 读取会失败
        prompt_file.write_bytes(b"\xc4\xe3\xba\xc3")  # "你好" 的 GBK 编码

        loader = PromptLoader()
        result = loader.load(str(prompt_file), "默认内容")

        assert result == "默认内容"

    def test_file_deleted_after_cache_fallback_to_default(self, tmp_path):
        """文件被删除后 fallback 到默认值"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("临时内容", encoding="utf-8")

        loader = PromptLoader()
        result1 = loader.load(str(prompt_file), "默认值")
        assert result1 == "临时内容"

        # 删除文件
        prompt_file.unlink()

        # 下次加载应该重新生成默认文件（或 fallback）
        result2 = loader.load(str(prompt_file), "默认值")
        assert result2 == "默认值"

    def test_mtime_unreadable_fallback_to_default(self, tmp_path):
        """无法读取 mtime 时 fallback 到默认值"""
        prompt_file = tmp_path / "system.md"
        prompt_file.write_text("内容", encoding="utf-8")

        loader = PromptLoader()

        # Mock os.path.getmtime 抛出 OSError
        with patch("os.path.getmtime", side_effect=OSError("权限不足")):
            result = loader.load(str(prompt_file), "默认值")

        assert result == "默认值"
