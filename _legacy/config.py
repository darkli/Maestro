"""
配置加载模块
支持 YAML 配置文件 + 环境变量替换
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


def _expand_env_vars(value: str) -> str:
    """替换 ${VAR_NAME} 格式的环境变量"""
    pattern = re.compile(r'\$\{([^}]+)\}')
    def replacer(match):
        var_name = match.group(1)
        result = os.environ.get(var_name, "")
        if not result:
            print(f"⚠️  警告：环境变量 {var_name} 未设置")
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


@dataclass
class MetaAgentConfig:
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: Optional[str] = None
    system_prompt: str = ""
    max_turns: int = 30
    request_timeout: int = 60


@dataclass
class ClaudeCodeConfig:
    auto_approve: bool = True
    response_timeout: int = 300
    command: str = "claude"
    working_dir: Optional[str] = None


@dataclass
class ZellijConfig:
    enabled: bool = True
    layout: str = "split"
    panel_ratio: str = "40:60"


@dataclass
class LoggingConfig:
    dir: str = "~/.autopilot/logs"
    level: str = "INFO"
    save_conversation: bool = True


@dataclass
class AppConfig:
    meta_agent: MetaAgentConfig = field(default_factory=MetaAgentConfig)
    claude_code: ClaudeCodeConfig = field(default_factory=ClaudeCodeConfig)
    zellij: ZellijConfig = field(default_factory=ZellijConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """加载配置文件"""
    path = Path(config_path)
    if not path.exists():
        # 尝试从默认位置查找
        home_config = Path.home() / ".autopilot" / "config.yaml"
        if home_config.exists():
            path = home_config
        else:
            print(f"⚠️  配置文件 {config_path} 不存在，使用默认配置")
            return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    raw = _process_config(raw)

    config = AppConfig()

    if "meta_agent" in raw:
        ma = raw["meta_agent"]
        config.meta_agent = MetaAgentConfig(
            provider=ma.get("provider", "deepseek"),
            model=ma.get("model", "deepseek-chat"),
            api_key=ma.get("api_key", ""),
            base_url=ma.get("base_url"),
            system_prompt=ma.get("system_prompt", ""),
            max_turns=ma.get("max_turns", 30),
            request_timeout=ma.get("request_timeout", 60),
        )

    if "claude_code" in raw:
        cc = raw["claude_code"]
        config.claude_code = ClaudeCodeConfig(
            auto_approve=cc.get("auto_approve", True),
            response_timeout=cc.get("response_timeout", 300),
            command=cc.get("command", "claude"),
            working_dir=cc.get("working_dir"),
        )

    if "zellij" in raw:
        zj = raw["zellij"]
        config.zellij = ZellijConfig(
            enabled=zj.get("enabled", True),
            layout=zj.get("layout", "split"),
            panel_ratio=zj.get("panel_ratio", "40:60"),
        )

    if "logging" in raw:
        lg = raw["logging"]
        config.logging = LoggingConfig(
            dir=lg.get("dir", "~/.autopilot/logs"),
            level=lg.get("level", "INFO"),
            save_conversation=lg.get("save_conversation", True),
        )

    return config
