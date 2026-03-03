"""
Manager Agent 模块

负责分析编码工具输出并决定下一步指令。
整合了 LLM 调用（多 provider 支持）、JSON 输出解析、action 路由、
重试逻辑和费用估算。

支持的 provider:
  - openai      (GPT-4o 等)
  - anthropic   (Claude API，使用原生 SDK)
  - deepseek    (性价比最高，推荐)
  - gemini      (Google)
  - ollama      (本地模型，完全免费)
  - azure       (Azure OpenAI)
  - 任何兼容 OpenAI 协议的服务（自定义 base_url）
"""

import json
import os
import re
import time
import logging
from enum import Enum
from pathlib import Path
from typing import Optional

from maestro.config import ManagerConfig

logger = logging.getLogger(__name__)


# ============================================================
# Action 枚举
# ============================================================

class ManagerAction(str, Enum):
    """Manager 可执行的动作"""
    EXECUTE = "execute"       # 向编码工具发送指令
    DONE = "done"             # 任务完成
    BLOCKED = "blocked"       # 遇到无法解决的阻塞
    ASK_USER = "ask_user"     # 需要用户决定
    RETRY = "retry"           # 重试上一条指令


# ============================================================
# 默认 System Prompt
# ============================================================

DEFAULT_SYSTEM_PROMPT = """你是资深工程师助手，负责分析编码工具的输出并决定下一步操作。

## 严格要求

你的每次回复必须是且仅是一个 JSON 对象，不要有任何其他文字。

## 可用 Action

1. execute — 向编码工具发送下一条指令
2. done — 任务已完成
3. blocked — 遇到无法自动解决的阻塞
4. ask_user — 需要用户做决定
5. retry — 重试上一条指令（编码工具出错时使用）

## 回复格式及示例

发送指令：
{"action":"execute","instruction":"请运行 pytest tests/ -v","reasoning":"代码修改完成，需要验证测试"}

任务完成：
{"action":"done","instruction":"","reasoning":"所有功能已实现，测试全部通过","summary":"完成了登录模块，包含 JWT 认证和密码重置"}

需要用户决定：
{"action":"ask_user","instruction":"","reasoning":"发现两套鉴权方案，无法自动决定","question":"项目使用 JWT 和 Cookie 两套鉴权，是否全部替换为 Session？"}

遇到阻塞：
{"action":"blocked","instruction":"","reasoning":"数据库连接失败，缺少配置信息"}

重试：
{"action":"retry","instruction":"","reasoning":"编码工具返回了模型错误，重试一次"}

## 决策原则

- 优先推进任务，减少不必要的确认
- 遇到小问题自己决定，只有重大决策才 ask_user
- 每条指令要具体、可执行，不要泛泛而谈
- 如果编码工具已经完成了所有需求且没有报错，果断 done
"""

DEFAULT_CHAT_PROMPT = (
    "你是一个正在执行编码任务的 AI 助手。\n"
    "用户正在向你询问任务的进展。请根据上下文直接回答用户的问题。\n"
    "回复用自然语言，不需要 JSON 格式。简洁明了。"
)

DEFAULT_FREE_CHAT_PROMPT = "你是一个智能助手。用自然语言回答用户的问题，简洁、准确、有帮助。"

# 决策风格：追加到 system prompt 末尾的额外决策原则
DECISION_STYLES = {
    "default": "",  # 不追加额外内容，使用 prompt 文件中的原文
    "conservative": """

## 额外决策原则（保守模式）

- 遇到任何不确定的决策，优先 ask_user
- 每完成一个子任务就报告进展，等待用户确认再继续
- 修改文件前先向用户确认方案
- 避免一次性做大量变更，拆分为小步骤逐步推进
""",
    "aggressive": """

## 额外决策原则（激进模式）

- 除非遇到根本无法判断的选择，否则自行决定并推进
- 不需要逐步确认，直接完成整个任务
- 遇到小问题（格式、命名等）直接按最佳实践处理
- 优先完整完成任务，最后统一报告
""",
}


# ============================================================
# Prompt 文件加载器
# ============================================================

