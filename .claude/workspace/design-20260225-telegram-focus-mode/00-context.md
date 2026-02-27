# 项目上下文

## 技术栈

| 能力 | 值 |
|------|-----|
| frontend | false |
| backend-api | false |
| database | false |
| testing | pytest |
| monorepo | false |

## 相关模块

| 模块 | 文件 | 本次改动 |
|------|------|----------|
| Orchestrator | `orchestrator.py` | 新增轮次事件文件写入，移除 per-turn Telegram 推送 |
| TelegramDaemon | `telegram_bot.py` | 新增 focus 状态管理、/focus 命令、增强 monitor_loop |
| Config | `config.py` | push_every_turn 默认值调整 |

## 当前通知架构（双通道）

1. **Orchestrator 直推**：`_telegram_push_turn()` 在每轮结束时直接 HTTP POST 到 Telegram API
2. **Daemon 监控推送**：`_monitor_loop()` 每 5s 轮询 state.json，检测状态变更后推送

两个通道独立工作，互不感知。当前问题是 Orchestrator 推送的内容只有数字，没有实质内容。
