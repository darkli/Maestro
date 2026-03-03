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
        echo "  init               首次部署（完整安装）"
        echo "  update             业务逻辑更新（代码+包+配置）"
        echo "  service start      启动 Daemon 服务"
        echo "  service stop       停止 Daemon 服务"
        echo "  service restart    重启 Daemon 服务"
        echo "  help               显示此帮助信息"
        echo ""
        echo "无命令时进入交互菜单。"
        echo ""
        echo "deploy.env 路径默认为当前目录的 deploy.env"
        exit 0
        ;;
    init|update|service)
        SUBCOMMAND="$1"
        SUBCOMMAND_ARG="${2:-}"
        ENV_FILE="${3:-deploy.env}"
        # service 子命令的 env 也可能在第二个位置
        if [[ "$SUBCOMMAND" != "service" ]]; then
            ENV_FILE="${2:-deploy.env}"
        fi
        ;;
    *)
        SUBCOMMAND=""
        SUBCOMMAND_ARG=""
        if [[ -n "${1:-}" && -f "${1:-}" ]]; then
            ENV_FILE="$1"
        elif [[ -n "${1:-}" ]]; then
            err "未知命令: $1"
            echo "用法: deploy.sh [init|update|service <start|stop|restart>|help] [deploy.env 路径]"
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
PREFER_IPV4="${PREFER_IPV4:-true}"
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
SETUP_SYSTEMD="${SETUP_SYSTEMD:-true}"
# 向后兼容：旧 CODING_TOOL_TYPE → 新 CODING_TOOLS
if [[ -z "${CODING_TOOLS:-}" && -n "${CODING_TOOL_TYPE:-}" ]]; then
    CODING_TOOLS="$CODING_TOOL_TYPE"
    DEFAULT_CODING_TOOL="${CODING_TOOL_TYPE}"
fi
CODING_TOOLS="${CODING_TOOLS:-claude}"
DEFAULT_CODING_TOOL="${DEFAULT_CODING_TOOL:-claude}"
MAESTRO_RUN_USER="${MAESTRO_RUN_USER:-viber}"
MAESTRO_RUN_PASSWORD="${MAESTRO_RUN_PASSWORD:-}"

# 未设密码时自动生成（纯字母数字，避免 shell 转义问题）
if [[ -z "$MAESTRO_RUN_PASSWORD" && "$MAESTRO_RUN_USER" != "root" ]]; then
    MAESTRO_RUN_PASSWORD=$(LC_ALL=C tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)
    info "已自动生成运行用户密码: $MAESTRO_RUN_PASSWORD"
fi

# 部署入口只支持 root SSH（系统操作需要特权，业务层通过 MAESTRO_RUN_USER 隔离）
if [[ "$VPS_USER" != "root" ]]; then
    die "VPS_USER 必须为 root（当前: $VPS_USER）。系统管理需 root 权限，业务执行以 $MAESTRO_RUN_USER 身份运行"
fi

# 业务用户 = root 时警告（Claude Code 内部禁止 root 运行）
if [[ "$MAESTRO_RUN_USER" == "root" ]]; then
    warn "MAESTRO_RUN_USER=root: Claude Code 禁止以 root 运行，建议设置非 root 业务用户（如 viber）"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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
    unset SSHPASS 2>/dev/null || true
}
trap cleanup_ssh EXIT INT TERM

# 构建认证参数
AUTH_OPTS=""
AUTH_CMD=""
if [[ -n "${VPS_SSH_KEY:-}" ]]; then
    # 展开 tilde（用户可能按文档写 ~/.ssh/id_rsa）
    VPS_SSH_KEY="${VPS_SSH_KEY/#\~/$HOME}"
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
    # 使用 -e 模式通过环境变量传递密码，避免 -p 在 ps 进程列表中暴露明文密码
    export SSHPASS="$VPS_PASSWORD"
    AUTH_CMD="sshpass -e"
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

# ---- shell-safe 变量转义（用于构造远端注入段） ----
_qv() { printf '%q' "$1"; }

# ---- YAML 字符串转义（转义 \ 和 " 以安全嵌入双引号值） ----
_yaml_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# ============================================================
# do_transfer() — 文件传输（从 do_deploy() Phase 1 拆分）
# ============================================================
do_transfer() {
    info "========== Phase 1: 传输项目文件 =========="
    run_ssh "mkdir -p $DEPLOY_DIR"

    if [[ "$DEPLOY_METHOD" == "rsync" ]]; then
        info "打包项目文件 ..."
        TARBALL="/tmp/maestro-deploy-$$.tar.gz"
        COPYFILE_DISABLE=1 tar czf "$TARBALL" \
            --disable-copyfile \
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
            --exclude='deploy' \
            .

        info "上传到 VPS ..."
        run_scp "$TARBALL" "${VPS_USER}@[${VPS_HOST}]:${DEPLOY_DIR}/_deploy.tar.gz"
        rm -f "$TARBALL"

        info "在 VPS 上解压 ..."
        run_ssh "cd $DEPLOY_DIR && tar xzf _deploy.tar.gz && rm -f _deploy.tar.gz && [[ '$MAESTRO_RUN_USER' != 'root' ]] && chown -R $MAESTRO_RUN_USER:$MAESTRO_RUN_USER $DEPLOY_DIR || true"
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
        # 设置目录所有权（与 rsync 模式一致）
        [[ "$MAESTRO_RUN_USER" != "root" ]] && run_ssh "chown -R $MAESTRO_RUN_USER:$MAESTRO_RUN_USER $DEPLOY_DIR"
        ok "git 部署完成"
    else
        die "不支持的部署方式: ${DEPLOY_METHOD}（仅支持 rsync | git）"
    fi
}

# ============================================================
# _set_run_user_password() — 通过管道设置运行用户密码（避免 shell 转义）
# ============================================================
_set_run_user_password() {
    if [[ "$MAESTRO_RUN_USER" == "root" || -z "$MAESTRO_RUN_PASSWORD" ]]; then
        return
    fi
    # 密码通过本地 printf 管道直传给远程 chpasswd，不经过远程 shell 展开
    # 这样即使密码含 ! $ ` ' " 等特殊字符也不会被转义
    printf '%s:%s\n' "$MAESTRO_RUN_USER" "$MAESTRO_RUN_PASSWORD" | run_ssh_pipe "chpasswd"
    ok "用户 $MAESTRO_RUN_USER 密码已设置"
}

