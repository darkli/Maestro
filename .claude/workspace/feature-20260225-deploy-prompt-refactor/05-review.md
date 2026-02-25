# 代码审查报告：deploy-prompt-refactor

## 审查摘要表

| 级别 | 数量 | 说明 |
|------|------|------|
| Critical | 0 | 无安全/数据损坏类问题 |
| High | 0 | 无功能缺陷或重大规范违反 |
| Medium | 3 | 内容一致性、边界处理改进建议 |
| Low | 3 | 代码风格和健壮性建议 |
| Info | 2 | 信息提示，非问题 |

## 整体评估

**APPROVE WITH COMMENTS**

两个方案的实现质量良好，完整覆盖了需求文档中的所有功能点和验收标准。代码结构清晰，与设计文档高度一致，测试覆盖全面（71/71 通过）。仅有少量 Medium 级别的内容一致性和健壮性问题，不影响功能正确性。

---

## 需求覆盖核对（对照 01-requirements.md）

### 方案 1：deploy.sh 分层改造

| 功能点 | 状态 | 核对说明 |
|--------|------|----------|
| 功能点 1：CLI `deploy.sh init` | 已实现 | `do_init()` = `do_transfer()` + `do_remote_full_install()` + `do_claude_auth()`，与设计一致 |
| 功能点 2：CLI `deploy.sh update` | 已实现 | `do_update()` = 前置检查 + prompts 备份 + `do_transfer()` + prompts 恢复 + `do_remote_quick_update()` |
| 功能点 3：交互菜单拆分为 4 项 | 已实现 | `show_menu()` 包含 4 项（首次部署、业务逻辑更新、查看状态、清理卸载）+ 退出 |
| 功能点 4：参数与菜单共存 | 已实现 | 顶部 `case` 解析 SUBCOMMAND，底部 `case "$SUBCOMMAND"` 路由 |
| 功能点 5：update 后重启 systemd | 已实现 | `do_remote_quick_update()` 中检查 `is-enabled` 并 `restart` |

### 方案 3：Prompt 外置化

| 功能点 | 状态 | 核对说明 |
|--------|------|----------|
| 功能点 6：System Prompt 外置 | 已实现 | `PromptLoader` + `_load_system_prompt()` 三级优先级 |
| 功能点 7：Action 协议作为 prompt 一部分 | 已实现 | `prompts/system.md` 包含完整 Action 枚举和格式示例 |
| 功能点 8：决策策略外置 | 已实现 | `DECISION_STYLES` 字典 + `decision_style` 配置字段 |
| 功能点 9：standalone_chat/free_chat 外置 | 已实现 | 两个方法均使用 `PromptLoader` 加载 |
| 功能点 10：热加载机制 | 已实现 | mtime 缓存，`decide()` 和 `start_task()` 入口触发 |
| 功能点 11：文件不存在时自动生成 | 已实现 | `_generate_default()` 创建目录 + 写入默认内容 |
| 功能点 12：config.example.yaml 更新 | 已实现 | manager 段新增 4 个配置项注释说明 |

### 验收标准核对

| 验收标准 | 状态 | 核对说明 |
|----------|------|----------|
| AC-1 | 已实现 | `do_init()` 完整执行 transfer + full_install + auth |
| AC-2 | 已实现 | `do_update()` 仅 transfer + pip install |
| AC-3 | 已实现 | `do_remote_quick_update()` 检查并重启 maestro-daemon |
| AC-4 | 已实现 | `do_update()` 前置检查 `.venv` 目录 |
| AC-5 | 已实现 | 菜单 4 项 + 退出选项 |
| AC-6 | 已实现 | 未知参数 `err` + `exit 1` |
| AC-7 | 已实现 | bash -n 语法检查通过 |
| AC-8 | 已实现 | 文件路径优先于内联字符串 |
| AC-9 | 已实现 | decide() 入口调用 `_load_system_prompt()` |
| AC-10 | 已实现 | 自动生成默认文件并返回默认值 |
| AC-11 | 已实现 | 零配置升级，行为完全一致 |
| AC-12 | 已实现 | standalone_chat + free_chat 均支持文件加载 |
| AC-13 | 已实现 | config.example.yaml 包含 4 个新字段说明 |
| AC-14 | 已实现 | prompts/ 目录包含 3 个默认文件 |

---

## 设计一致性核对（对照 02-design.md）

