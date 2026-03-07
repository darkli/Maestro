#!/bin/bash
# init.sh — 工作流初始化与升级脚本
# 用法: bash docs/flow/workflow-template/scripts/init.sh [选项]
# 版本: 1.2.0
# 兼容: macOS (BSD awk/sed) + Linux (GNU awk/sed)

set -euo pipefail

# ============================================================
# Constants
# ============================================================
SCRIPT_VERSION="1.2.0"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
TEMPLATE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Resolve project root (4 levels up from scripts/init.sh: scripts → workflow-template → flow → docs → root)
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
CLAUDE_MD="$PROJECT_ROOT/CLAUDE.md"

# Load common functions
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

# Defaults
MODE="init"
TARGET_DIR="$PROJECT_ROOT/.claude"
DRY_RUN=false
VERBOSE=false
SKIP_CLAUDE_MD=false

# Temp dir (cleaned up on exit)
TMP_DIR=""
ERRORS=0
WARNINGS=0
INSTALLED_FILES=0
INSTALLED_SCRIPTS=0

# Capability variables (defaults)
CAP_frontend="false"
CAP_backend_api="false"
CAP_database="false"
CAP_i18n="false"
CAP_testing="false"
CAP_cross_compile="false"
CAP_design_system="false"
CAP_ci_cd="false"
CAP_monorepo="false"
CAP_static_types="false"
CAP_websocket="false"

# Detection variables
INSTALL_CMD=""
DEV_CMD=""
BUILD_CMD=""
TEST_CMD=""
TEST_WATCH_CMD=""
LINT_CMD=""
FORMAT_CMD=""
FILE_PATTERNS=""
SOURCE_PATTERNS=""
TEST_FILE_PATTERNS=""
TEST_CMD_PATTERNS=""
COVERAGE_FILE=""
COVERAGE_FORMAT="json"
COVERAGE_THRESHOLD=80
DET_AGENT_VERSION_FILE=""
DET_AGENT_BUILD_CMD=""

# ============================================================
# Cleanup
# ============================================================
cleanup() {
  [ -n "$TMP_DIR" ] && [ -d "$TMP_DIR" ] && rm -rf "$TMP_DIR"
}
trap cleanup EXIT

# ============================================================
# Argument Parsing
# ============================================================
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --mode=*)       MODE="${1#--mode=}" ;;
      --template-dir=*) TEMPLATE_DIR="${1#--template-dir=}" ;;
      --target-dir=*) TARGET_DIR="${1#--target-dir=}" ;;
      --dry-run)      DRY_RUN=true ;;
      --verbose)      VERBOSE=true ;;
      --skip-claude-md) SKIP_CLAUDE_MD=true ;;
      -h|--help)
        echo "用法: init.sh [选项]"
        echo "  --mode=init|upgrade   运行模式（默认 init）"
        echo "  --template-dir=DIR    模板目录（默认自动检测）"
        echo "  --target-dir=DIR      目标目录（默认 .claude）"
        echo "  --dry-run             仅输出计划，不执行"
        echo "  --verbose             详细日志"
        echo "  --skip-claude-md      跳过 CLAUDE.md 生成/验证"
        exit 0
        ;;
      *) die "未知参数: $1" ;;
    esac
    shift
  done

  # Validate
  [ -d "$TEMPLATE_DIR" ] || die "模板目录不存在: $TEMPLATE_DIR"
  [ "$MODE" = "init" ] || [ "$MODE" = "upgrade" ] || die "无效模式: $MODE（仅支持 init 或 upgrade）"

  # Create temp dir
  TMP_DIR=$(mktemp -d "${TMPDIR:-/tmp}/init-XXXXXX")
  mkdir -p "$TMP_DIR/ps"
  verbose "临时目录: $TMP_DIR"
}

# ============================================================
# Utility functions: extract_md_section, extract_codeblock
# are now provided by common.sh
# ============================================================

# ============================================================
# Project Detection
# ============================================================
detect_project() {
  info "探测项目技术栈..."

  # Language/framework detection via marker files
  if [ -f "$PROJECT_ROOT/package.json" ]; then
    detect_node_project
  fi
  [ -f "$PROJECT_ROOT/go.mod" ] && [ "$CAP_static_types" = "false" ] && CAP_static_types="go"
  [ -f "$PROJECT_ROOT/Cargo.toml" ] && CAP_static_types="rust"
  if [ -f "$PROJECT_ROOT/pyproject.toml" ] || [ -f "$PROJECT_ROOT/setup.py" ] || [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    detect_python_project
  fi

  # Bash/Shell project (no other language detected, but has .sh files)
  if [ "$CAP_frontend" = "false" ] && [ "$CAP_backend_api" = "false" ] && [ "$CAP_static_types" = "false" ]; then
    local sh_count
    sh_count=$(find "$PROJECT_ROOT" -maxdepth 2 -name "*.sh" ! -path "*/.git/*" ! -path "*/node_modules/*" 2>/dev/null | wc -l | tr -d ' ')
    if [ "${sh_count:-0}" -gt 0 ]; then
      detect_bash_project
    fi
  fi

  # CI/CD
  [ -d "$PROJECT_ROOT/.github/workflows" ] && CAP_ci_cd="github-actions"
  [ -f "$PROJECT_ROOT/.gitlab-ci.yml" ] && CAP_ci_cd="gitlab-ci"

  # Design system
  if [ -f "$PROJECT_ROOT/tailwind.config.js" ] || [ -f "$PROJECT_ROOT/tailwind.config.ts" ]; then
    CAP_design_system="tailwind"
  fi

  # i18n details
  if [ -d "$PROJECT_ROOT/locales" ] || [ -d "$PROJECT_ROOT/i18n" ]; then
    [ "$CAP_i18n" = "false" ] && CAP_i18n="true"
  fi

  # Monorepo detection
  if [ -f "$PROJECT_ROOT/lerna.json" ] || [ -f "$PROJECT_ROOT/pnpm-workspace.yaml" ]; then
    CAP_monorepo="true"
  fi

  # Commit language detection (Chinese if > 50% of recent commits contain CJK)
  if command -v git >/dev/null 2>&1 && [ -d "$PROJECT_ROOT/.git" ]; then
    local total cjk
    total=$(cd "$PROJECT_ROOT" && git log --oneline -20 2>/dev/null | wc -l | tr -d ' ') || true
    # Use grep with Unicode character range for CJK detection (portable across BSD/GNU)
    cjk=$(cd "$PROJECT_ROOT" && git log --oneline -20 2>/dev/null | grep '[一-龥]' | wc -l | tr -d ' ') || true
    if [ "${total:-0}" -gt 0 ] && [ "${cjk:-0}" -gt 0 ]; then
      if [ $((cjk * 2)) -ge "$total" ]; then
        COMMIT_LANG="Chinese"
      else
        COMMIT_LANG="English"
      fi
    fi
  fi
  COMMIT_LANG="${COMMIT_LANG:-English}"

  # Indentation detection (sample a source file)
  INDENTATION="2-space"
  local sample_file=""
  sample_file=$(find "$PROJECT_ROOT/src" "$PROJECT_ROOT/backend/src" "$PROJECT_ROOT/app" \( -name "*.ts" -o -name "*.js" -o -name "*.tsx" -o -name "*.py" \) 2>/dev/null | head -1 || true)
  # Bash fallback: no known source dirs, search .sh files
  if [ -z "$sample_file" ]; then
    sample_file=$(find "$PROJECT_ROOT" -maxdepth 2 -name "*.sh" \
      ! -path "*/.git/*" ! -path "*/node_modules/*" 2>/dev/null | head -1 || true)
  fi
  if [ -n "$sample_file" ] && [ -f "$sample_file" ]; then
    local tab_count space_count
    tab_count=$(head -50 "$sample_file" | grep -c '^	' || true)
    space_count=$(head -50 "$sample_file" | grep -c '^  ' || true)
    if [ "${tab_count:-0}" -gt "${space_count:-0}" ]; then
      INDENTATION="tab"
    elif head -50 "$sample_file" | grep -q '^    [^ ]' 2>/dev/null; then
      INDENTATION="4-space"
    fi
  fi

  # --- Derived path/value detection (for CLAUDE.md placeholders) ---

  # Types file
  DET_TYPES_FILE=""
  [ -f "$PROJECT_ROOT/types.ts" ] && DET_TYPES_FILE="types.ts"
  [ -f "$PROJECT_ROOT/src/types.ts" ] && DET_TYPES_FILE="src/types.ts"
  [ -f "$PROJECT_ROOT/src/types/index.ts" ] && DET_TYPES_FILE="src/types/index.ts"

  # Routes dir
  DET_ROUTES_DIR=""
  [ -d "$PROJECT_ROOT/backend/src/routes" ] && DET_ROUTES_DIR="backend/src/routes/"
  [ -d "$PROJECT_ROOT/src/routes" ] && [ -z "$DET_ROUTES_DIR" ] && DET_ROUTES_DIR="src/routes/"
  [ -d "$PROJECT_ROOT/app/routes" ] && [ -z "$DET_ROUTES_DIR" ] && DET_ROUTES_DIR="app/routes/"
  [ -d "$PROJECT_ROOT/app/api" ] && [ -z "$DET_ROUTES_DIR" ] && DET_ROUTES_DIR="app/api/"
  [ -d "$PROJECT_ROOT/api" ] && [ -z "$DET_ROUTES_DIR" ] && DET_ROUTES_DIR="api/"

  # API service file
  DET_API_FILE=""
  [ -f "$PROJECT_ROOT/services/api.ts" ] && DET_API_FILE="services/api.ts"
  [ -f "$PROJECT_ROOT/src/services/api.ts" ] && DET_API_FILE="src/services/api.ts"
  [ -f "$PROJECT_ROOT/src/api/index.ts" ] && DET_API_FILE="src/api/index.ts"
  [ -f "$PROJECT_ROOT/app/main.py" ] && [ -z "$DET_API_FILE" ] && DET_API_FILE="app/main.py"
  [ -f "$PROJECT_ROOT/app.py" ] && [ -z "$DET_API_FILE" ] && DET_API_FILE="app.py"
  [ -f "$PROJECT_ROOT/manage.py" ] && [ -z "$DET_API_FILE" ] && DET_API_FILE="manage.py"

  # Locale dir and file list
  DET_LOCALE_DIR=""
  DET_LOCALE_LIST=""
  [ -d "$PROJECT_ROOT/locales" ] && DET_LOCALE_DIR="locales/"
  [ -d "$PROJECT_ROOT/i18n" ] && DET_LOCALE_DIR="i18n/"
  if [ -n "$DET_LOCALE_DIR" ]; then
    DET_LOCALE_LIST=$(find "$PROJECT_ROOT/${DET_LOCALE_DIR%/}" -maxdepth 1 -type f -exec basename {} \; 2>/dev/null | sort | awk 'NR>1{printf ", "} {printf "%s", $0} END{if(NR>0) print ""}')
  fi

  # Design system config file
  DET_TOKEN_CONFIG=""
  [ -f "$PROJECT_ROOT/tailwind.config.js" ] && DET_TOKEN_CONFIG="tailwind.config.js"
  [ -f "$PROJECT_ROOT/tailwind.config.ts" ] && DET_TOKEN_CONFIG="tailwind.config.ts"

  # Database access file
  DET_DB_FILE=""
  for p in "backend/src/database" "src/database" "backend/src/db" "src/db"; do
    [ -d "$PROJECT_ROOT/$p" ] || continue
    local found
    found=$(find "$PROJECT_ROOT/$p" -maxdepth 1 \( -name "*.ts" -o -name "*.js" \) 2>/dev/null | head -1 || true)
    if [ -n "$found" ]; then
      DET_DB_FILE="${p}/$(basename "$found")"
      break
    fi
  done
  # Python database files
  if [ -z "$DET_DB_FILE" ]; then
    [ -f "$PROJECT_ROOT/app/database.py" ] && DET_DB_FILE="app/database.py"
    [ -f "$PROJECT_ROOT/app/db.py" ] && [ -z "$DET_DB_FILE" ] && DET_DB_FILE="app/db.py"
    [ -f "$PROJECT_ROOT/database.py" ] && [ -z "$DET_DB_FILE" ] && DET_DB_FILE="database.py"
  fi

  # Frontend/Backend stack strings (composed from capabilities)
  DET_FE_STACK=""
  if [ "$CAP_frontend" != "false" ]; then
    DET_FE_STACK="$CAP_frontend"
    [ "$CAP_static_types" != "false" ] && DET_FE_STACK="$DET_FE_STACK + ${CAP_static_types}"
    [ "$CAP_design_system" != "false" ] && DET_FE_STACK="$DET_FE_STACK + ${CAP_design_system}"
  fi
  DET_BE_STACK=""
  if [ "$CAP_backend_api" != "false" ]; then
    case "$CAP_backend_api" in
      FastAPI|Flask|Django|Starlette)
        DET_BE_STACK="Python + $CAP_backend_api"
        ;;
      *)
        DET_BE_STACK="Node.js + $CAP_backend_api"
        [ "$CAP_static_types" = "typescript" ] && DET_BE_STACK="$DET_BE_STACK + TypeScript"
        ;;
    esac
    [ "$CAP_database" != "false" ] && DET_BE_STACK="$DET_BE_STACK + ${CAP_database}"
  fi

  verbose "检测结果: frontend=$CAP_frontend backend=$CAP_backend_api testing=$CAP_testing"
  verbose "检测结果: i18n=$CAP_i18n design=$CAP_design_system types=$CAP_static_types"
  verbose "检测路径: types=$DET_TYPES_FILE routes=$DET_ROUTES_DIR api=$DET_API_FILE"
}

