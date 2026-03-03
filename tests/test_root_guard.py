"""
_check_not_root() 行为测试

验证 CLI 的 root guard 机制：
- root 用户被拒绝
- 普通用户正常放行
- MAESTRO_ALLOW_ROOT 环境变量可强制跳过
- 所有依赖 ~/.maestro 的业务 handler 均调用了 root guard
"""

import os
import pytest
from unittest.mock import patch

from maestro.cli import _check_not_root


class TestCheckNotRoot:
    """测试 _check_not_root() 函数行为"""

    def test_rejects_root(self):
        """euid=0 时 sys.exit(1)"""
        with patch("os.geteuid", return_value=0), \
             patch.dict(os.environ, {}, clear=True):
            with pytest.raises(SystemExit) as exc_info:
                _check_not_root()
            assert exc_info.value.code == 1

    def test_allows_non_root(self):
        """euid=1000 正常通过"""
        with patch("os.geteuid", return_value=1000):
            _check_not_root()  # 不应抛出异常

    def test_allows_root_with_env_override(self):
        """MAESTRO_ALLOW_ROOT=1 时放行"""
        with patch("os.geteuid", return_value=0), \
             patch.dict(os.environ, {"MAESTRO_ALLOW_ROOT": "1"}):
            _check_not_root()  # 不应抛出异常

    def test_rejects_root_with_allow_root_zero(self):
        """MAESTRO_ALLOW_ROOT=0 时仍拒绝（0 不等于真值）"""
        with patch("os.geteuid", return_value=0), \
             patch.dict(os.environ, {"MAESTRO_ALLOW_ROOT": "0"}):
            with pytest.raises(SystemExit) as exc_info:
                _check_not_root()
            assert exc_info.value.code == 1

    def test_rejects_root_with_allow_root_false(self):
        """MAESTRO_ALLOW_ROOT=false 时仍拒绝"""
        with patch("os.geteuid", return_value=0), \
             patch.dict(os.environ, {"MAESTRO_ALLOW_ROOT": "false"}):
            with pytest.raises(SystemExit) as exc_info:
                _check_not_root()
            assert exc_info.value.code == 1


# 所有依赖 ~/.maestro 路径的业务 handler，必须在第一行调用 _check_not_root()
# 键为 parametrize 标签，值为实际函数名
_GUARDED_HANDLERS = {
    "run": "_handle_run",
    "list": "_handle_list",
    "status": "_handle_status",
    "ask": "_handle_ask",
    "chat": "_handle_chat",
    "abort": "_handle_abort",
    "resume": "_handle_resume",
    "report": "_handle_report",
    "daemon": "_handle_daemon",
    "switch": "_handle_switch",
    "worker": "_handle_worker",
}


class TestHandlerCallsGuard:
    """验证所有业务 handler 调用了 root guard"""

    @pytest.mark.parametrize("handler_name", _GUARDED_HANDLERS.keys())
    def test_handler_calls_root_guard(self, handler_name):
        """_handle_{handler_name} 调用了 _check_not_root"""
        import maestro.cli as cli_mod
        fn_name = _GUARDED_HANDLERS[handler_name]
        handler_fn = getattr(cli_mod, fn_name)
        with patch("maestro.cli._check_not_root", side_effect=SystemExit(1)) as mock_guard:
            with pytest.raises(SystemExit):
                handler_fn(None)
            mock_guard.assert_called_once()
