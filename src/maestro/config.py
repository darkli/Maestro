"""
配置加载模块

支持 YAML 配置文件 + 环境变量 ${VAR} 语法替换。
配置项使用 dataclass 建模，分为以下几段：
  - manager: Manager Agent（外层决策 AI）
  - coding_tool: 编码工具（Claude Code / Gemini CLI 等）
  - context: 上下文管理
  - safety: 安全控制（熔断器、并发限制）
  - telegram: Telegram Bot 远程控制
  - zellij: Zellij 终端 UI
  - logging: 日志管理
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


# ============================================================
# 环境变量替换
# ============================================================

def _expand_env_vars(value: str) -> str:
    """替换 ${VAR_NAME} 格式的环境变量"""
    pattern = re.compile(r'\$\{([^}]+)\}')

    def replacer(match):
        var_name = match.group(1)
        result = os.environ.get(var_name, "")
        if not result:
            print(f"  警告：环境变量 {var_name} 未设置")
        return result

    return pattern.sub(replacer, value)


def _process_config(obj):
    """递归处理配置中的环境变量"""
    if isinstance(obj, str):
        return _expand_env_vars(obj)
    elif isinstance(obj, dict):
        return {k: _process_config(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_process_config(item) for item in obj]
    return obj


# ============================================================
# 配置 dataclass 定义
# ============================================================

@dataclass
class ManagerConfig:
    """Manager Agent 配置"""
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: Optional[str] = None
    max_turns: int = 30
    max_budget_usd: float = 5.0
    request_timeout: int = 60
    retry_count: int = 3
    system_prompt: str = ""

    # ---- 网络配置 ----
    ip_version: int = 0              # IP 协议版本: 4 = 强制 IPv4, 6 = 强制 IPv6, 0 = 系统默认

    # ---- Prompt 外置化配置 ----
    system_prompt_file: str = ""     # system prompt 文件路径（优先于 system_prompt）
    chat_prompt_file: str = ""       # standalone_chat prompt 文件路径
    free_chat_prompt_file: str = ""  # free_chat prompt 文件路径
    decision_style: str = ""         # 决策风格: default | conservative | aggressive


@dataclass
class CodingToolConfig:
    """编码工具配置（Claude Code / Gemini CLI / Aider 等）"""
    type: str = "claude"              # claude | generic
    command: str = "claude"           # 可执行命令名或完整路径
    extra_args: list = field(default_factory=list)  # generic 模式的额外参数
    auto_approve: bool = True         # Claude 专用：--dangerously-skip-permissions
    timeout: int = 600                # 单轮 subprocess 超时（秒）


@dataclass
class ContextConfig:
    """上下文管理配置"""
    max_recent_turns: int = 5         # 传给 Manager 的最近轮数
    max_result_chars: int = 3000      # 工具输出截断长度


@dataclass
class SafetyConfig:
    """安全控制配置"""
    max_consecutive_similar: int = 3  # 死循环检测阈值
    max_parallel_tasks: int = 3       # 最大并行任务数


@dataclass
class TelegramConfig:
    """Telegram Bot 配置"""
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""                 # 授权用户 chat_id
    ask_user_timeout: int = 3600      # ASK_USER 等待超时（秒）


@dataclass
class ZellijConfig:
    """Zellij 终端 UI 配置"""
    enabled: bool = True
    auto_install: bool = True         # 未安装时自动安装


@dataclass
class LoggingConfig:
    """日志管理配置"""
    dir: str = "~/.maestro/logs"
    level: str = "INFO"
    max_days: int = 30                # 日志保留天数


@dataclass
class AppConfig:
    """应用全局配置"""
    manager: ManagerConfig = field(default_factory=ManagerConfig)
    coding_tool: CodingToolConfig = field(default_factory=CodingToolConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    zellij: ZellijConfig = field(default_factory=ZellijConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


# ============================================================
# 配置加载
# ============================================================

def _dict_to_dataclass(dc_class, data: dict):
    """将字典映射到 dataclass，忽略未知字段"""
    if not data:
        return dc_class()
    valid_fields = {f.name for f in dc_class.__dataclass_fields__.values()}
    filtered = {k: v for k, v in data.items() if k in valid_fields}
    return dc_class(**filtered)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    加载配置文件

    查找顺序：
    1. 指定路径
    2. ~/.maestro/config.yaml
    3. 使用默认配置
    """
    path = Path(config_path)
    if not path.exists():
        # 尝试从默认位置查找
        home_config = Path.home() / ".maestro" / "config.yaml"
        if home_config.exists():
            path = home_config
        else:
            print(f"  配置文件 {config_path} 不存在，使用默认配置")
            return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 环境变量替换
    raw = _process_config(raw)

    # 构建配置对象
    config = AppConfig(
        manager=_dict_to_dataclass(ManagerConfig, raw.get("manager", {})),
        coding_tool=_dict_to_dataclass(CodingToolConfig, raw.get("coding_tool", {})),
        context=_dict_to_dataclass(ContextConfig, raw.get("context", {})),
        safety=_dict_to_dataclass(SafetyConfig, raw.get("safety", {})),
        telegram=_dict_to_dataclass(TelegramConfig, raw.get("telegram", {})),
        zellij=_dict_to_dataclass(ZellijConfig, raw.get("zellij", {})),
        logging=_dict_to_dataclass(LoggingConfig, raw.get("logging", {})),
    )

    return config
