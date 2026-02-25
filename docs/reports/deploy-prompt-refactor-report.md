# 开发总结报告：deploy-prompt-refactor

> 版本：1.0.0 | 完成日期：2026-02-25

## 基本信息

| 项目 | 内容 |
|------|------|
| 功能名称 | deploy-prompt-refactor（分层部署脚本改造 + Prompt 外置化） |
| 开发日期 | 2026-02-25 |
| 需求文档 | `.claude/workspace/feature-20260225-deploy-prompt-refactor/01-requirements.md` |
| 设计文档 | `.claude/workspace/feature-20260225-deploy-prompt-refactor/02-design.md` |
| 上游设计 | `.claude/workspace/design-20260225-deploy-prompt-refactor/` |

## 开发过程回顾

### 阶段 1：需求分析

将用户需求拆解为两个独立方案共 12 个功能点和 14 个验收标准：
- **方案 1（分层部署脚本）**：5 个功能点（CLI init/update、菜单拆分、参数共存、systemd 重启）
- **方案 3（Prompt 外置化）**：7 个功能点（prompt 外置、热加载、决策风格、自动生成、config 更新）

识别了 10 个边界场景，包括误操作幂等性、文件编码异常、多实例共享等。

### 阶段 2：系统设计

设计了完整的函数拆分方案和 PromptLoader 类架构：
- deploy.sh 从 `do_deploy()` 拆分为 6 个独立函数（`do_transfer`、`do_remote_full_install`、`do_claude_auth`、`do_remote_quick_update`、`do_init`、`do_update`）
- 设计了 `PromptLoader` 类（mtime 缓存热加载）、`DECISION_STYLES` 字典、三级优先级加载策略
- 确认两方案完全独立，无交叉影响

### 阶段 3：TDD 测试设计

在编码实现前编写了测试骨架：
- 4 个测试文件，共设计 71 个测试用例
- 覆盖：PromptLoader 单元测试、ManagerAgent prompt 集成、ManagerConfig 字段兼容性、deploy.sh 结构验证

### 阶段 4：编码实现

按设计文档完成全部编码：
- 修改 3 个文件：`config.py`（4 个新字段）、`manager_agent.py`（PromptLoader 类 + 6 个方法改造）、`deploy.sh`（函数拆分 + 参数模式）
- 新增 3 个文件：`prompts/system.md`、`prompts/chat.md`、`prompts/free_chat.md`
- 更新 `config.example.yaml`（4 个新配置项）
- 71/71 测试通过

### 阶段 5：代码审查

审查结论：**APPROVE WITH COMMENTS**
- 0 Critical / 0 High / 3 Medium / 3 Low / 2 Info
- 3 个 Medium 问题均已修复：
  - CR-001：统一 `DEFAULT_CHAT_PROMPT` 常量与 `prompts/chat.md` 格式
  - CR-002：`_generate_default()` 写入后填充缓存
  - CR-003：`do_update()` prompts 备份添加用户提示日志

### 阶段 6：集成验证

验证结论：**PASS WITH WARNINGS**
- 构建验证：PASS（pip install -e . 成功）
- bash 语法检查：PASS
- 测试套件：71/71 PASS
- 覆盖率：64%（低于 80% 目标，但项目此前无测试，本次新增代码覆盖充分）
- API 契约验证：PASS（与设计文档完全一致）
- Prompt 文件一致性：PASS（3 文件与 3 常量完全匹配）
- 安全检查：PASS

### 阶段 7：文档交付

- 更新 `CLAUDE.md`：Architecture 目录结构（新增 `prompts/`、`tests/`）、Testing 部分、Key Design Decisions、Configuration 部分
- 生成用户指南：`docs/guides/deploy-prompt-refactor.md`
- 生成开发总结报告：`docs/reports/deploy-prompt-refactor-report.md`
- 生成变更日志：`CHANGELOG.md`

## 关键决策记录

