# Maestro

**用 Manager Agent 自动驱动编码工具完成开发任务**

Maestro 是一个 Python CLI 工具。它在外层运行一个可配置的 Manager Agent（通过 OpenAI 兼容 API 或 Anthropic 原生 SDK 调用任意 LLM），在内层驱动 Claude Code、Codex CLI、Gemini CLI 等编码工具执行代码变更。Manager 分析编码工具的输出，以 JSON 格式生成下一步指令，形成闭环，直到任务完成。支持 VPS 后台运行和 Telegram 远程控制。

---

## 前提条件

- 一台 VPS：Debian/Ubuntu，2GB+ 内存，2GB+ 磁盘
- 本地 Mac 能通过 SSH 访问 VPS
- 一个 LLM API Key 用于 Manager Agent（推荐 DeepSeek，约 ¥1/百万 token）
- 如使用密码认证 SSH，需先安装 sshpass：`brew install hudochenkov/sshpass/sshpass`

---

## 快速开始

### 第一步：填写部署配置

```bash
git clone <仓库地址>
cd Maestro
cp deploy.env.example deploy.env
```

编辑 `deploy.env`，填写以下必要项：

```bash
# ---- VPS 连接 ----
VPS_HOST="your.vps.ip"          # VPS IP（必填）
VPS_USER="root"                  # SSH 用户（必填）
VPS_SSH_KEY="~/.ssh/id_rsa"     # SSH 私钥路径（推荐）

# ---- Manager Agent（外层决策 AI）----
MANAGER_PROVIDER="deepseek"      # 或 openai / anthropic / gemini / ollama
MANAGER_MODEL="deepseek-chat"
MANAGER_API_KEY="sk-xxx"         # 填入 API Key

# ---- 编码工具（内层执行工具）----
CODING_TOOLS="claude,codex"      # 要安装的工具，逗号分隔
DEFAULT_CODING_TOOL="claude"     # 默认激活的工具

# ---- Telegram 远程控制（可选）----
TELEGRAM_BOT_TOKEN=""            # 从 @BotFather 获取
TELEGRAM_CHAT_ID=""              # 从 @userinfobot 获取
```