# ============================================================
# _ensure_codex_file_store() — 确保服务器上 Codex config.toml 包含 file 存储模式
# 在 VPS 无浏览器环境中，Codex CLI 需要将 OAuth 凭据存储为文件而非 keyring。
# 参数:
#   $1 - remote_dir : 服务器端 Codex 配置目录（如 "/home/viber/.codex"）
# 返回:
#   0 - 成功（配置已存在或已写入）
#   1 - 失败（写入失败）
# 副作用:
#   - 创建 remote_dir 目录（如不存在）
#   - 创建或追加 config.toml 文件
#   - 设置文件权限 600，owner 为 MAESTRO_RUN_USER
# ============================================================
_ensure_codex_file_store() {
    local remote_dir="$1"
    local config_file="${remote_dir}/config.toml"

    # 1. 确保目录存在
    run_ssh "mkdir -p ${remote_dir}" 2>/dev/null || true

    # 2. 检查 config.toml 是否已包含 cli_auth_credentials_store 配置
    if run_ssh "grep -q '^cli_auth_credentials_store' ${config_file} 2>/dev/null"; then
        info "Codex config.toml 已包含 file 存储模式配置，跳过"
        return 0
    fi

    # 3. 追加配置（文件不存在时自动创建）
    info "配置 Codex CLI file 存储模式 ..."
    if ! run_ssh "echo 'cli_auth_credentials_store = \"file\"' >> ${config_file}" 2>/dev/null; then
        warn "Codex config.toml 写入失败"
        return 1
    fi

    # 4. 设置权限和所有者
    run_ssh "chmod 600 ${config_file}" 2>/dev/null || true
    run_ssh "chmod 700 ${remote_dir}" 2>/dev/null || true
    if [[ "$MAESTRO_RUN_USER" != "$VPS_USER" ]]; then
        run_ssh "chown ${MAESTRO_RUN_USER}:${MAESTRO_RUN_USER} ${config_file}" 2>/dev/null || true
        run_ssh "chown ${MAESTRO_RUN_USER}:${MAESTRO_RUN_USER} ${remote_dir}" 2>/dev/null || true
    fi

    ok "Codex CLI file 存储模式已配置"
    return 0
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

    # ---- 构造远程变量注入段（使用 _qv 安全转义，防止值含特殊字符时断裂） ----
    VARS_SECTION="
DEPLOY_DIR=$(_qv "$DEPLOY_DIR")
VPS_USER=$(_qv "$VPS_USER")
ANTHROPIC_API_KEY=$(_qv "$ANTHROPIC_API_KEY")
MANAGER_PROVIDER=$(_qv "$MANAGER_PROVIDER")
MANAGER_MODEL=$(_qv "$MANAGER_MODEL")
MANAGER_API_KEY=$(_qv "$MANAGER_API_KEY")
MANAGER_BASE_URL=$(_qv "$MANAGER_BASE_URL")
TELEGRAM_BOT_TOKEN=$(_qv "$TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID=$(_qv "$TELEGRAM_CHAT_ID")
SETUP_SYSTEMD=$(_qv "$SETUP_SYSTEMD")
MAESTRO_RUN_USER=$(_qv "$MAESTRO_RUN_USER")
PREFER_IPV4=$(_qv "$PREFER_IPV4")
CODING_TOOLS=$(_qv "$CODING_TOOLS")
DEFAULT_CODING_TOOL=$(_qv "$DEFAULT_CODING_TOOL")
"

    # ---- 构造远程安装脚本 ----
    REMOTE_SCRIPT_TMP=$(mktemp)
    cat > "$REMOTE_SCRIPT_TMP" << 'REMOTE_EOF'
set -euo pipefail

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[远程]${NC} $*"; }
ok()    { echo -e "${GREEN}[远程 OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[远程 WARN]${NC} $*"; }

# YAML 字符串转义（转义 \ 和 " 以安全嵌入双引号值）
_yaml_str() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
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

# ---- 创建运行用户（非 root，Claude Code 安全要求） ----
if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
    if ! id "$MAESTRO_RUN_USER" &>/dev/null; then
        info "创建运行用户: $MAESTRO_RUN_USER ..."
        $SUDO useradd -m -s /bin/bash "$MAESTRO_RUN_USER"
        ok "用户 $MAESTRO_RUN_USER 已创建（密码稍后设置）"
    else
        ok "用户 $MAESTRO_RUN_USER 已存在"
    fi
    RUN_HOME=$(eval echo "~$MAESTRO_RUN_USER")

    # 确保 SSH 密码认证开启（部分云镜像默认关闭）
    SSHD_CONF="/etc/ssh/sshd_config.d/60-cloudimg-settings.conf"
    if [[ -f "$SSHD_CONF" ]] && grep -q "PasswordAuthentication no" "$SSHD_CONF"; then
        echo "PasswordAuthentication yes" > "$SSHD_CONF"
        systemctl reload ssh 2>/dev/null || systemctl reload sshd 2>/dev/null || true
        ok "SSH 密码认证已开启"
    fi
else
    RUN_HOME="$HOME"
fi

# ---- 记录部署前环境快照 ----
STATE_FILE="$DEPLOY_DIR/.pre-deploy-state"
if [[ ! -f "$STATE_FILE" ]]; then
    info "记录部署前环境快照 ..."
    {
        echo "# 部署前环境快照（deploy.sh 自动生成）"
        echo "# 清理时只删除由 deploy.sh 安装的组件"
        command -v node &>/dev/null && echo "HAD_NODEJS=true" || echo "HAD_NODEJS=false"
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

# ---- 系统级 IPv4 优先（gai.conf） ----
if [[ "$PREFER_IPV4" == "true" ]]; then
    GAI_CONF="/etc/gai.conf"
    GAI_LINE="precedence ::ffff:0:0/96  100"
    GAI_MARKER="# maestro: prefer IPv4"
    if grep -qF "$GAI_MARKER" "$GAI_CONF" 2>/dev/null; then
        ok "gai.conf IPv4 优先已配置（跳过）"
    else
        info "配置系统级 IPv4 优先（/etc/gai.conf）..."
        {
            echo ""
            echo "$GAI_MARKER"
            echo "$GAI_LINE"
        } >> "$GAI_CONF"
        ok "gai.conf 已配置: DNS 解析优先 IPv4（不禁用 IPv6）"
    fi
fi

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

# ---- 编码工具安装（非 root 用户走用户级 npm prefix） ----
NPM_PREFIX="$RUN_HOME/.npm-global"
NPM_BIN="$NPM_PREFIX/bin"

_npm_install_tool() {
    local pkg="$1"
    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        if command -v runuser &>/dev/null; then
            runuser -u "$MAESTRO_RUN_USER" -- npm install -g --prefix "$NPM_PREFIX" "$pkg"
        else
            su -s /bin/sh "$MAESTRO_RUN_USER" <<SU_EOF
npm install -g --prefix '$NPM_PREFIX' '$pkg'
SU_EOF
        fi
    else
        npm install -g "$pkg"
    fi
}

# 非 root 时创建 npm prefix 目录
if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
    mkdir -p "$NPM_PREFIX"
    chown "$MAESTRO_RUN_USER:$MAESTRO_RUN_USER" "$NPM_PREFIX"
fi

IFS=',' read -ra TOOL_LIST <<< "$CODING_TOOLS"
for tool in "${TOOL_LIST[@]}"; do
    tool=$(echo "$tool" | xargs)
    case "$tool" in
        claude)
            if [[ -x "$NPM_BIN/claude" ]] || command -v claude &>/dev/null; then
                ok "Claude Code 已安装"
            else
                info "安装 Claude Code ..."
                _npm_install_tool "@anthropic-ai/claude-code"
                ok "Claude Code 安装完成"
            fi
            ;;
        codex)
            if [[ -x "$NPM_BIN/codex" ]] || command -v codex &>/dev/null; then
                ok "Codex CLI 已安装"
            else
                info "安装 Codex CLI ..."
                _npm_install_tool "@openai/codex"
                ok "Codex CLI 安装完成"
            fi
            ;;
        *) warn "未知编码工具: ${tool}，跳过" ;;
    esac
