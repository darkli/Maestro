#!/bin/bash
# workspace.sh — Workspace 目录管理脚本
# 用法: bash workspace.sh <subcommand> [args]
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
WS_DIR="$PROJECT_ROOT/.claude/workspace"

# ============================================================
# 辅助函数
# ============================================================

# 从目录名提取类型前缀
# 用法: get_ws_type "feature-20260220-xxx"
# 返回: "功能开发" / "缺陷修复" 等
get_ws_type() {
  local name="$1"
  local prefix
  prefix=$(echo "$name" | awk -F'-' '{print $1}')
  case "$prefix" in
    product)  echo "产品设计" ;;
    feature)  echo "功能开发" ;;
    bugfix)   echo "缺陷修复" ;;
    design)   echo "系统设计" ;;
    doc)      echo "文档维护" ;;
    *)        echo "其他" ;;
  esac
}

# 从目录名提取日期并格式化为 YYYY-MM-DD
# 用法: get_ws_date "feature-20260220-xxx"
# 返回: "2026-02-20" 或 "—"
get_ws_date() {
  local name="$1"
  # 提取8位数字日期段
  local date_part
  date_part=$(echo "$name" | grep -oE '[0-9]{8}' | head -1)
  if [ -z "$date_part" ]; then
    echo "—"
    return 0
  fi
  # 格式化为 YYYY-MM-DD
  echo "$date_part" | awk '{print substr($0,1,4) "-" substr($0,5,2) "-" substr($0,7,2)}'
}

# 将 check_protection 返回值转换为可读状态
# 用法: format_protection_status "protected:进行中"
# 返回: "受保护" 或 "可清理"
format_protection_status() {
  local raw="$1"
  case "$raw" in
    protected:*) echo "受保护" ;;
    cleanable:*) echo "可清理" ;;
    unref)       echo "可清理" ;;
    *)           echo "可清理" ;;
  esac
}

# 获取目录中的文件数量
# 用法: count_dir_files "/path/to/dir"
count_dir_files() {
  local dir="$1"
  find "$dir" -type f 2>/dev/null | wc -l | tr -d ' '
}

# 获取目录最后修改时间（YYYY-MM-DD）
# 用法: get_dir_last_modified "/path/to/dir"
get_dir_last_modified() {
  local dir="$1"
  # 查找目录内最新修改的文件
  local newest
  newest=$(find "$dir" -type f 2>/dev/null | xargs ls -t 2>/dev/null | head -1)
  if [ -n "$newest" ]; then
    portable_stat_mtime "$newest"
  else
    portable_stat_mtime "$dir"
  fi
}

