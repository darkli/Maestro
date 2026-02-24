# 设计方案 Review（终审）

基于 `implementation_plan.md`（终稿 v5）+ `02-design.md`（15 项疏漏补充）的完整审查。
目标：确保方案**可实施、无遗漏、不过度设计**，适合个人远程 vibe coding 场景。

---

## 一、过度设计项（建议砍掉或简化）

### 1.1 砍掉 `llm_client.py`，合并回 `manager_agent.py`

**原设计**：02-design.md 第十二节将 LLM 调用拆分为独立模块，理由是"未来可能有其他 Agent 复用"。

**问题**：个人工具只有一个 Manager Agent，不存在复用场景。当前 `meta_agent.py` 已经把多 provider 支持写得很好（OpenAI 兼容 + Anthropic 原生），再抽一层只增加间接调用和维护负担。

**做法**：`ManagerAgent` 内部直接调用 SDK，只在其中加上重试逻辑和费用估算方法。省掉一个模块、一个 dataclass (`LLMResponse`)、一层间接调用。

### 1.2 砍掉 `notifier.py` 抽象层

**原设计**：ABC 接口 `Notifier` + `LogNotifier` + `TelegramNotifier` + `CompositeNotifier`，四个类。

**问题**：通知只有两个目标：日志和 Telegram。为两个目标建策略模式是典型的过度抽象。

**做法**：在 `Orchestrator` 内直接写 `_log_event()`（写日志）和 `_telegram_push()`（发 Telegram 通知，try/except 降级到日志）。共约 40 行代码，职责清晰，无需抽象。

### 1.3 砍掉 `inbox.py` 独立模块

**原设计**：独立模块封装 `write_inbox()` + `read_and_clear_inbox()` 两个函数。

**问题**：两个函数不值得单独建模块。

**做法**：这两个函数放到 `orchestrator.py` 内作为模块级工具函数，或放到通用 `utils.py` 中（如果有的话）。

### 1.4 砍掉 `reporter.py` 独立模块

**原设计**：独立模块 + Markdown 模板 + git diff 获取修改文件列表。

**问题**：报告本质上是把 `state.json` 格式化成可读文本。一个 50 行的函数足够。

**做法**：放到 `orchestrator.py` 中作为 `_generate_report()` 方法。在任务完成时调用，输出到 `~/.maestro/sessions/<task_id>/report.md`。

### 1.5 简化 Telegram 安全设计

**原设计**（02-design.md 第七节）：

- 多用户白名单 `allowed_chat_ids: list[int]`
- Rate limiting（每用户每分钟 10 条）
- 审计日志 `telegram-audit.log`
- 目录黑名单检查（`.ssh`、`.gnupg` 等）

**问题**：这是团队级别的安全设计。个人工具只有一个用户。

**做法**：Phase 1 只做：

- 单个 `chat_id` 校验（配置项 `telegram.chat_id`）
- `working_dir` 必须在 `$HOME` 下（`os.path.realpath` + `startswith`）

其余安全措施（rate limiting、审计日志、多用户）标注为 Phase 3 可选增强，不在 Phase 1/2 实现。

### 1.6 简化日志清理策略

**原设计**（02-design.md 第八节）：三维度清理——`max_task_logs`（数量）+ `max_days`（天数）+ `max_total_size_mb`（大小）。

**做法**：只保留一个维度 `max_days: 30`。Daemon 启动时扫描 `~/.maestro/sessions/`，删除超期目录。约 10 行代码。

### 1.7 砍掉 autopilot → maestro 迁移逻辑

**原设计**（02-design.md 第十节）：`_migrate_data_dir()`、旧版字段名兼容（`meta_agent` → `manager`）、数据目录自动迁移。

**问题**：个人项目，无外部用户，无需向后兼容。

**做法**：Phase 1 开始时一次性重命名所有 `autopilot` → `maestro`，直接删旧代码。不写任何兼容层。

### 1.8 砍掉 `budget_action` 配置项

**原设计**：`budget_action: ask_user | abort` 两种超预算行为可选。

**做法**：永远 `ask_user`。超预算时通知用户确认，超时无回复再 abort。不需要配置项。

---

## 二、可行性问题（必须修复）

### 2.1 Worker 进程健康监控缺失

**问题**：Daemon 的 `_monitor_loop` 只轮询 `state.json`。如果 Worker 进程崩溃但没来得及更新 state（如 OOM kill、segfault），任务会永远卡在 `executing` 状态，Daemon 无法感知。

**修复**：Worker 启动时把 PID 写入 `state.json`。Daemon 轮询时除了读 state，还检查进程是否存活：

```python
# state.json 增加字段
"worker_pid": 12345

# Daemon monitor 增加检查
def _check_worker_health(self, task_id: str, state: dict):
    if state["status"] == "executing":
        pid = state.get("worker_pid")
        if pid:
            try:
                os.kill(pid, 0)  # 不发信号，仅检查进程存在
            except ProcessLookupError:
                self._mark_task_failed(task_id, "Worker 进程意外退出")
                self._telegram_push(f"❌ [{task_id}] Worker 崩溃，可用 maestro resume {task_id} 恢复")
```

### 2.2 `state.json` 缺少原子写入

**问题**：02-design.md 为 `checkpoint.json` 设计了 tmp+rename 原子写入，但 `state.json` 没有。Daemon 和 Orchestrator 并发读写同一个文件，可能读到半写数据（JSON 截断 → 解析失败）。

**修复**：所有 JSON 文件写入统一使用 tmp+rename 模式。提供一个工具函数：

```python
def atomic_write_json(path: str, data: dict):
    """原子写入 JSON 文件（写临时文件再 rename，防止读到半写数据）"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp, path)
```

`state.json`、`checkpoint.json`、`registry.json` 三个文件的写入全部走此函数。

### 2.3 Daemon 进程模型不明确

**问题**：方案说"通过 systemd 或 Zellij 管理" Daemon，但没有做出选择。两者各有问题：

