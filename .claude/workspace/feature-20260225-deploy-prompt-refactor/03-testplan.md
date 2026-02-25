# 测试计划：deploy-prompt-refactor

## 测试策略总述

本次改造包含两个独立子方案：

- **方案 1（deploy.sh 分层改造）**：bash 脚本，依赖 SSH 连接和远程 VPS，**无法用 pytest 做功能测试**。采用结构验证策略：语法检查、help 输出验证、函数定义存在性检查、菜单项检查。
- **方案 3（Prompt 外置化）**：Python 代码，**可用 pytest 做完整的单元测试和集成测试**。包括 PromptLoader 类、ManagerConfig 新字段、ManagerAgent 加载优先级、热加载、决策风格、向后兼容。

测试框架：**pytest**（pyproject.toml dev 依赖）

## 需求→测试映射

| 需求(01-requirements) | 测试用例 | 测试类型 | 文件 |
|----------------------|----------|----------|------|
| 功能点 1：`deploy.sh init` | test_do_init_function_exists | 结构验证 | test_deploy_script.py |
| 功能点 2：`deploy.sh update` | test_do_update_function_exists | 结构验证 | test_deploy_script.py |
| 功能点 3：交互菜单拆分为 4 项 | test_menu_has_four_items | 结构验证 | test_deploy_script.py |
| 功能点 4：参数与菜单共存 | test_subcommand_parsing_exists, test_help_flag_shows_usage | 结构验证 | test_deploy_script.py |
| 功能点 5：update 后重启 systemd | test_update_restarts_systemd | 结构验证 | test_deploy_script.py |
| 功能点 6：System Prompt 外置 | test_load_existing_file, test_file_prompt_overrides_inline | 单元 | test_prompt_loader.py, test_manager_agent_prompt.py |
| 功能点 7：Action 协议作为 prompt 文件一部分 | test_default_constants_unchanged | 单元 | test_manager_agent_prompt.py |
| 功能点 8：决策策略外置（decision_style） | TestDecisionStyle 全部测试 | 单元 | test_manager_agent_prompt.py |
| 功能点 9：standalone_chat/free_chat prompt 外置 | TestStandaloneChatPrompt, TestFreeChatPrompt | 集成 | test_manager_agent_prompt.py |
| 功能点 10：热加载机制 | TestPromptLoaderHotReload, TestHotReloadInjection | 单元+集成 | test_prompt_loader.py, test_manager_agent_prompt.py |
| 功能点 11：Prompt 文件不存在时自动生成 | TestPromptLoaderDefaultGeneration | 单元 | test_prompt_loader.py |
| 功能点 12：config.example.yaml 同步更新 | （人工验证，不适合自动化测试） | - | - |
| AC-4：update 在未部署环境报错 | test_update_checks_venv_exists | 结构验证 | test_deploy_script.py |
| AC-6：无效参数处理 | test_unknown_subcommand_shows_error | 集成 | test_deploy_script.py |
| AC-11：向后兼容 | TestBackwardCompatibility, TestManagerConfigCompatibility | 单元 | test_manager_agent_prompt.py, test_config_prompt_fields.py |

## 测试文件清单

- `tests/__init__.py` — 测试包初始化
- `tests/conftest.py` — 公共 Fixture（4 个 fixture）
- `tests/test_prompt_loader.py` — PromptLoader 单元测试（17 个用例）
  - TestPromptLoaderBasicLoad（3 个）：基本加载功能
  - TestPromptLoaderDefaultGeneration（3 个）：默认文件生成
  - TestPromptLoaderHotReload（4 个）：缓存与热加载
  - TestPromptLoaderErrorHandling（5 个）：异常处理与 Fallback
- `tests/test_manager_agent_prompt.py` — ManagerAgent prompt 集成测试（24 个用例）
  - TestManagerAgentPromptPriority（5 个）：加载优先级
  - TestDecisionStyle（10 个）：决策风格
  - TestHotReloadInjection（3 个）：热加载注入点
  - TestStandaloneChatPrompt（2 个）：standalone_chat prompt 外置
  - TestFreeChatPrompt（2 个）：free_chat prompt 外置
  - TestBackwardCompatibility（4 个）：向后兼容性
- `tests/test_config_prompt_fields.py` — ManagerConfig 字段测试（13 个用例）
  - TestManagerConfigNewFields（8 个）：新字段存在性和默认值
  - TestManagerConfigCompatibility（5 个）：与现有字段兼容