### 方案 1：deploy.sh

| 设计项 | 一致性 | 说明 |
|--------|--------|------|
| 函数拆分（do_transfer / do_remote_full_install / do_claude_auth） | 一致 | 从 do_deploy() 完整拆分，内部逻辑不变 |
| 新增 do_remote_quick_update() | 一致 | pip install + systemd restart |
| 组合函数 do_init() / do_update() | 一致 | 调用链与设计一致 |
| SUBCOMMAND 解析（1.5 节） | 一致 | help 在 SSH 前拦截，init/update 设置 SUBCOMMAND |
| ENV_FILE 兼容（1.5 节） | 一致 | 子命令在前，ENV_FILE 取 $2 |
| 未知命令处理 | 一致 | `*` 分支区分文件和未知命令 |
| show_menu() 4 项 | 一致 | 与设计 1.6 节一致 |
| prompts 备份/恢复（1.3.6 节） | 一致 | do_update() 中 cp -r 备份 + 恢复 |

### 方案 3：Prompt 外置化

| 设计项 | 一致性 | 说明 |
|--------|--------|------|
| PromptLoader 类接口（2.5 节） | 一致 | `__init__()`, `load()`, `_generate_default()` 签名一致 |
| mtime 缓存机制 | 一致 | `_cache: dict[str, dict]`，mtime 比较 |
| ManagerConfig 4 个新字段（2.6 节） | 一致 | 名称、类型、默认值完全一致 |
| `_load_system_prompt()` 优先级（2.7.2 节） | 一致 | 文件 > 内联 > 默认 |
| decide() 热加载注入（2.7.3 节） | 一致 | 方法入口处调用 |
| start_task() 重新加载（2.7.4 节） | 一致 | 重置历史后重新加载 |
| standalone_chat() 改造（2.7.5 节） | 一致 | 使用 PromptLoader + DEFAULT_CHAT_PROMPT |
| free_chat() 改造（2.7.6 节） | 一致 | 使用 PromptLoader + DEFAULT_FREE_CHAT_PROMPT |
| config.example.yaml 变更（2.8 节） | 一致 | 注释格式和内容与设计一致 |
| 向后兼容矩阵（2.10 节） | 一致 | 所有 7 种场景行为正确 |

---

## 异常场景覆盖核对（对照 03-testplan.md）

| 边界场景 | 代码处理 | 测试覆盖 |
|----------|----------|----------|
| 场景 1：prompt 文件为空 | `if not content:` fallback | test_empty_file_fallback_to_default |
| 场景 2：非 UTF-8 编码 | `except UnicodeDecodeError:` fallback | test_non_utf8_file_fallback_to_default |
| 场景 3：文件被删除 | `if not path.exists():` 重新生成 | test_file_deleted_after_cache_fallback_to_default |
| 场景 4：mtime 不可读 | `except OSError:` fallback | test_mtime_unreadable_fallback_to_default |
| 场景 5：父目录不存在 | `path.parent.mkdir(parents=True)` | test_generate_default_creates_parent_dirs |
| 场景 6：file + inline 冲突 | 文件优先 + info 日志 | test_file_prompt_overrides_inline |
| 场景 7：未知 decision_style | `DECISION_STYLES.get(style, "")` 返回空 | test_unknown_style_no_change |
| 场景 8：deploy.sh 未知参数 | `err` + `exit 1` | test_unknown_subcommand_shows_error |
| 场景 9：help 在 SSH 前拦截 | case 分支 `exit 0` | test_help_flag_shows_usage |
| 场景 10：bash 语法正确 | bash -n | test_bash_syntax_check |
| 场景 11：无法写入默认文件 | `except OSError:` 不崩溃 | test_generate_default_on_permission_error |
| 场景 12：多文件独立缓存 | 按 path_str 独立缓存 | test_multiple_files_cached_independently |
| 场景 13：旧配置无新字段 | 默认值兼容 | test_dict_to_dataclass_without_new_fields |

---

## 安全审计

### 敏感信息泄露

无问题发现。代码中不涉及硬编码密钥或敏感信息。`PromptLoader` 仅处理 prompt 文本文件，不涉及凭证。`deploy.sh` 中的敏感变量（API Key 等）来自 `deploy.env`，不在代码中硬编码。

### 输入验证

