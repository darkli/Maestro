#!/bin/bash
# common.sh — 工作流脚本公共函数库
# 版本: 1.0.0
# 兼容: bash 3.2+ (macOS 默认) + Linux
# 用法: source common.sh（由其他脚本加载）

# 防止重复加载
[ "${COMMON_SH_LOADED:-}" = "true" ] && return 0
COMMON_SH_LOADED="true"

# ============================================================
# 全局变量（调用脚本可覆盖）
# ============================================================
VERBOSE="${VERBOSE:-false}"
ERRORS="${ERRORS:-0}"
WARNINGS="${WARNINGS:-0}"

# ============================================================
# 日志函数
# ============================================================
info()    { echo "[INFO] $*"; }
warn()    { echo "[WARN] $*" >&2; WARNINGS=$((WARNINGS + 1)); }
error()   { echo "[ERROR] $*" >&2; ERRORS=$((ERRORS + 1)); }
verbose() { [ "$VERBOSE" = true ] && echo "[DEBUG] $*" || true; }
die()     { echo "[FATAL] $*" >&2; exit 1; }

# ============================================================
# 结构化输出函数
# ============================================================

# 输出 JSON 格式数据（供 Skill 解析）
# 用法: output_json '{"key": "value"}'
output_json() {
  echo "[OUTPUT:JSON] $1"
}

# 输出 Markdown 格式数据（供 Skill 直接展示）
# 用法: output_md "| col1 | col2 |"
output_md() {
  echo "[OUTPUT:MD] $1"
}

# ============================================================
# Markdown 解析函数
# ============================================================

# 提取 Markdown 文件中指定 ## 标题下的内容
# 用法: extract_md_section "Section Title" [file]
# 返回: 该标题下直到下一个 ## 标题的所有内容
extract_md_section() {
  local title="$1"
  local file="${2:-$CLAUDE_MD}"
  [ -f "$file" ] || return 0
  awk -v title="$title" '
    /^## / {
      if (found) exit
      s = $0; sub(/^## */, "", s)
      # 去除尾部空白后精确匹配（避免 "Testing" 误匹配 "Testing Conventions"）
      gsub(/[[:space:]]+$/, "", s)
      if (s == title) { found = 1 }
      next
    }
    found { print }
  ' "$file"
}

