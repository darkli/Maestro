# 系统设计方案（完善版）

本文档基于 `docs/design/implementation_plan.md`（终稿 v5），逐项补充其中的疏漏和模糊点，使方案达到可直接编码的完整度。

---

## 一、Claude Runner 交互协议（补充疏漏 1）

### 1.1 核心调用方式

方案确认使用 `claude -p --output-format json` 非交互模式。每轮对话为一次独立的 subprocess 调用：

```python
# 首轮（创建新会话）
result = subprocess.run(
    ["claude", "-p", "--output-format", "json", "--dangerously-skip-permissions", instruction],
    capture_output=True, text=True, timeout=600,
    cwd=working_dir
)
# 从 JSON 输出中提取 session_id
response = json.loads(result.stdout)
session_id = response["session_id"]

# 后续轮次（复用会话）
result = subprocess.run(
    ["claude", "-p", "--output-format", "json", "--resume", session_id,
     "--dangerously-skip-permissions", instruction],
    capture_output=True, text=True, timeout=600,
    cwd=working_dir
)
```

### 1.2 JSON 输出解析

`claude -p --output-format json` 的输出结构：

```json
{
  "type": "result",
  "subtype": "success",
  "cost_usd": 0.021,
  "is_error": false,
  "duration_ms": 12345,
  "duration_api_ms": 10234,
  "num_turns": 1,
  "result": "这里是 Claude 的回复文本...",
  "session_id": "abc123-def456-..."
}
```

关键字段映射：

| JSON 字段 | 用途 | 写入位置 |
|-----------|------|----------|
| `result` | Claude 的回复内容，传给 Manager 分析 | state.json `last_output` |
| `session_id` | 会话 ID，用于 `--resume` | state.json `claude_session_id` |
| `cost_usd` | 本轮费用 | state.json `total_cost`（累加）|
| `is_error` | 是否出错 | 触发错误处理流程 |
| `duration_ms` | 本轮耗时 | state.json `last_duration_ms` |
| `subtype` | `success` / `error_max_turns` 等 | 判断是否需要 Manager 介入 |

### 1.3 错误情况处理

| subtype 值 | 含义 | 处理方式 |
|------------|------|----------|
| `success` | 正常完成 | 输出交给 Manager 决策 |
| `error_max_turns` | Claude 内部轮数超限 | Manager 决定：继续（resume）或 DONE |
| `error_model` | 模型 API 错误 | 重试 1 次，仍失败则 ASK_USER |
| `error_authentication` | 鉴权失效 | 直接 ABORT + 通知用户 |

### 1.4 claude_runner.py 接口设计

```python
@dataclass
class RunResult:
    """单轮执行结果"""
    output: str           # Claude 回复文本
    session_id: str       # 会话 ID
    cost_usd: float       # 本轮费用
    duration_ms: int      # 本轮耗时
    is_error: bool        # 是否出错
    error_type: str = ""  # 错误类型

class ClaudeRunner:
    def __init__(self, config: ClaudeCodeConfig, working_dir: str):
        self.config = config
        self.working_dir = working_dir
        self.session_id: Optional[str] = None  # 首轮后自动设置

    def run(self, instruction: str) -> RunResult:
        """执行一轮指令，返回结果"""
        ...

    def resume_session(self, session_id: str):
        """恢复到指定会话（用于崩溃恢复）"""
        self.session_id = session_id
```

---

## 二、Manager Agent 输出协议（补充疏漏 2）

### 2.1 Action 完整枚举

```python
class ManagerAction(str, Enum):
    EXECUTE = "execute"       # 向 Claude Code 发送指令
    DONE = "done"             # 任务完成
    BLOCKED = "blocked"       # 遇到无法解决的阻塞
    ASK_USER = "ask_user"     # 需要用户决定
    RETRY = "retry"           # 重试上一条指令（如 Claude 出错）
```

### 2.2 Manager 回复 JSON 格式

```json
{
  "action": "execute",
  "instruction": "请运行测试: pytest tests/ -v",
  "reasoning": "代码修改已完成，需要验证测试是否通过"
}
```

```json
{
  "action": "ask_user",
  "instruction": "",
  "reasoning": "发现两套鉴权方案，无法自动决定",
  "question": "项目使用了 JWT 和 Cookie 两套鉴权方案，请问是否全部替换为 Session？"
}
```

```json
{
  "action": "done",
  "instruction": "",
  "reasoning": "代码编写完成，测试全部通过，无报错",
  "summary": "完成了登录模块的实现，包含 JWT 认证、用户注册、密码重置功能"
}
```

### 2.3 JSON 解析失败的 Fallback

```python
def _parse_manager_response(self, raw: str) -> dict:
    """解析 Manager 回复，支持 JSON 和纯文本 fallback"""
    # 尝试 1：直接 JSON 解析
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass

    # 尝试 2：从 markdown code block 中提取 JSON
    json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试 3：检测信号关键词（兼容纯文本模式）
    if "##DONE##" in raw:
        return {"action": "done", "instruction": "", "reasoning": raw}
    if "##BLOCKED##" in raw:
        return {"action": "blocked", "instruction": "", "reasoning": raw}

    # Fallback：视为 execute 指令
    return {"action": "execute", "instruction": raw, "reasoning": "（纯文本 fallback）"}
```

### 2.4 reasoning 字段用途

- **写入日志**：方便调试和审计
- **推送给 Telegram**：ASK_USER 和 DONE 时附在通知中
- **不传给 Claude Code**：仅供人类阅读
- **不计入上下文压缩**：减少 token 消耗

