#!/bin/bash
# context.sh — 跨对话上下文文件管理脚本
# 用法: bash context.sh <subcommand> [args]
# 版本: 1.0.0
# 兼容: bash 3.2+ (macOS 默认) + Linux

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# ============================================================
# 常量与初始化
# ============================================================
PROJECT_ROOT="$(find_project_root "$PWD")"
CONTEXT_DIR="$PROJECT_ROOT/.claude/context"

# UUID 匹配模式（POSIX ERE，兼容 grep -E）
UUID_PATTERN='[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]-[0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F][0-9a-fA-F]\.jsonl'

# ============================================================
# 辅助函数
# ============================================================

# 检查 context 目录是否有 .md 文件
has_context_files() {
  ls "$CONTEXT_DIR"/*.md 2>/dev/null | head -1 | grep -q '.' 2>/dev/null
}

# 从上下文文件提取第一个 # 标题（任务名称）
extract_task_name() {
  local file="$1"
  awk '/^# / { sub(/^# /, ""); print; exit }' "$file"
}

# 提取 ## 当前状态 下的 - 进度：行（取第一条）
extract_status_line() {
  local file="$1"
  awk '
    /^## 当前状态/ { found=1; next }
    /^## / && found { exit }
    found && /^- 进度：/ {
      sub(/^- 进度：[[:space:]]*/, "")
      print; exit
    }
  ' "$file"
}

# 提取最后一条 ### YYYY-MM-DD 标题中的日期
extract_last_date() {
  local file="$1"
  grep '^### [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]' "$file" 2>/dev/null \
    | tail -1 \
    | awk '{ match($0, /[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/); print substr($0, RSTART, RLENGTH) }' \
    || true
}

# 提取最后一条完整的 ### YYYY- 会话节内容
extract_last_session() {
  local file="$1"
  awk '
    /^### [0-9][0-9][0-9][0-9]-/ { buf = $0; in_session=1; next }
    /^## / && in_session { exit }
    in_session { buf = buf "\n" $0 }
    END { print buf }
  ' "$file"
}

# 截断字符串到指定宽度（纯 awk，不依赖 bash 特性）
truncate_str() {
  local str="$1"
  local max="$2"
  echo "$str" | awk -v max="$max" '{
    if (length($0) > max) print substr($0, 1, max-3) "..."
    else print $0
  }'
}