done

# ---- Python venv + pip install ----
info "创建 Python 虚拟环境 ..."
cd "$DEPLOY_DIR"
$PYTHON -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -e . -q
ok "Python 环境配置完成"

# ---- 设置目录所有权 ----
if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
    info "设置目录权限: $MAESTRO_RUN_USER ..."
    chown -R "$MAESTRO_RUN_USER:$MAESTRO_RUN_USER" "$DEPLOY_DIR"
    ok "目录权限已设置"
fi

# ---- 生成 config.yaml ----
info "生成 config.yaml ..."
CONFIG_FILE="$DEPLOY_DIR/config.yaml"

TG_ENABLED="false"
[[ -n "$TELEGRAM_BOT_TOKEN" ]] && TG_ENABLED="true"

{
    echo "# 由 deploy.sh 自动生成"
    echo "manager:"
    echo "  provider: $MANAGER_PROVIDER"
    echo "  model: $MANAGER_MODEL"
    echo "  api_key: \"$(_yaml_str "$MANAGER_API_KEY")\""
} > "$CONFIG_FILE"

if [[ -n "$MANAGER_BASE_URL" ]]; then
    echo "  base_url: \"$(_yaml_str "$MANAGER_BASE_URL")\"" >> "$CONFIG_FILE"
fi

cat >> "$CONFIG_FILE" << CFGEOF
  max_turns: 30
  max_budget_usd: 5.0
  request_timeout: 60
  retry_count: 3

CFGEOF

# 动态生成 coding_tools 段
echo "coding_tools:" >> "$CONFIG_FILE"
echo "  active_tool: $DEFAULT_CODING_TOOL" >> "$CONFIG_FILE"
echo "  presets:" >> "$CONFIG_FILE"
IFS=',' read -ra TOOL_LIST <<< "$CODING_TOOLS"
for tool in "${TOOL_LIST[@]}"; do
    tool=$(echo "$tool" | xargs)
    case "$tool" in
        claude)
            cat >> "$CONFIG_FILE" << 'PRESET_EOF'
    claude:
      type: claude
      command: claude
      auto_approve: true
      timeout: 600
PRESET_EOF
            ;;
        codex)
            cat >> "$CONFIG_FILE" << 'PRESET_EOF'
    codex:
      type: codex
      command: codex
      auto_approve: true
      timeout: 600
PRESET_EOF
            ;;
    esac
done

{
    echo ""
    echo "context:"
    echo "  max_recent_turns: 5"
    echo "  max_result_chars: 3000"
    echo ""
    echo "safety:"
    echo "  max_consecutive_similar: 3"
    echo "  max_parallel_tasks: 3"
    echo ""
    echo "telegram:"
    echo "  enabled: $TG_ENABLED"
    echo "  bot_token: \"$(_yaml_str "$TELEGRAM_BOT_TOKEN")\""
    echo "  chat_id: \"$(_yaml_str "$TELEGRAM_CHAT_ID")\""
    echo "  ask_user_timeout: 3600"
    echo ""
    echo "logging:"
    echo "  dir: ~/.maestro/logs"
    echo "  level: INFO"
    echo "  max_days: 30"
} >> "$CONFIG_FILE"
chmod 600 "$CONFIG_FILE"
[[ "$MAESTRO_RUN_USER" != "root" ]] && chown "$MAESTRO_RUN_USER:$MAESTRO_RUN_USER" "$CONFIG_FILE"
ok "config.yaml 已生成"

# ---- 环境变量 ----
info "配置环境变量 ..."

DOT_ENV="$DEPLOY_DIR/.env"
{
    echo "HOME=$RUN_HOME"
    echo "PATH=$RUN_HOME/.npm-global/bin:$RUN_HOME/.local/bin:$DEPLOY_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
        echo "ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
    fi
} > "$DOT_ENV"
chmod 600 "$DOT_ENV"
[[ "$MAESTRO_RUN_USER" != "root" ]] && chown "$MAESTRO_RUN_USER:$MAESTRO_RUN_USER" "$DOT_ENV"

BASHRC="$RUN_HOME/.bashrc"
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
    echo "export PATH=\"\$HOME/.npm-global/bin:\$HOME/.local/bin:$DEPLOY_DIR/.venv/bin:\$PATH\""
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
User=$MAESTRO_RUN_USER
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

    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
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

    # ---- 设置运行用户密码（本地管道直传，避免 shell 转义） ----
    _set_run_user_password

    ok "远程安装全部完成"
}

# ============================================================
# do_update_config() — 远程更新 config.yaml（从 deploy.env 重新生成）
# ============================================================
do_update_config() {
    info "========== 更新远程 config.yaml =========="

    # 校验 API Key
    if [[ "${MANAGER_PROVIDER:-}" != "ollama" && -z "${MANAGER_API_KEY:-}" ]]; then
        die "更新配置需要设置 MANAGER_API_KEY（Ollama 除外）"
    fi

    # 构造 config.yaml 内容
    local TG_ENABLED="false"
    [[ -n "$TELEGRAM_BOT_TOKEN" ]] && TG_ENABLED="true"

    local CONFIG_CONTENT
    CONFIG_CONTENT="# 由 deploy.sh 自动生成
manager:
  provider: $MANAGER_PROVIDER
  model: $MANAGER_MODEL
  api_key: \"$(_yaml_str "$MANAGER_API_KEY")\""

    if [[ -n "$MANAGER_BASE_URL" ]]; then
        CONFIG_CONTENT="$CONFIG_CONTENT
  base_url: \"$(_yaml_str "$MANAGER_BASE_URL")\""
    fi

    # 动态生成 coding_tools 段
    local CODING_TOOLS_SECTION
    CODING_TOOLS_SECTION="coding_tools:
  active_tool: $DEFAULT_CODING_TOOL
  presets:"
    IFS=',' read -ra TOOL_LIST <<< "$CODING_TOOLS"
    for tool in "${TOOL_LIST[@]}"; do
        tool=$(echo "$tool" | xargs)
        case "$tool" in
            claude)
                CODING_TOOLS_SECTION="$CODING_TOOLS_SECTION
    claude:
      type: claude
      command: claude
      auto_approve: true
      timeout: 600"
                ;;
            codex)
                CODING_TOOLS_SECTION="$CODING_TOOLS_SECTION
    codex:
      type: codex
      command: codex
      auto_approve: true
      timeout: 600"
                ;;
        esac
    done

    CONFIG_CONTENT="$CONFIG_CONTENT
  max_turns: 30
  max_budget_usd: 5.0
  request_timeout: 60
  retry_count: 3

