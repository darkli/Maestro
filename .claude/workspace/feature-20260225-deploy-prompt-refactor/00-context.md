# 项目上下文

## 技术栈

| 能力 | 值 |
|------|-----|
| frontend | false |
| backend-api | false |
| database | false |
| i18n | false |
| testing | pytest |
| cross-compile | false |
| design-system | false |
| ci-cd | false |
| monorepo | false |
| static-types | false |

## 构建与开发命令


```bash
# 开发模式安装
pip install -e .

# 或直接运行（不安装）
PYTHONPATH=src python -m maestro.cli run "需求"
```

## 测试约定


当前无测试框架。项目暂未配置测试。

## 架构


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

## 编码规范

（未找到）

## 输出约定


All user-facing strings, comments, docstrings, and documentation are in Chinese (中文). Maintain this convention.

提交消息使用中文，简洁的动作导向格式。遵循现有风格。
