# 系统设计：deploy-prompt-refactor

## 目录

1. [方案 1：分层部署脚本改造](#方案-1分层部署脚本改造)
2. [方案 3：Prompt 外置化](#方案-3prompt-外置化)
3. [影响范围分析](#影响范围分析)
4. [关键设计决策](#关键设计决策)

---

## 方案 1：分层部署脚本改造

### 1.1 当前结构分析

`deploy.sh` 当前 798 行，结构如下：

```
第 1-106 行    配置加载 + SSH 连接建立（所有功能共用）
第 107-521 行  do_deploy()  — 完整部署（Phase 1 文件传输 + Phase 2 远程安装）
第 522-619 行  do_status()  — 查看 VPS 状态
第 620-765 行  do_clean()   — 清理卸载
第 766-798 行  主菜单循环
```

`do_deploy()` 内部两个阶段：
- **Phase 1（第 122-168 行）**：文件传输（rsync 打包 tar 或 git clone）
- **Phase 2（第 170-441 行）**：远程安装（系统包、Python、Node.js、Claude Code、Zellij、venv、config.yaml、环境变量、systemd）

### 1.2 改造目标

将 `do_deploy()` 拆分为可复用的子函数，支持两种部署模式：

| 模式 | 触发方式 | 执行内容 |
|------|---------|---------|
| `init` | `deploy.sh init` 或菜单选项 1 | Phase 1 + Phase 2 完整流程 + Claude Code 认证引导 |
| `update` | `deploy.sh update` 或菜单选项 2 | Phase 1 + `pip install -e .` + systemd restart |

### 1.3 函数拆分设计

从 `do_deploy()` 中提取以下独立函数：

```bash
# ---- 已有函数（保持不变） ----
do_status()    # 查看状态
do_clean()     # 清理卸载

# ---- 从 do_deploy() 拆分出的新函数 ----
do_transfer()              # Phase 1：文件传输（rsync/git）
do_remote_full_install()   # Phase 2：完整远程安装（系统包→venv→config→systemd）
do_remote_quick_update()   # 轻量远程更新（仅 pip install -e . + systemd restart）
do_claude_auth()           # Claude Code 认证引导 + Daemon 启动

# ---- 组合函数 ----
do_init()      # 首次部署 = do_transfer + do_remote_full_install + do_claude_auth
do_update()    # 业务更新 = 前置检查 + do_transfer + do_remote_quick_update
```

#### 1.3.1 `do_transfer()` — 文件传输

从 `do_deploy()` 的 Phase 1（第 122-168 行）原样提取，不修改内部逻辑。

```bash
do_transfer() {
    info "========== Phase 1: 传输项目文件 =========="
    run_ssh "mkdir -p $DEPLOY_DIR"

    if [[ "$DEPLOY_METHOD" == "rsync" ]]; then
        # ... 现有 tar + scp + 解压逻辑（第 127-151 行），不变
    elif [[ "$DEPLOY_METHOD" == "git" ]]; then
        # ... 现有 git clone/pull 逻辑（第 153-165 行），不变
    else
        die "不支持的部署方式: $DEPLOY_METHOD（仅支持 rsync | git）"
    fi
}
```

#### 1.3.2 `do_remote_full_install()` — 完整远程安装

从 `do_deploy()` 的 Phase 2（第 170-441 行）原样提取。这是最大的一块代码，包含远程执行的 heredoc 脚本。不修改内部逻辑，仅将其包装为独立函数。

```bash
do_remote_full_install() {
    # 校验部署必填项（原第 112-114 行）
    if [[ "${MANAGER_PROVIDER:-}" != "ollama" && -z "${MANAGER_API_KEY:-}" ]]; then
        die "部署需要设置 MANAGER_API_KEY（Ollama 除外）"
    fi

    info "========== Phase 2: 远程安装 =========="

    # ---- 构造远程变量注入段（原第 173-184 行） ----
    # 这些变量通过管道注入到远程 bash 脚本中
    # 依赖的外部变量全部来自脚本顶部的 deploy.env source，无需参数传入
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

    # ---- 构造远程安装脚本（原第 186-442 行） ----
    # 使用 heredoc 写入临时文件，通过 SSH 管道执行
    REMOTE_SCRIPT_TMP=$(mktemp)
    cat > "$REMOTE_SCRIPT_TMP" << 'REMOTE_EOF'
    # ... 原有的远程安装脚本内容（系统包→Python→Node.js→Claude Code→
    #     Zellij→venv→config.yaml→环境变量→systemd），共约 255 行，不变
REMOTE_EOF

    # ---- 管道执行（原第 444 行） ----
    { echo "$VARS_SECTION"; cat "$REMOTE_SCRIPT_TMP"; } | run_ssh_pipe bash
    rm -f "$REMOTE_SCRIPT_TMP"

    ok "远程安装全部完成"
}
```

**封装说明：** `do_remote_full_install()` 内部完整包含 VARS_SECTION 构造、临时脚本文件创建、heredoc 远程脚本和管道执行。所有依赖的配置变量（`DEPLOY_DIR`、`MANAGER_*`、`TELEGRAM_*` 等）来自脚本顶部 `source "$ENV_FILE"` 的全局变量，函数不需要接收参数。这与原 `do_deploy()` 的行为一致。

#### 1.3.3 `do_remote_quick_update()` — 轻量远程更新（新增）

这是新增的核心函数，仅执行 `pip install -e .` 和可选的 systemd restart。

```bash
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
```

#### 1.3.4 `do_claude_auth()` — Claude Code 认证引导

从 `do_deploy()` 的第 449-510 行提取。

```bash
do_claude_auth() {
    if [[ -z "$ANTHROPIC_API_KEY" ]]; then
        # ... 现有的 ~/.claude 检测 + 交互式认证引导 + Daemon 启动逻辑（第 450-510 行），不变
    fi
}
```

#### 1.3.5 `do_init()` — 首次部署（组合函数）

```bash
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
```

#### 1.3.6 `do_update()` — 业务逻辑更新（组合函数，新增）

```bash
do_update() {
    # 前置检查：远程 .venv 是否存在
    if ! run_ssh "test -d $DEPLOY_DIR/.venv" 2>/dev/null; then
        die "远程环境未初始化（$DEPLOY_DIR/.venv 不存在），请先执行: deploy.sh init"
    fi

    # 备份远端 prompts/（如存在用户自定义内容）
    # deploy.sh update 的 tar 解压会全量覆盖，需要保护用户修改
    run_ssh "
        if [[ -d $DEPLOY_DIR/prompts ]]; then
            cp -r $DEPLOY_DIR/prompts /tmp/_maestro_prompts_bak
        fi
    " 2>/dev/null || true

    do_transfer

    # 恢复远端 prompts/（用备份覆盖传输过来的默认版本）
    run_ssh "
        if [[ -d /tmp/_maestro_prompts_bak ]]; then
            cp -r /tmp/_maestro_prompts_bak/* $DEPLOY_DIR/prompts/ 2>/dev/null || true
            rm -rf /tmp/_maestro_prompts_bak
        fi
    " 2>/dev/null || true

    do_remote_quick_update

    echo ""
    ok "========== 业务逻辑更新完成! =========="
    echo ""
}
```

**prompts 保护策略说明**：`do_update()` 在文件传输前备份远端 `prompts/` 目录，传输后恢复。这样用户在 VPS 上直接修改 `prompts/system.md` 的内容不会被覆盖。如果本地仓库新增了 prompt 文件（如 `prompts/new.md`），仍会正常传输到 VPS。`do_init()` 不做此保护（首次部署应使用仓库默认版本）。

### 1.4 CLI 参数模式设计

在主菜单循环之前（当前第 785 行位置），插入参数解析逻辑。整体入口结构如下：

```bash
# ============================================================
# 入口：参数模式 vs 交互菜单
# ============================================================

# 注意：help 已在脚本顶部（1.5 节）拦截退出，此处不再处理
# SUBCOMMAND 变量由顶部参数解析设置

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
```

注意：入口 case 现在基于 `$SUBCOMMAND` 变量（由 1.5 节的顶部解析设置），而非 `$1`。未知命令在顶部解析的 `*` 分支中已处理（`SUBCOMMAND=""` 进菜单），无需重复。如果需要对未知子命令报错，应在顶部解析中增加一个 `*` 分支：

```bash
    *)
        # 非 env 文件也非已知子命令 → 报错
        if [[ -f "${1:-}" ]]; then
            SUBCOMMAND=""
            ENV_FILE="$1"
        else
            err "未知命令: $1"
            echo "用法: deploy.sh [init|update|help] [deploy.env 路径]"
            exit 1
        fi
        ;;
```

### 1.5 ENV_FILE 参数兼容性处理

当前第 26 行 `ENV_FILE="${1:-deploy.env}"` 将 `$1` 作为配置文件路径。改造后需要兼容子命令：

```bash
# 改造前：
# ENV_FILE="${1:-deploy.env}"

# 改造后：
# 如果第一个参数是子命令（init/update/help），则 ENV_FILE 取 $2；否则取 $1
# 注意：help 必须在此处拦截并退出，避免触发后续的 SSH 连接建立
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
        ENV_FILE="${1:-deploy.env}"
        ;;
esac
```

这段代码放在脚本最前面（当前第 26 行位置之前），替换原有的 `ENV_FILE` 赋值。**关键点：`help` 在 SSH 连接建立之前就退出，不需要读取 deploy.env 也不需要连接 VPS。**

### 1.6 交互菜单改造

```bash
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
```

### 1.7 整体代码组织（改造后）

```
deploy.sh 结构（改造后）：
├── 第 1-9 行     shebang + set 选项
├── 第 10-21 行   颜色输出工具函数
├── 第 22-45 行   SUBCOMMAND 解析 + help 拦截 + ENV_FILE 确定（改造，help 在此直接退出）
├── 第 46-106 行  配置加载 + SSH 连接建立（不变，help 已退出不会到达此处）
├── do_transfer()            ← 从 do_deploy() Phase 1 拆分
├── do_remote_full_install() ← 从 do_deploy() Phase 2 拆分（含 VARS_SECTION 构造和 heredoc 管道执行）
├── do_remote_quick_update() ← 新增
├── do_claude_auth()         ← 从 do_deploy() 尾部拆分
├── do_init()                ← 新增（组合 transfer + full_install + auth）
├── do_update()              ← 新增（前置检查 + prompts 备份 + transfer + 恢复 + quick_update）
├── do_status()              ← 不变
├── do_clean()               ← 不变
├── show_menu()              ← 改造（4 个菜单项）
└── 入口 case "$SUBCOMMAND"  ← 基于顶部解析的 SUBCOMMAND 变量路由
```

原有的 `do_deploy()` 函数将被删除，其代码完全拆分到 `do_transfer()`、`do_remote_full_install()`、`do_claude_auth()` 三个函数中。

---

## 方案 3：Prompt 外置化

### 2.1 当前 Prompt 硬编码分析

`manager_agent.py` 中有 3 处硬编码的 system prompt：

| 位置 | 变量/字符串 | 用途 | 行号 |
|------|-----------|------|------|
| `DEFAULT_SYSTEM_PROMPT` | 模块级常量 | Manager 主决策 prompt（38 行文本） | 47-84 |
| `standalone_chat` 方法内 | 字面字符串 | 任务问答 prompt | 343-346 |
| `free_chat` 方法内 | 字面字符串 | 自由聊天 prompt | 382 |

加载优先级（当前）：`config.yaml` 中的 `system_prompt` > `DEFAULT_SYSTEM_PROMPT` 常量。

### 2.2 Prompt 文件目录结构

```
prompts/
├── system.md          # Manager 主决策 system prompt
├── chat.md            # standalone_chat 的 system prompt（任务问答）
└── free_chat.md       # free_chat 的 system prompt（自由聊天）
```

**路径解析规则**（与 config.yaml 的路径解析保持一致）：

1. **绝对路径**：直接使用（如 `/home/user/.maestro/prompts/system.md`）
2. **相对路径**：相对于进程 cwd 解析
   - VPS systemd 服务：`WorkingDirectory=$DEPLOY_DIR`，所以 `prompts/system.md` → `$DEPLOY_DIR/prompts/system.md`
   - 本地开发：通常在项目根目录运行 `maestro run`，路径同样正确
   - 如果用户在非项目根目录运行，应使用绝对路径
3. 如未配置 `system_prompt_file`，不查找默认文件，直接使用内置常量（零 IO 开销）

### 2.3 Prompt 文件内容设计

#### 2.3.1 `prompts/system.md`

将当前 `DEFAULT_SYSTEM_PROMPT` 的内容直接写入此文件。支持模板变量注入，使 Action 协议定义可灵活扩展。

模板变量使用 `{{VARIABLE}}` 语法（与 `${ENV_VAR}` 区分），由 `PromptLoader` 在加载时替换。

**初始版本不引入模板变量**，直接使用纯文本。Action 协议作为 system.md 文件的一部分，用户可直接编辑。这样做的理由：

- 模板变量增加了复杂度，但 Action 枚举几乎不会变动
- 用户如果要新增 action，仍需修改代码中的 `ManagerAction` 枚举和路由逻辑
- 外置化的核心价值是让用户能调整 prompt 的措辞、决策原则、输出格式示例，而非动态组合 prompt 片段

文件内容即当前 `DEFAULT_SYSTEM_PROMPT` 的完整文本（第 47-84 行）。

#### 2.3.2 `prompts/chat.md`

```markdown
你是一个正在执行编码任务的 AI 助手。
用户正在向你询问任务的进展。请根据上下文直接回答用户的问题。
回复用自然语言，不需要 JSON 格式。简洁明了。
```

#### 2.3.3 `prompts/free_chat.md`

```markdown
你是一个智能助手。用自然语言回答用户的问题，简洁、准确、有帮助。
```

### 2.4 决策风格（decision_style）设计

通过 `config.yaml` 的 `manager.decision_style` 字段选择预定义的决策风格。决策风格体现为 system prompt 尾部追加的一段「决策原则」文本。

**预定义风格：**

| 风格 | 键值 | 行为特征 |
|------|------|---------|
| 默认 | `default`（或留空） | 当前的决策原则，不追加额外内容 |
| 保守型 | `conservative` | 多确认、少自作主张、遇到不确定性就 ask_user |
| 激进型 | `aggressive` | 大胆推进、减少确认、容错执行 |

**实现方式：** 在 `PromptLoader` 中定义内置的风格文本映射：

```python
DECISION_STYLES = {
    "default": "",  # 不追加额外内容，使用 prompt 文件中的原文
    "conservative": """

## 额外决策原则（保守模式）

- 遇到任何不确定的决策，优先 ask_user
- 每完成一个子任务就报告进展，等待用户确认再继续
- 修改文件前先向用户确认方案
- 避免一次性做大量变更，拆分为小步骤逐步推进
""",
    "aggressive": """

## 额外决策原则（激进模式）

- 除非遇到根本无法判断的选择，否则自行决定并推进
- 不需要逐步确认，直接完成整个任务
- 遇到小问题（格式、命名等）直接按最佳实践处理
- 优先完整完成任务，最后统一报告
""",
}
```

当 `decision_style` 不为 `default` 且不为空时，将对应的风格文本追加到 prompt 文件内容之后。

用户也可以直接在 `prompts/system.md` 中修改「决策原则」部分，此时 `decision_style` 设为 `default` 即可。两种方式互补：配置字段适合快速切换预设，文件编辑适合深度自定义。

### 2.5 PromptLoader 类设计

在 `manager_agent.py` 中新增 `PromptLoader` 类，负责 prompt 文件的加载、缓存、热加载。

```python
class PromptLoader:
    """
    Prompt 文件加载器（无状态，仅维护文件缓存）

    职责：
    1. 从文件加载 prompt 内容
    2. 基于 mtime 实现热加载（文件变更时自动重新读取）
    3. 文件不存在时自动生成默认内容
    4. 加载失败时 fallback 到内置默认值
    """

    def __init__(self):
        # 缓存: {file_path: {"content": str, "mtime": float}}
        self._cache: dict[str, dict] = {}

    def load(self, file_path: str, default_content: str) -> str:
        """
        加载 prompt 文件内容（带热加载缓存）

        参数:
          file_path: 文件路径（绝对路径或相对于 cwd 的相对路径）
          default_content: 文件不存在时写出的默认内容，也是 fallback 值

        返回:
          prompt 文本内容

        路径解析规则：
          - 绝对路径：直接使用
          - 相对路径：相对于进程 cwd（VPS systemd 服务中 cwd = DEPLOY_DIR，
            本地开发中 cwd 通常是项目根目录）
          - 与 config.yaml 的路径解析保持一致
        """
        path = Path(file_path)
        path_str = str(path)

        # 文件不存在 → 自动生成默认文件
        if not path.exists():
            self._generate_default(path, default_content)

        # 检查 mtime（热加载核心）
        try:
            current_mtime = os.path.getmtime(path_str)
        except OSError:
            logger.warning(f"无法读取 prompt 文件 mtime: {path_str}，使用默认值")
            return default_content

        cached = self._cache.get(path_str)
        if cached and cached["mtime"] == current_mtime:
            return cached["content"]

        # 读取文件
        try:
            content = path.read_text(encoding="utf-8").strip()
            if not content:
                logger.warning(f"Prompt 文件为空: {path_str}，使用默认值")
                return default_content
            self._cache[path_str] = {"content": content, "mtime": current_mtime}
            if cached:
                logger.info(f"Prompt 文件已更新，重新加载: {path_str}")
            else:
                logger.info(f"Prompt 文件已加载: {path_str}")
            return content
        except UnicodeDecodeError:
            logger.warning(f"Prompt 文件编码错误（非 UTF-8）: {path_str}，使用默认值")
            return default_content
        except OSError as e:
            logger.warning(f"Prompt 文件读取失败: {path_str}: {e}，使用默认值")
            return default_content

    def _generate_default(self, path: Path, content: str):
        """自动生成默认 prompt 文件"""
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content + "\n", encoding="utf-8")
            logger.warning(f"Prompt 文件不存在，已生成默认文件: {path}")
        except OSError as e:
            logger.warning(f"无法生成默认 prompt 文件: {path}: {e}")
```

### 2.6 ManagerConfig 变更

在 `config.py` 的 `ManagerConfig` dataclass 中新增字段：

```python
@dataclass
class ManagerConfig:
    """Manager Agent 配置"""
    provider: str = "deepseek"
    model: str = "deepseek-chat"
    api_key: str = ""
    base_url: Optional[str] = None
    max_turns: int = 30
    max_budget_usd: float = 5.0
    request_timeout: int = 60
    retry_count: int = 3
    system_prompt: str = ""          # 已有：内联 prompt 字符串

    # ---- 新增字段 ----
    system_prompt_file: str = ""     # system prompt 文件路径（优先于 system_prompt）
    chat_prompt_file: str = ""       # standalone_chat prompt 文件路径
    free_chat_prompt_file: str = ""  # free_chat prompt 文件路径
    decision_style: str = ""         # 决策风格: default | conservative | aggressive
```

**新增字段说明：**

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `system_prompt_file` | `str` | `""` | Manager 主决策 prompt 文件路径。为空时走原逻辑 |
| `chat_prompt_file` | `str` | `""` | `standalone_chat` 的 prompt 文件路径 |
| `free_chat_prompt_file` | `str` | `""` | `free_chat` 的 prompt 文件路径 |
| `decision_style` | `str` | `""` | 决策风格标识，空或 `default` 表示不追加 |

### 2.7 ManagerAgent 改造

#### 2.7.1 `__init__` 方法改造

```python
class ManagerAgent:
    def __init__(self, config: ManagerConfig):
        self.config = config
        self.conversation_history: list[dict] = []
        self._total_cost: float = 0.0

        # Prompt 加载器（新增）
        self._prompt_loader = PromptLoader()
        # 冲突日志去重标志（新增）
        self._warned_prompt_conflict = False

        # system_prompt 加载优先级：
        #   文件路径（system_prompt_file）> 内联字符串（system_prompt）> 内置默认值
        self.system_prompt = self._load_system_prompt()

        self._init_client()
```

#### 2.7.2 新增 `_load_system_prompt()` 方法

```python
def _load_system_prompt(self) -> str:
    """
    加载 system prompt（支持热加载）

    优先级：
    1. config.system_prompt_file 指定的文件
    2. config.system_prompt 内联字符串
    3. DEFAULT_SYSTEM_PROMPT 内置默认值
    """
    if self.config.system_prompt_file:
        # 冲突日志只输出一次，避免每轮 decide() 都打印
        if self.config.system_prompt and not self._warned_prompt_conflict:
            logger.info(
                "system_prompt_file 和 system_prompt 同时配置，"
                "使用文件路径，忽略内联字符串"
            )
            self._warned_prompt_conflict = True
        prompt = self._prompt_loader.load(
            self.config.system_prompt_file,
            DEFAULT_SYSTEM_PROMPT
        )
    elif self.config.system_prompt:
        prompt = self.config.system_prompt
    else:
        prompt = DEFAULT_SYSTEM_PROMPT

    # 追加决策风格
    style = self.config.decision_style or "default"
    style_text = DECISION_STYLES.get(style, "")
    if style_text:
        prompt += style_text

    return prompt
```

#### 2.7.3 `decide()` 方法改造 — 热加载注入点

在 `decide()` 方法开头添加一行热加载调用：

```python
def decide(self, tool_output: str) -> dict:
    # 热加载：检查 prompt 文件是否变更（新增）
    self.system_prompt = self._load_system_prompt()

    # ... 原有逻辑不变
```

`_load_system_prompt()` 内部通过 `PromptLoader.load()` 的 mtime 缓存机制实现热加载：
- 文件未变更 → 命中缓存，直接返回（微秒级）
- 文件已变更 → 重新读取并更新缓存
- 未配置文件路径 → 直接返回内联字符串或默认值（无 IO）

#### 2.7.4 `start_task()` 方法改造

在 `start_task()` 中也触发一次 prompt 重新加载，确保新任务使用最新 prompt：

```python
def start_task(self, requirement: str):
    """开始新任务，重置对话历史"""
    self.conversation_history = []
    self._total_cost = 0.0
    # 重新加载 prompt（新增）
    self.system_prompt = self._load_system_prompt()
    self.conversation_history.append({
        "role": "user",
        "content": f"用户需求：{requirement}\n\n请分析需求并给出第一条指令。"
    })
```

#### 2.7.5 `standalone_chat()` 方法改造

```python
def standalone_chat(self, context_summary: str, user_message: str) -> str:
    # 加载 chat prompt（新增）
    if self.config.chat_prompt_file:
        chat_prompt = self._prompt_loader.load(
            self.config.chat_prompt_file,
            DEFAULT_CHAT_PROMPT
        )
    else:
        chat_prompt = DEFAULT_CHAT_PROMPT

    messages = [
        {"role": "system", "content": chat_prompt},
        {"role": "user", "content": f"[任务上下文]\n{context_summary}\n\n[用户提问]\n{user_message}"}
    ]
    # ... 后续 LLM 调用逻辑不变
```

其中 `DEFAULT_CHAT_PROMPT` 是新增的模块级常量：

```python
DEFAULT_CHAT_PROMPT = (
    "你是一个正在执行编码任务的 AI 助手。"
    "用户正在向你询问任务的进展。请根据上下文直接回答用户的问题。"
    "回复用自然语言，不需要 JSON 格式。简洁明了。"
)
```

#### 2.7.6 `free_chat()` 方法改造

```python
def free_chat(self, history: list[dict], user_message: str) -> str:
    # 加载 free_chat prompt（新增）
    if self.config.free_chat_prompt_file:
        system = self._prompt_loader.load(
            self.config.free_chat_prompt_file,
            DEFAULT_FREE_CHAT_PROMPT
        )
    else:
        system = DEFAULT_FREE_CHAT_PROMPT

    messages = list(history) + [{"role": "user", "content": user_message}]
    # ... 后续 LLM 调用逻辑不变
```

其中 `DEFAULT_FREE_CHAT_PROMPT` 是新增的模块级常量：

```python
DEFAULT_FREE_CHAT_PROMPT = "你是一个智能助手。用自然语言回答用户的问题，简洁、准确、有帮助。"
```

### 2.8 config.example.yaml 变更

在 `manager` 段末尾新增：

```yaml
manager:
  # ... 现有字段不变 ...

  # ---- Prompt 外置化配置 ----

  # System prompt 文件路径（优先于上面的 system_prompt 内联字符串）
  # 支持绝对路径或相对于工作目录的相对路径
  # 文件不存在时会自动生成默认内容
  # 修改文件后下次 decide() 调用自动生效（热加载），无需重启
  # system_prompt_file: prompts/system.md

  # 任务问答 prompt 文件路径（用于 /chat 命令的上下文问答）
  # chat_prompt_file: prompts/chat.md

  # 自由聊天 prompt 文件路径（用于无任务上下文的聊天）
  # free_chat_prompt_file: prompts/free_chat.md

  # 决策风格: default | conservative | aggressive
  # default     — 使用 prompt 文件中的原文（默认）
  # conservative — 保守模式，多确认、遇到不确定就 ask_user
  # aggressive   — 激进模式，大胆推进、减少确认
  # 也可以直接在 prompt 文件中自定义决策原则
  # decision_style: default
```

### 2.9 deploy.sh 中 prompts/ 目录的传输处理

`do_transfer()` 中的 tar 打包排除列表不包含 `prompts/`，因此 `prompts/` 目录会自动随代码传输到 VPS。

**prompts 保护机制（方案 1 联动）：** `do_update()` 在调用 `do_transfer()` 前后会备份/恢复远端 `prompts/` 目录（详见 1.3.6 节），确保用户在 VPS 上的自定义修改不被覆盖。`do_init()` 不做此保护，首次部署使用仓库默认版本。

用户也可以通过 `config.yaml` 的 `system_prompt_file` 指定 tar 排除目录外的路径（如 `~/.maestro/prompts/system.md`），完全避免被传输覆盖。

### 2.10 向后兼容策略

| 场景 | 行为 |
|------|------|
| 不配置 `system_prompt_file` + 不配置 `system_prompt` | 使用 `DEFAULT_SYSTEM_PROMPT` 常量，行为与当前完全一致 |
| 不配置 `system_prompt_file` + 配置 `system_prompt` | 使用 config.yaml 中的内联字符串，行为与当前完全一致 |
| 配置 `system_prompt_file` + 不配置 `system_prompt` | 从文件加载（文件不存在则自动生成默认） |
| 配置 `system_prompt_file` + 配置 `system_prompt` | 文件优先，内联字符串被忽略，记录 info 日志 |
| 不配置 `decision_style` 或设为 `default` | 不追加额外决策原则，使用 prompt 文件原文 |
| 不配置 `chat_prompt_file` | `standalone_chat` 使用 `DEFAULT_CHAT_PROMPT` 常量 |
| 不配置 `free_chat_prompt_file` | `free_chat` 使用 `DEFAULT_FREE_CHAT_PROMPT` 常量 |

**关键原则：所有新增配置字段的默认值为空字符串，空值时走原有逻辑路径。零配置升级，零行为变更。**

### 2.11 完整代码变更清单（方案 3）

#### `src/maestro/manager_agent.py` 变更

```
新增 import：
  - import os                    # PromptLoader 需要 os.path.getmtime()
  - from pathlib import Path     # PromptLoader 需要 Path 操作

新增：
  - DEFAULT_CHAT_PROMPT 常量
  - DEFAULT_FREE_CHAT_PROMPT 常量
  - DECISION_STYLES 字典
  - PromptLoader 类（约 55 行）

修改：
  - ManagerAgent.__init__(): 初始化 _prompt_loader，调用 _load_system_prompt()
  - ManagerAgent.start_task(): 新增 prompt 重新加载
  - ManagerAgent.decide(): 新增热加载调用（1 行）
  - ManagerAgent.standalone_chat(): 使用 PromptLoader 加载 chat prompt
  - ManagerAgent.free_chat(): 使用 PromptLoader 加载 free_chat prompt

新增方法：
  - ManagerAgent._load_system_prompt()

不变：
  - ManagerAction 枚举
  - DEFAULT_SYSTEM_PROMPT 常量（保留作为 fallback 默认值）
  - MODEL_PRICING 字典
  - _estimate_cost() 函数
  - _get_openai_compatible_client() 函数
  - _call_llm_with_retry()
  - _call_openai_compatible()
  - _call_anthropic()
  - _parse_response()
  - decide_with_feedback()
  - total_cost 属性
```

#### `src/maestro/config.py` 变更

```
修改：
  - ManagerConfig: 新增 4 个字段（system_prompt_file, chat_prompt_file,
    free_chat_prompt_file, decision_style）

不变：
  - 所有其他 dataclass
  - load_config() 函数（_dict_to_dataclass 自动处理新字段）
  - _expand_env_vars() 和 _process_config()
```

注意：`_dict_to_dataclass()` 使用 `dataclass_fields` 自动映射，新增字段有默认值，旧配置文件中没有这些字段时自动使用默认值。**无需修改 `load_config()` 函数。**

#### `config.example.yaml` 变更

```
修改：
  - manager 段：新增 system_prompt_file、chat_prompt_file、
    free_chat_prompt_file、decision_style 的注释说明
```

#### 新增文件

```
prompts/system.md      — 默认 system prompt（从 DEFAULT_SYSTEM_PROMPT 复制）
prompts/chat.md        — 默认 chat prompt
prompts/free_chat.md   — 默认 free_chat prompt
```

注意：这些文件由 `PromptLoader` 在首次运行时自动生成，但也作为项目文件提交到仓库，方便用户参考和版本管理。

---

## 影响范围分析

### 3.1 方案 1 影响矩阵

| 文件 | 影响类型 | 影响描述 |
|------|---------|---------|
| `deploy.sh` | 重构 | 拆分 `do_deploy()` 为 5 个子函数；新增入口参数解析；菜单从 3 项改为 4 项 |
| 所有 Python 模块 | 无影响 | — |
| `config.yaml` / `config.example.yaml` | 无影响 | — |

### 3.2 方案 3 影响矩阵

| 文件 | 影响类型 | 影响描述 |
|------|---------|---------|
| `src/maestro/manager_agent.py` | 修改 | 新增 `PromptLoader` 类；改造 5 个方法；新增 2 个常量 + 1 个字典 |
| `src/maestro/config.py` | 修改 | `ManagerConfig` 新增 4 个字段 |
| `config.example.yaml` | 修改 | manager 段新增 4 个配置项说明 |
| `prompts/system.md` | 新增 | 默认 system prompt 文件 |
| `prompts/chat.md` | 新增 | 默认 chat prompt 文件 |
| `prompts/free_chat.md` | 新增 | 默认 free_chat prompt 文件 |
| `src/maestro/orchestrator.py` | 无影响 | `ManagerAgent` 的接口（`start_task`、`decide`）未变 |
| `src/maestro/telegram_bot.py` | 无影响 | 通过 `ManagerAgent` 调用 `standalone_chat`/`free_chat`，接口未变 |
| `src/maestro/cli.py` | 无影响 | — |
| `src/maestro/tool_runner.py` | 无影响 | — |

### 3.3 两方案交叉影响

方案 1 和方案 3 **完全独立，无交叉影响**。方案 1 只修改 `deploy.sh`（bash），方案 3 只修改 Python 模块和配置文件。可以并行开发、独立测试、分别合并。

---

## 关键设计决策

### 决策 1：不引入 Prompt 模板引擎

**决定：** Prompt 文件使用纯文本（Markdown），不引入 Jinja2 等模板引擎。

**理由：**
- Action 协议（execute/done/blocked/ask_user/retry）几乎不会变动，新增 action 仍需改代码中的枚举和路由逻辑
- 决策风格通过 `decision_style` 配置字段以"追加文本"方式实现，足够灵活
- 纯文本文件用户编辑成本最低，不需要了解模板语法
- 减少一个依赖（项目当前零模板依赖）

**折中方案：** 如果未来需要模板变量（如注入工具名称、项目信息），可在 `PromptLoader.load()` 中添加简单的 `str.replace()` 实现，不需要引入模板库。

### 决策 2：热加载使用 mtime 比较而非文件监听

**决定：** 每次 `decide()` 调用时通过 `os.path.getmtime()` 检查文件是否变更，而非使用 `watchdog`/`inotify` 等文件监听方案。

**理由：**
- `os.path.getmtime()` 开销极低（微秒级系统调用）
- `decide()` 调用频率低（每轮一次，间隔通常 10s-600s）
- 不引入新依赖，不需要后台线程
- VPS 环境可能不支持 inotify（容器/chroot 场景）
- 未命中缓存时才执行文件读取，命中时直接返回

### 决策 3：PromptLoader 放在 manager_agent.py 而非独立模块

**决定：** `PromptLoader` 类直接定义在 `manager_agent.py` 中，不新建 `prompt_loader.py`。

**理由：**
- `PromptLoader` 仅被 `ManagerAgent` 使用，职责单一且紧密耦合
- 项目当前 10 个模块，CLAUDE.md 中明确列出了模块清单，增加新模块需要同步更新文档
- `PromptLoader` 代码量约 60 行，不值得独立成文件
- 如果未来其他模块也需要从文件加载配置文本，可以再提取

### 决策 4：deploy.sh 参数位置设计（子命令在前）

**决定：** 使用 `deploy.sh init [deploy.env]` 而非 `deploy.sh [deploy.env] init`。

**理由：**
- 符合 CLI 工具的常见约定（`git clone <url>`、`docker compose up`）
- 子命令在前便于 `case` 分支判断
- `deploy.env` 参数较少使用（大多数用户使用默认路径），放在第二位更合理
- 原来 `deploy.sh deploy.env` 的用法仍然兼容（`*.env` 模式匹配）

### 决策 5：update 模式的前置检查方式

**决定：** 通过检查远程 `$DEPLOY_DIR/.venv` 目录是否存在来判断是否已初始化。

**理由：**
- `.venv` 是 `do_remote_full_install()` 在 Phase 2 中创建的，是"完整安装已完成"的可靠标志
- 如果 `.venv` 不存在，`pip install -e .` 必然失败
- 不需要额外的标记文件或版本号
- 检查只需一次 SSH 调用（`test -d`），开销极低

### 决策 6：prompts/ 目录的版本管理策略

**决定：** `prompts/` 目录提交到 git 仓库，作为"默认模板"参考。`PromptLoader` 首次运行时如果文件不存在也会自动生成。`deploy.sh update` 时自动备份/恢复远端 prompts 目录。

**理由：**
- 提交到仓库方便用户查看和参考默认 prompt 内容
- `deploy.sh update` 通过备份/恢复机制保护 VPS 上用户自定义的 prompt 修改（详见 1.3.6 节）
- `deploy.sh init` 不做保护，首次部署使用仓库默认版本
- 用户也可以通过 `config.yaml` 的 `system_prompt_file` 指定 `~/.maestro/prompts/` 等独立路径，完全规避覆盖问题
- 这与 `config.example.yaml`（提交到仓库）vs `config.yaml`（用户自定义，不提交）的模式一致

### 决策 7：保留 DEFAULT_SYSTEM_PROMPT 常量

**决定：** 外置化后仍保留 `DEFAULT_SYSTEM_PROMPT`、`DEFAULT_CHAT_PROMPT`、`DEFAULT_FREE_CHAT_PROMPT` 作为模块级常量。

**理由：**
- 作为 `PromptLoader` 加载失败时的 fallback 值
- 作为自动生成默认 prompt 文件的内容来源
- 确保即使 prompt 文件被误删、权限错误、编码异常，系统仍能正常工作
- 便于代码审查时快速了解默认 prompt 内容

---

## 附录：实现顺序建议

两个方案可并行实现，各自的内部实现顺序建议：

### 方案 1 实现步骤

1. 从 `do_deploy()` 提取 `do_transfer()`、`do_remote_full_install()`、`do_claude_auth()` 三个函数
2. 编写 `do_remote_quick_update()` 新函数
3. 编写 `do_init()`、`do_update()` 组合函数
4. 删除原 `do_deploy()` 函数
5. 改造 `show_menu()` 为 4 项菜单
6. 添加入口参数解析（SUBCOMMAND + ENV_FILE）
7. 改造脚本尾部的主入口逻辑
8. 手动测试：`deploy.sh init`、`deploy.sh update`、`deploy.sh`（菜单）、`deploy.sh help`、`deploy.sh foo`

### 方案 3 实现步骤

1. 在 `config.py` 的 `ManagerConfig` 中新增 4 个字段
2. 在 `manager_agent.py` 中新增 `DEFAULT_CHAT_PROMPT`、`DEFAULT_FREE_CHAT_PROMPT` 常量
3. 在 `manager_agent.py` 中新增 `DECISION_STYLES` 字典
4. 在 `manager_agent.py` 中新增 `PromptLoader` 类
5. 改造 `ManagerAgent.__init__()`：初始化 `_prompt_loader`，调用 `_load_system_prompt()`
6. 新增 `ManagerAgent._load_system_prompt()` 方法
7. 改造 `ManagerAgent.decide()`：添加热加载调用
8. 改造 `ManagerAgent.start_task()`：添加 prompt 重新加载
9. 改造 `ManagerAgent.standalone_chat()`：使用 `PromptLoader`
10. 改造 `ManagerAgent.free_chat()`：使用 `PromptLoader`
11. 创建 `prompts/system.md`、`prompts/chat.md`、`prompts/free_chat.md` 默认文件
12. 更新 `config.example.yaml` 新增配置项说明
