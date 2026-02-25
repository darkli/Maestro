# 编码实现：deploy-prompt-refactor

## 实现概述

按照 `02-design.md` 设计文档，完成了两个独立方案的全部编码实现：

1. **方案 3（Prompt 外置化）**：修改 `config.py`、`manager_agent.py`，创建 `prompts/` 默认文件，更新 `config.example.yaml`
2. **方案 1（deploy.sh 改造）**：拆分函数、新增参数模式、菜单改造

## 文件变更清单

### 方案 3：Prompt 外置化

| 文件 | 变更类型 | 变更说明 |
|------|---------|---------|
| `src/maestro/config.py` | 修改 | `ManagerConfig` 新增 4 个字段：`system_prompt_file`、`chat_prompt_file`、`free_chat_prompt_file`、`decision_style` |
| `src/maestro/manager_agent.py` | 修改 | 新增 `import os`、`from pathlib import Path`；新增 `DEFAULT_CHAT_PROMPT`、`DEFAULT_FREE_CHAT_PROMPT` 常量；新增 `DECISION_STYLES` 字典；新增 `PromptLoader` 类（约 60 行）；改造 `ManagerAgent.__init__()`、`_load_system_prompt()`（新增）、`start_task()`、`decide()`、`standalone_chat()`、`free_chat()` |
| `config.example.yaml` | 修改 | `manager` 段新增 4 个配置项说明（注释形式） |
| `prompts/system.md` | 新增 | 默认 system prompt 文件（内容与 `DEFAULT_SYSTEM_PROMPT` 一致） |
| `prompts/chat.md` | 新增 | 默认 chat prompt 文件 |
| `prompts/free_chat.md` | 新增 | 默认 free_chat prompt 文件 |

### 方案 1：deploy.sh 分层改造

| 文件 | 变更类型 | 变更说明 |
|------|---------|---------|
| `deploy.sh` | 重构 | 删除 `do_deploy()`，拆分为 `do_transfer()`、`do_remote_full_install()`、`do_claude_auth()`；新增 `do_remote_quick_update()`、`do_init()`、`do_update()`；新增入口参数解析（SUBCOMMAND + help 拦截）；菜单从 3 项改为 4 项；主入口改为 `case "$SUBCOMMAND"` 路由 |

## 需求覆盖核对表

### 方案 1

- [x] 功能点 1：CLI 参数模式 -- `deploy.sh init`（首次完整部署）
- [x] 功能点 2：CLI 参数模式 -- `deploy.sh update`（增量更新）
- [x] 功能点 3：交互菜单拆分为 4 项
- [x] 功能点 4：参数与菜单共存
- [x] 功能点 5：update 模式自动重启 systemd 服务

### 方案 3

- [x] 功能点 6：System Prompt 外置到 `prompts/system.md`
- [x] 功能点 7：Action 协议定义作为 system prompt 文件的一部分
- [x] 功能点 8：决策策略外置，支持 decision_style 配置切换
- [x] 功能点 9：standalone_chat / free_chat 的 prompt 外置
- [x] 功能点 10：热加载机制（mtime 比较）
- [x] 功能点 11：Prompt 文件不存在时自动生成默认内容
- [x] 功能点 12：config.example.yaml 同步更新新配置项

## 测试结果

```
71 passed in 0.57s
```

全部 71 个测试用例通过：
- `tests/test_config_prompt_fields.py` — 13 passed（ManagerConfig 新字段）
- `tests/test_deploy_script.py` — 17 passed（deploy.sh 结构验证）
- `tests/test_manager_agent_prompt.py` — 24 passed（ManagerAgent prompt 集成）
- `tests/test_prompt_loader.py` — 17 passed（PromptLoader 单元测试）

## 实现要点

### PromptLoader 类

- 基于 `os.path.getmtime()` 的 mtime 缓存实现热加载
- 文件不存在时自动生成默认文件并直接返回默认值（避免 strip 差异）
- 异常处理覆盖：空文件、非 UTF-8 编码、mtime 不可读、权限错误
- 多文件独立缓存

### ManagerAgent 改造

- `__init__()` 初始化 `PromptLoader`，通过 `_load_system_prompt()` 统一加载
- `_load_system_prompt()` 实现三级优先级：文件 > 内联字符串 > 默认常量
- `decide()` 和 `start_task()` 入口处调用 `_load_system_prompt()` 实现热加载
- `standalone_chat()` 和 `free_chat()` 分别支持 `chat_prompt_file` 和 `free_chat_prompt_file`
- `DECISION_STYLES` 字典追加到 prompt 末尾

### deploy.sh 改造

- `do_deploy()` 完全拆分为 `do_transfer()` + `do_remote_full_install()` + `do_claude_auth()`
- 新增 `do_remote_quick_update()`：仅 `pip install -e .` + systemd restart
- `do_init()` = transfer + full_install + auth
- `do_update()` = 前置检查 + prompts 备份 + transfer + prompts 恢复 + quick_update
- 入口解析：help 在 SSH 连接前拦截退出；init/update 直接执行；无参数进菜单
- 未知命令报错退出

## 下游摘要

### 变更文件清单
- `src/maestro/config.py` — ManagerConfig 新增 4 个字段
- `src/maestro/manager_agent.py` — 新增 PromptLoader 类、3 个常量、DECISION_STYLES 字典；改造 6 个方法
- `config.example.yaml` — manager 段新增 4 个配置项说明
- `prompts/system.md` — 默认 system prompt 文件
- `prompts/chat.md` — 默认 chat prompt 文件
- `prompts/free_chat.md` — 默认 free_chat prompt 文件
- `deploy.sh` — 重构：拆分 do_deploy 为 6 个函数，新增参数模式，菜单 4 项

### 测试结果
- 71/71 测试通过
- 覆盖：PromptLoader 单元测试、ManagerAgent 集成测试、ManagerConfig 字段测试、deploy.sh 结构验证