- systemd：需要 root 或 `--user` 模式，配置复杂
- Zellij：Zellij 会话被意外关闭则 Daemon 丢失

**修复**：采用最简单的 `nohup` + PID 文件方案：

```bash
# maestro daemon start
nohup python -m maestro.telegram_bot >> ~/.maestro/logs/daemon.log 2>&1 &
echo $! > ~/.maestro/daemon.pid

# maestro daemon stop
kill $(cat ~/.maestro/daemon.pid) && rm ~/.maestro/daemon.pid

# maestro daemon status
kill -0 $(cat ~/.maestro/daemon.pid) 2>/dev/null && echo "运行中" || echo "未运行"
```

不依赖 systemd（不需要 root），不依赖 Zellij（减少耦合）。Daemon 日志写到 `~/.maestro/logs/daemon.log`。

可选增强（Phase 3）：如果需要更可靠，可加一个简单的 watchdog 脚本或 cron job 定期检查 Daemon 是否存活。

### 2.4 优雅停止（abort）机制缺失

**问题**：`maestro abort <id>` 或 `/abort <id>` 只修改 `state.json` 状态。但 Orchestrator 是 `state.json` 的**写入方**，不会主动读取它——无法感知外部的 abort 请求。

**修复**：使用信号文件。外部 abort 命令创建 `~/.maestro/sessions/<task_id>/abort` 文件，Orchestrator 每轮循环开始时检查：

```python
# orchestrator.py 主循环每轮开头
def _check_abort(self) -> bool:
    abort_file = self.session_dir / "abort"
    if abort_file.exists():
        abort_file.unlink()
        return True
    return False

# 在 _main_loop 中
for turn in range(start_turn, max_turns + 1):
    if self._check_abort():
        self._update_state("aborted")
        self._telegram_push(f"⛔ [{self.task_id}] 已终止")
        return

    # ... 正常逻辑
```

外部 abort 实现：

```python
# cli.py 或 telegram_bot.py 中
def abort_task(task_id: str):
    abort_file = Path(f"~/.maestro/sessions/{task_id}/abort").expanduser()
    abort_file.touch()
    # 同时更新 registry 状态
    registry.update_task(task_id, status="aborted")
```

### 2.5 Telegram Daemon 异步边界

**问题**：`python-telegram-bot>=21.0` 是 async 库（基于 asyncio）。Orchestrator/Runner 全是同步代码。虽然 Daemon 和 Worker 是独立进程不冲突，但 Daemon 内部同时要做两件事：

1. 接收 Telegram 消息（async，事件驱动）
2. 轮询 state.json 监控任务（周期性）

这两者如何在同一个 asyncio event loop 中协调，设计未明确。

**修复**：明确 Daemon 内部架构：

```python
class TelegramDaemon:
    async def start(self):
        # 1. 初始化 Telegram Bot（async）
        app = Application.builder().token(self.config.bot_token).build()
        app.add_handler(CommandHandler("run", self._on_run))
        app.add_handler(CommandHandler("list", self._on_list))
        # ...

        # 2. 启动 state 监控任务（asyncio task，非线程）
        asyncio.create_task(self._monitor_loop())

        # 3. 启动 Bot polling（阻塞在此）
        await app.run_polling()

    async def _monitor_loop(self):
        """协程：定期轮询所有 task 的 state.json"""
        while True:
            for task_id in self._list_tasks():
                state = self._read_state(task_id)  # 文件 IO，极快，不需要 executor
                if self._has_changed(task_id, state):
                    await self._push_update(task_id, state)
            await asyncio.sleep(3)
```

关键点：**全部用 asyncio 协程**，不混用线程。文件 IO 很快（读几个 JSON），不需要 `run_in_executor`。

### 2.6 `_wait_for_user_reply` 轮询细节缺失

**问题**：Orchestrator 的 ASK_USER 处理中 `_wait_for_user_reply()` 会阻塞主循环等待用户回复。设计没说明轮询间隔和具体逻辑。

**修复**：明确为文件轮询，间隔 5 秒，同时检查 abort 信号：

```python
def _wait_for_user_reply(self) -> Optional[str]:
    """
    阻塞等待用户通过 inbox.txt 回复。
    返回用户消息，超时返回 None。
    轮询间隔 5 秒。
    """
    deadline = time.time() + self.config.telegram.ask_user_timeout
    while time.time() < deadline:
        # 同时检查 abort
        if self._check_abort():
            return None

        messages = self._read_and_clear_inbox()
        if messages:
            return "\n".join(msg.split("|", 2)[2] for msg in messages)

        time.sleep(5)

    return None  # 超时
```

### 2.7 Manager system_prompt 不够完整

**问题**：JSON 输出格式要可靠工作，system_prompt 必须包含严格的格式说明和示例。当前设计只有一行概要 `"必须以 JSON 回复: {...}"`。实测表明，许多模型（尤其 deepseek-chat）没有足够的 few-shot 示例时，JSON 格式遵从率较低。

**修复**：在 `config.example.yaml` 和代码中 `DEFAULT_SYSTEM_PROMPT` 提供完整 prompt：

```
你是资深工程师助手，负责分析 Claude Code 的输出并决定下一步操作。

## 严格要求

你的每次回复必须是且仅是一个 JSON 对象，不要有任何其他文字。

## 可用 Action

1. execute — 向 Claude Code 发送下一条指令
2. done — 任务已完成
3. blocked — 遇到无法自动解决的阻塞
4. ask_user — 需要用户做决定
5. retry — 重试上一条指令（Claude 出错时使用）

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
{"action":"retry","instruction":"","reasoning":"Claude 返回了模型错误，重试一次"}

## 决策原则

- 优先推进任务，减少不必要的确认
- 遇到小问题自己决定，只有重大决策才 ask_user
- 每条指令要具体、可执行，不要泛泛而谈
- 如果 Claude Code 已经完成了所有需求且没有报错，果断 done
```

### 2.8 首次部署流程缺失

