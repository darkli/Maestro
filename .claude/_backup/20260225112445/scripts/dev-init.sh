#!/bin/bash
# dev-init.sh — 开发类 Skill 通用初始化脚本
# 用法: dev-init.sh --type=<feature|bugfix|design|product|doc> \
#                   --name=<short-name> \
#                   --input=<text | - for stdin> \
#                   [--upstream=<upstream-workspace-path>] \
#                   [--skip-context] \
#                   [--dry-run]
# 版本: 1.1.0
# 兼容: bash 3.2+ (macOS 默认) + Linux
#
# 退出码:
#   0 = 成功
#   1 = 业务错误（参数无效、类型不支持等）
#   2 = 系统错误（文件系统异常等）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# ============================================================
# 常量与初始化
# ============================================================
PROJECT_ROOT="$(find_project_root "$PWD")"
CLAUDE_MD="$PROJECT_ROOT/CLAUDE.md"
WS_BASE="$PROJECT_ROOT/.claude/workspace"

# 参数变量
ARG_TYPE=""
ARG_NAME=""
ARG_INPUT=""
ARG_UPSTREAM=""
ARG_SKIP_CONTEXT=false
ARG_DRY_RUN=false

# 结果变量
RESULT_WORKSPACE=""
RESULT_FILES_CREATED=""
RESULT_UPSTREAM_DETECTED="null"
RESULT_AVAILABLE_UPSTREAMS=""
RESULT_PROGRESS_UPDATED=false
RESULT_CAPABILITIES=""

# 警告列表（JSON 数组元素，逗号分隔）
WARNINGS_LIST=""

# 临时文件（stdin 输入时使用）
TMP_INPUT_FILE=""

# ============================================================
# 清理
# ============================================================
cleanup() {
  if [ -n "$TMP_INPUT_FILE" ] && [ -f "$TMP_INPUT_FILE" ]; then
    rm -f "$TMP_INPUT_FILE"
  fi
  return 0
}
trap cleanup EXIT

# ============================================================
# 警告管理
# ============================================================
add_warning() {
  local msg="$1"
  warn "$msg"
  # JSON 转义：反斜杠和双引号
  local escaped_msg
  escaped_msg=$(printf '%s' "$msg" | sed 's/\\/\\\\/g; s/"/\\"/g')
  if [ -z "$WARNINGS_LIST" ]; then
    WARNINGS_LIST="\"${escaped_msg}\""
  else
    WARNINGS_LIST="${WARNINGS_LIST}, \"${escaped_msg}\""
  fi
}

# ============================================================
# 参数解析
# ============================================================
usage() {
  echo "用法: dev-init.sh --type=<feature|bugfix|design|product|doc> \\"
  echo "                  --name=<short-name> \\"
  echo "                  --input=<text | - for stdin> \\"
  echo "                  [--upstream=<path>] \\"
  echo "                  [--skip-context] \\"
  echo "                  [--dry-run]"
}

