#!/bin/bash
# clean.sh — 工作流文件清理脚本（重置已安装的工作流文件）
# 用法: bash clean.sh <subcommand> [args]
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
CLAUDE_DIR="$PROJECT_ROOT/.claude"

# ============================================================
# 删除目标：这些路径会在 execute --confirm 时被删除
# 格式: "路径|类型|描述"（类型: dir=目录, file=文件）
# ============================================================
# DELETE_TARGETS 使用换行分隔的字符串（bash 3.2 兼容，不用数组）
DELETE_TARGETS=".claude/skills/|dir|skills
.claude/agents/|dir|agents
.claude/hooks/|dir|hooks
.claude/settings.json|file|settings"

# ============================================================
# 保留目标：不会被删除的路径
# 格式: "路径|描述"
# ============================================================
PRESERVE_TARGETS=".claude/skills/f-init/|工作流安装入口（保留以便重装）
.claude/context/|跨对话上下文数据
.claude/workspace/|Workspace 工作目录
.claude/settings.local.json|本地个性化配置
.claude/scripts/|脚本工具（clean.sh 等）"

# ============================================================
# 辅助函数
# ============================================================

# 统计目录中指定文件类型的数量，生成描述字符串
# 用法: count_dir_content ".claude/skills/" "dir"
# 返回: "12 个 Skill" / "10 个 Agent" / "8 个 Hook" / 目录或文件计数
count_dir_content() {
  local rel_path="$1"
  local item_type="$2"
  local abs_path="$PROJECT_ROOT/$rel_path"

  if [ ! -e "$abs_path" ]; then
    echo "不存在"
    return 0
  fi

  case "$item_type" in
    skills)
      local count
      count=$(find "$abs_path" -name "SKILL.md" 2>/dev/null | wc -l | tr -d ' ')
      echo "${count} 个 Skill"
      ;;
    agents)
      local count
      count=$(find "$abs_path" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')
      echo "${count} 个 Agent"
      ;;
    hooks)
      local count
      count=$(find "$abs_path" -maxdepth 1 -name "*.sh" -type f 2>/dev/null | wc -l | tr -d ' ')
      echo "${count} 个 Hook"
      ;;
    file)
      echo "文件"
      ;;
    *)
      local count
      count=$(find "$abs_path" -maxdepth 1 2>/dev/null | tail -n +2 | wc -l | tr -d ' ')
      echo "${count} 个文件"
      ;;
  esac
}

# 检查路径是否存在（相对于 PROJECT_ROOT）
path_exists() {
  local rel_path="$1"
  [ -e "$PROJECT_ROOT/$rel_path" ]
}

# ============================================================
# 内部：构建扫描 JSON
# ============================================================
build_scan_json() {
  # 构建 delete 数组
  local delete_json="["
  local first=true

  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local rel_path
    local item_type
    local item_desc
    rel_path=$(echo "$line" | awk -F'|' '{print $1}')
    item_type=$(echo "$line" | awk -F'|' '{print $2}')
    item_desc=$(echo "$line" | awk -F'|' '{print $3}')

    # 判断存在性
    local exists="false"
    path_exists "$rel_path" && exists="true"

    # 统计内容（dir 类型按 item_desc 区分子类型，file 类型直接用 item_type）
    local content
    if [ "$item_type" = "file" ]; then
      content=$(count_dir_content "$rel_path" "file")
    else
      content=$(count_dir_content "$rel_path" "$item_desc")
    fi

    if [ "$first" = true ]; then
      delete_json="${delete_json}{\"path\": \"$rel_path\", \"content\": \"$content\", \"exists\": $exists}"
      first=false
    else
      delete_json="${delete_json}, {\"path\": \"$rel_path\", \"content\": \"$content\", \"exists\": $exists}"
    fi
  done <<EOF
$DELETE_TARGETS
EOF
  delete_json="${delete_json}]"

  # 构建 preserve 数组
  local preserve_json="["
  first=true

  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local rel_path
    local reason
    rel_path=$(echo "$line" | awk -F'|' '{print $1}')
    reason=$(echo "$line" | awk -F'|' '{print $2}')

    local exists="false"
    path_exists "$rel_path" && exists="true"

    if [ "$first" = true ]; then
      preserve_json="${preserve_json}{\"path\": \"$rel_path\", \"reason\": \"$reason\", \"exists\": $exists}"
      first=false
    else
      preserve_json="${preserve_json}, {\"path\": \"$rel_path\", \"reason\": \"$reason\", \"exists\": $exists}"
    fi
  done <<EOF
$PRESERVE_TARGETS
EOF
  preserve_json="${preserve_json}]"

  output_json "{\"delete\": $delete_json, \"preserve\": $preserve_json}"
}

