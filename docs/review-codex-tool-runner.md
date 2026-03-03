# 代码审查报告：tool_runner.py Codex CLI 支持

**审查时间**: 2026-02-27
**审查文件**: `src/maestro/tool_runner.py`
**审查范围**: Codex CLI 新增代码（`_run_codex`、`_parse_codex_jsonl`、`_estimate_codex_cost`、`run()` 路由、`resume_session()`）
**审查员**: 代码审查专家

---

## 审查摘要表

| 级别     | 数量 | 说明                         |
|----------|------|------------------------------|
| Critical | 0    | 无                           |
| High     | 2    | 命令格式错误、输出提取可能缺失 |
| Medium   | 3    | 定价硬编码、session_id 返回值不一致、错误场景遗漏 |
| Low      | 3    | 日志信息不完整、注释与实现不一致、timed_out 竞态 |
| Info     | 2    | 与 Claude 模式的代码重复、输出合并策略说明缺失 |

**整体评估**: REQUEST CHANGES

---

## 详细发现

---

### HIGH 问题

---

#### [CR-001] `_run_codex()` 命令格式错误 — resume 子命令位置不符合 Codex CLI 规范

**文件**: `src/maestro/tool_runner.py:529-534`

**问题描述**:

当前命令构建逻辑为：

```python
cmd = [self.config.command, "exec", "--json"]
if self.config.auto_approve:
    cmd.append("--full-auto")
if self.session_id:
    cmd.extend(["resume", self.session_id])   # 问题点
cmd.append(instruction)
```

生成的命令形如：
```
codex exec --json --full-auto resume <session_id> "<instruction>"
```

Codex CLI 的会话恢复子命令文档（模块顶部注释第16行亦声明）为 `codex exec resume <session_id>`，而非 `codex exec --json resume <session_id> "<instruction>"`。`resume` 是 `exec` 的子命令，其语义与 `exec <instruction>` 互斥：**exec + resume 不能同时带 instruction**。

此外，`--json`、`--full-auto` 是 `exec` 的选项，如果 `resume` 也是子命令，那么 `--full-auto resume <session_id>` 这一混合形式的合法性存疑。需要参照 Codex CLI 官方文档确认以下两点：
1. 会话恢复时是否传 instruction（恢复后续命令 vs 继续上一会话）？
2. 正确格式是 `codex exec resume <session_id>` 还是 `codex exec --resume <session_id>`（flag 形式）？

如果 Codex CLI 实际使用 `--resume <session_id>` flag（与 Claude 模式一致），则第 533 行的 `["resume", self.session_id]` 应改为 `["--resume", self.session_id]`。

**修复建议**:

在确认 Codex CLI 文档后，选择以下之一：

```python
# 方案 A：若 resume 是 exec 的子命令且不接受额外 instruction
if self.session_id:
    cmd = [self.config.command, "exec", "--json"]
    if self.config.auto_approve:
        cmd.append("--full-auto")
    cmd.extend(["resume", self.session_id])
    # 不追加 instruction，因为 resume 模式从历史会话继续
else:
    cmd.append(instruction)

# 方案 B：若恢复使用 --resume flag（类似 Claude 模式）
if self.session_id:
    cmd.extend(["--resume", self.session_id])
cmd.append(instruction)
```

---

#### [CR-002] `_parse_codex_jsonl()` 输出提取策略过窄，可能遗漏主要输出

**文件**: `src/maestro/tool_runner.py:673-678`

**问题描述**:

当前只提取 `item.completed` 中 `type == "agent_message"` 的 `text` 字段：

```python
elif event_type == "item.completed":
    item = obj.get("item", {})
    if item.get("type") == "agent_message":
        text = item.get("text", "")
        if text:
            result_text = text   # 取最后一个非空 agent_message
```

存在两个问题：

**问题 2a**：Codex CLI 的 agent 最终输出字段名未经实测验证。不同版本的 Codex CLI 可能使用 `content`、`output`、`message` 等字段，而非 `text`。如果字段名不对，`text` 始终为 `""`，导致 `result_text` 永远为空，然后 fallback 到 stderr（而 stderr 通常也是空的），最终返回 `RunResult(output="", is_error=False)`，Manager 收到空输出时行为不可预测。

**问题 2b**：仅取"最后一个" agent_message 可能丢失重要中间消息。Codex CLI 在长任务中可能产生多个 agent_message，只取最后一个意味着前面所有输出都被丢弃。Claude 模式（`_parse_stream_json`）中也是只取 `result` 事件的文本，但 Claude 在 result 事件中已聚合了完整输出。Codex 是否也这样设计需要确认。

**修复建议**:

