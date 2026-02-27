# 原始需求输入

**功能名称**: focus-auto-resume
**提交时间**: 2026-02-26
**用户描述**:

优化 focus 机制：当用户 focus 一条未完成的任务时，自动加载 Claude Code 对应的 session，保证对话随时可以继续，不会因超时而失效。

**背景上下文**（来自对话讨论）:

1. 当前问题：任务执行中 Manager 返回 ask_user，Orchestrator 轮询 inbox.txt 等待用户回复，但有超时限制。如果用户过了一天才回来，进程已因超时退出（状态变为 FAILED），inbox.txt 无人消费，用户通过 Telegram 发的消息石沉大海。
2. 用户期望：focus 一条失效的任务后发消息，系统应自动恢复任务执行（利用 checkpoint.json 中的 Claude Code session ID），让对话无缝继续。
3. 相关能力：`maestro resume` 已能加载 checkpoint、恢复 Claude Code session（--resume session_id）、恢复 Manager 对话历史，但需要用户手动执行。
4. 用户不使用 Zellij，纯后台进程模式。
