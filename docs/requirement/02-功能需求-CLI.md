# 02 - 功能需求：CLI 命令

## 2.1 命令总览

```bash
maestro <command> [options]
```

| 命令 | 用途 | 类型 |
|------|------|------|
| `run` | 启动新任务 | 核心 |
| `list` | 查看任务列表 | 查询 |
| `status` | 查看任务详情 | 查询 |
| `ask` | 给运行中的任务发送反馈 | 交互 |
| `chat` | 与任务 Manager 独立问答 | 交互 |
| `abort` | 终止任务 | 控制 |
| `resume` | 恢复崩溃的任务 | 控制 |
| `report` | 查看任务最终报告 | 查询 |
| `switch` | 查看/切换当前编码工具 | 控制 |
| `daemon` | Telegram Daemon 管理 | 运维 |
| `_worker` | 内部后台执行（用户不直接调用） | 内部 |

---

## 2.2 run - 启动新任务

### 语法

```bash
maestro run [options] "需求描述"
```

### 参数

| 参数 | 缩写 | 类型 | 默认值 | 说明 |
|------|------|------|--------|------|
| `requirement` | - | positional | 必填 | 需求描述文本 |
| `--config` | `-c` | string | config.yaml | 配置文件路径 |
| `--foreground` | `-f` | flag | false | 前台同步运行（调试用） |
| `--working-dir` | `-w` | string | 当前目录 | 编码工具的工作目录 |
| `--provider` | - | string | 配置值 | 覆盖 Manager provider |
| `--model` | - | string | 配置值 | 覆盖 Manager 模型 |

### 行为规格

#### 后台模式（默认）

1. 生成 8 位随机短 ID（hex）作为 task_id
2. 并发检查：活跃任务数 < `safety.max_parallel_tasks`，否则拒绝
3. 在 Registry 中创建任务条目
4. 通过 nohup 后台启动 worker 进程（日志写入 `~/.maestro/logs/tasks/{task_id}/worker.log`）
5. 输出：任务 ID + 查看进度的命令提示

#### 前台模式（`-f`）

1. 同后台模式步骤 1-3
2. 直接在当前终端同步执行 Orchestrator
3. 所有日志输出到 stdout
4. 阻塞直到任务完成/失败/中止

### 输出示例

```
任务已启动: a1b2c3d4
查看进度: maestro status a1b2c3d4
发送反馈: maestro ask a1b2c3d4 "消息"
```

---

## 2.3 list - 查看任务列表

### 语法

```bash
maestro list
```

### 行为规格

1. 从 Registry 读取所有任务
2. 对 `pending/executing/waiting_user` 任务同步 `state.json` 最新状态
3. 按创建时间降序排列
4. 表格输出

### 输出格式

```
ID        状态    需求                     创建时间
a1b2c3d4  [>>]   实现登录模块             2026-02-27 10:30
b2c3d4e5  [OK]   修复翻页 Bug             2026-02-27 09:15
c3d4e5f6  [!!]   添加单元测试             2026-02-26 18:00
```

### 状态图标

| 图标 | 状态 | 说明 |
|------|------|------|
| `[..]` | pending | 等待启动 |
| `[>>]` | executing | 执行中 |
| `[??]` | waiting_user | 等待用户回复 |
| `[OK]` | completed | 已完成 |
| `[!!]` | failed | 失败 |
| `[XX]` | aborted | 已中止 |

### 失败原因细分图标

| 图标 | fail_reason | 说明 |
|------|-------------|------|
| `[TO]` | ask_user_timeout | 等待用户回复超时 |
| `[MT]` | max_turns | 超过最大轮数 |
| `[CB]` | breaker_tripped | 熔断器触发 |
| `[BK]` | blocked | Manager 判断阻塞 |
| `[CR]` | worker_crashed | Worker 进程崩溃 |
| `[ER]` | runtime_error | 运行时异常 |

---

## 2.4 status - 查看任务详情

### 语法

```bash
maestro status <task_id>
```

### 行为规格

1. 从 state.json 读取任务完整状态
2. 格式化输出

### 输出内容

| 字段 | 说明 |
|------|------|
| 任务 ID | 8 位短 ID |
| 状态 | 当前状态 + 图标 |
| 需求 | 原始需求文本 |
| 进度 | 当前轮数 / 最大轮数 |
| 费用 | 累计费用（$USD） |
| 工作目录 | 编码工具的工作路径 |
| 工具类型 | claude / codex / generic |
| 最近指令 | Manager 最后一次 instruction |
| 最近输出 | 编码工具最后一次输出（截断） |
| Manager 思路 | 最后一次 reasoning |
| 最近问题 | 如处于 `waiting_user`，显示 Manager 最近一次 question |
| 错误信息 | 如有失败原因，显示详情 |