detect_node_project() {
  local pkg="$PROJECT_ROOT/package.json"

  # Dependencies detection (use || true to prevent set -e from aborting)
  grep -q '"react"' "$pkg" 2>/dev/null         && CAP_frontend="React" || true
  grep -q '"vue"' "$pkg" 2>/dev/null           && CAP_frontend="Vue" || true
  grep -q '"svelte"' "$pkg" 2>/dev/null        && CAP_frontend="Svelte" || true
  grep -q '"express"' "$pkg" 2>/dev/null       && CAP_backend_api="Express" || true
  grep -q '"fastify"' "$pkg" 2>/dev/null       && CAP_backend_api="Fastify" || true
  grep -q '"koa"' "$pkg" 2>/dev/null           && CAP_backend_api="Koa" || true
  grep -q '"vitest"' "$pkg" 2>/dev/null        && CAP_testing="vitest" || true
  grep -q '"jest"' "$pkg" 2>/dev/null          && [ "$CAP_testing" = "false" ] && CAP_testing="jest" || true
  grep -q '"react-i18next"' "$pkg" 2>/dev/null && CAP_i18n="react-i18next" || true
  grep -q '"vue-i18n"' "$pkg" 2>/dev/null      && CAP_i18n="vue-i18n" || true
  grep -q '"tailwindcss"' "$pkg" 2>/dev/null   && CAP_design_system="tailwind" || true
  grep -q '"typescript"' "$pkg" 2>/dev/null    && CAP_static_types="typescript" || true
  grep -q '"mysql"' "$pkg" 2>/dev/null         && CAP_database="mysql" || true
  grep -q '"mysql2"' "$pkg" 2>/dev/null        && CAP_database="mysql" || true
  grep -q '"pg"' "$pkg" 2>/dev/null            && CAP_database="postgresql" || true
  grep -q '"mongoose"' "$pkg" 2>/dev/null      && CAP_database="mongodb" || true
  grep -q '"sqlite3"' "$pkg" 2>/dev/null       && CAP_database="sqlite" || true
  # WebSocket detection
  grep -q '"ws"' "$pkg" 2>/dev/null            && CAP_websocket="true" || true
  grep -q '"socket.io"' "$pkg" 2>/dev/null     && CAP_websocket="true" || true

  # Also check backend/package.json if it exists
  local bpkg="$PROJECT_ROOT/backend/package.json"
  if [ -f "$bpkg" ]; then
    grep -q '"express"' "$bpkg" 2>/dev/null   && CAP_backend_api="Express" || true
    grep -q '"mysql"' "$bpkg" 2>/dev/null     && CAP_database="mysql" || true
    grep -q '"mysql2"' "$bpkg" 2>/dev/null    && CAP_database="mysql" || true
    grep -q '"pg"' "$bpkg" 2>/dev/null        && CAP_database="postgresql" || true
    grep -q '"vitest"' "$bpkg" 2>/dev/null    && CAP_testing="vitest" || true
    grep -q '"ws"' "$bpkg" 2>/dev/null        && CAP_websocket="true" || true
    grep -q '"socket.io"' "$bpkg" 2>/dev/null && CAP_websocket="true" || true
  fi

  # Install command (based on lock file type)
  if [ -f "$PROJECT_ROOT/pnpm-lock.yaml" ]; then
    INSTALL_CMD="pnpm install"
  elif [ -f "$PROJECT_ROOT/yarn.lock" ]; then
    INSTALL_CMD="yarn install"
  elif [ -f "$PROJECT_ROOT/bun.lockb" ]; then
    INSTALL_CMD="bun install"
  else
    INSTALL_CMD="npm install"
  fi
  # If backend dir exists, add backend install
  [ -d "$PROJECT_ROOT/backend" ] && [ -f "$bpkg" ] && \
    INSTALL_CMD="$INSTALL_CMD"$'\n'"cd backend && $INSTALL_CMD"

  # Extract npm scripts
  DEV_CMD=$(extract_npm_script "dev" "$pkg")
  BUILD_CMD=$(extract_npm_script "build" "$pkg")
  TEST_CMD=$(extract_npm_script "test" "$pkg")
  TEST_WATCH_CMD=$(extract_npm_script "test:watch" "$pkg")
  LINT_CMD=$(extract_npm_script "lint" "$pkg")
  FORMAT_CMD=$(extract_npm_script "format" "$pkg")

  # Convert script names to runnable commands
  [ -n "$DEV_CMD" ] && DEV_CMD="npm run dev"
  [ -n "$BUILD_CMD" ] && BUILD_CMD="npm run build"
  [ -n "$TEST_CMD" ] && TEST_CMD="npm test"
  [ -n "$TEST_WATCH_CMD" ] && TEST_WATCH_CMD="npm run test:watch"
  [ -n "$LINT_CMD" ] && LINT_CMD="npm run lint"
  [ -n "$FORMAT_CMD" ] && FORMAT_CMD="npm run format"

  # File patterns
  if [ "$CAP_static_types" = "typescript" ]; then
    FILE_PATTERNS="*.ts|*.tsx|*.js|*.jsx"
    SOURCE_PATTERNS="src/*.ts|src/*.tsx"
    TEST_FILE_PATTERNS="src/*.test.ts|src/*.test.tsx"
  else
    FILE_PATTERNS="*.js|*.jsx"
    SOURCE_PATTERNS="src/*.js|src/*.jsx"
    TEST_FILE_PATTERNS="src/*.test.js|src/*.test.jsx"
  fi

  # Test command patterns
  TEST_CMD_PATTERNS="npm test"
  [ "$CAP_testing" = "vitest" ] && TEST_CMD_PATTERNS="npm test|vitest"
  [ "$CAP_testing" = "jest" ] && TEST_CMD_PATTERNS="npm test|jest"

  # Coverage file
  COVERAGE_FILE="./coverage/coverage-summary.json"

  # Cross-compile detection (agent directory)
  if [ -d "$PROJECT_ROOT/agent" ] && [ -f "$PROJECT_ROOT/agent/main.go" ]; then
    CAP_cross_compile="true"
    # Agent version file
    for vf in "agent/version/version.json" "agent/version.json" "agent/VERSION"; do
      if [ -f "$PROJECT_ROOT/$vf" ]; then
        DET_AGENT_VERSION_FILE="$vf"
        break
      fi
    done
    # Agent build command
    DET_AGENT_BUILD_CMD="cd agent && GOOS=linux GOARCH=amd64 go build -o omniprobe ."
  fi
}

