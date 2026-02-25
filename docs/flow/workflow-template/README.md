# 工作流模板 — 安装与使用指南

本模板为 Claude Code 项目提供完整的 **AI 辅助开发工作流**，包含 12 个 Skill 命令和 10 个专业子代理，覆盖从产品设计到文档交付的全流程。

---

## 快速开始

### 方式 A：脚本直接执行（推荐，零 LLM token）

```bash
bash docs/flow/workflow-template/scripts/init.sh
```

脚本在 ~10 秒内自动完成：探测项目技术栈 → 解析 CLAUDE.md → 裁剪模板条件块 → 替换项目特定内容 → 安装 31 个文件 → 验证 → 报告。

如果项目没有 CLAUDE.md，脚本会自动生成（含 TODO 标记待手动补全）。

可选参数：`--verbose`（详细日志）、`--dry-run`（仅预览不执行）、`--mode=upgrade`（升级模式）。

### 方式 B：通过 Skill 执行

```
/f-init
```

调用同一个脚本，额外提供：报告格式化、TODO 补全提示、异常修复建议。

### 方式 C：手动安装

```bash
# 复制 skills 和 agents 到项目
cp -r workflow-template/skills/* your-project/.claude/skills/
cp -r workflow-template/agents/* your-project/.claude/agents/
cp -r workflow-template/hooks/* your-project/.claude/hooks/

# 创建工作区目录
mkdir -p your-project/.claude/{workspace,context}

# 在项目根目录创建 CLAUDE.md
cp workflow-template/CLAUDE.md.template your-project/CLAUDE.md
# 然后根据项目实际情况填写占位符，参考 claude-md-contract.md
```

手动安装不执行条件裁剪和 PS 替换，需手动编辑模板中的 IF/PS 标记。

---

## 文件结构

```
workflow-template/
├── README.md                          # 本文件：安装与使用指南
├── CLAUDE.md.template                 # CLAUDE.md 模板（可直接复制使用）
├── claude-md-contract.md              # CLAUDE.md 接口契约文档
│
├── skills/                            # Skill 命令定义
│   ├── README.md                      # Skills 速查手册
│   ├── f-product/
│   │   └── SKILL.md                   # 产品设计：从想法到 PRD（3 阶段）
│   ├── f-dev/
│   │   └── SKILL.md                   # 端到端完整功能开发（7 阶段）
│   ├── f-quick-dev/
│   │   └── SKILL.md                   # 快速功能开发（7 阶段，2 次确认）
│   ├── f-light-dev/
│   │   └── SKILL.md                   # 轻量功能开发（4 阶段精简）
│   ├── f-bugfix/
│   │   └── SKILL.md                   # Bug 修复（4 阶段）
│   ├── f-design/
│   │   └── SKILL.md                   # 需求分析与系统设计（只做方案）
│   ├── f-context/
│   │   └── SKILL.md                   # 跨对话上下文管理（save/load/list/remove/clean）
│   ├── f-test/
│   │   └── SKILL.md                   # 独立测试（run/cover/write）
│   ├── f-workspace/
│   │   └── SKILL.md                   # Workspace 目录查看与清理（list/clean）
│   ├── f-clean/
│   │   └── SKILL.md                   # 工作流清理（删除已安装文件，保留用户数据）
│   ├── f-doc/
│   │   └── SKILL.md                   # 文档与模板开发（5 阶段，含一致性扫描）
│   └── f-init/
│       └── SKILL.md                   # 工作流初始化（安装脚本）
│
├── agents/                            # 子代理定义
│   ├── product-designer.md            # 产品设计师
│   ├── requirements-analyst.md        # 需求分析师
│   ├── system-designer.md             # 系统架构师
│   ├── test-engineer.md               # 测试工程师
│   ├── code-engineer.md               # 编码工程师
│   ├── code-reviewer.md               # 代码审查员
│   ├── integration-validator.md       # 集成验证员
│   ├── documentation-writer.md        # 文档撰写员
│   ├── doc-consistency-checker.md     # 文档一致性检查员
│   └── doc-reviewer.md               # 文档审查员
│
├── hooks/                             # Git Hook 脚本
│   ├── README.md                      # Hook 适配指南（本目录）
│   ├── protect-files.sh               # 保护关键文件不被误删
│   ├── lint-check.sh                  # Lint 检查
│   ├── auto-format.sh                 # 自动格式化
│   ├── run-related-tests.sh           # 运行相关测试
│   ├── check-coverage.sh              # 覆盖率检查
│   ├── notify-completion.sh           # 操作完成通知
│   ├── generate-report.sh             # 生成开发报告
│   └── git-guard.sh                   # Git 写操作拦截守卫
│
├── scripts/                           # 自动化脚本
│   ├── init.sh                        # 主初始化脚本（探测+安装+验证，~10秒）
│   ├── process_if.awk                 # IF/ENDIF 条件块处理器（POSIX awk）
│   └── process_ps.awk                 # PROJECT-SPECIFIC 替换处理器（POSIX awk）
│
└── settings.json                      # Claude Code 工作流配置
```

