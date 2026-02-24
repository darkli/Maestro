# Claude Autopilot — 整体架构设计

## 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        用户                                   │
│  $ autopilot run "帮我实现一个 FastAPI 用户登录接口"            │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    CLI (cli.py)                              │
│  - 解析命令行参数                                              │
│  - 加载配置文件                                               │
│  - 启动 Orchestrator                                         │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Orchestrator (orchestrator.py)              │
│                                                              │
│  1. 创建 Zellij 会话                                         │
│  2. 启动 Claude Code 进程                                     │
│  3. 进入主循环：                                              │
│     Meta-Agent 决策 → 驱动 Claude Code → 分析输出 → 循环     │
│  4. 检测 DONE/BLOCKED/超轮次，结束任务                        │
└──────────────┬──────────────────────────┬───────────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────────┐  ┌───────────────────────────────┐
│   Meta-Agent             │  │   Claude Code Driver          │
│   (meta_agent.py)        │  │   (claude_driver.py)          │
│                          │  │                               │
│  可配置任意大模型后端：     │  │  - pexpect 控制进程           │
│  - DeepSeek（推荐）       │  │  - 自动处理权限确认            │
│  - OpenAI GPT-4o         │  │  - 实时捕获输出               │
│  - Gemini                │  │  - 错误检测                   │
│  - Ollama（本地免费）      │  │                               │
│  - Anthropic Claude API  │  │  Claude Code 进程             │
│  - 任何 OpenAI 兼容服务   │  │  (Max Plan，不额外收费)       │
└──────────────────────────┘  └───────────────────────────────┘
               │                          │
               └──────────┬───────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Zellij Session (zellij_session.py)          │
│                                                              │
│  ┌─────────────────┬────────────────────────────────────┐   │
│  │ 📋 Meta-Agent   │  ⚡ Claude Code 输出               │   │
│  │    日志          │                                    │   │
│  │                 │                                    │   │
│  │ [10:23:01] 分析  │  > 正在创建 main.py...             │   │
│  │   需求...        │  > 安装依赖 fastapi...              │   │
│  │ [10:23:05] 指令  │  > 运行测试...                     │   │
│  │   已发送         ├────────────────────────────────────┤   │
│  │ [10:23:12] 检测  │  📊 任务状态                       │   │
│  │   到错误，重试... │  任务: a1b2c3d4                    │   │
│  │                 │  状态: ⚙️ 运行中 (Turn 3/30)       │   │
│  └─────────────────┴────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
claude-autopilot/
├── README.md
├── config.example.yaml        # 配置模板
├── requirements.txt
├── setup.py                   # pip install -e . 后可用 autopilot 命令
└── autopilot/
    ├── __init__.py
    ├── cli.py                 # 命令行入口
    ├── config.py              # 配置加载（支持环境变量替换）
    ├── orchestrator.py        # 调度核心，串联所有组件
    ├── meta_agent.py          # Meta-Agent，可插拔大模型后端
    ├── claude_driver.py       # pexpect 驱动 Claude Code 进程
    └── zellij_session.py      # Zellij 会话和多面板管理
```

## 配置示例

### 用 DeepSeek（最省钱，推荐）
```yaml
meta_agent:
  provider: deepseek
  model: deepseek-chat
  api_key: ${DEEPSEEK_API_KEY}
```

### 用 Ollama 本地模型（完全免费）
```yaml
meta_agent:
  provider: ollama
  model: qwen2.5:14b
  # 不需要 api_key
```

### 用 OpenAI
```yaml
meta_agent:
  provider: openai
  model: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
```

### 用 Gemini
```yaml
meta_agent:
  provider: gemini
  model: gemini-2.0-flash
  api_key: ${GEMINI_API_KEY}
```

## 使用方式

```bash
# 安装
pip install -e .

# 执行需求
autopilot run "帮我实现一个 FastAPI 用户登录接口，包含 JWT 认证"

# 不启动 Zellij（纯命令行模式）
autopilot run --no-zellij "优化这个项目的数据库查询性能"

# 临时切换模型
autopilot run --provider ollama --model qwen2.5:14b "写单元测试"

# 多行需求（交互模式）
autopilot run
# 然后粘贴需求，两次回车确认
```

## 成本分析

| 场景 | Meta-Agent | Claude Code | 费用 |
|------|-----------|-------------|------|
| Ollama 本地模型 | 免费 | Max Plan | 💚 零额外费用 |
| DeepSeek-chat | ~$0.001/1K tokens | Max Plan | 💚 极低成本 |
| GPT-4o-mini | ~$0.0002/1K tokens | Max Plan | 💚 低成本 |
| GPT-4o | ~$0.005/1K tokens | Max Plan | 💛 中等成本 |

Meta-Agent 只做"分析+决策"，每轮消耗 token 很少，选 DeepSeek 或 Ollama 完全够用。

## 关键设计决策

1. **为什么用 pexpect 而非 subprocess**：Claude Code 是交互式进程，需要实时读写 stdin/stdout，pexpect 专为此设计。

2. **为什么 Meta-Agent 用 OpenAI 兼容协议**：DeepSeek、Ollama、Azure、大多数国产大模型都兼容此协议，只需改 base_url，无需改代码。

3. **为什么用 Zellij 而非 tmux**：Zellij 原生支持 KDL 布局文件，Python 可以直接生成配置文件然后启动，比 tmux 的脚本控制更可靠；同时 Zellij 的面板管理更现代。

4. **任务状态通过文件传递**：Zellij 面板用 `tail -f` 和 `watch` 监控文件，解耦了进程间通信，简单可靠。