# Extract a script value from package.json
# Uses exact key matching to avoid "test" matching "test:watch"
extract_npm_script() {
  local name="$1" file="$2"
  awk -v name="$name" '
    /"scripts"/ { in_scripts = 1; next }
    in_scripts && /^[[:space:]]*\}/ { in_scripts = 0; next }
    in_scripts {
      # Match exact key: "name" followed by :
      pattern = "\"" name "\""
      if (index($0, pattern) > 0) {
        # Verify it is an exact key match (next non-space char after closing quote is :)
        pos = index($0, pattern) + length(pattern)
        rest = substr($0, pos)
        gsub(/^[[:space:]]*/, "", rest)
        if (substr(rest, 1, 1) == ":") { print "found"; exit }
      }
    }
  ' "$file" 2>/dev/null | head -1
}

# Check if a Python dependency exists in any dependency file
# Returns 0 (true) if found, 1 (false) otherwise
grep_python_deps() {
  local dep="$1"
  local found=false

  # pyproject.toml
  if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
    grep -qi "$dep" "$PROJECT_ROOT/pyproject.toml" 2>/dev/null && found=true
  fi

  # requirements*.txt
  if [ "$found" = false ]; then
    for reqfile in "$PROJECT_ROOT"/requirements*.txt; do
      [ -f "$reqfile" ] || continue
      grep -qi "^${dep}" "$reqfile" 2>/dev/null && found=true && break
    done
  fi

  # setup.py
  if [ "$found" = false ] && [ -f "$PROJECT_ROOT/setup.py" ]; then
    grep -qi "$dep" "$PROJECT_ROOT/setup.py" 2>/dev/null && found=true
  fi

  # Pipfile
  if [ "$found" = false ] && [ -f "$PROJECT_ROOT/Pipfile" ]; then
    grep -qi "$dep" "$PROJECT_ROOT/Pipfile" 2>/dev/null && found=true
  fi

  [ "$found" = "true" ]
}

