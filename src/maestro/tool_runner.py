"""
编码工具运行器模块

支持三种模式：
  - claude: Claude Code 专用模式（Popen + stream-json 流式读取，自动 fallback 到 json）
  - codex: OpenAI Codex CLI 专用模式（Popen + JSONL 事件流读取，会话恢复，费用估算）
  - generic: 通用 subprocess 包装（适配 Gemini CLI、Aider 等任何 CLI 工具）

generic 模式的约定：
  command + extra_args + instruction 拼成完整命令。
  工具的 stdout+stderr 作为输出传给 Manager Agent 分析。
  不支持费用追踪和会话恢复。

codex 模式说明：
  使用 `codex exec --json` 非交互模式，输出为 JSONL 事件流（每行一个 JSON 对象）。
  支持 `--full-auto`（自动批准）和 `codex exec resume <session_id>`（会话恢复）。
  从 JSONL 事件中提取 session_id（thread.started）、输出文本（item.completed/agent_message）、
  token 用量（turn.completed/usage）用于费用估算。

流式读取说明：
  使用 subprocess.Popen + preexec_fn=os.setsid 创建进程组，支持整组 kill。
  stdout 逐行读取，每行触发 on_event 回调；stderr 在后台线程读取防止 pipe 死锁。
  超时通过 threading.Timer 实现，是唯一的超时机制。
"""

import json
import os
import signal
import threading
import time
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable

from maestro.config import CodingToolConfig

logger = logging.getLogger(__name__)


# ─────────────────────────── ToolEvent 事件类型常量 ───────────────────────────

EVENT_TOOL_STARTED = "tool_started"
EVENT_TOOL_OUTPUT_CHUNK = "tool_output_chunk"
EVENT_TOOL_COMPLETED = "tool_completed"
EVENT_MANAGER_DECIDING = "manager_deciding"
EVENT_MANAGER_DECIDED = "manager_decided"
EVENT_BREAKER_WARNING = "breaker_warning"
EVENT_ERROR = "error"


# ─────────────────────────── 数据模型 ─────────────────────────────────────────

@dataclass
class ToolEvent:
    """编码工具统一事件"""
    type: str        # 事件类型（见上方 EVENT_* 常量）
    timestamp: str   # ISO 格式时间戳
    turn: int        # 所属轮次（由 Orchestrator 在回调中填入）
    data: dict       # 类型特定载荷


def tool_event_to_dict(event: ToolEvent) -> dict:
    """序列化 ToolEvent 为可 JSON 化的字典"""
    return {
        "type": event.type,
        "timestamp": event.timestamp,
        "turn": event.turn,
        "data": event.data,
    }


@dataclass
class RunResult:
    """单轮执行结果"""
    output: str                                           # 工具输出文本（完整拼接后）
    session_id: str = ""                                  # 会话 ID（Claude / Codex 有）
    cost_usd: float = 0.0                                 # 本轮费用（Claude 直接提供 / Codex 估算）
    duration_ms: int = 0                                  # 本轮耗时（毫秒）
    is_error: bool = False                                # 是否出错
    error_type: str = ""                                  # 错误类型
    events: list = field(default_factory=list)            # 本轮 ToolEvent 列表


# ─────────────────────────── ToolRunner ──────────────────────────────────────

