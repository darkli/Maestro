# 实现摘要：Focus 自动恢复

## 变更清单

| 文件 | 改动类型 | 改动说明 |
|------|----------|----------|
| `src/maestro/telegram_bot.py` | 修改 | 新增自动恢复相关方法和逻辑集成 |
| `src/maestro/orchestrator.py` | 修改 | resume notice 增强 + 步骤注释修正 |
| `src/maestro/config.py` | 修改 | 删除 `push_every_turn` 字段 |
| `src/maestro/cli.py` | 未改动 | `_launch_resume_background` 被 telegram_bot.py 复用 |
| `config.example.yaml` | 修改 | 删除 `push_every_turn` 配置 |
| `deploy.sh` | 修改 | 删除 `push_every_turn` 配置 |
| `tests/test_focus_mode.py` | 修改 | 新增 21 个自动恢复相关测试 |

## 核心实现

### 1. telegram_bot.py 新增

#### `_is_worker_alive(state) -> bool`
进程存活检测，通过 `os.kill(pid, 0)` 实现。增加了 PID 合法性校验（`isinstance(pid, int) and pid > 0`），防止负数 PID 导致的安全问题。

#### `_auto_resume_if_needed(task_id, update) -> bool`
自动恢复核心方法，检测任务状态和进程存活性，满足条件时调用 `_launch_resume_background()` 启动恢复。包含：
- 状态过滤（仅 failed/waiting_user）
- 进程存活检测
- `_resuming_tasks` 防重入
- checkpoint 存在性验证
- 恢复进程启动

#### `_resuming_tasks: set[str]`
防重入状态集合，在 `_monitor_loop` 中当任务状态变为 executing/completed/failed/aborted 时清理。

### 2. telegram_bot.py 修改

#### `_on_ask()` - 集成自动恢复 + 终态拦截（CR-003）
- 写入 inbox 前先检查 completed/aborted 状态，提前拦截
- 写入 inbox 后调用 `_auto_resume_if_needed()`

#### `_on_message()` - 直接回复 + focus 消息集成
- 直接回复通知消息：写入 inbox 后自动恢复检测
- focus 模式普通消息：区分进程存活/已死，存活时路由到 inbox，已死时自动恢复

#### `_on_focus()` - 状态提示
- failed: 提示"直接发消息即可自动恢复"
- aborted: 提示"maestro resume"
- waiting_user + 进程死: 提示"直接发消息即可自动恢复"
- waiting_user + 进程活: 提示"直接发消息或 /ask 即可回复"

#### `_monitor_loop()` - 清理防重入 + Worker 健康检测
- `_resuming_tasks` 清理扩展到所有终态
- Worker 崩溃检测复用 `_is_worker_alive()` 方法

### 3. orchestrator.py 修改

#### `resume()` - inbox 消息注入
- 恢复前读取 inbox.txt 中的用户消息
- 有用户消息时：构建含"用户回复了：<消息>"的 resume notice
- 无用户消息时：标准崩溃恢复 notice

### 4. 审查问题修复

| CR 编号 | 级别 | 修复方式 |
|---------|------|----------|
| CR-001 | High | `_monitor_loop` 清理条件扩展到 executing/completed/failed/aborted |
| CR-002 | High | `_is_worker_alive` 增加 `isinstance(pid, int) and pid > 0` 校验 |
| CR-003 | High | `_on_ask` 对 completed/aborted 状态提前拦截 |
| CR-004 | Medium | `_on_message` focus 路径区分进程存活/已死 |
| CR-005 | Medium | `_monitor_loop` 复用 `_is_worker_alive()` |
| CR-006 | Medium | 防重入提示语改为"正在恢复中，你的消息已排队" |
| CR-007 | Medium | 删除 `_launch_resume()` 方法，import 复用 `cli.py::_launch_resume_background()` |
| CR-008 | Medium | 步骤注释 "# 6." 改为 "# 7." |
| CR-010 | Low | focus 路径 resume 失败时补充用户提示 |
| CR-012 | Low | 恢复启动时增加 logger.info 日志 |

## 测试结果

```
tests/test_focus_mode.py: 48 passed
tests/ (全部): 119 passed
```

## 需求覆盖核对

| 需求 | 状态 |
|------|------|
| FR-1 向死任务发消息时自动恢复 | 已实现并测试 |
| FR-2 focus 死任务时提示可恢复 | 已实现并测试 |
| FR-3 恢复时注入用户消息到 Manager 上下文 | 已实现并测试 |
| FR-4 进程存活检测 | 已实现并测试 |
| NFR-1 自动恢复只触发一次 | 已实现并测试 |
| NFR-2 恢复后 focus 状态保持 | 已实现 |
| NFR-3 不影响运行中任务 | 已实现并测试 |

## 下游摘要

### 变更文件
- `src/maestro/telegram_bot.py` — 自动恢复逻辑（_auto_resume_if_needed, _is_worker_alive, _resuming_tasks），_on_ask/_on_message/_on_focus/_monitor_loop 集成
- `src/maestro/orchestrator.py` — resume() inbox 消息注入
- `src/maestro/config.py` — 删除 push_every_turn
- `config.example.yaml` — 删除 push_every_turn
- `deploy.sh` — 删除 push_every_turn
- `tests/test_focus_mode.py` — 21 个新增测试

### 测试结果
全部 119 个测试通过

### 需求覆盖
FR-1~FR-4 和 NFR-1~NFR-3 全部覆盖
