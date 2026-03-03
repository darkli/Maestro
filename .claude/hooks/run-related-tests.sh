#!/bin/bash
# @version 2.2.0
# 关联测试 Hook — 修改源码后自动运行相关测试

# 加载公共函数库（match_patterns 等）
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/../scripts/common.sh"

# === 配置区域（由 f-init 填充） ===
CAPABILITY_TESTING="pytest"
TEST_CMD="pytest"
SOURCE_PATTERNS="*.sh"
TEST_FILE_PATTERNS="test/*.bats|tests/*.bats|test/*_test.sh|tests/*_test.sh"
# === 配置区域结束 ===

# testing:false 早退
if [ "$CAPABILITY_TESTING" = "false" ]; then
  exit 0
fi

# 根据测试框架和命令格式构造完整的测试执行命令
run_test() {
  local file_path="$1"
  case "$CAPABILITY_TESTING" in
    vitest|jest)
      case "$TEST_CMD" in
        npm\ test*|npm\ run\ test*)
          # npm 需要 -- 分隔符传递参数给底层框架
          $TEST_CMD -- "$file_path" --passWithNoTests
          ;;
        *)
          $TEST_CMD "$file_path" --passWithNoTests
          ;;
      esac
      ;;
    pytest)
      $TEST_CMD "$file_path"
      ;;
    *)
      $TEST_CMD "$file_path"
      ;;
  esac
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
  run_test "$FILE_PATH"
fi

exit 0
