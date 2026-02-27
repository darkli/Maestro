<!-- 来源: design-20260225-telegram-focus-mode -->
# 需求分析

## 功能需求

### FR-1: 任务关注模式（Focus Mode）

**描述**: Daemon 维护一个 "当前关注任务" 状态，只有被关注的任务才推送每轮详细输出。

**规则**:
- 一次只能关注一个任务
- 新发起的任务（/run）自动成为关注任务
- 非关注任务只在状态变更时推送（完成/失败/阻塞/等待用户），与现有行为一致
- 关注任务结束（completed/failed/aborted）后自动取消关注

### FR-2: 轮次输出内容推送

**描述**: 被关注的任务在每轮完成后，推送 Claude Code 的实际输出摘要和 Manager 的决策内容。

**推送内容**:
- Turn 序号和进度
- Claude Code 输出摘要（截断到合理长度）
- Manager 的 reasoning 和下一步 instruction
- 耗时

**"vibing" 提示**: 如果 Claude Code 输出为空或极短（<20字符），推送 "Claude Code vibing..." 而非空内容。

### FR-3: /focus 命令

**描述**: 新增 `/focus` 命令切换关注任务。

**用法**:
- `/focus` — 查看当前关注的任务
- `/focus <task_id>` — 切换关注到指定任务

### FR-4: 通知通道统一

**描述**: 将每轮进度通知从 Orchestrator 直推迁移到 Daemon 统一管理，解决 Orchestrator 不知道 focus 状态的问题。

## 非功能需求

- NFR-1: 不丢轮次 — Daemon 轮询间隔 5s，快速轮次可能被合并，可接受但需有合并提示
- NFR-2: Telegram 消息长度 — 单条消息不超过 4096 字符，超长自动截断
- NFR-3: 向后兼容 — 不影响现有 /status, /chat, /ask, /abort 等命令
- NFR-4: 无需持久化 — focus 状态存内存，Daemon 重启后清空（可接受）

## 用户故事

### US-1: 发起任务并自动关注
```
用户发送: /run /home/user/project 修复登录 Bug
Bot 回复: 任务 [abc12345] 已启动（已自动关注）...
Bot 推送: [abc12345] Turn 1/30 (7.8s)
          Claude Code 输出:
          我来分析登录模块的代码...找到了 auth.py 中的问题...

          Manager: 代码分析完成，准备修复
          下一步: 修改 auth.py 第 42 行的验证逻辑
```

### US-2: 切换关注
```
用户发送: /focus def67890
Bot 回复: 已关注任务 [def67890]
          需求: 实现用户注册功能
          当前进度: Turn 5/30
（后续推送切换到 def67890）
```

### US-3: Claude Code 无实质输出
```
Bot 推送: [abc12345] Turn 3/30 (2.1s)
          Claude Code vibing...

          Manager: 等待编码工具响应
```

### US-4: 非关注任务完成
```
Bot 推送: [def67890] 任务完成！
          轮数: 12
          费用: $0.35
          查看报告: /report def67890
（不推送 def67890 的每轮详情，只推送最终状态变更）
```
