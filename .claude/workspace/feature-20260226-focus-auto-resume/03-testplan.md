# 测试计划：Focus 自动恢复

## 测试用例清单

### 1. _is_worker_alive 进程检测

| 用例 | 输入 | 预期结果 |
|------|------|----------|
| 存活进程 PID | `os.getpid()` | `True` |
| 不存在的大 PID | `999999999` | `False` |
| state 为 None | `None` | `False` |
| 无 worker_pid 字段 | `{}` | `False` |
| pid=0 | `{"worker_pid": 0}` | `False` |
| 负数 pid（CR-002） | `{"worker_pid": -1}` | `False` |
| 字符串 pid | `{"worker_pid": "1234"}` | `False` |

### 2. _auto_resume_if_needed 自动恢复

| 用例 | 条件 | 预期结果 |
|------|------|----------|
| 非可恢复状态 | status=executing/completed/aborted/pending | `False`，不触发 |
| 进程存活 | status=failed, pid=存活进程 | `False`，不触发 |
| 防重入 | task_id 已在 _resuming_tasks 中 | `True`，提示"正在恢复中，已排队" |
| 无 checkpoint | status=failed, 无 checkpoint.json | `False`，提示无法恢复 |

### 3. _resuming_tasks 防重入清理

| 用例 | 条件 | 预期结果 |
|------|------|----------|
| 恢复后 executing | 状态变为 executing | 从 set 中移除 |
| 直接到 completed（CR-001） | 状态变为 completed | 从 set 中移除 |
| 直接到 failed（CR-001） | 状态变为 failed | 从 set 中移除 |
| 直接到 aborted（CR-001） | 状态变为 aborted | 从 set 中移除 |

### 4. _on_ask 终态拦截（CR-003）

| 用例 | 条件 | 预期结果 |
|------|------|----------|
| completed 任务 | status=completed | 拒绝，提示"已完成" |
| aborted 任务 | status=aborted | 拒绝，提示"已终止" |

### 5. _on_focus 状态提示

| 用例 | 条件 | 预期结果 |
|------|------|----------|
| 失败任务 | status=failed | 提示"自动恢复" |
| 终止任务 | status=aborted | 提示"maestro resume" |
| 等待回复+进程死 | status=waiting_user, worker 死 | 提示"自动恢复" |
| 已完成任务 | status=completed | 无恢复提示 |

### 6. Orchestrator resume notice 增强

| 用例 | 条件 | 预期结果 |
|------|------|----------|
| 有用户消息 | inbox 有内容 | notice 包含"用户回复了" |
| 无用户消息 | inbox 为空 | notice 包含"崩溃恢复" |
| inbox 清空 | 读取后 | inbox 内容被清除 |

## 测试框架

- pytest + pytest-asyncio
- unittest.mock (MagicMock, AsyncMock, patch)
- tmp_path fixture 用于文件系统测试

## 测试覆盖

共 21 个新增测试用例，分布在 5 个测试类中：
- `TestAutoResume`: 11 个
- `TestOnAskTerminalStateInterception`: 1 个
- `TestOnFocusStatusHint`: 4 个
- `TestOrchestratorResumeNotice`: 3 个

加上原有的 27 个用例，总计 48 个测试全部通过。

## 下游摘要

### 测试文件
- `tests/test_focus_mode.py`

### 覆盖目标
- `_is_worker_alive()`: 7 个边界场景
- `_auto_resume_if_needed()`: 4 个核心路径
- `_resuming_tasks` 清理: 2 个终态场景
- `/ask` 终态拦截: 1 个
- `/focus` 状态提示: 4 个
- `resume notice` 增强: 3 个
