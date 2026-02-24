# 项目上下文

## 技术栈

- 语言: Python（全栈）
- 进程控制: pexpect（当前）→ 方案使用 subprocess（`claude -p --output-format json`）
- 终端 UI: Zellij (KDL 布局)
- 配置: YAML + dataclasses
- LLM 协议: OpenAI 兼容 + Anthropic 原生 SDK
- 包管理: 计划使用 pyproject.toml

## 现有模块

| 模块 | 文件 | 职责 |
|------|------|------|
| CLI | cli.py | 命令行入口，解析参数，加载配置 |
| Orchestrator | orchestrator.py | 调度核心，串联 Meta-Agent 和 Claude Driver |
| MetaAgent | meta_agent.py | 外层决策 AI，支持多 provider |
| ClaudeCodeDriver | claude_driver.py | pexpect 控制 Claude Code 进程 |
| Config | config.py | YAML 配置加载 + 环境变量替换 |
| ZellijSession | zellij_session.py | Zellij 多面板 UI 管理 |

## 包前缀

- 当前: `autopilot.*`
- 方案: `maestro.*`（需要重命名）

## 编码约定

- 4 空格缩进
- snake_case 文件/函数/变量，PascalCase 类名
- docstrings 和注释使用中文
- 提交消息使用中文

## 输出语言

中文

## 关键设计决策（现有）

- pexpect 控制 Claude Code（交互式进程）
- OpenAI 兼容协议（多 provider 统一接口）
- 文件 IPC（Zellij 面板通过文件通信）
- 环境变量 `${VAR}` 语法展开

## 方案核心变更

1. pexpect → subprocess (`claude -p --output-format json`)
2. autopilot → maestro 包名
3. 新增 Telegram Bot 守护进程
4. 新增多任务并行注册表
5. 新增状态机 + 熔断器
6. 新增上下文管理（压缩）
7. 新增崩溃恢复（checkpoint）
