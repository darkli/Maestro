# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Maestro 是一个 Python CLI 工具，使用可配置的 Manager Agent（通过 OpenAI 兼容 API 或 Anthropic 原生 SDK 调用任意 LLM）自动驱动编码工具（Claude Code / Gemini CLI 等）完成开发任务。Manager 分析编码工具输出，以 JSON 格式生成下一步指令，支持 VPS 后台运行和 Telegram 远程控制。

## Capabilities

| 能力 | 值 |
|------|-----|
| frontend | false |
| backend-api | false |
| database | false |
| i18n | false |
| testing | false |
| cross-compile | false |
| design-system | false |
| ci-cd | false |
| monorepo | false |
| static-types | false |

## Running

```bash
# 安装
pip install -e .

# 复制配置文件并设置 API Key
cp config.example.yaml ~/.maestro/config.yaml

# 后台启动任务（默认）
maestro run "your requirement here"

# 前台同步运行（调试用）
maestro run -f "your requirement here"

# 覆盖 provider/model
maestro run --provider ollama --model qwen2.5:14b "your requirement"

# 不使用 Zellij UI
maestro run --no-zellij "your requirement"

# 查看任务列表
maestro list

# 查看任务详情
maestro status <task_id>

# 发送反馈
maestro ask <task_id> "消息"

# 与 Manager 对话
maestro chat <task_id> "问题"

# 终止任务
maestro abort <task_id>

# 恢复崩溃的任务
maestro resume <task_id>

# 启动 Telegram Daemon
maestro daemon start
```

No tests, linter, or formatter are currently configured.

## Build & Development Commands

```bash
# 开发模式安装
pip install -e .

# 或直接运行（不安装）
PYTHONPATH=src python -m maestro.cli run "需求"
```

## Testing

当前无测试框架。项目暂未配置测试。

## Code Style

- 4 空格缩进，Python 全栈
- 文件命名：snake_case `.py` 文件
- 类名：PascalCase，函数/变量：snake_case
- 使用 dataclasses 进行配置建模
- docstrings 和注释使用中文

## Adding New Features

1. 在对应模块文件中添加新功能代码
2. 如涉及配置项，更新 `src/maestro/config.py` 中的 dataclass 定义
3. 如涉及新配置字段，同步更新 `config.example.yaml`
4. 如涉及 CLI 参数，更新 `src/maestro/cli.py` 的 argparse 定义
5. 确保所有导入使用 `maestro.*` 包前缀

## Commit Style

提交消息使用中文，简洁的动作导向格式。遵循现有风格。

## Architecture

系统由 10 个模块组成，核心闭环：CLI → Orchestrator → ToolRunner + ManagerAgent → 循环直到完成。

### 核心模块

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI | `cli.py` | 命令行入口，支持 run/list/status/ask/chat/abort/resume/report/daemon 命令 |
| Orchestrator | `orchestrator.py` | 调度核心：主循环、inbox 路由、abort 检测、通知、报告生成 |
| ManagerAgent | `manager_agent.py` | 外层决策 AI：多 provider 支持、JSON 输出解析、action 路由、费用估算 |
| ToolRunner | `tool_runner.py` | 编码工具运行器：Claude Code JSON 模式 + 通用 subprocess 模式 |
| Config | `config.py` | YAML 配置加载 + 环境变量替换 + dataclass 建模 |

### 辅助模块

| 模块 | 文件 | 职责 |
|------|------|------|
| State | `state.py` | 状态机（6 态）+ 熔断器 + atomic_write_json 工具 |
| Context | `context.py` | 上下文压缩（滑动窗口）+ 输出截断 |
| Session | `session.py` | Zellij 管理（KDL 布局 + 自动安装 + fallback） |
| Registry | `registry.py` | 多任务注册表（CRUD + 并发数检查） |
| TelegramBot | `telegram_bot.py` | Telegram Bot + Daemon（asyncio，含 /chat LLM 调用） |

### 目录结构

```
Maestro/
├── pyproject.toml
├── config.example.yaml
├── src/maestro/
│   ├── __init__.py
│   ├── cli.py
│   ├── config.py
│   ├── orchestrator.py
│   ├── tool_runner.py
│   ├── manager_agent.py
│   ├── state.py
│   ├── context.py
│   ├── session.py
│   ├── registry.py
│   └── telegram_bot.py
└── _legacy/                  # 旧版 autopilot 代码（已弃用）
```

## Key Design Decisions

- **subprocess over pexpect**: 使用 `claude -p --output-format json` 非交互模式，每轮独立进程调用，通过 `--resume session_id` 保持会话上下文
- **JSON action 协议**: Manager 必须以 JSON 回复决策（action: execute/done/blocked/ask_user/retry），含 fallback 到纯文本模式
- **编码工具可插拔**: `tool_runner.py` 支持 claude 和 generic 两种模式，可适配 Gemini CLI、Aider 等
- **文件 IPC**: inbox.txt（用户反馈）+ abort 信号文件 + state.json（状态共享）
- **Zellij 进程保活**: 任务在 Zellij Session 中运行，SSH 断开后不中断
- **nohup + PID 文件**: Daemon 管理使用最简方案，不依赖 systemd

## Configuration

配置文件加载顺序：`config.yaml`（当前目录）→ `~/.maestro/config.yaml` → 默认值。

7 个配置段：`manager`、`coding_tool`、`context`、`safety`、`telegram`、`zellij`、`logging`。

环境变量通过 `${VAR_NAME}` 语法展开。详见 `config.example.yaml`。

## Language

All user-facing strings, comments, docstrings, and documentation are in Chinese (中文). Maintain this convention.
