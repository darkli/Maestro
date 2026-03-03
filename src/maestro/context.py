"""
上下文管理模块

管理传给 Manager Agent 的对话上下文窗口：
  - 对话历史压缩（保留首轮 + 最近 N 轮 + 中间摘要）
  - 编码工具输出截断（1/3 头部 + 2/3 尾部）

截断策略说明：
  编码工具的输出通常是：进度日志（头部）→ 代码内容（中部）→ 执行结果/错误信息（尾部）。
  Manager 做决策主要依赖尾部的结果信息，所以保留更多尾部内容。
"""

from maestro.config import ContextConfig


class ContextManager:
    """管理传给 Manager 的上下文窗口"""

    def __init__(self, config: ContextConfig):
        self.max_recent_turns = config.max_recent_turns
        self.max_result_chars = config.max_result_chars

    def build_context(self, conversation_history: list[dict]) -> list[dict]:
        """
        构建传给 LLM 的消息列表

        策略：
        1. 历史不长时，全量传递
        2. 历史过长时：保留首轮（需求）+ 最近 N 轮 + 中间用摘要替代
        """
        # 每轮对话包含 user + assistant 两条消息
        threshold = self.max_recent_turns * 2
        if len(conversation_history) <= threshold:
            return conversation_history

        # 保留首轮（需求描述，通常是最重要的上下文）
        first_pair = conversation_history[:2]

        # 保留最近 N 轮
        recent = conversation_history[-threshold:]

        # 中间轮次生成摘要
        middle = conversation_history[2:-threshold]
        summary = self._summarize_middle(middle)

        return first_pair + [
            {"role": "user", "content": f"[中间 {len(middle) // 2} 轮的摘要]\n{summary}"},
            {"role": "assistant", "content": "已记录历史决策摘要，继续分析当前状态。"},
        ] + recent

    def truncate_output(self, output: str) -> str:
        """
        截断过长的编码工具输出

        保留 1/3 头部 + 2/3 尾部。
        尾部通常包含执行结果和错误信息，对 Manager 决策更关键。
        """
        if len(output) <= self.max_result_chars:
            return output

        head_chars = self.max_result_chars // 3
        tail_chars = self.max_result_chars * 2 // 3
        omitted = len(output) - head_chars - tail_chars

        return (
            output[:head_chars]
            + f"\n\n... [省略 {omitted} 字符] ...\n\n"
            + output[-tail_chars:]
        )

    def _summarize_middle(self, messages: list[dict]) -> str:
        """
        生成中间轮次的简短摘要

        从 assistant 消息（Manager 的决策/指令）中提取前 80 字符，
        保留最近 5 条，便于 Manager 了解之前的决策脉络。
        """
        summary_parts = []
        for i in range(0, len(messages), 2):
            if i + 1 < len(messages):
                # assistant 消息是 Manager 的指令
                instruction = messages[i + 1]["content"][:80]
                turn_num = i // 2 + 2  # +2 因为跳过了首轮
                summary_parts.append(f"  Turn {turn_num}: {instruction}")

        # 最多保留最近 5 行摘要
        return "\n".join(summary_parts[-5:])
