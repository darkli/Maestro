#!/bin/bash
# @version 2.0.0
# 自动格式化 Hook — 在文件修改后自动格式化

# === 配置区域（由 f-init 填充） ===
FORMAT_CMD="ruff format ."
FILE_PATTERNS="*.py"
# === 配置区域结束 ===

# 检查文件路径是否匹配管道分隔的 glob 模式
match_patterns() {
  local file="$1" patterns="$2"
  IFS='|' read -ra PATS <<< "$patterns"
  for pat in "${PATS[@]}"; do
    case "$file" in $pat) return 0 ;; esac
  done
  return 1
}

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

if match_patterns "$FILE_PATH" "$FILE_PATTERNS"; then
  $FORMAT_CMD "$FILE_PATH" 2>/dev/null
fi

exit 0