`PromptLoader.load()` 对 `file_path` 参数未做路径清理（如防止路径穿越），但该参数来自 `config.yaml` 配置文件（管理员控制），不接受用户输入，因此不构成安全风险。记为 Info。

### 文件操作安全

`_generate_default()` 在文件不存在时自动创建文件和目录。此行为已有适当的异常处理。`deploy.sh` 中的 `do_update()` prompts 备份使用 `/tmp/_maestro_prompts_bak`，在多用户 VPS 上理论上存在 tmp 目录名冲突风险，但实际场景中 Maestro 通常由单个用户运行，风险极低。记为 Info。

---

## 详细发现

### Medium

**[CR-001] prompts/chat.md 文件内容与 DEFAULT_CHAT_PROMPT 常量不一致**

- 文件：`prompts/chat.md` vs `src/maestro/manager_agent.py:88-92`
- 问题描述：`DEFAULT_CHAT_PROMPT` 常量是单行拼接字符串（句子之间无换行），而 `prompts/chat.md` 文件中使用了多行格式（每句一行）。虽然语义相同，但这意味着当 `PromptLoader` 从文件加载并 `strip()` 后得到的内容与 `DEFAULT_CHAT_PROMPT` 常量不完全相等。如果代码中有依赖精确相等比较的逻辑（目前没有），这将是一个 bug。更重要的是，当 `_generate_default()` 自动生成 chat.md 文件时，写出的是 `DEFAULT_CHAT_PROMPT + "\n"`（单行），这与手动创建的 `prompts/chat.md`（多行）不同。
- 严重级别：Medium
- 修复建议：将 `DEFAULT_CHAT_PROMPT` 常量改为多行格式与文件一致，或将 `prompts/chat.md` 改为单行格式与常量一致。推荐前者，因为多行格式可读性更好：

  ```python
  DEFAULT_CHAT_PROMPT = (
      "你是一个正在执行编码任务的 AI 助手。\n"
      "用户正在向你询问任务的进展。请根据上下文直接回答用户的问题。\n"
      "回复用自然语言，不需要 JSON 格式。简洁明了。"
  )
  ```

**[CR-002] `_generate_default()` 写入后直接返回默认值，后续加载可能缓存不一致**

- 文件：`src/maestro/manager_agent.py:153-156`
- 问题描述：当文件不存在时，`load()` 调用 `_generate_default()` 后直接 `return default_content`，没有将该值写入 `_cache`。下次再调用 `load()` 时，文件已存在，会走 mtime 检查分支读取文件内容（经过 `strip()`），而文件内容是 `default_content + "\n"`，strip 后等于 `default_content`。所以功能上正确。但如果 `default_content` 本身尾部有空白，`strip()` 会改变内容。这是一个极低概率的边界情况，但为了防御性编程，可以考虑在 `return default_content` 前填充缓存。
- 严重级别：Medium
- 修复建议：在 `_generate_default` 成功写入后，填充 `_cache`（可选，当前行为功能正确，只是防御性改进）。

**[CR-003] `do_update()` prompts 备份未验证恢复结果**

- 文件：`deploy.sh:621-637`
- 问题描述：`do_update()` 中 prompts 备份/恢复使用了 `2>/dev/null || true` 静默处理错误。如果备份或恢复失败（如磁盘空间不足），用户的自定义 prompts 可能丢失，但不会收到任何告警。
- 严重级别：Medium
- 修复建议：对备份操作的成功与否输出 `info`/`warn` 日志，让用户有感知：

  ```bash
  run_ssh "
      if [[ -d $DEPLOY_DIR/prompts ]]; then
          if cp -r $DEPLOY_DIR/prompts /tmp/_maestro_prompts_bak; then
              echo '[远程] prompts 已备份'
          else
              echo '[远程 WARN] prompts 备份失败'
          fi
      fi
  " || true
  ```

### Low

**[CR-004] `PromptLoader` 缓存使用 `str(Path(file_path))` 作为 key，路径规范化不完整**

- 文件：`src/maestro/manager_agent.py:150-151`
- 问题描述：`path_str = str(path)` 不会解析符号链接或 `../` 等相对路径引用。如果同一文件通过不同路径引用（如 `prompts/system.md` 和 `./prompts/../prompts/system.md`），会创建独立的缓存条目。实际使用中路径来自配置文件，几乎不会出现此情况。
- 严重级别：Low
- 修复建议：使用 `str(path.resolve())` 替代 `str(path)` 进行路径规范化（可选改进）。

