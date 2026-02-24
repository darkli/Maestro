"""
状态管理模块

包含：
  - TaskStatus: 任务状态枚举
  - 状态转换验证
  - CircuitBreaker: 熔断器（死循环检测 + 资源超限）
  - atomic_write_json: 原子写入工具函数
"""

import os
import json
import hashlib
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

from maestro.config import SafetyConfig


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

    三个维度：
    1. 轮数上限 (max_turns)
    2. 费用上限 (max_budget_usd)
    3. 连续相似指令 (max_consecutive_similar) — 检测死循环
    """
    max_turns: int = 30
    max_budget_usd: float = 5.0
    max_consecutive_similar: int = 3

    # 运行时状态
    _instruction_hashes: list = field(default_factory=list)
    _total_cost: float = 0.0
    _current_turn: int = 0

    @classmethod
    def from_config(cls, safety: SafetyConfig, max_turns: int = 30,
                    max_budget_usd: float = 5.0) -> "CircuitBreaker":
        """从配置创建熔断器"""
        return cls(
            max_turns=max_turns,
            max_budget_usd=max_budget_usd,
            max_consecutive_similar=safety.max_consecutive_similar,
        )

    def check(self, instruction: str, cost: float) -> Optional[str]:
        """
        检查是否应该熔断

        返回 None 表示正常，否则返回熔断原因。
        """
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
            "instruction_hashes": self._instruction_hashes.copy(),
            "total_cost": self._total_cost,
            "current_turn": self._current_turn,
            "consecutive_similar": self._count_consecutive_similar(),
        }

    def restore(self, data: dict):
        """从字典恢复状态（用于崩溃恢复）"""
        self._instruction_hashes = data.get("instruction_hashes", [])
        self._total_cost = data.get("total_cost", 0.0)
        self._current_turn = data.get("current_turn", 0)

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
