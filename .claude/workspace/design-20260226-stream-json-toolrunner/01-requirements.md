# 需求分析：stream-json-toolrunner

## 功能概述

为 ToolRunner 的 Claude Code 调用模式（`type=claude`）添加 `stream-json` 实时流式输出支持。当前系统使用 `subprocess.run` + `--output-format json` 的阻塞模式，整轮执行完毕后才能获取输出。需要改为 `subprocess.Popen` + `--output-format stream-json` 的流式模式，实现执行过程中的实时输出推送能力（Zellij 面板实时滚动、Telegram focus 模式实时推送等），同时保留 `session_id`、`cost_usd`、`is_error` 等结构化数据的提取。

## 核心功能点

- [ ] **功能点 1：流式进程管理**
  - 将 `_run_claude()` 中的 `subprocess.run` 替换为 `subprocess.Popen`
  - 以 `--output-format stream-json` 替代 `--output-format json`
  - 逐行读取 stdout 的 NDJSON 流，解析每一行为独立 JSON 事件
  - 保留超时控制机制（`timeout` 配置项）
  - 保留 `FileNotFoundError` 等异常处理
  - **验收标准**：Claude Code 以 Popen 方式启动，输出以 stream-json 格式逐行接收

- [ ] **功能点 2：stream-json 事件解析**
  - 解析 5 种事件类型：`system`（init）、`assistant`（消息）、`user`（工具结果）、`result`（最终结果）、`stream_event`（token 级流式）
  - 从 `system`（subtype=init）事件中提取 `session_id`
  - 从 `result` 事件中提取 `session_id`、`total_cost_usd`、`is_error`、`subtype`（错误类型）、`result`（最终文本）、`duration_ms`
  - 从 `assistant` 事件的 `message.content` 中提取文本内容用于中间输出
  - **验收标准**：所有关键字段（session_id、cost_usd、is_error、result 文本）能正确提取，与原 JSON 模式的 `RunResult` 字段保持一致

- [ ] **功能点 3：实时输出回调机制**
  - 在 `ToolRunner.run()` 方法中新增可选的回调参数（如 `on_output: Callable`）
  - 回调在每收到一个有意义的事件（assistant 文本、工具执行结果等）时触发
  - 回调接口简洁：传入事件类型和文本内容，供上游（Orchestrator）转发
  - 不使用回调时（`on_output=None`），行为等价于原阻塞模式：收集全部输出后返回 `RunResult`
  - **验收标准**：Orchestrator 可通过回调在执行过程中获得实时文本输出

- [ ] **功能点 4：Orchestrator 集成**
  - Orchestrator 的 `_main_loop()` 调用 `runner.run()` 时传入回调
  - 回调将实时输出写入 Zellij 日志文件（`claude.log`，供 `tail -f` 面板展示）
  - 回调将实时输出追加写入 `turns.jsonl` 的中间事件（可选，供 Daemon 实时推送）
  - 最终 `RunResult` 的使用方式不变（传给 Manager Agent 决策）
  - **验收标准**：Zellij 面板能在 Claude Code 执行过程中实时看到输出滚动

- [ ] **功能点 5：Telegram focus 模式实时推送（增强）**
  - 利用 Orchestrator 写入的实时事件，Daemon 的 `_push_focused_turns()` 可推送中间输出
  - 或：在 `turns.jsonl` 中新增中间事件行，Daemon 读取后推送
  - **验收标准**：Telegram focus 模式下，用户能在每轮执行过程中（而非仅在轮次结束后）收到输出片段

- [ ] **功能点 6：RunResult 兼容性**
  - `RunResult` 的字段定义不变：`output`、`session_id`、`cost_usd`、`duration_ms`、`is_error`、`error_type`
  - 流式模式下，`output` 字段包含最终 `result` 事件的 `result` 字段文本
  - 如果 `result` 事件缺失（进程崩溃），降级为收集所有 assistant 文本拼接
  - **验收标准**：Manager Agent 收到的 `RunResult` 与原 JSON 模式完全一致

- [ ] **功能点 7：配置项**
  - 在 `CodingToolConfig` 中新增 `stream` 布尔字段（默认 `True`）
  - `stream=True` 时使用 stream-json 模式，`stream=False` 时保留原 JSON 阻塞模式
  - 在 `config.example.yaml` 中文档化此配置项
  - **验收标准**：用户可通过配置切换流式/阻塞模式

## 边界情况

- **场景 1：Claude Code 进程崩溃（非正常退出）**
  没有 `result` 事件，需要从已收集的 assistant 文本中组装输出，设置 `is_error=True`

- **场景 2：stream-json 某行 JSON 解析失败**
  跳过该行并记录警告日志，继续处理后续行

- **场景 3：超时**
  Popen 模式需要手动实现超时逻辑（不能依赖 `subprocess.run(timeout=...)`），使用 `threading.Timer` 或在读取循环中检查已用时间，超时后 `process.kill()`

