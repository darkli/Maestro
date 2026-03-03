#!/bin/bash
# @version 2.1.0
# 会话报告生成 Hook — 会话结束时自动生成开发报告
#
# [PROJECT-SPECIFIC] 适配说明：
#   1. 修改 WS_DIR 的 glob 模式匹配你项目的 Workspace 前缀
#   2. 修改 REPORT_DIR 为你希望存放报告的目录
#
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

# [PROJECT-SPECIFIC] 修改 Workspace 目录 glob 模式
WS_DIR=$(ls -dt .claude/workspace/feature-* .claude/workspace/bugfix-* .claude/workspace/design-* .claude/workspace/product-* .claude/workspace/doc-* 2>/dev/null | head -1)

# 无 Workspace 时跳过报告生成，避免产生低价值文件
if [ -z "$WS_DIR" ] || [ ! -d "$WS_DIR" ]; then
  exit 0
fi

# [PROJECT-SPECIFIC] 修改报告输出目录
REPORT_DIR="./docs/reports"
mkdir -p "$REPORT_DIR"

FEATURE_NAME=$(basename "$WS_DIR" | sed 's/^[a-z]*-[0-9]*-//')

# 自动检测 workspace 类型并列出所有产物文件
WS_TYPE=$(basename "$WS_DIR" | sed 's/-.*//')
cat > "$REPORT_DIR/session-${TIMESTAMP}.md" << REPORT
# 开发会话报告

**会话 ID**: ${SESSION_ID}
**时间**: ${TIMESTAMP}
**功能**: ${FEATURE_NAME}
**Workspace**: ${WS_DIR}
**类型**: ${WS_TYPE}

## Workspace 产物状态

| 文件 | 状态 |
|------|------|
$(find "$WS_DIR" -maxdepth 1 -name "*.md" -exec basename {} \; 2>/dev/null | sort | while read -r f; do echo "| $f | ✅ |"; done)

REPORT

echo "开发报告已生成: $REPORT_DIR/session-${TIMESTAMP}.md"
exit 0
