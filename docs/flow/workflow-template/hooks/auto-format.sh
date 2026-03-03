#!/bin/bash
# @version 2.2.0
# 自动格式化 Hook — 在文件修改后自动格式化

# 加载公共函数库（match_patterns 等）
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/../scripts/common.sh"

# === 配置区域（由 f-init 填充） ===
FORMAT_CMD=""
FILE_PATTERNS="*.ts|*.tsx|*.js|*.jsx"
# === 配置区域结束 ===

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

if [ -n "$FORMAT_CMD" ] && match_patterns "$FILE_PATH" "$FILE_PATTERNS"; then
  $FORMAT_CMD "$FILE_PATH" 2>/dev/null
fi

exit 0