# ============================================================
# 子命令：scan
# ============================================================
cmd_scan() {
  build_scan_json
}

# ============================================================
# 子命令：execute [--confirm]
# ============================================================
cmd_execute() {
  local confirm=false
  local arg
  for arg in "$@"; do
    [ "$arg" = "--confirm" ] && confirm=true
  done

  # 不带 --confirm 时等同于 scan
  if [ "$confirm" = false ]; then
    build_scan_json
    return 0
  fi

  # 执行删除
  local deleted_json="["
  local first_del=true

  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local rel_path
    local item_type
    rel_path=$(echo "$line" | awk -F'|' '{print $1}')
    item_type=$(echo "$line" | awk -F'|' '{print $2}')
    local abs_path="$PROJECT_ROOT/$rel_path"

    if [ ! -e "$abs_path" ]; then
      continue
    fi

    if [ "$item_type" = "dir" ]; then
      rm -rf "$abs_path"
    else
      rm -f "$abs_path"
    fi

    if [ "$first_del" = true ]; then
      deleted_json="${deleted_json}\"$rel_path\""
      first_del=false
    else
      deleted_json="${deleted_json}, \"$rel_path\""
    fi
  done <<EOF
$DELETE_TARGETS
EOF
  deleted_json="${deleted_json}]"

  # 验证：确认删除目标已消失
  local all_deleted=true
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local rel_path
    rel_path=$(echo "$line" | awk -F'|' '{print $1}')
    if [ -e "$PROJECT_ROOT/$rel_path" ]; then
      all_deleted=false
      break
    fi
  done <<EOF
$DELETE_TARGETS
EOF

  # 验证：确认保留目标仍然存在（仅验证原本存在的）
  local preserved_json="["
  local first_pres=true

  while IFS= read -r line; do
    [ -z "$line" ] && continue
    local rel_path
    rel_path=$(echo "$line" | awk -F'|' '{print $1}')
    # 仅收录当前仍然存在的保留项
    if [ -e "$PROJECT_ROOT/$rel_path" ]; then
      if [ "$first_pres" = true ]; then
        preserved_json="${preserved_json}\"$rel_path\""
        first_pres=false
      else
        preserved_json="${preserved_json}, \"$rel_path\""
      fi
    fi
  done <<EOF
$PRESERVE_TARGETS
EOF
  preserved_json="${preserved_json}]"

  local verified="true"
  [ "$all_deleted" = false ] && verified="false"

  output_json "{\"deleted\": $deleted_json, \"preserved\": $preserved_json, \"verified\": $verified}"
}

# ============================================================
# 主入口
# ============================================================
main() {
  if [ $# -eq 0 ]; then
    echo "用法: clean.sh <subcommand> [args]" >&2
    echo "子命令: scan | execute [--confirm]" >&2
    exit 2
  fi

  local subcommand="$1"
  shift

  case "$subcommand" in
    scan)
      cmd_scan "$@"
      ;;
    execute)
      cmd_execute "$@"
      ;;
    *)
      error "未知子命令: $subcommand"
      echo "子命令: scan | execute [--confirm]" >&2
      exit 2
      ;;
  esac
}

main "$@"
