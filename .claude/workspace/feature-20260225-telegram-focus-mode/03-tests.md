# 阶段 3：TDD 测试设计

## 测试文件

`tests/test_focus_mode.py` — 27 个测试用例

## 测试矩阵

| 测试类 | 用例数 | 覆盖模块 |
|--------|--------|----------|
| TestWriteTurnEvent | 6 | orchestrator._write_turn_event() |
| TestFormatTurnMessage | 6 | telegram_bot._format_turn_message() |
| TestFocusStateManagement | 4 | telegram_bot focus 状态字段 |
| TestSeekTurnsToEnd | 2 | telegram_bot._seek_turns_to_end() |
| TestInitTurnPositions | 2 | telegram_bot._init_turn_positions() |
| TestPushFocusedTurns | 3 | telegram_bot._push_focused_turns() |
| TestConfigPushEveryTurnRemoved | 2 | config.TelegramConfig 字段删除 |
| TestOrchestratorTelegramPushRemoved | 2 | orchestrator 方法删除 |

## TDD 红灯状态

- 通过: 4（纯状态管理测试）
- 失败: 23（待实现的方法和字段删除）

## 关键测试说明

- `test_output_truncated_to_2000_chars`: 验证 turns.jsonl 写入截断
- `test_output_truncated_to_1500`: 验证 Telegram 消息格式化截断
- `test_vibing_on_short_output`: 验证 <20 字符判定为 vibing
- `test_reads_new_lines_only`: 验证基于字节偏移的增量读取不重复
- `test_field_not_in_telegram_config`: 验证 push_every_turn 已删除
- `test_no_telegram_push_method`: 验证 Orchestrator 不再有直推方法