---

## 三、状态机设计（补充疏漏 3）

### 3.1 状态枚举与转换图

```
                ┌─────────┐
                │ PENDING │  ← 任务创建，等待启动
                └────┬────┘
                     │ start
                     ▼
                ┌──────────┐
           ┌───▶│EXECUTING │◀──┐
           │    └────┬─────┘   │
           │         │         │ user_reply / retry
           │         ▼         │
           │    ┌──────────┐   │
           │    │WAITING   │───┘
           │    │_USER     │
           │    └────┬─────┘
           │         │ timeout
           │         ▼
           │    ┌──────────┐
           │    │COMPLETED │  ← 正常完成（DONE）
           │    └──────────┘
           │
           │    ┌──────────┐
           ├───▶│ FAILED   │  ← 熔断/鉴权失效/超预算
           │    └──────────┘
           │
           │    ┌──────────┐
           └───▶│ ABORTED  │  ← 用户手动终止
                └──────────┘
```

合法状态转换：

```python
VALID_TRANSITIONS = {
    "pending":      ["executing"],
    "executing":    ["waiting_user", "completed", "failed", "aborted"],
    "waiting_user": ["executing", "failed", "aborted"],
    "completed":    [],  # 终态
    "failed":       ["pending"],  # resume 可回到 pending
    "aborted":      [],  # 终态
}
```

### 3.2 state.json 完整结构

```json
{
    "task_id": "abc12345",
    "status": "executing",
    "requirement": "帮我实现登录模块",
    "working_dir": "/home/user/project-a",
    "current_turn": 5,
    "max_turns": 30,
    "total_cost_usd": 0.82,
    "max_budget_usd": 5.0,
    "claude_session_id": "sess-xxx-yyy",
    "created_at": "2026-02-23T11:30:00",
    "updated_at": "2026-02-23T11:33:45",
    "started_at": "2026-02-23T11:30:02",
    "last_turn_duration_ms": 12345,
    "last_manager_action": "execute",
    "last_manager_reasoning": "代码修改完成，下一步跑测试",
    "error_message": "",
    "zellij_session": "maestro-abc12345",
    "modified_files": ["auth.py", "test_auth.py"],
    "breaker": {
        "consecutive_similar": 0,
        "last_instruction_hash": ""
    }
}
```

### 3.3 state.json 与 registry.json 的同步策略

- **state.json 为主（Source of Truth）**：每个任务的 `~/.maestro/sessions/<task_id>/state.json` 是该任务的权威状态
- **registry.json 为索引**：只存储 `task_id → {requirement, working_dir, status, created_at, zellij_session}` 的摘要
- **同步时机**：Orchestrator 每次更新 state.json 后，同步更新 registry.json 中对应条目的 status
- **冲突处理**：如果 registry.json 损坏，可从各 task 的 state.json 重建

### 3.4 熔断器详细设计

```python
@dataclass
class CircuitBreaker:
    """熔断器：检测死循环和资源超限"""
    max_consecutive_similar: int = 3  # 连续相似指令阈值
    max_turns: int = 30               # 最大轮数
    max_budget_usd: float = 5.0       # 最大预算

    # 运行时状态
    _instruction_hashes: list = field(default_factory=list)
    _total_cost: float = 0.0
    _current_turn: int = 0

    def check(self, instruction: str, cost: float) -> Optional[str]:
        """检查是否应该熔断，返回 None 表示正常，否则返回原因"""
        # 轮数检查
        self._current_turn += 1
        if self._current_turn > self.max_turns:
            return f"超过最大轮数 {self.max_turns}"

        # 费用检查
        self._total_cost += cost
        if self._total_cost > self.max_budget_usd:
            return f"费用超限: ${self._total_cost:.2f} > ${self.max_budget_usd}"

        # 死循环检查（指令 hash 重复）
        h = hashlib.md5(instruction.encode()).hexdigest()[:8]
        self._instruction_hashes.append(h)
        if len(self._instruction_hashes) >= self.max_consecutive_similar:
            recent = self._instruction_hashes[-self.max_consecutive_similar:]
            if len(set(recent)) == 1:
                return f"检测到死循环：连续 {self.max_consecutive_similar} 次相同指令"

        return None  # 正常
```

---

## 四、inbox.txt 通信协议（补充疏漏 4）

### 4.1 消息格式

每条消息一行，格式为 `时间戳|来源|消息内容`：

```
2026-02-23T11:35:00|telegram|别改数据库，用现有的表
2026-02-23T11:36:00|cli|优先处理登录功能
```

### 4.2 读写协议

- **写入**：追加模式（`a`），使用文件锁（`fcntl.flock`）防并发
- **读取**：Orchestrator 在每轮循环开始前读取 inbox.txt，读取后 **清空文件**（truncate）
- **原子操作**：

```python
import fcntl

def write_inbox(inbox_path: str, source: str, message: str):
    """线程/进程安全地写入 inbox"""
    timestamp = datetime.now().isoformat()
    line = f"{timestamp}|{source}|{message}\n"
    with open(inbox_path, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f, fcntl.LOCK_UN)

def read_and_clear_inbox(inbox_path: str) -> list[str]:
    """读取并清空 inbox，返回消息列表"""
    with open(inbox_path, "r+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        messages = f.readlines()
        f.truncate(0)
        f.seek(0)
        fcntl.flock(f, fcntl.LOCK_UN)
    return [m.strip() for m in messages if m.strip()]
```

### 4.3 Orchestrator 消息消费时机