> 完整配置项见 [deploy.env 配置参考](#deployenv-配置参考)。

### 第二步：执行部署

```bash
bash deploy.sh init
```

脚本自动完成：传输代码 → 创建运行用户 → 安装系统依赖 → 安装编码工具 → 创建虚拟环境 → 生成 config.yaml → 配置 systemd 服务 → 引导编码工具认证。

### 第三步：开始使用

SSH 登录 VPS：

```bash
ssh your.vps.ip
su - viber                       # 切换到运行用户（默认 viber）

maestro run "实现一个用户登录接口"  # 后台运行
maestro run -f "修复失败的测试"    # 前台运行（实时输出）
maestro list                      # 查看任务列表
maestro status <task_id>          # 查看任务详情
```

配置了 Telegram 后，直接在手机上用 `/run`、`/list`、`/status` 等指令远程操控。

---

## 日常运维

### 代码更新

```bash
bash deploy.sh update
```

只同步代码和配置，不影响系统环境和编码工具认证。自动备份并恢复 VPS 上的 `prompts/` 目录。

### 服务管理

```bash
bash deploy.sh service start     # 启动 Telegram Daemon
bash deploy.sh service stop
bash deploy.sh service restart
```

### 切换编码工具

```bash
maestro switch codex             # 切换到 Codex CLI
maestro switch                   # 查看当前和可用工具
# 或 Telegram: /switch codex
```

切换只对新启动的任务生效，运行中的任务不受影响。

### 交互菜单

```bash
bash deploy.sh                   # 不带参数进入交互菜单
```

包含：首次部署、业务更新、查看 VPS 状态、服务管理、清理卸载等选项。

---

## deploy.env 配置参考

### VPS 连接

```bash
VPS_HOST="your.vps.ip"          # VPS IP 或域名（必填）
VPS_PORT="22"                    # SSH 端口
VPS_USER="root"                  # SSH 用户（必填）
VPS_SSH_KEY="~/.ssh/id_rsa"     # SSH 私钥路径（推荐，与密码二选一）
VPS_PASSWORD=""                  # SSH 密码（需 sshpass）
```

### Manager Agent

| Provider | MANAGER_PROVIDER | MANAGER_MODEL | MANAGER_BASE_URL |
|----------|-----------------|---------------|-----------------|
| DeepSeek（推荐） | `deepseek` | `deepseek-chat` | 留空 |
| OpenAI | `openai` | `gpt-4o-mini` | 留空 |
| Anthropic | `anthropic` | `claude-sonnet-4-20250514` | 留空 |
| Google Gemini | `gemini` | `gemini-2.0-flash` | 留空 |
| Ollama | `ollama` | `qwen2.5:14b` | 留空 |
| Azure OpenAI | `azure` | 部署名 | 必须填写 |
| OpenRouter 等 | `openai` | 按文档填 | 填入端点地址 |

```bash
MANAGER_PROVIDER="deepseek"
MANAGER_MODEL="deepseek-chat"
MANAGER_API_KEY="sk-xxx"
MANAGER_BASE_URL=""              # 大多数留空
```

### 编码工具

```bash
CODING_TOOLS="claude,codex"      # 逗号分隔，init 时全部安装
DEFAULT_CODING_TOOL="claude"     # 默认激活工具
ANTHROPIC_API_KEY=""             # 填入则自动配置，留空则部署后引导 claude login
```

### Telegram Bot（可选）

```bash
TELEGRAM_BOT_TOKEN=""            # 从 @BotFather 获取
TELEGRAM_CHAT_ID=""              # 从 @userinfobot 获取
```

### 运行用户

```bash
MAESTRO_RUN_USER="viber"         # 非 root 运行用户（自动创建）
MAESTRO_RUN_PASSWORD=""          # 留空则自动生成 16 位密码
```

### 网络

```bash
PREFER_IPV4="true"               # 系统级 IPv4 优先（gai.conf），覆盖所有进程
```

---

## CLI 命令参考

| 命令 | 用法 | 说明 |
|------|------|------|
| run | `maestro run [-f] [-w 目录] [-c config] [--provider P] [--model M] "需求"` | 启动任务（默认后台，`-f` 前台运行） |
| list | `maestro list` | 查看所有任务列表及状态 |
| status | `maestro status <task_id>` | 查看任务详情（进度、费用、最近输出） |
| ask | `maestro ask <task_id> "消息"` | 向任务注入用户反馈（用于 ask_user 等待时） |
| chat | `maestro chat <task_id> "问题"` | 与 Manager Agent 对话（不影响任务本身） |
| abort | `maestro abort <task_id>` | 终止运行中的任务 |
| resume | `maestro resume [-f] <task_id>` | 恢复崩溃或中断的任务 |
| report | `maestro report <task_id>` | 查看任务完成报告 |
| switch | `maestro switch [工具名]` | 切换编码工具（不带参数显示可用列表） |
| daemon | `maestro daemon start\|stop\|status` | 管理 Telegram Daemon 进程 |

**常用示例：**

```bash
# 后台启动，稍后查看
maestro run "实现分页查询接口"
maestro list
maestro status abc123

# 前台运行，实时看输出
maestro run -f "写一个 Fibonacci 数列的单元测试"

# 任务卡住时发送提示
maestro ask abc123 "忽略 lint 错误，专注功能实现"

# 询问 Manager 当前状况
maestro chat abc123 "你现在遇到了什么问题？"

# 切换编码工具后启动新任务
maestro switch codex
maestro run "重构数据库连接池"

# 恢复崩溃的任务
maestro resume abc123
```

---

## Telegram 命令参考

| 命令 | 说明 |
|------|------|
| `/cd <路径>` | 设置后续任务的默认工作目录 |
| `/run <需求>` | 启动新任务 |
| `/list` | 查看所有任务列表 |
| `/status [id]` | 查看任务详情 |
| `/ask [id] <消息>` | 向任务注入反馈 |
| `/chat [id] <问题>` | 与 Manager Agent 对话 |
| `/abort [id]` | 终止任务 |
| `/report [id]` | 查看任务报告 |
| `/switch [工具名]` | 切换编码工具 |
| `/focus [id]` | 关注任务，实时推送每轮输出（省略 id 取消关注） |
| `/new` | 重置自由聊天历史 |

- 省略 `[id]` 的命令自动作用于当前 `/focus` 的任务
- 直接发送消息（非命令）进入自由聊天模式
- 任务状态变更（完成、失败、需要用户输入）自动推送通知
- 回复通知消息可直接向对应任务发送反馈

---

## License

MIT License（见 LICENSE 文件）
