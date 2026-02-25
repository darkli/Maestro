#!/bin/bash
# @version 2.1.0
# 关联测试 Hook — 修改源码后自动运行相关测试

# === 配置区域（由 f-init 填充） ===
CAPABILITY_TESTING="pytest"
TEST_CMD="pytest"
SOURCE_PATTERNS="*.sh"
TEST_FILE_PATTERNS="test/*.bats|tests/*.bats|test/*_test.sh|tests/*_test.sh"
# === 配置区域结束 ===

# testing:false 或 CMD 为空时早退
if [ "$CAPABILITY_TESTING" = "false" ] || [ -z "$TEST_CMD" ]; then
  exit 0
fi

# 检查文件路径是否匹配管道分隔的 glob 模式
# 支持绝对路径：对每个模式额外尝试 */ 前缀匹配
match_patterns() {
  local file="$1" patterns="$2"
  IFS='|' read -ra PATS <<< "$patterns"
  for pat in "${PATS[@]}"; do
    case "$file" in $pat | */$pat) return 0 ;; esac
  done
  return 1
}

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# 跳过测试文件自身
if match_patterns "$FILE_PATH" "$TEST_FILE_PATTERNS"; then
  exit 0
fi

# 对源码文件运行关联测试
if match_patterns "$FILE_PATH" "$SOURCE_PATTERNS"; then
  $TEST_CMD "$FILE_PATH" 2>/dev/null
fi

exit 0
