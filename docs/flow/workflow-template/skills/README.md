# Skills 速查手册

本目录包含所有可用的 Skill 命令。每个 Skill 是一个独立的自动化工作流，在 Claude Code 对话中通过 `/命令名` 调用。

---

## 快速选择

```
有模糊想法、需要产品定义      → /f-product
任务规模大、需要完整文档      → /f-dev
任务中等、希望少确认          → /f-quick-dev
小功能、UI 小改动             → /f-light-dev
有 Bug 需要修复               → /f-bugfix
只需要方案不需要代码          → /f-design
跑测试、补充测试、覆盖率     → /f-test
保存/查看跨对话上下文         → /f-context
查看/清理 workspace 目录      → /f-workspace
重置工作流、全新安装          → /f-clean
文档/模板/工作流文件修改      → /f-doc
上次中断的任务                → 继续做
```

---

## 命令一览

| 命令 | 用途 | 阶段 | 确认点 |
|------|------|------|--------|
| `/f-product` | 产品设计：从想法到 PRD | 3 | 3 |
| `/f-dev` | 端到端完整功能开发（TDD 驱动） | 7 | 5 |
| `/f-quick-dev` | 快速功能开发（完整流程，少确认） | 7 | 2 |
| `/f-light-dev` | 轻量功能开发（精简流程） | 4 | 2 |
| `/f-bugfix` | Bug 诊断与修复 | 4 | 1 |
| `/f-design` | 需求分析与系统设计（只出方案） | 2 | 2 |
| `/f-test` | 独立测试（运行/覆盖率/补充测试） | — | 按需 |
| `/f-context` | 跨对话上下文管理 | — | — |
| `/f-workspace` | Workspace 目录查看与清理 | — | 按需 |
| `/f-clean` | 工作流清理（删除已安装文件，保留用户数据） | — | 1 |
| `/f-doc` | 文档与模板开发（含一致性扫描） | 5 | 2 |
| `/f-init` | 工作流初始化（安装与配置） | — | 按需 |

---

## 详细说明

### `/f-product` — 产品设计

**触发词**：产品设计、定义产品、PRD

**流程**：
1. **问题定义** → 输出 `01-problem.md` → *用户确认*
2. **方案设计** → 输出 `02-solution.md` → *用户确认*
3. **功能规格** → 输出 `03-spec.md` → *用户确认*

**特点**：
- 从产品经理视角定义"做什么"和"为什么做"，不涉及技术实现
- 3 个阶段全部由 Product Designer (Opus) 执行
- 输出 MoSCoW 优先级标注的功能清单和 MVP 范围
- 产出可直接衔接 `/f-design` 进入技术设计

**Workspace**：`.claude/workspace/product-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-product 我想给服务器管理平台加一个监控面板
```

---

### `/f-design` — 需求分析与系统设计

**触发词**：分析需求、设计方案、可行性分析、技术选型

**流程**：
1. **需求分析** → 输出 `01-requirements.md` → *用户确认*
2. **系统设计** → 输出 `02-design.md` → *用户确认*

**特点**：
- 只做方案不写代码，专注于高质量的需求文档和设计方案
- 产出可直接衔接 `/f-dev` 或 `/f-light-dev` 继续开发
- 子代理：Requirements Analyst (Opus) + System Designer (Opus)

**Workspace**：`.claude/workspace/design-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-design 评估将前端状态管理从 Context 迁移到 Zustand 的方案
```

---

### `/f-dev` — 端到端完整功能开发

**触发词**：开发新功能、创建模块、完整开发流程

**流程**：
1. **需求分析** (Requirements Analyst) → *用户确认*
2. **系统设计** (System Designer) → *用户确认*
3. **TDD 测试设计** (Test Engineer) → 自动流转
4. **编码实现** (Code Engineer) → *用户确认*
5. **代码审查** (Code Reviewer) → *用户确认*
6. **集成验证** (Integration Validator) → *用户确认*
7. **文档交付** (Documentation Writer) → 自动流转

**特点**：
- TDD 驱动：先写失败的测试，再写实现代码
- 5 个确认点，每步都可以审查和调整
- 完整的文档交付（API 文档、变更日志）
- 支持中断后从任意阶段恢复

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-dev 添加用户角色权限系统，支持管理员、编辑、只读三种角色
```

---

### `/f-quick-dev` — 快速功能开发

**触发词**：快速开发、快速模式

**流程**：与 `/f-dev` 相同的 7 个阶段，但只在 2 个关键节点暂停：
- ⏸ 阶段 2（设计确认）
- ⏸ 阶段 6（验证确认）
- 其余阶段自动流转

**特点**：
- 完整流程但最少交互
- 代码审查发现 Critical/High 问题时自动返回修复
- 适合信任流程、想快速推进的场景

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-quick-dev 给列表页面添加标签筛选功能
```

