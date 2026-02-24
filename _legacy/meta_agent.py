"""
Meta-Agent 模块
负责分析 Claude Code 输出并决定下一步指令
支持多种大模型后端（OpenAI 兼容协议 + Anthropic 原生）
"""

import json
import logging
from typing import Optional
from openai import OpenAI
from autopilot.config import MetaAgentConfig

logger = logging.getLogger(__name__)

# 任务状态信号
SIGNAL_DONE = "##DONE##"
SIGNAL_BLOCKED = "##BLOCKED##"

DEFAULT_SYSTEM_PROMPT = """你是一个资深工程师助手，负责协调 Claude Code 完成用户需求。

你的职责：
1. 分析 Claude Code 的输出，判断任务进度
2. 当 Claude Code 遇到问题或报错时，给出具体解决指令
3. 当 Claude Code 请求确认（Yes/No）时，替用户做出合理决策
4. 判断任务何时真正完成（代码写完、测试通过、无报错）

回复规则：
- 需要向 Claude Code 发送指令 → 直接输出指令文本，简洁明了
- 任务已完成 → 回复 ##DONE##
- 遇到无法自动解决的阻塞问题 → 回复 ##BLOCKED## 原因说明
- 不要解释你的思考过程，直接给出指令
"""

# ============================================================
# Provider 工厂
# ============================================================

def _get_openai_compatible_client(config: MetaAgentConfig) -> OpenAI:
    """构建 OpenAI 兼容客户端（支持 DeepSeek、Ollama、Azure 等）"""
    kwargs = {"api_key": config.api_key or "ollama"}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    elif config.provider == "deepseek":
        kwargs["base_url"] = "https://api.deepseek.com"
    elif config.provider == "ollama":
        kwargs["base_url"] = "http://localhost:11434/v1"
        kwargs["api_key"] = "ollama"
    elif config.provider == "gemini":
        kwargs["base_url"] = "https://generativelanguage.googleapis.com/v1beta/openai/"
    return OpenAI(**kwargs)


class MetaAgent:
    """
    Meta-Agent：分析 Claude Code 输出，决定下一步动作
    
    支持的 provider:
      - openai      (GPT-4o 等)
      - anthropic   (Claude API，注意会额外收费)
      - deepseek    (性价比最高，推荐)
      - gemini      (Google)
      - ollama      (本地模型，完全免费)
      - azure       (Azure OpenAI)
      - 任何兼容 OpenAI 协议的服务
    """

    def __init__(self, config: MetaAgentConfig):
        self.config = config
        self.conversation_history = []
        self.system_prompt = config.system_prompt or DEFAULT_SYSTEM_PROMPT
        self._init_client()

    def _init_client(self):
        """初始化对应 provider 的客户端"""
        if self.config.provider == "anthropic":
            # 使用原生 Anthropic SDK
            from anthropic import Anthropic
            self._anthropic_client = Anthropic(api_key=self.config.api_key)
            self._use_anthropic = True
        else:
            # 其他全部走 OpenAI 兼容协议
            self._openai_client = _get_openai_compatible_client(self.config)
            self._use_anthropic = False

        logger.info(f"✅ Meta-Agent 初始化完成: {self.config.provider}/{self.config.model}")

    def start_task(self, requirement: str):
        """开始新任务，重置对话历史"""
        self.conversation_history = []
        self.conversation_history.append({
            "role": "user",
            "content": f"用户需求：{requirement}\n\n请给出第一条指令发送给 Claude Code。"
        })

    def decide(self, claude_output: str) -> str:
        """
        根据 Claude Code 的最新输出，决定下一步指令
        
        返回值：
          - 普通字符串：下一条指令
          - SIGNAL_DONE：任务完成
          - SIGNAL_BLOCKED：遇到阻塞
        """
        # 将 Claude Code 输出加入历史
        self.conversation_history.append({
            "role": "user",
            "content": f"Claude Code 输出：\n{claude_output}\n\n请分析输出并给出下一步指令。"
        })

        # 调用 Meta-Agent
        if self._use_anthropic:
            response = self._call_anthropic()
        else:
            response = self._call_openai_compatible()

        # 将 Meta-Agent 回复加入历史
        self.conversation_history.append({
            "role": "assistant",
            "content": response
        })

        logger.info(f"🤖 Meta-Agent 决策: {response[:100]}...")
        return response

    def _call_openai_compatible(self) -> str:
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.conversation_history)

        response = self._openai_client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            timeout=self.config.request_timeout,
            max_tokens=1000,
        )
        return response.choices[0].message.content.strip()

    def _call_anthropic(self) -> str:
        response = self._anthropic_client.messages.create(
            model=self.config.model,
            system=self.system_prompt,
            messages=self.conversation_history,
            max_tokens=1000,
        )
        return response.content[0].text.strip()

    def is_done(self, response: str) -> bool:
        return SIGNAL_DONE in response

    def is_blocked(self, response: str) -> bool:
        return SIGNAL_BLOCKED in response