| 决策点 | 选项 | 选择 | 理由 |
|--------|------|------|------|
| Prompt 模板引擎 | Jinja2 / 纯文本 | 纯文本 | Action 协议几乎不变动，纯文本编辑成本最低，零新依赖 |
| 热加载方案 | watchdog / mtime 轮询 | mtime 轮询 | `os.path.getmtime()` 微秒级开销，无需后台线程，VPS 兼容性好 |
| PromptLoader 位置 | 独立模块 / manager_agent.py 内 | manager_agent.py 内 | 仅被 ManagerAgent 使用，约 60 行代码，不值得独立成文件 |
| CLI 参数位置 | 子命令在前 / 在后 | 子命令在前 | 符合 CLI 工具常见约定（git、docker），便于 case 分支判断 |
| update 前置检查 | 标记文件 / .venv 目录 | .venv 目录 | `.venv` 是完整安装的可靠标志，无需额外文件 |
| prompts/ 版本管理 | git 提交 / 忽略 | git 提交 | 作为默认模板参考，update 时自动备份/恢复远端用户修改 |
| 默认常量保留 | 删除 / 保留 | 保留 | 作为 fallback 值和自动生成的内容来源，确保系统鲁棒性 |

## 文件变更清单

### 修改的文件

| 文件 | 变更类型 | 变更说明 |
|------|---------|---------|
| `src/maestro/config.py` | 修改 | ManagerConfig 新增 4 个字段 |
| `src/maestro/manager_agent.py` | 修改 | 新增 PromptLoader 类、3 个常量、DECISION_STYLES 字典；改造 6 个方法 |
| `config.example.yaml` | 修改 | manager 段新增 4 个配置项注释说明 |
| `deploy.sh` | 重构 | 拆分 do_deploy 为 6 个函数，新增参数模式，菜单从 3 项改为 4 项 |
| `CLAUDE.md` | 更新 | Architecture 目录结构、Testing、Key Design Decisions、Configuration |

### 新增的文件

| 文件 | 说明 |
|------|------|
| `prompts/system.md` | 默认 system prompt 文件 |
| `prompts/chat.md` | 默认 chat prompt 文件 |
| `prompts/free_chat.md` | 默认 free_chat prompt 文件 |
| `tests/test_prompt_loader.py` | PromptLoader 单元测试（17 用例） |
| `tests/test_manager_agent_prompt.py` | ManagerAgent prompt 集成测试（24 用例） |
| `tests/test_config_prompt_fields.py` | ManagerConfig 字段测试（13 用例） |
| `tests/test_deploy_script.py` | deploy.sh 结构验证测试（17 用例） |
| `tests/conftest.py` | pytest 配置 |
| `docs/guides/deploy-prompt-refactor.md` | 用户指南 |
| `docs/reports/deploy-prompt-refactor-report.md` | 开发总结报告 |
| `CHANGELOG.md` | 变更日志 |

## 测试摘要

| 测试文件 | 用例数 | 状态 |
|----------|--------|------|
| `test_prompt_loader.py` | 17 | 全部通过 |
| `test_manager_agent_prompt.py` | 24 | 全部通过 |
| `test_config_prompt_fields.py` | 13 | 全部通过 |
| `test_deploy_script.py` | 17 | 全部通过 |
| **总计** | **71** | **全部通过** |

覆盖率：64%（manager_agent.py 60%，config.py 71%）

## 已知限制

1. **覆盖率低于 80% 目标**：主要因为 LLM 调用路径（`_call_openai_compatible`、`_call_anthropic`）和 `config.py` 的 `load_config()` 等非本次改造代码未覆盖。本次新增代码覆盖充分。
2. **deploy.sh 仅 bash -n 静态检查**：未做真实 VPS 环境的端到端测试（需要实际 SSH 连接）。
3. **PromptLoader 路径规范化不完整**：不会解析符号链接或 `../` 等相对引用，同一文件通过不同路径引用会创建独立缓存（实际场景中路径来自配置文件，几乎不会出现）。

## 后续建议

1. **提升测试覆盖率**：为 `_call_openai_compatible()`、`_call_anthropic()` 和 `load_config()` 添加 Mock 测试
2. **VPS 端到端测试**：在实际 VPS 环境验证 `deploy.sh init` 和 `deploy.sh update` 的完整流程
3. **Prompt 模板变量**：如未来需要动态注入变量（如工具名称、项目信息），可在 `PromptLoader.load()` 中添加简单的 `str.replace()` 实现
4. **多环境 Prompt 管理**：考虑支持按环境（dev/staging/prod）加载不同 Prompt 文件
