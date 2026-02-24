"""
Zellij Session 管理模块

为每个任务创建独立的 Zellij 会话，提供多面板界面：
  - 左侧：Manager Agent 日志（tail -f）
  - 右上：编码工具输出（tail -f）
  - 右下：任务状态（watch cat）

包含自动安装逻辑（下载预编译二进制到 ~/.local/bin）。
Zellij 不可用时自动降级为纯日志输出，不阻塞任务。
"""

import os
import shutil
import platform
import subprocess
import tempfile
import time
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class ZellijSession:
    """
    管理一个 Zellij 会话，对应一个 maestro 任务

    职责：
    - 检查/安装 Zellij
    - 生成 KDL 布局文件
    - 启动/attach/kill Zellij Session
    - 提供日志写入接口（供 tail -f 面板）
    """

    def __init__(self, task_id: str, log_dir: str = "~/.maestro/logs",
                 auto_install: bool = True):
        self.task_id = task_id
        self.session_name = f"maestro-{task_id}"
        self.auto_install = auto_install
        self.log_dir = Path(log_dir).expanduser()
        self.task_log_dir = self.log_dir / "tasks" / task_id
        self.task_log_dir.mkdir(parents=True, exist_ok=True)

        # 各面板的输出文件
        self.manager_log_file = self.task_log_dir / "manager.log"
        self.claude_log_file = self.task_log_dir / "claude.log"
        self.status_file = self.task_log_dir / "status.txt"

        # 初始化文件
        for f in [self.manager_log_file, self.claude_log_file, self.status_file]:
            f.touch()

        self._layout_file: Optional[str] = None
        self._zellij_path: Optional[str] = None

    def launch(self) -> bool:
        """
        启动 Zellij 会话

        返回 True 表示成功，False 表示 Zellij 不可用。
        """
        # 确保 Zellij 可用
        self._zellij_path = self._ensure_zellij()
        if not self._zellij_path:
            logger.warning("Zellij 不可用，降级为纯日志模式")
            return False

        # 检查是否已有同名会话（resume 场景）
        if self._session_exists():
            logger.info(f"复用已有 Zellij 会话: {self.session_name}")
            return True

        # 生成布局文件
        self._layout_file = self._create_layout_file()

        cmd = [
            self._zellij_path,
            "--session", self.session_name,
            "--layout", self._layout_file,
        ]

        # 在后台启动
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        time.sleep(1.5)  # 等待 Zellij 初始化

        logger.info(f"Zellij 会话已启动: {self.session_name}")
        return True

    def kill(self):
        """结束 Zellij 会话"""
        if self._zellij_path:
            subprocess.run(
                [self._zellij_path, "kill-session", self.session_name],
                capture_output=True,
            )
        if self._layout_file and Path(self._layout_file).exists():
            os.unlink(self._layout_file)

    def write_manager_log(self, message: str):
        """写入 Manager 日志面板"""
        timestamp = time.strftime("%H:%M:%S")
        with open(self.manager_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def write_tool_output(self, text: str):
        """写入编码工具输出面板"""
        with open(self.claude_log_file, "a", encoding="utf-8") as f:
            f.write(text)

    def update_status(self, status: str):
        """更新状态面板"""
        with open(self.status_file, "w", encoding="utf-8") as f:
            f.write(f"任务 ID: {self.task_id}\n")
            f.write(f"更新时间: {time.strftime('%H:%M:%S')}\n")
            f.write(f"状态: {status}\n")

    # ============================================================
    # Zellij 检查/安装
    # ============================================================

    def _ensure_zellij(self) -> Optional[str]:
        """确保 Zellij 已安装，返回可执行文件路径"""
        # 1. 检查 PATH 中是否已有
        zellij_path = shutil.which("zellij")
        if zellij_path:
            return zellij_path

        # 2. 检查 ~/.local/bin/
        local_path = Path.home() / ".local" / "bin" / "zellij"
        if local_path.exists() and os.access(local_path, os.X_OK):
            return str(local_path)

        # 3. 自动安装（如果启用）
        if self.auto_install:
            return self._install_zellij()

        logger.warning("Zellij 未安装，可通过 cargo install zellij 安装")
        return None

    def _install_zellij(self) -> Optional[str]:
        """下载安装预编译 Zellij 二进制"""
        system = platform.system().lower()
        if system != "linux":
            logger.warning(f"自动安装仅支持 Linux，当前系统: {system}")
            return None

        arch = platform.machine()
        arch_map = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
        zellij_arch = arch_map.get(arch)
        if not zellij_arch:
            logger.warning(f"不支持的架构: {arch}")
            return None

        version = "0.41.2"
        url = (
            f"https://github.com/zellij-org/zellij/releases/download/"
            f"v{version}/zellij-{zellij_arch}-unknown-linux-musl.tar.gz"
        )

        install_dir = Path.home() / ".local" / "bin"
        install_dir.mkdir(parents=True, exist_ok=True)
        target = install_dir / "zellij"

        try:
            import urllib.request
            import tarfile
            import io

            print(f"正在下载 Zellij v{version} ({zellij_arch})...")
            response = urllib.request.urlopen(url, timeout=60)
            with tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz") as tar:
                tar.extract("zellij", path=str(install_dir))

            target.chmod(0o755)
            print(f"Zellij 已安装到 {target}")

            if str(install_dir) not in os.environ.get("PATH", ""):
                print(f"提示：请将 {install_dir} 加入 PATH")

            return str(target)

        except Exception as e:
            logger.warning(f"Zellij 自动安装失败: {e}")
            print(f"手动安装: 下载 {url} 并解压到 PATH 目录中")
            return None

    def _session_exists(self) -> bool:
        """检查 Zellij 会话是否已存在"""
        try:
            result = subprocess.run(
                [self._zellij_path, "list-sessions"],
                capture_output=True, text=True, timeout=5,
            )
            return self.session_name in result.stdout
        except Exception:
            return False

    # ============================================================
    # KDL 布局
    # ============================================================

    def _create_layout_file(self) -> str:
        """生成 Zellij KDL 布局文件"""
        layout_content = f"""layout {{
    pane split_direction="vertical" {{
        pane name="Manager 日志" size="40%" {{
            command "tail"
            args "-f" "{self.manager_log_file}"
        }}
        pane split_direction="horizontal" {{
            pane name="编码工具输出" {{
                command "tail"
                args "-f" "{self.claude_log_file}"
            }}
            pane name="任务状态" size="15%" {{
                command "watch"
                args "-n1" "cat" "{self.status_file}"
            }}
        }}
    }}
}}
"""
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".kdl",
            prefix="maestro-",
            delete=False,
            encoding="utf-8"
        )
        tmp.write(layout_content)
        tmp.close()
        return tmp.name
