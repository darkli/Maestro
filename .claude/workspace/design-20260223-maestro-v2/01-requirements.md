# 需求分析文档

## 1. 核心需求清单

### 1.1 Agent 自动驱动 Claude Code

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| R-1.1 | Agent（Manager）接收用户需求后，自动启动 Claude Code CLI 进程 | P0 |
| R-1.2 | Manager 分析 Claude Code 每轮输出，生成下一步指令 | P0 |
| R-1.3 | Manager 替用户做决策（确认、选择等）| P0 |
| R-1.4 | 检测任务完成（DONE）或阻塞（BLOCKED），自动终止循环 | P0 |
| R-1.5 | 支持 ASK_USER 信号，Manager 无法决定时请求用户介入 | P0 |
| R-1.6 | 超过最大轮数自动熔断 | P0 |

### 1.2 Manager AI 灵活配置

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| R-2.1 | 通过配置文件指定 provider（DeepSeek、OpenAI、Anthropic、Gemini、Ollama 等）| P0 |
| R-2.2 | 通过配置文件指定 model | P0 |
| R-2.3 | 支持自定义 base_url（兼容任何 OpenAI 协议服务）| P0 |
| R-2.4 | 支持自定义 system_prompt | P1 |
| R-2.5 | 支持运行时命令行参数覆盖 provider/model | P1 |
| R-2.6 | 环境变量 `${VAR}` 语法展开 API Key | P0 |

### 1.3 远程 VPS 后台运行

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| R-3.1 | 任务在后台运行，SSH 断开后不中断 | P0 |
| R-3.2 | 基于 Zellij Session 实现进程保活 | P0 |
| R-3.3 | Zellij 未安装时自动安装预编译二进制 | P1 |
| R-3.4 | 守护进程（Daemon）长驻后台管理所有任务 | P0 |

### 1.4 SSH 交互查看

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| R-4.1 | `zellij attach` 查看任务实时输出（多面板 UI）| P0 |
| R-4.2 | CLI 命令查看任务列表和状态 | P0 |
| R-4.3 | CLI 命令给运行中的任务发送消息 | P1 |
| R-4.4 | CLI 命令终止/恢复任务 | P1 |

### 1.5 Telegram Bot 远程控制

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| R-5.1 | `/run` 命令远程启动任务 | P0 |
| R-5.2 | `/list` `/status` 查看任务状态 | P0 |
| R-5.3 | `/ask` 给任务发送用户指令 | P0 |
| R-5.4 | `/abort` 终止任务 | P1 |
| R-5.5 | `/report` 获取任务完成报告 | P1 |
| R-5.6 | 自动推送每轮进度 | P0 |
| R-5.7 | ASK_USER 时推送通知，支持直接回复 | P0 |
| R-5.8 | 任务完成/失败自动推送通知 | P0 |
| R-5.9 | 授权用户 ID 限制（安全控制）| P0 |

### 1.6 多任务并行

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| R-6.1 | 同时运行多个独立任务 | P1 |
| R-6.2 | 任务间进程/会话/目录/状态完全隔离 | P1 |
| R-6.3 | 全局任务注册表管理 | P1 |

## 2. 现有方案与需求的对照分析

### 2.1 方案已覆盖的需求

方案（终稿 v5）已涵盖上述所有核心需求 R-1.x 至 R-6.x。以下是方案的优势：

- 架构清晰，组件划分合理（Orchestrator/Manager/Runner/Registry/Notifier/Telegram）
- 文件 IPC 设计简洁（state.json + inbox.txt）
- Zellij Session 隔离方案可靠
- 边界防御表全面（12 种异常场景）

### 2.2 方案存在的疏漏和待完善点

经过详细分析，发现以下疏漏：

---

#### 疏漏 1: Claude Code 交互方式转换细节不足

**现状**：现有代码使用 pexpect 控制交互式 Claude Code 进程。方案提到使用 `claude -p --output-format json`，但缺少以下细节：