# 提取第 N 个代码块的内容（从 stdin 读取）
# 用法: echo "$content" | extract_codeblock 1
extract_codeblock() {
  local n="${1:-1}"
  awk -v n="$n" '
    BEGIN { block_count = 0; in_block = 0 }
    /^```/ {
      if (in_block) { in_block = 0; next }
      block_count++
      if (block_count == n) in_block = 1
      next
    }
    in_block { print }
  '
}

# 提取 Markdown 中 **字段名**: 值 格式的值
# 用法: extract_md_field "状态" file.md
# 返回: 字段值（去除前后空格）
extract_md_field() {
  local field="$1"
  local file="$2"
  [ -f "$file" ] || return 0
  awk -v field="$field" '
    {
      pattern = "\\*\\*" field "\\*\\*"
      if (match($0, pattern)) {
        s = $0
        sub(/.*\*\*[^*]+\*\*[[:space:]]*:[[:space:]]*/, "", s)
        gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
        print s
        exit
      }
    }
  ' "$file"
}

# 统计 Markdown 文件中特定格式标题的数量
# 用法: count_section_headers "### YYYY" file.md
# 返回: 匹配标题的数量
count_section_headers() {
  local pattern="$1"
  local file="$2"
  [ -f "$file" ] || { echo 0; return 0; }
  grep -c "$pattern" "$file" 2>/dev/null || echo 0
}

# 提取 Workspace 文件中的 ## 下游摘要 节
# 用法: extract_downstream_summary file.md
# 返回: 下游摘要节的全部内容
extract_downstream_summary() {
  local file="$1"
  [ -f "$file" ] || return 0
  awk '
    /^## 下游摘要/ { found = 1; next }
    /^## / && found { exit }
    found { print }
  ' "$file"
}

# ============================================================
# CLAUDE.md Capabilities 解析
# ============================================================

# 解析 CLAUDE.md 中的 Capabilities 表格
# 用法: parse_capabilities [claude_md_path]
# 输出: key=value 格式（每行一个），通过 stdout
parse_capabilities() {
  local file="${1:-${CLAUDE_MD:-CLAUDE.md}}"
  [ -f "$file" ] || return 1
  awk -F'|' '
    /^\| *能力/ { next }
    /^\|---/ { next }
    /^\|[[:space:]]+[a-z]/ {
      key = $2; val = $3
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", key)
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", val)
      if (val != "") print key "=" val
    }
  ' "$file"
}

# 查询单个 capability 值
# 用法: get_capability "testing" [claude_md_path]
# 返回: 该 capability 的值（如 "vitest"），不存在返回 "false"
get_capability() {
  local key="$1"
  local file="${2:-${CLAUDE_MD:-CLAUDE.md}}"
  local val
  val=$(parse_capabilities "$file" | awk -F= -v k="$key" '$1 == k { print $2; exit }')
  echo "${val:-false}"
}

# ============================================================
# Transcript 路径计算
# ============================================================

# 获取当前项目的 transcript 目录
# 用法: get_transcript_dir [project_root]
# 返回: transcript 目录绝对路径
get_transcript_dir() {
  local project_root="${1:-$PWD}"
  local project_hash
  # 将 / 替换为 -，去掉开头的 -（保留 _ 以匹配 Claude Code 实际目录命名）
  project_hash=$(echo "$project_root" | sed 's|/|-|g' | sed 's|^-||')
  echo "$HOME/.claude/projects/-${project_hash}"
}

# 获取当前正在使用的 transcript 文件（最新修改的 .jsonl）
# 用法: get_current_transcript [project_root]
# 返回: 最新 transcript 文件的绝对路径，不存在则返回空
get_current_transcript() {
  local project_root="${1:-$PWD}"
  local transcript_dir
  transcript_dir=$(get_transcript_dir "$project_root")
  [ -d "$transcript_dir" ] || return 0
  # 仅顶层 .jsonl 文件（不含子代理目录中的）
  ls -t "$transcript_dir"/*.jsonl 2>/dev/null | head -1
}

# ============================================================
# 跨平台兼容函数
# ============================================================

# 获取文件的最后修改时间（ISO 格式 YYYY-MM-DD）
# 兼容 macOS (BSD stat) 和 Linux (GNU stat)
portable_stat_mtime() {
  local file="$1"
  if stat -f '%Sm' -t '%Y-%m-%d' "$file" 2>/dev/null; then
    return 0
  fi
  # GNU stat fallback
  stat -c '%Y' "$file" 2>/dev/null | awk '{ print strftime("%Y-%m-%d", $1) }' 2>/dev/null || echo "unknown"
}

# 获取目录或文件大小（人类可读格式，如 128K）
# 兼容 macOS 和 Linux
portable_du() {
  local target="$1"
  if [ -d "$target" ]; then
    du -sh "$target" 2>/dev/null | cut -f1
  elif [ -f "$target" ]; then
    du -h "$target" 2>/dev/null | cut -f1
  else
    echo "0"
  fi
}

# ============================================================
# 项目路径与 Workspace 工具
# ============================================================

# 查找项目根目录（通过 CLAUDE.md 或 .git 定位）
# 用法: find_project_root [start_dir]
find_project_root() {
  local dir="${1:-$PWD}"
  while [ "$dir" != "/" ]; do
    if [ -f "$dir/CLAUDE.md" ] || [ -d "$dir/.git" ]; then
      echo "$dir"
      return 0
    fi
    dir=$(dirname "$dir")
  done
  # 默认返回当前目录
  echo "${1:-$PWD}"
}

# 检查 _progress-*.md 文件中指定 workspace 目录的保护状态
# 用法: check_protection "feature-20260220-xxx" progress_dir
# 返回: "protected:进行中" 或 "cleanable:已完成" 或 "unref"（未引用）
check_protection() {
  local ws_name="$1"
  local progress_dir="${2:-.claude/workspace}"
  local found_status=""

  for pf in "$progress_dir"/_progress-*.md; do
    [ -f "$pf" ] || continue
    # 查找引用了此 workspace 的行
    if grep -q "$ws_name" "$pf" 2>/dev/null; then
      # 在 Workspace 行上方查找 **状态**: 行
      local status
      status=$(awk -v ws="$ws_name" '
        /\*\*状态\*\*/ { last_status = $0 }
        index($0, ws) > 0 && last_status != "" {
          s = last_status
          sub(/.*\*\*状态\*\*[[:space:]]*:[[:space:]]*/, "", s)
          gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
          print s
          exit
        }
      ' "$pf")

      case "$status" in
        *已完成*) found_status="cleanable:$status" ;;
        *)        found_status="protected:${status:-未知}" ;;
      esac
      break
    fi
  done

  echo "${found_status:-unref}"
}

# ============================================================
# Workspace 进度检测
# ============================================================

# 根据 workspace 目录类型检测进度（阶段 X/Y）
# 用法: detect_ws_progress "product-20260219-xxx" ws_base_dir
detect_ws_progress() {
  local ws_name="$1"
  local ws_dir="${2:-.claude/workspace}/$ws_name"
  [ -d "$ws_dir" ] || { echo "未知"; return 0; }

  local total=0
  local completed=0
  local prefix
  prefix=$(echo "$ws_name" | sed 's/-.*//')

  case "$prefix" in
    product)
      # product 阶段: 01-problem, 02-solution, 03-spec（00-input 是初始化文件不计入阶段）
      total=3
      [ -f "$ws_dir/01-problem.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/02-solution.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/03-spec.md" ] && completed=$((completed + 1))
      ;;
    doc)
      total=5
      [ -f "$ws_dir/01-analysis.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/02-plan.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/03-changes.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/04-consistency.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/05-review.md" ] && completed=$((completed + 1))
      ;;
    *)
      # feature, bugfix, design, etc.
      total=7
      [ -f "$ws_dir/01-requirements.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/02-design.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/03-testplan.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/04-implementation.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/05-review.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/06-validation.md" ] && completed=$((completed + 1))
      [ -f "$ws_dir/07-delivery.md" ] && completed=$((completed + 1))
      # design type only has 2 stages
      if [ "$prefix" = "design" ]; then
        total=2
        completed=0
        [ -f "$ws_dir/01-requirements.md" ] && completed=$((completed + 1))
        [ -f "$ws_dir/02-design.md" ] && completed=$((completed + 1))
      fi
      ;;
  esac

  echo "阶段 $completed/$total"
}

# ============================================================
# 测试辅助函数
# ============================================================

# 从 CLAUDE.md Testing 节构造测试命令
# 用法: construct_test_command [scope] [type] [file_path] [claude_md]
#   scope: all(默认) / frontend / backend
#   type:  all(默认) / unit / integration / e2e
#   file_path: 可选，指定文件路径
# 输出: JSON { "command": "...", "scope": "...", "type": "..." }
construct_test_command() {
  local scope="${1:-all}"
  local test_type="${2:-all}"
  local file_path="${3:-}"
  local claude_md="${4:-${CLAUDE_MD:-CLAUDE.md}}"

  [ -f "$claude_md" ] || { error "CLAUDE.md 未找到: $claude_md"; return 1; }

  # 提取 Testing section 中的代码块
  local testing_section
  testing_section=$(extract_md_section "Testing" "$claude_md")
  [ -n "$testing_section" ] || { error "CLAUDE.md 中未找到 Testing 节"; return 1; }

  local cmd=""

  if [ -n "$file_path" ]; then
    # 指定文件：使用框架运行指定文件
    local framework
    framework=$(get_capability "testing" "$claude_md")
    case "$framework" in
      vitest|jest)
        # 判断文件是否在 backend 目录中
        case "$file_path" in
          backend/*)
            local rel_path="${file_path#backend/}"
            cmd="cd backend && npx $framework run $rel_path" ;;
          *)
            cmd="npx $framework run $file_path" ;;
        esac
        ;;
      pytest)
        cmd="pytest $file_path" ;;
      *)
        cmd="$framework $file_path" ;;
    esac
  else
    # 按 scope 提取命令
    case "$scope" in
      frontend)
        cmd=$(echo "$testing_section" | extract_codeblock 1 | grep -v '^[[:space:]]*#' | grep -E -i -m1 'npm|npx|yarn|pnpm' | sed 's/^[[:space:]]*//')
        # fallback: 前端测试命令通常是第一个代码块的非 backend 命令
        [ -z "$cmd" ] && cmd=$(echo "$testing_section" | extract_codeblock 1 | grep -v '^[[:space:]]*#' | grep -v 'backend' | head -1 | sed 's/^[[:space:]]*//')
        ;;
      backend)
        # 查找包含 "backend" 的测试命令
        cmd=$(echo "$testing_section" | extract_codeblock 1 | grep -v '^[[:space:]]*#' | grep -m1 'backend' | sed 's/^[[:space:]]*//')
        ;;
      all|*)
        # 查找 test:all 或全量测试命令
        cmd=$(echo "$testing_section" | extract_codeblock 1 | grep -v '^[[:space:]]*#' | grep -E -m1 'test:all|test_all|test --' | sed 's/^[[:space:]]*//')
        # fallback: 取 "Run once" 相关命令（排除 npm test:watch 等变体）
        [ -z "$cmd" ] && cmd=$(echo "$testing_section" | extract_codeblock 1 | grep -v '^[[:space:]]*#' | grep -E -m1 'npm test([[:space:]]|$)' | sed 's/^[[:space:]]*//')
        ;;
    esac
  fi

  [ -z "$cmd" ] && { error "无法从 CLAUDE.md 中构造 scope=$scope 的测试命令"; return 1; }

  # 去除行内注释（要求 # 前至少一个空格，避免误截 URL 中的 #）
  cmd=$(echo "$cmd" | sed 's/[[:space:]][[:space:]]*#.*$//' | sed 's/[[:space:]]*$//')

  # JSON escape the command
  local cmd_escaped
  cmd_escaped=$(echo "$cmd" | sed 's/"/\\"/g')

  output_json "{\"command\": \"$cmd_escaped\", \"scope\": \"$scope\", \"type\": \"$test_type\"}"
}

# 从测试输出提取结果数字（vitest/jest 格式）
# 用法: echo "$test_output" | parse_test_output
# 输出: JSON { "passed": N, "failed": N, "skipped": N, "duration": "Xs", "total": N }
parse_test_output() {
  awk '
  BEGIN {
    passed = 0; failed = 0; skipped = 0; duration = "unknown"; total = 0
  }

  # vitest 格式: "  Tests  42 passed | 2 failed | 1 skipped (45)"
  # 注意: 此规则也会匹配 jest 的 "Tests:" 行，但结果会被下面 /^Tests:/ 规则覆盖，最终值正确
  /Tests.*passed/ {
    s = $0
    if (match(s, /([0-9]+) passed/)) {
      p = substr(s, RSTART); sub(/ .*/, "", p); passed = p + 0
    }
    if (match(s, /([0-9]+) failed/)) {
      f = substr(s, RSTART); sub(/ .*/, "", f); failed = f + 0
    }
    if (match(s, /([0-9]+) skipped/)) {
      sk = substr(s, RSTART); sub(/ .*/, "", sk); skipped = sk + 0
    }
    if (match(s, /\(([0-9]+)\)/)) {
      t = substr(s, RSTART + 1); sub(/\).*/, "", t); total = t + 0
    }
  }

  # vitest/jest 格式: "Duration  3.21s (transform 0.34s, setup 0.12s, ...)"
  /Duration/ {
    s = $0
    if (match(s, /[0-9]+\.[0-9]+s/)) {
      duration = substr(s, RSTART, RLENGTH)
    } else if (match(s, /[0-9]+s/)) {
      duration = substr(s, RSTART, RLENGTH)
    }
  }

  # jest 格式: "Test Suites: 1 failed, 3 passed, 4 total"
  /Test Suites:/ { next }

  # jest 格式: "Tests:       2 failed, 40 passed, 2 skipped, 44 total"
  /^Tests:/ {
    s = $0
    if (match(s, /([0-9]+) passed/)) {
      p = substr(s, RSTART); sub(/ .*/, "", p); passed = p + 0
    }
    if (match(s, /([0-9]+) failed/)) {
      f = substr(s, RSTART); sub(/ .*/, "", f); failed = f + 0
    }
    if (match(s, /([0-9]+) skipped/)) {
      sk = substr(s, RSTART); sub(/ .*/, "", sk); skipped = sk + 0
    }
    if (match(s, /([0-9]+) total/)) {
      t = substr(s, RSTART); sub(/ .*/, "", t); total = t + 0
    }
  }

  # jest 格式: "Time:        3.456 s"
  /^Time:/ {
    s = $0
    if (match(s, /[0-9]+\.[0-9]+ s/)) {
      duration = substr(s, RSTART, RLENGTH)
      gsub(/ /, "", duration)
    }
  }

  END {
    if (total == 0) total = passed + failed + skipped
    printf "[OUTPUT:JSON] {\"passed\": %d, \"failed\": %d, \"skipped\": %d, \"duration\": \"%s\", \"total\": %d}\n", passed, failed, skipped, duration, total
  }
  '
}

# 构造覆盖率命令（在测试命令基础上追加 --coverage）
# 用法: construct_coverage_command [scope] [claude_md]
# 输出: JSON { "command": "...", "scope": "..." }
construct_coverage_command() {
  local scope="${1:-all}"
  local claude_md="${2:-${CLAUDE_MD:-CLAUDE.md}}"

  [ -f "$claude_md" ] || { error "CLAUDE.md 未找到: $claude_md"; return 1; }

  local framework
  framework=$(get_capability "testing" "$claude_md")

  local base_cmd=""
  # 先构造基础测试命令
  local base_json
  base_json=$(construct_test_command "$scope" "all" "" "$claude_md" 2>/dev/null | grep '^\[OUTPUT:JSON\]' | sed 's/^\[OUTPUT:JSON\] //')
  if [ -n "$base_json" ]; then
    # 提取 command 字段（用 awk 正确处理含转义引号的值）
    base_cmd=$(echo "$base_json" | awk '{
      s = $0
      # 找到 "command": " 的位置
      key = "\"command\": \""
      i = index(s, key)
      if (i == 0) { key = "\"command\":\""; i = index(s, key) }
      if (i > 0) {
        s = substr(s, i + length(key))
        # 找到未转义的结束引号
        result = ""
        while (length(s) > 0) {
          c = substr(s, 1, 1)
          if (c == "\\") {
            result = result substr(s, 1, 2)
            s = substr(s, 3)
          } else if (c == "\"") {
            break
          } else {
            result = result c
            s = substr(s, 2)
          }
        }
        print result
      }
    }')
  fi

  [ -z "$base_cmd" ] && { error "无法构造 scope=$scope 的覆盖率命令"; return 1; }

  # 追加覆盖率参数
  local cov_cmd=""
  case "$framework" in
    vitest)
      # vitest: 追加 --coverage
      case "$base_cmd" in
        *"npm test"*|*"npm run test"*)
          cov_cmd="$base_cmd -- --coverage" ;;
        *npx*)
          cov_cmd="$base_cmd --coverage" ;;
        *)
          cov_cmd="$base_cmd --coverage" ;;
      esac
      ;;
    jest)
      case "$base_cmd" in
        *"npm test"*|*"npm run test"*)
          cov_cmd="$base_cmd -- --coverage" ;;
        *)
          cov_cmd="$base_cmd --coverage" ;;
      esac
      ;;
    pytest)
      cov_cmd="$base_cmd --cov" ;;
    *)
      cov_cmd="$base_cmd --coverage" ;;
  esac

  local cmd_escaped
  cmd_escaped=$(echo "$cov_cmd" | sed 's/"/\\"/g')

  output_json "{\"command\": \"$cmd_escaped\", \"scope\": \"$scope\"}"
}

# 从覆盖率输出提取指标（vitest/jest/istanbul 格式）
# 用法: echo "$coverage_output" | parse_coverage_output
# 输出: JSON { "statements": "75.3%", "branches": "70.1%", "functions": "85.7%", "lines": "76.2%", "files": [...] }
parse_coverage_output() {
  awk '
  function json_escape(s) {
    gsub(/\\/, "\\\\", s)
    gsub(/"/, "\\\"", s)
    return s
  }
  BEGIN {
    stmts = "0%"; branches = "0%"; funcs = "0%"; lines_cov = "0%"
    file_count = 0
    in_table = 0
  }

  # istanbul/vitest/jest 格式总计行:
  # All files  |   75.3 |   70.1 |   85.7 |   76.2 |
  /All files/ && /\|/ {
    n = split($0, parts, "|")
    if (n >= 5) {
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", parts[2]); stmts = parts[2] "%"
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", parts[3]); branches = parts[3] "%"
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", parts[4]); funcs = parts[4] "%"
      gsub(/^[[:space:]]+|[[:space:]]+$/, "", parts[5]); lines_cov = parts[5] "%"
    }
    in_table = 1
    next
  }

  # 逐文件行: src/foo.ts | 50 | 30 | 60 | 45 | 1-10,20-30
  in_table && /\|/ && !/^-/ && !/File/ {
    n = split($0, parts, "|")
    if (n >= 5) {
      fname = parts[1]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", fname)
      fstmt = parts[2]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", fstmt)
      fbranch = parts[3]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", fbranch)
      ffunc = parts[4]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", ffunc)
      fline = parts[5]; gsub(/^[[:space:]]+|[[:space:]]+$/, "", fline)

      if (fname != "" && fstmt ~ /^[0-9]/) {
        file_count++
        file_names[file_count] = fname
        file_stmts[file_count] = fstmt + 0
        file_branches[file_count] = fbranch + 0
        file_funcs[file_count] = ffunc + 0
        file_lines[file_count] = fline + 0
      }
    }
  }

  # 空行、分隔线（=== 或 ---）、或非管道行结束表格
  in_table && (/^[[:space:]]*$/ || /^[=\-]{3,}$/ || (!/\|/ && !/^-/)) { in_table = 0 }

  END {
    # 按语句覆盖率排序（冒泡），找出最低的 10 个
    for (i = 1; i <= file_count; i++) {
      for (j = i + 1; j <= file_count; j++) {
        if (file_stmts[j] < file_stmts[i]) {
          # swap
          tmp = file_names[i]; file_names[i] = file_names[j]; file_names[j] = tmp
          tmp = file_stmts[i]; file_stmts[i] = file_stmts[j]; file_stmts[j] = tmp
          tmp = file_branches[i]; file_branches[i] = file_branches[j]; file_branches[j] = tmp
          tmp = file_funcs[i]; file_funcs[i] = file_funcs[j]; file_funcs[j] = tmp
          tmp = file_lines[i]; file_lines[i] = file_lines[j]; file_lines[j] = tmp
        }
      }
    }

    # Build files JSON array (top 10 lowest)
    max_files = file_count
    if (max_files > 10) max_files = 10

    files_json = "["
    for (i = 1; i <= max_files; i++) {
      if (i > 1) files_json = files_json ", "
      files_json = files_json "{\"file\": \"" json_escape(file_names[i]) "\", \"statements\": " file_stmts[i] ", \"branches\": " file_branches[i] ", \"functions\": " file_funcs[i] ", \"lines\": " file_lines[i] "}"
    }
    files_json = files_json "]"

    printf "[OUTPUT:JSON] {\"statements\": \"%s\", \"branches\": \"%s\", \"functions\": \"%s\", \"lines\": \"%s\", \"file_count\": %d, \"lowest_files\": %s}\n", stmts, branches, funcs, lines_cov, file_count, files_json
  }
  '
}