class PromptLoader:
    """
    Prompt 文件加载器（无状态，仅维护文件缓存）

    职责：
    1. 从文件加载 prompt 内容
    2. 基于 mtime 实现热加载（文件变更时自动重新读取）
    3. 文件不存在时自动生成默认内容
    4. 加载失败时 fallback 到内置默认值
    """

    def __init__(self):
        # 缓存: {file_path: {"content": str, "mtime": float}}
        self._cache: dict[str, dict] = {}

    def load(self, file_path: str, default_content: str) -> str:
        """
        加载 prompt 文件内容（带热加载缓存）

        参数:
          file_path: 文件路径（绝对路径或相对于 cwd 的相对路径）
          default_content: 文件不存在时写出的默认内容，也是 fallback 值

        返回:
          prompt 文本内容
        """
        path = Path(file_path)
        path_str = str(path)

        # 文件不存在 → 自动生成默认文件，填充缓存后返回默认值
        if not path.exists():
            self._generate_default(path, default_content)
            # 防御性填充缓存，避免下次加载时 strip() 导致内容差异
            try:
                mtime = os.path.getmtime(path_str)
                self._cache[path_str] = {"content": default_content, "mtime": mtime}
            except OSError:
                pass
            return default_content

        # 检查 mtime（热加载核心）
        try:
            current_mtime = os.path.getmtime(path_str)
        except OSError:
            logger.warning(f"无法读取 prompt 文件 mtime: {path_str}，使用默认值")
            return default_content

        cached = self._cache.get(path_str)
        if cached and cached["mtime"] == current_mtime:
            return cached["content"]

        # 读取文件
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                logger.warning(f"Prompt 文件为空: {path_str}，使用默认值")
                return default_content
            self._cache[path_str] = {"content": content, "mtime": current_mtime}
            if cached:
                logger.info(f"Prompt 文件已更新，重新加载: {path_str}")
            else:
                logger.info(f"Prompt 文件已加载: {path_str}")
            return content
        except UnicodeDecodeError:
            logger.warning(f"Prompt 文件编码错误（非 UTF-8）: {path_str}，使用默认值")
            return default_content
        except OSError as e:
            logger.warning(f"Prompt 文件读取失败: {path_str}: {e}，使用默认值")
            return default_content

    def _generate_default(self, path: Path, content: str):
        """自动生成默认 prompt 文件"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content + "\n", encoding="utf-8")
            logger.warning(f"Prompt 文件不存在，已生成默认文件: {path}")
        except OSError as e:
            logger.warning(f"无法生成默认 prompt 文件: {path}: {e}")


# ============================================================
# 费用估算
# ============================================================

# 各模型的 token 定价（USD per 1K tokens）
MODEL_PRICING = {
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-reasoner": {"input": 0.00055, "output": 0.00219},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "gpt-4.1": {"input": 0.002, "output": 0.008},
    "gpt-4.1-mini": {"input": 0.0004, "output": 0.0016},
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
    "claude-sonnet-4-20250514": {"input": 0.003, "output": 0.015},
    "gemini-2.0-flash": {"input": 0.0001, "output": 0.0004},
    "gemini-2.5-pro": {"input": 0.00125, "output": 0.01},
    "gemini-3-flash-preview": {"input": 0.0001, "output": 0.0004},
}


def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """估算 LLM 调用费用"""
    pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000


# ============================================================
# Provider 工厂
# ============================================================

def _get_openai_compatible_client(config: ManagerConfig):
    """构建 OpenAI 兼容客户端（支持 DeepSeek、Ollama、Azure 等）"""
    from openai import OpenAI

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


# ============================================================
# Manager Agent
# ============================================================

class ManagerAgent:
    """
    Manager Agent：分析编码工具输出，决定下一步动作

    集成了 LLM 调用（多 provider）、JSON 解析（含 fallback）、
    重试逻辑和费用估算。不再拆分为独立的 llm_client.py。
    """

    def __init__(self, config: ManagerConfig, context_mgr=None):
        self.config = config
        self.conversation_history: list[dict] = []
        self._total_cost: float = 0.0
        self._context_mgr = context_mgr

        # Prompt 加载器
        self._prompt_loader = PromptLoader()
        # 冲突日志去重标志
        self._warned_prompt_conflict = False

        # system_prompt 加载优先级：
        #   文件路径（system_prompt_file）> 内联字符串（system_prompt）> 内置默认值
        self.system_prompt = self._load_system_prompt()

        self._init_client()

    def _init_client(self):
        """初始化对应 provider 的客户端"""
        if self.config.provider == "anthropic":
            from anthropic import Anthropic
            self._anthropic_client = Anthropic(api_key=self.config.api_key)
            self._use_anthropic = True
        else:
            self._openai_client = _get_openai_compatible_client(self.config)
            self._use_anthropic = False

        logger.info(f"Manager Agent 初始化完成: {self.config.provider}/{self.config.model}")

    def _load_system_prompt(self) -> str:
        """
        加载 system prompt（支持热加载）

        优先级：
        1. config.system_prompt_file 指定的文件
        2. config.system_prompt 内联字符串
        3. DEFAULT_SYSTEM_PROMPT 内置默认值
        """
        if self.config.system_prompt_file:
            # 冲突日志只输出一次，避免每轮 decide() 都打印
            if self.config.system_prompt and not self._warned_prompt_conflict:
                logger.info(
                    "system_prompt_file 和 system_prompt 同时配置，"
                    "使用文件路径，忽略内联字符串"
                )
                self._warned_prompt_conflict = True
            prompt = self._prompt_loader.load(
                self.config.system_prompt_file,
                DEFAULT_SYSTEM_PROMPT
            )
        elif self.config.system_prompt:
            prompt = self.config.system_prompt
        else:
            prompt = DEFAULT_SYSTEM_PROMPT

        # 追加决策风格
        style = self.config.decision_style or "default"
        style_text = DECISION_STYLES.get(style, "")
        if style_text:
            prompt += style_text

        return prompt

    def start_task(self, requirement: str):
        """开始新任务，重置对话历史"""
        self.conversation_history = []
        self._total_cost = 0.0
        # 重新加载 prompt
        self.system_prompt = self._load_system_prompt()
        self.conversation_history.append({
            "role": "user",
            "content": f"用户需求：{requirement}\n\n请分析需求并给出第一条指令。"
        })

    def decide(self, tool_output: str) -> dict:
        """
        根据编码工具的最新输出，决定下一步动作

        参数:
          tool_output: 编码工具的输出文本（首轮为空字符串）

        返回:
          解析后的决策字典，至少包含 action 和 instruction 字段
        """
        # 热加载：检查 prompt 文件是否变更
        self.system_prompt = self._load_system_prompt()

        # 如果有输出，加入对话历史
        if tool_output:
            self.conversation_history.append({
                "role": "user",
                "content": f"编码工具输出：\n{tool_output}\n\n请分析输出并给出下一步操作。"
            })

        # 调用 LLM（含重试）
        raw_response = self._call_llm_with_retry()

        # 将回复加入历史
        self.conversation_history.append({
            "role": "assistant",
            "content": raw_response
        })

        # 解析 JSON 回复
        parsed = self._parse_response(raw_response)
        logger.info(
            f"Manager 决策: action={parsed['action']}, "
            f"instruction={parsed.get('instruction', '')[:60]}..."
        )

        return parsed

    def decide_with_feedback(self, tool_output: str, user_feedback: str) -> dict:
        """
        带用户反馈的决策

        用户反馈通过 inbox 注入，在 Manager 决策前合并。
        """
        combined = tool_output
        if user_feedback:
            combined += f"\n\n[用户实时反馈]: {user_feedback}"
        return self.decide(combined)

    @property
    def total_cost(self) -> float:
        """Manager 调用的累计费用（估算）"""
        return self._total_cost

    # ============================================================
    # LLM 调用（含重试）
    # ============================================================

    def _call_llm_with_retry(self) -> str:
        """调用 LLM，支持指数退避重试"""
        last_error = None
        for attempt in range(self.config.retry_count):
            try:
                if self._use_anthropic:
                    return self._call_anthropic()
                else:
                    return self._call_openai_compatible()
            except Exception as e:
                last_error = e
                if attempt < self.config.retry_count - 1:
                    wait = 2 ** attempt
                    logger.warning(f"LLM 请求失败（第 {attempt + 1} 次），{wait}s 后重试: {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"LLM 请求失败（已重试 {self.config.retry_count} 次）: {e}")
        raise last_error

    def _call_openai_compatible(self) -> str:
        """通过 OpenAI 兼容协议调用 LLM"""
        history = self.conversation_history
        if self._context_mgr:
            history = self._context_mgr.build_context(history)
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(history)

        response = self._openai_client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            timeout=self.config.request_timeout,
            max_tokens=2000,
        )

        # 费用估算
        usage = response.usage
        if usage:
            cost = _estimate_cost(
                self.config.model,
                usage.prompt_tokens,
                usage.completion_tokens
            )
            self._total_cost += cost

        return response.choices[0].message.content.strip()

    def _call_anthropic(self) -> str:
        """通过 Anthropic 原生 SDK 调用"""
        history = self.conversation_history
        if self._context_mgr:
            history = self._context_mgr.build_context(history)
        response = self._anthropic_client.messages.create(
            model=self.config.model,
            system=self.system_prompt,
            messages=history,
            max_tokens=2000,
        )

        # 费用估算
        usage = response.usage
        if usage:
            cost = _estimate_cost(
                self.config.model,
                usage.input_tokens,
                usage.output_tokens
            )
            self._total_cost += cost

        return response.content[0].text.strip()

    # ============================================================
    # JSON 解析（含 fallback）
    # ============================================================

    def _parse_response(self, raw: str) -> dict:
        """
        解析 Manager 回复，支持 JSON 和纯文本 fallback

        尝试顺序：
        1. 直接 JSON 解析
        2. 从 markdown code block 中提取 JSON
        3. 检测信号关键词（兼容纯文本模式）
        4. Fallback：视为 execute 指令
        """
        # 尝试 1：直接 JSON 解析
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # 尝试 2：从 markdown code block 中提取 JSON
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # 尝试 3：检测信号关键词（兼容旧版纯文本模式）
        if "##DONE##" in raw:
            return {"action": "done", "instruction": "", "reasoning": raw}
        if "##BLOCKED##" in raw:
            return {"action": "blocked", "instruction": "", "reasoning": raw}

        # Fallback：视为 execute 指令
        logger.warning("Manager 回复非 JSON，fallback 为 execute 指令")
        return {"action": "execute", "instruction": raw, "reasoning": "（纯文本 fallback）"}

    # ============================================================
    # 独立问答（用于 /chat 命令）
    # ============================================================

    def standalone_chat(self, context_summary: str, user_message: str) -> str:
        """
        独立问答：不影响任务主循环的对话历史

        用于 Telegram /chat 和 CLI maestro chat 命令。
        Daemon 直接调用此方法回答用户提问。
        """
        # 加载 chat prompt
        if self.config.chat_prompt_file:
            chat_prompt = self._prompt_loader.load(
                self.config.chat_prompt_file,
                DEFAULT_CHAT_PROMPT
            )
        else:
            chat_prompt = DEFAULT_CHAT_PROMPT

        messages = [
            {"role": "system", "content": chat_prompt},
            {"role": "user", "content": f"[任务上下文]\n{context_summary}\n\n[用户提问]\n{user_message}"}
        ]

        try:
            if self._use_anthropic:
                response = self._anthropic_client.messages.create(
                    model=self.config.model,
                    system=messages[0]["content"],
                    messages=[messages[1]],
                    max_tokens=1000,
                )
                return response.content[0].text.strip()
            else:
                response = self._openai_client.chat.completions.create(
                    model=self.config.model,
                    messages=messages,
                    timeout=self.config.request_timeout,
                    max_tokens=1000,
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"独立问答失败: {e}")
            return f"抱歉，无法回答：{e}"

    def free_chat(self, history: list[dict], user_message: str) -> str:
        """
        自由聊天：无任务上下文的多轮对话

        参数:
          history: 之前的对话历史 [{"role": "user/assistant", "content": "..."}]
          user_message: 当前用户消息
        返回:
          助手回复文本
        """
        # 加载 free_chat prompt
        if self.config.free_chat_prompt_file:
            system = self._prompt_loader.load(
                self.config.free_chat_prompt_file,
                DEFAULT_FREE_CHAT_PROMPT
            )
        else:
            system = DEFAULT_FREE_CHAT_PROMPT
        messages = list(history) + [{"role": "user", "content": user_message}]

        try:
            if self._use_anthropic:
                response = self._anthropic_client.messages.create(
                    model=self.config.model,
                    system=system,
                    messages=messages,
                    max_tokens=2000,
                )
                return response.content[0].text.strip()
            else:
                oai_messages = [{"role": "system", "content": system}] + messages
                response = self._openai_client.chat.completions.create(
                    model=self.config.model,
                    messages=oai_messages,
                    timeout=self.config.request_timeout,
                    max_tokens=2000,
                )
                return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"自由聊天失败: {e}")
            return f"抱歉，无法回答：{e}"
