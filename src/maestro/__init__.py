"""
Maestro — 用 Manager Agent 自动驱动编码工具完成开发任务

核心组件：
  - CLI: 命令行入口
  - Orchestrator: 调度核心
  - ManagerAgent: 外层决策 AI
  - ToolRunner: 编码工具运行器（Claude Code / Gemini CLI 等）
  - TelegramDaemon: Telegram Bot 远程控制
"""

__version__ = "0.1.0"