# ============================================================
# 子命令：list
# ============================================================
cmd_list() {
  if ! has_context_files; then
    output_md "没有上下文文件（.claude/context/ 为空）"
    return 0
  fi

  # 表头
  echo "[OUTPUT:MD] | 名称 | 当前状态 | 会话数 | 最后更新 |"
  echo "[OUTPUT:MD] |------|----------|--------|----------|"

  for file in "$CONTEXT_DIR"/*.md; do
    [ -f "$file" ] || continue
    local name
    name=$(basename "$file" .md)

    local status
    status=$(extract_status_line "$file")
    [ -z "$status" ] && status="（无状态）"
    status=$(truncate_str "$status" 40)

    local session_count
    session_count=$(count_section_headers '### [0-9][0-9][0-9][0-9]-' "$file")

    local last_date
    last_date=$(extract_last_date "$file")
    [ -z "$last_date" ] && last_date="—"

    echo "[OUTPUT:MD] | $name | $status | $session_count | $last_date |"
  done
}

# ============================================================
# 子命令：load <name>
# ============================================================
cmd_load() {
  local name="${1:-}"
  if [ -z "$name" ]; then
    error "用法: context.sh load <name>"
    exit 1
  fi

  local file="$CONTEXT_DIR/${name}.md"
  if [ ! -f "$file" ]; then
    output_md "错误：上下文文件不存在：.claude/context/${name}.md"
    exit 1
  fi

  local task_name
  task_name=$(extract_task_name "$file")

  local background
  background=$(extract_md_section "背景" "$file")

  local current_status
  current_status=$(extract_md_section "当前状态" "$file")

  local key_files
  key_files=$(extract_md_section "关键文件" "$file")

  local last_session
  last_session=$(extract_last_session "$file")

  local session_count
  session_count=$(count_section_headers '### [0-9][0-9][0-9][0-9]-' "$file")

  local last_date
  last_date=$(extract_last_date "$file")
  [ -z "$last_date" ] && last_date="—"

  echo "[OUTPUT:MD] # 上下文：$task_name"
  echo "[OUTPUT:MD] "
  echo "[OUTPUT:MD] ## 背景"
  echo "$background" | while IFS= read -r line; do
    echo "[OUTPUT:MD] $line"
  done
  echo "[OUTPUT:MD] "
  echo "[OUTPUT:MD] ## 当前状态"
  echo "$current_status" | while IFS= read -r line; do
    echo "[OUTPUT:MD] $line"
  done
  echo "[OUTPUT:MD] "
  echo "[OUTPUT:MD] ## 关键文件"
  echo "$key_files" | while IFS= read -r line; do
    echo "[OUTPUT:MD] $line"
  done
  echo "[OUTPUT:MD] "
  echo "[OUTPUT:MD] ## 最近会话"
  echo "$last_session" | while IFS= read -r line; do
    echo "[OUTPUT:MD] $line"
  done
  echo "[OUTPUT:MD] "
  echo "[OUTPUT:MD] ---"
  echo "[OUTPUT:MD] - 会话数：$session_count"
  echo "[OUTPUT:MD] - 最后更新：$last_date"
}

# ============================================================
# 子命令：remove <name> [--confirm]
# ============================================================
cmd_remove() {
  local name="${1:-}"
  local confirm=false

  if [ -z "$name" ]; then
    error "用法: context.sh remove <name> [--confirm]"
    exit 1
  fi

  # Parse --confirm flag (may come as $2 or mixed)
  local arg
  for arg in "$@"; do
    [ "$arg" = "--confirm" ] && confirm=true
  done

  local file="$CONTEXT_DIR/${name}.md"

  if [ ! -f "$file" ]; then
    output_json "{\"exists\": false, \"path\": \".claude/context/${name}.md\"}"
    return 0
  fi

  if [ "$confirm" = false ]; then
    output_json "{\"exists\": true, \"path\": \".claude/context/${name}.md\"}"
    return 0
  fi

  rm -f "$file"
  output_json "{\"deleted\": true, \"path\": \".claude/context/${name}.md\"}"
}

# ============================================================
# 子命令：clean [--confirm]
# ============================================================
cmd_clean() {
  local confirm=false
  local arg
  for arg in "$@"; do
    [ "$arg" = "--confirm" ] && confirm=true
  done

  # Step 1: Get transcript dir
  local transcript_dir
  transcript_dir=$(get_transcript_dir "$PROJECT_ROOT")

  if [ ! -d "$transcript_dir" ]; then
    output_json "{\"error\": \"transcript 目录不存在\", \"path\": \"$transcript_dir\"}"
    exit 1
  fi

  # Step 2: Collect referenced transcript UUIDs from context files
  # Build a newline-separated list of referenced basenames (e.g. "abc123...jsonl")
  local referenced_list=""
  local has_transcript_refs=false
  if has_context_files; then
    # 先检查是否有任何 transcript: 引用
    if grep -qh 'transcript:' "$CONTEXT_DIR"/*.md 2>/dev/null; then
      has_transcript_refs=true
    fi
    referenced_list=$(grep -h 'transcript:' "$CONTEXT_DIR"/*.md 2>/dev/null \
      | grep -oE "$UUID_PATTERN" \
      | sort -u \
      || true)
    # 安全检查：上下文文件引用了 transcript 但提取为空（正则引擎失败），拒绝清理
    if [ "$has_transcript_refs" = true ] && [ -z "$referenced_list" ]; then
      error "上下文文件中存在 transcript 引用但未能提取 UUID，拒绝清理以防数据丢失"
      output_json "{\"error\": \"UUID 提取失败，无法安全判断哪些 transcript 可清理\"}"
      exit 1
    fi
  fi
  local referenced_count=0
  if [ -n "$referenced_list" ]; then
    referenced_count=$(echo "$referenced_list" | grep -c '.' || true)
  fi

  # Step 3: Get current (most recently modified) transcript
  local current_transcript=""
  current_transcript=$(get_current_transcript "$PROJECT_ROOT") || true
  local current_basename=""
  [ -n "$current_transcript" ] && current_basename=$(basename "$current_transcript")

  # Step 4: Compute cleanable = all - referenced - current
  # Use a temp file to hold cleanable paths (one per line, safe for paths with spaces)
  local cleanable_tmp
  cleanable_tmp=$(mktemp "${TMPDIR:-/tmp}/ctx-clean-XXXXXX")

  local f
  for f in "$transcript_dir"/*.jsonl; do
    [ -f "$f" ] || continue
    local bname
    bname=$(basename "$f")

    # Skip current transcript
    [ "$bname" = "$current_basename" ] && continue

    # Skip if referenced
    local is_ref=false
    if [ -n "$referenced_list" ]; then
      if echo "$referenced_list" | grep -qF "$bname"; then
        is_ref=true
      fi
    fi
    [ "$is_ref" = true ] && continue

    echo "$f" >> "$cleanable_tmp"
  done

  # Compute total size of cleanable files
  local total_size="0"
  if [ -s "$cleanable_tmp" ]; then
    total_size=$(xargs du -ch < "$cleanable_tmp" 2>/dev/null | tail -1 | awk '{print $1}' || echo "unknown")
  fi

  # Build JSON array of cleanable basenames
  local json_array="["
  local first=true
  while IFS= read -r f; do
    local bname
    bname=$(basename "$f")
    if [ "$first" = true ]; then
      json_array="${json_array}\"$bname\""
      first=false
    else
      json_array="${json_array}, \"$bname\""
    fi
  done < "$cleanable_tmp"
  json_array="${json_array}]"

  if [ "$confirm" = false ]; then
    rm -f "$cleanable_tmp"
    output_json "{\"cleanable\": $json_array, \"referenced_count\": $referenced_count, \"current\": \"$current_basename\", \"total_size\": \"$total_size\"}"
    return 0
  fi

  # With --confirm: delete cleanable files and their same-name subdirs
  local deleted_count=0
  while IFS= read -r f; do
    [ -f "$f" ] || continue
    local subdir="${f%.jsonl}"
    rm -f "$f"
    deleted_count=$((deleted_count + 1))
    if [ -d "$subdir" ]; then
      rm -rf "$subdir"
    fi
  done < "$cleanable_tmp"
  rm -f "$cleanable_tmp"

  output_json "{\"deleted_count\": $deleted_count, \"cleanable\": $json_array, \"total_size\": \"$total_size\"}"
}

# ============================================================
# 子命令：save-prepare [--name=X]
# ============================================================
cmd_save_prepare() {
  local name_arg=""
  local arg
  for arg in "$@"; do
    case "$arg" in
      --name=*) name_arg="${arg#--name=}" ;;
    esac
  done

  # Step 1: Get current transcript
  local transcript=""
  transcript=$(get_current_transcript "$PROJECT_ROOT") || true

  local transcript_basename=""
  [ -n "$transcript" ] && transcript_basename=$(basename "$transcript")

  # Step 2: Determine mode and path
  local mode="create"
  local ctx_path=""
  local existing_name=""
  local dedup=false

  if [ -n "$name_arg" ]; then
    # Name provided: check if file exists
    ctx_path=".claude/context/${name_arg}.md"
    local abs_path="$CONTEXT_DIR/${name_arg}.md"
    if [ -f "$abs_path" ]; then
      mode="append"
      existing_name="$name_arg"
      # Check dedup: is current transcript UUID already in the file's 会话日志?
      if [ -n "$transcript_basename" ] && grep -q "$transcript_basename" "$abs_path" 2>/dev/null; then
        dedup=true
        mode="update"
      fi
    else
      mode="create"
      ctx_path=".claude/context/${name_arg}.md"
    fi
  else
    # No name: try to auto-associate via current transcript basename
    if [ -n "$transcript_basename" ] && has_context_files; then
      local matched_file=""
      for f in "$CONTEXT_DIR"/*.md; do
        [ -f "$f" ] || continue
        if grep -q "$transcript_basename" "$f" 2>/dev/null; then
          matched_file="$f"
          break
        fi
      done
      if [ -n "$matched_file" ]; then
        existing_name=$(basename "$matched_file" .md)
        ctx_path=".claude/context/${existing_name}.md"
        mode="update"
        dedup=true
      fi
    fi
    # If still no match, mode stays "create" with empty path
    if [ -z "$ctx_path" ]; then
      mode="create"
      ctx_path=""
    fi
  fi

  # Emit JSON
  local dedup_val="false"
  [ "$dedup" = true ] && dedup_val="true"

  local existing_name_json="null"
  [ -n "$existing_name" ] && existing_name_json="\"$existing_name\""

  local ctx_path_json="null"
  [ -n "$ctx_path" ] && ctx_path_json="\"$ctx_path\""

  local transcript_json="null"
  [ -n "$transcript" ] && transcript_json="\"$transcript\""

  output_json "{\"mode\": \"$mode\", \"path\": $ctx_path_json, \"transcript\": $transcript_json, \"existing_name\": $existing_name_json, \"dedup\": $dedup_val}"
}

# ============================================================
# 主入口
# ============================================================
main() {
  if [ $# -eq 0 ]; then
    echo "用法: context.sh <subcommand> [args]" >&2
    echo "子命令: list | load <name> | remove <name> [--confirm] | clean [--confirm] | save-prepare [--name=X]" >&2
    exit 2
  fi

  local subcommand="$1"
  shift

  case "$subcommand" in
    list)
      cmd_list "$@"
      ;;
    load)
      cmd_load "$@"
      ;;
    remove)
      cmd_remove "$@"
      ;;
    clean)
      cmd_clean "$@"
      ;;
    save-prepare)
      cmd_save_prepare "$@"
      ;;
    *)
      error "未知子命令: $subcommand"
      echo "子命令: list | load <name> | remove <name> [--confirm] | clean [--confirm] | save-prepare [--name=X]" >&2
      exit 2
      ;;
  esac
}

main "$@"
