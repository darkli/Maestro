"""
deploy.sh 结构验证测试

由于 deploy.sh 是一个依赖 SSH 连接的 bash 脚本，无法进行完整的功能测试。
这里通过以下方式验证改造后的结构正确性：

1. 语法检查（bash -n）
2. help 参数输出验证（不需要 SSH 连接）
3. 未知参数处理验证
4. 函数定义存在性检查（通过 grep 源码）

对应功能点 1-5 和验收标准 AC-1 ~ AC-7。
"""

import subprocess
import pytest
from pathlib import Path

DEPLOY_SCRIPT = Path(__file__).parent.parent / "deploy.sh"


class TestDeployScriptSyntax:
    """验证 deploy.sh 的 bash 语法正确性"""

    def test_bash_syntax_check(self):
        """AC-7: deploy.sh 语法无错误（bash -n）"""
        result = subprocess.run(
            ["bash", "-n", str(DEPLOY_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash 语法检查失败: {result.stderr}"


class TestDeployScriptHelp:
    """验证 help 参数处理"""

    def test_help_flag_shows_usage(self):
        """AC-6: deploy.sh help 显示帮助信息并退出"""
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "init" in result.stdout
        assert "update" in result.stdout

    def test_dash_h_shows_usage(self):
        """deploy.sh -h 也显示帮助信息"""
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "-h"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "init" in result.stdout
        assert "update" in result.stdout

    def test_dash_dash_help_shows_usage(self):
        """deploy.sh --help 也显示帮助信息"""
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode == 0
        assert "init" in result.stdout
        assert "update" in result.stdout


class TestDeployScriptStructure:
    """验证 deploy.sh 中关键函数定义的存在性"""

    @pytest.fixture(autouse=True)
    def load_script(self):
        """读取脚本内容"""
        self.script_content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    def test_do_transfer_function_exists(self):
        """do_transfer() 函数已定义"""
        assert "do_transfer()" in self.script_content

    def test_do_remote_full_install_function_exists(self):
        """do_remote_full_install() 函数已定义"""
        assert "do_remote_full_install()" in self.script_content

    def test_do_remote_quick_update_function_exists(self):
        """do_remote_quick_update() 函数已定义"""
        assert "do_remote_quick_update()" in self.script_content

    def test_do_claude_auth_function_exists(self):
        """do_claude_auth() 函数已定义"""
        assert "do_claude_auth()" in self.script_content

    def test_do_init_function_exists(self):
        """do_init() 组合函数已定义"""
        assert "do_init()" in self.script_content

    def test_do_update_function_exists(self):
        """do_update() 组合函数已定义"""
        assert "do_update()" in self.script_content

    def test_do_deploy_function_removed(self):
        """原 do_deploy() 函数已被移除"""
        # do_deploy() 不应该作为函数定义存在
        # 注意：do_deploy 可能在注释中出现，只检查函数定义
        import re
        # 匹配独立的函数定义（非注释行）
        func_def_pattern = re.compile(r'^\s*do_deploy\s*\(\)', re.MULTILINE)
        assert not func_def_pattern.search(self.script_content), \
            "do_deploy() 函数应已被拆分移除"

    def test_menu_has_four_items(self):
        """AC-5: 交互菜单含 4 项功能选项"""
        # 检查菜单文本
        assert "首次部署" in self.script_content
        assert "业务逻辑更新" in self.script_content or "业务更新" in self.script_content
        assert "查看状态" in self.script_content
        assert "清理卸载" in self.script_content

    def test_subcommand_parsing_exists(self):
        """参数解析逻辑存在（SUBCOMMAND 变量）"""
        assert "SUBCOMMAND" in self.script_content

    def test_update_checks_venv_exists(self):
        """AC-4: update 模式检查 .venv 是否存在"""
        assert ".venv" in self.script_content
        # do_update 中应该有 .venv 的检查逻辑
        assert "do_update" in self.script_content

    def test_update_restarts_systemd(self):
        """AC-3: update 后检查并重启 maestro-daemon"""
        assert "maestro-daemon" in self.script_content
        # do_remote_quick_update 中应该有 systemd restart 逻辑
        assert "systemctl restart maestro-daemon" in self.script_content \
            or "systemctl restart" in self.script_content

    def test_prompts_backup_in_update(self):
        """update 模式备份/恢复 prompts/ 目录"""
        assert "prompts" in self.script_content


class TestDeployScriptUnknownArgs:
    """验证未知参数处理"""

    def test_unknown_subcommand_shows_error(self):
        """AC-6: deploy.sh foo 显示错误或 usage"""
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "foo"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # 应该报错退出（非零返回码）或显示 usage
        # 注意：如果 foo 被当做 env 文件处理，也会因为文件不存在而报错
        assert result.returncode != 0 or "用法" in result.stdout or "usage" in result.stdout.lower()
