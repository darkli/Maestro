#!/bin/bash
# @version 2.0.0
# Lint 检查 Hook — 在文件写入前执行 lint 检查

# === 配置区域（由 init-workflow 填充） ===
LINT_CMD="npx eslint"             # 项目专属 lint 命令
FILE_PATTERNS="src/*.ts|src/*.tsx" # 管道分隔的 glob 模式
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
  $LINT_CMD "$FILE_PATH" 2>/dev/null
fi

exit 0
