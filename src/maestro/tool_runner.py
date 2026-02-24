"""
编码工具运行器模块

支持两种模式：
  - claude: Claude Code 专用模式（-p --output-format json，精确解析费用/会话）
  - generic: 通用 subprocess 包装（适配 Gemini CLI、Aider 等任何 CLI 工具）

generic 模式的约定：
  command + extra_args + instruction 拼成完整命令。
  工具的 stdout+stderr 作为输出传给 Manager Agent 分析。
  不支持费用追踪和会话恢复。
"""

import json
import time
import logging
import subprocess
from dataclasses import dataclass
from typing import Optional

from maestro.config import CodingToolConfig

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    """单轮执行结果"""
    output: str                       # 工具输出文本
    session_id: str = ""              # 会话 ID（仅 Claude 有）
    cost_usd: float = 0.0            # 本轮费用（仅 Claude 有）
    duration_ms: int = 0              # 本轮耗时
    is_error: bool = False            # 是否出错
    error_type: str = ""              # 错误类型


class ToolRunner:
    """
    编码工具运行器

    type=claude 时使用 Claude Code 的 JSON 模式（精确解析费用/会话）。
    type=generic 时作为通用 subprocess 包装（适配任何 CLI 工具）。
    """

    def __init__(self, config: CodingToolConfig, working_dir: str):
        self.config = config
        self.working_dir = working_dir
        self.session_id: Optional[str] = None

    def run(self, instruction: str) -> RunResult:
        """执行一轮指令，返回结果"""
        if self.config.type == "claude":
            return self._run_claude(instruction)
        else:
            return self._run_generic(instruction)

    def resume_session(self, session_id: str):
        """恢复到指定会话（仅 Claude 模式有效）"""
        if self.config.type == "claude":
            self.session_id = session_id

    def _run_claude(self, instruction: str) -> RunResult:
        """Claude Code 专用：-p --output-format json，解析 JSON 输出"""
        cmd = [self.config.command, "-p", "--output-format", "json"]
        if self.config.auto_approve:
            cmd.append("--dangerously-skip-permissions")
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        cmd.append(instruction)

        logger.info(f"执行 Claude Code（session={self.session_id or '新建'}）")
        logger.debug(f"指令: {instruction[:100]}...")

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.config.timeout, cwd=self.working_dir
            )
            duration_ms = int((time.time() - start) * 1000)
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"Claude Code 超时 ({self.config.timeout}s)")
            return RunResult(
                output="[错误] Claude Code 执行超时",
                duration_ms=duration_ms,
                is_error=True,
                error_type="timeout",
            )
        except FileNotFoundError:
            logger.error(f"找不到命令: {self.config.command}")
            return RunResult(
                output=f"[错误] 找不到命令: {self.config.command}，请确认 Claude Code 已安装",
                is_error=True,
                error_type="command_not_found",
            )

        # 解析 Claude 的 JSON 输出
        try:
            data = json.loads(result.stdout)
            self.session_id = data.get("session_id", self.session_id)
            return RunResult(
                output=data.get("result", ""),
                session_id=data.get("session_id", ""),
                cost_usd=data.get("cost_usd", 0.0),
                duration_ms=duration_ms,
                is_error=data.get("is_error", False),
                error_type=data.get("subtype", ""),
            )
        except json.JSONDecodeError:
            # JSON 解析失败，降级为纯文本
            logger.warning("Claude Code 输出非 JSON，降级为纯文本模式")
            output = result.stdout
            if result.stderr:
                output += "\n" + result.stderr
            return RunResult(
                output=output,
                duration_ms=duration_ms,
                is_error=result.returncode != 0,
            )

    def _run_generic(self, instruction: str) -> RunResult:
        """通用模式：直接运行命令，捕获 stdout"""
        cmd = [self.config.command] + self.config.extra_args + [instruction]

        logger.info(f"执行编码工具: {self.config.command}")
        logger.debug(f"完整命令: {' '.join(cmd[:5])}...")

        start = time.time()
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.config.timeout, cwd=self.working_dir
            )
            duration_ms = int((time.time() - start) * 1000)
        except subprocess.TimeoutExpired:
            duration_ms = int((time.time() - start) * 1000)
            logger.error(f"编码工具超时 ({self.config.timeout}s)")
            return RunResult(
                output=f"[错误] 编码工具执行超时 ({self.config.timeout}s)",
                duration_ms=duration_ms,
                is_error=True,
                error_type="timeout",
            )
        except FileNotFoundError:
            logger.error(f"找不到命令: {self.config.command}")
            return RunResult(
                output=f"[错误] 找不到命令: {self.config.command}",
                is_error=True,
                error_type="command_not_found",
            )

        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        return RunResult(
            output=output,
            duration_ms=duration_ms,
            is_error=result.returncode != 0,
        )