- `claude -p` 是 **非交互式模式（print mode）**，每次调用是独立进程，不保持会话
- 需要通过 `--resume <session_id>` 实现多轮对话的上下文延续
- 方案未明确说明每轮是 **启动新进程** 还是 **复用进程**
- 未说明 JSON 输出的解析格式和字段映射
- 未说明 `--resume` 的 session_id 获取方式（首轮创建，后续复用）

**影响**：这是架构最核心的变更（pexpect → subprocess），细节不足会导致实现歧义。

---

#### 疏漏 2: Manager Agent 的输出格式约束不完整

**现状**：方案提到 Manager 必须以 JSON 回复 `{"action":"...","instruction":"...","reasoning":"..."}`，但：

- 未定义 `action` 的完整枚举值（方案隐含了 EXECUTE、DONE、BLOCKED、ASK_USER，但未列出完整列表）
- 未定义 JSON 解析失败时的 fallback 策略（现有代码直接返回纯文本，新方案要求 JSON，过渡如何处理？）
- 未说明 `reasoning` 字段的用途（仅日志记录？还是作为上下文传递给下一轮？）
- 未定义 ASK_USER action 的消息体格式（问题描述如何传递给用户？）

**影响**：Manager 输出格式是系统运转的核心协议，不明确会导致解析错误。

---

#### 疏漏 3: state.json 状态机定义缺失

**现状**：方案在 registry.json 中使用了 `status` 字段（值包括 `executing`、`waiting_user`），但：

- 未定义完整的状态枚举（如 `pending`、`executing`、`waiting_user`、`completed`、`failed`、`aborted`、`recovering`）
- 未定义状态转换规则（哪些状态之间可以转换？）
- 未定义 state.json 的完整字段结构
- state.json 和 registry.json 中的 status 是否同步？如何保持一致？

**影响**：没有明确的状态机，多个组件（Orchestrator、Daemon、CLI）对状态的读写可能不一致。

---

#### 疏漏 4: inbox.txt 的并发安全问题

**现状**：方案使用 inbox.txt 作为用户→任务的消息通道，但：

- 未定义 inbox.txt 的读写协议（Orchestrator 读完后是否清空？还是追加模式？）
- 多来源写入（CLI `ask`、Telegram 回复）是否有竞争条件？
- Orchestrator 何时检查 inbox.txt？每轮循环开始时？还是异步监听？
- 未定义消息格式（纯文本？带时间戳？带来源标记？）

**影响**：文件 IPC 的并发安全需要明确协议，否则可能丢消息或重复消费。

---

#### 疏漏 5: checkpoint.json 崩溃恢复细节缺失

**现状**：方案提到 checkpoint + `maestro resume`，但：

- 未定义 checkpoint.json 的数据结构（保存哪些状态？对话历史？当前轮数？Claude session_id？）
- 未说明 checkpoint 的写入时机（每轮结束后？还是关键状态变更时？）
- resume 时如何恢复 Manager 的对话上下文？
- resume 时如何恢复 Claude Code 的会话（`--resume session_id` 是否够用？）
- 崩溃后 Zellij Session 是否仍然存活？布局如何重建？

**影响**：崩溃恢复是 VPS 长时间运行的关键保障，细节不足会导致恢复失败。

---

#### 疏漏 6: 费用追踪机制缺失

**现状**：方案提到 `max_budget_usd: 5.0` 和消息推送中的费用信息（`$0.82`），但：

- 未说明费用从哪里获取（Claude Code 的 JSON 输出中是否包含 token/cost 信息？）
- Manager Agent 的调用费用如何计算？
- 费用数据保存在哪个文件？state.json？
- 熔断时的具体逻辑（累计 > max_budget → 停止？还是发 ASK_USER？）

**影响**：费用控制是配置的重要部分，但获取方式未明确。

---

#### 疏漏 7: Telegram Bot 安全性不足

**现状**：方案只提到 `chat_id` 做授权，但：

- 未说明 chat_id 是单用户还是支持多用户/群组
- 未考虑恶意命令注入（`/run` 的 working_dir 参数可能被用于目录遍历）
- 未说明 Bot Token 泄露后的应对（是否需要白名单 IP？）
- 未考虑 rate limiting（防止 Bot 被滥用刷 API）