在主循环的每轮开头（调用 Claude Code 之前）：

```python
# 主循环每轮
for turn in range(1, max_turns + 1):
    # 1. 检查 inbox（用户可能插入了指令）
    user_messages = read_and_clear_inbox(inbox_path)
    if user_messages:
        # 将用户消息附加到下一条指令中
        extra = "\n".join([f"[用户补充] {m.split('|', 2)[2]}" for m in user_messages])
        instruction = f"{instruction}\n\n{extra}"

    # 2. 执行 Claude Code
    result = runner.run(instruction)
    # ...
```

---

## 五、checkpoint 崩溃恢复（补充疏漏 5）

### 5.1 checkpoint.json 数据结构

```json
{
    "task_id": "abc12345",
    "saved_at": "2026-02-23T11:33:45",
    "current_turn": 5,
    "claude_session_id": "sess-xxx-yyy",
    "total_cost_usd": 0.82,
    "manager_conversation_history": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ],
    "last_instruction": "请运行测试",
    "breaker_state": {
        "instruction_hashes": ["a1b2c3d4", "e5f6g7h8"],
        "consecutive_similar": 0
    },
    "modified_files": ["auth.py", "test_auth.py"]
}
```

### 5.2 写入时机

每轮循环结束后（Claude Code 返回结果且 Manager 决策完成后）：

```python
def _save_checkpoint(self):
    """保存 checkpoint，用于崩溃恢复"""
    data = {
        "task_id": self.task_id,
        "saved_at": datetime.now().isoformat(),
        "current_turn": self.current_turn,
        "claude_session_id": self.runner.session_id,
        "total_cost_usd": self.breaker._total_cost,
        "manager_conversation_history": self.manager.conversation_history,
        "last_instruction": self.last_instruction,
        "breaker_state": self.breaker.to_dict(),
        "modified_files": self.state.modified_files,
    }
    # 原子写入（写入临时文件再 rename）
    tmp = self.checkpoint_path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp, self.checkpoint_path)
```

### 5.3 恢复流程

```python
def resume(self, task_id: str):
    """恢复崩溃的任务"""
    checkpoint = self._load_checkpoint(task_id)

    # 1. 恢复 ClaudeRunner 会话
    self.runner.resume_session(checkpoint["claude_session_id"])

    # 2. 恢复 Manager 对话历史
    self.manager.conversation_history = checkpoint["manager_conversation_history"]

    # 3. 恢复熔断器状态
    self.breaker.restore(checkpoint["breaker_state"])

    # 4. 恢复轮数和费用
    self.current_turn = checkpoint["current_turn"]

    # 5. 更新状态为 executing
    self._update_state("executing")

    # 6. 让 Manager 基于恢复上下文决定下一步
    instruction = self.manager.decide(
        f"[系统通知] 任务从第 {self.current_turn} 轮崩溃恢复。"
        f"上一条指令是：{checkpoint['last_instruction']}。"
        f"请决定下一步操作。"
    )

    # 7. 继续主循环
    self._main_loop(start_turn=self.current_turn + 1, first_instruction=instruction)
```

### 5.4 Zellij Session 恢复

Zellij Session 在 Python 崩溃后通常仍然存活（因为 Session 内运行的是 tail -f 等独立进程）。恢复时：

- 检查 `zellij list-sessions` 是否包含 `maestro-<task_id>`
- 如果存在：直接复用，无需重建布局
- 如果不存在：创建新 Session

---

## 六、费用追踪机制（补充疏漏 6）

### 6.1 费用来源

| 来源 | 获取方式 | 精度 |
|------|----------|------|
| Claude Code 调用 | JSON 输出的 `cost_usd` 字段 | 精确（API 返回）|
| Manager Agent 调用 | 根据 input/output token 数和模型定价估算 | 估算 |

### 6.2 Manager 费用估算

```python
# 各 provider 的 token 定价（USD per 1K tokens）
MODEL_PRICING = {
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4o": {"input": 0.0025, "output": 0.01},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    # ollama 本地模型：0
}

def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = MODEL_PRICING.get(model, {"input": 0, "output": 0})
    return (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000
```

### 6.3 费用数据存储

费用累计写入 state.json 的 `total_cost_usd` 字段，分项明细写入日志：

```
[11:33:45] [COST] Turn 5: Claude $0.021 + Manager $0.003 = $0.024 (累计: $0.82)
```

### 6.4 预算熔断逻辑

```python
if total_cost > max_budget_usd:
    # 不是立即 ABORT，而是通知用户确认
    action = "ask_user"
    question = f"费用已达 ${total_cost:.2f}（预算 ${max_budget_usd}），是否继续？"
    # 如果 ASK_USER 超时无回复，则自动 ABORT
```

---

## 七、Telegram Bot 安全加固（补充疏漏 7）

### 7.1 授权模型

```python
class AuthConfig:
    """Telegram 授权配置"""
    allowed_chat_ids: list[int]   # 允许的 chat_id 列表（支持多用户）
    admin_chat_id: int            # 管理员 chat_id（接收系统通知）
```

### 7.2 安全措施

| 措施 | 实现方式 |
|------|----------|
| 用户鉴权 | 每条消息检查 `chat_id` 是否在白名单 |
| 目录白名单 | `/run` 的 working_dir 必须在 `allowed_dirs` 配置列表中，或至少在 `$HOME` 下 |
| 命令注入防护 | working_dir 使用 `os.path.realpath()` 解析后检查，禁止 `..`、符号链接逃逸 |
| Rate Limiting | 每用户每分钟最多 10 条命令 |
| 审计日志 | 所有 Telegram 命令记录到 `~/.maestro/logs/telegram-audit.log` |

