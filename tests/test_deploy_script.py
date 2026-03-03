"""
deploy.sh 结构验证测试

由于 deploy.sh 是一个依赖 SSH 连接的 bash 脚本，无法进行完整的功能测试。
这里通过以下方式验证改造后的结构正确性：

1. 语法检查（bash -n）
2. help 参数输出验证（不需要 SSH 连接）
3. 未知参数处理验证
4. 函数定义存在性检查（通过 grep 源码）
5. 认证流程验证：安装后统一手动登录，卸载时只卸载软件不删认证
"""

import subprocess
import pytest
from pathlib import Path

DEPLOY_SCRIPT = Path(__file__).parent.parent / "deploy.sh"


class TestDeployScriptSyntax:
    """验证 deploy.sh 的 bash 语法正确性"""

    def test_bash_syntax_check(self):
        """deploy.sh 语法无错误（bash -n）"""
        result = subprocess.run(
            ["bash", "-n", str(DEPLOY_SCRIPT)],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"bash 语法检查失败: {result.stderr}"


class TestDeployScriptHelp:
    """验证 help 参数处理"""

    def test_help_flag_shows_usage(self):
        """deploy.sh help 显示帮助信息并退出"""
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

    def test_do_tool_auth_function_exists(self):
        """do_tool_auth() 函数已定义"""
        assert "do_tool_auth()" in self.script_content

    def test_do_init_function_exists(self):
        """do_init() 组合函数已定义"""
        assert "do_init()" in self.script_content

    def test_do_update_function_exists(self):
        """do_update() 组合函数已定义"""
        assert "do_update()" in self.script_content

    def test_do_deploy_function_removed(self):
        """原 do_deploy() 函数已被移除"""
        import re
        func_def_pattern = re.compile(r'^\s*do_deploy\s*\(\)', re.MULTILINE)
        assert not func_def_pattern.search(self.script_content), \
            "do_deploy() 函数应已被拆分移除"

    def test_menu_has_four_items(self):
        """交互菜单含功能选项"""
        assert "首次部署" in self.script_content
        assert "业务逻辑更新" in self.script_content or "业务更新" in self.script_content
        assert "查看状态" in self.script_content
        assert "清理卸载" in self.script_content

    def test_subcommand_parsing_exists(self):
        """参数解析逻辑存在（SUBCOMMAND 变量）"""
        assert "SUBCOMMAND" in self.script_content

    def test_update_checks_venv_exists(self):
        """update 模式检查 .venv 是否存在"""
        assert ".venv" in self.script_content
        assert "do_update" in self.script_content

    def test_update_restarts_systemd(self):
        """update 后检查并重启 maestro-daemon"""
        assert "maestro-daemon" in self.script_content
        assert "systemctl restart maestro-daemon" in self.script_content \
            or "systemctl restart" in self.script_content

    def test_prompts_backup_in_update(self):
        """update 模式备份/恢复 prompts/ 目录"""
        assert "prompts" in self.script_content

    def test_git_mode_has_chown(self):
        """git 部署块包含 chown 设置目录所有权"""
        import re
        git_block = re.search(
            r'DEPLOY_METHOD.*git.*?ok "git 部署完成"',
            self.script_content, re.DOTALL
        )
        assert git_block, "找不到 git 部署代码块"
        assert "chown" in git_block.group(), "git 部署块应包含 chown"

    def test_systemd_no_longer_starts_on_claude_file_only(self):
        """systemd 初装不应仅凭 Claude 凭据文件存在自动启动"""
        assert '[[ -n "$ANTHROPIC_API_KEY" ]]' in self.script_content
        remote_block = self.script_content.split('systemd 服务已创建并启动')[0]
        assert '[[ -s "$RUN_HOME/.claude/.credentials.json" ]]' not in remote_block, \
            "systemd 初装阶段不应仅凭 Claude 凭据文件存在自动启动"

    def test_codex_summary_checks_auth_json(self):
        """_print_summary 中 codex 使用 test -s auth.json 精确检测"""
        import re
        summary_block = re.search(
            r'_print_summary\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert summary_block, "找不到 _print_summary 函数"
        block = summary_block.group()
        assert "test -s" in block, "_print_summary 应使用 test -s 精确检测认证文件"

    def test_vps_ssh_key_tilde_expansion(self):
        """包含 tilde 展开逻辑"""
        assert 'VPS_SSH_KEY="${VPS_SSH_KEY/#\\~/$HOME}"' in self.script_content, \
            "应对 VPS_SSH_KEY 做 tilde 展开"

    def test_vps_user_root_constraint(self):
        """存在 VPS_USER != root 的 die 检查"""
        import re
        pattern = r'VPS_USER.*!=.*root.*die'
        assert re.search(pattern, self.script_content, re.DOTALL), \
            "应有 VPS_USER 非 root 时 die 的硬约束"


class TestDeployScriptAuthRefactor:
    """验证认证流程重构：安装后统一手动登录，卸载时只卸载软件不删认证"""

    @pytest.fixture(autouse=True)
    def load_script(self):
        """读取脚本内容"""
        self.script_content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    # ---- 备份/恢复机制已移除 ----

    def test_no_backup_tool_auth_function(self):
        """_backup_tool_auth() 函数已删除"""
        assert "_backup_tool_auth()" not in self.script_content

    def test_no_restore_tool_auth_function(self):
        """_restore_tool_auth() 函数已删除"""
        assert "_restore_tool_auth()" not in self.script_content

    def test_no_check_claude_ready_function(self):
        """_check_claude_ready() 函数已删除"""
        assert "_check_claude_ready()" not in self.script_content

    def test_no_check_codex_ready_function(self):
        """_check_codex_ready() 函数已删除"""
        assert "_check_codex_ready()" not in self.script_content

    def test_no_auth_backup_base_variable(self):
        """AUTH_BACKUP_BASE 变量已删除"""
        assert "AUTH_BACKUP_BASE" not in self.script_content

    # ---- 安装阶段：统一手动登录 ----

    def test_claude_api_key_mode_skips_login(self):
        """Claude API Key 模式跳过登录"""
        assert "API Key 模式" in self.script_content

    def test_claude_login_prompt_exists(self):
        """安装阶段存在 claude login 手动登录引导"""
        assert "claude login" in self.script_content

    def test_codex_login_prompt_exists(self):
        """安装阶段存在 codex login --device-auth 手动登录引导"""
        assert "codex login --device-auth" in self.script_content

    def test_ensure_codex_file_store_preserved(self):
        """_ensure_codex_file_store() 函数保留"""
        assert "_ensure_codex_file_store()" in self.script_content

    def test_no_restore_in_do_tool_auth(self):
        """do_tool_auth 中不再调用 _restore_tool_auth"""
        import re
        auth_block = re.search(
            r'do_tool_auth\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert auth_block, "找不到 do_tool_auth 函数"
        block = auth_block.group()
        assert "_restore_tool_auth" not in block
        assert "_backup_tool_auth" not in block

    # ---- 卸载阶段：只卸载软件不删认证 ----

    def test_clean_asks_uninstall_claude(self):
        """卸载阶段提问是"是否卸载 Claude Code"而非删除认证"""
        assert "是否卸载 Claude Code" in self.script_content

    def test_clean_asks_uninstall_codex(self):
        """卸载阶段提问是"是否卸载 Codex CLI"而非删除认证"""
        assert "是否卸载 Codex CLI" in self.script_content

    def test_clean_no_remove_claude_auth_prompt(self):
        """不再询问"是否删除 Claude Code 认证"""
        assert "是否删除 Claude Code 认证" not in self.script_content

    def test_clean_no_remove_codex_auth_prompt(self):
        """不再询问"是否删除 Codex CLI 认证"""
        assert "是否删除 Codex CLI 认证" not in self.script_content

    def test_clean_no_remove_auth_variables(self):
        """REMOVE_CLAUDE_AUTH / REMOVE_CODEX_AUTH 变量已删除"""
        assert "REMOVE_CLAUDE_AUTH" not in self.script_content
        assert "REMOVE_CODEX_AUTH" not in self.script_content

    def test_clean_uses_uninstall_variables(self):
        """do_clean 使用 UNINSTALL_CLAUDE / UNINSTALL_CODEX 变量"""
        assert "UNINSTALL_CLAUDE" in self.script_content
        assert "UNINSTALL_CODEX" in self.script_content

    def test_clean_no_rm_rf_claude_dir(self):
        """清理脚本不再 rm -rf ~/.claude"""
        import re
        clean_block = re.search(
            r'do_clean\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 do_clean 函数"
        block = clean_block.group()
        assert 'rm -rf "$RUN_HOME/.claude"' not in block

    def test_clean_no_rm_rf_codex_dir(self):
        """清理脚本不再 rm -rf ~/.codex"""
        import re
        clean_block = re.search(
            r'do_clean\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 do_clean 函数"
        block = clean_block.group()
        assert 'rm -rf "$RUN_HOME/.codex"' not in block

    def test_clean_no_unconditional_npm_global_delete(self):
        """不再无条件删除 .npm-global 目录"""
        import re
        clean_block = re.search(
            r'do_clean\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 do_clean 函数"
        block = clean_block.group()
        assert 'rm -rf "$RUN_HOME/.npm-global"' not in block

    def test_clean_uses_npm_uninstall(self):
        """卸载时使用 npm uninstall 官方卸载命令"""
        import re
        clean_block = re.search(
            r'do_clean\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 do_clean 函数"
        block = clean_block.group()
        assert "npm uninstall -g @anthropic-ai/claude-code" in block
        assert "npm uninstall -g @openai/codex" in block

    def test_clean_nodejs_respects_tool_retention(self):
        """Node.js 卸载需感知编码工具保留状态（避免留下不可用的工具）"""
        import re
        clean_block = re.search(
            r"CLEAN_SCRIPT=\$\(cat << 'CLEAN_EOF'.*?^CLEAN_EOF$",
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 CLEAN_SCRIPT heredoc"
        block = clean_block.group()
        # Node.js 卸载逻辑中应检查 UNINSTALL_CLAUDE/UNINSTALL_CODEX
        assert "UNINSTALL_CLAUDE" in block and "UNINSTALL_CODEX" in block, \
            "Node.js 卸载应检查编码工具是否被保留"

    def test_daemon_not_started_without_auth(self):
        """do_tool_auth 在编码工具未认证时不应启动 daemon"""
        import re
        auth_block = re.search(
            r'do_tool_auth\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert auth_block, "找不到 do_tool_auth 函数"
        block = auth_block.group()
        assert "all_authed" in block, \
            "do_tool_auth 应跟踪认证状态决定是否启动 daemon"
        assert "暂不启动" in block, \
            "未完成认证时应提示 daemon 暂不启动"

    def test_clean_script_has_set_e(self):
        """CLEAN_SCRIPT 使用完整 set -euo pipefail（命令失败时不被静默吞掉）"""
        import re
        # 匹配 heredoc 开始到独占一行的 CLEAN_EOF
        clean_block = re.search(
            r"CLEAN_SCRIPT=\$\(cat << 'CLEAN_EOF'.*?^CLEAN_EOF$",
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 CLEAN_SCRIPT heredoc"
        block = clean_block.group()
        assert "set -euo pipefail" in block, \
            "CLEAN_SCRIPT 必须使用 set -euo pipefail"


class TestDeployScriptRobustness:
    """验证既有问题修复：变量注入安全、检查顺序、交互一致性"""

    @pytest.fixture(autouse=True)
    def load_script(self):
        """读取脚本内容"""
        self.script_content = DEPLOY_SCRIPT.read_text(encoding="utf-8")

    def test_vars_section_uses_safe_quoting(self):
        """VARS_SECTION 使用 _qv (printf %q) 安全转义，而非裸单引号"""
        assert "_qv()" in self.script_content, "应定义 _qv 安全转义函数"
        # VARS_SECTION 中应使用 _qv 调用
        import re
        vars_block = re.search(
            r'VARS_SECTION=".*?"',
            self.script_content, re.DOTALL
        )
        assert vars_block, "找不到 VARS_SECTION 定义"
        block = vars_block.group()
        assert "$(_qv" in block, "VARS_SECTION 应使用 _qv 转义变量值"
        # 不应有裸单引号包裹的 ${VAR} 模式
        assert "='${" not in block, \
            "VARS_SECTION 不应使用 '${VAR}' 裸单引号包裹"

    def test_clean_vars_injection_uses_safe_quoting(self):
        """do_clean 变量注入也使用 _qv 安全转义"""
        import re
        clean_block = re.search(
            r'do_clean\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 do_clean 函数"
        block = clean_block.group()
        assert "$(_qv" in block, "do_clean 变量注入应使用 _qv 转义"

    def test_do_update_checks_venv_before_user_creation(self):
        """do_update 先检查 .venv 再创建用户（避免 die 时遗留孤立用户）"""
        import re
        update_block = re.search(
            r'do_update\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert update_block, "找不到 do_update 函数"
        block = update_block.group()
        venv_pos = block.find(".venv")
        user_create_pos = block.find("useradd")
        assert venv_pos < user_create_pos, \
            "do_update 应先检查 .venv 再创建用户"

    def test_gai_conf_cleanup_no_global_blank_line_removal(self):
        """gai.conf 清理不做全局空行删除（避免误删用户空行）"""
        import re
        clean_block = re.search(
            r"CLEAN_SCRIPT=.*?CLEAN_EOF",
            self.script_content, re.DOTALL
        )
        assert clean_block, "找不到 CLEAN_SCRIPT heredoc"
        block = clean_block.group()
        # 不应包含全局空行删除 sed 模式
        assert '/^$/N;/^\\n$/d' not in block, \
            "不应对 gai.conf 做全局连续空行删除"

    def test_do_clean_confirmation_style(self):
        """do_clean 确认交互使用统一的 [y/N] 风格"""
        import re
        clean_block = re.search(
            r'do_clean\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert clean_block, "找不到 do_clean 函数"
        block = clean_block.group()
        assert "输入 yes 继续" not in block, \
            "do_clean 不应使用 '输入 yes 继续'，应统一使用 [y/N]"

    def test_yaml_str_function_exists(self):
        """_yaml_str() YAML 转义函数已定义"""
        assert "_yaml_str()" in self.script_content

    def test_config_yaml_uses_yaml_str_for_api_key(self):
        """config.yaml 生成时 API Key 等敏感值使用 _yaml_str 转义"""
        # 检查 do_update_config 中的用法
        import re
        update_config_block = re.search(
            r'do_update_config\(\).*?^}',
            self.script_content, re.DOTALL | re.MULTILINE
        )
        assert update_config_block, "找不到 do_update_config 函数"
        block = update_config_block.group()
        assert '_yaml_str "$MANAGER_API_KEY"' in block, \
            "do_update_config 应对 MANAGER_API_KEY 使用 _yaml_str"
        assert '_yaml_str "$TELEGRAM_BOT_TOKEN"' in block, \
            "do_update_config 应对 TELEGRAM_BOT_TOKEN 使用 _yaml_str"


class TestDeployScriptUnknownArgs:
    """验证未知参数处理"""

    def test_unknown_subcommand_shows_error(self):
        """deploy.sh foo 显示错误或 usage"""
        result = subprocess.run(
            ["bash", str(DEPLOY_SCRIPT), "foo"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        assert result.returncode != 0 or "用法" in result.stdout or "usage" in result.stdout.lower()