- **场景 4：巨大输出**
  单行事件可能包含大量文本（如大文件内容），回调应传递原始文本，截断逻辑留给上游（ContextManager）

- **场景 5：generic 模式不受影响**
  `type=generic` 的 `_run_generic()` 方法完全不受此变更影响

- **场景 6：`--resume session_id` 兼容性**
  流式模式同样支持 `--resume` 参数，session_id 从 `system` init 事件获取

- **场景 7：无回调调用**
  当 `on_output=None` 时，静默收集所有事件，最终返回 `RunResult`，完全等价于原阻塞行为

- **场景 8：回调异常**
  回调函数抛出异常时，捕获并记录警告日志，不中断流式读取

## 非功能需求

- **性能**：流式读取不应引入显著的 CPU 开销。逐行 readline + json.loads 的方式足够高效
- **内存**：不缓存全部 stream 事件对象，仅保留必要的文本累积（最终 output）和元数据
- **兼容性**：Python 3.10+ 标准库即可实现，不引入新的第三方依赖
- **线程安全**：回调在主线程（Orchestrator 所在线程）中同步调用，无需额外同步机制

## 约束条件

- **技术约束**：
  - 必须使用 Python 标准库的 `subprocess.Popen`，不使用 `asyncio.subprocess`（Orchestrator 是同步代码）
  - Claude Code CLI 的 stream-json 输出格式为 NDJSON（每行一个 JSON 对象）
  - `--output-format stream-json` 要求 `-p`（print/非交互模式）
  - `result` 事件始终是最后一个事件，包含汇总信息

- **设计约束**：
  - `RunResult` dataclass 不改变字段定义，保持向后兼容
  - `_run_generic()` 方法不做任何修改
  - 不引入异步代码（asyncio），保持现有同步架构
  - 回调接口极简，避免过度设计

## 影响范围

- **直接修改的文件**：
  - `src/maestro/tool_runner.py` — 核心变更：新增 `_run_claude_stream()` 方法，修改 `run()` 方法签名
  - `src/maestro/config.py` — `CodingToolConfig` 新增 `stream` 字段
  - `config.example.yaml` — 文档化 `stream` 配置项
  - `src/maestro/orchestrator.py` — `_main_loop()` 传入回调，写入实时日志

- **间接影响的模块**：
  - `src/maestro/session.py` — Zellij 面板的 `claude.log` 已有 `tail -f`，实时写入后自动生效
  - `src/maestro/telegram_bot.py` — focus 模式推送逻辑可能需要调整以支持中间事件
  - `src/maestro/context.py` — 无需修改（截断逻辑作用于最终 `RunResult.output`）

- **不受影响的模块**：
  - `src/maestro/manager_agent.py` — 接收 `RunResult.output` 进行决策，接口不变
  - `src/maestro/state.py` — 状态机不受影响
  - `src/maestro/registry.py` — 任务注册表不受影响
  - `src/maestro/cli.py` — CLI 参数不受影响

## 验收标准汇总

- [ ] Claude Code 以 `subprocess.Popen` + `--output-format stream-json` 启动
- [ ] 正确解析 NDJSON 流中的 `system`、`assistant`、`user`、`result`、`stream_event` 事件
- [ ] 从 `result` 事件中提取 `session_id`、`total_cost_usd`、`is_error`、`result` 文本
- [ ] `RunResult` 的所有字段正确填充，与原 JSON 模式完全兼容
- [ ] 回调机制正常工作：Orchestrator 通过回调将实时输出写入 Zellij 日志
- [ ] 无回调时等价于原阻塞模式
- [ ] `stream=False` 配置可回退到原 JSON 阻塞模式
- [ ] 超时、进程崩溃、JSON 解析错误等异常正确处理
- [ ] `_run_generic()` 不受任何影响
- [ ] `config.example.yaml` 包含 `stream` 配置项说明
- [ ] 现有测试不受影响，新增 stream 模式的单元测试

## 风险评估

- **风险 1**：Claude Code 版本差异导致 stream-json 格式字段不一致
  - **应对策略**：对未知字段做宽容解析（忽略未知字段），对缺失字段使用默认值

- **风险 2**：Popen 超时实现的可靠性
  - **应对策略**：使用 `threading.Timer` 在超时时调用 `process.kill()`，并在主循环中二次检查 `process.poll()`

- **风险 3**：实时回调频率过高导致 Telegram 推送被限流
  - **应对策略**：回调仅写入文件（Zellij 日志），Telegram 推送仍按 5 秒轮询间隔，不直接由回调触发

- **风险 4**：stream-json 模式下 `result` 字段为空（Claude Code 无有效输出）
  - **应对策略**：降级到从 assistant 事件累积的文本作为输出