**问题**：设计文档覆盖了架构和模块设计，但没有"从零到运行"的完整部署步骤。

**修复**：在方案中增加部署章节：

```bash
# 1. 安装
git clone <repo> && cd Maestro
pip install -e .

# 2. 配置
mkdir -p ~/.maestro
cp config.example.yaml ~/.maestro/config.yaml
# 编辑 ~/.maestro/config.yaml：
#   - 填入 manager.api_key（DeepSeek/OpenAI）
#   - 填入 telegram.bot_token（从 @BotFather 获取）
#   - 填入 telegram.chat_id（从 @userinfobot 获取）

# 3. 本地测试（不启动 Daemon）
maestro run "创建一个 hello world 的 Python 脚本"

# 4. 启动 Telegram Daemon
maestro daemon start

# 5. 远程使用
# 在 Telegram 中发送：/run /home/user/myproject 帮我实现登录模块
# SSH 查看：zellij attach maestro-<task_id>
```

---

## 三、核心需求对照 Review（二审）

针对 4 项核心需求逐一评估，发现 5 个新缺陷。

### 3.1 【需求 1】SSH CLI + Telegram 发送需求

> 我可以通过直接 SSH 登陆 VPS 通过命令，或者通过 Telegram Bot 发送消息给 agent 发送我的需求。

**评估**：基本覆盖（CLI `maestro run` + Telegram `/run`），但有 1 个问题。

**缺陷 A：`maestro run` 默认是阻塞式的**

当前设计中 Telegram `/run` 走 Daemon → 后台启动 worker，用户可以立刻发下一个 `/run`。但 CLI `maestro run` 的行为没有明确定义。如果像现有代码一样同步阻塞到任务完成，用户在 SSH 中就无法一次启动多个任务——必须开多个终端。

**修复**：`maestro run` 默认走后台模式（创建 task → 启动 worker → 打印 task_id → 立刻返回），`--foreground` 同步运行（调试用）：

```python
# cli.py
run_parser.add_argument("--foreground", "-f", action="store_true",
                        help="前台同步运行（调试用，默认后台）")

def _handle_run(args):
    task_id = generate_task_id()
    registry.create_task(task_id, args.requirement, args.working_dir)

    if args.foreground:
        # 同步模式：直接在当前进程运行 Orchestrator
        orchestrator = Orchestrator(config, task_id=task_id)
        orchestrator.run(args.requirement)
    else:
        # 后台模式：在 Zellij session 中启动 worker
        _launch_worker_background(task_id, args.working_dir, args.requirement)
        print(f"✅ 任务 [{task_id}] 已启动")
        print(f"   查看进度: maestro status {task_id}")
        print(f"   实时观看: zellij attach maestro-{task_id}")
```

### 3.2 【需求 2】自动调用 Claude Code 或 Gemini CLI 等工具

> agent 自动调用 claude code 或者 gemini cli 之类的命令行 vibe coding 工具进行代码编写。

**评估：重大缺陷——设计硬编码了 Claude Code**

整个 `claude_runner.py` 完全耦合到 Claude Code 的特有接口：

- `claude -p --output-format json` 命令格式
- JSON 输出解析（`session_id`、`cost_usd`、`subtype`）
- `--resume <session_id>` 会话恢复
- `--dangerously-skip-permissions` 权限跳过

如果要用 Gemini CLI、Aider 或其他工具，整个 Runner 不可复用。

**修复**：将 `claude_runner.py` 改为 `tool_runner.py`，通过配置支持两种模式：

```python
@dataclass
class CodingToolConfig:
    """编码工具配置"""
    type: str = "claude"          # claude | generic
    command: str = "claude"       # 可执行命令
    extra_args: list = field(default_factory=list)  # 额外命令行参数
    auto_approve: bool = True     # Claude 专用：跳过权限确认
    timeout: int = 600            # 单轮超时（秒）

@dataclass
class RunResult:
    """单轮执行结果"""
    output: str                   # 工具输出文本
    session_id: str = ""          # 会话 ID（仅 Claude 有）
    cost_usd: float = 0.0        # 本轮费用（仅 Claude 有）
    duration_ms: int = 0          # 本轮耗时
    is_error: bool = False        # 是否出错
    error_type: str = ""          # 错误类型

class ToolRunner:
    """
    编码工具运行器。
    type=claude 时使用 Claude Code 的 JSON 模式（精确解析费用/会话）。
    type=generic 时作为通用 subprocess 包装（适配任何 CLI 工具）。
    """

    def __init__(self, config: CodingToolConfig, working_dir: str):
        self.config = config
        self.working_dir = working_dir
        self.session_id: Optional[str] = None

    def run(self, instruction: str) -> RunResult:
        if self.config.type == "claude":
            return self._run_claude(instruction)
        else:
            return self._run_generic(instruction)

    def _run_claude(self, instruction: str) -> RunResult:
        """Claude Code 专用：-p --output-format json，解析 JSON 输出"""
        cmd = [self.config.command, "-p", "--output-format", "json"]
        if self.config.auto_approve:
            cmd.append("--dangerously-skip-permissions")
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        cmd.append(instruction)

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=self.config.timeout, cwd=self.working_dir
        )
        duration_ms = int((time.time() - start) * 1000)

        # 解析 Claude 的 JSON 输出
        try:
            data = json.loads(result.stdout)
            self.session_id = data.get("session_id", self.session_id)
            return RunResult(
                output=data.get("result", ""),
                session_id=data.get("session_id", ""),
                cost_usd=data.get("cost_usd", 0.0),
                duration_ms=duration_ms,
                is_error=data.get("is_error", False),
                error_type=data.get("subtype", ""),
            )
        except json.JSONDecodeError:
            # JSON 解析失败，降级为纯文本
            return RunResult(
                output=result.stdout + result.stderr,
                duration_ms=duration_ms,
                is_error=result.returncode != 0,
            )

    def _run_generic(self, instruction: str) -> RunResult:
        """通用模式：直接运行命令，捕获 stdout"""
        cmd = [self.config.command] + self.config.extra_args + [instruction]

        start = time.time()
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=self.config.timeout, cwd=self.working_dir
        )
        duration_ms = int((time.time() - start) * 1000)

        return RunResult(
            output=result.stdout + result.stderr,
            duration_ms=duration_ms,
            is_error=result.returncode != 0,
        )

    def resume_session(self, session_id: str):
        """恢复会话（仅 Claude 模式有效）"""
        if self.config.type == "claude":
            self.session_id = session_id
```