```python
elif event_type == "item.completed":
    item = obj.get("item", {})
    if item.get("type") == "agent_message":
        # 尝试多个可能的字段名
        text = item.get("text") or item.get("content") or item.get("output") or ""
        if isinstance(text, list):
            # content 字段有时是 list[{type: text, text: ...}] 格式
            text = " ".join(
                part.get("text", "") for part in text if isinstance(part, dict)
            )
        if text:
            # 拼接所有 agent_message，而非只取最后一个
            result_texts.append(str(text))
```

并在函数开头改用 `result_texts = []`，最后 `result_text = "\n".join(result_texts)`。

---

### MEDIUM 问题

---

#### [CR-003] `_estimate_codex_cost()` 定价硬编码，与实际模型可能不符

**文件**: `src/maestro/tool_runner.py:713-726`

**问题描述**:

```python
def _estimate_codex_cost(self, input_tokens: int, output_tokens: int) -> float:
    input_price = 1.50 / 1_000_000    # $1.50/M tokens
    output_price = 6.00 / 1_000_000   # $6.00/M tokens
    return input_tokens * input_price + output_tokens * output_price
```

注释说明"使用保守定价"，但硬编码了单一价格，存在以下问题：

1. 这是 GPT-4o 级别的定价（接近 2024 年中的定价），Codex CLI 支持多个模型（o3、o4-mini、gpt-4.1 等），价格差异可能达 10 倍以上。
2. 用户无法通过配置覆盖价格，估算值可能严重失准（如使用 o4-mini 时高估费用，或使用 o3 时低估）。
3. 没有在日志/文档中注明这是估算值，用户可能误以为是精确费用。

与 `CodingToolConfig` 对比：该配置类没有 `input_price`/`output_price` 字段，说明这是有意的简化，但应至少让用户知道这是粗估。

**修复建议**:

在 `CodingToolConfig` 中添加可选价格字段：

```python
# config.py
@dataclass
class CodingToolConfig:
    ...
    # codex 模式：token 费用估算定价（$/M tokens，留空使用内置默认值）
    input_price_per_million: float = 1.50
    output_price_per_million: float = 6.00
```

并在 `_estimate_codex_cost` 中使用配置值，同时在日志中标明是估算：

```python
def _estimate_codex_cost(self, input_tokens: int, output_tokens: int) -> float:
    input_price = self.config.input_price_per_million / 1_000_000
    output_price = self.config.output_price_per_million / 1_000_000
    cost = input_tokens * input_price + output_tokens * output_price
    logger.debug(f"费用估算（{input_tokens} 输入 + {output_tokens} 输出 tokens）: ${cost:.6f}（估算值）")
    return cost
```

---

#### [CR-004] `_parse_codex_jsonl()` 中 `RunResult.session_id` 在恢复场景返回空字符串

**文件**: `src/maestro/tool_runner.py:700-708`

**问题描述**:

```python
# 更新会话 ID
self.session_id = session_id or self.session_id  # 保留上一轮的 session_id

return RunResult(
    output=result_text,
    session_id=session_id,    # 问题：session_id 可能为空字符串 ""
    ...
)
```

当恢复会话时（`self.session_id` 已有值），如果新一轮 JSONL 输出中没有 `thread.started` 事件（Codex CLI 在 resume 模式下可能复用现有 thread，不再产生 `thread.started`），则 `session_id` 局部变量为 `""`。

- `self.session_id` 被正确保留（`session_id or self.session_id`）
- 但 `RunResult.session_id` 返回 `""` 给 Orchestrator

在 `orchestrator.py:319` 中：

```python
tool_session_id=result.session_id,
```

Orchestrator 用 `result.session_id` 更新 state，如果这里是 `""`，则 state 中的 `tool_session_id` 被清空，checkpoint 保存的也是 `""`，导致崩溃恢复时丢失 session_id。

**修复建议**:

```python
# 返回时使用 self.session_id（已包含回退逻辑）
return RunResult(
    output=result_text,
    session_id=self.session_id,   # 而非局部变量 session_id
    cost_usd=cost_usd,
    duration_ms=duration_ms,
    is_error=is_error,
)
```

注意：Claude 模式（`_parse_stream_json` 第 470 行）存在相同的问题，但那里 session_id 在每次调用都会出现在 `init` 事件中，影响较小。

---

#### [CR-005] `turn.failed` 错误场景下 `is_error=True` 但进程可能返回 0，导致 stderr fallback 逻辑跳过

**文件**: `src/maestro/tool_runner.py:685-697`

**问题描述**:

```python
elif event_type == "turn.failed":
    is_error = True
    error_msg = obj.get("error", obj.get("message", ""))
    if error_msg:
        result_text = str(error_msg)

# 如果 JSONL 没有解析出任何有效输出，尝试 stderr 补充
if not result_text:
    stderr_text = "".join(stderr_lines).strip()
    if stderr_text:
        result_text = stderr_text
        is_error = True
```