### 7.3 目录安全检查

```python
def _validate_working_dir(self, path: str) -> tuple[bool, str]:
    """验证工作目录是否安全"""
    real_path = os.path.realpath(os.path.expanduser(path))

    # 检查是否存在
    if not os.path.isdir(real_path):
        return False, f"目录不存在: {real_path}"

    # 检查是否在允许的范围内
    home = os.path.expanduser("~")
    if not real_path.startswith(home):
        return False, f"目录必须在 $HOME 下: {real_path}"

    # 检查是否在黑名单中
    blacklist = [".ssh", ".gnupg", ".maestro"]
    for b in blacklist:
        if f"/{b}" in real_path:
            return False, f"禁止访问敏感目录: {b}"

    return True, real_path
```

---

## 八、日志管理策略（补充疏漏 8）

### 8.1 日志目录结构

```
~/.maestro/
├── logs/
│   ├── maestro.log              # 主进程日志（daemon + 系统级）
│   ├── telegram-audit.log       # Telegram 命令审计日志
│   └── tasks/
│       ├── abc12345/
│       │   ├── orchestrator.log # 该任务的调度日志
│       │   ├── manager.log      # Manager 决策日志
│       │   └── claude.log       # Claude Code 输出日志
│       └── def67890/
│           └── ...
├── sessions/                    # 任务运行时状态（已在方案中定义）
│   └── ...
└── config.yaml                  # 全局配置
```

### 8.2 日志保留策略

```yaml
logging:
  dir: ~/.maestro/logs
  level: INFO
  retention:
    max_task_logs: 50       # 最多保留 50 个任务的日志
    max_days: 30            # 超过 30 天自动清理
    max_total_size_mb: 500  # 总大小上限
```

### 8.3 清理逻辑

```python
def cleanup_old_logs(log_dir: str, config: LogRetentionConfig):
    """清理过期日志"""
    tasks_dir = Path(log_dir) / "tasks"
    if not tasks_dir.exists():
        return

    task_dirs = sorted(tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime)

    # 按数量清理
    while len(task_dirs) > config.max_task_logs:
        oldest = task_dirs.pop(0)
        shutil.rmtree(oldest)

    # 按时间清理
    cutoff = time.time() - config.max_days * 86400
    for d in task_dirs:
        if d.stat().st_mtime < cutoff:
            shutil.rmtree(d)
```

在 Daemon 启动时和每天凌晨各执行一次清理。

---

## 九、Zellij 自动安装（补充疏漏 9）

### 9.1 安装逻辑

```python
def ensure_zellij_installed() -> str:
    """确保 Zellij 已安装，返回可执行文件路径"""
    # 1. 检查 PATH 中是否已有
    zellij_path = shutil.which("zellij")
    if zellij_path:
        return zellij_path

    # 2. 检查 ~/.local/bin/
    local_path = Path.home() / ".local" / "bin" / "zellij"
    if local_path.exists() and os.access(local_path, os.X_OK):
        return str(local_path)

    # 3. 自动安装
    return _install_zellij()

def _install_zellij() -> str:
    """下载安装预编译 Zellij 二进制"""
    import platform

    arch = platform.machine()  # x86_64 / aarch64
    arch_map = {"x86_64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}
    zellij_arch = arch_map.get(arch)
    if not zellij_arch:
        raise RuntimeError(f"不支持的架构: {arch}")

    # 下载地址（GitHub Releases）
    version = "0.41.2"  # 固定版本，避免兼容性问题
    url = (f"https://github.com/zellij-org/zellij/releases/download/"
           f"v{version}/zellij-{zellij_arch}-unknown-linux-musl.tar.gz")

    install_dir = Path.home() / ".local" / "bin"
    install_dir.mkdir(parents=True, exist_ok=True)

    # 下载并解压
    import urllib.request, tarfile, io
    print(f"正在下载 Zellij v{version} ({zellij_arch})...")
    response = urllib.request.urlopen(url, timeout=60)
    with tarfile.open(fileobj=io.BytesIO(response.read()), mode="r:gz") as tar:
        tar.extract("zellij", path=str(install_dir))

    target = install_dir / "zellij"
    target.chmod(0o755)

    # 提示用户将 ~/.local/bin 加入 PATH
    print(f"Zellij 已安装到 {target}")
    if str(install_dir) not in os.environ.get("PATH", ""):
        print(f"请将 {install_dir} 加入 PATH（或重新登录 shell）")

    return str(target)
```

### 9.2 Fallback

如果下载失败（无网络 / GitHub 不可达）：

1. 打印明确的安装指引（包含手动下载 URL）
2. 降级为无 Zellij 模式（纯日志输出，任务仍正常运行）
3. 不阻塞任务启动

---

## 十、包迁移策略（补充疏漏 10）

### 10.1 迁移步骤

Phase 1 开始时一次性完成：

1. 创建 `src/maestro/` 目录结构
2. 将现有 `.py` 文件移动到 `src/maestro/` 下（同时重命名需要改名的文件）
3. 全局替换 `autopilot.*` → `maestro.*` import
4. 创建 `pyproject.toml`

### 10.2 pyproject.toml

```toml
[project]
name = "maestro"
version = "0.1.0"
description = "用 Manager Agent 自动驱动 Claude Code 完成开发任务"
requires-python = ">=3.10"
dependencies = [
    "openai>=1.0",
    "anthropic>=0.30",
    "pyyaml>=6.0",
    "python-telegram-bot>=21.0",
]

[project.optional-dependencies]
dev = ["pytest", "ruff"]

[project.scripts]
maestro = "maestro.cli:main"

[build-system]
requires = ["setuptools>=68.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[tool.setuptools.packages.find]
where = ["src"]
```