---

## Skill 命令

安装完成后，在 Claude Code 对话中直接使用以下命令：

| 命令 | 适用场景 | 阶段数 | 确认次数 |
|------|----------|--------|----------|
| `/f-product` | 从模糊想法到 PRD，产品定义 | 3 阶段 | 3 次 |
| `/f-dev` | 完整功能模块开发，注重质量和文档 | 7 阶段 | 5 次 |
| `/f-quick-dev` | 中等规模功能，减少交互 | 7 阶段 | 2 次 |
| `/f-light-dev` | 小功能、UI 增强、简单修改 | 4 阶段 | 2 次 |
| `/f-bugfix` | Bug 修复、调试、异常排查 | 4 阶段 | 1 次 |
| `/f-design` | 前期规划、技术选型、可行性分析 | 2 阶段 | 2 次 |
| `/f-test` | 独立测试（运行/覆盖率/补充测试） | — | 按需 |
| `/f-context` | 跨对话上下文管理（save/load/list/remove/clean） | — | — |
| `/f-workspace` | Workspace 目录查看与清理（list/clean） | — | 按需 |
| `/f-clean` | 工作流清理，删除已安装文件，保留用户数据 | — | 1 次 |
| `/f-doc` | 文档/模板/prompt 编写与修改 | 5 阶段 | 2 次 |

> `/f-init` 是安装脚本本身，不在上表中。安装完成后通过 `/f-init -u` 升级已有工作流。

### 使用示例

```
# 从模糊想法开始产品设计
/f-product 我想给服务器管理平台加一个监控面板

# 开发完整功能模块
/f-dev 添加用户角色权限系统，支持管理员、编辑、只读三种角色

# 快速开发（减少确认）
/f-quick-dev 给列表页面添加标签筛选功能

# 小功能修改
/f-light-dev 给文件管理器添加批量删除按钮

# 修复 Bug
/f-bugfix 上传文件超时后没有显示错误提示

# 只做方案设计
/f-design 评估将前端状态管理从 Context 迁移到 Zustand 的方案

# 运行测试
/f-test run                      # 全量测试
/f-test run frontend             # 前端测试
/f-test run backend unit         # 后端单元测试

# 分析覆盖率
/f-test cover frontend

# 补充测试
/f-test write src/services/api.ts

# 保存当前对话上下文
/f-context save my-task-name

# 新对话中加载之前的上下文
/f-context load my-task-name

# 查看所有长期任务上下文
/f-context list

# 删除不再需要的上下文
/f-context remove my-task-name

# 清理未被引用的旧对话记录
/f-context clean

# 查看所有 workspace 目录
/f-workspace list

# 交互式清理已完成的 workspace
/f-workspace clean

# 清理工作流文件（准备重新初始化）
/f-clean

# 继续上次未完成的任务
继续做
```

### 选择哪个命令

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

## 子代理说明

子代理是 Skill 流程中被协调调用的专业模块，每个代理负责特定阶段：

| 子代理 | 文件 | 专长 | 被哪些 Skill 使用 |
|--------|------|------|-------------------|
| Product Designer | `product-designer.md` | 问题定义、方案设计、功能规格（PRD） | f-product |
| Requirements Analyst | `requirements-analyst.md` | 需求澄清、验收标准定义、影响范围评估 | f-dev、f-design |
| System Designer | `system-designer.md` | 架构设计、接口定义、数据模型设计、技术选型 | f-dev、f-quick-dev、f-light-dev、f-bugfix（诊断）、f-design |
| Test Engineer | `test-engineer.md` | TDD 测试用例设计、测试骨架生成、Mock 数据创建 | f-dev、f-quick-dev、f-test |
| Code Engineer | `code-engineer.md` | 全栈代码实现、i18n 更新、测试通过验证 | f-dev、f-quick-dev、f-light-dev、f-bugfix |
| Code Reviewer | `code-reviewer.md` | 代码质量审查、安全审计、需求覆盖核对 | f-dev、f-quick-dev、f-light-dev、f-bugfix |
| Integration Validator | `integration-validator.md` | 构建验证、测试运行、覆盖率检查、API 契约验证 | f-dev、f-quick-dev、f-light-dev、f-bugfix |
| Documentation Writer | `documentation-writer.md` | API 文档、用户指南、变更日志更新 | f-dev、f-quick-dev |
| Doc Consistency Checker | `doc-consistency-checker.md` | 跨文件一致性检查、自动修复 CRITICAL/HIGH 问题 | f-doc |
| Doc Reviewer | `doc-reviewer.md` | 文档质量审查、计划符合度核对、格式一致性检查 | f-doc |

