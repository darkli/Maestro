"""
Claude Code 驱动模块
使用 pexpect 控制 Claude Code 进程，模拟人工交互
"""

import re
import time
import logging
import pexpect
from typing import Optional, Callable
from autopilot.config import ClaudeCodeConfig

logger = logging.getLogger(__name__)

# Claude Code 交互模式下可能出现的提示词（正则）
INTERACTION_PATTERNS = [
    # 权限/确认类
    (r"Do you want to proceed\?.*\(y/n\)", "yes"),
    (r"Continue\?.*\(y/n\)", "yes"),
    (r"Are you sure\?.*\(y/n\)", "yes"),
    (r"Would you like to.*\(y/n\)", "yes"),
    (r"\[Y/n\]", "y"),
    (r"\[y/N\]", "y"),
    # Claude Code 特有的确认
    (r"Allow this tool to run\?", "1"),      # 选 "Yes, allow"
    (r"Approve all tools", "2"),
]

# 标志 Claude Code 完成一轮响应（等待用户输入）
PROMPT_READY_PATTERN = r"Human:|>\s*$|\$\s*$"

# 标志 Claude Code 遇到错误
ERROR_PATTERNS = [
    r"Error:",
    r"error:",
    r"FAILED",
    r"Traceback \(most recent call last\)",
    r"Command failed",
]


class ClaudeCodeDriver:
    """
    控制 Claude Code 进程的驱动器
    
    职责：
    - 启动/停止 Claude Code 进程
    - 发送指令
    - 读取输出
    - 自动处理权限确认等交互
    """

    def __init__(self, config: ClaudeCodeConfig, output_callback: Optional[Callable] = None):
        self.config = config
        self.output_callback = output_callback  # 实时输出回调（用于 Zellij 显示）
        self.child: Optional[pexpect.spawn] = None
        self._output_buffer = []

    def start(self):
        """启动 Claude Code 进程"""
        cmd = self.config.command
        if self.config.auto_approve:
            cmd += " --dangerously-skip-permissions"

        cwd = self.config.working_dir or None
        logger.info(f"🚀 启动 Claude Code: {cmd}")

        self.child = pexpect.spawn(
            cmd,
            encoding="utf-8",
            timeout=self.config.response_timeout,
            cwd=cwd,
            dimensions=(50, 220),  # 给足够宽的终端
        )

        # 等待初始提示出现
        self.child.expect([r"Human:", r"Claude", pexpect.TIMEOUT], timeout=15)
        logger.info("✅ Claude Code 已启动")

    def send_instruction(self, instruction: str) -> str:
        """
        发送指令给 Claude Code，等待响应完成后返回输出
        
        自动处理中途出现的交互确认
        """
        if not self.child:
            raise RuntimeError("Claude Code 未启动，请先调用 start()")

        logger.debug(f"📤 发送指令: {instruction[:80]}...")
        self.child.sendline(instruction)

        output_parts = []
        start_time = time.time()

        while True:
            # 超时检查
            elapsed = time.time() - start_time
            if elapsed > self.config.response_timeout:
                logger.warning("⏰ 等待 Claude Code 响应超时")
                break

            # 构建期望模式列表
            patterns = [
                PROMPT_READY_PATTERN,          # 0: 响应完成，等待输入
                pexpect.TIMEOUT,               # 1: 超时
                pexpect.EOF,                   # 2: 进程结束
            ]
            # 加入交互确认模式
            interaction_patterns = [p[0] for p in INTERACTION_PATTERNS]
            for p in interaction_patterns:
                patterns.append(p)             # 3+: 需要确认

            try:
                index = self.child.expect(patterns, timeout=30)
            except pexpect.exceptions.TIMEOUT:
                # 读取缓冲区内容，继续等待
                chunk = self.child.before or ""
                if chunk:
                    output_parts.append(chunk)
                    self._emit_output(chunk)
                continue
            except pexpect.exceptions.EOF:
                break

            # 读取匹配前的输出
            chunk = self.child.before or ""
            if chunk:
                output_parts.append(chunk)
                self._emit_output(chunk)

            if index == 0:
                # 响应完成
                break
            elif index == 1:
                # 短暂超时，继续等待
                continue
            elif index == 2:
                # 进程结束
                logger.warning("⚠️  Claude Code 进程意外结束")
                break
            else:
                # 需要交互确认
                pattern_index = index - 3
                auto_response = INTERACTION_PATTERNS[pattern_index][1]
                matched_text = self.child.after or ""
                logger.info(f"🤝 自动确认: '{matched_text.strip()}' → '{auto_response}'")
                output_parts.append(f"\n[自动确认: {matched_text.strip()} → {auto_response}]\n")
                self.child.sendline(auto_response)

        full_output = "".join(output_parts)
        self._output_buffer.append(full_output)
        return full_output

    def stop(self):
        """停止 Claude Code 进程"""
        if self.child and self.child.isalive():
            self.child.sendline("/exit")
            try:
                self.child.expect(pexpect.EOF, timeout=5)
            except:
                self.child.terminate(force=True)
        logger.info("🛑 Claude Code 已停止")

    def get_full_output(self) -> str:
        """获取完整输出历史"""
        return "\n".join(self._output_buffer)

    def _emit_output(self, text: str):
        """触发实时输出回调"""
        if self.output_callback and text.strip():
            self.output_callback(text)

    def has_error(self, output: str) -> bool:
        """检测输出中是否包含错误"""
        for pattern in ERROR_PATTERNS:
            if re.search(pattern, output):
                return True
        return False