# ============================================================
# 子命令：list
# ============================================================
cmd_list() {
  if [ ! -d "$WS_DIR" ]; then
    info "没有 workspace"
    exit 0
  fi

  # 收集目录列表（排除 _progress-*.md 等非目录）
  local has_dirs=false
  local dir_name

  # 先检查是否有子目录
  for entry in "$WS_DIR"/*/; do
    [ -d "$entry" ] && has_dirs=true && break
  done

  if [ "$has_dirs" = false ]; then
    info "没有 workspace"
    exit 0
  fi

  # 输出表头
  echo "[OUTPUT:MD] | 目录名 | 类型 | 日期 | 进度 | 大小 | 状态 |"
  echo "[OUTPUT:MD] |--------|------|------|------|------|------|"

  for entry in "$WS_DIR"/*/; do
    [ -d "$entry" ] || continue
    dir_name=$(basename "$entry")

    local ws_type
    ws_type=$(get_ws_type "$dir_name")

    local ws_date
    ws_date=$(get_ws_date "$dir_name")

    local ws_progress
    ws_progress=$(detect_ws_progress "$dir_name" "$WS_DIR")

    local ws_size
    ws_size=$(portable_du "$entry")

    local raw_status
    raw_status=$(check_protection "$dir_name" "$WS_DIR")

    local ws_status
    ws_status=$(format_protection_status "$raw_status")

    echo "[OUTPUT:MD] | $dir_name | $ws_type | $ws_date | $ws_progress | $ws_size | $ws_status |"
  done
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

  if [ ! -d "$WS_DIR" ]; then
    output_json "{\"protected\": [], \"cleanable\": [], \"total_cleanable_size\": \"0\"}"
    exit 0
  fi

  # 分类目录
  local protected_names=""
  local cleanable_names=""

  for entry in "$WS_DIR"/*/; do
    [ -d "$entry" ] || continue
    local dir_name
    dir_name=$(basename "$entry")

    local raw_status
    raw_status=$(check_protection "$dir_name" "$WS_DIR")

    case "$raw_status" in
      protected:*)
        if [ -z "$protected_names" ]; then
          protected_names="$dir_name"
        else
          protected_names="$protected_names
$dir_name"
        fi
        ;;
      *)
        if [ -z "$cleanable_names" ]; then
          cleanable_names="$dir_name"
        else
          cleanable_names="$cleanable_names
$dir_name"
        fi
        ;;
    esac
  done

  if [ "$confirm" = false ]; then
    # 构建 protected JSON 数组
    local protected_json="["
    local first=true
    if [ -n "$protected_names" ]; then
      while IFS= read -r name; do
        [ -z "$name" ] && continue
        local raw_s
        raw_s=$(check_protection "$name" "$WS_DIR")
        # 提取状态描述（去掉前缀 "protected:"）
        local status_desc
        status_desc=$(echo "$raw_s" | awk -F: '{print $2}')
        [ -z "$status_desc" ] && status_desc="进行中"

        # 查找引用该 workspace 的 progress 文件
        local progress_file=""
        for pf in "$WS_DIR"/_progress-*.md; do
          [ -f "$pf" ] || continue
          if grep -q "$name" "$pf" 2>/dev/null; then
            progress_file=".claude/workspace/$(basename "$pf")"
            break
          fi
        done

        if [ "$first" = true ]; then
          protected_json="${protected_json}{\"name\": \"$name\", \"status\": \"$status_desc\", \"progress_file\": \"$progress_file\"}"
          first=false
        else
          protected_json="${protected_json}, {\"name\": \"$name\", \"status\": \"$status_desc\", \"progress_file\": \"$progress_file\"}"
        fi
      done <<EOF
$protected_names
EOF
    fi
    protected_json="${protected_json}]"

    # 构建 cleanable JSON 数组及计算总大小
    local cleanable_json="["
    local cleanable_dirs=""
    first=true
    if [ -n "$cleanable_names" ]; then
      while IFS= read -r name; do
        [ -z "$name" ] && continue
        local dir_path="$WS_DIR/$name"
        local file_count
        file_count=$(count_dir_files "$dir_path")
        local dir_size
        dir_size=$(portable_du "$dir_path")
        local last_mod
        last_mod=$(get_dir_last_modified "$dir_path")

        if [ "$first" = true ]; then
          cleanable_json="${cleanable_json}{\"name\": \"$name\", \"files\": $file_count, \"size\": \"$dir_size\", \"last_modified\": \"$last_mod\"}"
          first=false
        else
          cleanable_json="${cleanable_json}, {\"name\": \"$name\", \"files\": $file_count, \"size\": \"$dir_size\", \"last_modified\": \"$last_mod\"}"
        fi

        # 收集路径用于计算总大小
        if [ -z "$cleanable_dirs" ]; then
          cleanable_dirs="$dir_path"
        else
          cleanable_dirs="$cleanable_dirs
$dir_path"
        fi
      done <<EOF
$cleanable_names
EOF
    fi
    cleanable_json="${cleanable_json}]"

    # 计算可清理总大小（用 du -ch 汇总，取最后一行 total）
    local total_size="0"
    if [ -n "$cleanable_dirs" ]; then
      total_size=$(echo "$cleanable_dirs" | tr '\n' '\0' | xargs -0 du -ch 2>/dev/null | tail -1 | awk '{print $1}' || echo "0")
    fi

    output_json "{\"protected\": $protected_json, \"cleanable\": $cleanable_json, \"total_cleanable_size\": \"$total_size\"}"
    return 0
  fi

  # --confirm 模式：执行清理
  local deleted_names=""
  local delete_errors=0

  if [ -n "$cleanable_names" ]; then
    while IFS= read -r name; do
      [ -z "$name" ] && continue
      local dir_path="$WS_DIR/$name"
      if [ -d "$dir_path" ]; then
        rm -rf "$dir_path"
        if [ -z "$deleted_names" ]; then
          deleted_names="$name"
        else
          deleted_names="$deleted_names
$name"
        fi
      fi
    done <<EOF
$cleanable_names
EOF
  fi

  # 构建已删除 JSON 数组
  local deleted_json="["
  local first=true
  if [ -n "$deleted_names" ]; then
    while IFS= read -r name; do
      [ -z "$name" ] && continue
      if [ "$first" = true ]; then
        deleted_json="${deleted_json}\"$name\""
        first=false
      else
        deleted_json="${deleted_json}, \"$name\""
      fi
    done <<EOF
$deleted_names
EOF
  fi
  deleted_json="${deleted_json}]"

  local deleted_count=0
  [ -n "$deleted_names" ] && deleted_count=$(echo "$deleted_names" | grep -c '.' || echo 0)

  output_json "{\"deleted\": $deleted_json, \"deleted_count\": $deleted_count, \"errors\": $delete_errors}"
}

# ============================================================
# 主入口
# ============================================================
main() {
  if [ $# -eq 0 ]; then
    echo "用法: workspace.sh <subcommand> [args]" >&2
    echo "子命令: list | clean [--confirm]" >&2
    exit 2
  fi

  local subcommand="$1"
  shift

  case "$subcommand" in
    list)
      cmd_list "$@"
      ;;
    clean)
      cmd_clean "$@"
      ;;
    *)
      error "未知子命令: $subcommand"
      echo "子命令: list | clean [--confirm]" >&2
      exit 2
      ;;
  esac
}

main "$@"
