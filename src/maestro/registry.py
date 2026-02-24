"""
多任务注册表模块

管理所有任务的索引信息：
  - 任务 CRUD（创建、查询、更新、删除）
  - 文件锁保证并发安全
  - 并发数检查（max_parallel_tasks）
  - 从各任务的 state.json 重建索引

registry.json 是索引（摘要），state.json 是每个任务的权威状态。
"""

import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional

from maestro.state import atomic_write_json, read_json_safe


class TaskRegistry:
    """
    多任务注册表

    数据存储在 ~/.maestro/registry.json。
    每个条目包含：task_id, requirement, working_dir, status, created_at, zellij_session。
    """

    def __init__(self, maestro_dir: str = "~/.maestro",
                 max_parallel_tasks: int = 3):
        self.maestro_dir = Path(maestro_dir).expanduser()
        self.maestro_dir.mkdir(parents=True, exist_ok=True)
        self.registry_path = str(self.maestro_dir / "registry.json")
        self.max_parallel_tasks = max_parallel_tasks

    @staticmethod
    def generate_task_id() -> str:
        """生成 8 位短任务 ID"""
        return str(uuid.uuid4())[:8]

    def create_task(self, task_id: str, requirement: str,
                    working_dir: str) -> dict:
        """创建新任务条目"""
        registry = self._load()
        entry = {
            "task_id": task_id,
            "requirement": requirement,
            "working_dir": working_dir,
            "status": "pending",
            "created_at": datetime.now().isoformat(),
            "zellij_session": f"maestro-{task_id}",
        }
        registry[task_id] = entry
        self._save(registry)
        return entry

    def update_task(self, task_id: str, **kwargs):
        """更新任务条目字段"""
        registry = self._load()
        if task_id not in registry:
            return
        registry[task_id].update(kwargs)
        self._save(registry)

    def get_task(self, task_id: str) -> Optional[dict]:
        """查询单个任务"""
        registry = self._load()
        return registry.get(task_id)

    def list_tasks(self) -> list[dict]:
        """列出所有任务（按创建时间排序）"""
        registry = self._load()
        tasks = list(registry.values())
        tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)
        return tasks

    def delete_task(self, task_id: str):
        """删除任务条目"""
        registry = self._load()
        if task_id in registry:
            del registry[task_id]
            self._save(registry)

    def can_start_new_task(self) -> tuple[bool, str]:
        """
        检查是否可以启动新任务

        返回 (可以启动, 原因说明)
        """
        registry = self._load()
        active_statuses = ("executing", "waiting_user", "pending")
        active = len([
            t for t in registry.values()
            if t.get("status") in active_statuses
        ])
        if active >= self.max_parallel_tasks:
            return False, (
                f"已达并发上限 {self.max_parallel_tasks}，"
                f"当前 {active} 个任务运行中"
            )
        return True, ""

    def sync_from_state(self, task_id: str):
        """
        从 state.json 同步任务状态到 registry

        Orchestrator 每次更新 state.json 后调用此方法。
        """
        state_path = self.maestro_dir / "sessions" / task_id / "state.json"
        state = read_json_safe(str(state_path))
        if state:
            self.update_task(task_id, status=state.get("status", "unknown"))

    def rebuild(self):
        """
        从所有 state.json 重建 registry

        用于 registry.json 损坏时的恢复。
        """
        sessions_dir = self.maestro_dir / "sessions"
        if not sessions_dir.exists():
            return

        registry = {}
        for task_dir in sessions_dir.iterdir():
            if not task_dir.is_dir():
                continue
            state = read_json_safe(str(task_dir / "state.json"))
            if state:
                task_id = state.get("task_id", task_dir.name)
                registry[task_id] = {
                    "task_id": task_id,
                    "requirement": state.get("requirement", ""),
                    "working_dir": state.get("working_dir", ""),
                    "status": state.get("status", "unknown"),
                    "created_at": state.get("created_at", ""),
                    "zellij_session": state.get("zellij_session", ""),
                }
        self._save(registry)

    # ============================================================
    # 内部方法
    # ============================================================

    def _load(self) -> dict:
        """加载 registry.json（文件锁保护）"""
        data = read_json_safe(self.registry_path)
        return data if data else {}

    def _save(self, data: dict):
        """保存 registry.json（文件锁保护 + 原子写入）"""
        atomic_write_json(self.registry_path, data)
