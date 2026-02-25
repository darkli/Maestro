#!/bin/bash
# @version 2.0.0
# 会话报告生成 Hook — 会话结束时自动生成开发报告
#
# [PROJECT-SPECIFIC] 适配说明：
#   1. 修改 WS_DIR 的 glob 模式匹配你项目的 Workspace 前缀
#   2. 修改阶段文件名（如果你自定义了 Workspace 文件命名）
#   3. 修改 REPORT_DIR 为你希望存放报告的目录
#
INPUT=$(cat)
SESSION_ID=$(echo "$INPUT" | jq -r '.session_id // "unknown"')
TIMESTAMP=$(date +"%Y-%m-%d_%H-%M-%S")

# [PROJECT-SPECIFIC] 修改 Workspace 目录 glob 模式
WS_DIR=$(ls -dt .claude/workspace/feature-* .claude/workspace/bugfix-* .claude/workspace/design-* .claude/workspace/doc-* 2>/dev/null | head -1)

# [PROJECT-SPECIFIC] 修改报告输出目录
REPORT_DIR="./docs/reports"
mkdir -p "$REPORT_DIR"

if [ -n "$WS_DIR" ] && [ -d "$WS_DIR" ]; then
  FEATURE_NAME=$(basename "$WS_DIR" | sed 's/^[a-z]*-[0-9]*-//')

  # [PROJECT-SPECIFIC] 修改阶段文件名以匹配你的 Workspace 结构
  cat > "$REPORT_DIR/session-${TIMESTAMP}.md" << REPORT
# 开发会话报告

**会话 ID**: ${SESSION_ID}
**时间**: ${TIMESTAMP}
**功能**: ${FEATURE_NAME}
**Workspace**: ${WS_DIR}

## Workspace 工件状态

| 阶段 | 文件 | 状态 |
|------|------|------|
| 需求分析 | 01-requirements.md | $([ -f "$WS_DIR/01-requirements.md" ] && echo "✅" || echo "❌") |
| 系统设计 | 02-design.md | $([ -f "$WS_DIR/02-design.md" ] && echo "✅" || echo "❌") |
| 测试计划 | 03-testplan.md | $([ -f "$WS_DIR/03-testplan.md" ] && echo "✅" || echo "❌") |
| 编码实现 | 04-implementation.md | $([ -f "$WS_DIR/04-implementation.md" ] && echo "✅" || echo "❌") |
| 代码审查 | 05-review.md | $([ -f "$WS_DIR/05-review.md" ] && echo "✅" || echo "❌") |
| 集成验证 | 06-validation.md | $([ -f "$WS_DIR/06-validation.md" ] && echo "✅" || echo "❌") |
| 交付清单 | 07-delivery.md | $([ -f "$WS_DIR/07-delivery.md" ] && echo "✅" || echo "❌") |

REPORT
else
  cat > "$REPORT_DIR/session-${TIMESTAMP}.md" << REPORT
# 开发会话报告

**会话 ID**: ${SESSION_ID}
**时间**: ${TIMESTAMP}

## 本次会话概要

[此报告由 Hook 自动生成，未检测到 Workspace 目录]

REPORT
fi

echo "开发报告已生成: $REPORT_DIR/session-${TIMESTAMP}.md"
exit 0