### 10.3 数据目录迁移

```python
def _migrate_data_dir():
    """检查并迁移旧版数据目录"""
    old_dir = Path.home() / ".autopilot"
    new_dir = Path.home() / ".maestro"

    if old_dir.exists() and not new_dir.exists():
        print(f"检测到旧版数据目录 {old_dir}，正在迁移到 {new_dir}...")
        shutil.copytree(old_dir, new_dir)
        print(f"迁移完成。旧目录 {old_dir} 已保留，可手动删除。")
```

### 10.4 配置文件兼容

```python
def load_config(config_path: str = "config.yaml") -> AppConfig:
    """加载配置文件，兼容旧版字段名"""
    raw = _load_yaml(config_path)

    # 兼容旧版字段名
    if "meta_agent" in raw and "manager" not in raw:
        raw["manager"] = raw.pop("meta_agent")

    # ... 正常解析
```

---

## 十一、Notifier 通知抽象层（补充疏漏 11）

### 11.1 接口设计

```python
from abc import ABC, abstractmethod
from enum import Enum

class NotifyLevel(str, Enum):
    INFO = "info"           # 常规轮次进度
    WARNING = "warning"     # ASK_USER、费用警告
    SUCCESS = "success"     # 任务完成
    ERROR = "error"         # 任务失败、熔断

class Notifier(ABC):
    """通知抽象层"""

    @abstractmethod
    def notify_turn(self, task_id: str, turn: int, max_turns: int,
                    cost: float, duration_ms: int, manager_summary: str):
        """每轮进度通知"""
        ...

    @abstractmethod
    def notify_ask_user(self, task_id: str, question: str) -> None:
        """ASK_USER 通知"""
        ...

    @abstractmethod
    def notify_completed(self, task_id: str, summary: str,
                         total_turns: int, total_cost: float,
                         modified_files: list[str]):
        """任务完成通知"""
        ...

    @abstractmethod
    def notify_failed(self, task_id: str, reason: str):
        """任务失败通知"""
        ...
```

### 11.2 实现类

```python
class LogNotifier(Notifier):
    """日志通知（默认，总是启用）"""
    # 写入日志文件 + 控制台

class TelegramNotifier(Notifier):
    """Telegram 推送通知"""
    # 调用 Telegram Bot API

class CompositeNotifier(Notifier):
    """组合通知器：同时发送到多个通道"""
    def __init__(self, notifiers: list[Notifier]):
        self.notifiers = notifiers

    def notify_turn(self, ...):
        for n in self.notifiers:
            try:
                n.notify_turn(...)
            except Exception as e:
                logger.warning(f"通知失败 ({type(n).__name__}): {e}")
```

### 11.3 Notifier 与 TelegramDaemon 的关系

- **TelegramDaemon** 是 Telegram Bot 的常驻进程，负责：接收命令、路由消息、管理生命周期
- **TelegramNotifier** 是通知接口的 Telegram 实现，被 Orchestrator 调用
- TelegramNotifier 通过**文件 IPC**（或共享 Bot Token 直接发消息）与 TelegramDaemon 解耦
- 如果 Daemon 不在运行，TelegramNotifier 仍可直接调用 Telegram API 发送通知

---

## 十二、llm_client.py 与 manager_agent.py 职责划分（补充疏漏 12）

### 12.1 职责边界

```
llm_client.py                    manager_agent.py
┌─────────────────────┐          ┌─────────────────────────┐
│ 通用 LLM 调用封装    │          │ Manager 业务逻辑        │
│                     │          │                         │
│ - 多 provider 支持   │  ←───── │ - system_prompt 管理    │
│ - 重试 + 退避        │          │ - 对话历史维护          │
│ - 超时处理           │          │ - JSON 输出解析         │
│ - token 计数         │          │ - action 路由           │
│ - 费用估算           │          │ - 信号检测              │
└─────────────────────┘          └─────────────────────────┘
```

### 12.2 llm_client.py 接口

```python
@dataclass
class LLMResponse:
    content: str
    input_tokens: int
    output_tokens: int
    cost_usd: float  # 估算
    model: str

class LLMClient:
    """通用 LLM 客户端，支持多 provider"""

    def __init__(self, config: ManagerConfig):
        self.config = config
        self._init_client()

    def chat(self, messages: list[dict], system: str = "") -> LLMResponse:
        """发送聊天请求"""
        for attempt in range(3):
            try:
                return self._call(messages, system)
            except (Timeout, ConnectionError) as e:
                if attempt == 2:
                    raise
                wait = 2 ** attempt
                logger.warning(f"LLM 请求失败，{wait}s 后重试: {e}")
                time.sleep(wait)
```

这样拆分的好处：

- llm_client.py 可被未来其他 Agent 复用（如果引入 Code Review Agent 等）
- 重试、超时、费用估算逻辑集中在一处
- manager_agent.py 专注于业务决策逻辑

---

## 十三、Context 上下文管理（补充疏漏 13）

### 13.1 上下文压缩策略

