# deploy-prompt-refactor 用户指南

> 版本：1.0.0 | 更新日期：2026-02-25

本指南介绍两个新功能：**分层部署脚本**和 **Prompt 外置化**。

---

## 功能一：分层部署脚本

### 功能介绍

`deploy.sh` 现在支持两种使用方式：

1. **命令行参数模式**：直接执行 `deploy.sh init` 或 `deploy.sh update`，适合自动化脚本和 CI/CD 场景
2. **交互菜单模式**：不带参数运行 `deploy.sh`，进入可视化菜单选择操作

### 前置条件

- 本地已安装 bash 3.2+
- 已配置 `deploy.env` 文件（包含 VPS 连接信息和 API Key）
- VPS 可通过 SSH 连接

### 使用步骤

#### 1. 首次部署（完整安装）

```bash
# 方式一：命令行参数
bash deploy.sh init

# 方式二：交互菜单中选择 "1) 首次部署（完整安装）"
bash deploy.sh
```

`init` 执行完整的部署流程：
1. 传输项目文件到 VPS（Phase 1）
2. 远程安装系统包、Python、Node.js、Claude Code、Zellij、venv、配置文件、systemd 服务（Phase 2）
3. 编码工具认证引导（Claude Code / Codex CLI 由用户手动登录）

#### 2. 业务逻辑更新（增量更新）

```bash
# 方式一：命令行参数
bash deploy.sh update

# 方式二：交互菜单中选择 "2) 业务逻辑更新（仅代码+包）"
bash deploy.sh
```

`update` 仅执行轻量更新：
1. 传输项目文件到 VPS
2. 执行 `pip install -e .` 更新 Python 包
3. 自动重启 maestro-daemon systemd 服务（如已启用）

**注意**：`update` 会自动备份 VPS 上的 `prompts/` 目录，传输完成后恢复，防止用户在 VPS 上的自定义 Prompt 修改被覆盖。

#### 3. 查看帮助

```bash
bash deploy.sh help
# 或
bash deploy.sh --help
bash deploy.sh -h
```

#### 4. 指定自定义 deploy.env 路径

```bash
bash deploy.sh init /path/to/my-deploy.env
bash deploy.sh update /path/to/my-deploy.env
```

### 交互菜单

不带参数运行 `deploy.sh` 时，将看到以下菜单：

```
  ╔══════════════════════════════════════╗
  ║     Maestro VPS 部署管理工具         ║
  ╚══════════════════════════════════════╝

  目标: user@host:port

  1) 首次部署（完整安装）
  2) 业务逻辑更新（仅代码+包）
  3) 查看状态
  4) 清理卸载
  0) 退出
```

### 常见问题

**Q: 在已部署环境上误执行了 `deploy.sh init` 会怎样？**

A: `init` 是幂等的，会覆盖安装但不会损坏现有配置。不过 `config.yaml` 会被重新生成（与之前行为一致）。

**Q: 在未部署环境上执行 `deploy.sh update` 会怎样？**

A: 会友好报错提示"远程环境未初始化，请先执行 deploy.sh init"。

**Q: 传入未知参数（如 `deploy.sh foo`）会怎样？**

A: 会打印错误信息和用法说明并退出。

---

## 功能二：Prompt 外置化

### 功能介绍

Manager Agent 的 system prompt、聊天 prompt 等内容现在可以从外部 Markdown 文件加载，支持运行时热加载（修改文件后下次调用自动生效），无需重启服务。

### 前置条件

- Maestro 已安装并可正常运行
- 如需自定义 Prompt，需要编辑权限访问 Prompt 文件

### 使用步骤

#### 1. 启用 Prompt 文件加载

编辑 `config.yaml`，在 `manager` 段添加以下配置：

```yaml
manager:
  # ... 其他配置 ...

  # 启用 Prompt 外置化
  system_prompt_file: prompts/system.md
  chat_prompt_file: prompts/chat.md
  free_chat_prompt_file: prompts/free_chat.md
```

#### 2. 自定义 Prompt 内容

直接编辑 `prompts/` 目录下的 Markdown 文件：

| 文件 | 用途 | 影响范围 |
|------|------|---------|
| `prompts/system.md` | 主决策 system prompt | `decide()` 每轮决策 |
| `prompts/chat.md` | 任务问答 prompt | `/chat` 命令、Telegram `/chat` |
| `prompts/free_chat.md` | 自由聊天 prompt | Telegram 无任务上下文聊天 |

修改保存后，下次 `decide()` 或 `start_task()` 调用时自动使用新内容，无需重启。

#### 3. 切换决策风格

在 `config.yaml` 中设置 `decision_style`：

```yaml
manager:
  decision_style: conservative  # 保守模式：多确认、遇到不确定就 ask_user
  # decision_style: aggressive  # 激进模式：大胆推进、减少确认
  # decision_style: default     # 默认：使用 prompt 文件原文
```

决策风格会在 prompt 文件内容末尾追加对应的"额外决策原则"。

#### 4. 自动生成默认 Prompt 文件

如果配置了 `system_prompt_file` 但文件不存在，系统会自动生成包含默认内容的文件。这意味着你可以：

1. 配置好路径
2. 运行一次 Maestro
3. 系统自动生成默认 Prompt 文件
4. 基于默认内容进行自定义修改

### Prompt 加载优先级

System prompt 的加载遵循以下优先级（从高到低）：

1. `system_prompt_file` 指定的外部文件内容
2. `system_prompt` 内联字符串（config.yaml 中直接写入）
3. 代码内置默认值（`DEFAULT_SYSTEM_PROMPT` 常量）

如果同时配置了 `system_prompt_file` 和 `system_prompt`，文件路径优先，内联字符串被忽略。

### 常见问题

**Q: 不配置 Prompt 外置化相关字段，系统行为有变化吗？**

A: 完全没有变化。所有新增配置字段默认为空，空值时走原有逻辑路径。这是零配置升级，零行为变更。

**Q: Prompt 文件被误删会怎样？**

A: 系统会 fallback 到代码内置默认值并记录 warning 日志。下次调用时如果配置了文件路径，会自动重新生成默认文件。

**Q: 多个任务共享同一个 Prompt 文件，修改会冲突吗？**

A: 不会。每个 `ManagerAgent` 实例独立检测文件 mtime，互不影响。文件修改仅在 `decide()` 入口处读取，不存在写竞争。

**Q: 在 VPS 上修改了 Prompt 文件，执行 `deploy.sh update` 会覆盖吗？**

A: 不会。`update` 模式会自动备份/恢复远端 `prompts/` 目录。但 `init` 模式（首次部署）不做此保护。如果担心覆盖，可以将 Prompt 文件放到 `~/.maestro/prompts/` 等独立路径。

### 注意事项

- Prompt 文件必须使用 UTF-8 编码
- 空文件会触发 fallback 到默认值
- 热加载使用 `os.path.getmtime()` 比较（微秒级开销），不影响性能
- `decision_style` 中的未知值会被忽略（不追加额外内容）