配置示例：

```yaml
# 使用 Claude Code（默认）
coding_tool:
  type: claude
  command: claude
  auto_approve: true
  timeout: 600

# 使用 Gemini CLI
coding_tool:
  type: generic
  command: gemini
  extra_args: ["--message"]
  timeout: 600

# 使用 Aider
coding_tool:
  type: generic
  command: aider
  extra_args: ["--message"]
  timeout: 600
```

注意：generic 模式下没有会话恢复、没有费用追踪。这是合理取舍——这些是 Claude Code 独有的能力，其他工具要支持需要各自适配，但 Manager Agent 的核心循环不受影响（它只看输出文本做决策）。

### 3.3 【需求 3】并行多任务

> 我可以一次给多个需求，agent 可以并行开多个 zellij session，同时管理。

**评估**：架构层面覆盖，有 1 个配置缺失。

**缺陷 C：缺少 `max_parallel_tasks` 并发限制**

02-design.md 提到了 `max_parallel_tasks` 配置项，但 03-review.md 简化时未明确保留。VPS 资源有限（通常 2-4GB 内存），每个任务消耗：

- 1 个 Python 进程（Orchestrator）~50MB
- 1 个 Claude subprocess ~100-200MB
- 1 个 Zellij session ~10MB

3-5 个并发任务就可能接近上限。

**修复**：在配置中保留 `max_parallel_tasks`，在 Daemon 和 CLI 启动新任务时检查：

```python
# registry.py
def can_start_new_task(self) -> tuple[bool, str]:
    active = len([t for t in self.tasks.values() if t["status"] in ("executing", "waiting_user")])
    if active >= self.config.max_parallel_tasks:
        return False, f"已达并发上限 {self.config.max_parallel_tasks}，当前 {active} 个任务运行中"
    return True, ""
```

配置：

```yaml
safety:
  max_consecutive_similar: 3
  max_parallel_tasks: 3          # 最大并行任务数（VPS 2GB 建议 2-3）
```

### 3.4 【需求 4】随时与 Agent 交互

> 我可以随时通过命令或 TG 消息与 agent 进行讨论、发送反馈、查看进展、停止任务等操作。

**评估：最多问题，有 3 个缺陷。**

#### 缺陷 D：用户反馈路由到了错误位置

当前主循环设计（02-design.md 第十六节）：

```
步骤 (a): 读 inbox → 把用户消息追加到 instruction
步骤 (b): 执行 Claude Code（instruction 包含用户消息）
步骤 (f): Manager 分析 Claude 输出 → 决策
```

问题：用户反馈**绕过了 Manager**，直接拼接到给 Claude Code 的指令里。Manager 不知道用户说了什么。

场景示例：当前指令是 "请运行 pytest tests/"，用户发来 "先不要跑测试了，改用 jest"。按当前设计，拼成的指令是：

```
请运行 pytest tests/

[用户补充]: 先不要跑测试了，改用 jest
```

这对 Claude Code 来说是矛盾的。正确做法是让 Manager 看到反馈后重新决策。

**修复**：将 inbox 消费移到 Manager 决策步骤，而非 Claude 执行步骤：

```python
def _main_loop(self, start_turn: int, first_instruction: str):
    instruction = first_instruction

    for turn in range(start_turn, self.config.manager.max_turns + 1):
        # (a) 检查 abort
        if self._check_abort():
            self._update_state("aborted")
            return

        # (b) 执行编码工具（用当前指令，不混入用户消息）
        result = self.runner.run(instruction)

        # (c) 熔断检查
        breaker_reason = self.breaker.check(instruction, result.cost_usd)
        if breaker_reason:
            self._handle_breaker(breaker_reason)
            return

        # (d) 更新状态
        self._update_state("executing", current_turn=turn, ...)

        # (e) 通知
        self._push_turn_update(turn, result)

        # (f) 读取 inbox（在 Manager 决策前，而非 Claude 执行前）
        user_messages = self._read_and_clear_inbox()

        # (g) Manager 决策：同时看到 Claude 输出 + 用户反馈
        truncated_output = self.context_mgr.truncate_output(result.output)
        manager_input = truncated_output
        if user_messages:
            feedback = "\n".join(msg.split("|", 2)[2] for msg in user_messages)
            manager_input += f"\n\n[用户实时反馈]: {feedback}"

        decision = self.manager.decide(manager_input)
        parsed = self.manager.parse_response(decision)

        # (h) 路由 action
        # ... 与原设计相同

        # (i) 保存 checkpoint
        self._save_checkpoint()
```

关键变化：**用户反馈交给 Manager 决策，Manager 决定如何调整后续指令**，而非盲目拼到 Claude Code 的输入中。

#### 缺陷 E：缺少"与 Agent 对话讨论"的能力

设计中 `/ask <id> <消息>` 只是往 inbox.txt 写一行消息，等下一轮被 Orchestrator 消费。用户**不会收到任何直接回复**。

用户发 "当前进展如何？你打算怎么做？" → 消息写入 inbox → 下一轮被 Manager 看到 → Manager 输出一条给 Claude Code 的指令 → 用户看不到 Manager 的思考，只看到 Telegram 推送的简短 turn 通知。

这不是"讨论"，这是单向指令。用户需要的是**双向对话**：问 Agent 问题，Agent 直接回答。

**修复**：新增 `/chat <id> <消息>` 命令和 `maestro chat <id> "消息"` CLI 命令。