当 `turn.failed` 事件的 `error`/`message` 字段为空（空对象、null、空字符串）时，`result_text` 保持为 `""`，但 `is_error` 已被设为 `True`。随后 stderr fallback 逻辑判断 `if not result_text` 为 True，会继续尝试 stderr。

但是，如果 stderr 也为空（Codex CLI 可能将错误信息仅写入 JSONL 而不写 stderr），最终 `result_text = ""`，Manager 收到空输出且 `is_error=True`。Manager 的 prompt 对这种空错误场景的处理需要健壮性。

另外，`turn.failed` 中 `error` 字段的实际结构不确定，可能是字符串，也可能是嵌套对象（`{"code": ..., "message": ...}`）。当前 `str(error_msg)` 对嵌套对象会产生 `{'code': ..., 'message': ...}` 这样的 Python dict 字符串，不友好。

**修复建议**:

```python
elif event_type == "turn.failed":
    is_error = True
    error_obj = obj.get("error", obj.get("message", ""))
    if isinstance(error_obj, dict):
        # 处理嵌套错误对象
        error_msg = error_obj.get("message") or error_obj.get("msg") or str(error_obj)
    else:
        error_msg = str(error_obj) if error_obj else ""
    if error_msg:
        result_text = f"[Codex 错误] {error_msg}"
    else:
        result_text = "[Codex 错误] turn.failed（无详细信息）"
```

---

### LOW 问题

---

#### [CR-006] `_run_codex()` 日志信息不包含完整命令，调试困难

**文件**: `src/maestro/tool_runner.py:536-537`

**问题描述**:

```python
logger.info(f"执行 Codex CLI（session={self.session_id or '新建'}）")
logger.debug(f"指令: {instruction[:100]}...")
```

Claude 模式（第175-176行）有相同日志格式，但都只输出指令前100字符，没有输出完整的 `cmd` 数组。在命令构建有 bug 时（如 CR-001 所描述），日志中看不到实际执行的命令，排查困难。

对比：`_run_generic` 第 743 行有 `logger.debug(f"完整命令: {' '.join(cmd[:5])}...")` 日志，但这也只取前5个参数，意义有限。

**修复建议**:

```python
logger.info(f"执行 Codex CLI（session={self.session_id or '新建'}）")
logger.debug(f"完整命令: {' '.join(str(x) for x in cmd)}")
logger.debug(f"指令前100字符: {instruction[:100]}...")
```

---

#### [CR-007] 模块顶部注释与代码行号不一致

**文件**: `src/maestro/tool_runner.py:5-6`

**问题描述**:

模块 docstring 第5行声明"Claude Code 专用模式"，但没有更新为三种模式并列的完整描述（代码已支持三种模式，但 docstring 格式稍显不整齐）。另外，第16行注释：

```
支持 `--full-auto`（自动批准）和 `codex exec resume <session_id>`（会话恢复）。
```

如果 CR-001 确认 resume 使用的是 `--resume` flag 而非子命令，这里的注释也需要同步修正。

**修复建议**: 在 CR-001 修复后同步更新模块注释。

---

#### [CR-008] `timed_out` 标记与实际 `_kill_process_group` 竞态

**文件**: `src/maestro/tool_runner.py:577-601`

**问题描述**:

```python
timed_out = False
try:
    for line in proc.stdout:
        ...
finally:
    timer.cancel()

try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    ...
    timed_out = True
```

`timed_out` 仅在 `proc.wait(timeout=10)` 超时时才置为 `True`，但实际上进程可能是被 `timer` 的 `_kill_process_group` 杀死的（Timer 触发）。这种情况下：

1. Timer 触发 → 进程被 SIGTERM/SIGKILL
2. stdout EOF → `for line in proc.stdout` 退出
3. `timer.cancel()` 返回（已触发的 timer cancel 无效，无害）
4. `proc.wait(timeout=10)` 立即返回（进程已死），不超时
5. `timed_out = False` — **但实际是超时导致的**

所以 `timed_out` 实际上永远不会为 `True`（在正常流程中），超时时也不会返回错误的 `RunResult`。而 Timer 触发的情况会走到 `_parse_codex_jsonl`，此时 stdout 可能只有部分输出。

这是 Claude 模式和 Generic 模式共同存在的逻辑问题，Codex 新增代码完整复制了这一逻辑。

**修复建议（初步）**:

在 `_run_with_timeout` 中增加 `_timed_out` 标记回调，或通过检查进程 returncode（Timer kill 会产生负值 returncode）来判断是否超时：

```python
# Timer kill 产生负 returncode（SIGTERM=-15, SIGKILL=-9）
# 且 _aborted 为 False（如果是 abort，_aborted 为 True）
if proc.returncode is not None and proc.returncode < 0 and not self._aborted:
    # 大概率是 Timer 超时导致的 kill
    ...
```

