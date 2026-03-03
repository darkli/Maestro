"""
状态管理模块

包含：
  - TaskStatus: 任务状态枚举
  - 状态转换验证
  - CircuitBreaker: 熔断器（死循环检测 + 资源超限）
  - atomic_write_json: 原子写入工具函数
"""

import os
import re
import json
import hashlib
from difflib import SequenceMatcher
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

from maestro.config import SafetyConfig

# 费用超限熔断消息前缀（供 Orchestrator 判定熔断类型，避免硬编码中文匹配）
BREAKER_BUDGET_PREFIX = "费用超限"


# ============================================================
# 状态枚举与转换规则
# ============================================================

class TaskStatus(str, Enum):
    """任务状态枚举"""
    PENDING = "pending"              # 已创建，等待启动
    EXECUTING = "executing"          # 执行中
    WAITING_USER = "waiting_user"    # 等待用户回复
    COMPLETED = "completed"          # 正常完成
    FAILED = "failed"                # 失败（熔断/鉴权/超预算）
    ABORTED = "aborted"              # 用户手动终止


class FailReason(str, Enum):
    """失败原因分类（用于展示层差异化）"""
    ASK_USER_TIMEOUT = "ask_user_timeout"
    MAX_TURNS = "max_turns"
    BREAKER_TRIPPED = "breaker_tripped"
    BLOCKED = "blocked"
    WORKER_CRASHED = "worker_crashed"
    RUNTIME_ERROR = "runtime_error"


# 合法状态转换
VALID_TRANSITIONS: dict[str, list[str]] = {
    "pending":      ["executing"],
    "executing":    ["waiting_user", "completed", "failed", "aborted"],
    "waiting_user": ["executing", "failed", "aborted"],
    "completed":    [],                       # 终态
    "failed":       ["pending"],              # resume 可回到 pending
    "aborted":      [],                       # 终态
}


def validate_transition(current: str, target: str) -> bool:
    """验证状态转换是否合法"""
    allowed = VALID_TRANSITIONS.get(current, [])
    return target in allowed


# ============================================================
# 熔断器
# ============================================================