```
/chat <id> <消息>    ← 与任务的 Manager Agent 直接对话，立即返回回复
/ask <id> <消息>     ← 给任务注入反馈，影响下一轮决策（不返回回复）
```

实现方式：`/chat` 由 Daemon 直接处理，不经过 Orchestrator。Daemon 用当前任务的上下文调用 Manager LLM 做一次独立问答：

```python
# telegram_bot.py
async def _on_chat(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 /chat 命令：与 Manager 直接对话"""
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法: /chat <task_id> <消息>")
        return

    task_id = args[0]
    user_message = " ".join(args[1:])

    # 1. 读取任务当前状态
    state = self._read_state(task_id)
    if not state:
        await update.message.reply_text(f"任务 {task_id} 不存在")
        return

    # 2. 构建上下文
    context_summary = (
        f"当前任务: {state['requirement']}\n"
        f"状态: {state['status']}, 第 {state['current_turn']}/{state['max_turns']} 轮\n"
        f"费用: ${state['total_cost_usd']:.2f}\n"
        f"最近 Manager 决策: {state['last_manager_action']}\n"
        f"Manager 思路: {state['last_manager_reasoning']}\n"
    )

    # 3. 读取最近的 Claude 输出摘要（从日志中取最后 N 行）
    last_output = self._read_last_output(task_id, max_lines=30)
    if last_output:
        context_summary += f"\n最近 Claude 输出摘要:\n{last_output}\n"

    # 4. 调用 Manager LLM 做独立问答（不影响任务循环）
    messages = [
        {"role": "system", "content": (
            "你是一个正在执行编码任务的 AI 助手。"
            "用户正在向你询问任务的进展。请根据上下文直接回答用户的问题。"
            "回复用自然语言，不需要 JSON 格式。简洁明了。"
        )},
        {"role": "user", "content": f"[任务上下文]\n{context_summary}\n\n[用户提问]\n{user_message}"}
    ]

    reply = self._call_llm(messages)  # Daemon 直接调用 LLM
    await update.message.reply_text(f"🤖 [{task_id}]\n\n{reply}")
```

核心要点：
- `/chat` 是**同步问答**，立即返回 Manager 的回复
- 不经过 Orchestrator 主循环，不消耗轮次
- 用 state.json + 日志文件的内容构建上下文
- Daemon 需要有 LLM 调用能力（复用 `manager` 的配置）

#### 缺陷 F：`/status` 信息深度不足

当前 `/status` 返回 state.json 中的字段：turn 数、费用、最后一个 action。但用户想知道：
- Agent 当前在做什么具体事？（最后的 Manager 指令）
- Claude 最近输出了什么？（最后输出摘要）
- Manager 为什么做这个决定？（reasoning）

state.json 里 `last_manager_reasoning` 只有一行，且没有最后的 Claude 输出摘要和 Manager 下发的指令。

**修复**：state.json 增加 3 个字段，让 `/status` 能展示更丰富的上下文：

```json
{
    "...": "（现有字段不变）",
    "last_instruction": "请运行 pytest tests/ -v 验证修改",
    "last_output_summary": "测试通过 12/12，无报错，覆盖率 85%",
    "last_manager_reasoning": "所有测试通过，代码质量良好，准备收尾"
}
```

Orchestrator 每轮更新 state.json 时写入这三个字段：

```python
# orchestrator.py _update_state 中增加
"last_instruction": instruction[:200],          # 截取前 200 字符
"last_output_summary": result.output[-500:],    # 截取最后 500 字符（尾部最有价值）
"last_manager_reasoning": parsed.get("reasoning", ""),
```

Telegram `/status` 展示格式升级：

```
📊 [abc123] 帮我实现登录模块

状态: 🔄 执行中
进度: Turn 5/30 | 💰 $0.82 | ⏱️ 3m12s
目录: /home/user/project-a

📤 上一轮指令:
  请运行 pytest tests/ -v 验证修改

📥 Claude 最近输出:
  测试通过 12/12，无报错，覆盖率 85%

🧠 Manager 思路:
  所有测试通过，代码质量良好，准备收尾
```

CLI `maestro status <id>` 输出同样格式。

---

## 四、补充确认

### 4.1 Manager Agent LLM 可配置性（确认）

Manager Agent 使用的大模型**已在设计中完全支持按需配置**。配置路径：`manager.provider` + `manager.model` + `manager.api_key` + `manager.base_url`。

支持的 provider：

| provider | 说明 | 是否需要 base_url |
|----------|------|-------------------|
| `deepseek` | 性价比最高，推荐 | 自动设 `https://api.deepseek.com` |
| `openai` | GPT-4o / GPT-4o-mini | 无需（默认 OpenAI 官方） |
| `anthropic` | Claude API（使用原生 SDK） | 无需 |
| `gemini` | Google Gemini | 自动设 Gemini OpenAI 兼容端点 |
| `ollama` | 本地模型，完全免费 | 自动设 `http://localhost:11434/v1` |
| `azure` | Azure OpenAI | 需要用户填写 |
| 自定义 | 任何 OpenAI 协议兼容服务 | 用户填写 `base_url` |

运行时覆盖（不改配置文件）：

```bash
maestro run --provider ollama --model qwen2.5:14b "你的需求"
```

实现要点：沿用现有 `meta_agent.py` 的 `_get_openai_compatible_client()` 工厂模式——根据 provider 自动设置 base_url，用户只需填 provider + model + api_key，不需要关心底层 SDK 差异。Anthropic 走原生 SDK，其余全部走 OpenAI 兼容协议。

### 4.2 编码工具可配置性（确认 + 补充 Codex）

编码工具**已在 3.2 节设计了 `tool_runner.py` 的 claude/generic 双模式**。此处补充 Codex CLI 的配置示例：