---

### `/f-light-dev` — 轻量功能开发

**触发词**：小功能、简单修改、轻量开发

**流程**：
1. **分析与设计** (System Designer, 合并需求+设计) → *用户确认*
2. **编码与测试** (Code Engineer, 边写边测) → 自动流转
3. **代码审查** (Code Reviewer) → *用户确认*
4. **集成验证** (Integration Validator) → 自动流转

**特点**：
- 4 阶段精简，减少子代理调用
- 非 TDD（边写代码边写测试）
- 无文档生成阶段
- 支持升级到 `/f-dev` 完整模式

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-light-dev 给文件管理器添加批量删除按钮
```

---

### `/f-bugfix` — Bug 修复

**触发词**：修复 Bug、调试、报错、异常

**流程**：
1. **诊断分析** (System Designer, Opus) → *用户确认*
2. **修复与测试** (Code Engineer) → 自动流转
3. **代码审查** (Code Reviewer) → 自动流转
4. **集成验证** (Integration Validator) → 自动流转

**特点**：
- 只有 1 个确认点（诊断确认），后续自动流转
- 使用 Opus 模型进行诊断（强推理能力定位根因）
- 核心流程：复现 → 定位根因 → 修复 → 回归测试
- 审查重点：是否修复了根因而非症状

**Workspace**：`.claude/workspace/bugfix-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-bugfix 上传文件超时后没有显示错误提示
```

---

### `/f-test` — 独立测试

**触发词**：跑测试、运行测试、补充测试、测试覆盖率

**子命令**：

| 命令 | 用途 |
|------|------|
| `/f-test run [范围]` | 运行测试并报告结果（支持 frontend/backend/文件路径/模块名） |
| `/f-test cover [范围]` | 分析覆盖率，找出薄弱环节，可衔接补充测试 |
| `/f-test write [目标]` | 为已有代码编写测试（核心功能） |

**特点**：
- 独立于开发流程，可单独调用
- `run` 支持按范围（前端/后端/文件）和类型（unit/integration/e2e）灵活组合
- `write` 调用 Test Engineer 子代理设计测试用例，遵循项目测试规范
- `cover` 分析覆盖率后可直接衔接 `write` 补充测试
- 无 Workspace 目录，测试结果直接输出

**使用示例**：
```
/f-test run                      # 全量测试
/f-test run frontend             # 前端测试
/f-test run backend unit         # 后端单元测试
/f-test cover                    # 全量覆盖率
/f-test cover frontend           # 前端覆盖率
/f-test write src/services/api.ts  # 为指定文件补充测试
/f-test write                    # 自动选择覆盖率最低的文件补充
```

---

### `/f-context` — 上下文管理

**触发词**：保存上下文、加载上下文、查看上下文、清理对话记录

**子命令**：

| 命令 | 用途 |
|------|------|
| `/f-context save [名称]` | 保存当前对话上下文到 `.claude/context/<名称>.md` |
| `/f-context load [名称]` | 加载指定上下文到当前对话（新 session 的第一步） |
| `/f-context list` | 列出所有长期任务上下文（表格展示） |
| `/f-context remove [名称]` | 删除指定的上下文文件 |
| `/f-context clean` | 清理未被上下文引用的对话记录（transcript） |

**特点**：
- 解决跨对话的上下文丢失问题
- `load` 在新对话中显式恢复上下文，无名称时自动选择唯一上下文或让用户选
- 会话日志只追加不改写，当前状态每次覆盖
- `save` 无名称时自动建议名称
- `clean` 会保护当前对话和被引用的 transcript
- 同一对话多次 `save` 自动去重

**存储位置**：`.claude/context/<名称>.md`

**使用示例**：
```
/f-context save my-feature        # 保存上下文
/f-context load my-feature        # 新对话中加载上下文
/f-context list                   # 查看所有上下文
/f-context remove my-feature      # 删除不再需要的上下文
/f-context clean                  # 清理旧对话记录
```

---

### `/f-workspace` — Workspace 管理

**触发词**：查看 workspace、清理 workspace、workspace 列表

**子命令**：

| 命令 | 用途 |
|------|------|
| `/f-workspace list` | 列出所有 workspace，显示类型、日期、进度、大小、状态 |
| `/f-workspace clean` | 交互式清理已完成且未被引用的 workspace 目录 |

**特点**：
- 管理 `.claude/workspace/` 下的工作流产物目录
- `list` 自动识别目录类型（feature/bugfix/design）、推算进度阶段
- `clean` 保护进行中/待执行/已阻塞的任务目录，仅清理可安全删除的
- 已完成任务的 workspace 可以被清理（即使被 `_progress` 文件引用）
- `_progress-*.md` 文件和散文件不在清理范围内

**使用示例**：
```
/f-workspace list                 # 查看所有 workspace 目录
/f-workspace clean                # 交互式清理可清理的目录
```

---

### `/f-clean` — 工作流清理

**触发词**：清理工作流、重置工作流、删除工作流文件

**流程**：
1. **扫描目标** → 检测将删除和将保留的文件
2. **展示清单** → 分类展示并请用户确认 → *用户确认*
3. **执行清理** → 删除 skills/agents/hooks/settings.json
4. **验证结果** → 确认删除成功 + 保留文件完好
5. **输出建议** → 提示运行 `/f-init` 重新初始化

**特点**：
- 删除所有已安装的 Skills（含 f-clean 自身）、Agents、Hooks 和 settings.json
- 保留 f-init（初始化入口）、context（上下文数据）、workspace（工作区数据）
- 执行前需用户确认，不可撤销（可通过 `/f-init` 重新安装）
- `.claude/skills/` 不存在时自动跳过，无需清理

**使用示例**：
```
/f-clean                          # 清理所有工作流文件，准备重新初始化
```

---

### `/f-doc` — 文档与模板开发

**触发词**：修改模板、更新文档、编写 Skill、修改工作流

**流程**：
1. **需求分析**（内联） → 自动流转
2. **设计计划**（内联） → *用户确认*
3. **编写实现**（内联） → 自动流转
4. **一致性扫描** (Doc Consistency Checker) → 自动流转
5. **文档审查** (Doc Reviewer) → *用户确认*

**特点**：
- 阶段 1-3 由主协调器内联执行，不调用子代理
- 阶段 4 一致性扫描是核心差异化（7 类跨文件一致性检查）
- 一致性检查 Agent 拥有修复权限，可自动修复 CRITICAL/HIGH 问题
- 阶段 5 文档审查聚焦内容质量（清晰度、准确性），而非代码质量

**Workspace**：`.claude/workspace/doc-YYYYMMDD-$NAME/`

**使用示例**：
```
/f-doc 为工作流模板系统新增 f-doc Skill
/f-doc 更新 README 中的文件计数和命令列表
/f-doc 优化 code-reviewer Agent 的 prompt
```

---

### `/f-init` — 工作流初始化

**触发词**：初始化工作流、安装工作流

**架构**：`/f-init` 是 `scripts/init.sh` 的薄包装器。init.sh 处理 100% 的工作（探测、安装、验证），Skill 仅调用脚本并展示报告。用户也可以直接 `bash docs/flow/workflow-template/scripts/init.sh` 零 LLM 执行。

**初始化模式**（`/f-init`）：
1. 执行 `bash scripts/init.sh --verbose`（~10 秒）
2. 脚本自动：探测项目 → 解析 CLAUDE.md → 裁剪条件块 → 替换项目内容 → 安装 31 个文件 → 验证
3. 展示安装报告，如有 TODO 标记则提示补全

**升级模式**（`/f-init -u`）：
1. 执行 `bash scripts/init.sh --mode=upgrade --verbose`
2. 脚本自动：备份到 `.claude/_backup/` → 重新安装 → 输出 diff 摘要
3. 展示变更摘要，提示如有定制被覆盖可从备份恢复

**特点**：
- 脚本驱动，~10 秒完成，0 LLM token（通过 Skill 调用约 1 分钟）
- 全自动项目探测 + POSIX awk 确定性模板处理
- 支持 `--dry-run` 预览和 `--verbose` 详细日志

**使用示例**：
```
/f-init          # 通过 Skill 初始化
/f-init -u       # 通过 Skill 升级
bash docs/flow/workflow-template/scripts/init.sh              # 直接脚本执行
bash docs/flow/workflow-template/scripts/init.sh --dry-run    # 预览模式
```

---

## 通用机制

### Workspace（工作记忆）

所有开发类 Skill 都使用 `.claude/workspace/` 目录存放阶段产物。每个任务一个独立目录，互不干扰。

### 中断恢复

每个阶段完成后会自动 `git commit`。恢复时指定 Workspace 路径和阶段号：
```
从阶段 4 恢复 feature-20260225-user-auth 的开发
```

### 多任务追踪

大型任务被 `/f-design` 拆分为多个子任务时，进度记录在 `.claude/workspace/_progress-$PROJECT.md`。说"继续做"会自动读取进度文件。

### 子代理模型

- Product Designer 和 System Designer 使用 **Opus**（产品设计、架构设计和 Bug 诊断需要强推理）
- 其他子代理使用 **Sonnet**（含 Doc Consistency Checker 和 Doc Reviewer）
- 如无 Opus 权限，修改子代理文件中的 `model` 字段
