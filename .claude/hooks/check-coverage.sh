#!/bin/bash
# @version 2.1.0
# 覆盖率检查 Hook — 运行测试后检查覆盖率是否达标

# === 配置区域（由 f-init 填充） ===
CAPABILITY_TESTING="pytest"
TEST_CMD_PATTERNS="bats|shunit2|make test"
COVERAGE_FILE=".coverage"
COVERAGE_FORMAT="xml"
THRESHOLD="80"
# === 配置区域结束 ===

# testing:false 早退
if [ "$CAPABILITY_TESTING" = "false" ]; then
  exit 0
fi

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# 检查是否为测试命令
MATCH=0
IFS='|' read -ra PATS <<< "$TEST_CMD_PATTERNS"
for pat in "${PATS[@]}"; do
  case "$COMMAND" in
    *"$pat"*) MATCH=1; break ;;
  esac
done

if [ "$MATCH" -eq 0 ]; then
  exit 0
fi

if [ ! -f "$COVERAGE_FILE" ]; then
  exit 0  # 无覆盖率报告，不阻塞
fi

# 根据覆盖率格式解析覆盖率数据
STATEMENT_COV=""
case "$COVERAGE_FORMAT" in
  json)
    STATEMENT_COV=$(jq -r '.total.statements.pct // 0' "$COVERAGE_FILE" 2>/dev/null)
    ;;
  lcov)
    LF=$(grep -c "^LF:" "$COVERAGE_FILE" 2>/dev/null || echo "0")
    LH=$(grep -c "^LH:" "$COVERAGE_FILE" 2>/dev/null || echo "0")
    if [ "$LF" -gt 0 ]; then
      STATEMENT_COV=$(echo "scale=1; $LH * 100 / $LF" | bc -l 2>/dev/null || echo "0")
    else
      STATEMENT_COV=0
    fi
    ;;
  cobertura)
    STATEMENT_COV=$(COVERAGE_PATH="$COVERAGE_FILE" python3 -c "
import os, xml.etree.ElementTree as ET
tree = ET.parse(os.environ['COVERAGE_PATH'])
root = tree.getroot()
print(round(float(root.attrib.get('line-rate', 0)) * 100, 1))
" 2>/dev/null || echo "0")
    ;;
  *)
    # 未知格式，跳过检查
    exit 0
    ;;
esac

# 校验解析结果是否为有效数字
if ! echo "$STATEMENT_COV" | grep -qE '^[0-9]+\.?[0-9]*$'; then
  exit 0  # 解析失败，不阻塞
fi

if [ "$(echo "$STATEMENT_COV < $THRESHOLD" | bc -l 2>/dev/null)" = "1" ]; then
  echo "测试覆盖率不达标！当前：${STATEMENT_COV}%，要求：${THRESHOLD}%" >&2
  exit 1
fi

echo "测试覆盖率达标：${STATEMENT_COV}%"
exit 0
