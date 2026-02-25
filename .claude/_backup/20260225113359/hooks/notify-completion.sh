#!/bin/bash
# @version 1.0.0
# 完成通知 Hook — 会话结束时发送桌面通知
INPUT=$(cat)
ERROR=$(echo "$INPUT" | jq -r '.error // empty')

if command -v osascript &>/dev/null; then
  if [ -n "$ERROR" ]; then
    osascript -e 'display notification "开发流程异常终止，请检查错误信息" with title "Claude Code ⚠️" sound name "Basso"'
  else
    osascript -e 'display notification "功能开发流程已完成！" with title "Claude Code ✅" sound name "Glass"'
  fi
fi
exit 0