$CODING_TOOLS_SECTION

context:
  max_recent_turns: 5
  max_result_chars: 3000

safety:
  max_consecutive_similar: 3
  max_parallel_tasks: 3

telegram:
  enabled: $TG_ENABLED
  bot_token: \"$(_yaml_str "$TELEGRAM_BOT_TOKEN")\"
  chat_id: \"$(_yaml_str "$TELEGRAM_CHAT_ID")\"
  ask_user_timeout: 3600

logging:
  dir: ~/.maestro/logs
  level: INFO
  max_days: 30"

    # 获取运行用户的 HOME
    local RUN_HOME
    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        RUN_HOME=$(run_ssh "eval echo ~$MAESTRO_RUN_USER")
    else
        RUN_HOME=$(run_ssh "echo \$HOME")
    fi

    # 写入远程 config.yaml
    echo "$CONFIG_CONTENT" | run_ssh_pipe "cat > $DEPLOY_DIR/config.yaml && chmod 600 $DEPLOY_DIR/config.yaml && [[ '$MAESTRO_RUN_USER' != 'root' ]] && chown $MAESTRO_RUN_USER:$MAESTRO_RUN_USER $DEPLOY_DIR/config.yaml || true"

    # 同步更新 .env 文件（ANTHROPIC_API_KEY 等环境变量）
    local ENV_CONTENT="HOME=$RUN_HOME
PATH=$RUN_HOME/.npm-global/bin:$RUN_HOME/.local/bin:$DEPLOY_DIR/.venv/bin:/usr/local/bin:/usr/bin:/bin"
    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
        ENV_CONTENT="$ENV_CONTENT
ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY"
    fi
    echo "$ENV_CONTENT" | run_ssh_pipe "cat > $DEPLOY_DIR/.env && chmod 600 $DEPLOY_DIR/.env && [[ '$MAESTRO_RUN_USER' != 'root' ]] && chown $MAESTRO_RUN_USER:$MAESTRO_RUN_USER $DEPLOY_DIR/.env || true"

    # 同步更新 .bashrc PATH（确保 update 后交互 shell 也能找到编码工具）
    local BASHRC_CONTENT="# >>> maestro >>>"
    if [[ -n "$ANTHROPIC_API_KEY" ]]; then
        BASHRC_CONTENT="$BASHRC_CONTENT
export ANTHROPIC_API_KEY=\"$ANTHROPIC_API_KEY\""
    fi
    BASHRC_CONTENT="$BASHRC_CONTENT
export PATH=\"\$HOME/.npm-global/bin:\$HOME/.local/bin:$DEPLOY_DIR/.venv/bin:\$PATH\"
# <<< maestro <<<"
    echo "$BASHRC_CONTENT" | run_ssh_pipe "BASHRC='$RUN_HOME/.bashrc' && sed -i '/# >>> maestro >>>/,/# <<< maestro <<</d' \"\$BASHRC\" && cat >> \"\$BASHRC\""

    ok "config.yaml、.env 和 .bashrc 已更新"
}

# ============================================================
# do_remote_quick_update() — 轻量远程更新（新增）
# ============================================================
do_remote_quick_update() {
    info "========== 远程更新 Python 包 =========="

    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        run_ssh "su - $MAESTRO_RUN_USER -c 'cd $DEPLOY_DIR && source .venv/bin/activate && pip install -e . -q && echo \"[远程 OK] pip install 完成\"'"
    else
        run_ssh "cd $DEPLOY_DIR && source .venv/bin/activate && pip install -e . -q && echo '[远程 OK] pip install 完成'"
    fi
    ok "Python 包更新完成"

    # 更新 systemd 服务文件（确保 User 与当前配置一致）
    DAEMON_ENABLED=$(run_ssh "systemctl is-enabled maestro-daemon 2>/dev/null" || true)
    if [[ "$DAEMON_ENABLED" == "enabled" ]]; then
        info "更新并重启 maestro-daemon 服务 ..."
        # 重新生成 service 文件（确保 User 正确）
        local SVC_CONTENT="[Unit]
Description=Maestro Telegram Daemon
After=network.target

[Service]
Type=simple
User=${MAESTRO_RUN_USER}
WorkingDirectory=${DEPLOY_DIR}
EnvironmentFile=${DEPLOY_DIR}/.env
ExecStart=${DEPLOY_DIR}/.venv/bin/python -m maestro.telegram_bot --config ${DEPLOY_DIR}/config.yaml
Restart=on-failure
RestartSec=30
StartLimitBurst=5

[Install]
WantedBy=multi-user.target"
        echo "$SVC_CONTENT" | run_ssh_pipe "cat > /etc/systemd/system/maestro-daemon.service && systemctl daemon-reload && systemctl restart maestro-daemon"
        sleep 2
        DAEMON_STATUS=$(run_ssh "systemctl is-active maestro-daemon 2>/dev/null" || true)
        if [[ "$DAEMON_STATUS" == "active" ]]; then
            ok "maestro-daemon 已重启（User=${MAESTRO_RUN_USER}）"
        else
            warn "maestro-daemon 重启异常，请检查: systemctl status maestro-daemon"
        fi
    else
        info "maestro-daemon 未启用，跳过重启"
    fi
}