**影响**：在远程 VPS 上运行，安全性需要更严格的考虑。

---

#### 疏漏 8: 日志管理和清理策略缺失

**现状**：方案提到 `~/.maestro/logs` 目录，但：

- 未说明日志文件的命名规则和组织结构
- 未定义日志保留策略（长时间运行会积累大量日志）
- 未说明 state.json / checkpoint.json / report.md 等运行时文件的清理策略
- Phase 3 提到"日志清理"但无具体方案

**影响**：VPS 磁盘空间有限，无清理策略可能导致磁盘满。

---

#### 疏漏 9: Zellij 自动安装的细节缺失

**现状**：方案提到"自动安装预编译二进制"，但：

- 未说明安装路径（`~/.local/bin`？`/usr/local/bin`？）
- 未说明如何选择正确的二进制版本（amd64 vs arm64）
- 未说明下载失败的 fallback（无网络环境？）
- 未说明是否需要 sudo 权限

**影响**：Ubuntu VPS 环境差异大，自动安装需要健壮的逻辑。

---

#### 疏漏 10: 从 autopilot 到 maestro 的迁移策略缺失

**现状**：现有代码使用 `autopilot.*` 包前缀，方案使用 `maestro.*`，但：

- 未说明迁移步骤（是一次性重命名还是逐步替换？）
- 未说明现有用户的 `~/.autopilot/` 数据如何迁移到 `~/.maestro/`
- 未说明 `config.yaml` 的字段名变更（`meta_agent` → `manager`）是否需要兼容旧格式
- 未说明 `pyproject.toml` 的配置（entry_points、依赖等）

**影响**：如果有用户已在使用旧版，需要平滑迁移。

---

#### 疏漏 11: 通知抽象层（notifier.py）的设计缺失

**现状**：方案在目录结构中列出 `notifier.py`，但未给出任何设计细节：

- Notifier 与 Telegram Bot 的关系是什么？（是 Telegram 的上层抽象？还是平级？）
- 是否支持其他通知通道（如 webhook、email、Slack）？
- Notifier 的接口定义是什么？

**影响**：通知是系统的核心能力，设计缺失影响扩展性。

---

#### 疏漏 12: llm_client.py 与 manager_agent.py 的职责边界模糊

**现状**：方案同时有 `llm_client.py`（通用 LLM 客户端）和 `manager_agent.py`（Manager Agent），但：

- 现有代码中 MetaAgent 内部直接调用 OpenAI SDK，不存在独立的 LLM 客户端层
- llm_client.py 是否只是从 manager_agent.py 中抽取的底层调用？
- 如果未来有多个 Agent 需要调用 LLM，llm_client.py 作为公共模块合理，但方案未说明这一点

**影响**：模块拆分需要明确职责，否则增加不必要的复杂度。

---

#### 疏漏 13: context.py 上下文管理的具体策略缺失

**现状**：方案提到 `max_recent_turns: 5` 和 `max_result_chars: 3000`，但：

- 未说明上下文压缩的具体算法（截断？摘要？滑动窗口？）
- Claude Code 每轮输出可能非常长（几千行代码），`max_result_chars: 3000` 如何截取？从头部还是尾部？
- Manager 的对话历史如何与 context.py 配合？是传全量历史给 LLM 还是只传压缩后的？
- 压缩后的上下文是否会丢失关键信息？

**影响**：上下文管理直接影响 Manager 的决策质量和 API 成本。

---

#### 疏漏 14: reporter.py 报告生成的内容定义缺失

**现状**：方案提到 `/report` 命令和 `report.md`，但：

- 未定义报告的内容模板（包含哪些章节？）
- 报告是任务完成后自动生成，还是按需生成？
- 报告是否包含代码 diff？修改文件列表？测试结果？

**影响**：报告是用户了解任务成果的关键通道。

---

#### 疏漏 15: `_worker` 内部命令未设计

**现状**：Telegram Daemon 通过 `maestro _worker task_id requirement` 启动任务进程，但：