注意：这不是 Codex 新增引入的问题，Codex 代码与 Claude 代码保持了一致性。作为信息提示记录，后续统一修复。

---

### INFO 信息

---

#### [CR-009] `_run_codex` 与 `_run_claude` 代码高度重复，可提取为公共方法

**文件**: `src/maestro/tool_runner.py:515-632`

**说明**:

`_run_codex` 和 `_run_claude` 在以下部分完全相同：
- Popen 创建（参数完全一致，除 cmd 外）
- stderr 后台线程
- stdout 逐行读取
- Timer 超时处理
- `proc.wait(timeout=10)` 兜底
- `self._proc = None` 清理

唯一差异在于 cmd 构建和最终解析函数（`_parse_stream_json` vs `_parse_codex_jsonl`）。

这种重复在第三种模式（如未来的 Gemini 专用模式）时会加剧。建议将公共部分提取为 `_run_popen_streaming(cmd, parse_fn, tool_name)` 内部方法。

这是设计改进建议，不影响当前正确性，可在后续重构中考虑。

---

#### [CR-010] `_parse_codex_jsonl` 未记录 JSONL 协议版本/来源

**文件**: `src/maestro/tool_runner.py:634-711`

**说明**:

函数 docstring 中的 JSONL 格式示例（`thread.started`、`item.completed`、`turn.completed`）来源未标注（是否来自官方文档、实测还是推测？版本号是多少？）。Codex CLI 尚在快速迭代中，接口可能变化。建议在注释中标注：

```
# Codex CLI JSONL 协议参考：https://... （实测版本：x.y.z，日期：2025-xx）
```

---

## 修复优先级建议

### 必须修复（影响功能正确性）

1. **[CR-001]** 确认 `codex exec resume` 命令格式，修正 session_id 的传参方式（子命令 vs flag）
2. **[CR-002]** 验证 `agent_message` 输出字段名，考虑累积所有 agent_message 而非只取最后一个
3. **[CR-004]** 修正 `RunResult.session_id` 在 resume 场景下返回空字符串的问题

### 建议修复（影响可维护性和用户体验）

4. **[CR-005]** 改善 `turn.failed` 错误对象的解析和错误消息格式
5. **[CR-003]** 将定价参数提升至配置，或至少在日志中标明为估算值
6. **[CR-006]** 在 debug 日志中输出完整命令

### 可延后处理

7. **[CR-007]** 同步更新模块注释（依赖 CR-001 结论）
8. **[CR-008]** 统一修复三种模式的 `timed_out` 标记逻辑
9. **[CR-009]** 公共方法提取重构
10. **[CR-010]** 补充协议版本注释

---

## 整体评估

**REQUEST CHANGES**

Codex CLI 支持代码整体结构良好，与现有 Claude 模式保持了很强的一致性：
- 正确复用了 `_run_with_timeout`、`_kill_process_group`、`_emit_event`、`_read_stream` 等基础设施
- Popen 参数、preexec_fn 进程组创建、stderr 后台线程等关键细节与 Claude 模式一致
- JSONL 解析框架清晰，事件驱动的分支逻辑可读性好
- `resume_session()` 的 codex 支持正确添加

但 **[CR-001]**（命令格式错误）和 **[CR-002]**（输出提取字段名未验证）是功能正确性问题，在 Codex CLI 实际运行时极可能导致会话无法恢复、输出为空。这两个 HIGH 问题需要通过真实 Codex CLI 实测验证后修复，才可以合并此功能。

---

## 下游摘要

### 整体评估
REQUEST CHANGES

### 未修复问题
#### Critical
无

#### High
- [CR-001] `_run_codex` 第 533 行：`resume` 子命令格式未验证，可能导致 session 恢复完全失败
- [CR-002] `_parse_codex_jsonl` 第 675-678 行：`agent_message.text` 字段名未经实测，输出可能始终为空

#### Medium
- [CR-003] `_estimate_codex_cost`：定价硬编码且不可配置，估算可能严重失准
- [CR-004] `_parse_codex_jsonl` 第 707 行：`RunResult.session_id` 在 resume 场景返回 `""`，破坏 checkpoint 恢复链
- [CR-005] `_parse_codex_jsonl` 第 685-690 行：`turn.failed` 的错误对象解析过于简单，可能产生不友好输出

### 修复建议
最高优先级：
1. 用真实 Codex CLI 实测 `codex exec resume` 的命令格式，并修正第 533 行
2. 用真实 Codex CLI 实测 `agent_message` 的输出字段名（`text`/`content`/`output`），修正第 675 行
3. 将第 707 行 `session_id=session_id` 改为 `session_id=self.session_id`（一行修复）