parse_args() {
  if [ $# -eq 0 ]; then
    usage >&2
    exit 1
  fi

  while [ $# -gt 0 ]; do
    case "$1" in
      --type=*)       ARG_TYPE="${1#--type=}" ;;
      --name=*)       ARG_NAME="${1#--name=}" ;;
      --input=*)      ARG_INPUT="${1#--input=}" ;;
      --upstream=*)   ARG_UPSTREAM="${1#--upstream=}" ;;
      --skip-context) ARG_SKIP_CONTEXT=true ;;
      --dry-run)      ARG_DRY_RUN=true ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        echo "[FATAL] 未知参数: $1" >&2
        usage >&2
        exit 1
        ;;
    esac
    shift
  done

  # 必填参数校验
  if [ -z "$ARG_TYPE" ]; then
    echo "[FATAL] 缺少必填参数: --type" >&2
    usage >&2
    exit 1
  fi
  if [ -z "$ARG_NAME" ]; then
    echo "[FATAL] 缺少必填参数: --name" >&2
    usage >&2
    exit 1
  fi
  if [ -z "$ARG_INPUT" ]; then
    echo "[FATAL] 缺少必填参数: --input" >&2
    usage >&2
    exit 1
  fi

  # 类型合法性校验（bash 3.2 兼容：不使用 =~）
  case "$ARG_TYPE" in
    feature|bugfix|design|product|doc) ;;
    *)
      echo "[FATAL] 无效类型: ${ARG_TYPE} (仅支持 feature|bugfix|design|product|doc)" >&2
      exit 1
      ;;
  esac

  # stdin 输入处理
  if [ "$ARG_INPUT" = "-" ]; then
    TMP_INPUT_FILE=$(mktemp "${TMPDIR:-/tmp}/dev-init-input-XXXXXX")
    cat > "$TMP_INPUT_FILE"
    ARG_INPUT=$(cat "$TMP_INPUT_FILE")
  fi
}

# ============================================================
# (a) 目录创建
# ============================================================
create_workspace_dir() {
  # 类型到前缀的映射（bash 3.2 兼容：不使用关联数组）
  local prefix
  case "$ARG_TYPE" in
    feature) prefix="feature" ;;
    bugfix)  prefix="bugfix" ;;
    design)  prefix="design" ;;
    product) prefix="product" ;;
    doc)     prefix="doc" ;;
    *)       prefix="feature" ;;
  esac

  local date_str
  date_str=$(date +%Y%m%d)

  local ws_name="${prefix}-${date_str}-${ARG_NAME}"
  RESULT_WORKSPACE=".claude/workspace/${ws_name}"

  local ws_abs="${WS_BASE}/${ws_name}"

  if [ "$ARG_DRY_RUN" = true ]; then
    verbose "[DRY-RUN] mkdir -p $ws_abs"
    return 0
  fi

  if ! mkdir -p "$ws_abs"; then
    echo "[FATAL] 无法创建 workspace 目录: $ws_abs" >&2
    exit 2
  fi

  verbose "已创建 workspace 目录: $ws_abs"
}

# ============================================================
# (b) 00-input.md 生成（按类型差异化模板）
# ============================================================
generate_input_md() {
  local ws_abs="${PROJECT_ROOT}/${RESULT_WORKSPACE}"
  local output_file="${ws_abs}/00-input.md"

  local datetime
  datetime=$(date "+%Y-%m-%d %H:%M")

  # 附加上下文内容
  local extra_context="（未提供）"
  if [ -n "$ARG_UPSTREAM" ]; then
    extra_context="上游 Workspace: ${ARG_UPSTREAM}"
  fi

  local content=""

  case "$ARG_TYPE" in
    feature|design|product)
      content="# 原始需求输入

**功能名称**: ${ARG_NAME}
**提交时间**: ${datetime}
**用户描述**:

${ARG_INPUT}

**附加上下文**:

${extra_context}"
      ;;

    bugfix)
      content="# Bug 信息

**问题名称**: ${ARG_NAME}
**报告时间**: ${datetime}
**问题描述**:

${ARG_INPUT}

**错误日志/堆栈跟踪**:

（未提供）

**复现步骤**:

（未提供）

**预期行为**:

（未提供）

**实际行为**:

（未提供）"
      ;;

    doc)
      content="# 原始需求输入

**任务名称**: ${ARG_NAME}
**提交时间**: ${datetime}
**任务类型**: 新增文档 / 修改文档 / 同步更新

**用户描述**:

${ARG_INPUT}

**附加上下文**:

${extra_context}"
      ;;
  esac

  if [ "$ARG_DRY_RUN" = true ]; then
    verbose "[DRY-RUN] 将写入 $output_file"
    RESULT_FILES_CREATED="${RESULT_FILES_CREATED} 00-input.md"
    return 0
  fi

  printf '%s\n' "$content" > "$output_file"
  RESULT_FILES_CREATED="${RESULT_FILES_CREATED} 00-input.md"
  verbose "已生成 00-input.md"
}

