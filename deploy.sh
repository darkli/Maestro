#!/usr/bin/env bash
# ============================================================
# Maestro VPS 部署管理脚本
# 在本地 Mac 上执行，通过 SSH 远程管理 VPS 上的 Maestro
# 用法: bash deploy.sh [命令] [deploy.env 路径]
#   命令: init | update | help
#   无命令时进入交互菜单
# ============================================================
set -euo pipefail

# ---- 颜色输出 ----
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()   { echo -e "${RED}[ERROR]${NC} $*" >&2; }
die()   { err "$@"; exit 1; }

# ============================================================
# SUBCOMMAND 解析 + help 拦截 + ENV_FILE 确定
# ============================================================
case "${1:-}" in
    -h|--help|help)
        echo "用法: deploy.sh [命令] [deploy.env 路径]"
        echo ""
        echo "命令:"
        echo "  init     首次部署（完整安装）"
        echo "  update   业务逻辑更新（仅代码+包）"
        echo "  help     显示此帮助信息"
        echo ""
        echo "无命令时进入交互菜单。"
        echo ""
        echo "deploy.env 路径默认为当前目录的 deploy.env"
        exit 0
        ;;
    init|update)
        SUBCOMMAND="$1"
        ENV_FILE="${2:-deploy.env}"
        ;;
    *)
        SUBCOMMAND=""
        if [[ -n "${1:-}" && -f "${1:-}" ]]; then
            ENV_FILE="$1"
        elif [[ -n "${1:-}" ]]; then
            err "未知命令: $1"
            echo "用法: deploy.sh [init|update|help] [deploy.env 路径]"
            exit 1
        else
            ENV_FILE="${1:-deploy.env}"
        fi
        ;;
esac

# ============================================================
# 读取配置 + SSH 连接（所有操作共用）
# ============================================================
if [[ ! -f "$ENV_FILE" ]]; then
    die "配置文件 $ENV_FILE 不存在，请先复制 deploy.env.example 为 deploy.env 并填入配置"
fi
set -a
# shellcheck source=/dev/null
source "$ENV_FILE"
set +a