# ============================================================
# do_tool_auth() — 编码工具认证引导（支持 claude / codex）
# 安装后统一引导用户手动登录，不接管认证过程
# ============================================================
do_tool_auth() {
    # 获取运行用户的 HOME
    local RUN_HOME
    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        RUN_HOME=$(run_ssh "eval echo ~$MAESTRO_RUN_USER")
    else
        RUN_HOME=$(run_ssh "echo \$HOME")
    fi

    IFS=',' read -ra TOOL_LIST <<< "$CODING_TOOLS"
    local PENDING=()  # 收集需要手动登录的工具

    for tool in "${TOOL_LIST[@]}"; do
        tool=$(echo "$tool" | xargs)
        case "$tool" in
            claude)
                if [[ -n "$ANTHROPIC_API_KEY" ]]; then
                    ok "Claude Code: API Key 模式，跳过登录"
                    continue
                fi
                PENDING+=("Claude Code|claude login|$RUN_HOME/.claude|claude")
                ;;
            codex)
                # 确保 config.toml 包含 file 存储模式（VPS 无浏览器环境必需）
                _ensure_codex_file_store "$RUN_HOME/.codex" || warn "Codex file 存储模式配置失败"
                PENDING+=("Codex CLI|codex login --device-auth|$RUN_HOME/.codex|codex")
                ;;
            *) continue ;;
        esac
    done

    # 如有需要认证的工具，一次性提示用户手动登录
    local all_authed=true
    if [[ ${#PENDING[@]} -gt 0 ]]; then
        echo ""
        echo -e "${YELLOW}===== 以下编码工具需要登录认证 =====${NC}"
        echo ""
        echo "  请打开另一个终端窗口，执行："
        echo -e "    ${GREEN}ssh ${VPS_SSH_KEY:+-i $VPS_SSH_KEY }-p $VPS_PORT ${VPS_USER}@${VPS_HOST}${NC}"
        if [[ "$MAESTRO_RUN_USER" != "$VPS_USER" ]]; then
            echo -e "    ${GREEN}su - $MAESTRO_RUN_USER${NC}"
        fi
        for entry in "${PENDING[@]}"; do
            IFS='|' read -r n c d t <<< "$entry"
            echo -e "    ${GREEN}${c}${NC}    # ${n}"
        done
        echo ""
        echo -e "${YELLOW}  全部完成后按 Enter 继续 ...${NC}"
        read -r < /dev/tty

        # 逐个验证认证结果
        for entry in "${PENDING[@]}"; do
            IFS='|' read -r n c d t <<< "$entry"
            local auth_file
            case "$t" in
                claude) auth_file="${d}/.credentials.json" ;;
                codex)  auth_file="${d}/auth.json" ;;
                *)      auth_file="" ;;
            esac
            if [[ -n "$auth_file" ]] && run_ssh "test -s \"${auth_file}\"" 2>/dev/null; then
                ok "$n 认证成功"
            else
                warn "$n 可能未完成认证，请稍后手动执行: $c"
                all_authed=false
            fi
        done
    fi

    # 仅当所有编码工具认证完成后才启动 daemon，避免半可用状态
    if [[ -n "$TELEGRAM_BOT_TOKEN" && "$SETUP_SYSTEMD" == "true" ]]; then
        if [[ "$all_authed" == "true" ]]; then
            DAEMON_STATUS=$(run_ssh "systemctl is-active maestro-daemon 2>/dev/null" || true)
            if [[ "$DAEMON_STATUS" != "active" ]]; then
                info "启动 Telegram Daemon ..."
                run_ssh "systemctl restart maestro-daemon" 2>/dev/null || true
                sleep 2
                DAEMON_STATUS=$(run_ssh "systemctl is-active maestro-daemon 2>/dev/null" || true)
            fi
            if [[ "$DAEMON_STATUS" == "active" ]]; then
                ok "Telegram Daemon 运行中"
            else
                warn "Daemon 启动异常，请检查: systemctl status maestro-daemon"
            fi
        else
            warn "部分编码工具未完成认证，Telegram Daemon 暂不启动"
            info "完成认证后可执行: systemctl restart maestro-daemon"
        fi
    fi
}

# ============================================================
# do_init() — 首次部署（组合函数）
# ============================================================
do_init() {
    info "编码工具: ${CODING_TOOLS}（默认激活: ${DEFAULT_CODING_TOOL}）"

    do_transfer
    do_remote_full_install

    ok "========== 远程安装完成! =========="

    do_tool_auth
    _print_summary "init"
}

# ============================================================
# _print_summary() — 部署完成后输出汇总信息
# ============================================================
_print_summary() {
    local mode="${1:-init}"

    # 获取 daemon 状态
    local daemon_status
    daemon_status=$(run_ssh "systemctl is-active maestro-daemon 2>/dev/null || true")
    [[ -z "$daemon_status" ]] && daemon_status="未安装"

    # 获取编码工具认证状态（遍历所有工具）
    local run_home
    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        run_home=$(run_ssh "eval echo ~$MAESTRO_RUN_USER" 2>/dev/null)
    else
        run_home=$(run_ssh "echo \$HOME" 2>/dev/null)
    fi

    IFS=',' read -ra TOOL_LIST <<< "$CODING_TOOLS"
    local tool_status_parts=()
    local any_unauthed=false
    for tool in "${TOOL_LIST[@]}"; do
        tool=$(echo "$tool" | xargs)
        case "$tool" in
            claude)
                if [[ -n "${ANTHROPIC_API_KEY:-}" ]]; then
                    tool_status_parts+=("$tool (API Key)")
                    continue
                fi
                if run_ssh "test -s ${run_home}/.claude/.credentials.json" 2>/dev/null; then
                    tool_status_parts+=("$tool (已认证)")
                else
                    tool_status_parts+=("$tool (未认证)")
                    any_unauthed=true
                fi
                ;;
            codex)
                if run_ssh "test -s ${run_home}/.codex/auth.json" 2>/dev/null; then
                    tool_status_parts+=("$tool (已认证)")
                else
                    tool_status_parts+=("$tool (未认证)")
                    any_unauthed=true
                fi
                ;;
            *) continue ;;
        esac
    done
    local tool_status_str
    tool_status_str=$(IFS=', '; echo "${tool_status_parts[*]}")

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    if [[ "$mode" == "init" ]]; then
        echo -e "${GREEN}║          部署完成！以下是你的环境信息                ║${NC}"
    else
        echo -e "${GREEN}║          更新完成！以下是你的环境信息                ║${NC}"
    fi
    echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${CYAN}VPS 连接${NC}"
    echo "    地址: ${VPS_HOST}:${VPS_PORT}"
    echo "    SSH 用户: ${VPS_USER}"
    echo ""
    echo -e "  ${CYAN}Maestro 运行用户${NC}"
    echo "    用户名: ${MAESTRO_RUN_USER}"
    if [[ -n "$MAESTRO_RUN_PASSWORD" ]]; then
        echo "    密码: ${MAESTRO_RUN_PASSWORD}"
    fi
    echo ""
    echo -e "  ${CYAN}服务状态${NC}"
    echo "    部署目录: ${DEPLOY_DIR}"
    echo "    Telegram Daemon: ${daemon_status}"
    echo "    编码工具: ${tool_status_str}"
    echo "    当前激活: ${DEFAULT_CODING_TOOL}"
    echo "    Manager: ${MANAGER_PROVIDER}/${MANAGER_MODEL}"
    echo ""
    echo -e "  ${CYAN}使用方式${NC}"
    echo ""
    echo "    方式 1: Telegram Bot 远程控制（推荐）"
    echo "      发送: /run <工作目录> <需求描述>"
    echo ""
    echo "    方式 2: SSH 到 VPS 手动运行"
    echo -e "      ${GREEN}ssh ${VPS_SSH_KEY:+-i $VPS_SSH_KEY }-p $VPS_PORT ${VPS_USER}@${VPS_HOST}${NC}"
    if [[ "$MAESTRO_RUN_USER" != "$VPS_USER" ]]; then
        echo -e "      ${GREEN}su - $MAESTRO_RUN_USER${NC}"
    fi
    echo -e "      ${GREEN}cd $DEPLOY_DIR && source .venv/bin/activate${NC}"
    echo -e "      ${GREEN}maestro run \"你的需求\"${NC}"

    if [[ "$any_unauthed" == "true" ]]; then
        echo ""
        echo -e "  ${YELLOW}⚠ 部分编码工具尚未认证，请 SSH 到 VPS 执行对应的 login 命令${NC}"
        echo -e "      ${GREEN}ssh ${VPS_SSH_KEY:+-i $VPS_SSH_KEY }-p $VPS_PORT ${VPS_USER}@${VPS_HOST}${NC}"
        if [[ "$MAESTRO_RUN_USER" != "$VPS_USER" ]]; then
            echo -e "      ${GREEN}su - $MAESTRO_RUN_USER${NC}"
        fi
    fi
    echo ""
}