# ============================================================
# (c) 00-context.md 生成
# ============================================================

# 将 parse_capabilities 输出格式化为 Markdown 表格
build_tech_table() {
  if [ ! -f "$CLAUDE_MD" ]; then
    return 0
  fi

  echo "| 能力 | 值 |"
  echo "|------|-----|"
  parse_capabilities "$CLAUDE_MD" | awk -F= '{
    key = $1
    # value may contain "=" — rejoin from field 2 onwards
    val = ""
    for (i = 2; i <= NF; i++) {
      val = (i == 2) ? $i : (val "=" $i)
    }
    if (key != "" && val != "") {
      printf "| %s | %s |\n", key, val
    }
  }'
}

# 校验节内容是否为空，空则记录警告
validate_section() {
  local section_name="$1"
  local content="$2"

  # 去掉纯空白行后检查是否有实质内容
  local trimmed
  trimmed=$(printf '%s' "$content" | awk 'NF{p=1} p')

  if [ -z "$trimmed" ]; then
    add_warning "section \"${section_name}\" 在 CLAUDE.md 中未找到或为空"
  fi
}

generate_context_md() {
  if [ "$ARG_SKIP_CONTEXT" = true ]; then
    verbose "跳过 00-context.md 生成（--skip-context）"
    return 0
  fi

  local ws_abs="${PROJECT_ROOT}/${RESULT_WORKSPACE}"
  local output_file="${ws_abs}/00-context.md"

  if [ ! -f "$CLAUDE_MD" ]; then
    add_warning "CLAUDE.md 不存在，跳过 00-context.md 生成"
    return 0
  fi

  # 提取各节内容
  local section_tech section_build section_testing section_arch
  local section_conventions section_language section_commit

  section_tech=$(build_tech_table)
  section_build=$(extract_md_section "Build & Development Commands" "$CLAUDE_MD")
  section_testing=$(extract_md_section "Testing" "$CLAUDE_MD")
  section_arch=$(extract_md_section "Architecture" "$CLAUDE_MD")
  section_conventions=$(extract_md_section "Key Development Conventions" "$CLAUDE_MD")
  section_language=$(extract_md_section "Language" "$CLAUDE_MD")
  section_commit=$(extract_md_section "Commit Style" "$CLAUDE_MD")

  # 校验各节是否为空
  validate_section "技术栈" "$section_tech"
  validate_section "Build & Development Commands" "$section_build"
  validate_section "Testing" "$section_testing"
  validate_section "Architecture" "$section_arch"
  validate_section "Key Development Conventions" "$section_conventions"
  validate_section "Language" "$section_language"
  validate_section "Commit Style" "$section_commit"

  if [ "$ARG_DRY_RUN" = true ]; then
    verbose "[DRY-RUN] 将写入 $output_file"
    RESULT_FILES_CREATED="${RESULT_FILES_CREATED} 00-context.md"
    return 0
  fi

  {
    echo "# 项目上下文"
    echo ""
    echo "## 技术栈"
    echo ""
    if [ -n "$section_tech" ]; then
      echo "$section_tech"
    else
      echo "（未找到）"
    fi
    echo ""
    echo "## 构建与开发命令"
    echo ""
    if [ -n "$section_build" ]; then
      echo "$section_build"
    else
      echo "（未找到）"
    fi
    echo ""
    echo "## 测试约定"
    echo ""
    if [ -n "$section_testing" ]; then
      echo "$section_testing"
    else
      echo "（未找到）"
    fi
    echo ""
    echo "## 架构"
    echo ""
    if [ -n "$section_arch" ]; then
      echo "$section_arch"
    else
      echo "（未找到）"
    fi
    echo ""
    echo "## 编码规范"
    echo ""
    if [ -n "$section_conventions" ]; then
      echo "$section_conventions"
    else
      echo "（未找到）"
    fi
    echo ""
    echo "## 输出约定"
    echo ""
    if [ -n "$section_language" ]; then
      echo "$section_language"
    fi
    if [ -n "$section_commit" ]; then
      echo "$section_commit"
    fi
    if [ -z "$section_language" ] && [ -z "$section_commit" ]; then
      echo "（未找到）"
    fi
  } > "$output_file"

  RESULT_FILES_CREATED="${RESULT_FILES_CREATED} 00-context.md"
  verbose "已生成 00-context.md"
}