@dataclass
class CircuitBreaker:
    """
    熔断器：检测死循环和资源超限

    七个维度：
    1. 轮数上限 (max_turns)
    2. 费用上限 (max_budget_usd)
    3. 连续完全相同指令 (max_consecutive_similar) — hash 完全一致
    4. 指令语义相似度 (similarity_threshold) — SequenceMatcher 相邻对比
    5. 相同错误重复 (max_consecutive_errors) — 错误段 hash 连续相同
    6. 输出停滞 (stagnation_threshold) — 尾部指纹相邻对比
    7. action 震荡 (oscillation_window) — ABABAB 周期模式
    """
    max_turns: int = 30
    max_budget_usd: float = 5.0
    max_consecutive_similar: int = 3

    # [新增] 多维度检测配置
    similarity_threshold: float = 0.85      # 指令语义相似度阈值
    stagnation_threshold: float = 0.9       # 输出停滞相似度阈值
    max_consecutive_errors: int = 3         # 连续相同错误上限
    oscillation_window: int = 6             # 震荡检测窗口大小

    # 运行时状态
    _instruction_hashes: list = field(default_factory=list)
    _total_cost: float = 0.0
    _current_turn: int = 0

    # [新增] 运行时状态
    _instruction_texts: list = field(default_factory=list)    # 归一化后的指令文本
    _error_hashes: list = field(default_factory=list)         # 错误输出 hash（None 表示无错误轮次）
    _output_fingerprints: list = field(default_factory=list)  # 输出指纹（尾部 1000 字符）
    _action_sequence: list = field(default_factory=list)      # action 序列

    @classmethod
    def from_config(cls, safety: SafetyConfig, max_turns: int = 30,
                    max_budget_usd: float = 5.0) -> "CircuitBreaker":
        """从配置创建熔断器"""
        return cls(
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            max_consecutive_similar=safety.max_consecutive_similar,
            similarity_threshold=safety.similarity_threshold,
            stagnation_threshold=safety.stagnation_threshold,
            max_consecutive_errors=safety.max_consecutive_errors,
            oscillation_window=safety.oscillation_window,
        )

    def check(self, instruction: str, cost: float,
              tool_output: str = "") -> Optional[str]:
        """
        检查是否应该熔断（不含 action 震荡维度）

        返回 None 表示正常，否则返回熔断原因。

        action 震荡检测由 check_action() 单独负责，避免同一个 action
        在 check() 和 check_action() 中被双重 append。

        参数:
          instruction: 本轮发送给编码工具的指令
          cost: 本轮费用（USD）
          tool_output: 编码工具的输出（默认 "" 保持向后兼容）
        """
        # ① 轮数检查
        self._current_turn += 1
        if self._current_turn > self.max_turns:
            return f"超过最大轮数 {self.max_turns}"

        # ② 费用检查（工具费用）
        # _total_cost 只累计编码工具费用（由 Orchestrator 传入 result.cost_usd）。
        # Manager LLM 费用由 Orchestrator 在步骤 j 补充检查总预算。
        self._total_cost += cost
        if self._total_cost > self.max_budget_usd:
            return f"{BREAKER_BUDGET_PREFIX}: ${self._total_cost:.2f} > ${self.max_budget_usd}"

        # ③ 死循环检查（指令 hash 完全相同）
        h = hashlib.md5(instruction.encode()).hexdigest()[:8]
        self._instruction_hashes.append(h)
        if len(self._instruction_hashes) >= self.max_consecutive_similar:
            recent = self._instruction_hashes[-self.max_consecutive_similar:]
            if len(set(recent)) == 1:
                return f"检测到死循环：连续 {self.max_consecutive_similar} 次相同指令"

        # ④ 指令语义相似度检查
        reason = self._check_instruction_similarity(instruction)
        if reason:
            return reason

        # ⑤ 相同错误重复检查
        reason = self._check_error_repetition(tool_output)
        if reason:
            return reason

        # ⑥ 输出停滞检查
        reason = self._check_output_stagnation(tool_output)
        if reason:
            return reason

        # ⑦ action 震荡：不在此处检测，由 check_action() 单独负责

        return None  # 正常

    def check_action(self, action: str) -> Optional[str]:
        """
        公有方法：仅对 action 做震荡检测

        供 Orchestrator 在 Manager 决策后补做震荡检测时使用。
        当 check() 调用时 action 尚未产生（传 ""），事后需补做 action
        维度检测时调用此方法（_check_action_oscillation 内部负责 append）。
        """
        return self._check_action_oscillation(action)

    @property
    def total_cost(self) -> float:
        """获取累计费用"""
        return self._total_cost

    @property
    def current_turn(self) -> int:
        """获取当前轮数"""
        return self._current_turn

    def to_dict(self) -> dict:
        """序列化为字典（用于 checkpoint）"""
        return {
            "instruction_hashes": self._instruction_hashes[-20:],  # 截断，只保留最近 20 条
            "total_cost": self._total_cost,
            "current_turn": self._current_turn,
            "consecutive_similar": self._count_consecutive_similar(),
            # [新增] 多维度状态序列化
            "instruction_texts": self._instruction_texts[-10:],  # 只保留最近 10 条
            "error_hashes": self._error_hashes[-10:],            # 只保留最近 10 条
            "output_fingerprints": [],  # 不序列化：体积大且 resume 后参考价值低
            "action_sequence": self._action_sequence[-20:],      # 只保留最近 20 条
        }

    def restore(self, data: dict):
        """从字典恢复状态（用于崩溃恢复）"""
        self._instruction_hashes = data.get("instruction_hashes", [])
        self._total_cost = data.get("total_cost", 0.0)
        self._current_turn = data.get("current_turn", 0)
        # [新增] 多维度状态恢复
        self._instruction_texts = data.get("instruction_texts", [])
        self._error_hashes = data.get("error_hashes", [])
        self._output_fingerprints = []  # 恢复后重新开始积累，避免历史指纹干扰
        self._action_sequence = data.get("action_sequence", [])

    def _count_consecutive_similar(self) -> int:
        """计算当前连续相同指令的次数"""
        if not self._instruction_hashes:
            return 0
        count = 1
        last = self._instruction_hashes[-1]
        for h in reversed(self._instruction_hashes[:-1]):
            if h == last:
                count += 1
            else:
                break
        return count

    # ============================================================
    # 多维度检测私有方法
    # ============================================================

    def _check_instruction_similarity(self, instruction: str) -> Optional[str]:
        """
        检测连续 N 轮指令语义高度相似

        归一化后使用 SequenceMatcher 做相邻对比较。
        相邻对比意味着"每一步都像上一步"，比与首条比较更能捕捉渐进漂移的死循环。
        """
        normalized = self._normalize_text(instruction)
        self._instruction_texts.append(normalized)

        if len(self._instruction_texts) < self.max_consecutive_similar:
            return None

        recent = self._instruction_texts[-self.max_consecutive_similar:]
        # 相邻对比较：检测连续每步都与上一步高度相似的趋势
        all_similar = True
        min_ratio = 1.0
        for i in range(1, len(recent)):
            ratio = SequenceMatcher(None, recent[i - 1], recent[i]).ratio()
            min_ratio = min(min_ratio, ratio)
            if ratio < self.similarity_threshold:
                all_similar = False
                break

        if all_similar:
            return (
                f"指令语义相似：连续 {self.max_consecutive_similar} 次"
                f"（最低相似度 {min_ratio:.2f}）"
            )
        return None

    def _check_error_repetition(self, tool_output: str) -> Optional[str]:
        """
        检测连续 N 轮出现相同错误

        提取输出中的错误段后归一化、hash，连续相同 hash 则触发熔断。
        无错误的轮次以 None 占位，避免跨越正常轮次的误判。
        """
        error_section = self._extract_error_section(tool_output)
        if not error_section:
            self._error_hashes.append(None)  # None 明确表示本轮无错误
            return None

        normalized_error = self._normalize_text(error_section)
        error_hash = hashlib.md5(normalized_error.encode()).hexdigest()[:8]
        self._error_hashes.append(error_hash)

        if len(self._error_hashes) < self.max_consecutive_errors:
            return None

        recent = self._error_hashes[-self.max_consecutive_errors:]
        # 全部非 None 且相同才触发（含 None 说明中间有正常轮次，不算连续）
        if all(h is not None and h == recent[0] for h in recent):
            return (
                f"相同错误重复：连续 {self.max_consecutive_errors} 轮"
                f"出现相同错误"
            )
        return None

    def _check_output_stagnation(self, tool_output: str) -> Optional[str]:
        """
        检测连续 N 轮输出无实质变化

        取输出尾部 1000 字符作为指纹（尾部含最终结论/错误，比头部更能反映实质内容），
        相邻对比较，全部超过阈值则判定为停滞。
        """
        # 尾部指纹，控制 SequenceMatcher 计算量
        fingerprint = tool_output[-1000:] if tool_output else ""
        self._output_fingerprints.append(fingerprint)

        if len(self._output_fingerprints) < self.max_consecutive_similar:
            return None

        recent = self._output_fingerprints[-self.max_consecutive_similar:]

        # 相邻对比较（与维度1保持一致的比较策略）
        all_stagnant = True
        for i in range(1, len(recent)):
            if not recent[i - 1] and not recent[i]:
                continue  # 相邻两轮都空输出也算停滞，继续检查其他对
            ratio = SequenceMatcher(None, recent[i - 1], recent[i]).ratio()
            if ratio < self.stagnation_threshold:
                all_stagnant = False
                break

        if all_stagnant and any(recent):  # 至少有一轮有输出才触发
            return (
                f"输出停滞：连续 {self.max_consecutive_similar} 轮"
                f"输出高度相似（无实质推进）"
            )
        return None

    def _check_action_oscillation(self, action: str) -> Optional[str]:
        """
        检测 action 序列的周期性震荡（ABABAB 模式）

        注意：此方法内部负责将 action append 到 _action_sequence，
        调用方不应在调用前手动 append，否则会导致重复记录。
        空 action 直接跳过，不记录也不检测。
        """
        if not action:
            return None
        self._action_sequence.append(action)

        if len(self._action_sequence) < self.oscillation_window:
            return None

        recent = self._action_sequence[-self.oscillation_window:]

        # 检测周期为 2 的震荡：ABABAB 模式
        if len(recent) >= 4:
            is_oscillating = True
            for i in range(2, len(recent)):
                if recent[i] != recent[i % 2]:
                    is_oscillating = False
                    break
            if is_oscillating and recent[0] != recent[1]:
                return (
                    f"action 震荡：{recent[0]}↔{recent[1]} "
                    f"交替 {len(recent) // 2} 次"
                )

        return None

    # ============================================================
    # 辅助方法
    # ============================================================

    def _normalize_text(self, text: str) -> str:
        """
        归一化文本：去除时间戳、序号、路径前缀等噪声

        用于减少无意义差异对相似度计算的干扰，截取前 500 字符
        控制 SequenceMatcher 的计算量。
        """
        # 去时间戳（ISO 格式和常见日志格式）
        text = re.sub(r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*', '', text)
        # 去序号（如 "第3次"、"#5"、"step 2"）
        text = re.sub(r'[#第]\s*\d+[次步]?', '', text)
        # 去文件路径（/xxx/yyy/ 或 /xxx/yyy/file.py）
        text = re.sub(r'/[\w\-\.]+(/[\w\-\.]+)+/?', '', text)
        # 去多余空白
        text = re.sub(r'\s+', ' ', text).strip()
        # 截取前 500 字符（控制 SequenceMatcher 计算量）
        return text[:500]

    def _extract_error_section(self, output: str) -> str:
        """
        从输出中提取错误相关的部分

        策略：取包含 error/failed/exception/traceback/错误 等关键词的行，
        最多取最后 10 行错误行，避免提取结果过长。
        """
        if not output:
            return ""
        error_lines = []
        for line in output.split("\n"):
            if any(kw in line.lower() for kw in
                   ["error", "错误", "failed", "exception", "traceback"]):
                error_lines.append(line)
        return "\n".join(error_lines[-10:])


# ============================================================
# 工具函数
# ============================================================

def atomic_write_json(path: str, data: dict):
    """
    原子写入 JSON 文件

    先写入临时文件，再 rename，防止并发读取到半写数据。
    用于 state.json、checkpoint.json、registry.json 等共享文件。
    """
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.rename(tmp, path)


def read_json_safe(path: str) -> Optional[dict]:
    """
    安全读取 JSON 文件

    文件不存在或解析失败时返回 None。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
