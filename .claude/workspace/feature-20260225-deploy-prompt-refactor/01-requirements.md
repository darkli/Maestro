# 需求分析：deploy-prompt-refactor

## 功能概述

本次改造包含两个独立子方案：**方案 1（分层部署脚本改造）** 和 **方案 3（Prompt 外置化）**。方案 1 将 `deploy.sh` 从纯交互菜单模式改造为支持命令行参数直接调用（`deploy.sh init` / `deploy.sh update`），同时在交互菜单中将"业务逻辑更新"拆为独立菜单项，降低全量部署的频率。方案 3 将 `manager_agent.py` 中硬编码的 system prompt、action 协议定义、决策策略等内容抽取到外部文件，并支持热加载（运行时检测文件变更自动重载，无需重启服务）。

上游设计文档：`.claude/workspace/design-20260225-deploy-prompt-refactor/`

## 核心功能点

### 方案 1：分层部署脚本改造

- [ ] **功能点 1：CLI 参数模式 -- `deploy.sh init`**
  - 描述：首次部署，执行完整的 Phase 1（文件传输）+ Phase 2（远程安装：系统包、Python、Node.js、Claude Code、Zellij、venv、config.yaml、环境变量、systemd 服务）+ Claude Code 认证引导。等价于当前菜单选项 1 的完整流程。
  - 验收标准：`bash deploy.sh init` 在全新 VPS 上可完成完整部署，无需手动选择菜单。

- [ ] **功能点 2：CLI 参数模式 -- `deploy.sh update`**
  - 描述：增量更新，仅执行 Phase 1（文件传输）+ `pip install -e .`（更新 Python 包），跳过系统包安装、Node.js/Claude Code/Zellij 安装、config.yaml 生成等已有环境初始化步骤。
  - 验收标准：`bash deploy.sh update` 在已部署环境上仅传输代码并重新安装 Python 包，耗时显著少于 `init`。

- [ ] **功能点 3：交互菜单拆分"业务逻辑更新"**
  - 描述：在现有交互菜单中，将当前的「1) 部署 / 更新」拆为两个菜单项：「1) 首次部署（完整安装）」和「2) 业务逻辑更新（仅代码+包）」。原「2) 查看状态」变为「3)」，原「3) 清理卸载」变为「4)」。
  - 验收标准：交互菜单展示 4 个选项（不含退出），各选项功能正确。

- [ ] **功能点 4：参数与菜单共存**
  - 描述：当 `deploy.sh` 收到 `init` 或 `update` 参数时直接执行对应功能并退出（非交互模式）；无参数时进入交互菜单（当前行为）。
  - 验收标准：`deploy.sh init` 非交互执行，`deploy.sh`（无参数）进入交互菜单。

- [ ] **功能点 5：`update` 模式附加能力 -- systemd 服务重启**
  - 描述：`update` 完成后检测 systemd 服务是否存在且已启用，若是则自动 restart maestro-daemon。
  - 验收标准：代码更新后 Telegram Daemon 自动重启，无需手动操作。

### 方案 3：Prompt 外置化（配置与代码分离）

- [ ] **功能点 6：System Prompt 外置**
  - 描述：将 `manager_agent.py` 中的 `DEFAULT_SYSTEM_PROMPT` 常量抽取到外部文件 `prompts/system.md`。`ManagerConfig` 新增 `system_prompt_file` 字段指定文件路径。加载优先级：`system_prompt_file` 指定的文件 > `config.yaml` 中的 `system_prompt` 字符串 > 代码内置默认值。
  - 验收标准：修改外部 prompt 文件后，不重启服务，新创建的任务使用新 prompt。

- [ ] **功能点 7：Action 协议定义外置**
  - 描述：将 action 枚举（execute/done/blocked/ask_user/retry）及其在 system prompt 中的格式示例定义作为 system prompt 文件的一部分。用户可直接编辑 `prompts/system.md` 修改 action 协议格式。
  - 验收标准：新增 action 类型时只需修改外部文件和对应的代码处理逻辑，无需修改 prompt 硬编码。

- [ ] **功能点 8：决策策略外置**
  - 描述：将 system prompt 中「决策原则」部分抽取，支持按场景切换不同决策风格（如"保守型"vs"激进型"）。通过 config.yaml 中的 `manager.decision_style` 字段选择预定义风格，或直接在 prompt 文件中自定义。
  - 验收标准：通过修改配置可切换决策风格，无需改代码。

- [ ] **功能点 9：standalone_chat / free_chat 的 system prompt 外置**
  - 描述：将 `standalone_chat` 和 `free_chat` 方法中硬编码的 system prompt 字符串也抽取到外部文件（`prompts/chat.md` 和 `prompts/free_chat.md`）。
  - 验收标准：修改聊天模式的 prompt 无需改代码。