```python
class ContextManager:
    """管理传给 Manager 的上下文窗口"""

    def __init__(self, max_recent_turns: int = 5, max_result_chars: int = 3000):
        self.max_recent_turns = max_recent_turns
        self.max_result_chars = max_result_chars

    def build_context(self, conversation_history: list[dict]) -> list[dict]:
        """构建传给 LLM 的消息列表"""
        if len(conversation_history) <= self.max_recent_turns * 2:
            # 历史不长，全量传递
            return conversation_history

        # 策略：保留首轮（需求）+ 最近 N 轮 + 中间用摘要替代
        first_pair = conversation_history[:2]  # 首轮 user + assistant
        recent = conversation_history[-(self.max_recent_turns * 2):]

        # 中间轮次生成摘要
        middle = conversation_history[2:-(self.max_recent_turns * 2)]
        summary = self._summarize_middle(middle)

        return first_pair + [
            {"role": "user", "content": f"[中间 {len(middle)//2} 轮的摘要]\n{summary}"}
        ] + recent

    def truncate_output(self, output: str) -> str:
        """截断过长的 Claude Code 输出"""
        if len(output) <= self.max_result_chars:
            return output

        # 保留头部 + 尾部（尾部通常包含最终结果和错误信息）
        head_chars = self.max_result_chars // 3
        tail_chars = self.max_result_chars * 2 // 3

        return (
            output[:head_chars] +
            f"\n\n... [省略 {len(output) - head_chars - tail_chars} 字符] ...\n\n" +
            output[-tail_chars:]
        )

    def _summarize_middle(self, messages: list[dict]) -> str:
        """生成中间轮次的简短摘要"""
        summary_parts = []
        for i in range(0, len(messages), 2):
            if i + 1 < len(messages):
                instruction = messages[i+1]["content"][:80]
                summary_parts.append(f"  Turn {i//2+2}: {instruction}")
        return "\n".join(summary_parts[-5:])  # 最多保留 5 行摘要
```

### 13.2 输出截断策略

为什么保留尾部更多？

- Claude Code 的输出通常是：**进度日志（头部）→ 代码内容（中部）→ 执行结果/错误信息（尾部）**
- Manager 做决策主要依赖**尾部的结果信息**
- 头部保留一部分用于了解上下文

---

## 十四、reporter.py 报告生成（补充疏漏 14）

### 14.1 报告模板

```markdown
# 任务报告: {requirement}

## 概要

| 项目 | 值 |
|------|-----|
| 任务 ID | {task_id} |
| 状态 | {status} |
| 总轮数 | {total_turns} |
| 总耗时 | {total_duration} |
| 总费用 | ${total_cost} |
| 开始时间 | {started_at} |
| 完成时间 | {completed_at} |

## 修改文件

{modified_files_list}

## 执行轨迹

{turn_by_turn_summary}

## Manager 总结

{final_summary}
```

### 14.2 生成时机

- **自动生成**：任务状态变为 `completed` 或 `failed` 时自动生成
- **按需生成**：`/report` 或 `maestro report` 命令触发
- 报告保存到 `~/.maestro/sessions/<task_id>/report.md`

### 14.3 修改文件列表的获取

从 Claude Code 的 JSON 输出中，`result` 字段通常会提到修改了哪些文件。可通过正则提取或让 Manager 在 DONE 的 `summary` 中列出。另一种更可靠的方式是在 working_dir 下运行 `git diff --name-only` 获取实际变更文件列表。

---

## 十五、`_worker` 内部命令（补充疏漏 15）

### 15.1 CLI 注册

```python
# cli.py
def main():
    parser = argparse.ArgumentParser(prog="maestro")
    subparsers = parser.add_subparsers(dest="command")

    # ... 其他公开命令 ...

    # 内部命令（不在 help 中显示）
    worker_parser = subparsers.add_parser("_worker", help=argparse.SUPPRESS)
    worker_parser.add_argument("task_id")
    worker_parser.add_argument("working_dir")
    worker_parser.add_argument("requirement")
```

### 15.2 调用方式

TelegramDaemon 启动任务时：

```python
def _on_run_command(self, chat_id, working_dir, requirement):
    task_id = self._generate_id()

    # 注册任务
    self.registry.create_task(task_id, requirement, working_dir)

    # 在新 Zellij session 中启动 worker
    cmd = [
        "zellij", "--session", f"maestro-{task_id}",
        "--", "maestro", "_worker", task_id, working_dir, requirement
    ]
    subprocess.Popen(cmd, start_new_session=True)  # 完全脱离父进程
```

### 15.3 Worker 执行逻辑

```python
def _handle_worker(args):
    """内部 worker：加载配置 → 创建 Orchestrator → 运行任务"""
    config = load_config()  # 加载全局配置
    config.claude_code.working_dir = args.working_dir  # 覆盖工作目录

    orchestrator = Orchestrator(config, task_id=args.task_id)
    orchestrator.run(args.requirement)
```

---

## 十六、完善后的 Orchestrator 主循环

整合所有补充设计后，Orchestrator 的完整主循环：