```yaml
# Claude Code（默认）
coding_tool:
  type: claude
  command: claude
  auto_approve: true
  timeout: 600

# Gemini CLI
coding_tool:
  type: generic
  command: gemini
  extra_args: ["--message"]
  timeout: 600

# OpenAI Codex CLI
coding_tool:
  type: generic
  command: codex
  extra_args: ["--message"]
  timeout: 600

# Aider
coding_tool:
  type: generic
  command: aider
  extra_args: ["--message"]
  timeout: 600

# 任何 CLI 编码工具（只要接受文本指令、输出文本结果）
coding_tool:
  type: generic
  command: /path/to/any-tool
  extra_args: ["--flag1", "--flag2"]
  timeout: 600
```

`generic` 模式的约定：`command` + `extra_args` + `instruction`（指令作为最后一个参数）拼成完整命令。工具的 stdout+stderr 作为输出传给 Manager Agent 分析。

与 `claude` 模式的差异：

| 能力 | claude 模式 | generic 模式 |
|------|------------|-------------|
| 费用追踪 | 精确（JSON 的 `cost_usd`） | 不支持（记为 0） |
| 会话恢复 | 支持（`--resume session_id`） | 不支持（每轮独立） |
| 输出解析 | 结构化 JSON | 纯文本 |
| 错误检测 | 精确（`is_error` + `subtype`） | 仅 exit code |

这是合理取舍——generic 模式牺牲精确信息换取通用性，Manager Agent 的核心决策循环（看输出 → 生成指令）不受影响。

### 4.3 从现有代码中提取的可复用模式

现有 6 个 Python 文件虽然是旧架构（pexpect 交互式），但有 5 个设计模式值得在新代码中保留：

| 模式 | 来源 | 说明 | 新代码中如何复用 |
|------|------|------|-----------------|
| **环境变量递归替换** | `config.py` `_expand_env_vars()` + `_process_config()` | 递归遍历 dict/list/str，替换 `${VAR}` 语法 | 直接搬到新 `config.py`，逻辑不变 |
| **Provider 工厂** | `meta_agent.py` `_get_openai_compatible_client()` | 根据 provider 自动设置 base_url（deepseek/ollama/gemini），用户免填 | 搬到新 `manager_agent.py`，增加重试和费用估算 |
| **对话历史管理** | `meta_agent.py` `start_task()` + `decide()` | 将需求/输出/决策维护为 messages 列表，传给 LLM | 搬到新 `manager_agent.py`，增加 JSON 解析和 action 路由 |
| **日志 callback 解耦** | `orchestrator.py` `on_meta_log`/`on_claude_output` | 用 callback 函数把日志输出从核心逻辑中解耦 | 新 `orchestrator.py` 用 `_log_event()` + `_telegram_push()` 同理 |
| **KDL 布局动态生成** | `zellij_session.py` `_create_layout_file()` | tempfile 生成 Zellij KDL 布局，启动后清理 | 搬到新 `session.py`，适配多任务 session 命名 |

---

## 五、简化后的最终模块结构

```
src/maestro/
├── __init__.py
├── cli.py                 # CLI 入口（run/list/status/ask/chat/abort/resume/daemon/_worker）
├── config.py              # 配置加载（dataclass 建模 + 环境变量展开）
├── orchestrator.py        # 调度核心（主循环 + inbox + 通知 + 报告）
├── tool_runner.py         # 编码工具运行器（Claude/Gemini/Aider 等，见 3.2 节）
├── manager_agent.py       # Manager 决策 + LLM 调用 + 费用估算（含多 provider）
├── state.py               # 状态机（6 态）+ 熔断器 + atomic_write_json 工具
├── context.py             # 上下文压缩（滑动窗口）+ 输出截断（1/3 头 + 2/3 尾）
├── session.py             # Zellij 管理（布局生成 + 自动安装 + fallback）
├── telegram_bot.py        # Telegram Bot + Daemon（asyncio，含 /chat LLM 调用）
└── registry.py            # 多任务注册表（CRUD + 文件锁 + 并发数检查）
```

**10 个模块**（相比原方案 14 个砍掉 4 个：`llm_client.py`、`notifier.py`、`inbox.py`、`reporter.py`）。

关键变更（相比一审）：

| 变更 | 说明 |
|------|------|
| `claude_runner.py` → `tool_runner.py` | 支持 Claude Code + 通用 CLI 工具（Gemini、Aider 等） |
| `telegram_bot.py` 增加 `/chat` | Daemon 直接调用 LLM 做问答，不经过 Orchestrator |
| `registry.py` 增加并发数检查 | `can_start_new_task()` 检查是否超过 `max_parallel_tasks` |

砍掉的模块职责归属：

| 砍掉的模块 | 原职责 | 归入 |
|------------|--------|------|
| `llm_client.py` | LLM 调用封装、重试、费用估算 | `manager_agent.py` 内部方法 |
| `notifier.py` | 通知抽象层 | `orchestrator.py` 的 `_log_event()` + `_telegram_push()` |
| `inbox.py` | inbox.txt 读写协议 | `orchestrator.py` 的模块级工具函数 |
| `reporter.py` | 报告生成 | `orchestrator.py` 的 `_generate_report()` 方法 |

---

## 五、简化后的完整配置文件

```yaml
# ~/.maestro/config.yaml

manager:
  provider: deepseek           # openai | anthropic | deepseek | gemini | ollama | azure
  model: deepseek-chat
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com
  max_turns: 30
  max_budget_usd: 5.0
  request_timeout: 60
  retry_count: 3
  system_prompt: |
    （见 2.7 节完整 prompt）

# 编码工具配置（支持 Claude Code / Gemini CLI / Aider 等）
coding_tool:
  type: claude                 # claude | generic
  command: claude              # 可执行命令名或完整路径
  extra_args: []               # generic 模式的额外参数（如 ["--message"]）
  auto_approve: true           # Claude 专用：--dangerously-skip-permissions
  timeout: 600                 # 单轮 subprocess 超时（秒）

  # 切换到 Gemini CLI 时：
  # type: generic
  # command: gemini
  # extra_args: ["--message"]

context:
  max_recent_turns: 5          # 传给 Manager 的最近轮数
  max_result_chars: 3000       # 工具输出截断长度

safety:
  max_consecutive_similar: 3   # 死循环检测阈值
  max_parallel_tasks: 3        # 最大并行任务数（VPS 2GB 建议 2-3）

telegram:
  enabled: true
  bot_token: ${TELEGRAM_BOT_TOKEN}
  chat_id: ${TELEGRAM_CHAT_ID}
  push_every_turn: true
  ask_user_timeout: 3600       # ASK_USER 等待超时（秒）

zellij:
  enabled: true
  auto_install: true

logging:
  dir: ~/.maestro/logs
  level: INFO
  max_days: 30                 # 日志保留天数
```