detect_python_project() {
  verbose "检测 Python 项目..."

  # --- Framework detection ---
  grep_python_deps "fastapi"   && CAP_backend_api="FastAPI" || true
  grep_python_deps "flask"     && [ "$CAP_backend_api" = "false" ] && CAP_backend_api="Flask" || true
  grep_python_deps "django"    && [ "$CAP_backend_api" = "false" ] && CAP_backend_api="Django" || true
  grep_python_deps "starlette" && [ "$CAP_backend_api" = "false" ] && CAP_backend_api="Starlette" || true

  # --- Testing ---
  grep_python_deps "pytest" && CAP_testing="pytest" || true
  if [ "$CAP_testing" = "false" ]; then
    # Check for test directory (unittest convention)
    if [ -d "$PROJECT_ROOT/tests" ] || [ -d "$PROJECT_ROOT/test" ]; then
      CAP_testing="pytest"
    fi
  fi

  # --- Database ---
  if grep_python_deps "sqlalchemy" 2>/dev/null; then
    if grep_python_deps "psycopg2" 2>/dev/null || grep_python_deps "asyncpg" 2>/dev/null; then
      CAP_database="postgresql"
    elif grep_python_deps "pymysql" 2>/dev/null || grep_python_deps "mysql-connector" 2>/dev/null; then
      CAP_database="mysql"
    else
      CAP_database="sqlite"
    fi
  fi
  if grep_python_deps "django" 2>/dev/null && [ "$CAP_database" = "false" ]; then
    if grep_python_deps "psycopg2" 2>/dev/null; then
      CAP_database="postgresql"
    else
      CAP_database="sqlite"
    fi
  fi
  if grep_python_deps "pymongo" 2>/dev/null || grep_python_deps "motor" 2>/dev/null; then
    CAP_database="mongodb"
  fi

  # --- i18n ---
  grep_python_deps "babel"       && CAP_i18n="python-i18n" || true
  grep_python_deps "python-i18n" && CAP_i18n="python-i18n" || true

  # --- Package manager & install command (by priority) ---
  if [ -f "$PROJECT_ROOT/uv.lock" ]; then
    INSTALL_CMD="uv sync"
  elif [ -f "$PROJECT_ROOT/poetry.lock" ] || ([ -f "$PROJECT_ROOT/pyproject.toml" ] && grep -q '\[tool\.poetry\]' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null); then
    INSTALL_CMD="poetry install"
  elif [ -f "$PROJECT_ROOT/Pipfile" ]; then
    INSTALL_CMD="pipenv install"
  elif [ -f "$PROJECT_ROOT/requirements.txt" ]; then
    INSTALL_CMD="pip install -r requirements.txt"
  fi

  # --- DEV_CMD (by framework) ---
  if [ "$CAP_backend_api" = "FastAPI" ]; then
    DEV_CMD="uvicorn app.main:app --reload"
    # Try to extract from pyproject.toml [tool.scripts] or [project.scripts]
    if [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
      local script_cmd
      script_cmd=$(awk '/\[tool\.scripts\]|\[project\.scripts\]/{found=1; next} found && /^\[/{exit} found && /dev/{gsub(/.*=\s*"/, ""); gsub(/".*/, ""); print; exit}' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null) || true
      [ -n "$script_cmd" ] && DEV_CMD="$script_cmd"
    fi
  elif [ "$CAP_backend_api" = "Flask" ]; then
    DEV_CMD="flask run --debug"
  elif [ "$CAP_backend_api" = "Django" ]; then
    DEV_CMD="python manage.py runserver"
  fi

  # --- TEST_CMD ---
  if [ "$CAP_testing" = "pytest" ] && grep_python_deps "pytest" 2>/dev/null; then
    TEST_CMD="pytest"
  else
    TEST_CMD="python -m unittest discover"
  fi

  # --- TEST_WATCH_CMD ---
  if grep_python_deps "pytest-watch" 2>/dev/null || grep_python_deps "ptw" 2>/dev/null; then
    TEST_WATCH_CMD="ptw"
  fi

  # --- BUILD_CMD (Python typically doesn't have a build step) ---
  # Leave empty unless using a build tool
  if [ -f "$PROJECT_ROOT/pyproject.toml" ] && grep -q '\[build-system\]' "$PROJECT_ROOT/pyproject.toml" 2>/dev/null; then
    BUILD_CMD="python -m build"
  fi

  # --- LINT / FORMAT ---
  grep_python_deps "ruff"   && LINT_CMD="ruff check" && FORMAT_CMD="ruff format" || true
  grep_python_deps "flake8" && [ -z "$LINT_CMD" ] && LINT_CMD="flake8" || true
  grep_python_deps "black"  && [ -z "$FORMAT_CMD" ] && FORMAT_CMD="black" || true

  # --- File patterns ---
  FILE_PATTERNS="*.py"
  if [ -d "$PROJECT_ROOT/src" ]; then
    SOURCE_PATTERNS="src/**/*.py"
  elif [ -d "$PROJECT_ROOT/app" ]; then
    SOURCE_PATTERNS="app/**/*.py"
  else
    SOURCE_PATTERNS="*.py"
  fi
  TEST_FILE_PATTERNS="tests/**/*.py|test_*.py"

  # --- Test command patterns ---
  TEST_CMD_PATTERNS="pytest|python -m unittest"

  # --- Coverage ---
  COVERAGE_FILE=".coverage"
  COVERAGE_FORMAT="xml"

  # --- Python does not set CAP_static_types ---
  # (mypy/pyright are optional type checkers, Python itself is dynamically typed)

  # Cross-compile: not typical for Python
}

detect_bash_project() {
  verbose "检测 Bash/Shell 项目..."

  # --- Testing ---
  # 1. bats/bats-core
  local bats_found=false
  if command -v bats >/dev/null 2>&1; then
    bats_found=true
  fi
  if [ "$bats_found" = false ]; then
    local bats_files
    bats_files=$(find "$PROJECT_ROOT/tests" "$PROJECT_ROOT/test" -name "*.bats" 2>/dev/null | head -1 || true)
    [ -n "$bats_files" ] && bats_found=true
  fi
  if [ "$bats_found" = true ]; then
    CAP_testing="bats"
    if [ -d "$PROJECT_ROOT/tests" ]; then
      TEST_CMD="bats tests/"
    elif [ -d "$PROJECT_ROOT/test" ]; then
      TEST_CMD="bats test/"
    fi
  fi

  # 2. shunit2 (fallback)
  if [ "$CAP_testing" = "false" ]; then
    local shunit_files
    shunit_files=$(find "$PROJECT_ROOT/test" "$PROJECT_ROOT/tests" \
      \( -name "*_test.sh" -o -name "test_*.sh" \) 2>/dev/null | head -1 || true)
    [ -n "$shunit_files" ] && CAP_testing="shunit2"
  fi

  # --- Linting / Formatting ---
  if [ -f "$PROJECT_ROOT/.shellcheckrc" ] || command -v shellcheck >/dev/null 2>&1; then
    LINT_CMD="shellcheck"
  else
    LINT_CMD="bash -n"
  fi
  command -v shfmt >/dev/null 2>&1 && FORMAT_CMD="shfmt -w" || true

  # --- Build (Makefile targets) ---
  local makefile=""
  for mf in Makefile makefile GNUmakefile; do
    [ -f "$PROJECT_ROOT/$mf" ] && makefile="$PROJECT_ROOT/$mf" && break
  done
  if [ -n "$makefile" ]; then
    BUILD_CMD="make"
    grep -q '^test[[:space:]]*:' "$makefile" 2>/dev/null && [ -z "$TEST_CMD" ] && TEST_CMD="make test"
    grep -q '^lint[[:space:]]*:' "$makefile" 2>/dev/null && [ -z "$LINT_CMD" ] && LINT_CMD="make lint"
    grep -q '^install[[:space:]]*:' "$makefile" 2>/dev/null && INSTALL_CMD="make install"
  fi

  # --- File patterns ---
  FILE_PATTERNS="*.sh"
  SOURCE_PATTERNS="*.sh"
  [ -d "$PROJECT_ROOT/scripts" ] && SOURCE_PATTERNS="scripts/*.sh"
  [ -d "$PROJECT_ROOT/lib" ] && SOURCE_PATTERNS="lib/*.sh|$SOURCE_PATTERNS"
  TEST_FILE_PATTERNS="test/*.bats|tests/*.bats|test/*_test.sh|tests/*_test.sh"
  TEST_CMD_PATTERNS="bats|shunit2|make test"

  # Bash does not set CAP_static_types (dynamically typed)
}

# ============================================================
# CLAUDE.md Handling
# ============================================================
uncomment_optional_sections() {
  # Auto-uncomment optional sections in CLAUDE.md when capability is detected
  # Each section is wrapped in <!-- ... --> HTML comments in the template
  local tmp="$CLAUDE_MD.tmp"

  # i18n section: uncomment when CAP_i18n != false
  if [ "$CAP_i18n" != "false" ]; then
    awk '/^<!-- ### i18n/ { sub(/^<!-- /, ""); in_block=1 }
         in_block && / -->$/ { sub(/ -->$/, ""); print; in_block=0; next }
         { print }' "$CLAUDE_MD" > "$tmp" && mv "$tmp" "$CLAUDE_MD"
    verbose "已启用可选段落: i18n"
  fi

  # Design System section
  if [ "$CAP_design_system" != "false" ]; then
    awk '/^<!-- ### Design System/ { sub(/^<!-- /, ""); in_block=1 }
         in_block && / -->$/ { sub(/ -->$/, ""); print; in_block=0; next }
         { print }' "$CLAUDE_MD" > "$tmp" && mv "$tmp" "$CLAUDE_MD"
    verbose "已启用可选段落: Design System"
  fi

  # Database section
  if [ "$CAP_database" != "false" ]; then
    awk '/^<!-- ### Database/ { sub(/^<!-- /, ""); in_block=1 }
         in_block && / -->$/ { sub(/ -->$/, ""); print; in_block=0; next }
         { print }' "$CLAUDE_MD" > "$tmp" && mv "$tmp" "$CLAUDE_MD"
    verbose "已启用可选段落: Database"
  fi

  # Agent Versioning section
  if [ "$CAP_cross_compile" = "true" ]; then
    awk '/^<!-- ### Agent Versioning/ { sub(/^<!-- /, ""); in_block=1 }
         in_block && / -->$/ { sub(/ -->$/, ""); print; in_block=0; next }
         { print }' "$CLAUDE_MD" > "$tmp" && mv "$tmp" "$CLAUDE_MD"
    verbose "已启用可选段落: Agent Versioning"
  fi
}

generate_claude_md() {
  local template="$TEMPLATE_DIR/CLAUDE.md.template"
  if [ ! -f "$template" ]; then
    warn "CLAUDE.md.template 不存在，跳过 CLAUDE.md 生成"
    return 1
  fi
  info "从模板生成 CLAUDE.md..."

  if [ "$DRY_RUN" = true ]; then
    info "[DRY-RUN] 将生成 CLAUDE.md（含 TODO 标记需手动补全）"
    return 0
  fi

  local todo='<!-- TODO: 请手动填写 -->'

  # Replace placeholders with detected values or TODO markers
  # Strategy: use ENVIRON[] for values that may contain newlines or &
  # (awk -v processes \-escapes and can't handle literal newlines)
  INSTALL_CMD_V="$INSTALL_CMD" \
  DEV_CMD_V="$DEV_CMD" \
  BUILD_CMD_V="$BUILD_CMD" \
  TEST_CMD_V="$TEST_CMD" \
  TEST_WATCH_V="$TEST_WATCH_CMD" \
  TODO_V="$todo" \
  DET_FE_STACK_V="$DET_FE_STACK" \
  DET_BE_STACK_V="$DET_BE_STACK" \
  DET_LOCALE_LIST_V="$DET_LOCALE_LIST" \
  DET_AGENT_VER_V="$DET_AGENT_VERSION_FILE" \
  DET_AGENT_BUILD_V="$DET_AGENT_BUILD_CMD" \
  awk -v cap_fe="$CAP_frontend" \
      -v cap_be="$CAP_backend_api" \
      -v cap_db="$CAP_database" \
      -v cap_i18n="$CAP_i18n" \
      -v cap_test="$CAP_testing" \
      -v cap_ds="$CAP_design_system" \
      -v cap_ci="$CAP_ci_cd" \
      -v cap_st="$CAP_static_types" \
      -v commit_lang="$COMMIT_LANG" \
      -v indent="$INDENTATION" \
      -v types_file="$DET_TYPES_FILE" \
      -v routes_dir="$DET_ROUTES_DIR" \
      -v api_file="$DET_API_FILE" \
      -v locale_dir="$DET_LOCALE_DIR" \
      -v token_config="$DET_TOKEN_CONFIG" \
      -v db_file="$DET_DB_FILE" \
  'function esc(s) {
    # Escape & and \ for gsub replacement string
    gsub(/\\/, "\\\\", s)
    gsub(/&/, "\\&", s)
    return s
  }
  function capitalize(s) {
    return toupper(substr(s,1,1)) substr(s,2)
  }
  BEGIN {
    install_cmd = ENVIRON["INSTALL_CMD_V"]
    dev_cmd     = ENVIRON["DEV_CMD_V"]
    build_cmd   = ENVIRON["BUILD_CMD_V"]
    test_cmd    = ENVIRON["TEST_CMD_V"]
    test_watch  = ENVIRON["TEST_WATCH_V"]
    todo        = ENVIRON["TODO_V"]
    fe_stack    = ENVIRON["DET_FE_STACK_V"]
    be_stack    = ENVIRON["DET_BE_STACK_V"]
    locale_list = ENVIRON["DET_LOCALE_LIST_V"]
    agent_ver   = ENVIRON["DET_AGENT_VER_V"]
    agent_build = ENVIRON["DET_AGENT_BUILD_V"]
  }
  {
    gsub(/\$FRONTEND_FRAMEWORK/, esc((cap_fe != "false") ? cap_fe : todo))
    gsub(/\$BACKEND_FRAMEWORK/, esc((cap_be != "false") ? cap_be : todo))
    gsub(/\$DATABASE_TYPE/, esc((cap_db != "false") ? cap_db : todo))
    gsub(/\$I18N_LIBRARY/, (cap_i18n != "false") ? cap_i18n : "false")
    gsub(/\$TEST_FRAMEWORK/, (cap_test != "false") ? cap_test : "false")
    gsub(/\$DESIGN_SYSTEM/, (cap_ds != "false") ? cap_ds : "false")
    gsub(/\$CI_CD_TOOL/, (cap_ci != "false") ? cap_ci : "false")
    gsub(/\$STATIC_TYPES_LANG/, (cap_st != "false") ? cap_st : "false")
    gsub(/\$INSTALL_COMMAND/, esc((install_cmd != "") ? install_cmd : todo))
    gsub(/\$DEV_COMMAND/, esc((dev_cmd != "") ? dev_cmd : todo))
    gsub(/\$BUILD_COMMAND/, esc((build_cmd != "") ? build_cmd : todo))
    gsub(/\$TEST_COMMAND/, esc((test_cmd != "") ? test_cmd : todo))
    gsub(/\$TEST_WATCH_COMMAND/, esc((test_watch != "") ? test_watch : todo))
    gsub(/\$COMMIT_LANGUAGE/, commit_lang)
    gsub(/\$OUTPUT_LANGUAGE/, commit_lang)
    gsub(/\$PROJECT_DESCRIPTION/, esc(todo))
    gsub(/\$FRONTEND_STACK/, esc((fe_stack != "") ? fe_stack : todo))
    gsub(/\$FRONTEND_PORT/, esc(todo))
    gsub(/\$BACKEND_STACK/, esc((be_stack != "") ? be_stack : todo))
    gsub(/\$BACKEND_PORT/, esc(todo))
    gsub(/\$DATABASE/, esc((cap_db != "false") ? cap_db : todo))
    gsub(/\$ARCHITECTURE_DIAGRAM/, esc(todo))
    gsub(/\$STATE_MANAGEMENT/, esc(todo))
    gsub(/\$BACKEND_LAYERS/, esc(todo))
    gsub(/\$KEY_SERVICE_FILES/, esc(todo))
    gsub(/\$INDENTATION/, indent)
    gsub(/\$LANGUAGE/, (cap_st != "false") ? capitalize(cap_st) : "JavaScript")
    gsub(/\$TYPES_FILE/, esc((types_file != "") ? types_file : todo))
    gsub(/\$ROUTES_DIR/, esc((routes_dir != "") ? routes_dir : todo))
    gsub(/\$API_SERVICE_FILE/, esc((api_file != "") ? api_file : todo))
    gsub(/\$LOCALE_DIR/, esc((locale_dir != "") ? locale_dir : todo))
    gsub(/\$LOCALE_LIST/, esc((locale_list != "") ? locale_list : todo))
    gsub(/\$CSS_FRAMEWORK/, esc((cap_ds != "false") ? cap_ds : todo))
    gsub(/\$TOKEN_CONFIG_FILE/, esc((token_config != "") ? token_config : todo))
    gsub(/\$DB_ACCESS_FILE/, esc((db_file != "") ? db_file : todo))
    gsub(/\$AGENT_VERSION_FILE/, esc((agent_ver != "") ? agent_ver : todo))
    gsub(/\$AGENT_BUILD_COMMAND/, esc((agent_build != "") ? agent_build : todo))
    print
  }' "$template" > "$CLAUDE_MD"

  # Auto-uncomment optional sections when capability is detected
  uncomment_optional_sections

  local todo_count
  todo_count=$(grep -c 'TODO' "$CLAUDE_MD" 2>/dev/null) || todo_count=0
  if [ "$todo_count" -gt 0 ]; then
    info "CLAUDE.md 已生成（$todo_count 个 TODO 标记待 LLM 自动补全）"
  else
    info "CLAUDE.md 已生成（所有占位符已自动填充）"
  fi
}

