# 04 - 功能需求：Telegram Bot

## 4.1 概述

Telegram Bot 提供远程控制和状态监控能力，允许用户通过手机管理 VPS 上的编码任务。

**启动方式**：通过 Daemon 模式后台运行。

```bash
maestro daemon start    # 启动
maestro daemon stop     # 停止
maestro daemon status   # 查看状态
```

---

## 4.2 命令全表

| 命令 | 参数 | 说明 | 需要 focus |
|------|------|------|-----------|
| `/start` | - | 显示欢迎和帮助信息 | 否 |
| `/help` | - | 显示帮助信息 | 否 |
| `/cd` | `<路径>` | 设置工作目录（后续 /run 使用） | 否 |
| `/run` | `<需求>` | 启动新任务（自动 focus） | 否 |
| `/list` | - | 列出所有任务（最多 10 个） | 否 |
| `/focus` | `[id\|off]` | 关注/取消关注任务 | 否 |
| `/status` | `[id]` | 查看任务详情 | 可省略 id |
| `/ask` | `[id] <消息>` | 发送反馈到运行中的任务 | 可省略 id |
| `/chat` | `[id] <问题>` | 与 Manager 独立问答 | 可省略 id |
| `/abort` | `[id]` | 终止任务 | 可省略 id |
| `/report` | `[id]` | 查看任务报告 | 可省略 id |
| `/switch` | `[tool]` | 查看/切换当前编码工具 | 否 |
| `/new` | - | 重置自由聊天历史 | 否 |
| 直接消息 | 任意文本 | 自由聊天（多轮） | 否 |

---

## 4.3 Focus 模式

### 4.3.1 概念

用户"关注"某个任务后，后续命令可省略 task_id，自动操作被关注的任务。

### 4.3.2 启用/关闭

```
/focus a1b2c3d4    → 关注任务 a1b2c3d4
/focus off         → 取消关注
```

### 4.3.3 自动 Focus

- 通过 `/run` 启动新任务时自动 focus 该任务

### 4.3.4 命令省略 ID

Focus 模式下以下命令可省略 task_id：

```
/status          → 等同于 /status a1b2c3d4
/ask "问题"     → 等同于 /ask a1b2c3d4 "问题"
/chat "问题"    → 等同于 /chat a1b2c3d4 "问题"
/abort           → 等同于 /abort a1b2c3d4
/report          → 等同于 /report a1b2c3d4
```

### 4.3.5 推送增强

Focus 任务的每轮执行详情从 `turns.jsonl` 读取并推送到 Telegram（超出消息长度限制时省略输出部分）。

---

## 4.4 状态监控推送

### 4.4.1 轮询机制

- 间隔：5 秒轮询一次
- 数据源：各任务的 `state.json`

### 4.4.2 推送条件

| 事件 | 推送内容 |
|------|---------|
| 状态变更 | "任务 {id} 状态变为 {status}" |
| ask_user 触发 | Manager 的问题文本 + 提示回复方式 |
| 任务完成 | 完成通知 + summary |
| 任务失败 | 失败通知 + fail_reason |
| focus 任务每轮 | 当前轮数、指令、输出（截断）、reasoning |

`waiting_user` 推送优先展示 `state.json.last_question`；若 question 缺失，才 fallback 到 Manager reasoning。

### 4.4.3 消息 ID 映射

Bot 发送通知时记录 `message_id → task_id` 映射，供直接回复路由使用。

---

## 4.5 直接回复路由

### 4.5.1 工作流程

```
1. Manager 触发 ask_user → Orchestrator 状态变 waiting_user
2. Telegram Bot 检测状态变更 → 推送问题通知到用户
3. 用户在 Telegram 直接回复该通知消息
4. Bot 从 reply_to_message_id 查找 task_id 映射
5. 回复内容自动写入对应任务的 inbox.txt
6. Orchestrator 读取反馈 → 交给 Manager 基于回复重新决策 → 再继续执行
```

### 4.5.2 备选方式

用户也可以通过 `/ask` 命令手动发送反馈（不依赖直接回复）。

---

## 4.6 自由聊天

### 4.6.1 触发条件

直接发文本消息到 Bot（不带 `/` 命令前缀）。

### 4.6.2 特性

- 使用 `free_chat_prompt_file` 的 system prompt
- 保存最近 20 条对话历史（用户消息 + Bot 回复）
- `/new` 命令清空历史重新开始

### 4.6.3 与 /chat 的区别

| 对比 | 自由聊天 | /chat |
|------|---------|-------|
| 上下文 | 独立多轮历史 | 任务上下文（state.json） |
| Prompt | free_chat.md | chat.md |
| 关联任务 | 无 | 需要 task_id |
| 历史轮数 | 20 轮 | 无历史（每次独立） |

---

## 4.7 /run 远程启动任务

### 4.7.1 前置条件

- 必须先通过 `/cd <路径>` 设置工作目录
- 路径必须在 VPS 上存在

### 4.7.2 流程

```
1. 用户：/cd /home/user/project
2. Bot：工作目录已设置为 /home/user/project
3. 用户：/run 实现登录模块
4. Bot：任务 a1b2c3d4 已启动（自动 focus）
```

---

## 4.8 /list 任务列表

### 4.8.1 输出格式

```
📋 任务列表：
1. [>>] a1b2c3d4 - 实现登录模块
2. [OK] b2c3d4e5 - 修复翻页 Bug
3. [!!] c3d4e5f6 - 添加单元测试
```

### 4.8.2 限制

- 最多显示 10 个任务
- 含状态图标（同 CLI 的 list 命令）

---

## 4.9 鉴权机制

### 4.9.1 配置

```yaml
telegram:
  chat_id: "123456789"    # 授权用户的 Telegram chat_id
```

### 4.9.2 鉴权逻辑

- `chat_id` 已配置：仅匹配的用户可使用 Bot
- `chat_id` 未配置（空）：不鉴权，任何人可用（不推荐）

### 4.9.3 未授权行为

返回"未授权"消息，不执行任何操作。

---

## 4.10 Daemon 管理

### 4.10.1 启动

```bash
maestro daemon start
```

- 通过 `nohup` 后台启动 `telegram_bot.py`
- PID 写入 `~/.maestro/daemon.pid`
- 日志输出到 `~/.maestro/logs/daemon.log`

### 4.10.2 停止

```bash
maestro daemon stop
```

- 读取 PID 文件
- 发送 SIGTERM

### 4.10.3 状态检查

```bash
maestro daemon status
```

- 检查 PID 文件是否存在
- 检查对应进程是否存活