class ToolRunner:
    """
    编码工具运行器

    type=claude 时使用 Claude Code 的 stream-json 流式模式（自动 fallback 到 json）。
    type=codex 时使用 Codex CLI 的 JSONL 事件流模式（会话恢复 + 费用估算）。
    type=generic 时作为通用 subprocess 包装（适配任何 CLI 工具）。
    """

    def __init__(self, config: CodingToolConfig, working_dir: str):
        self.config = config
        self.working_dir = working_dir
        self.session_id: Optional[str] = None

        # 进程管理状态
        self._proc: Optional[subprocess.Popen] = None   # 当前运行的子进程
        self._collected_events: list = []               # 本轮收集的 ToolEvent
        self._aborted: bool = False                     # 是否已被外部 abort
        self._kill_lock = threading.Lock()              # 防止 Timer 和 abort 并发 kill
        self._use_json_fallback: bool = False           # 缓存 stream-json 不可用状态

    # ─────────────────────────── 公有接口 ─────────────────────────────────────

    def run(self, instruction: str, on_event: Optional[Callable] = None) -> RunResult:
        """
        执行一轮指令，返回结果

        参数:
          instruction: 发送给编码工具的指令文本
          on_event: 可选回调 Callable[[ToolEvent], None]
                    每产生一个事件立即调用，用于实时写入 events.jsonl
        """
        # 每轮开始时重置 abort 标记，防止上一轮残留状态干扰
        self._aborted = False
        if self.config.type == "claude":
            return self._run_claude(instruction, on_event)
        elif self.config.type == "codex":
            return self._run_codex(instruction, on_event)
        else:
            return self._run_generic(instruction, on_event)

    def resume_session(self, session_id: str):
        """恢复到指定会话（Claude 和 Codex 模式有效）"""
        if self.config.type in ("claude", "codex"):
            self.session_id = session_id

    def abort(self):
        """外部调用：立即终止当前子进程（线程安全）"""
        self._aborted = True
        proc = self._proc
        if proc:
            # 直接委托 _kill_process_group，其内部在锁内做 poll() 检查
            # 避免在锁外调用 poll() 产生的 TOCTOU 竞态
            self._kill_process_group(proc)

    def consume_abort(self) -> bool:
        """检查并重置 abort 标记，返回之前的 abort 状态（供 Orchestrator 查询）"""
        was = self._aborted
        self._aborted = False
        return was

    # ─────────────────────────── Claude 模式 ──────────────────────────────────

    def _run_claude(self, instruction: str, on_event: Optional[Callable] = None) -> RunResult:
        """
        Claude Code 专用：Popen + stream-json 流式读取

        流程：
          1. 重置本轮事件列表
          2. 如已缓存 fallback 标记，直接走 json 模式
          3. 否则尝试 stream-json 模式
          4. 如检测到 stream-json 不可用，自动 fallback 到 json 模式并缓存标记
        """
        # [重要] 每次调用重置事件列表，防止跨轮次事件累积
        self._collected_events = []

        # 如果之前已检测到 stream-json 不可用，直接走 json fallback
        if self._use_json_fallback:
            return self._run_claude_json_fallback(instruction, on_event)

        cmd = [self.config.command, "-p", "--output-format", "stream-json"]
        if self.config.auto_approve:
            cmd.append("--dangerously-skip-permissions")
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        cmd.append(instruction)

        logger.info(f"执行 Claude Code stream-json 模式（session={self.session_id or '新建'}）")
        logger.debug(f"指令: {instruction[:100]}...")

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_dir,
                preexec_fn=os.setsid,   # 创建新进程组，便于整组 kill
            )
        except FileNotFoundError:
            logger.error(f"找不到命令: {self.config.command}")
            result = RunResult(
                output=f"[错误] 找不到命令: {self.config.command}，请确认 Claude Code 已安装",
                is_error=True,
                error_type="command_not_found",
            )
            result.events = self._collected_events
            return result

        self._proc = proc   # 保存引用，供 abort() 使用

        # 启动超时 Timer（唯一的超时机制）
        timer = self._run_with_timeout(proc, self.config.timeout)

        # 发出 tool_started 事件
        self._emit_event(on_event, EVENT_TOOL_STARTED, {"command": "claude"})

        # 启动 stderr 后台线程（防止 pipe 死锁）
        stderr_lines = []
        stderr_thread = threading.Thread(
            target=self._read_stream, args=(proc.stderr, stderr_lines)
        )
        stderr_thread.daemon = True
        stderr_thread.start()

        # 主线程逐行读取 stdout
        stdout_lines = []
        timed_out = False
        try:
            for line in proc.stdout:
                stdout_lines.append(line)
                self._emit_chunk_event(on_event, line)
        except Exception as e:
            logger.warning(f"读取 Claude stdout 异常: {e}")
        finally:
            # stdout 读完后取消 Timer（进程可能正常结束或已被 Timer kill）
            timer.cancel()

        # 等待进程退出（仅收集 exit status，不做超时控制）
        # 此时进程已退出（stdout EOF）或已被 Timer kill，wait() 应立即返回
        try:
            proc.wait(timeout=10)   # 10 秒宽限，正常情况下立即返回
        except subprocess.TimeoutExpired:
            # 极端情况：stdout 关闭但进程仍活着，强制 kill
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            timed_out = True

        # 等待 stderr 线程完成（进程退出后 stderr EOF，线程应很快结束）
        stderr_thread.join(timeout=5)

        self._proc = None   # 清理进程引用

        duration_ms = int((time.time() - start) * 1000)

        if timed_out:
            self._emit_event(on_event, EVENT_ERROR, {"reason": "timeout"})
            result = RunResult(
                output="[超时] 编码工具执行超时",
                duration_ms=duration_ms,
                is_error=True,
                error_type="timeout",
            )
            result.events = self._collected_events
            return result

        # ── fallback 检测 ──
        # 如果 stream-json 不可用，进程会在极短时间内以非零码退出
        if self._should_fallback_to_json(proc, stdout_lines, stderr_lines, duration_ms):
            self._use_json_fallback = True   # 缓存 fallback 标记，后续轮次直接走 json
            # skip_tool_started=True: 上方已发过 tool_started，避免磁盘重复
            return self._run_claude_json_fallback(instruction, on_event, skip_tool_started=True)

        # 解析 stream-json 输出
        result = self._parse_stream_json(stdout_lines, stderr_lines, duration_ms)

        # 发出 tool_completed 事件
        self._emit_event(on_event, EVENT_TOOL_COMPLETED, {
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "is_error": result.is_error,
        })

        result.events = self._collected_events
        return result

    def _run_claude_json_fallback(
        self, instruction: str, on_event: Optional[Callable] = None,
        skip_tool_started: bool = False,
    ) -> RunResult:
        """
        Fallback 模式：使用 --output-format json 重新执行

        清空首次尝试产生的事件，避免污染本轮结果。
        仍用 Popen 流式读取，等 stdout 全部读完后一次性解析 JSON。

        参数:
          skip_tool_started: 为 True 时不发 tool_started 事件（从 stream-json 回退时
                             已发过一次，避免磁盘上产生重复事件）
        """
        # [重要] 清理上一次尝试的事件，避免污染
        self._collected_events = []

        cmd = [self.config.command, "-p", "--output-format", "json"]
        if self.config.auto_approve:
            cmd.append("--dangerously-skip-permissions")
        if self.session_id:
            cmd.extend(["--resume", self.session_id])
        cmd.append(instruction)

        logger.info(f"Claude Code json fallback 模式（session={self.session_id or '新建'}）")

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_dir,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError:
            logger.error(f"找不到命令: {self.config.command}")
            result = RunResult(
                output=f"[错误] 找不到命令: {self.config.command}，请确认 Claude Code 已安装",
                is_error=True,
                error_type="command_not_found",
            )
            result.events = self._collected_events
            return result

        self._proc = proc

        # 启动超时 Timer
        timer = self._run_with_timeout(proc, self.config.timeout)

        # 发出 tool_started 事件（从 stream-json 回退时已发过，跳过避免重复）
        if not skip_tool_started:
            self._emit_event(on_event, EVENT_TOOL_STARTED, {"command": "claude"})

        # stderr 后台线程
        stderr_lines = []
        stderr_thread = threading.Thread(
            target=self._read_stream, args=(proc.stderr, stderr_lines)
        )
        stderr_thread.daemon = True
        stderr_thread.start()

        # stdout 全量读取（json 模式输出单行大 JSON）
        stdout_lines = []
        timed_out = False
        try:
            for line in proc.stdout:
                stdout_lines.append(line)
                self._emit_chunk_event(on_event, line)
        except Exception as e:
            logger.warning(f"读取 Claude json fallback stdout 异常: {e}")
        finally:
            timer.cancel()

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            timed_out = True

        stderr_thread.join(timeout=5)
        self._proc = None

        duration_ms = int((time.time() - start) * 1000)

        if timed_out:
            self._emit_event(on_event, EVENT_ERROR, {"reason": "timeout"})
            result = RunResult(
                output="[超时] 编码工具执行超时（json fallback 模式）",
                duration_ms=duration_ms,
                is_error=True,
                error_type="timeout",
            )
            result.events = self._collected_events
            return result

        # 解析 json 格式输出（单行完整 JSON）
        raw_output = "".join(stdout_lines)
        stderr_output = "".join(stderr_lines)

        try:
            data = json.loads(raw_output)
            self.session_id = data.get("session_id", self.session_id)
            result = RunResult(
                output=data.get("result", ""),
                session_id=data.get("session_id", ""),
                cost_usd=data.get("cost_usd", 0.0),
                duration_ms=duration_ms,
                is_error=data.get("is_error", False),
                error_type=data.get("subtype", ""),
            )
        except json.JSONDecodeError:
            # JSON 解析失败，降级为纯文本
            logger.warning("Claude Code json fallback 输出非 JSON，降级为纯文本模式")
            output = raw_output
            if stderr_output:
                output += "\n" + stderr_output
            result = RunResult(
                output=output,
                duration_ms=duration_ms,
                is_error=proc.returncode != 0,
            )

        self._emit_event(on_event, EVENT_TOOL_COMPLETED, {
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "is_error": result.is_error,
        })

        result.events = self._collected_events
        return result

    def _parse_stream_json(
        self, stdout_lines: list, stderr_lines: list, duration_ms: int
    ) -> RunResult:
        """
        从 stream-json 行中提取 RunResult

        Claude Code stream-json 格式（每行一个 JSON 对象）：
          {"type": "system", "subtype": "init", "session_id": "xxx", ...}
          {"type": "assistant", "message": {"content": [...]}, ...}
          {"type": "result", "subtype": "success", "result": "最终输出",
           "cost_usd": 0.12, "session_id": "xxx", ...}
        """
        session_id = ""
        cost_usd = 0.0
        result_text = ""
        is_error = False

        for line in stdout_lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = obj.get("type", "")
            if event_type == "system" and obj.get("subtype") == "init":
                session_id = obj.get("session_id", session_id)
            elif event_type == "result":
                result_text = obj.get("result", "")
                cost_usd = obj.get("cost_usd", 0.0)
                session_id = obj.get("session_id", session_id)
                is_error = obj.get("is_error", False)

        # 如果 stream-json 没有解析出任何有效输出，尝试 stderr 补充
        if not result_text:
            stderr_text = "".join(stderr_lines).strip()
            if stderr_text:
                result_text = stderr_text
                is_error = True

        # 更新会话 ID
        self.session_id = session_id or self.session_id

        return RunResult(
            output=result_text,
            session_id=session_id,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            is_error=is_error,
        )

    def _should_fallback_to_json(
        self,
        proc: subprocess.Popen,
        stdout_lines: list,
        stderr_lines: list,
        duration_ms: int,
    ) -> bool:
        """
        判断是否需要 fallback 到 --output-format json

        三个条件同时满足才 fallback：
          1. 进程非零退出
          2. 执行时间极短（< 5 秒），说明是启动阶段就失败了
          3. stderr 包含格式相关的错误关键词
        """
        # 条件 1：进程非零退出（排除信号 kill 导致的负 returncode，
        # 如 SIGTERM=-15、SIGKILL=-9，这些是超时/abort 造成的，不应 fallback）
        if proc.returncode is None or proc.returncode == 0 or proc.returncode < 0:
            return False
        # 条件 2：执行时间极短，排除真正的任务执行失败
        if duration_ms > 5000:
            return False
        # 条件 3：stderr 含格式相关关键词
        stderr_text = "".join(stderr_lines).lower()
        fallback_keywords = [
            "unknown format",
            "invalid format",
            "stream-json",
            "unsupported",
            "unrecognized option",
        ]
        if not any(kw in stderr_text for kw in fallback_keywords):
            return False

        logger.warning("stream-json 不可用，fallback 到 json 模式（后续轮次直接走 json）")
        return True

    # ─────────────────────────── Codex 模式 ───────────────────────────────────

    def _run_codex(self, instruction: str, on_event: Optional[Callable] = None) -> RunResult:
        """
        Codex CLI 专用：Popen + JSONL 事件流读取

        流程：
          1. 重置本轮事件列表
          2. 构建命令：codex exec --json [--full-auto] [resume <session_id>] "<instruction>"
          3. Popen 启动子进程
          4. 流式读取 stdout（JSONL 格式，每行一个 JSON 事件）
          5. 解析 JSONL 事件，提取 session_id、输出文本、token 用量
        """
        # [重要] 每次调用重置事件列表，防止跨轮次事件累积
        self._collected_events = []

        cmd = [self.config.command, "exec", "--json"]
        if self.config.auto_approve:
            cmd.append("--full-auto")
        # Codex CLI 专用参数
        if self.config.sandbox:
            cmd.extend(["--sandbox", self.config.sandbox])
        if self.config.model:
            cmd.extend(["--model", self.config.model])
        if self.config.skip_git_check:
            cmd.append("--skip-git-check")
        if self.session_id:
            cmd.extend(["resume", self.session_id])
        cmd.append(instruction)

        logger.info(f"执行 Codex CLI（session={self.session_id or '新建'}）")
        logger.debug(f"指令: {instruction[:100]}...")

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_dir,
                preexec_fn=os.setsid,   # 创建新进程组，便于整组 kill
            )
        except FileNotFoundError:
            logger.error(f"找不到命令: {self.config.command}")
            result = RunResult(
                output=f"[错误] 找不到命令: {self.config.command}，请确认 Codex CLI 已安装",
                is_error=True,
                error_type="command_not_found",
            )
            result.events = self._collected_events
            return result

        self._proc = proc   # 保存引用，供 abort() 使用

        # 启动超时 Timer（唯一的超时机制）
        timer = self._run_with_timeout(proc, self.config.timeout)

        # 发出 tool_started 事件
        self._emit_event(on_event, EVENT_TOOL_STARTED, {"command": "codex"})

        # 启动 stderr 后台线程（防止 pipe 死锁）
        stderr_lines = []
        stderr_thread = threading.Thread(
            target=self._read_stream, args=(proc.stderr, stderr_lines)
        )
        stderr_thread.daemon = True
        stderr_thread.start()

        # 主线程逐行读取 stdout（JSONL 格式）
        stdout_lines = []
        timed_out = False
        try:
            for line in proc.stdout:
                stdout_lines.append(line)
                self._emit_chunk_event(on_event, line)
        except Exception as e:
            logger.warning(f"读取 Codex stdout 异常: {e}")
        finally:
            # stdout 读完后取消 Timer（进程可能正常结束或已被 Timer kill）
            timer.cancel()

        # 等待进程退出
        try:
            proc.wait(timeout=10)   # 10 秒宽限，正常情况下立即返回
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            timed_out = True

        # 等待 stderr 线程完成
        stderr_thread.join(timeout=5)

        self._proc = None   # 清理进程引用

        duration_ms = int((time.time() - start) * 1000)

        if timed_out:
            self._emit_event(on_event, EVENT_ERROR, {"reason": "timeout"})
            result = RunResult(
                output="[超时] Codex CLI 执行超时",
                duration_ms=duration_ms,
                is_error=True,
                error_type="timeout",
            )
            result.events = self._collected_events
            return result

        # 解析 JSONL 输出
        result = self._parse_codex_jsonl(stdout_lines, stderr_lines, duration_ms)

        # 发出 tool_completed 事件
        self._emit_event(on_event, EVENT_TOOL_COMPLETED, {
            "duration_ms": result.duration_ms,
            "cost_usd": result.cost_usd,
            "is_error": result.is_error,
        })

        result.events = self._collected_events
        return result

    def _parse_codex_jsonl(
        self, stdout_lines: list, stderr_lines: list, duration_ms: int
    ) -> RunResult:
        """
        从 Codex CLI JSONL 事件流中提取 RunResult

        Codex CLI --json 输出格式（每行一个 JSON 对象）：
          {"type":"thread.started","thread_id":"0199a213-..."}
          {"type":"turn.started"}
          {"type":"item.started","item":{"id":"item_1","type":"command_execution",...}}
          {"type":"item.completed","item":{"id":"item_3","type":"agent_message","text":"..."}}
          {"type":"turn.completed","usage":{"input_tokens":24763,"output_tokens":122,...}}

        解析策略：
          - thread.started → 提取 session_id（thread_id）
          - item.completed + type=agent_message → 提取输出文本（取最后一个非空 text）
          - turn.completed → 累加 token 用量（用于费用估算）
          - turn.failed → 标记错误
        """
        session_id = ""
        result_text = ""
        is_error = False
        input_tokens = 0
        output_tokens = 0

        for line in stdout_lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = obj.get("type", "")

            if event_type == "thread.started":
                session_id = obj.get("thread_id", session_id)

            elif event_type == "item.completed":
                item = obj.get("item", {})
                if item.get("type") == "agent_message":
                    text = item.get("text", "")
                    if text:
                        result_text = text   # 取最后一个非空 agent_message

            elif event_type == "turn.completed":
                usage = obj.get("usage", {})
                input_tokens += usage.get("input_tokens", 0)
                output_tokens += usage.get("output_tokens", 0)

            elif event_type == "turn.failed":
                is_error = True
                # 提取错误信息作为 output（error 可能是字符串或嵌套 dict）
                error_msg = obj.get("error", obj.get("message", ""))
                if error_msg:
                    if isinstance(error_msg, dict):
                        result_text = json.dumps(error_msg, ensure_ascii=False)
                    else:
                        result_text = str(error_msg)

        # 如果 JSONL 没有解析出任何有效输出，尝试 stderr 补充
        if not result_text:
            stderr_text = "".join(stderr_lines).strip()
            if stderr_text:
                result_text = stderr_text
                is_error = True

        # 更新会话 ID
        self.session_id = session_id or self.session_id

        # 费用估算（Codex CLI 不直接提供 cost_usd，通过 token 计数估算）
        cost_usd = self._estimate_codex_cost(input_tokens, output_tokens)

        return RunResult(
            output=result_text,
            session_id=self.session_id,
            cost_usd=cost_usd,
            duration_ms=duration_ms,
            is_error=is_error,
        )

    # Codex 模型定价（$/M tokens: [input, output]）
    _CODEX_PRICING = {
        "codex-mini-latest": (1.50, 6.00),
        "codex-mini":        (1.50, 6.00),
        "o3":                (2.00, 8.00),
        "o4-mini":           (1.10, 4.40),
    }
    _CODEX_DEFAULT_PRICING = (1.50, 6.00)   # 未知模型使用保守定价

    def _estimate_codex_cost(self, input_tokens: int, output_tokens: int) -> float:
        """
        基于 token 计数和模型名估算 Codex CLI 费用

        Codex CLI 不直接输出 cost_usd，通过 turn.completed 事件中的
        usage.input_tokens 和 usage.output_tokens 进行粗略估算。

        定价根据 config.model 查表，未知模型使用保守定价（codex-mini-latest 费率）。
        """
        model = self.config.model or ''
        price_in, price_out = self._CODEX_PRICING.get(model, self._CODEX_DEFAULT_PRICING)
        if model and model not in self._CODEX_PRICING:
            logger.debug(f"Codex 模型 '{model}' 无定价数据，使用默认费率估算")
        return input_tokens * price_in / 1_000_000 + output_tokens * price_out / 1_000_000

    # ─────────────────────────── Generic 模式 ─────────────────────────────────

    def _run_generic(self, instruction: str, on_event: Optional[Callable] = None) -> RunResult:
        """
        通用模式：Popen 流式读取，适配任何 CLI 工具

        stdout + stderr 合并后传给 Manager Agent 分析。
        不支持费用追踪和会话恢复。
        """
        # [重要] 每次调用重置事件列表
        self._collected_events = []

        cmd = [self.config.command] + self.config.extra_args + [instruction]

        logger.info(f"执行编码工具: {self.config.command}")
        logger.debug(f"完整命令: {' '.join(cmd[:5])}...")

        start = time.time()
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.working_dir,
                preexec_fn=os.setsid,
            )
        except FileNotFoundError:
            logger.error(f"找不到命令: {self.config.command}")
            result = RunResult(
                output=f"[错误] 找不到命令: {self.config.command}",
                is_error=True,
                error_type="command_not_found",
            )
            result.events = self._collected_events
            return result

        self._proc = proc

        # 启动超时 Timer
        timer = self._run_with_timeout(proc, self.config.timeout)

        # 发出 tool_started 事件
        self._emit_event(on_event, EVENT_TOOL_STARTED, {"command": self.config.command})

        # stderr 后台线程
        stderr_lines = []
        stderr_thread = threading.Thread(
            target=self._read_stream, args=(proc.stderr, stderr_lines)
        )
        stderr_thread.daemon = True
        stderr_thread.start()

        # stdout 逐行读取
        stdout_lines = []
        timed_out = False
        try:
            for line in proc.stdout:
                stdout_lines.append(line)
                self._emit_chunk_event(on_event, line)
        except Exception as e:
            logger.warning(f"读取 generic stdout 异常: {e}")
        finally:
            timer.cancel()

        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                pgid = os.getpgid(proc.pid)
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            timed_out = True

        stderr_thread.join(timeout=5)
        self._proc = None

        duration_ms = int((time.time() - start) * 1000)

        if timed_out:
            self._emit_event(on_event, EVENT_ERROR, {"reason": "timeout"})
            result = RunResult(
                output=f"[错误] 编码工具执行超时 ({self.config.timeout}s)",
                duration_ms=duration_ms,
                is_error=True,
                error_type="timeout",
            )
            result.events = self._collected_events
            return result

        output = "".join(stdout_lines)
        stderr_output = "".join(stderr_lines)
        if stderr_output:
            output += "\n" + stderr_output

        result = RunResult(
            output=output,
            duration_ms=duration_ms,
            is_error=proc.returncode != 0,
        )

        self._emit_event(on_event, EVENT_TOOL_COMPLETED, {
            "duration_ms": duration_ms,
            "is_error": result.is_error,
        })

        result.events = self._collected_events
        return result

    # ─────────────────────────── 辅助方法 ─────────────────────────────────────

    def _read_stream(self, stream, lines_list: list):
        """在后台线程中逐行读取 stream，防止 pipe 死锁"""
        try:
            for line in stream:
                lines_list.append(line)
        except (ValueError, OSError):
            pass   # pipe 关闭时的正常异常

    def _emit_event(self, on_event: Optional[Callable], event_type: str, data: dict):
        """
        发出一个 ToolEvent

        turn 字段的处理策略：
        - ToolRunner 不感知 turn（属于 Orchestrator 概念），初始设为 0（占位值）
        - 当 on_event 回调存在时，Orchestrator 在回调中设置正确的 turn 值
        - 当 on_event 为 None 时，Orchestrator 在 run() 返回后遍历 result.events 统一设置 turn
        """
        event = ToolEvent(
            type=event_type,
            timestamp=datetime.now().isoformat(),
            turn=0,   # 占位值，由 Orchestrator 设置正确的 turn
            data=data,
        )
        self._collected_events.append(event)
        if on_event:
            on_event(event)

    def _emit_chunk_event(self, on_event: Optional[Callable], line: str):
        """发出 output_chunk 事件（截断保护，最多 2000 字符）"""
        chunk = line.rstrip("\n")
        if len(chunk) > 2000:
            chunk = chunk[:2000]
        self._emit_event(on_event, EVENT_TOOL_OUTPUT_CHUNK, {"text": chunk})

    def _run_with_timeout(self, proc: subprocess.Popen, timeout: int) -> threading.Timer:
        """
        启动超时监控 Timer

        Timer 是唯一的超时机制。timeout 秒后调用 _kill_process_group。
        主线程在 stdout 读完后调用 timer.cancel() 取消 Timer。
        """
        timer = threading.Timer(timeout, self._kill_process_group, args=[proc])
        timer.daemon = True
        timer.start()
        return timer

    def _kill_process_group(self, proc: subprocess.Popen):
        """
        超时/abort 时杀死进程组（两阶段：SIGTERM → SIGKILL）

        线程安全：使用 _kill_lock 防止 Timer 线程和 abort() 并发调用。
        """
        with self._kill_lock:
            try:
                # 先检查进程是否还活着，避免对已退出进程操作
                if proc.poll() is not None:
                    return
                pgid = os.getpgid(proc.pid)
                logger.info(f"发送 SIGTERM 到进程组 {pgid}")
                os.killpg(pgid, signal.SIGTERM)
                # 给进程 5 秒优雅退出时间
                try:
                    proc.wait(timeout=5)
                    logger.info(f"进程组 {pgid} 已优雅退出")
                except subprocess.TimeoutExpired:
                    # 5 秒内未退出，强制 SIGKILL
                    try:
                        logger.warning(f"进程组 {pgid} 未响应 SIGTERM，发送 SIGKILL")
                        os.killpg(pgid, signal.SIGKILL)
                    except (ProcessLookupError, OSError):
                        pass   # SIGTERM 后进程可能已退出
            except (ProcessLookupError, OSError):
                pass   # 进程已退出，忽略
