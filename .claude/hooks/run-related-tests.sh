#!/bin/bash
# @version 2.0.0
# 关联测试 Hook — 修改源码后自动运行相关测试

# === 配置区域（由 init-workflow 填充） ===
CAPABILITY_TESTING="false"                    # 值为框架名或 "false"
TEST_CMD="pytest"                             # 项目专属测试命令
SOURCE_PATTERNS="*.py"                        # 源码文件 glob 模式
TEST_FILE_PATTERNS="test_*.py|*_test.py"      # 测试文件 glob 模式（跳过用）
# === 配置区域结束 ===

# testing:false 早退
if [ "$CAPABILITY_TESTING" = "false" ]; then
  exit 0
fi

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

# 跳过测试文件自身
if match_patterns "$FILE_PATH" "$TEST_FILE_PATTERNS"; then
  exit 0
fi

# 对源码文件运行关联测试
if match_patterns "$FILE_PATH" "$SOURCE_PATTERNS"; then
  $TEST_CMD "$FILE_PATH" --passWithNoTests 2>/dev/null
fi

exit 0