- `tests/test_deploy_script.py` — deploy.sh 结构验证（17 个用例）
  - TestDeployScriptSyntax（1 个）：bash 语法检查
  - TestDeployScriptHelp（3 个）：help 参数
  - TestDeployScriptStructure（11 个）：函数定义、菜单项、参数解析
  - TestDeployScriptUnknownArgs（1 个）：未知参数处理

**总计：71 个测试用例**（不含 collection error 的 41 个 + 被 import error 阻塞的约 30 个）

## Mock 数据

- `conftest.py` 中的 `sample_prompt_content` fixture 提供标准 prompt 文本
- `conftest.py` 中的 `mock_openai_client` fixture 提供 Mock OpenAI 客户端
- `tmp_path`（pytest 内置）用于创建临时 prompt 文件目录
- `unittest.mock.patch` 用于隔离 `ManagerAgent._init_client()` 和 `_call_llm_with_retry()`

## 边界测试场景

- 场景 1：prompt 文件为空（仅空白字符） → fallback 到默认值
- 场景 2：prompt 文件编码非 UTF-8（GBK） → fallback 到默认值
- 场景 3：prompt 文件在加载后被删除 → 重新生成默认文件
- 场景 4：prompt 文件 mtime 不可读 → fallback 到默认值
- 场景 5：文件路径的父目录不存在 → 自动创建
- 场景 6：同时配置 system_prompt_file 和 system_prompt → 文件优先
- 场景 7：未知 decision_style 值 → 不追加额外内容
- 场景 8：deploy.sh 传入未知参数 → 报错退出
- 场景 9：deploy.sh help 在 SSH 连接前拦截退出 → 返回码 0
- 场景 10：deploy.sh 语法正确性 → bash -n 检查通过
- 场景 11：无法写入默认文件（权限问题） → fallback 到默认值不崩溃
- 场景 12：多个文件独立缓存 → 修改一个不影响另一个
- 场景 13：旧配置文件无新字段 → 使用默认值，零影响

## 覆盖目标

- 单元测试覆盖率: 方案 3 新增代码 >= 90%
- 测试类型分布: 单元 70%（PromptLoader + Config 字段）/ 集成 20%（ManagerAgent 端到端）/ 结构验证 10%（deploy.sh）

## TDD 执行结果（Red 阶段）

当前所有测试预期 FAIL 状态：

- `tests/test_prompt_loader.py` — **ImportError**（PromptLoader 尚未实现）
- `tests/test_manager_agent_prompt.py` — **ImportError**（PromptLoader, DEFAULT_CHAT_PROMPT 等尚未实现）
- `tests/test_config_prompt_fields.py` — **25 FAILED / 5 PASSED**（新字段未添加，现有字段正常）
- `tests/test_deploy_script.py` — 脚本结构尚未改造，多数 FAILED

阶段 4 实现后，所有测试应全部 PASS。

## 下游摘要

### 测试文件清单
- tests/conftest.py — 公共 Fixture（ManagerConfig、Mock 客户端、临时目录）
- tests/test_prompt_loader.py — PromptLoader 单元测试（加载、缓存、热加载、生成、异常处理，17 个用例）
- tests/test_manager_agent_prompt.py — ManagerAgent prompt 集成测试（优先级、决策风格、热加载注入、chat/free_chat 外置、向后兼容，24 个用例）
- tests/test_config_prompt_fields.py — ManagerConfig 新字段测试（存在性、默认值、兼容性，13 个用例）
- tests/test_deploy_script.py — deploy.sh 结构验证测试（语法、help、函数定义、菜单、参数解析，17 个用例）

### 边界测试场景
- 场景 1：prompt 文件为空 → fallback 到默认值
- 场景 2：prompt 文件编码非 UTF-8 → fallback 到默认值
- 场景 3：prompt 文件被删除 → 重新生成默认文件
- 场景 4：prompt 文件 mtime 不可读 → fallback 到默认值
- 场景 5：文件路径父目录不存在 → 自动创建
- 场景 6：同时配置 file 和 inline prompt → 文件优先
- 场景 7：未知 decision_style → 不追加额外内容
- 场景 8：deploy.sh 未知参数 → 报错退出
- 场景 9：deploy.sh help 在 SSH 前拦截 → 正常退出
- 场景 10：deploy.sh bash 语法正确 → bash -n 通过
- 场景 11：无法写入默认文件 → fallback 不崩溃
- 场景 12：多文件独立缓存 → 互不影响
- 场景 13：旧配置无新字段 → 默认值兼容

### 覆盖目标
- 单元测试覆盖率: 方案 3 新增代码 >= 90%
- 测试类型分布: 单元 70% / 集成 20% / 结构验证 10%