相比原设计的变更：

**新增**：
- `coding_tool.type` — 支持 `claude`（JSON 模式）和 `generic`（通用 subprocess）
- `coding_tool.extra_args` — generic 模式的额外命令行参数
- `safety.max_parallel_tasks` — 并行任务数上限

**重命名**：
- `claude_code` 配置段 → `coding_tool`

**砍掉**：
- `telegram.allowed_chat_ids` → 简化为单个 `chat_id`
- `telegram.admin_chat_id`、`telegram.rate_limit_per_minute` → 砍掉
- `safety.budget_action` → 砍掉（永远 ask_user）
- `logging.retention.*` → 简化为单个 `max_days`
- `zellij.layout` → 砍掉（只有一种布局）

---

## 六、简化后的 state.json 完整结构

```json
{
    "task_id": "abc12345",
    "status": "executing",
    "requirement": "帮我实现登录模块",
    "working_dir": "/home/user/project-a",
    "worker_pid": 12345,
    "coding_tool_type": "claude",
    "current_turn": 5,
    "max_turns": 30,
    "total_cost_usd": 0.82,
    "max_budget_usd": 5.0,
    "tool_session_id": "sess-xxx-yyy",
    "created_at": "2026-02-23T11:30:00",
    "updated_at": "2026-02-23T11:33:45",
    "started_at": "2026-02-23T11:30:02",
    "last_turn_duration_ms": 12345,
    "last_instruction": "请运行 pytest tests/ -v 验证修改",
    "last_output_summary": "测试通过 12/12，无报错，覆盖率 85%",
    "last_manager_action": "execute",
    "last_manager_reasoning": "所有测试通过，代码质量良好，准备收尾",
    "error_message": "",
    "zellij_session": "maestro-abc12345",
    "breaker": {
        "consecutive_similar": 0,
        "last_instruction_hash": ""
    }
}
```

相比 02-design.md 的变更：
- 新增 `worker_pid`（进程健康监控，见 2.1 节）
- 新增 `coding_tool_type`（标识使用的编码工具，见 3.2 节）
- 新增 `last_instruction`（上一轮发给编码工具的指令，见 3.4 缺陷 F）
- 新增 `last_output_summary`（上一轮工具输出摘要，见 3.4 缺陷 F）
- `claude_session_id` → `tool_session_id`（通用化命名）

---

## 七、完整交互命令对照表

整合所有交互方式（CLI + Telegram），含二审新增的 `/chat`：

| 操作 | CLI 命令 | Telegram 命令 | 说明 |
|------|---------|---------------|------|
| 启动任务 | `maestro run "需求"` | `/run <dir> <需求>` | 默认后台运行，CLI 加 `--foreground` 可前台 |
| 查看任务列表 | `maestro list` | `/list` | 显示所有任务 + 状态 |
| 查看任务详情 | `maestro status <id>` | `/status <id>` | 含 Manager 思路、最近输出摘要 |
| 发送反馈 | `maestro ask <id> "消息"` | `/ask <id> <消息>` | 注入 inbox，下一轮 Manager 会看到 |
| 与 Agent 对话 | `maestro chat <id> "问题"` | `/chat <id> <问题>` | 直接问答，立即返回回复，不影响任务 |
| 终止任务 | `maestro abort <id>` | `/abort <id>` | 信号文件触发优雅停止 |
| 恢复任务 | `maestro resume <id>` | — | 崩溃恢复 |
| 查看报告 | `maestro report <id>` | `/report <id>` | 任务完成后的 Markdown 报告 |
| 实时观看 | `zellij attach maestro-<id>` | — | 多面板 UI |
| 守护进程管理 | `maestro daemon start/stop/status` | — | Telegram Daemon 管理 |
| 直接回复 | — | 回复通知消息 | 自动关联到对应 task 的 inbox |

`/ask` vs `/chat` 的区别：

| | `/ask` | `/chat` |
|-|--------|---------|
| 响应方式 | 无直接回复，影响下一轮 | 立即返回 Manager 的回答 |
| 是否消耗轮次 | 否（注入 inbox） | 否（独立 LLM 调用） |
| 是否影响任务执行 | 是（Manager 下一轮会看到） | 否（只读查询） |
| 用途 | 发送指令、反馈、修正方向 | 询问进展、讨论策略、了解状态 |

---

## 八、调整后的分阶段实施计划

### Phase 1：核心闭环（单任务 + CLI + 基础 Telegram）

**开发顺序**（有依赖关系，必须按序）：

```
 1. config.py           ← 基础设施，所有模块依赖（含 CodingToolConfig）
 2. state.py            ← 状态枚举 + 熔断器 + atomic_write_json
 3. context.py          ← 上下文压缩/截断
 4. tool_runner.py      ← 编码工具运行器（claude 模式 + generic 模式）
 5. manager_agent.py    ← Manager 决策 + LLM 调用 + 费用估算
 6. orchestrator.py     ← 调度核心（修正后的 inbox 路由 + 通知 + 报告）
 7. session.py          ← Zellij 管理 + 自动安装
 8. registry.py         ← 任务注册表 + 并发数检查
 9. cli.py              ← CLI 入口（run [--foreground] / status / daemon / _worker）
10. telegram_bot.py     ← Telegram Daemon（/run / /status / 进度推送）
```