- [ ] **功能点 10：热加载机制**
  - 描述：在 `ManagerAgent` 中实现 prompt 文件的热加载。每次调用 `decide()` 或创建新任务时（`start_task()`），检查 prompt 文件的修改时间（mtime），若文件已变更则重新读取。使用简单的 mtime 比较即可，无需 inotify/fswatch 等复杂方案。
  - 验收标准：修改 prompt 文件后，下一次 `decide()` 调用自动使用新 prompt，无需重启进程。

- [ ] **功能点 11：Prompt 文件的默认内容生成**
  - 描述：首次运行或 prompt 文件不存在时，自动将代码内置默认 prompt 写出到文件，方便用户基于默认内容自定义修改。
  - 验收标准：删除 prompt 文件后运行，系统自动生成默认 prompt 文件并正常工作。

- [ ] **功能点 12：config.example.yaml 同步更新**
  - 描述：在 `config.example.yaml` 的 `manager` 段新增 `system_prompt_file`、`chat_prompt_file`、`free_chat_prompt_file` 和 `decision_style` 字段的说明和示例。
  - 验收标准：新用户能通过 `config.example.yaml` 了解如何配置 prompt 外置化。

## 边界情况

### 方案 1

- 场景 1：用户在已部署环境上误执行 `deploy.sh init` -> 应正常运行（幂等性），覆盖安装不会损坏现有配置。现有 config.yaml 会被覆盖（与当前行为一致）。
- 场景 2：用户在未部署环境上执行 `deploy.sh update` -> 应友好报错，提示需要先执行 `init`。检查条件：远程 `$DEPLOY_DIR/.venv` 不存在。
- 场景 3：`deploy.sh init` 或 `update` 时 SSH 连接失败 -> 与当前行为一致，`set -euo pipefail` 触发退出。
- 场景 4：传入未知参数（如 `deploy.sh foo`）-> 打印 usage 帮助信息并退出。

### 方案 3

- 场景 1：prompt 文件路径配置了但文件不存在 -> 自动生成默认内容到该路径，并记录 warning 日志。
- 场景 2：prompt 文件内容为空 -> 使用代码内置默认值，记录 warning 日志。
- 场景 3：prompt 文件编码非 UTF-8 -> 尝试 UTF-8 读取，失败则 fallback 到默认值并记录 warning。
- 场景 4：prompt 文件在 `decide()` 执行过程中被修改 -> 不影响当前调用，下次调用时生效。
- 场景 5：多个 Orchestrator 实例共享同一个 prompt 文件 -> 各自独立检测 mtime，互不影响。
- 场景 6：`system_prompt`（config.yaml 内联字符串）和 `system_prompt_file`（文件路径）同时配置 -> 文件路径优先，config 中的字符串被忽略，记录 info 日志。

## 非功能需求

- **性能**：热加载使用 mtime 比较（`os.path.getmtime()`），开销可忽略（微秒级），不影响 `decide()` 的延迟。
- **兼容性**：
  - deploy.sh 保持 bash 3.2+ 兼容（macOS 默认 shell）。
  - Prompt 外置化向后兼容：不配置 `system_prompt_file` 时，行为与当前完全一致。
- **可维护性**：Prompt 文件使用 Markdown 格式（`.md`），便于编辑和版本管理。

## 约束条件

- **技术约束**：
  - deploy.sh 必须保持单文件可执行，不引入外部依赖（除现有的 sshpass）。
  - Prompt 热加载不使用文件监听库（如 watchdog），仅用 `os.path.getmtime()` 轮询比较。
  - 项目无 static-types（无 mypy）。
  - 测试框架为 pytest，但项目暂未配置测试。
  - 所有用户可见字符串、注释使用中文。

## 影响范围

### 方案 1 影响

- **修改的文件**：
  - `deploy.sh`：重构为支持参数模式 + 菜单拆分
- **不影响**：所有 Python 模块、config.yaml 格式

### 方案 3 影响

- **修改的文件**：
  - `src/maestro/manager_agent.py`：添加热加载逻辑、prompt 文件读取
  - `src/maestro/config.py`：`ManagerConfig` 新增字段
  - `config.example.yaml`：新增配置项说明
- **新增的文件**：
  - `prompts/system.md`：默认 system prompt
  - `prompts/chat.md`：standalone_chat 的 system prompt
  - `prompts/free_chat.md`：free_chat 的 system prompt
- **不影响**：`orchestrator.py`、`tool_runner.py`、`cli.py`（无需修改调用方式）

## 验收标准汇总

### 方案 1

