# 原始需求输入

**功能名称**: stream-json-toolrunner
**提交时间**: 2026-02-26 11:54
**用户描述**:

为 ToolRunner 的 Claude Code 调用模式添加 stream-json 实时流式输出支持。当前使用 subprocess.run + --output-format json 的阻塞模式，需要改为 subprocess.Popen + --output-format stream-json 的流式模式，实现实时输出推送能力（Zellij 面板、Telegram 等），同时保留 session_id/cost_usd 等结构化数据的提取。

**附加上下文**:

（未提供）
