# Changelog

本文件记录 Maestro 项目的所有重要变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)。

## [0.2.0] - 2026-02-25

### 新增 (Added)

- **Prompt 外置化**：Manager Agent 的 system prompt、chat prompt、free_chat prompt 支持从外部 Markdown 文件加载（`prompts/system.md`、`prompts/chat.md`、`prompts/free_chat.md`）
- **Prompt 热加载**：基于 mtime 缓存的热加载机制，修改 prompt 文件后下次 `decide()` 调用自动生效，无需重启服务
- **决策风格切换**：通过 `config.yaml` 的 `manager.decision_style` 字段支持 `default`/`conservative`/`aggressive` 三种预定义决策风格
- **deploy.sh CLI 参数模式**：支持 `deploy.sh init`（首次完整部署）和 `deploy.sh update`（仅代码+包增量更新）
- **deploy.sh help 命令**：支持 `deploy.sh help`/`--help`/`-h` 查看帮助
- **deploy.sh update 自动重启**：`update` 完成后自动检测并重启 maestro-daemon systemd 服务
- **deploy.sh prompts 保护**：`update` 模式自动备份/恢复远端 `prompts/` 目录，防止用户自定义被覆盖
- **PromptLoader 类**：`manager_agent.py` 内新增 prompt 文件加载器，支持缓存、热加载、自动生成默认文件
- **ManagerConfig 新字段**：`system_prompt_file`、`chat_prompt_file`、`free_chat_prompt_file`、`decision_style`
- **pytest 测试套件**：新增 71 个测试用例（4 个测试文件），覆盖 PromptLoader、ManagerAgent prompt 集成、ManagerConfig 字段、deploy.sh 结构验证

### 变更 (Changed)

- **deploy.sh 函数拆分**：原 `do_deploy()` 拆分为 `do_transfer()`、`do_remote_full_install()`、`do_claude_auth()` 三个独立函数，新增 `do_remote_quick_update()`、`do_init()`、`do_update()` 组合函数
- **deploy.sh 交互菜单**：从 3 项（部署/更新、查看状态、清理卸载）改为 4 项（首次部署、业务逻辑更新、查看状态、清理卸载）
- **ManagerAgent.standalone_chat()**：支持通过 `chat_prompt_file` 配置从文件加载 prompt
- **ManagerAgent.free_chat()**：支持通过 `free_chat_prompt_file` 配置从文件加载 prompt
- **CLAUDE.md**：更新 Architecture 目录结构（新增 `prompts/`、`tests/`）、Testing 部分、Key Design Decisions、Configuration 部分

### 技术细节

- 影响文件数：7 个修改 + 14 个新增
- 测试覆盖率：64%（manager_agent.py 60%，config.py 71%）
- 新增依赖：无（全部使用 Python 标准库）
- 向后兼容：完全兼容，所有新增配置字段默认为空，空值时走原有逻辑路径