- [ ] AC-1: `bash deploy.sh init` 在全新 VPS 完成完整部署
- [ ] AC-2: `bash deploy.sh update` 仅传输代码并更新 Python 包
- [ ] AC-3: `bash deploy.sh update` 完成后自动重启 maestro-daemon（如已启用）
- [ ] AC-4: `deploy.sh update` 在未部署环境上友好报错
- [ ] AC-5: `deploy.sh`（无参数）进入交互菜单，菜单含 4 项（首次部署、业务更新、查看状态、清理卸载）
- [ ] AC-6: `deploy.sh foo`（无效参数）打印 usage 并退出
- [ ] AC-7: 所有原有功能不受影响

### 方案 3

- [ ] AC-8: 配置 `system_prompt_file` 后，ManagerAgent 从文件加载 prompt
- [ ] AC-9: 修改 prompt 文件后，下次 `decide()` 调用自动使用新内容（热加载）
- [ ] AC-10: prompt 文件不存在时自动生成默认内容
- [ ] AC-11: 不配置 `system_prompt_file` 时行为与当前完全一致（向后兼容）
- [ ] AC-12: `standalone_chat` / `free_chat` 的 prompt 也支持外置
- [ ] AC-13: `config.example.yaml` 包含新配置项的说明
- [ ] AC-14: `prompts/` 目录包含所有默认 prompt 文件

## 风险评估

- **风险 1：deploy.sh 重构引入 regression** -> 应对策略：保持 `do_deploy()` 函数内部逻辑不变，仅拆分调用入口。`init` 调用组合函数 `do_init()`，`update` 调用新函数 `do_update()`。菜单选项映射到同一组函数。
- **风险 2：Prompt 热加载的竞态条件** -> 应对策略：热加载仅在 `decide()` 入口处执行，单线程内操作，无并发问题。多进程共享文件的场景下各自独立读取，不存在写竞争。
- **风险 3：Prompt 文件被误删导致服务异常** -> 应对策略：文件不存在时 fallback 到代码内置默认值，并记录 warning 日志。同时提供自动生成默认文件的能力。
- **风险 4：deploy.sh update 在半部署状态执行** -> 应对策略：检查远程 `.venv` 目录是否存在，不存在则提示先执行 `init`。

## 下游摘要

### 功能点清单
- [ ] 功能点 1：CLI 参数模式 -- `deploy.sh init`（首次完整部署）
- [ ] 功能点 2：CLI 参数模式 -- `deploy.sh update`（增量更新：文件传输 + pip install）
- [ ] 功能点 3：交互菜单拆分为 4 项（首次部署、业务更新、查看状态、清理卸载）
- [ ] 功能点 4：参数与菜单共存（有参数直接执行，无参数进入菜单）
- [ ] 功能点 5：update 模式自动重启 systemd 服务
- [ ] 功能点 6：System Prompt 外置到 `prompts/system.md`
- [ ] 功能点 7：Action 协议定义作为 system prompt 文件的一部分
- [ ] 功能点 8：决策策略外置，支持 decision_style 配置切换
- [ ] 功能点 9：standalone_chat / free_chat 的 prompt 外置
- [ ] 功能点 10：热加载机制（mtime 比较）
- [ ] 功能点 11：Prompt 文件不存在时自动生成默认内容
- [ ] 功能点 12：config.example.yaml 同步更新新配置项

### 验收标准清单
- [ ] AC-1: `bash deploy.sh init` 在全新 VPS 完成完整部署
- [ ] AC-2: `bash deploy.sh update` 仅传输代码并更新 Python 包
- [ ] AC-3: `bash deploy.sh update` 完成后自动重启 maestro-daemon（如已启用）
- [ ] AC-4: `deploy.sh update` 在未部署环境上友好报错
- [ ] AC-5: `deploy.sh`（无参数）进入交互菜单，菜单含 4 项
- [ ] AC-6: `deploy.sh foo`（无效参数）打印 usage 并退出
- [ ] AC-7: 所有原有功能不受影响
- [ ] AC-8: 配置 `system_prompt_file` 后，ManagerAgent 从文件加载 prompt
- [ ] AC-9: 修改 prompt 文件后，下次 `decide()` 调用自动使用新内容（热加载）
- [ ] AC-10: prompt 文件不存在时自动生成默认内容
- [ ] AC-11: 不配置 `system_prompt_file` 时行为与当前完全一致（向后兼容）
- [ ] AC-12: `standalone_chat` / `free_chat` 的 prompt 也支持外置
- [ ] AC-13: `config.example.yaml` 包含新配置项的说明
- [ ] AC-14: `prompts/` 目录包含所有默认 prompt 文件
