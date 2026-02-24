"""
Zellij Session 管理模块
为每个任务创建独立的 Zellij 会话，提供多面板界面
"""

import os
import time
import subprocess
import tempfile
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Zellij KDL 布局模板
# 左侧：Meta-Agent 日志面板
# 右侧上：Claude Code 输出
# 右侧下：任务状态/控制
ZELLIJ_LAYOUT_TEMPLATE = """
layout {{
    pane_groups {{
        pane_group size="{left_ratio}" {{
            pane name="Meta-Agent 日志" {{
                command "tail"
                args "-f" "{log_file}"
            }}
        }}
        pane_group size="{right_ratio}" {{
            pane name="Claude Code" {{
                command "tail"
                args "-f" "{claude_output_file}"
            }}
            pane size="10%" name="状态" {{
                command "watch"
                args "-n1" "cat {status_file}"
            }}
        }}
    }}
    pane size="1" borderless=true {{
        plugin location="zellij:tab-bar"
    }}
    pane size="2" borderless=true {{
        plugin location="zellij:status-bar"
    }}
}}
"""

# 简化版：直接用 zellij action 命令动态创建面板
SIMPLE_LAYOUT = """
layout {
    pane split_direction="vertical" {
        pane name="📋 Meta-Agent 日志" size="40%"
        pane split_direction="horizontal" {
            pane name="⚡ Claude Code 输出"
            pane name="📊 任务状态" size="15%"
        }
    }
}
"""


class ZellijSession:
    """
    管理一个 Zellij 会话，对应一个 autopilot 任务
    """

    def __init__(self, task_id: str, log_dir: str = "~/.autopilot/logs"):
        self.task_id = task_id
        self.session_name = f"autopilot-{task_id}"
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # 各面板的输出文件（tail -f 方式实时显示）
        self.meta_log_file = self.log_dir / f"{task_id}-meta.log"
        self.claude_log_file = self.log_dir / f"{task_id}-claude.log"
        self.status_file = self.log_dir / f"{task_id}-status.txt"

        # 初始化文件
        for f in [self.meta_log_file, self.claude_log_file, self.status_file]:
            f.touch()

        self._layout_file: Optional[str] = None

    def is_zellij_available(self) -> bool:
        """检查 Zellij 是否安装"""
        try:
            result = subprocess.run(["zellij", "--version"], capture_output=True, timeout=3)
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def launch(self) -> bool:
        """
        启动 Zellij 会话
        返回 True 表示成功，False 表示 Zellij 不可用
        """
        if not self.is_zellij_available():
            logger.warning("⚠️  Zellij 未安装，跳过 UI 界面。可通过 cargo install zellij 安装。")
            return False

        # 生成布局文件
        self._layout_file = self._create_layout_file()

        cmd = [
            "zellij",
            "--session", self.session_name,
            "--layout", self._layout_file,
        ]

        # 在后台启动（detached）
        subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)  # 等待 Zellij 初始化

        logger.info(f"✅ Zellij 会话已启动: {self.session_name}")
        return True

    def attach(self):
        """attach 到已有 Zellij 会话（前台，供用户观看）"""
        subprocess.run(["zellij", "attach", self.session_name])

    def kill(self):
        """结束 Zellij 会话"""
        subprocess.run(
            ["zellij", "kill-session", self.session_name],
            capture_output=True
        )
        if self._layout_file and Path(self._layout_file).exists():
            os.unlink(self._layout_file)

    def write_meta_log(self, message: str):
        """写入 Meta-Agent 日志面板"""
        timestamp = time.strftime("%H:%M:%S")
        with open(self.meta_log_file, "a", encoding="utf-8") as f:
            f.write(f"[{timestamp}] {message}\n")

    def write_claude_output(self, text: str):
        """写入 Claude Code 输出面板"""
        with open(self.claude_log_file, "a", encoding="utf-8") as f:
            f.write(text)

    def update_status(self, status: str):
        """更新状态面板"""
        with open(self.status_file, "w", encoding="utf-8") as f:
            f.write(f"任务 ID: {self.task_id}\n")
            f.write(f"更新时间: {time.strftime('%H:%M:%S')}\n")
            f.write(f"状态: {status}\n")

    def _create_layout_file(self) -> str:
        """生成 Zellij KDL 布局文件"""
        layout_content = f"""
layout {{
    pane split_direction="vertical" {{
        pane name="📋 Meta-Agent 日志" size="40%" {{
            command "tail"
            args "-f" "{self.meta_log_file}"
        }}
        pane split_direction="horizontal" {{
            pane name="⚡ Claude Code 输出" {{
                command "tail"
                args "-f" "{self.claude_log_file}"
            }}
            pane name="📊 任务状态" size="15%" {{
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
            prefix="autopilot-",
            delete=False,
            encoding="utf-8"
        )
        tmp.write(layout_content)
        tmp.close()
        return tmp.name