```python
class Orchestrator:
    def __init__(self, config: AppConfig, task_id: str = None):
        self.config = config
        self.task_id = task_id or str(uuid.uuid4())[:8]
        self.session_dir = Path(f"~/.maestro/sessions/{self.task_id}").expanduser()
        self.session_dir.mkdir(parents=True, exist_ok=True)

        # 核心组件
        self.runner = ClaudeRunner(config.claude_code, config.claude_code.working_dir)
        self.manager = ManagerAgent(config.manager, LLMClient(config.manager))
        self.breaker = CircuitBreaker(config.safety)
        self.context_mgr = ContextManager(config.context)
        self.notifier = self._build_notifier(config)
        self.registry = TaskRegistry()

        # 文件路径
        self.state_path = self.session_dir / "state.json"
        self.checkpoint_path = self.session_dir / "checkpoint.json"
        self.inbox_path = self.session_dir / "inbox.txt"
        self.inbox_path.touch()

    def run(self, requirement: str):
        """执行任务的完整流程"""
        # 1. 初始化状态
        self._update_state("executing", requirement=requirement)
        self.registry.update_task(self.task_id, status="executing")

        # 2. 启动 Zellij Session
        zellij = ZellijSession(self.task_id)
        zellij.launch()

        # 3. Manager 初始化
        self.manager.start_task(requirement)
        first_instruction = self.manager.decide("")

        # 4. 主循环
        self._main_loop(start_turn=1, first_instruction=first_instruction)

    def _main_loop(self, start_turn: int, first_instruction: str):
        instruction = first_instruction

        for turn in range(start_turn, self.config.manager.max_turns + 1):
            # (a) 检查 inbox
            user_messages = read_and_clear_inbox(str(self.inbox_path))
            if user_messages:
                extra = "\n".join([parse_inbox_message(m) for m in user_messages])
                instruction = f"{instruction}\n\n[用户补充]: {extra}"

            # (b) 执行 Claude Code
            result = self.runner.run(instruction)

            # (c) 熔断检查
            breaker_reason = self.breaker.check(instruction, result.cost_usd)
            if breaker_reason:
                self._handle_breaker(breaker_reason)
                return

            # (d) 更新状态
            self._update_state(
                "executing",
                current_turn=turn,
                total_cost_usd=self.breaker._total_cost,
                claude_session_id=result.session_id,
            )

            # (e) 通知
            self.notifier.notify_turn(
                self.task_id, turn, self.config.manager.max_turns,
                result.cost_usd, result.duration_ms, ""
            )

            # (f) Manager 决策
            truncated_output = self.context_mgr.truncate_output(result.output)
            decision = self.manager.decide(truncated_output)
            parsed = self.manager.parse_response(decision)

            # (g) 路由 action
            if parsed["action"] == "done":
                self._handle_done(parsed, turn)
                return
            elif parsed["action"] == "blocked":
                self._handle_blocked(parsed)
                return
            elif parsed["action"] == "ask_user":
                self._handle_ask_user(parsed)
                # 等待用户回复后继续
                instruction = self._wait_for_user_reply()
                if instruction is None:  # 超时
                    self._handle_timeout()
                    return
            elif parsed["action"] == "retry":
                pass  # instruction 不变，重试
            else:  # execute
                instruction = parsed["instruction"]

            # (h) 保存 checkpoint
            self._save_checkpoint()

        # 超过最大轮数
        self._handle_max_turns()
```

---

## 十七、完善后的配置文件

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
  retry_backoff: 2             # 指数退避基数（秒）
  system_prompt: |
    你是资深工程师助手，负责协调 Claude Code 完成用户需求。
    必须以 JSON 回复：{"action":"execute|done|blocked|ask_user|retry","instruction":"...","reasoning":"..."}
    ...

claude_code:
  command: claude
  auto_approve: true
  timeout: 600                 # 单轮 subprocess 超时（秒）
  # working_dir 由每个任务单独指定

context:
  max_recent_turns: 5          # 传给 Manager 的最近轮数
  max_result_chars: 3000       # Claude 输出截断长度

safety:
  max_consecutive_similar: 3   # 死循环检测阈值
  max_budget_usd: 5.0          # 单任务费用上限
  budget_action: ask_user      # 超预算时的动作: ask_user | abort

telegram:
  enabled: true
  bot_token: ${TELEGRAM_BOT_TOKEN}
  allowed_chat_ids:            # 授权用户列表
    - ${TELEGRAM_CHAT_ID}
  admin_chat_id: ${TELEGRAM_CHAT_ID}
  push_every_turn: true
  ask_user_timeout: 3600       # ASK_USER 等待超时（秒）
  rate_limit_per_minute: 10

zellij:
  enabled: true
  auto_install: true           # 未安装时自动安装
  layout: split

logging:
  dir: ~/.maestro/logs
  level: INFO
  retention:
    max_task_logs: 50
    max_days: 30
    max_total_size_mb: 500
```

---

## 十八、完善后的目录结构

```
Maestro/
├── pyproject.toml
├── config.example.yaml
├── src/maestro/
│   ├── __init__.py
│   ├── cli.py                 # 命令行入口（run/list/status/ask/abort/resume/report/daemon/_worker）
│   ├── config.py              # 配置加载（兼容旧版字段名 + 数据迁移）
│   ├── orchestrator.py        # 单任务调度核心（主循环 + 状态管理）
│   ├── claude_runner.py       # Claude CLI subprocess 封装
│   ├── manager_agent.py       # Manager Agent 业务逻辑（JSON 解析 + action 路由）
│   ├── llm_client.py          # 通用 LLM 客户端（多 provider + 重试 + 费用估算）
│   ├── state.py               # 状态机（枚举 + 转换规则）+ 熔断器
│   ├── context.py             # 上下文管理（压缩 + 截断）
│   ├── session.py             # Zellij 管理（布局 + 自动安装）
│   ├── telegram_bot.py        # Telegram Bot 命令处理 + Daemon 生命周期
│   ├── registry.py            # 多任务注册表（CRUD + 文件锁）
│   ├── notifier.py            # 通知抽象层（Log / Telegram / Composite）
│   ├── reporter.py            # 报告生成（模板 + git diff）
│   └── inbox.py               # inbox.txt 读写协议（文件锁 + 消息格式）
└── tests/
    ├── test_config.py
    ├── test_state.py
    ├── test_context.py
    ├── test_inbox.py
    ├── test_breaker.py
    └── test_registry.py