**[CR-005] `_load_system_prompt()` 中 `_warned_prompt_conflict` 标志在热加载场景下的语义**

- 文件：`src/maestro/manager_agent.py:296-301`
- 问题描述：`_warned_prompt_conflict` 确保冲突日志只输出一次，这是正确的。但如果用户在运行时修改 config（理论上不会，因为 config 是初始化时加载的），该标志不会重置。这不是实际问题，因为 config 对象在 ManagerAgent 生命周期内不可变。记为 Low 仅供知晓。
- 严重级别：Low
- 修复建议：无需修复，当前实现正确。

**[CR-006] `deploy.sh` 中 `do_remote_quick_update()` 的变量引用未加引号**

- 文件：`deploy.sh:492-497`
- 问题描述：`cd $DEPLOY_DIR` 中 `$DEPLOY_DIR` 未加双引号。如果 DEPLOY_DIR 路径包含空格（极少见但理论可能），命令会出错。同样的情况出现在 `do_update()` 的多处 `run_ssh` 调用中。
- 严重级别：Low
- 修复建议：在 run_ssh 内的远程脚本中对变量加双引号：`cd "$DEPLOY_DIR"`。注意此问题同样存在于原 deploy.sh 的 do_status / do_clean 等函数中（既有代码），属于历史遗留风格。

### Info

**[CR-007] `PromptLoader.load()` 的 file_path 参数来自配置文件，无路径穿越风险**

- 文件：`src/maestro/manager_agent.py:139`
- 说明：file_path 参数由 `config.yaml` 配置提供（管理员控制），不接受外部用户输入。当前无需添加路径清理。

**[CR-008] `do_update()` prompts 备份使用固定 `/tmp` 路径**

- 文件：`deploy.sh:625`
- 说明：备份路径 `/tmp/_maestro_prompts_bak` 是固定名称。在多用户 VPS 上理论上可能冲突，但 Maestro 通常由单个用户部署运行，实际无风险。如需加固，可使用 `mktemp -d` 生成唯一备份路径。

---

## 代码质量亮点

1. **错误处理覆盖全面**：`PromptLoader.load()` 对 6 种异常场景（文件不存在、空文件、编码错误、mtime 不可读、权限错误、文件读取失败）均有独立处理分支，全部 fallback 到默认值。
2. **向后兼容设计严谨**：所有新增字段默认值为空字符串，空值时完整走原有逻辑路径。`_dict_to_dataclass()` 自动处理新字段的向后兼容。
3. **冲突日志去重**：`_warned_prompt_conflict` 标志避免每轮 `decide()` 都打印冲突警告，用户体验友好。
4. **测试质量高**：71 个测试用例覆盖了所有功能点、边界场景和向后兼容性。Mock 策略合理（patch `_init_client` 避免真实 LLM 调用）。
5. **deploy.sh 改造干净**：原 `do_deploy()` 完整拆分，内部逻辑不变，新增功能（quick_update、prompts 备份）独立添加，风险可控。

---

## 新增依赖检查

本次改造未引入新的外部依赖。所有使用的库（`os`、`pathlib`、`json`、`re` 等）均为 Python 标准库。

---

## 修复优先级建议

1. **[CR-001] prompts/chat.md 内容一致性**（Medium）：建议修复，确保常量与文件内容一致。修复方式二选一，推荐修改常量为多行格式。
2. **[CR-003] prompts 备份日志**（Medium）：建议修复，让用户知晓备份状态。简单改动。
3. **[CR-002] 缓存填充**（Medium）：可选改进，当前功能正确。
4. **其余 Low/Info**：可在后续迭代中处理或忽略。

---

## 下游摘要

### 整体评估
APPROVE WITH COMMENTS

### 未修复问题
#### Critical
无

#### High
无

#### Medium
- [CR-001] prompts/chat.md 文件内容与 DEFAULT_CHAT_PROMPT 常量格式不一致（单行 vs 多行）
- [CR-002] _generate_default() 写入后未填充缓存（功能正确，防御性改进建议）
- [CR-003] do_update() prompts 备份失败时无用户提示

### 修复建议
CR-001 优先修复，统一常量与文件的格式。CR-003 可选修复，改善 deploy.sh 的用户反馈。CR-002 属于防御性编程改进，可推迟。