ensure_capabilities() {
  [ ! -f "$CLAUDE_MD" ] && return 1
  # Check if Capabilities section exists
  if ! grep -q '^## Capabilities' "$CLAUDE_MD" 2>/dev/null; then
    info "CLAUDE.md 缺少 Capabilities 节，追加检测结果..."
    if [ "$DRY_RUN" = true ]; then
      info "[DRY-RUN] 将追加 Capabilities 表到 CLAUDE.md"
      return 0
    fi
    cat >> "$CLAUDE_MD" << CAPEOF

## Capabilities

| 能力 | 值 |
|------|-----|
| frontend | $CAP_frontend |
| backend-api | $CAP_backend_api |
| database | $CAP_database |
| i18n | $CAP_i18n |
| testing | $CAP_testing |
| cross-compile | $CAP_cross_compile |
| design-system | $CAP_design_system |
| ci-cd | $CAP_ci_cd |
| monorepo | $CAP_monorepo |
| static-types | $CAP_static_types |
CAPEOF
    info "Capabilities 表已追加"
  else
    # Capabilities section exists — update "false" entries with detected values
    [ "$DRY_RUN" = true ] && return 0
    local updated=0
    local tmp="$CLAUDE_MD.tmp"
    local cap_name cap_val
    # Build associative updates: only override "false" with detected non-false values
    for cap_name in frontend backend-api database i18n testing cross-compile design-system ci-cd monorepo static-types; do
      case "$cap_name" in
        frontend)      cap_val="$CAP_frontend" ;;
        backend-api)   cap_val="$CAP_backend_api" ;;
        database)      cap_val="$CAP_database" ;;
        i18n)          cap_val="$CAP_i18n" ;;
        testing)       cap_val="$CAP_testing" ;;
        cross-compile) cap_val="$CAP_cross_compile" ;;
        design-system) cap_val="$CAP_design_system" ;;
        ci-cd)         cap_val="$CAP_ci_cd" ;;
        monorepo)      cap_val="$CAP_monorepo" ;;
        static-types)  cap_val="$CAP_static_types" ;;
      esac
      [ "$cap_val" = "false" ] && continue
      # Replace "| cap_name | false |" with "| cap_name | detected_val |"
      if grep -q "| ${cap_name} | false" "$CLAUDE_MD" 2>/dev/null; then
        # Escape sed special chars in cap_val (/, &, \)
        local safe_val
        safe_val=$(printf '%s\n' "$cap_val" | sed 's/[\/&\\]/\\&/g')
        sed "s/| ${cap_name} | false/| ${cap_name} | ${safe_val}/" "$CLAUDE_MD" > "$tmp" && mv "$tmp" "$CLAUDE_MD"
        updated=$((updated + 1))
      fi
    done
    if [ "$updated" -gt 0 ]; then
      info "CLAUDE.md Capabilities 表已更新 $updated 项（用检测值替换 false）"
    fi
  fi
}

parse_capabilities_into_vars() {
  [ ! -f "$CLAUDE_MD" ] && return 1
  info "解析 CLAUDE.md Capabilities 表..."

  # Use common.sh parse_capabilities() and populate CAP_ variables
  # Strategy: CLAUDE.md values override detect_project() results,
  # UNLESS the CLAUDE.md value is "false" and detect_project() found a real value.
  # This allows auto-detection to fill in capabilities that CLAUDE.md hasn't set yet,
  # while still respecting explicit non-false values written by the user.
  while IFS= read -r line; do
    local key val
    key=$(echo "$line" | cut -d= -f1)
    val=$(echo "$line" | cut -d= -f2-)
    # Skip "false" values from CLAUDE.md — keep detect_project() result if it found something
    [ "$val" = "false" ] && continue
    case "$key" in
      frontend)      CAP_frontend="$val" ;;
      backend-api)   CAP_backend_api="$val" ;;
      database)      CAP_database="$val" ;;
      i18n)          CAP_i18n="$val" ;;
      testing)       CAP_testing="$val" ;;
      cross-compile) CAP_cross_compile="$val" ;;
      design-system) CAP_design_system="$val" ;;
      ci-cd)         CAP_ci_cd="$val" ;;
      monorepo)      CAP_monorepo="$val" ;;
      static-types)  CAP_static_types="$val" ;;
    esac
  done < <(parse_capabilities "$CLAUDE_MD")

  verbose "Capabilities: frontend=$CAP_frontend backend=$CAP_backend_api testing=$CAP_testing"
}

derive_implicit_tags() {
  # Derive tags not in Capabilities table but used in IF conditions
  # websocket: scan Architecture section for WebSocket references
  if [ -f "$CLAUDE_MD" ] && grep -qE '[Ww]eb[Ss]ocket|[Ww][Ss][ /:]' "$CLAUDE_MD" 2>/dev/null; then
    CAP_websocket="true"
  else
    CAP_websocket="false"
  fi
  verbose "派生标签: websocket=$CAP_websocket"
}

build_caps_string() {
  # Normalize empty values to "false" to prevent awk empty-string issues
  CAPS_STRING="frontend=${CAP_frontend:-false}"
  CAPS_STRING="$CAPS_STRING,backend-api=${CAP_backend_api:-false}"
  CAPS_STRING="$CAPS_STRING,database=${CAP_database:-false}"
  CAPS_STRING="$CAPS_STRING,i18n=${CAP_i18n:-false}"
  CAPS_STRING="$CAPS_STRING,testing=${CAP_testing:-false}"
  CAPS_STRING="$CAPS_STRING,cross-compile=${CAP_cross_compile:-false}"
  CAPS_STRING="$CAPS_STRING,design-system=${CAP_design_system:-false}"
  CAPS_STRING="$CAPS_STRING,ci-cd=${CAP_ci_cd:-false}"
  CAPS_STRING="$CAPS_STRING,monorepo=${CAP_monorepo:-false}"
  CAPS_STRING="$CAPS_STRING,static-types=${CAP_static_types:-false}"
  CAPS_STRING="$CAPS_STRING,websocket=${CAP_websocket:-false}"
  verbose "CAPS_STRING=$CAPS_STRING"
}

# ============================================================
# PS Value Extraction
# ============================================================
PS_NUM=0