**验证标准**：

- [ ] `pip install -e .` 安装成功
- [ ] `maestro run "需求"` 后台启动任务，打印 task_id 后立刻返回
- [ ] `maestro run --foreground "需求"` 前台同步运行
- [ ] Manager 自动驱动 Claude Code 完成任务
- [ ] 任务完成后输出 DONE 并退出
- [ ] `maestro daemon start` 启动 Telegram Daemon
- [ ] Telegram `/run /path 需求` 启动任务，自动推送进度
- [ ] 任务完成后 Telegram 推送通知
- [ ] SSH 断开后任务不中断（Zellij 保活）
- [ ] Worker 崩溃后 Daemon 能检测到并通知
- [ ] 切换 `coding_tool.type: generic` 后可用 Gemini CLI 跑任务

### Phase 2：多任务 + 交互完善

**新增/完善**：

```
1. registry.py       ← 多任务 CRUD + 并发数限制
2. orchestrator.py   ← 修正后的 inbox 路由 + ASK_USER 等待 + abort 检测
3. cli.py            ← list / ask / chat / abort / resume / report
4. telegram_bot.py   ← /list / /ask / /chat / /abort / /report / 直接回复
5. orchestrator.py   ← _generate_report() 方法
```

**验证标准**：

- [ ] 同时运行 2 个任务，各自独立完成
- [ ] 超过 `max_parallel_tasks` 时拒绝启动并提示
- [ ] `/list` 正确显示所有任务状态
- [ ] `/ask <id> 消息` 注入反馈，Manager 下一轮据此调整决策
- [ ] `/chat <id> 问题` 立即返回 Manager 的回答
- [ ] `/status <id>` 显示 Manager 思路 + 最近输出摘要
- [ ] `/abort <id>` 能终止正在运行的任务
- [ ] `maestro resume <id>` 可恢复崩溃的任务
- [ ] `/report <id>` 生成完整的 Markdown 报告

### Phase 3：稳定性加固（按需）

```
1. 熔断器参数调优（运行实际任务后根据经验调整阈值）
2. 上下文压缩策略优化（如需要可加 LLM 摘要）
3. Daemon 自恢复（简单的 watchdog 脚本 或 cron job）
4. Telegram 安全增强（多用户白名单、rate limiting、审计日志）
5. 72 小时连续运行稳定性验证
```

---

## 九、Review 变更清单

汇总所有变更（一审 + 二审），便于实施时对照：

### 砍掉的（一审）

| # | 项目 | 原位置 |
|---|------|--------|
| 1 | `llm_client.py` 模块 | 02-design 第十二节 |
| 2 | `notifier.py` 模块（ABC + 3 实现类） | 02-design 第十一节 |
| 3 | `inbox.py` 模块 | 02-design 第四节 |
| 4 | `reporter.py` 模块 | 02-design 第十四节 |
| 5 | 多用户白名单 + rate limiting + 审计日志 | 02-design 第七节 |
| 6 | 三维度日志清理 | 02-design 第八节 |
| 7 | autopilot → maestro 迁移逻辑 | 02-design 第十节 |
| 8 | `budget_action` 配置项 | 02-design 第十七节 |

### 修复的（一审）

| # | 项目 | 严重程度 | 说明 |
|---|------|----------|------|
| 1 | Worker PID 健康监控 | 高 | state.json 增加 worker_pid，Daemon 检查进程存活 |
| 2 | state.json 原子写入 | 高 | 统一使用 tmp+rename |
| 3 | Daemon 进程模型 | 高 | nohup + PID 文件 |
| 4 | 优雅停止机制 | 高 | abort 信号文件 + 每轮检查 |
| 5 | Telegram 异步架构 | 中 | 全部 asyncio 协程 |
| 6 | `_wait_for_user_reply` 细节 | 中 | 轮询 5 秒 + 检查 abort |
| 7 | Manager system_prompt | 中 | 完整 prompt + 5 种 action 示例 |
| 8 | 首次部署流程 | 低 | clone → install → config → run |

### 修复的（二审 — 核心需求对照）

| # | 项目 | 严重程度 | 对应需求 | 说明 |
|---|------|----------|----------|------|
| A | `maestro run` 后台模式 | 高 | 需求 1+3 | 默认后台启动，`--foreground` 可选前台 |
| B | 编码工具通用化 | 高 | 需求 2 | `claude_runner.py` → `tool_runner.py`，支持 generic 模式 |
| C | 并行任务数限制 | 中 | 需求 3 | 新增 `max_parallel_tasks` + 启动时检查 |
| D | inbox 路由修正 | 高 | 需求 4 | 用户反馈交给 Manager 决策，不直接拼到工具指令 |
| E | `/chat` 对话能力 | 高 | 需求 4 | 新增 `/chat` 命令，Daemon 直接调用 LLM 做问答 |
| F | `/status` 信息增强 | 中 | 需求 4 | state.json 增加 last_instruction/last_output_summary |

---

## 十、结论

经过两轮 review（一审：简化 + 可行性修复；二审：核心需求对照），最终方案：

- **10 个模块**（从原方案 14 个精简而来）
- **砍掉 8 项过度设计**
- **修复 8 + 6 = 14 个问题**（一审 8 个可行性问题 + 二审 6 个需求缺陷）

核心架构：

| 组件 | 职责 |
|------|------|
| **Tool Runner** | 驱动编码工具（Claude Code / Gemini CLI / 通用 CLI） |
| **Manager Agent** | 可配置 LLM 分析输出、生成 JSON 决策指令 |
| **Orchestrator** | 主循环驱动、用户反馈路由到 Manager、文件 IPC |
| **Zellij** | 进程保活 + 可视化（可选） |
| **Telegram Bot** | 远程控制 + 通知推送 + `/chat` 直接对话 |
| **Registry** | 多任务管理 + 并发数控制 |

方案已达到可直接编码的完整度。4 项核心需求全部覆盖。