---

## 2.5 ask - 发送实时反馈

### 语法

```bash
maestro ask <task_id> "消息内容"
```

### 行为规格

1. 格式化消息为 `时间戳|cli|消息内容`
2. 通过 fcntl 文件锁写入 `~/.maestro/sessions/{task_id}/inbox.txt`
3. Worker 主循环在下一轮开始前读取并清空 inbox
4. 反馈内容合并到 Manager 的下一次决策上下文中

### 前置条件

- 任务必须处于 `executing` 或 `waiting_user` 状态

---

## 2.6 chat - 与 Manager 独立问答

### 语法

```bash
maestro chat <task_id> "问题"
  -c, --config <path>    配置文件路径
```

### 行为规格

1. 加载任务的 state.json 获取当前上下文（最近指令、输出、状态）
2. 使用 `chat_prompt_file` 作为 system prompt
3. 向 Manager LLM 发起**独立请求**（不改变任务主循环的对话历史）
4. 返回自然语言回复（非 JSON）

### 与 ask 的区别

| 对比 | ask | chat |
|------|-----|------|
| 目的 | 注入反馈影响任务执行 | 查询/咨询不影响执行 |
| 写入位置 | inbox.txt | 无（独立请求） |
| 回复来源 | 无直接回复 | LLM 即时回复 |
| 对任务影响 | 改变下一轮决策 | 零影响 |

---

## 2.7 abort - 终止任务

### 语法

```bash
maestro abort <task_id>
```

### 行为规格

1. 在 `~/.maestro/sessions/{task_id}/` 下创建 `abort` 信号文件
2. 更新 state.json 状态为 `aborted`
3. 更新 Registry 状态为 `aborted`
4. Worker 主循环检测到 abort 文件后，删除文件并退出

### 特性

- 即使编码工具正在执行（subprocess 运行中），下一次主循环检查点也会捕获 abort 信号
- 不会强制 kill 正在运行的 subprocess，等待其自然结束后退出

---

## 2.8 resume - 恢复崩溃的任务

### 语法

```bash
maestro resume <task_id>
  -c, --config <path>    配置文件路径
  -f, --foreground       前台同步运行
```

### 行为规格

1. 读取 `~/.maestro/sessions/{task_id}/checkpoint.json`
2. 恢复 Manager 对话历史（conversation history）
3. 恢复 ToolRunner 会话 ID（Claude / Codex）
4. 恢复费用累计、轮数计数、最近问题等 checkpoint 状态
5. 更新状态为 `executing` 并清空瞬时 `sub_status`
6. 若 inbox 中已有待处理用户消息，优先交给 Manager 结合恢复通知重新决策
7. 继续主循环

### 前置条件

- 任务必须处于 `failed` 状态
- `checkpoint.json` 必须存在

---

## 2.9 report - 查看任务报告

### 语法

```bash
maestro report <task_id>
```

### 行为规格

1. 读取 `~/.maestro/sessions/{task_id}/report.md`
2. 输出到终端

### 报告内容

- 任务基本信息（ID、需求、状态、耗时、费用）

---

## 2.10 switch - 查看/切换编码工具

### 语法

```bash
maestro switch
maestro switch <tool_name>
  -c, --config <path>    配置文件路径
```

### 行为规格

1. 不带参数时，显示当前激活工具和所有可用预设
2. 带工具名时，校验该工具存在于 `coding_tools.presets`
3. 原子更新 `config.yaml` 中的 `coding_tools.active_tool`
4. 切换仅影响后续新任务，运行中的任务不受影响
- Manager 总结（summary）
- 修改文件列表（git diff）
- 执行轮数统计

---

## 2.10 daemon - Telegram Daemon 管理

### 语法

```bash
maestro daemon <action>
  -c, --config <path>    配置文件路径
```

### action 选项

| action | 行为 |
|--------|------|
| `start` | 通过 nohup 后台启动 Telegram Bot，管理 PID 文件 |
| `stop` | 发送 SIGTERM 终止 Daemon 进程 |
| `status` | 检查 PID 是否存活，输出运行状态 |

### PID 文件位置

```
~/.maestro/daemon.pid
```

---

## 2.11 _worker - 内部后台执行

### 语法

```bash
maestro _worker <task_id> <working_dir> <requirement>
  -c, --config <path>    配置文件路径
```

### 说明

- **用户不应直接调用**此命令
- 由 `run` 命令内部通过 nohup 后台启动
- 执行 Orchestrator 的完整主循环