```

新增的 `inbox.py` 模块封装了 inbox.txt 的读写协议，避免 Orchestrator 和外部调用方（CLI/Telegram）各自实现导致不一致。

---

## 十九、完善后的分阶段实施计划

### Phase 1: 核心闭环（单任务 + CLI + 基础 Telegram）

**目标**：一个任务从 CLI 或 Telegram 启动，自动完成，推送结果。

**模块开发顺序**（有依赖关系，必须按序）：

```
1. config.py        ← 基础设施，所有模块依赖
2. state.py         ← 状态枚举 + 熔断器
3. llm_client.py    ← LLM 调用封装
4. context.py       ← 上下文管理
5. inbox.py         ← inbox 读写协议
6. claude_runner.py ← Claude CLI subprocess
7. manager_agent.py ← Manager 决策逻辑
8. notifier.py      ← 通知抽象层（先只实现 LogNotifier）
9. orchestrator.py  ← 调度核心（集成以上所有）
10. session.py      ← Zellij 管理 + 自动安装
11. registry.py     ← 任务注册表
12. cli.py          ← CLI 入口（run / status / _worker）
13. telegram_bot.py ← Telegram Daemon（/run / /status / 进度推送）
14. notifier.py     ← 补充 TelegramNotifier
```

**验证标准**：
- [ ] `maestro run "需求"` 启动任务，Manager 自动驱动 Claude Code
- [ ] 任务完成后输出 DONE 并退出
- [ ] `maestro daemon start` 启动 Telegram Daemon
- [ ] Telegram `/run` 启动任务，自动推送进度，完成后推送通知
- [ ] SSH 断开后任务不中断

### Phase 2: 多任务 + 交互完善 + 报告

**目标**：支持多任务并行，完善所有交互命令。

**新增/完善**：

```
1. registry.py      ← 多任务 CRUD + 并发安全
2. orchestrator.py  ← inbox 消费 + ASK_USER 等待
3. cli.py           ← list / ask / abort / resume / report
4. telegram_bot.py  ← /list / /ask / /abort / /report / 直接回复
5. reporter.py      ← 报告生成
6. notifier.py      ← ASK_USER 通知 + 完成通知完善
```

**验证标准**：
- [ ] 同时运行 2 个任务，各自独立完成
- [ ] `/list` 正确显示所有任务状态
- [ ] `/ask` 消息路由到正确的任务
- [ ] `/abort` 可终止任务
- [ ] `maestro resume` 可恢复崩溃的任务
- [ ] `/report` 生成完整报告

### Phase 3: 稳定性加固 + 安全

**目标**：生产级可靠性。

**完善**：

```
1. state.py         ← 熔断器参数调优
2. context.py       ← 上下文压缩策略优化（可选 LLM 摘要）
3. telegram_bot.py  ← 安全加固（目录白名单 / rate limiting / 审计日志）
4. session.py       ← Daemon 自恢复（watchdog）
5. config.py        ← 日志清理策略
6. tests/           ← 完整测试套件
```

**验证标准**：
- [ ] 连续运行 72 小时无崩溃
- [ ] 费用超限自动停止
- [ ] 死循环自动熔断
- [ ] Manager API 故障时优雅降级
- [ ] Telegram 断网后自动重连

---

## 二十、遗留风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| `claude -p --output-format json` 输出格式在 Claude Code 更新后变化 | 解析失败 | 版本锁定 + JSON schema 校验 + fallback 到纯文本模式 |
| Telegram Bot API 限流（30 msg/s） | 多任务高频推送被限 | 消息队列 + 批量发送 + 合并同任务连续消息 |
| VPS 内存不足（多任务并行） | OOM | 限制最大并行任务数（建议 3-5 个）+ 配置项 `max_parallel_tasks` |
| Claude Code 会话超长后性能下降 | 响应变慢 | 监控 `duration_ms`，超阈值时让 Manager 考虑开新会话 |
| Manager 决策质量差（便宜模型） | 任务完不成 | 提供高质量 system_prompt 模板 + 允许用户随时介入 |

---

## 二十一、设计总结

本设计方案在原终稿 v5 基础上，补充了以下 15 项关键疏漏：

1. **Claude Runner 交互协议**：明确了 subprocess 调用方式、JSON 解析、session_id 管理
2. **Manager 输出格式**：完整 action 枚举、JSON fallback、reasoning 用途
3. **状态机**：完整状态枚举、转换规则、state.json 结构
4. **inbox 协议**：消息格式、文件锁、读写时机
5. **checkpoint 恢复**：数据结构、写入时机、恢复流程
6. **费用追踪**：来源、估算算法、预算熔断逻辑
7. **Telegram 安全**：授权模型、目录白名单、注入防护
8. **日志管理**：目录结构、保留策略、清理逻辑
9. **Zellij 自动安装**：平台检测、下载逻辑、fallback
10. **包迁移**：步骤、pyproject.toml、数据迁移、配置兼容
11. **Notifier 设计**：接口定义、实现类、与 Daemon 关系
12. **llm_client 职责**：与 manager_agent 的边界、接口定义
13. **上下文管理**：压缩策略、截断算法
14. **报告生成**：模板、生成时机、文件列表获取
15. **_worker 命令**：CLI 注册、调用方式、执行逻辑

新增了 `inbox.py` 模块和 `max_parallel_tasks` 配置项。