# ============================================================
# (d) 上游检测
# ============================================================
detect_upstream() {
  if [ -n "$ARG_UPSTREAM" ]; then
    # 用户明确指定了上游，upstream_detected 设为字符串值
    RESULT_UPSTREAM_DETECTED="\"${ARG_UPSTREAM}\""
    verbose "上游 workspace 已指定: $ARG_UPSTREAM"
    return 0
  fi

  # 未指定时，扫描 product-* workspace 作为可用上游候选
  RESULT_AVAILABLE_UPSTREAMS=""
  local first=true

  for entry in "${WS_BASE}"/product-*/; do
    [ -d "$entry" ] || continue
    local dir_name
    dir_name=$(basename "$entry")
    local rel_path=".claude/workspace/${dir_name}"

    if [ "$first" = true ]; then
      RESULT_AVAILABLE_UPSTREAMS="\"${rel_path}\""
      first=false
    else
      RESULT_AVAILABLE_UPSTREAMS="${RESULT_AVAILABLE_UPSTREAMS}, \"${rel_path}\""
    fi
  done

  verbose "可用上游: ${RESULT_AVAILABLE_UPSTREAMS:-（无）}"
}

# ============================================================
# (e) 进度文件检查与更新
# ============================================================
check_progress_file() {
  # 收集进度文件列表
  local progress_files
  progress_files=$(ls "${WS_BASE}"/_progress-*.md 2>/dev/null || true)

  if [ -z "$progress_files" ]; then
    verbose "未找到进度文件"
    return 0
  fi

  # 在所有进度文件中搜索 ARG_NAME
  local matched_file=""
  for pf in $progress_files; do
    [ -f "$pf" ] || continue
    if grep -q "$ARG_NAME" "$pf" 2>/dev/null; then
      matched_file="$pf"
      break
    fi
  done

  if [ -z "$matched_file" ]; then
    verbose "进度文件中未找到 '$ARG_NAME'"
    return 0
  fi

  verbose "找到进度文件: ${matched_file}，更新状态为进行中"

  if [ "$ARG_DRY_RUN" = true ]; then
    verbose "[DRY-RUN] 将更新 $matched_file 中 '$ARG_NAME' 相关子任务状态为进行中"
    RESULT_PROGRESS_UPDATED=true
    return 0
  fi

  # 使用 awk 将 ARG_NAME 所在子任务块的最近 **状态**: 行更新为 进行中
  local tmp_file
  tmp_file=$(mktemp "${TMPDIR:-/tmp}/dev-init-progress-XXXXXX")

  awk -v name="$ARG_NAME" '
    {
      if (/\*\*状态\*\*/) {
        last_status_line = NR
      }
      # 仅在 **Workspace** 行或子任务标题行匹配名称，避免注释中的误匹配
      if ((index($0, "Workspace") > 0 || /^### /) && index($0, name) > 0 && last_status_line > 0) {
        lines[last_status_line] = "- **状态**: 进行中"
        last_status_line = 0
      }
      lines[NR] = $0
    }
    END {
      for (i = 1; i <= NR; i++) {
        print lines[i]
      }
    }
  ' "$matched_file" > "$tmp_file"

  mv "$tmp_file" "$matched_file"
  RESULT_PROGRESS_UPDATED=true
  verbose "已更新进度文件: $matched_file"
}

# ============================================================
# (f) Capabilities 提取为 JSON 对象
# ============================================================
extract_capabilities_json() {
  RESULT_CAPABILITIES=""

  if [ ! -f "$CLAUDE_MD" ]; then
    verbose "CLAUDE.md 不存在，跳过 capabilities 提取"
    return 0
  fi

  local pairs
  pairs=$(parse_capabilities "$CLAUDE_MD")

  if [ -z "$pairs" ]; then
    verbose "未提取到 capabilities"
    return 0
  fi

  # 用 awk 构建 JSON 对象（避免 heredoc 展开风险，且无子 shell 变量丢失问题）
  local json
  json=$(printf '%s\n' "$pairs" | awk -F= '{
    key = $1
    val = ""
    for (i = 2; i <= NF; i++) val = (i == 2) ? $i : (val "=" $i)
    if (key == "" || val == "") next
    gsub(/\\/, "\\\\", val); gsub(/"/, "\\\"", val)
    if (NR > 1) printf ", "
    printf "\"%s\": \"%s\"", key, val
  }')
  json="{${json}}"
  RESULT_CAPABILITIES="$json"
  verbose "已提取 capabilities: $RESULT_CAPABILITIES"
}

# ============================================================
# JSON 结果输出
# ============================================================
emit_result_json() {
  # files_created 转为 JSON 数组
  local files_json="["
  local first=true
  for f in $RESULT_FILES_CREATED; do
    [ -z "$f" ] && continue
    if [ "$first" = true ]; then
      files_json="${files_json}\"${f}\""
      first=false
    else
      files_json="${files_json}, \"${f}\""
    fi
  done
  files_json="${files_json}]"

  # upstream_detected：已设置时为带引号字符串，否则为 JSON null
  local upstream_detected="${RESULT_UPSTREAM_DETECTED}"

  # available_upstreams 转为 JSON 数组
  local upstreams_json="[]"
  if [ -n "$RESULT_AVAILABLE_UPSTREAMS" ]; then
    upstreams_json="[${RESULT_AVAILABLE_UPSTREAMS}]"
  fi

  # progress_updated 布尔值
  local progress_val="false"
  [ "$RESULT_PROGRESS_UPDATED" = true ] && progress_val="true"

  # capabilities JSON 对象
  local caps_val="{}"
  [ -n "$RESULT_CAPABILITIES" ] && caps_val="$RESULT_CAPABILITIES"

  # warnings 转为 JSON 数组
  local warnings_json="[]"
  if [ -n "$WARNINGS_LIST" ]; then
    warnings_json="[${WARNINGS_LIST}]"
  fi

  output_json "{\"workspace\": \"${RESULT_WORKSPACE}\", \"files_created\": ${files_json}, \"upstream_detected\": ${upstream_detected}, \"available_upstreams\": ${upstreams_json}, \"progress_updated\": ${progress_val}, \"capabilities\": ${caps_val}, \"warnings\": ${warnings_json}}"
}

# ============================================================
# 主流程
# ============================================================
main() {
  parse_args "$@"

  verbose "dev-init.sh 启动"
  verbose "类型=$ARG_TYPE 名称=$ARG_NAME dry-run=$ARG_DRY_RUN skip-context=$ARG_SKIP_CONTEXT"

  # (a) 创建 workspace 目录
  create_workspace_dir

  # (b) 生成 00-input.md
  generate_input_md

  # (c) 生成 00-context.md（除非 --skip-context）
  generate_context_md

  # (d) 上游检测
  detect_upstream

  # (e) 进度文件检查与更新
  check_progress_file

  # (f) 提取 capabilities 为 JSON
  extract_capabilities_json

  # 输出 JSON 结果（供 Skill 解析）
  emit_result_json
}

main "$@"
