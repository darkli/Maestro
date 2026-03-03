"""
配置加载模块

支持 YAML 配置文件 + 环境变量 ${VAR} 语法替换。
配置项使用 dataclass 建模，分为以下几段：
  - manager: Manager Agent（外层决策 AI）
  - coding_tools: 编码工具预设（多工具 + 运行时切换）
  - context: 上下文管理
  - safety: 安全控制（熔断器、并发限制）
  - telegram: Telegram Bot 远程控制
  - logging: 日志管理
"""

import os
import re
import tempfile
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

    # ---- Prompt 外置化配置 ----
    system_prompt_file: str = ""     # system prompt 文件路径（优先于 system_prompt）
    chat_prompt_file: str = ""       # standalone_chat prompt 文件路径
    free_chat_prompt_file: str = ""  # free_chat prompt 文件路径
    decision_style: str = ""         # 决策风格: default | conservative | aggressive


@dataclass
class CodingToolConfig:
    """编码工具配置（Claude Code / Codex CLI / Gemini CLI / Aider 等）"""
    type: str = "claude"              # claude | codex | generic
    command: str = "claude"           # 可执行命令名或完整路径
    extra_args: list = field(default_factory=list)  # generic 模式的额外参数
    auto_approve: bool = True         # Claude → --dangerously-skip-permissions / Codex → --full-auto
    timeout: int = 600                # 单轮 subprocess 超时（秒）

    # ---- Codex CLI 专用配置 ----
    sandbox: str = ""                 # Codex 沙箱级别: full | net-disabled | off（空=使用 Codex 默认）
    model: str = ""                   # Codex 模型名（如 codex-mini-latest, o3, o4-mini；空=使用 Codex 默认）
    skip_git_check: bool = False      # Codex: --skip-git-check（跳过 git 仓库检查）


@dataclass
class CodingToolsConfig:
    """多编码工具配置（支持预设 + 运行时切换）"""
    active_tool: str = "claude"
    presets: dict = field(default_factory=dict)  # name -> CodingToolConfig dict


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
    # 多维度死循环检测阈值
    similarity_threshold: float = 0.85       # 指令语义相似度阈值
    stagnation_threshold: float = 0.9        # 输出停滞相似度阈值
    max_consecutive_errors: int = 3           # 连续相同错误上限
    oscillation_window: int = 6              # action 震荡检测窗口大小


@dataclass
class TelegramConfig:
    """Telegram Bot 配置"""
    enabled: bool = False
    bot_token: str = ""
    chat_id: str = ""                 # 授权用户 chat_id
    ask_user_timeout: int = 3600      # ASK_USER 等待超时（秒）


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
    coding_tools: CodingToolsConfig = field(default_factory=CodingToolsConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @property
    def coding_tool(self) -> CodingToolConfig:
        """向后兼容：返回当前激活工具的 CodingToolConfig"""
        active = self.coding_tools.active_tool
        preset = self.coding_tools.presets.get(active)
        if preset is None:
            print(f"  警告：active_tool '{active}' 在 presets 中不存在，"
                  f"可用: {list(self.coding_tools.presets.keys())}，将使用默认配置")
            return CodingToolConfig()
        if isinstance(preset, dict):
            return _dict_to_dataclass(CodingToolConfig, preset)
        return preset

    @property
    def available_tools(self) -> list[str]:
        """返回所有预设工具名"""
        return list(self.coding_tools.presets.keys())


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


def _resolve_config_path(config_path: str = "config.yaml") -> Optional[Path]:
    """
    解析配置文件路径

    查找顺序：
    1. 指定路径
    2. ~/.maestro/config.yaml
    3. 返回 None
    """
    path = Path(config_path)
    if path.exists():
        return path
    home_config = Path.home() / ".maestro" / "config.yaml"
    if home_config.exists():
        return home_config
    return None


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """
    加载配置文件

    查找顺序：
    1. 指定路径
    2. ~/.maestro/config.yaml
    3. 使用默认配置
    """
    path = _resolve_config_path(config_path)
    if path is None:
        print(f"  配置文件 {config_path} 不存在，使用默认配置")
        return AppConfig()

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    # 环境变量替换
    raw = _process_config(raw)

    # 构建 coding_tools（向后兼容旧格式）
    if "coding_tools" in raw:
        ct_raw = raw["coding_tools"]
        coding_tools_config = CodingToolsConfig(
            active_tool=ct_raw.get("active_tool", "claude"),
            presets=ct_raw.get("presets", {}),
        )
    elif "coding_tool" in raw:
        # 旧格式：单个 coding_tool → 包装为 presets
        print("  提示：检测到旧格式 coding_tool:，已自动转换。"
              "建议迁移为 coding_tools: + presets 新格式")
        old_ct = raw["coding_tool"]
        tool_type = old_ct.get("type", "claude")
        coding_tools_config = CodingToolsConfig(
            active_tool=tool_type,
            presets={tool_type: old_ct},
        )
    else:
        coding_tools_config = CodingToolsConfig(
            active_tool="claude",
            presets={"claude": {
                "type": "claude", "command": "claude",
                "auto_approve": True, "timeout": 600,
            }},
        )

    # 构建配置对象
    config = AppConfig(
        manager=_dict_to_dataclass(ManagerConfig, raw.get("manager", {})),
        coding_tools=coding_tools_config,
        context=_dict_to_dataclass(ContextConfig, raw.get("context", {})),
        safety=_dict_to_dataclass(SafetyConfig, raw.get("safety", {})),
        telegram=_dict_to_dataclass(TelegramConfig, raw.get("telegram", {})),
        logging=_dict_to_dataclass(LoggingConfig, raw.get("logging", {})),
    )

    return config


def save_active_tool(config_path: str, tool_name: str):
    """原子更新 config.yaml 中的 active_tool 值"""
    # 校验工具名（防止正则注入）
    if not re.match(r'^[A-Za-z0-9_-]+$', tool_name):
        raise ValueError(f"工具名包含非法字符: {tool_name!r}")

    path = _resolve_config_path(config_path)
    if path is None:
        raise FileNotFoundError(f"配置文件 {config_path} 不存在")

    content = path.read_text(encoding="utf-8")

    if "active_tool:" in content:
        # 使用 lambda 避免 tool_name 中特殊字符被当作替换语法；
        # ^锚点 + MULTILINE 确保只替换实际字段行，不误改注释
        content = re.sub(
            r'^(\s*active_tool:\s*)\S+',
            lambda m: m.group(1) + tool_name,
            content,
            flags=re.MULTILINE,
        )
    else:
        raise ValueError("config.yaml 中无 active_tool 字段，请升级为新格式")

    # 原子写入
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