# ============================================================
# do_update() — 业务逻辑更新（组合函数，新增）
# ============================================================
do_update() {
    # 注意: update 只管代码+包+配置，绝不安装编码工具或修改系统环境
    # 编码工具安装只在 init 时执行（do_remote_full_install）

    # 前置检查：远程 .venv 是否存在（先于用户创建，避免 die 时遗留孤立用户）
    if ! run_ssh "test -d $DEPLOY_DIR/.venv" 2>/dev/null; then
        die "远程环境未初始化（$DEPLOY_DIR/.venv 不存在），请先执行: deploy.sh init"
    fi

    # 前置检查：确保运行用户存在
    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        if ! run_ssh "id $MAESTRO_RUN_USER" 2>/dev/null; then
            info "创建运行用户: $MAESTRO_RUN_USER ..."
            run_ssh "useradd -m -s /bin/bash $MAESTRO_RUN_USER"
            _set_run_user_password
            ok "用户 $MAESTRO_RUN_USER 已创建"
        fi
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

    # 系统级 IPv4 优先（gai.conf，幂等）
    if [[ "$PREFER_IPV4" == "true" ]]; then
        run_ssh "
            GAI_CONF='/etc/gai.conf'
            GAI_MARKER='# maestro: prefer IPv4'
            if grep -qF \"\$GAI_MARKER\" \"\$GAI_CONF\" 2>/dev/null; then
                echo '[远程] gai.conf IPv4 优先已配置（跳过）'
            else
                echo '' >> \"\$GAI_CONF\"
                echo \"\$GAI_MARKER\" >> \"\$GAI_CONF\"
                echo 'precedence ::ffff:0:0/96  100' >> \"\$GAI_CONF\"
                echo '[远程 OK] gai.conf 已配置 IPv4 优先'
            fi
        "
    fi

    # 从 deploy.env 重新生成远程 config.yaml（确保 API Key 等配置同步）
    do_update_config

    do_remote_quick_update

    _print_summary "update"
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
        RUN_HOME=\$(eval echo ~${MAESTRO_RUN_USER} 2>/dev/null || echo \"\$HOME\")

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
        NPM_BIN=\"\$RUN_HOME/.npm-global/bin\"
        if [[ -x \"\$NPM_BIN/claude\" ]]; then
            echo -n 'Claude Code: '; \"\$NPM_BIN/claude\" --version 2>/dev/null || echo '已安装（版本未知）'
        elif command -v claude &>/dev/null; then
            echo -n 'Claude Code: '; claude --version 2>/dev/null || echo '已安装（版本未知）'
        else
            echo 'Claude Code: 未安装'
        fi
        if [[ -x \"\$NPM_BIN/codex\" ]]; then
            echo -n 'Codex CLI: '; \"\$NPM_BIN/codex\" --version 2>/dev/null || echo '已安装（版本未知）'
        elif command -v codex &>/dev/null; then
            echo -n 'Codex CLI: '; codex --version 2>/dev/null || echo '已安装（版本未知）'
        else
            echo 'Codex CLI: 未安装'
        fi

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
        echo '=== 编码工具认证 ==='
        IFS=',' read -ra _STATUS_TOOLS <<< \"${CODING_TOOLS}\"
        for _st in \"\${_STATUS_TOOLS[@]}\"; do
            _st=\$(echo \"\$_st\" | xargs)
            case \"\$_st\" in
                claude)
                    if [[ -n \"${ANTHROPIC_API_KEY}\" ]]; then
                        echo 'Claude Code: API Key 模式'
                    elif [[ -s \"\$RUN_HOME/.claude/.credentials.json\" ]]; then
                        echo 'Claude Code: 已认证'
                    else
                        echo 'Claude Code: 未认证'
                    fi
                    ;;
                codex)
                    if [[ -s \"\$RUN_HOME/.codex/auth.json\" ]]; then
                        echo 'Codex CLI: 已认证'
                    else
                        echo 'Codex CLI: 未认证'
                    fi
                    ;;
            esac
        done

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
        if [[ -d \"\$RUN_HOME/.maestro\" ]]; then
            task_count=\$(find \"\$RUN_HOME/.maestro\" -name 'state.json' 2>/dev/null | wc -l)
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
# do_clean() — 清理卸载
# 卸载时只处理"软件是否卸载"，不处理"认证目录是否删除"
# ============================================================
do_clean() {
    echo ""
    echo -e "${YELLOW}============================================================${NC}"
    echo -e "${YELLOW}  清理卸载 Maestro${NC}"
    echo -e "${YELLOW}  目标: ${VPS_USER}@${VPS_HOST}:${VPS_PORT}${NC}"
    echo -e "${YELLOW}  部署目录: ${DEPLOY_DIR}${NC}"
    echo -e "${YELLOW}============================================================${NC}"
    echo ""

    # 读取环境快照（如有）判断 Node.js 是否由部署脚本安装
    PRE_STATE=$(run_ssh "cat ${DEPLOY_DIR}/.pre-deploy-state 2>/dev/null" || true)
    HAD_NODEJS=true
    if [[ -n "$PRE_STATE" ]]; then
        while IFS='=' read -r key val; do
            case "$key" in
                HAD_NODEJS) [[ "$val" == "false" ]] && HAD_NODEJS="false" ;;
            esac
        done < <(echo "$PRE_STATE" | grep -E '^HAD_NODEJS=(true|false)$')
    fi

    echo "  将执行以下操作："
    echo "    1. 停止并移除 systemd 服务（maestro-daemon）"
    echo "    2. 删除部署目录（${DEPLOY_DIR}）"
    echo "    3. 清理 bashrc 中的 maestro 环境变量"
    echo "    4. 删除 Maestro 日志（~/.maestro）"
    [[ "$HAD_NODEJS" == "false" ]] && echo "    5. 卸载 Node.js（部署时安装）"
    echo ""
    echo "  以下内容保留："
    KEEP_LIST=""
    [[ "$HAD_NODEJS" == "true" ]] && KEEP_LIST="${KEEP_LIST}Node.js、"
    KEEP_LIST="${KEEP_LIST}Python（系统级）"
    echo "    - ${KEEP_LIST}"
    echo ""
    echo -e "${RED}  此操作不可恢复！${NC}"
    echo ""
    read -r -p "  确认执行清理？[y/N] " CONFIRM
    case "$CONFIRM" in
        [yY]|[yY][eE][sS]) ;;
        *)
            info "已取消"
            return
            ;;
    esac

    info "开始清理 ..."

    local RUN_HOME
    if [[ "$MAESTRO_RUN_USER" != "root" ]]; then
        RUN_HOME=$(run_ssh "eval echo ~$MAESTRO_RUN_USER")
    else
        RUN_HOME=$(run_ssh "echo \$HOME")
    fi

    # ---- 询问是否卸载编码工具软件 ----
    UNINSTALL_CLAUDE="false"
    UNINSTALL_CODEX="false"

    IFS=',' read -ra TOOL_LIST_CHECK <<< "$CODING_TOOLS"
    for tool in "${TOOL_LIST_CHECK[@]}"; do
        tool=$(echo "$tool" | xargs)
        case "$tool" in
            claude)
                echo ""
                read -r -p "  是否卸载 Claude Code？[y/N] " DEL_CLAUDE
                case "$DEL_CLAUDE" in
                    [yY]|[yY][eE][sS]) UNINSTALL_CLAUDE="true" ;;
                    *) UNINSTALL_CLAUDE="false" ;;
                esac
                ;;
            codex)
                echo ""
                read -r -p "  是否卸载 Codex CLI？[y/N] " DEL_CODEX
                case "$DEL_CODEX" in
                    [yY]|[yY][eE][sS]) UNINSTALL_CODEX="true" ;;
                    *) UNINSTALL_CODEX="false" ;;
                esac
                ;;
        esac
    done

    CLEAN_SCRIPT=$(cat << 'CLEAN_EOF'
set -euo pipefail

# 清理脚本必须以 root 执行（由 deploy.sh root SSH 保证）
if [[ "$(id -u)" -ne 0 ]]; then
    echo "[清理] 错误: 必须以 root 身份执行"
    exit 1
fi

# RUN_HOME 由管道注入（见脚本末尾变量块），无需在此解析

# 停止 systemd 服务
if systemctl is-enabled maestro-daemon &>/dev/null; then
    echo "[清理] 停止 maestro-daemon 服务 ..."
    systemctl stop maestro-daemon 2>/dev/null || true
    systemctl disable maestro-daemon 2>/dev/null || true
    rm -f /etc/systemd/system/maestro-daemon.service
    systemctl daemon-reload
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
BASHRC="$RUN_HOME/.bashrc"
if [[ -f "$BASHRC" ]] && grep -q '# >>> maestro >>>' "$BASHRC"; then
    sed -i '/# >>> maestro >>>/,/# <<< maestro <<</d' "$BASHRC"
    echo "[清理] bashrc 环境变量已清理"
else
    echo "[清理] bashrc 无 maestro 配置，跳过"
fi

# 清理 gai.conf 中 maestro 写入的 IPv4 优先配置
GAI_CONF="/etc/gai.conf"
GAI_MARKER="# maestro: prefer IPv4"
if [[ -f "$GAI_CONF" ]] && grep -qF "$GAI_MARKER" "$GAI_CONF"; then
    # 精确删除标记行 + 紧随其后的 precedence 行（不影响文件其他空行）
    sed -i "/$GAI_MARKER/{N;d;}" "$GAI_CONF"
    echo "[清理] gai.conf IPv4 优先配置已移除"
else
    echo "[清理] gai.conf 无 maestro 配置，跳过"
fi

# 清理日志和任务记录
if [[ -d "$RUN_HOME/.maestro" ]]; then
    rm -rf "$RUN_HOME/.maestro"
    echo "[清理] $RUN_HOME/.maestro 已删除"
fi

# 卸载 Claude Code（根据用户选择，只执行官方卸载命令，不删除 ~/.claude）
if [[ "$UNINSTALL_CLAUDE" == "true" ]]; then
    if command -v claude &>/dev/null; then
        npm uninstall -g @anthropic-ai/claude-code 2>/dev/null || true
        echo "[清理] Claude Code 已卸载"
    elif [[ -x "$RUN_HOME/.npm-global/bin/claude" ]]; then
        NPM_PREFIX="$RUN_HOME/.npm-global"
        if command -v runuser &>/dev/null; then
            runuser -u "$MAESTRO_RUN_USER" -- npm uninstall -g --prefix "$NPM_PREFIX" @anthropic-ai/claude-code 2>/dev/null || true
        else
            su -s /bin/sh "$MAESTRO_RUN_USER" -c "npm uninstall -g --prefix '$NPM_PREFIX' @anthropic-ai/claude-code" 2>/dev/null || true
        fi
        echo "[清理] Claude Code 已卸载"
    else
        echo "[清理] Claude Code 未安装，跳过"
    fi
else
    echo "[清理] Claude Code 已保留"
fi

# 卸载 Codex CLI（根据用户选择，只执行官方卸载命令，不删除 ~/.codex）
if [[ "$UNINSTALL_CODEX" == "true" ]]; then
    if command -v codex &>/dev/null; then
        npm uninstall -g @openai/codex 2>/dev/null || true
        echo "[清理] Codex CLI 已卸载"
    elif [[ -x "$RUN_HOME/.npm-global/bin/codex" ]]; then
        NPM_PREFIX="$RUN_HOME/.npm-global"
        if command -v runuser &>/dev/null; then
            runuser -u "$MAESTRO_RUN_USER" -- npm uninstall -g --prefix "$NPM_PREFIX" @openai/codex 2>/dev/null || true
        else
            su -s /bin/sh "$MAESTRO_RUN_USER" -c "npm uninstall -g --prefix '$NPM_PREFIX' @openai/codex" 2>/dev/null || true
        fi
        echo "[清理] Codex CLI 已卸载"
    else
        echo "[清理] Codex CLI 未安装，跳过"
    fi
else
    echo "[清理] Codex CLI 已保留"
fi

# Node.js 卸载（仅当部署时安装的才卸载，且已配置的编码工具没有被保留）
if [[ "$HAD_NODEJS" == "false" ]]; then
    # 检查 CODING_TOOLS 中是否有工具被保留（只看实际配置的工具）
    _any_tool_kept=false
    IFS=',' read -ra _CT <<< "$CODING_TOOLS"
    for _t in "${_CT[@]}"; do
        _t=$(echo "$_t" | xargs)
        if [[ "$_t" == "claude" && "$UNINSTALL_CLAUDE" == "false" ]]; then
            _any_tool_kept=true
        elif [[ "$_t" == "codex" && "$UNINSTALL_CODEX" == "false" ]]; then
            _any_tool_kept=true
        fi
    done
    if [[ "$_any_tool_kept" == "true" ]]; then
        echo "[清理] Node.js 保留（有编码工具被保留，Node.js 是其运行时依赖）"
    else
        apt-get remove -y -qq nodejs 2>/dev/null || true
        echo "[清理] Node.js 已卸载（部署时安装）"
    fi
else
    echo "[清理] Node.js 保留（部署前已存在）"
fi

echo ""
echo "[清理] 全部完成"
CLEAN_EOF
)

    echo "DEPLOY_DIR=$(_qv "$DEPLOY_DIR")
HAD_NODEJS=$(_qv "$HAD_NODEJS")
UNINSTALL_CLAUDE=$(_qv "$UNINSTALL_CLAUDE")
UNINSTALL_CODEX=$(_qv "$UNINSTALL_CODEX")
CODING_TOOLS=$(_qv "$CODING_TOOLS")
MAESTRO_RUN_USER=$(_qv "$MAESTRO_RUN_USER")
RUN_HOME=$(_qv "$RUN_HOME")
${CLEAN_SCRIPT}" | run_ssh_pipe bash

    echo ""
    ok "VPS 清理完成"
    echo ""
    echo "  已清理: systemd 服务、部署目录、环境变量、日志"

    # 工具卸载摘要（跟随 CODING_TOOLS 配置）
    TOOL_SUMMARY=""
    IFS=',' read -ra TOOL_LIST_SUMMARY <<< "$CODING_TOOLS"
    for tool in "${TOOL_LIST_SUMMARY[@]}"; do
        tool=$(echo "$tool" | xargs)
        case "$tool" in
            claude)
                [[ "$UNINSTALL_CLAUDE" == "true" ]] && TOOL_SUMMARY="${TOOL_SUMMARY}Claude Code（已卸载）、" || TOOL_SUMMARY="${TOOL_SUMMARY}Claude Code（已保留）、"
                ;;
            codex)
                [[ "$UNINSTALL_CODEX" == "true" ]] && TOOL_SUMMARY="${TOOL_SUMMARY}Codex CLI（已卸载）、" || TOOL_SUMMARY="${TOOL_SUMMARY}Codex CLI（已保留）、"
                ;;
        esac
    done
    # Node.js 摘要需反映实际结果（与远端卸载逻辑一致）
    if [[ "$HAD_NODEJS" == "false" ]]; then
        # 检查 CODING_TOOLS 中是否有工具被保留
        local _any_kept=false
        for tool in "${TOOL_LIST_SUMMARY[@]}"; do
            tool=$(echo "$tool" | xargs)
            case "$tool" in
                claude) [[ "$UNINSTALL_CLAUDE" == "false" ]] && _any_kept=true ;;
                codex)  [[ "$UNINSTALL_CODEX" == "false" ]]  && _any_kept=true ;;
            esac
        done
        if [[ "$_any_kept" == "true" ]]; then
            TOOL_SUMMARY="${TOOL_SUMMARY}Node.js（已保留，编码工具运行时依赖）、"
        else
            TOOL_SUMMARY="${TOOL_SUMMARY}Node.js（已卸载）、"
        fi
    else
        TOOL_SUMMARY="${TOOL_SUMMARY}Node.js（已保留）、"
    fi
    TOOL_SUMMARY="${TOOL_SUMMARY%、}"
    echo "  工具处理: ${TOOL_SUMMARY}"
    echo ""
    echo "  如需重新部署，再次运行此脚本选择「部署」即可。"
    echo ""
}

# ============================================================
# do_service() — 远程服务管理
# ============================================================
do_service() {
    local action="${1:-}"
    if [[ -z "$action" ]]; then
        echo ""
        echo "  a) 启动服务"
        echo "  b) 停止服务"
        echo "  c) 重启服务"
        echo "  0) 返回"
        echo ""
        read -r -p "  请选择 [a/b/c/0]: " SVC_CHOICE
        case "${SVC_CHOICE:-}" in
            a) action="start" ;;
            b) action="stop" ;;
            c) action="restart" ;;
            0|*) return ;;
        esac
    fi

    case "$action" in
        start)
            info "启动 Daemon 服务 ..."
            run_ssh "systemctl start maestro-daemon 2>&1; echo '状态:' \$(systemctl is-active maestro-daemon 2>/dev/null)"
            ok "启动命令已发送"
            ;;
        stop)
            info "停止 Daemon 服务 ..."
            run_ssh "systemctl stop maestro-daemon 2>&1; echo '状态:' \$(systemctl is-active maestro-daemon 2>/dev/null)"
            ok "停止命令已发送"
            ;;
        restart)
            info "重启 Daemon 服务 ..."
            run_ssh "systemctl restart maestro-daemon 2>&1; echo '状态:' \$(systemctl is-active maestro-daemon 2>/dev/null)"
            ok "重启命令已发送"
            ;;
    esac
}

# ============================================================
# 交互菜单（6 项）
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
    echo "  2) 业务逻辑更新（代码+包+配置）"
    echo "  3) 查看状态"
    echo "  4) 服务管理（启动/停止/重启）"
    echo "  5) 清理卸载"
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
    service)
        if [[ -z "$SUBCOMMAND_ARG" || ! "$SUBCOMMAND_ARG" =~ ^(start|stop|restart)$ ]]; then
            echo "用法: deploy.sh service <start|stop|restart>"
            exit 1
        fi
        do_service "$SUBCOMMAND_ARG"
        ;;
    "")
        # 无子命令 → 进入交互菜单
        while true; do
            show_menu
            read -r -p "  请选择 [0-5]: " MENU_CHOICE
            case "$MENU_CHOICE" in
                1) do_init ;;
                2) do_update ;;
                3) do_status ;;
                4) do_service ;;
                5) do_clean ;;
                0) echo ""; ok "再见！"; exit 0 ;;
                *) warn "无效选择: $MENU_CHOICE" ;;
            esac
            echo ""
            read -r -p "  按 Enter 返回菜单 ..."
        done
        ;;
esac