---

## 命名约束（重要）

以下名称是**系统固定标识符**，在任何项目中都**不可修改**。它们在 Skill、Agent、Workspace 文件之间交叉引用，改动任何一个都会导致工作流断裂。

- **Skill 命令名**：`f-product`、`f-dev`、`f-quick-dev`、`f-light-dev`、`f-bugfix`、`f-design`、`f-test`、`f-context`、`f-workspace`、`f-doc`、`f-clean` — 目录名和 SKILL.md 中的 `name:` 字段必须完全一致
- **Agent 文件名**：`product-designer.md`、`requirements-analyst.md`、`system-designer.md`、`test-engineer.md`、`code-engineer.md`、`code-reviewer.md`、`integration-validator.md`、`documentation-writer.md`、`doc-consistency-checker.md`、`doc-reviewer.md` — SKILL 中通过文件名引用这些 Agent
- **Workspace 文件名（代码开发类）**：`00-input.md` 到 `07-delivery.md` — 每个 Agent 的输入/输出契约依赖这些固定文件名
- **Workspace 文件名（产品设计类）**：`00-input.md`、`00-context.md`、`01-problem.md`、`02-solution.md`、`03-spec.md`
- **Workspace 文件名（文档开发类）**：`00-input.md`、`01-analysis.md`、`02-plan.md`、`03-changes.md`、`04-consistency.md`、`05-review.md`

**初始化时只定制文件内容（PROJECT-SPECIFIC 标记块），不改文件名和目录名。**

---

## 自定义指南

### 必须做：填写 CLAUDE.md

工作流所有子代理都会读取 `CLAUDE.md`。新项目必须填写完整的 `CLAUDE.md`，详细格式要求见 `claude-md-contract.md`。

**最低必填项**（8 项用户填写 + 1 项自动生成，缺少任何一项会影响子代理输出质量）：

1. **Project Overview** — 项目描述和技术栈
2. **Build Commands** — 构建和启动命令
3. **Testing** — 测试框架和命令
4. **Architecture** — 系统架构和文件组织
5. **Code Style** — 代码风格规范
6. **Adding New Features** — 新功能开发步骤
7. **Commit Style** — 提交消息格式
8. **Language** — 文档语言规范
9. **Capabilities**（自动生成）— 能力标签表，由 `/f-init` 自动推断并写入

### 可选：调整 Git Hook

`hooks/` 目录中的脚本提供代码保护和自动化检查。根据项目情况调整后，安装到 `.git/hooks/`：

```bash
# 安装所有 hook
cp .claude/hooks/*.sh .git/hooks/
chmod +x .git/hooks/*.sh
```

具体的适配方法见 `hooks/README.md`。

### 可选：修改子代理行为

每个子代理文件（`agents/` 目录）都是独立的 Markdown 文件，可以修改以适配项目需求：

- 调整子代理的输出格式（修改 Workspace 文件模板）
- 添加项目特定的检查项（如特定的安全规范）
- 修改覆盖率要求（默认 80%）

**注意**：修改子代理文件后，测试确保 f-dev/f-quick-dev 等 Skill 流程仍然正常运行。

---

## 条件块语法

模板文件中使用两种标记实现项目适配：

### 条件块（IF/ENDIF）

根据 CLAUDE.md Capabilities 节的能力标签值，自动包含或排除模板内容：

```markdown
<!-- IF:i18n -->
此部分仅在项目启用 i18n 时保留。
<!-- ENDIF:i18n -->

<!-- IF:NOT:testing -->
此部分仅在项目未配置测试框架时保留。
<!-- ENDIF:NOT:testing -->
```

AND 逻辑使用嵌套（不支持原生 AND/OR 操作符）：
```markdown
<!-- IF:frontend -->
<!-- IF:design-system -->
检查是否使用了项目 Design Token。
<!-- ENDIF:design-system -->
<!-- ENDIF:frontend -->
```
处理规则：外层条件为假时，内层整体被移除；外层条件为真时，递归处理内层。