# 校验必填项
missing=()
[[ -z "${VPS_HOST:-}" ]]  && missing+=("VPS_HOST")
[[ -z "${VPS_USER:-}" ]]  && missing+=("VPS_USER")
if [[ ${#missing[@]} -gt 0 ]]; then
    die "以下必填项未设置: ${missing[*]}"
fi

# 默认值
VPS_PORT="${VPS_PORT:-22}"
VPS_PASSWORD="${VPS_PASSWORD:-}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
DEPLOY_METHOD="${DEPLOY_METHOD:-rsync}"
DEPLOY_DIR="${DEPLOY_DIR:-/opt/maestro}"
GIT_BRANCH="${GIT_BRANCH:-main}"
MANAGER_PROVIDER="${MANAGER_PROVIDER:-deepseek}"
MANAGER_MODEL="${MANAGER_MODEL:-deepseek-chat}"
MANAGER_API_KEY="${MANAGER_API_KEY:-}"
MANAGER_BASE_URL="${MANAGER_BASE_URL:-}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
SETUP_SYSTEMD="${SETUP_SYSTEMD:-true}"

# ---- SSH 连接复用（ControlMaster） ----
# 整个脚本生命周期共用一个 SSH 连接，避免重复认证和触发防暴力破解
CONTROL_PATH="/tmp/maestro-ssh-control-$$"
COMMON_OPTS="-o StrictHostKeyChecking=accept-new -o ConnectTimeout=10 -o ControlPath=${CONTROL_PATH} -o ServerAliveInterval=30 -o ServerAliveCountMax=6"
SSH_OPTS="$COMMON_OPTS -p ${VPS_PORT}"
SCP_OPTS="$COMMON_OPTS -P ${VPS_PORT}"

# 退出时自动关闭 SSH 连接
cleanup_ssh() {
    if [[ -S "$CONTROL_PATH" ]]; then
        ssh -o ControlPath="$CONTROL_PATH" -O exit "${VPS_USER}@${VPS_HOST}" 2>/dev/null || true
        info "SSH 连接已关闭"
    fi
    rm -f "$CONTROL_PATH" 2>/dev/null || true
}
trap cleanup_ssh EXIT INT TERM

# 构建认证参数
AUTH_OPTS=""
AUTH_CMD=""
if [[ -n "${VPS_SSH_KEY:-}" ]]; then
    if [[ ! -f "$VPS_SSH_KEY" ]]; then
        die "SSH Key 文件不存在: $VPS_SSH_KEY"
    fi
    key_perms=$(stat -f "%Lp" "$VPS_SSH_KEY" 2>/dev/null || stat -c "%a" "$VPS_SSH_KEY" 2>/dev/null)
    if [[ "$key_perms" != "600" && "$key_perms" != "400" ]]; then
        die "SSH Key 权限不安全 ($key_perms)，请执行: chmod 600 $VPS_SSH_KEY"
    fi
    SSH_OPTS="$SSH_OPTS -i $VPS_SSH_KEY"
    SCP_OPTS="$SCP_OPTS -i $VPS_SSH_KEY"
elif [[ -n "$VPS_PASSWORD" ]]; then
    if ! command -v sshpass &>/dev/null; then
        die "密码登录需要 sshpass，请先安装: brew install sshpass（macOS）"
    fi
    AUTH_CMD="sshpass -p $VPS_PASSWORD"
fi

# 建立 ControlMaster 持久连接
info "连接 ${VPS_USER}@${VPS_HOST}:${VPS_PORT} ..."
if ! $AUTH_CMD ssh $SSH_OPTS -o ControlMaster=yes -o ControlPersist=yes -fN "${VPS_USER}@${VPS_HOST}" 2>/dev/null; then
    die "SSH 连接失败，请检查 VPS 配置"
fi
ok "SSH 连接成功（复用模式）"

# 后续命令通过 ControlPath 复用；若连接断开，sshpass 自动重新认证
run_ssh()       { $AUTH_CMD ssh $SSH_OPTS "${VPS_USER}@${VPS_HOST}" "$@" < /dev/null; }
run_ssh_pipe()  { $AUTH_CMD ssh $SSH_OPTS "${VPS_USER}@${VPS_HOST}" "$@"; }
run_scp()       { $AUTH_CMD scp $SCP_OPTS "$@"; }

# ============================================================
# do_transfer() — 文件传输（从 do_deploy() Phase 1 拆分）
# ============================================================
do_transfer() {
    info "========== Phase 1: 传输项目文件 =========="
    run_ssh "mkdir -p $DEPLOY_DIR"

    if [[ "$DEPLOY_METHOD" == "rsync" ]]; then
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

        info "打包项目文件 ..."
        TARBALL="/tmp/maestro-deploy-$$.tar.gz"
        COPYFILE_DISABLE=1 tar czf "$TARBALL" \
            --no-mac-metadata \
            -C "$SCRIPT_DIR" \
            --exclude='.git' \
            --exclude='_legacy' \
            --exclude='.claude' \
            --exclude='.venv' \
            --exclude='config.yaml' \
            --exclude='deploy.env' \
            --exclude='__pycache__' \
            --exclude='*.pyc' \
            --exclude='.env' \
            .

        info "上传到 VPS ..."
        run_scp "$TARBALL" "${VPS_USER}@[${VPS_HOST}]:${DEPLOY_DIR}/_deploy.tar.gz"
        rm -f "$TARBALL"

        info "在 VPS 上解压 ..."
        run_ssh "cd $DEPLOY_DIR && tar xzf _deploy.tar.gz && rm -f _deploy.tar.gz"
        ok "文件传输完成"

    elif [[ "$DEPLOY_METHOD" == "git" ]]; then
        if [[ -z "${GIT_REPO:-}" ]]; then
            die "git 模式需要设置 GIT_REPO"
        fi
        info "使用 git 部署: $GIT_REPO (branch: $GIT_BRANCH) ..."
        run_ssh "
            if [[ -d $DEPLOY_DIR/.git ]]; then
                cd $DEPLOY_DIR && git fetch origin && git checkout $GIT_BRANCH && git pull origin $GIT_BRANCH
            else
                git clone -b $GIT_BRANCH $GIT_REPO $DEPLOY_DIR
            fi
        "
        ok "git 部署完成"
    else
        die "不支持的部署方式: $DEPLOY_METHOD（仅支持 rsync | git）"
    fi
}

# ============================================================
# do_remote_full_install() — 完整远程安装（从 do_deploy() Phase 2 拆分）
# ============================================================
do_remote_full_install() {
    # 校验部署必填项
    if [[ "${MANAGER_PROVIDER:-}" != "ollama" && -z "${MANAGER_API_KEY:-}" ]]; then
        die "部署需要设置 MANAGER_API_KEY（Ollama 除外）"
    fi

    info "========== Phase 2: 远程安装 =========="

    # ---- 构造远程变量注入段 ----
    VARS_SECTION="
DEPLOY_DIR='${DEPLOY_DIR}'
VPS_USER='${VPS_USER}'
ANTHROPIC_API_KEY='${ANTHROPIC_API_KEY}'
MANAGER_PROVIDER='${MANAGER_PROVIDER}'
MANAGER_MODEL='${MANAGER_MODEL}'
MANAGER_API_KEY='${MANAGER_API_KEY}'
MANAGER_BASE_URL='${MANAGER_BASE_URL}'
TELEGRAM_BOT_TOKEN='${TELEGRAM_BOT_TOKEN}'
TELEGRAM_CHAT_ID='${TELEGRAM_CHAT_ID}'
SETUP_SYSTEMD='${SETUP_SYSTEMD}'
"

    # ---- 构造远程安装脚本 ----
    REMOTE_SCRIPT_TMP=$(mktemp)
    cat > "$REMOTE_SCRIPT_TMP" << 'REMOTE_EOF'
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[远程]${NC} $*"; }
ok()    { echo -e "${GREEN}[远程 OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[远程 WARN]${NC} $*"; }
die()   { echo -e "${RED}[远程 ERROR]${NC} $*" >&2; exit 1; }

# ---- 前置检查 ----
if ! command -v apt-get &>/dev/null; then
    die "仅支持 Debian/Ubuntu 系统（需要 apt-get）"
fi

avail_kb=$(df -k "$DEPLOY_DIR" | awk 'NR==2 {print $4}')
avail_gb=$((avail_kb / 1024 / 1024))
if [[ $avail_kb -lt 2097152 ]]; then
    die "磁盘可用空间不足: ${avail_gb}GB，需要至少 2GB"
fi

total_mem_kb=$(grep MemTotal /proc/meminfo | awk '{print $2}')
total_mem_mb=$((total_mem_kb / 1024))
if [[ $total_mem_mb -lt 2048 ]]; then
    warn "内存较低: ${total_mem_mb}MB，建议至少 2GB"
fi

# ---- sudo 处理 ----
SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
    if sudo -n true 2>/dev/null; then
        SUDO="sudo"
    else
        die "非 root 用户且 sudo 需要密码，请使用 root 用户或配置免密 sudo"
    fi
fi

# ---- 记录部署前环境快照 ----
STATE_FILE="$DEPLOY_DIR/.pre-deploy-state"
if [[ ! -f "$STATE_FILE" ]]; then
    info "记录部署前环境快照 ..."
    {
        echo "# 部署前环境快照（deploy.sh 自动生成）"
        echo "# 清理时只删除由 deploy.sh 安装的组件"
        command -v node &>/dev/null && echo "HAD_NODEJS=true" || echo "HAD_NODEJS=false"
        command -v claude &>/dev/null && echo "HAD_CLAUDE=true" || echo "HAD_CLAUDE=false"
        (command -v zellij &>/dev/null || [[ -x "$HOME/.local/bin/zellij" ]]) && echo "HAD_ZELLIJ=true" || echo "HAD_ZELLIJ=false"
    } > "$STATE_FILE"
    ok "环境快照已记录: $STATE_FILE"
else
    info "环境快照已存在，跳过记录"
fi

# ---- 系统包 ----
info "安装系统依赖 ..."
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq python3 python3-pip python3-venv git curl software-properties-common
ok "系统依赖安装完成"

# ---- Python 版本检查 ----
PYTHON="python3"
py_version=$($PYTHON --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
py_major=$(echo "$py_version" | cut -d. -f1)
py_minor=$(echo "$py_version" | cut -d. -f2)

if [[ $py_major -lt 3 ]] || [[ $py_major -eq 3 && $py_minor -lt 10 ]]; then
    info "Python $py_version < 3.10，安装 Python 3.12 ..."
    $SUDO add-apt-repository -y ppa:deadsnakes/ppa
    $SUDO apt-get update -qq
    $SUDO apt-get install -y -qq python3.12 python3.12-venv python3.12-dev
    PYTHON="python3.12"
    ok "Python 3.12 安装完成"
else
    ok "Python 版本: $py_version"
fi

# ---- Node.js ----
if command -v node &>/dev/null; then
    node_version=$(node --version | tr -d 'v' | cut -d. -f1)
    if [[ $node_version -ge 18 ]]; then
        ok "Node.js 已安装: $(node --version)"
    else
        info "Node.js 版本过低，升级到 22.x ..."
        curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO bash -
        $SUDO apt-get install -y -qq nodejs
        ok "Node.js 升级完成: $(node --version)"
    fi
else
    info "安装 Node.js 22.x ..."
    curl -fsSL https://deb.nodesource.com/setup_22.x | $SUDO bash -
    $SUDO apt-get install -y -qq nodejs
    ok "Node.js 安装完成: $(node --version)"
fi

# ---- Claude Code ----
if command -v claude &>/dev/null; then
    ok "Claude Code 已安装: $(claude --version 2>/dev/null || echo 'installed')"
else
    info "安装 Claude Code ..."
    $SUDO npm install -g @anthropic-ai/claude-code
    ok "Claude Code 安装完成"
fi

# ---- Zellij ----
if command -v zellij &>/dev/null || [[ -x "$HOME/.local/bin/zellij" ]]; then
    ok "Zellij 已安装"
else
    info "安装 Zellij v0.41.2 ..."
    ZELLIJ_DIR="$HOME/.local/bin"
    mkdir -p "$ZELLIJ_DIR"
    ARCH=$(uname -m)
    case "$ARCH" in
        x86_64)  ZELLIJ_ARCH="x86_64" ;;
        aarch64) ZELLIJ_ARCH="aarch64" ;;
        *)       die "不支持的架构: $ARCH" ;;
    esac
    curl -fsSL "https://github.com/zellij-org/zellij/releases/download/v0.41.2/zellij-${ZELLIJ_ARCH}-unknown-linux-musl.tar.gz" \
        | tar xz -C "$ZELLIJ_DIR"
    chmod +x "$ZELLIJ_DIR/zellij"
    ok "Zellij 安装完成"
fi

# ---- Python venv + pip install ----
info "创建 Python 虚拟环境 ..."
cd "$DEPLOY_DIR"
$PYTHON -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e . -q
ok "Python 环境配置完成"

# ---- 生成 config.yaml ----
info "生成 config.yaml ..."
CONFIG_FILE="$DEPLOY_DIR/config.yaml"

TG_ENABLED="false"
[[ -n "$TELEGRAM_BOT_TOKEN" ]] && TG_ENABLED="true"

cat > "$CONFIG_FILE" << CFGEOF
# 由 deploy.sh 自动生成
manager:
  provider: $MANAGER_PROVIDER
  model: $MANAGER_MODEL
  api_key: "$MANAGER_API_KEY"
CFGEOF

if [[ -n "$MANAGER_BASE_URL" ]]; then
    echo "  base_url: \"$MANAGER_BASE_URL\"" >> "$CONFIG_FILE"
fi

cat >> "$CONFIG_FILE" << CFGEOF
  max_turns: 30
  max_budget_usd: 5.0
  request_timeout: 60
  retry_count: 3

coding_tool:
  type: claude
  command: claude
  auto_approve: true
  timeout: 600

context:
  max_recent_turns: 5
  max_result_chars: 3000

safety:
  max_consecutive_similar: 3
  max_parallel_tasks: 3

telegram:
  enabled: $TG_ENABLED
  bot_token: "$TELEGRAM_BOT_TOKEN"
  chat_id: "$TELEGRAM_CHAT_ID"
  push_every_turn: true
  ask_user_timeout: 3600

zellij:
  enabled: true
  auto_install: true

logging:
  dir: ~/.maestro/logs
  level: INFO
  max_days: 30
CFGEOF
chmod 600 "$CONFIG_FILE"
ok "config.yaml 已生成"

# ---- 环境变量 ----
info "配置环境变量 ..."

DOT_ENV="$DEPLOY_DIR/.env"
{
    echo "PATH=$HOME/.local/bin:$DEPLOY_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
        echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
    fi
} > "$DOT_ENV"
chmod 600 "$DOT_ENV"

BASHRC="$HOME/.bashrc"
MARKER_START="# >>> maestro >>>"
MARKER_END="# <<< maestro <<<"
if [[ -f "$BASHRC" ]]; then
    sed -i '/# >>> maestro >>>/,/# <<< maestro <<</d' "$BASHRC"
fi
{
    echo "$MARKER_START"
    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
        echo "export ANTHROPIC_API_KEY=\"$ANTHROPIC_API_KEY\""
    fi
    echo "export PATH=\"\$HOME/.local/bin:$DEPLOY_DIR/.venv/bin:\$PATH\""
    echo "$MARKER_END"
} >> "$BASHRC"
ok "环境变量已配置"

# ---- systemd 服务 ----
if [[ "$SETUP_SYSTEMD" == "true" && "$TG_ENABLED" == "true" ]]; then
    info "创建 systemd 服务 ..."
    SERVICE_FILE="/etc/systemd/system/maestro-daemon.service"
    $SUDO tee "$SERVICE_FILE" > /dev/null << SVCEOF
[Unit]
Description=Maestro Telegram Daemon
After=network.target

[Service]
Type=simple
User=$VPS_USER
WorkingDirectory=$DEPLOY_DIR
EnvironmentFile=$DEPLOY_DIR/.env
ExecStart=$DEPLOY_DIR/.venv/bin/python -m maestro.telegram_bot --config $DEPLOY_DIR/config.yaml
Restart=on-failure
RestartSec=30
StartLimitBurst=5

[Install]
WantedBy=multi-user.target
SVCEOF
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable maestro-daemon

    if [[ -n "$ANTHROPIC_API_KEY" ]] || [[ -d "$HOME/.claude" ]]; then
        $SUDO systemctl restart maestro-daemon
        ok "systemd 服务已创建并启动"
    else
        ok "systemd 服务已创建（等 claude login 后启动）"
    fi
else
    if [[ "$SETUP_SYSTEMD" == "true" ]]; then
        warn "未配置 Telegram，跳过 systemd 服务"
    fi
fi

ok "远程安装全部完成"
REMOTE_EOF

    # ---- 管道执行 ----
    { echo "$VARS_SECTION"; cat "$REMOTE_SCRIPT_TMP"; } | run_ssh_pipe bash
    rm -f "$REMOTE_SCRIPT_TMP"

    ok "远程安装全部完成"
}

# ============================================================
# do_remote_quick_update() — 轻量远程更新（新增）
# ============================================================
do_remote_quick_update() {
    info "========== 远程更新 Python 包 =========="

    run_ssh "
        cd $DEPLOY_DIR
        source .venv/bin/activate
        pip install -e . -q
        echo '[远程 OK] pip install 完成'
    "
    ok "Python 包更新完成"

    # systemd 服务重启（如存在且已启用）
    DAEMON_ENABLED=$(run_ssh "systemctl is-enabled maestro-daemon 2>/dev/null" || true)
    if [[ "$DAEMON_ENABLED" == "enabled" ]]; then
        info "重启 maestro-daemon 服务 ..."
        run_ssh "sudo systemctl restart maestro-daemon"
        sleep 2
        DAEMON_STATUS=$(run_ssh "sudo systemctl is-active maestro-daemon 2>/dev/null" || true)
        if [[ "$DAEMON_STATUS" == "active" ]]; then
            ok "maestro-daemon 已重启"
        else
            warn "maestro-daemon 重启异常，请检查: sudo systemctl status maestro-daemon"
        fi
    else
        info "maestro-daemon 未启用，跳过重启"
    fi
}

# ============================================================
# do_claude_auth() — Claude Code 认证引导（从 do_deploy() 尾部拆分）
# ============================================================
do_claude_auth() {
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        if run_ssh "test -d ~/.claude" 2>/dev/null; then
            ok "Claude Code 已认证（检测到 ~/.claude）"

            if [[ -n "$TELEGRAM_BOT_TOKEN" && "$SETUP_SYSTEMD" == "true" ]]; then
                DAEMON_STATUS=$(run_ssh "sudo systemctl is-active maestro-daemon 2>/dev/null" || true)
                if [[ "$DAEMON_STATUS" != "active" ]]; then
                    info "启动 Telegram Daemon ..."
                    run_ssh "sudo systemctl restart maestro-daemon"
                    sleep 2
                    DAEMON_STATUS=$(run_ssh "sudo systemctl is-active maestro-daemon 2>/dev/null" || true)
                fi
                if [[ "$DAEMON_STATUS" == "active" ]]; then
                    ok "Telegram Daemon 运行中"
                else
                    warn "Daemon 启动异常，请检查: sudo systemctl status maestro-daemon"
                fi
            fi
        else
            echo ""
            echo -e "${YELLOW}============================================================${NC}"
            echo -e "${YELLOW}  Claude Code 登录认证（只需一次）${NC}"
            echo -e "${YELLOW}============================================================${NC}"
            echo ""
            echo "  请打开另一个终端窗口，执行以下命令："
            echo ""
            echo -e "    ${GREEN}ssh ${VPS_SSH_KEY:+-i $VPS_SSH_KEY }-p $VPS_PORT ${VPS_USER}@${VPS_HOST}${NC}"
            echo -e "    ${GREEN}claude login${NC}"
            echo ""
            echo "  按提示在浏览器中完成授权。"
            echo "  认证信息保存在 ~/.claude/，所有终端会话共享，只需登录一次。"
            echo ""
            echo -e "${YELLOW}  完成后回到此窗口按 Enter 继续 ...${NC}"
            read -r < /dev/tty

            info "检查 Claude Code 认证状态 ..."
            if run_ssh "test -d ~/.claude" 2>/dev/null; then
                ok "Claude Code 认证成功"

                if [[ -n "$TELEGRAM_BOT_TOKEN" && "$SETUP_SYSTEMD" == "true" ]]; then
                    info "启动 Telegram Daemon ..."
                    run_ssh "sudo systemctl restart maestro-daemon"
                    sleep 2
                    DAEMON_STATUS=$(run_ssh "sudo systemctl is-active maestro-daemon 2>/dev/null" || true)
                    if [[ "$DAEMON_STATUS" == "active" ]]; then
                        ok "Telegram Daemon 已启动"
                    else
                        warn "Daemon 启动异常，请检查: sudo systemctl status maestro-daemon"
                    fi
                fi
            else
                warn "未检测到 ~/.claude 目录，claude login 可能未完成"
                echo ""
                echo "  你可以稍后 SSH 到 VPS 手动执行："
                echo "    claude login"
                if [[ -n "$TELEGRAM_BOT_TOKEN" ]]; then
                    echo "    sudo systemctl start maestro-daemon"
                fi
            fi
        fi
    fi
}

# ============================================================
# do_init() — 首次部署（组合函数）
# ============================================================
do_init() {
    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
        info "Claude Code 认证: API Key（按量计费）"
    else
        info "Claude Code 认证: 部署后引导 claude login（Max/Pro 订阅）"
    fi

    do_transfer
    do_remote_full_install

    ok "========== 远程安装完成! =========="

    do_claude_auth

    echo ""
    ok "========== 全部部署完成! =========="
    echo ""
    echo "  部署目录: $DEPLOY_DIR"
    echo "  使用方式:"
    echo "    ssh ${VPS_SSH_KEY:+-i $VPS_SSH_KEY }-p $VPS_PORT ${VPS_USER}@${VPS_HOST}"
    echo "    cd $DEPLOY_DIR && source .venv/bin/activate"
    echo "    maestro run \"你的需求\""
    echo ""
}

# ============================================================
# do_update() — 业务逻辑更新（组合函数，新增）
# ============================================================
do_update() {
    # 前置检查：远程 .venv 是否存在
    if ! run_ssh "test -d $DEPLOY_DIR/.venv" 2>/dev/null; then
        die "远程环境未初始化（$DEPLOY_DIR/.venv 不存在），请先执行: deploy.sh init"
    fi

    # 备份远端 prompts/（如存在用户自定义内容）
    # deploy.sh update 的 tar 解压会全量覆盖，需要保护用户修改
    run_ssh "
        if [[ -d $DEPLOY_DIR/prompts ]]; then
            if cp -r $DEPLOY_DIR/prompts /tmp/_maestro_prompts_bak; then
                echo '[远程] prompts 已备份'
            else
                echo '[远程 WARN] prompts 备份失败，自定义 prompts 可能被覆盖'
            fi
        fi
    " || true

    do_transfer

    # 恢复远端 prompts/（用备份覆盖传输过来的默认版本）
    run_ssh "
        if [[ -d /tmp/_maestro_prompts_bak ]]; then
            if cp -r /tmp/_maestro_prompts_bak/* $DEPLOY_DIR/prompts/ 2>/dev/null; then
                echo '[远程] prompts 已恢复'
            else
                echo '[远程 WARN] prompts 恢复失败，请手动检查 /tmp/_maestro_prompts_bak'
            fi
            rm -rf /tmp/_maestro_prompts_bak
        fi
    " || true

    do_remote_quick_update

    echo ""
    ok "========== 业务逻辑更新完成! =========="
    echo ""
}

# ============================================================
# do_status() — 查看状态（不变）
# ============================================================
do_status() {
    info "查询 VPS 状态 ..."
    echo ""

    # 用单次 SSH 收集所有信息，避免多次连接
    STATUS_OUTPUT=$(run_ssh "
        DEPLOY_DIR='${DEPLOY_DIR}'

        echo '=== 系统信息 ==='
        echo \"OS: \$(lsb_release -ds 2>/dev/null || cat /etc/os-release 2>/dev/null | head -1 || echo unknown)\"
        echo \"Kernel: \$(uname -r)\"
        echo \"Arch: \$(uname -m)\"

        total_mem=\$(grep MemTotal /proc/meminfo | awk '{printf \"%.0f\", \$2/1024}')
        avail_mem=\$(grep MemAvailable /proc/meminfo | awk '{printf \"%.0f\", \$2/1024}')
        echo \"Memory: \${avail_mem}MB free / \${total_mem}MB total\"

        avail_disk=\$(df -h / | awk 'NR==2 {print \$4}')
        total_disk=\$(df -h / | awk 'NR==2 {print \$2}')
        echo \"Disk: \${avail_disk} free / \${total_disk} total\"

        echo ''
        echo '=== 组件版本 ==='
        echo -n 'Python: '; python3 --version 2>&1 | awk '{print \$2}' || echo '未安装'
        echo -n 'Node.js: '; node --version 2>/dev/null || echo '未安装'
        echo -n 'Claude Code: '; claude --version 2>/dev/null || echo '未安装'
        echo -n 'Zellij: '; (zellij --version 2>/dev/null || \$HOME/.local/bin/zellij --version 2>/dev/null) || echo '未安装'

        echo ''
        echo '=== Maestro ==='
        if [[ -d \"\$DEPLOY_DIR\" ]]; then
            echo \"部署目录: \$DEPLOY_DIR (存在)\"
            if [[ -f \"\$DEPLOY_DIR/config.yaml\" ]]; then
                echo 'config.yaml: 存在'
            else
                echo 'config.yaml: 不存在'
            fi
            if [[ -d \"\$DEPLOY_DIR/.venv\" ]]; then
                echo 'Python venv: 存在'
                if \$DEPLOY_DIR/.venv/bin/maestro --help &>/dev/null; then
                    echo 'Maestro CLI: 正常'
                else
                    echo 'Maestro CLI: 异常'
                fi
            else
                echo 'Python venv: 不存在'
            fi
        else
            echo \"部署目录: \$DEPLOY_DIR (不存在)\"
        fi

        echo ''
        echo '=== Claude Code 认证 ==='
        if [[ -d \"\$HOME/.claude\" ]]; then
            echo '状态: 已认证 (~/.claude 存在)'
        else
            echo '状态: 未认证'
        fi

        echo ''
        echo '=== Telegram Daemon ==='
        if systemctl is-enabled maestro-daemon &>/dev/null; then
            status=\$(systemctl is-active maestro-daemon 2>/dev/null || true)
            echo \"服务状态: \$status\"
            echo \"开机自启: \$(systemctl is-enabled maestro-daemon 2>/dev/null)\"
            if [[ \"\$status\" == \"active\" ]]; then
                pid=\$(systemctl show maestro-daemon --property=MainPID --value 2>/dev/null)
                uptime=\$(systemctl show maestro-daemon --property=ActiveEnterTimestamp --value 2>/dev/null)
                echo \"PID: \$pid\"
                echo \"启动时间: \$uptime\"
            fi
        else
            echo '服务状态: 未安装'
        fi

        echo ''
        echo '=== 运行中的 Maestro 任务 ==='
        if [[ -d \"\$HOME/.maestro\" ]]; then
            task_count=\$(find \"\$HOME/.maestro\" -name 'state.json' 2>/dev/null | wc -l)
            echo \"任务数: \$task_count\"
        else
            echo '无任务记录'
        fi
    " 2>/dev/null || true)

    # 格式化输出
    echo -e "${CYAN}┌──────────────────────────────────────────┐${NC}"
    echo -e "${CYAN}│  Maestro VPS 状态                        │${NC}"
    echo -e "${CYAN}│  ${NC}${VPS_USER}@${VPS_HOST}:${VPS_PORT}${CYAN}${NC}"
    echo -e "${CYAN}└──────────────────────────────────────────┘${NC}"
    echo ""
    echo "$STATUS_OUTPUT"
    echo ""
}

# ============================================================
# do_clean() — 清理卸载（不变）
# ============================================================
do_clean() {
    echo ""
    echo -e "${YELLOW}============================================================${NC}"
    echo -e "${YELLOW}  清理卸载 Maestro${NC}"
    echo -e "${YELLOW}  目标: ${VPS_USER}@${VPS_HOST}:${VPS_PORT}${NC}"
    echo -e "${YELLOW}  部署目录: ${DEPLOY_DIR}${NC}"
    echo -e "${YELLOW}============================================================${NC}"
    echo ""
    # 读取环境快照（如有）判断哪些工具是部署脚本安装的
    PRE_STATE=$(run_ssh "cat ${DEPLOY_DIR}/.pre-deploy-state 2>/dev/null" || true)
    HAD_NODEJS=true; HAD_CLAUDE=true; HAD_ZELLIJ=true
    if [[ -n "$PRE_STATE" ]]; then
        eval "$(echo "$PRE_STATE" | grep -E '^HAD_')"
    fi

    echo "  将执行以下操作："
    echo "    1. 停止并移除 systemd 服务（maestro-daemon）"
    echo "    2. 删除部署目录（${DEPLOY_DIR}）"
    echo "    3. 清理 bashrc 中的 maestro 环境变量"
    echo "    4. 删除 Maestro 日志（~/.maestro）"
    echo "    5. 删除 Claude Code 认证（~/.claude）"
    [[ "$HAD_CLAUDE" == "false" ]] && echo "    6. 卸载 Claude Code（部署时安装）"
    [[ "$HAD_ZELLIJ" == "false" ]] && echo "    7. 删除 Zellij（部署时安装）"
    [[ "$HAD_NODEJS" == "false" ]] && echo "    8. 卸载 Node.js（部署时安装）"
    echo ""
    echo "  以下内容保留（部署前已存在）："
    KEEP_LIST=""
    [[ "$HAD_NODEJS" == "true" ]] && KEEP_LIST="${KEEP_LIST}Node.js、"
    [[ "$HAD_CLAUDE" == "true" ]] && KEEP_LIST="${KEEP_LIST}Claude Code、"
    [[ "$HAD_ZELLIJ" == "true" ]] && KEEP_LIST="${KEEP_LIST}Zellij、"
    KEEP_LIST="${KEEP_LIST}Python（系统级）"
    echo "    - ${KEEP_LIST}"
    echo ""
    echo -e "${RED}  此操作不可恢复！${NC}"
    echo ""
    read -r -p "  确认清理？输入 yes 继续: " CONFIRM

    if [[ "$CONFIRM" != "yes" ]]; then
        info "已取消"
        return
    fi

    info "开始清理 ..."

    CLEAN_SCRIPT=$(cat << 'CLEAN_EOF'
set -uo pipefail

SUDO=""
if [[ "$(id -u)" -ne 0 ]]; then
    sudo -n true 2>/dev/null && SUDO="sudo"
fi

# 停止 systemd 服务
if systemctl is-enabled maestro-daemon &>/dev/null; then
    echo "[清理] 停止 maestro-daemon 服务 ..."
    $SUDO systemctl stop maestro-daemon 2>/dev/null || true
    $SUDO systemctl disable maestro-daemon 2>/dev/null || true
    $SUDO rm -f /etc/systemd/system/maestro-daemon.service
    $SUDO systemctl daemon-reload
    echo "[清理] systemd 服务已移除"
else
    echo "[清理] systemd 服务不存在，跳过"
fi

# 删除部署目录
if [[ -d "$DEPLOY_DIR" ]]; then
    rm -rf "$DEPLOY_DIR"
    echo "[清理] 部署目录已删除: $DEPLOY_DIR"
else
    echo "[清理] 部署目录不存在，跳过"
fi

# 清理 bashrc
BASHRC="$HOME/.bashrc"
if [[ -f "$BASHRC" ]] && grep -q '# >>> maestro >>>' "$BASHRC"; then
    sed -i '/# >>> maestro >>>/,/# <<< maestro <<</d' "$BASHRC"
    echo "[清理] bashrc 环境变量已清理"
else
    echo "[清理] bashrc 无 maestro 配置，跳过"
fi

# 清理日志和任务记录
if [[ -d "$HOME/.maestro" ]]; then
    rm -rf "$HOME/.maestro"
    echo "[清理] ~/.maestro 已删除"
fi

# 删除 Claude Code 认证
if [[ -d "$HOME/.claude" ]]; then
    rm -rf "$HOME/.claude"
    echo "[清理] ~/.claude 认证已删除"
fi

# 根据快照决定是否卸载工具
if [[ "$HAD_CLAUDE" == "false" ]]; then
    if command -v claude &>/dev/null; then
        $SUDO npm uninstall -g @anthropic-ai/claude-code 2>/dev/null || true
        echo "[清理] Claude Code 已卸载（部署时安装）"
    fi
else
    echo "[清理] Claude Code 保留（部署前已存在）"
fi

if [[ "$HAD_ZELLIJ" == "false" ]]; then
    if [[ -x "$HOME/.local/bin/zellij" ]]; then
        rm -f "$HOME/.local/bin/zellij"
        echo "[清理] Zellij 已删除（部署时安装）"
    elif command -v zellij &>/dev/null; then
        $SUDO rm -f "$(command -v zellij)" 2>/dev/null || true
        echo "[清理] Zellij 已删除（部署时安装）"
    fi
else
    echo "[清理] Zellij 保留（部署前已存在）"
fi

if [[ "$HAD_NODEJS" == "false" ]]; then
    $SUDO apt-get remove -y -qq nodejs 2>/dev/null || true
    echo "[清理] Node.js 已卸载（部署时安装）"
else
    echo "[清理] Node.js 保留（部署前已存在）"
fi

echo ""
echo "[清理] 全部完成"
CLEAN_EOF
)

    echo "DEPLOY_DIR='${DEPLOY_DIR}'
HAD_NODEJS='${HAD_NODEJS}'
HAD_CLAUDE='${HAD_CLAUDE}'
HAD_ZELLIJ='${HAD_ZELLIJ}'
${CLEAN_SCRIPT}" | run_ssh_pipe bash

    echo ""
    ok "VPS 清理完成"
    echo ""
    echo "  已清理: systemd 服务、部署目录、环境变量、日志、认证"
    echo "  工具卸载: 仅删除部署时安装的组件，部署前已有的已保留"
    echo ""
    echo "  如需重新部署，再次运行此脚本选择「部署」即可。"
    echo ""
}

# ============================================================
# 交互菜单（改造为 4 项）
# ============================================================
show_menu() {
    echo ""
    echo -e "${CYAN}  ╔══════════════════════════════════════╗${NC}"
    echo -e "${CYAN}  ║     Maestro VPS 部署管理工具         ║${NC}"
    echo -e "${CYAN}  ╚══════════════════════════════════════╝${NC}"
    echo ""
    echo "  目标: ${VPS_USER}@${VPS_HOST}:${VPS_PORT}"
    echo ""
    echo "  1) 首次部署（完整安装）"
    echo "  2) 业务逻辑更新（仅代码+包）"
    echo "  3) 查看状态"
    echo "  4) 清理卸载"
    echo "  0) 退出"
    echo ""
}

# ============================================================
# 入口：参数模式 vs 交互菜单
# ============================================================
case "$SUBCOMMAND" in
    init)
        do_init
        ;;
    update)
        do_update
        ;;
    "")
        # 无子命令 → 进入交互菜单
        while true; do
            show_menu
            read -r -p "  请选择 [0-4]: " MENU_CHOICE
            case "$MENU_CHOICE" in
                1) do_init ;;
                2) do_update ;;
                3) do_status ;;
                4) do_clean ;;
                0) echo ""; ok "再见！"; exit 0 ;;
                *) warn "无效选择: $MENU_CHOICE" ;;
            esac
            echo ""
            read -r -p "  按 Enter 返回菜单 ..."
        done
        ;;
esac