# Add a PS replacement value (raw content)
add_ps() {
  local desc="$1"
  PS_NUM=$((PS_NUM + 1))
  local file="$TMP_DIR/ps/$(printf '%03d' $PS_NUM).txt"
  # Content comes from stdin or $2
  if [ $# -ge 2 ]; then
    printf '%s\n' "$2" > "$file"
  else
    cat > "$file"
  fi
  printf '%s\t%s\n' "$desc" "$file" >> "$TMP_DIR/ps-index.txt"
  verbose "PS[$PS_NUM] '$desc' -> $file"
}

# Add a PS value wrapped in a code block
add_ps_block() {
  local desc="$1" lang="$2" content="$3"
  PS_NUM=$((PS_NUM + 1))
  local file="$TMP_DIR/ps/$(printf '%03d' $PS_NUM).txt"
  printf '```%s\n%s\n```\n' "$lang" "$content" > "$file"
  printf '%s\t%s\n' "$desc" "$file" >> "$TMP_DIR/ps-index.txt"
  verbose "PS[$PS_NUM] '$desc' -> $file (code block)"
}

extract_ps_values() {
  info "提取 PROJECT-SPECIFIC 替换值..."
  > "$TMP_DIR/ps-index.txt"

  # --- Command-type PS values ---

  # 1. 依赖安装命令
  local install_lines=""
  if [ -f "$CLAUDE_MD" ]; then
    install_lines=$(extract_md_section "Build & Development Commands" | extract_codeblock 1 | awk '
      /^# [Ii]nstall/ { found=1; next }
      /^# / && found { exit }
      found && NF { print }
    ')
  fi
  [ -z "$install_lines" ] && install_lines="$INSTALL_CMD"
  [ -n "$install_lines" ] && add_ps_block "依赖安装命令" "bash" "$install_lines"

  # 2. 构建命令
  local build_lines=""
  if [ -f "$CLAUDE_MD" ]; then
    build_lines=$(extract_md_section "Build & Development Commands" | extract_codeblock 1 | awk '
      /^# [Bb]uild/ { found=1; next }
      /^# / && found { exit }
      found && NF { print }
    ')
  fi
  [ -z "$build_lines" ] && build_lines="$BUILD_CMD"
  if [ -n "$build_lines" ]; then
    add_ps_block "构建命令" "bash" "$build_lines"
    add_ps_block "构建验证命令" "bash" "$build_lines"
  fi

  # 3. 测试命令
  local test_lines=""
  if [ -f "$CLAUDE_MD" ]; then
    test_lines=$(extract_md_section "Testing" | extract_codeblock 1)
  fi
  if [ -z "$test_lines" ] && [ -n "$TEST_CMD" ]; then
    test_lines="$TEST_CMD"
    [ -n "$TEST_WATCH_CMD" ] && test_lines="$test_lines"$'\n'"$TEST_WATCH_CMD"
  fi
  if [ -n "$test_lines" ]; then
    # Remove pure comment lines (lines starting with #), keep inline # in commands
    local clean_test
    clean_test=$(echo "$test_lines" | grep -v '^[[:space:]]*#')
    add_ps_block "测试命令" "bash" "$clean_test"
    # Integration test command (derived)
    local base_test
    base_test=$(echo "$clean_test" | head -1)
    add_ps_block "集成测试命令" "bash" "$base_test -- integration"
  fi

  # 4. 类型检查命令
  if [ "$CAP_static_types" = "typescript" ]; then
    add_ps_block "类型检查命令" "bash" "npx tsc --noEmit"
  fi

  # 5. 交叉编译命令 (from CLAUDE.md or detection)
  if [ "$CAP_cross_compile" = "true" ]; then
    local xc_lines=""
    if [ -f "$CLAUDE_MD" ]; then
      xc_lines=$(extract_md_section "Build & Development Commands" | extract_codeblock 1 | awk '
        /[Aa]gent|[Cc]ross|GOOS/ { found=1; print; next }
        found && NF { print }
        /^$/ && found { exit }
      ')
    fi
    if [ -z "$xc_lines" ] && [ -d "$PROJECT_ROOT/agent" ]; then
      xc_lines="cd agent && GOOS=linux GOARCH=amd64 go build -o omniprobe ."
    fi
    [ -n "$xc_lines" ] && add_ps_block "交叉编译命令" "bash" "$xc_lines"
  fi

  # --- File structure PS values ---

  # 6. 文件结构示例
  local file_struct=""
  if [ "$CAP_frontend" != "false" ] && [ "$CAP_backend_api" != "false" ]; then
    local api_file routes_dir services_dir types_file
    # Detect common file locations
    if [ -f "$PROJECT_ROOT/services/api.ts" ]; then
      api_file="services/api.ts"
    elif [ -f "$PROJECT_ROOT/src/services/api.ts" ]; then
      api_file="src/services/api.ts"
    else
      api_file="services/api.ts"
    fi
    routes_dir="backend/src/routes/"
    [ -d "$PROJECT_ROOT/backend/src/routes" ] || routes_dir="src/routes/"
    services_dir="backend/src/services/"
    [ -d "$PROJECT_ROOT/backend/src/services" ] || services_dir="src/services/"
    if [ -f "$PROJECT_ROOT/src/types.ts" ]; then
      types_file="src/types.ts"
    else
      types_file="types.ts"
    fi

    file_struct="前端：\`src/components/FeatureName/\`（主组件、子组件、自定义 Hook），API 调用更新 \`$api_file\`，类型更新 \`$types_file\`。后端：路由放 \`$routes_dir\`，服务放 \`$services_dir\`。"
  elif [ "$CAP_frontend" != "false" ]; then
    file_struct="前端：\`src/components/FeatureName/\`（主组件、子组件），API 调用更新 \`src/services/api.ts\`。"
  elif [ "$CAP_backend_api" != "false" ]; then
    file_struct="路由放 \`src/routes/\`，服务放 \`src/services/\`，类型放 \`src/types/\`。"
  fi
  [ -n "$file_struct" ] && add_ps "文件结构示例" "$file_struct"

  # 7. i18n 文件列表
  local locale_dir=""
  [ -d "$PROJECT_ROOT/locales" ] && locale_dir="$PROJECT_ROOT/locales"
  [ -d "$PROJECT_ROOT/i18n" ] && locale_dir="$PROJECT_ROOT/i18n"
  if [ -n "$locale_dir" ] && [ "$CAP_i18n" != "false" ]; then
    local dir_name
    dir_name=$(basename "$locale_dir")
    local i18n_tree=""
    local files
    files=$(find "$locale_dir" -maxdepth 1 -type f -exec basename {} \; 2>/dev/null | sort)
    local count total
    total=$(echo "$files" | wc -l | tr -d ' ')
    count=0
    while IFS= read -r f; do
      count=$((count + 1))
      if [ "$count" -eq "$total" ]; then
        i18n_tree="${i18n_tree}${i18n_tree:+
}└── $f"
      else
        i18n_tree="${i18n_tree}${i18n_tree:+
}├── $f"
      fi
    done <<< "$files"
    local i18n_content
    i18n_content=$(printf '```\n%s/\n%s\n```' "$dir_name" "$i18n_tree")
    add_ps "i18n 文件列表" "$i18n_content"
  fi

  # 8. 测试框架约定 (from CLAUDE.md Testing Conventions)
  if [ -f "$CLAUDE_MD" ]; then
    local conventions=""
    conventions=$(extract_md_section "Testing" | awk '
      /^\*\*Conventions/ || /^### Conventions/ { found=1; next }
      /^## / { exit }
      /^### / && found { exit }
      found { print }
    ')
    # Remove leading/trailing empty lines (portable)
    conventions=$(echo "$conventions" | awk 'NF{p=1} p')
    [ -n "$conventions" ] && add_ps "测试框架约定" "$conventions"
  fi

  # 9. 测试文件路径示例
  if [ "$CAP_testing" != "false" ]; then
    local test_paths=""
    if [ "$CAP_static_types" = "typescript" ]; then
      test_paths="- src/xxx.test.ts（N 个用例）
- tests/integration/xxx.test.ts（N 个用例）"
    else
      test_paths="- src/xxx.test.js（N 个用例）
- tests/integration/xxx.test.js（N 个用例）"
    fi
    add_ps "测试文件路径示例" "$test_paths"
  fi

  # 10. 测试文件放置规范
  if [ -f "$CLAUDE_MD" ] && [ "$CAP_testing" != "false" ]; then
    local placement=""
    placement=$(extract_md_section "Testing" | awk '
      /co-located|Test files|测试文件/ { found=1 }
      found { print }
      /^$/ && found { exit }
    ')
    [ -n "$placement" ] && add_ps "测试文件放置规范" "$placement"
  fi

  # 11. Mock 数据路径
  if [ "$CAP_testing" != "false" ]; then
    if [ -d "$PROJECT_ROOT/tests/fixtures" ]; then
      add_ps "Mock 数据路径" "- tests/fixtures/xxx.ts"
    elif [ -d "$PROJECT_ROOT/test/fixtures" ]; then
      add_ps "Mock 数据路径" "- test/fixtures/xxx.ts"
    fi
  fi

  # 12. 后端服务地址 (from CLAUDE.md overview)
  if [ -f "$CLAUDE_MD" ] && [ "$CAP_backend_api" != "false" ]; then
    local be_port=""
    be_port=$(grep -oE '[Bb]ackend.*port ([0-9]+)' "$CLAUDE_MD" 2>/dev/null | grep -oE '[0-9]+' | head -1) || true
    if [ -n "$be_port" ]; then
      add_ps "后端服务地址" "  - REST API: \`http://localhost:$be_port/api/\`"
    fi
  fi

  local ps_count
  ps_count=$(wc -l < "$TMP_DIR/ps-index.txt" | tr -d ' ')
  info "已提取 $ps_count 个 PS 替换值"
}

validate_claude_md() {
  [ ! -f "$CLAUDE_MD" ] && return 1
  info "验证 CLAUDE.md 完整性..."

  local missing=0
  local required_sections="Project Overview|Capabilities|Build & Development Commands|Testing|Architecture|Key Development Conventions|Language|Commit Style"

  local OLD_IFS="$IFS"
  IFS='|'
  for section in $required_sections; do
    if ! grep -q "^## $section" "$CLAUDE_MD" 2>/dev/null; then
      warn "CLAUDE.md 缺少必需节: ## $section"
      missing=$((missing + 1))
    fi
  done
  IFS="$OLD_IFS"

  if [ "$missing" -gt 0 ]; then
    WARNINGS=$((WARNINGS + missing))
  fi

  local todo_count
  todo_count=$(grep -c 'TODO' "$CLAUDE_MD" 2>/dev/null) || todo_count=0
  [ "${todo_count:-0}" -gt 0 ] && info "CLAUDE.md 中有 $todo_count 个 TODO 标记待补全"

  verbose "CLAUDE.md 验证: 缺少 $missing 个必需节, $todo_count 个 TODO"
}

# ============================================================
# Template Processing
# ============================================================
process_template() {
  local src="$1" dst="$2"
  verbose "处理模板: $src -> $dst"

  # Pass 1: IF condition trimming
  awk -v caps="$CAPS_STRING" -f "$SCRIPT_DIR/process_if.awk" "$src" > "$TMP_DIR/pass1.tmp"

  # Pass 2: PS replacement
  if [ -s "$TMP_DIR/ps-index.txt" ]; then
    awk -v ps_index="$TMP_DIR/ps-index.txt" -f "$SCRIPT_DIR/process_ps.awk" "$TMP_DIR/pass1.tmp" > "$dst"
  else
    cp "$TMP_DIR/pass1.tmp" "$dst"
  fi
}

# ============================================================
# Installation
# ============================================================
create_directories() {
  info "创建目录结构..."
  local dirs="skills hooks scripts workspace context"
  for d in $dirs; do
    if [ "$DRY_RUN" = true ]; then
      verbose "[DRY-RUN] mkdir -p $TARGET_DIR/$d"
    else
      mkdir -p "$TARGET_DIR/$d"
    fi
  done

  # Create skill subdirectories
  for skill in f-product f-dev f-bugfix f-design \
               f-test f-context f-workspace f-clean f-doc f-init \
               f-analyze f-revise; do
    if [ "$DRY_RUN" = true ]; then
      verbose "[DRY-RUN] mkdir -p $TARGET_DIR/skills/$skill"
    else
      mkdir -p "$TARGET_DIR/skills/$skill"
    fi
  done
}

install_skills() {
  # Skills that are direct copy
  local copy_skills="f-dev f-bugfix f-design f-product f-test f-doc f-init f-context f-workspace f-clean f-analyze f-revise"
  local skill_count_expected
  # shellcheck disable=SC2086
  skill_count_expected=$(echo $copy_skills | wc -w | tr -d ' ')
  info "安装 Skills（${skill_count_expected} 个）..."
  for skill in $copy_skills; do
    local src="$TEMPLATE_DIR/skills/$skill/SKILL.md"
    local dst="$TARGET_DIR/skills/$skill/SKILL.md"
    if [ ! -f "$src" ]; then
      warn "模板不存在: $src"
      continue
    fi
    if [ "$DRY_RUN" = true ]; then
      info "[DRY-RUN] 复制 $skill"
    else
      cp "$src" "$dst"
      INSTALLED_FILES=$((INSTALLED_FILES + 1))
    fi
  done
}

install_hooks() {
  info "安装 Hooks（6 个）..."

  # Copy all hook scripts
  for src in "$TEMPLATE_DIR/hooks/"*.sh; do
    [ -f "$src" ] || continue
    local name
    name=$(basename "$src")
    local dst="$TARGET_DIR/hooks/$name"
    if [ "$DRY_RUN" = true ]; then
      info "[DRY-RUN] 复制 Hook $name"
    else
      cp "$src" "$dst"
      chmod +x "$dst"
      INSTALLED_FILES=$((INSTALLED_FILES + 1))
    fi
  done

  [ "$DRY_RUN" = true ] && return 0

  # Fill configuration variables in hooks that have "配置区域" sections
  info "填充 Hook 配置变量..."
  for hook in "$TARGET_DIR/hooks/"*.sh; do
    [ -f "$hook" ] || continue
    # Only process hooks with configuration sections
    grep -q '配置区域' "$hook" 2>/dev/null || continue

    local tmp="$hook.tmp"
    # Use ENVIRON[] to pass values safely (avoids awk -v escape processing)
    V_CAP_TESTING="$CAP_testing" \
    V_LINT_CMD="$LINT_CMD" \
    V_FORMAT_CMD="$FORMAT_CMD" \
    V_FILE_PATTERNS="$FILE_PATTERNS" \
    V_TEST_CMD="$TEST_CMD" \
    V_TEST_CMD_PATTERNS="$TEST_CMD_PATTERNS" \
    V_SOURCE_PATTERNS="$SOURCE_PATTERNS" \
    V_TEST_FILE_PATTERNS="$TEST_FILE_PATTERNS" \
    V_COVERAGE_FILE="$COVERAGE_FILE" \
    V_COVERAGE_FORMAT="$COVERAGE_FORMAT" \
    V_THRESHOLD="$COVERAGE_THRESHOLD" \
    awk 'function shell_escape(s) {
      gsub(/\\/, "\\\\", s); gsub(/"/, "\\\"", s); gsub(/\$/, "\\$", s); gsub(/`/, "\\`", s)
      return s
    }
    {
      if ($0 ~ /^CAPABILITY_TESTING=/) { print "CAPABILITY_TESTING=\"" shell_escape(ENVIRON["V_CAP_TESTING"]) "\""; next }
      if ($0 ~ /^LINT_CMD=/)           { print "LINT_CMD=\"" shell_escape(ENVIRON["V_LINT_CMD"]) "\""; next }
      if ($0 ~ /^FORMAT_CMD=/)         { print "FORMAT_CMD=\"" shell_escape(ENVIRON["V_FORMAT_CMD"]) "\""; next }
      if ($0 ~ /^FILE_PATTERNS=/)      { print "FILE_PATTERNS=\"" shell_escape(ENVIRON["V_FILE_PATTERNS"]) "\""; next }
      if ($0 ~ /^TEST_CMD=/)           { print "TEST_CMD=\"" shell_escape(ENVIRON["V_TEST_CMD"]) "\""; next }
      if ($0 ~ /^TEST_CMD_PATTERNS=/)  { print "TEST_CMD_PATTERNS=\"" shell_escape(ENVIRON["V_TEST_CMD_PATTERNS"]) "\""; next }
      if ($0 ~ /^SOURCE_PATTERNS=/)    { print "SOURCE_PATTERNS=\"" shell_escape(ENVIRON["V_SOURCE_PATTERNS"]) "\""; next }
      if ($0 ~ /^TEST_FILE_PATTERNS=/) { print "TEST_FILE_PATTERNS=\"" shell_escape(ENVIRON["V_TEST_FILE_PATTERNS"]) "\""; next }
      if ($0 ~ /^COVERAGE_FILE=/)      { print "COVERAGE_FILE=\"" shell_escape(ENVIRON["V_COVERAGE_FILE"]) "\""; next }
      if ($0 ~ /^COVERAGE_FORMAT=/)    { print "COVERAGE_FORMAT=\"" shell_escape(ENVIRON["V_COVERAGE_FORMAT"]) "\""; next }
      if ($0 ~ /^THRESHOLD=/)          { print "THRESHOLD=\"" shell_escape(ENVIRON["V_THRESHOLD"]) "\""; next }
      print
    }' "$hook" > "$tmp" && mv "$tmp" "$hook"
    chmod +x "$hook"
    verbose "配置已填充: $(basename "$hook")"
  done
}

install_scripts() {
  info "安装脚本到 .claude/scripts/..."

  if [ "$DRY_RUN" = true ]; then
    info "[DRY-RUN] mkdir -p $TARGET_DIR/scripts"
  else
    mkdir -p "$TARGET_DIR/scripts"
  fi

  # Copy all .sh and .awk scripts from template scripts/ dir
  for src in "$TEMPLATE_DIR/scripts/"*.sh "$TEMPLATE_DIR/scripts/"*.awk; do
    [ -f "$src" ] || continue
    local name
    name=$(basename "$src")
    # Skip init.sh itself — it stays in template dir only
    [ "$name" = "init.sh" ] && continue
    local dst="$TARGET_DIR/scripts/$name"
    if [ "$DRY_RUN" = true ]; then
      info "[DRY-RUN] 复制脚本 $name"
    else
      cp "$src" "$dst"
      chmod +x "$dst"
      INSTALLED_SCRIPTS=$((INSTALLED_SCRIPTS + 1))
      INSTALLED_FILES=$((INSTALLED_FILES + 1))
    fi
  done
}

install_settings() {
  info "安装 settings.json..."
  local src="$TEMPLATE_DIR/settings.json"
  local dst="$TARGET_DIR/settings.json"
  if [ ! -f "$src" ]; then
    warn "settings.json 模板不存在"
    return 1
  fi
  if [ "$DRY_RUN" = true ]; then
    info "[DRY-RUN] 复制 settings.json"
  else
    cp "$src" "$dst"
    INSTALLED_FILES=$((INSTALLED_FILES + 1))
  fi
}

# ============================================================
# Validation
# ============================================================
validate_all() {
  info "验证安装结果..."
  local errors=0

  # File counts
  local skill_count hook_count
  skill_count=$(find "$TARGET_DIR/skills" -name "SKILL.md" 2>/dev/null | wc -l | tr -d ' ')
  hook_count=$(find "$TARGET_DIR/hooks" -name "*.sh" 2>/dev/null | wc -l | tr -d ' ')

  # Expected counts: derived from template directory
  local expected_skills expected_hooks
  expected_skills=$(find "$TEMPLATE_DIR/skills" -name "SKILL.md" 2>/dev/null | wc -l | tr -d ' ')
  expected_hooks=$(find "$TEMPLATE_DIR/hooks" -name "*.sh" 2>/dev/null | wc -l | tr -d ' ')

  if [ "$skill_count" -ne "$expected_skills" ]; then
    error "Skills 数量 $skill_count != $expected_skills"
    errors=$((errors + 1))
  fi
  if [ "$hook_count" -ne "$expected_hooks" ]; then
    error "Hooks 数量 $hook_count != $expected_hooks"
    errors=$((errors + 1))
  fi
  if [ ! -f "$TARGET_DIR/settings.json" ]; then
    error "settings.json 缺失"
    errors=$((errors + 1))
  fi

  # Residual markers (exclude f-init which has IF markers in documentation text)
  local residual_if
  residual_if=$(grep -rl '<!-- IF:' "$TARGET_DIR/skills/" 2>/dev/null | grep -v 'f-init' | wc -l | tr -d ' ') || true

  if [ "${residual_if:-0}" -gt 0 ]; then
    error "发现 $residual_if 个文件含有残留 IF 标记"
    errors=$((errors + 1))
  fi

  # Executable permissions — hooks
  for sh in "$TARGET_DIR/hooks/"*.sh; do
    [ -f "$sh" ] || continue
    if [ ! -x "$sh" ]; then
      error "$sh 缺少可执行权限"
      errors=$((errors + 1))
    fi
  done

  # Scripts directory
  if [ -d "$TARGET_DIR/scripts" ]; then
    local script_count
    script_count=$(find "$TARGET_DIR/scripts" \( -name "*.sh" -o -name "*.awk" \) 2>/dev/null | wc -l | tr -d ' ')
    verbose "Scripts 数量: $script_count"
    # Verify key scripts exist
    for key_script in common.sh context.sh workspace.sh clean.sh; do
      if [ -f "$TEMPLATE_DIR/scripts/$key_script" ] && [ ! -f "$TARGET_DIR/scripts/$key_script" ]; then
        warn "脚本未安装: $key_script"
      fi
    done
    # Executable permissions — scripts
    for sh in "$TARGET_DIR/scripts/"*.sh; do
      [ -f "$sh" ] || continue
      if [ ! -x "$sh" ]; then
        error "$sh 缺少可执行权限"
        errors=$((errors + 1))
      fi
    done
  fi

  verbose "验证完成: $errors 个错误"
  [ "$errors" -eq 0 ] && return 0 || return 1
}

# ============================================================
# Reporting
# ============================================================
output_report() {
  local status="SUCCESS"
  [ "$ERRORS" -gt 0 ] && status="FAILED"

  echo ""
  echo "================================================"
  echo "  工作流初始化报告"
  echo "================================================"
  echo ""
  echo "状态: $status"
  echo "模式: $MODE"
  echo "模板: $TEMPLATE_DIR"
  echo "目标: $TARGET_DIR"
  echo ""
  echo "--- 检测到的能力 ---"
  echo "  frontend:      $CAP_frontend"
  echo "  backend-api:   $CAP_backend_api"
  echo "  database:      $CAP_database"
  echo "  i18n:          $CAP_i18n"
  echo "  testing:       $CAP_testing"
  echo "  cross-compile: $CAP_cross_compile"
  echo "  design-system: $CAP_design_system"
  echo "  ci-cd:         $CAP_ci_cd"
  echo "  monorepo:      $CAP_monorepo"
  echo "  static-types:  $CAP_static_types"
  echo "  websocket:     $CAP_websocket (派生)"
  echo ""
  local report_skill_count report_hook_count
  report_skill_count=$(find "$TARGET_DIR/skills" -name "SKILL.md" 2>/dev/null | wc -l | tr -d ' ')
  report_hook_count=$(find "$TARGET_DIR/hooks" -name "*.sh" 2>/dev/null | wc -l | tr -d ' ')
  echo "--- 安装统计 ---"
  echo "  已安装文件: $INSTALLED_FILES"
  echo "  Skills:     $report_skill_count (直接复制)"
  echo "  Hooks:      $report_hook_count (含配置填充)"
  echo "  Scripts:     $INSTALLED_SCRIPTS"
  echo "  Settings:    1"
  echo ""

  if [ "$ERRORS" -gt 0 ]; then
    echo "--- 错误 ---"
    echo "  $ERRORS 个错误需要修复"
    echo ""
  fi

  if [ "$WARNINGS" -gt 0 ]; then
    echo "--- 警告 ---"
    echo "  $WARNINGS 个警告"
    echo ""
  fi

  # TODO count
  if [ -f "$CLAUDE_MD" ]; then
    local todo_count
    todo_count=$(grep -c 'TODO' "$CLAUDE_MD" 2>/dev/null) || todo_count=0
    if [ "${todo_count:-0}" -gt 0 ]; then
      echo "--- 待办 ---"
      echo "  CLAUDE.md 中有 $todo_count 个 TODO 标记"
      echo "  请手动补全这些标记以确保工作流正常运行"
      echo ""
    fi
  fi

  # Inline PS count (items kept as template defaults)
  local ps_inline
  ps_inline=$(grep -rc '<!-- PROJECT-SPECIFIC:' "$TARGET_DIR/skills/" 2>/dev/null | awk -F: '{s+=$NF} END{print s+0}') || true
  if [ "$ps_inline" -gt 0 ]; then
    echo "--- 内联 PS 标记 ---"
    echo "  $ps_inline 个 PROJECT-SPECIFIC 标记保留为模板默认值"
    echo "  这些标记是对 CLAUDE.md 的引用提示，无需处理"
    echo ""
  fi

  echo "================================================"
}

# ============================================================
# Upgrade Mode
# ============================================================
upgrade_mode() {
  info "执行升级模式..."

  # U1: Scan installed versions
  info "扫描已安装版本..."
  local changes=0

  # U2: Backup
  local backup_dir="$TARGET_DIR/_backup/$(date +%Y%m%d%H%M%S)"
  if [ "$DRY_RUN" = true ]; then
    info "[DRY-RUN] 将备份到 $backup_dir"
  else
    mkdir -p "$backup_dir"
    # Backup existing files (include agents for legacy rollback support)
    for dir in skills hooks scripts agents; do
      if [ -d "$TARGET_DIR/$dir" ]; then
        cp -r "$TARGET_DIR/$dir" "$backup_dir/$dir" 2>/dev/null || true
      fi
    done
    [ -f "$TARGET_DIR/settings.json" ] && cp "$TARGET_DIR/settings.json" "$backup_dir/"
    info "已备份到 $backup_dir"
  fi

  # U3: Clean managed directories (remove deprecated files before re-install)
  if [ "$DRY_RUN" = true ]; then
    info "[DRY-RUN] 清理受管目录: skills, hooks, scripts（遗留 agents 目录如存在将单独清理）"
  else
    # Remove managed content (workspace/context are user data, never touched)
    for dir in skills hooks scripts; do
      if [ -d "$TARGET_DIR/$dir" ]; then
        rm -rf "$TARGET_DIR/$dir"
        verbose "已清理: $TARGET_DIR/$dir"
      fi
    done
    # Clean legacy agents directory if it exists (agents removed since v2.0.0)
    if [ -d "$TARGET_DIR/agents" ]; then
      info "清理遗留 agents 目录（已由 Claude Code 内置 agent 类型替代）"
      rm -rf "$TARGET_DIR/agents"
    fi
  fi

  # U4: Re-install from template
  create_directories
  install_skills
  install_hooks
  install_scripts
  install_settings

  # U5: Validate
  if [ "$DRY_RUN" != true ]; then
    validate_all || true
  fi

  # U6: Generate diff summary
  if [ "$DRY_RUN" != true ] && [ -d "$backup_dir" ]; then
    info "变更摘要:"
    local changed=0
    local added=0
    local removed=0
    # 检测变更和已删除的文件（遍历旧文件）
    for dir in skills hooks scripts; do
      if [ -d "$backup_dir/$dir" ]; then
        while IFS= read -r old_file; do
          local rel_path="${old_file#$backup_dir/}"
          local new_file="$TARGET_DIR/$rel_path"
          if [ ! -f "$new_file" ]; then
            verbose "  删除: $rel_path"
            removed=$((removed + 1))
          elif ! diff -q "$old_file" "$new_file" >/dev/null 2>&1; then
            verbose "  变更: $rel_path"
            changed=$((changed + 1))
          fi
        done < <(find "$backup_dir/$dir" -type f 2>/dev/null)
      fi
    done
    # 检测新增文件（遍历新文件，查找 backup 中不存在的）
    for dir in skills hooks scripts; do
      if [ -d "$TARGET_DIR/$dir" ]; then
        while IFS= read -r new_file; do
          local rel_path="${new_file#$TARGET_DIR/}"
          local old_file="$backup_dir/$rel_path"
          if [ ! -f "$old_file" ]; then
            verbose "  新增: $rel_path"
            added=$((added + 1))
          fi
        done < <(find "$TARGET_DIR/$dir" -type f 2>/dev/null)
      fi
    done
    local summary=""
    [ "$changed" -gt 0 ] && summary="${summary}${changed} 个变更"
    [ "$added" -gt 0 ] && { [ -n "$summary" ] && summary="${summary}、"; summary="${summary}${added} 个新增"; }
    [ "$removed" -gt 0 ] && { [ -n "$summary" ] && summary="${summary}、"; summary="${summary}${removed} 个删除"; }
    [ -z "$summary" ] && summary="无变更"
    info "共 $summary"
  fi
}

# ============================================================
# Main
# ============================================================
main() {
  parse_args "$@"

  info "工作流初始化脚本 v$SCRIPT_VERSION"
  info "项目根目录: $PROJECT_ROOT"
  info "运行模式: $MODE"
  [ "$DRY_RUN" = true ] && info "*** DRY-RUN 模式 ***"

  # Step 1: Project detection
  detect_project

  # Step 2: CLAUDE.md handling
  if [ "$SKIP_CLAUDE_MD" != true ]; then
    if [ ! -f "$CLAUDE_MD" ]; then
      generate_claude_md
    fi
    if [ -f "$CLAUDE_MD" ]; then
      ensure_capabilities
      parse_capabilities_into_vars
    fi
  fi

  derive_implicit_tags
  build_caps_string
  extract_ps_values

  if [ -f "$CLAUDE_MD" ]; then
    validate_claude_md
  fi

  # Step 3: Install
  if [ "$MODE" = "upgrade" ]; then
    upgrade_mode
  else
    create_directories
    install_skills
    install_hooks
    install_scripts
    install_settings

    # Step 4: Validate
    if [ "$DRY_RUN" != true ]; then
      validate_all || true
    fi
  fi

  # Step 5: Report
  output_report

  if [ "$ERRORS" -gt 0 ]; then
    exit 1
  fi
  exit 0
}

main "$@"