- `_worker` 命令在 CLI 命令列表中未出现
- `_worker` 是内部命令，需要在 CLI 中注册但对用户隐藏
- `_worker` 如何接收 working_dir 参数？
- `_worker` 是否需要载入完整配置？

**影响**：这是 Daemon 与 Worker 之间的关键接口。

---

## 3. 非功能性需求

| 需求项 | 描述 | 优先级 |
|--------|------|--------|
| NFR-1 | 进程保活：SSH 断开后任务继续运行 | P0 |
| NFR-2 | 崩溃恢复：Python 崩溃后可通过 resume 恢复 | P1 |
| NFR-3 | 资源控制：费用上限、轮数上限、超时控制 | P0 |
| NFR-4 | 安全性：Bot 访问控制、目录权限控制 | P1 |
| NFR-5 | 可观测性：日志、状态文件、Telegram 推送 | P0 |
| NFR-6 | 可扩展性：新增 LLM provider 无需改代码 | P1 |
| NFR-7 | 低资源占用：VPS 通常内存有限（1-4GB）| P1 |
| NFR-8 | 网络容错：Telegram 断网后自动重连 | P2 |
| NFR-9 | 幂等性：resume 多次不应产生副作用 | P1 |

## 4. 验收标准

### AC-1: 基础闭环
- [ ] 配置 Manager provider/model 后，`maestro run "需求"` 能启动任务
- [ ] Manager 能分析 Claude Code 输出并生成指令
- [ ] 任务完成后输出 DONE 并退出
- [ ] 任务阻塞后输出 BLOCKED 原因并退出

### AC-2: VPS 后台运行
- [ ] 任务在 Zellij Session 中运行
- [ ] SSH 断开后任务不中断
- [ ] `zellij attach` 可查看实时进度
- [ ] 多面板显示 Manager 日志、Claude 输出、任务状态

### AC-3: Telegram Bot
- [ ] `/run` 远程启动任务并推送开始通知
- [ ] 每轮自动推送进度
- [ ] ASK_USER 时推送通知，回复可路由回任务
- [ ] 任务完成后推送汇总通知
- [ ] `/list` 显示所有任务状态
- [ ] `/status` 显示指定任务详情
- [ ] `/abort` 可终止任务
- [ ] 仅授权 chat_id 可操作

### AC-4: 多任务
- [ ] 同时启动 2 个任务，各自独立运行
- [ ] 不同任务使用不同 working_dir
- [ ] `/list` 正确显示所有任务状态
- [ ] 终止一个任务不影响其他任务

### AC-5: 容错
- [ ] Manager API 超时时重试 3 次
- [ ] 超过 max_turns 自动停止
- [ ] 超过 max_budget 自动停止
- [ ] Python 崩溃后 `maestro resume` 可恢复
- [ ] Zellij 未安装时自动安装

## 5. 对现有模块的影响评估

| 现有模块 | 变更程度 | 说明 |
|----------|----------|------|
| cli.py | **重写** | 新增多个子命令，引入 daemon 管理 |
| orchestrator.py | **大改** | 新增状态机、checkpoint、inbox 监听、notifier 集成 |
| meta_agent.py | **重构** | 拆分为 manager_agent.py + llm_client.py，输出改为 JSON 格式 |
| claude_driver.py | **重写** | pexpect → subprocess (`claude -p --output-format json`)，改名 claude_runner.py |
| config.py | **大改** | 新增 telegram/safety/context 配置段，字段重命名 |
| zellij_session.py | **重构** | 改名 session.py，新增自动安装逻辑，适配多任务 |
| （新增）telegram_bot.py | **新建** | Telegram Daemon + Bot 命令处理 |
| （新增）registry.py | **新建** | 多任务注册表 |
| （新增）notifier.py | **新建** | 通知抽象层 |
| （新增）reporter.py | **新建** | 报告生成 |
| （新增）state.py | **新建** | 状态机 + 熔断器 |
| （新增）context.py | **新建** | 上下文管理 + 压缩 |