> **注意**：不支持 OR 逻辑。如需"任一条件成立"的效果，可在需要的每个条件块内分别放置相同内容。

### 替换标记（PROJECT-SPECIFIC）

标记需要替换为项目具体值的内容块：

```markdown
<!-- PROJECT-SPECIFIC: 测试命令 -->
npm test
<!-- /PROJECT-SPECIFIC -->
```

`/f-init` 在初始化时自动处理这两种标记（Pass 1: 条件块裁剪 → Pass 2: PROJECT-SPECIFIC 替换）。

### 搜索标记

```bash
# 查找模板中的所有条件块
grep -r "IF:" docs/flow/workflow-template/

# 查找模板中的所有需替换标记
grep -r "PROJECT-SPECIFIC" docs/flow/workflow-template/
```

> **默认行为**：如果 CLAUDE.md 中不存在 Capabilities 节，或某个标签在 Capabilities 表中不存在，则该标签值默认为 `false`（安全默认值）。

---

## 常见问题

**Q: Workspace 文件越来越多怎么办？**

使用 `/f-workspace clean` 交互式清理已完成的 workspace 目录。该命令会自动保护进行中的任务目录，仅清理可安全删除的。也可以用 `/f-workspace list` 先查看所有 workspace 的状态。

其他建议：
1. 在 `.gitignore` 中添加 `.claude/workspace/` 避免进入版本库
2. 保留最近 5-10 个 Workspace 作为参考

**Q: 中途中断了怎么恢复？**

每个阶段完成后都会执行 `git commit` 并写入 Workspace 文件。恢复时：
```
从阶段 4 恢复 feature-20260225-user-auth 的开发
```
Skill 会读取已有的 Workspace 文件（不依赖对话历史），从指定阶段继续。

**Q: 多个功能同时开发会冲突吗？**

不会。每个功能有独立的 Workspace 目录（如 `feature-20260221-tags/`、`feature-20260222-auth/`），互不干扰。但建议一次只开发一个功能，避免 git 分支冲突。

**Q: 什么时候用 /f-product 而不是 /f-design？**

如果你只有一个模糊想法，还不清楚具体要做什么功能、给谁用、解决什么问题，用 `/f-product`。它会帮你从产品经理视角理清问题、设计方案、划定功能范围，输出 PRD。完成后可以衔接 `/f-design` 进入技术设计。如果你已经很清楚要做什么（有明确的功能需求），直接用 `/f-design` 即可。

**Q: 什么时候用 /f-design 而不是 /f-dev？**

如果你还不确定是否要做这个功能，或者功能很复杂需要先看方案再决定，用 `/f-design`。`/f-design` 只产出文档不写代码，完成后可以直接衔接 `/f-dev` 或 `/f-light-dev` 从后续阶段继续。

**Q: /f-light-dev 能升级到 /f-dev 吗？**

可以。在 `/f-light-dev` 阶段 1 确认时选择"升级到完整模式"，已生成的 `01-requirements.md` 和 `02-design.md` 会被保留，然后执行：
```
/f-dev 从阶段 3 继续，Workspace: .claude/workspace/feature-20260221-xxx
```

**Q: /f-doc 和直接修改文件有什么区别？**

`/f-doc` 提供自动化的一致性扫描（阶段 4），能检测跨文件引用断裂、版本号不同步、README 未更新等问题。如果修改范围仅限单个文件且无跨文件引用，直接修改即可。如果修改涉及多个文件或有复杂的交叉引用关系，建议使用 `/f-doc`。

**Q: 子代理的模型选择是否重要？**

是的。Product Designer（产品设计）和 System Designer（架构设计）使用 Opus 模型，因为产品设计、架构设计和 Bug 诊断需要强推理能力。其他子代理使用 Sonnet。如果你的账号没有 Opus 访问权限，修改子代理文件中的 `model` 字段改为 Sonnet。

**Q: 如何重置工作流？**

使用 `/f-clean` 清理所有已安装的工作流文件（Skills、Agents、Hooks、settings.json），然后重新运行 `/f-init` 全新初始化。`/f-clean` 会保留 f-init 初始化工具、context 上下文数据和 workspace 工作区数据，只删除工作流安装文件。

```
/f-clean         # 清理工作流文件
/f-init          # 重新初始化
```

**Q: 如何让子代理输出英文文档？**

修改 `CLAUDE.md` 的 `Language` 部分，将语言改为 English。所有子代理都会读取此配置。
