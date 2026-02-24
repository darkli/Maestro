# 工作流模板 — 安装与使用指南

本模板为 Claude Code 项目提供完整的 **AI 辅助开发工作流**，包含 9 个 Skill 命令和 9 个专业子代理，覆盖从需求分析到文档交付的全流程。

---

## 快速开始

### 自动方式（推荐）

在已安装 Claude Code 的项目根目录执行：

```
/init-workflow
```

`/init-workflow` 会自动完成：
1. **Phase 0**：自动探测项目环境（语言、框架、构建工具、测试框架等）
2. **Phase 0.5**：如缺失 `CLAUDE.md`，自动生成并预填探测结果
3. **Phase 0.7**：验证 `CLAUDE.md` 完整性，引导补全缺失部分
4. **Phase 1**：扫描 `CLAUDE.md`，推断 Capabilities（能力标签），写入/更新 Capabilities 节到 CLAUDE.md（紧跟 Project Overview 之后），推断隐式派生标签
5. **Phase 2**：验证 CLAUDE.md 完整性，确认 Capabilities 节已存在且标签值合理
6. **Phase 3-5**：两遍处理生成定制化文件（Pass 1: IF 条件裁剪 → Pass 2: PROJECT-SPECIFIC 替换）、验证、报告

### 手动方式

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

手动安装完成后，编辑 `CLAUDE.md` 中的占位符（`$PROJECT_NAME` 等），参考 `claude-md-contract.md` 了解每个段落的详细要求。

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
│   ├── feature-dev/
│   │   └── SKILL.md                   # 端到端完整功能开发（7 阶段）
│   ├── quick-dev/
│   │   └── SKILL.md                   # 快速功能开发（7 阶段，2 次确认）
│   ├── light-dev/
│   │   └── SKILL.md                   # 轻量功能开发（4 阶段精简）
│   ├── fix-bug/
│   │   └── SKILL.md                   # Bug 修复（4 阶段）
│   ├── design/
│   │   └── SKILL.md                   # 需求分析与系统设计（只做方案）
│   ├── context/
│   │   └── SKILL.md                   # 跨对话上下文管理（save/load/list/remove/clean）
│   ├── test/
│   │   └── SKILL.md                   # 独立测试（run/cover/write）
│   ├── workspace/
│   │   └── SKILL.md                   # Workspace 目录查看与清理（list/clean）
│   ├── doc-dev/
│   │   └── SKILL.md                   # 文档与模板开发（5 阶段，含一致性扫描）
│   └── init-workflow/
│       └── SKILL.md                   # 工作流初始化（安装脚本）
│
├── agents/                            # 子代理定义
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
└── settings.json                      # Claude Code 工作流配置
```

---

## Skill 命令

安装完成后，在 Claude Code 对话中直接使用以下命令：

| 命令 | 适用场景 | 阶段数 | 确认次数 |
|------|----------|--------|----------|
| `/feature-dev` | 完整功能模块开发，注重质量和文档 | 7 阶段 | 5 次 |
| `/quick-dev` | 中等规模功能，减少交互 | 7 阶段 | 2 次 |
| `/light-dev` | 小功能、UI 增强、简单修改 | 4 阶段 | 2 次 |
| `/fix-bug` | Bug 修复、调试、异常排查 | 4 阶段 | 1 次 |
| `/design` | 前期规划、技术选型、可行性分析 | 2 阶段 | 2 次 |
| `/test` | 独立测试（运行/覆盖率/补充测试） | — | 按需 |
| `/context` | 跨对话上下文管理（save/load/list/remove/clean） | — | — |
| `/workspace` | Workspace 目录查看与清理（list/clean） | — | 按需 |
| `/doc-dev` | 文档/模板/prompt 编写与修改 | 5 阶段 | 2 次 |

### 使用示例

```
# 开发完整功能模块
/feature-dev 添加用户角色权限系统，支持管理员、编辑、只读三种角色

# 快速开发（减少确认）
/quick-dev 给列表页面添加标签筛选功能

# 小功能修改
/light-dev 给文件管理器添加批量删除按钮

# 修复 Bug
/fix-bug 上传文件超时后没有显示错误提示

# 只做方案设计
/design 评估将前端状态管理从 Context 迁移到 Zustand 的方案

# 运行测试
/test run                      # 全量测试
/test run frontend             # 前端测试
/test run backend unit         # 后端单元测试

# 分析覆盖率
/test cover frontend

# 补充测试
/test write src/services/api.ts

# 保存当前对话上下文
/context save my-task-name

# 新对话中加载之前的上下文
/context load my-task-name

# 查看所有长期任务上下文
/context list

# 删除不再需要的上下文
/context remove my-task-name

# 清理未被引用的旧对话记录
/context clean

# 查看所有 workspace 目录
/workspace list

# 交互式清理已完成的 workspace
/workspace clean

# 继续上次未完成的任务
继续做
```

### 选择哪个命令

```
任务规模大、需要完整文档      → /feature-dev
任务中等、希望少确认          → /quick-dev
小功能、UI 小改动             → /light-dev
有 Bug 需要修复               → /fix-bug
只需要方案不需要代码          → /design
跑测试、补充测试、覆盖率     → /test
保存/查看跨对话上下文         → /context
查看/清理 workspace 目录      → /workspace
文档/模板/工作流文件修改      → /doc-dev
上次中断的任务                → 继续做
```

---

## 子代理说明

子代理是 Skill 流程中被协调调用的专业模块，每个代理负责特定阶段：

| 子代理 | 文件 | 专长 | 被哪些 Skill 使用 |
|--------|------|------|-------------------|
| Requirements Analyst | `requirements-analyst.md` | 需求澄清、验收标准定义、影响范围评估 | feature-dev、design |
| System Designer | `system-designer.md` | 架构设计、接口定义、数据模型设计、技术选型 | feature-dev、quick-dev、light-dev、fix-bug（诊断）、design |
| Test Engineer | `test-engineer.md` | TDD 测试用例设计、测试骨架生成、Mock 数据创建 | feature-dev、quick-dev、test |
| Code Engineer | `code-engineer.md` | 全栈代码实现、i18n 更新、测试通过验证 | feature-dev、quick-dev、light-dev、fix-bug |
| Code Reviewer | `code-reviewer.md` | 代码质量审查、安全审计、需求覆盖核对 | feature-dev、quick-dev、light-dev、fix-bug |
| Integration Validator | `integration-validator.md` | 构建验证、测试运行、覆盖率检查、API 契约验证 | feature-dev、quick-dev、light-dev、fix-bug |
| Documentation Writer | `documentation-writer.md` | API 文档、用户指南、变更日志更新 | feature-dev、quick-dev |
| Doc Consistency Checker | `doc-consistency-checker.md` | 跨文件一致性检查、自动修复 CRITICAL/HIGH 问题 | doc-dev |
| Doc Reviewer | `doc-reviewer.md` | 文档质量审查、计划符合度核对、格式一致性检查 | doc-dev |

---

## 命名约束（重要）

以下名称是**系统固定标识符**，在任何项目中都**不可修改**。它们在 Skill、Agent、Workspace 文件之间交叉引用，改动任何一个都会导致工作流断裂。

- **Skill 命令名**：`feature-dev`、`quick-dev`、`light-dev`、`fix-bug`、`design`、`test`、`context`、`workspace`、`doc-dev` — 目录名和 SKILL.md 中的 `name:` 字段必须完全一致
- **Agent 文件名**：`requirements-analyst.md`、`system-designer.md`、`test-engineer.md`、`code-engineer.md`、`code-reviewer.md`、`integration-validator.md`、`documentation-writer.md`、`doc-consistency-checker.md`、`doc-reviewer.md` — SKILL 中通过文件名引用这些 Agent
- **Workspace 文件名（代码开发类）**：`00-input.md` 到 `07-delivery.md` — 每个 Agent 的输入/输出契约依赖这些固定文件名
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
9. **Capabilities**（自动生成）— 能力标签表，由 `/init-workflow` Phase 1 自动推断写入

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

**注意**：修改子代理文件后，测试确保 Skill 流程仍然正常运行。

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

AND 逻辑使用嵌套（处理规则：外层条件为假时内层整体移除；外层条件为真时递归处理内层）：
```markdown
<!-- IF:frontend -->
<!-- IF:design-system -->
检查是否使用了项目 Design Token。
<!-- ENDIF:design-system -->
<!-- ENDIF:frontend -->
```

### 替换标记（PROJECT-SPECIFIC）

标记需要替换为项目具体值的内容块：

```markdown
<!-- PROJECT-SPECIFIC: 测试命令 -->
npm test
<!-- /PROJECT-SPECIFIC -->
```

`/init-workflow` 在初始化时自动处理这两种标记（Pass 1: 条件块裁剪 → Pass 2: PROJECT-SPECIFIC 替换）。

### 搜索标记

```bash
# 查找模板中的所有条件块
grep -r "IF:" docs/flow/workflow-template/

# 查找模板中的所有需替换标记
grep -r "PROJECT-SPECIFIC" docs/flow/workflow-template/
```

---

## 常见问题

**Q: Workspace 文件越来越多怎么办？**

使用 `/workspace clean` 交互式清理已完成的 workspace 目录。该命令会自动保护进行中的任务目录，仅清理可安全删除的。也可以用 `/workspace list` 先查看所有 workspace 的状态。

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

**Q: 什么时候用 /design 而不是 /feature-dev？**

如果你还不确定是否要做这个功能，或者功能很复杂需要先看方案再决定，用 `/design`。`/design` 只产出文档不写代码，完成后可以直接衔接 `/feature-dev` 或 `/light-dev` 从后续阶段继续。

**Q: /light-dev 能升级到 /feature-dev 吗？**

可以。在 `/light-dev` 阶段 1 确认时选择"升级到完整模式"，已生成的 `01-requirements.md` 和 `02-design.md` 会被保留，然后执行：
```
/feature-dev 从阶段 3 继续，Workspace: .claude/workspace/feature-20260221-xxx
```

**Q: /doc-dev 和直接修改文件有什么区别？**

`/doc-dev` 提供自动化的一致性扫描（阶段 4），能检测跨文件引用断裂、版本号不同步、README 未更新等问题。如果修改范围仅限单个文件且无跨文件引用，直接修改即可。如果修改涉及多个文件或有复杂的交叉引用关系，建议使用 `/doc-dev`。

**Q: 子代理的模型选择是否重要？**

是的。System Designer（架构设计）使用 Opus 模型，因为架构和 Bug 诊断需要强推理能力。其他子代理使用 Sonnet。如果你的账号没有 Opus 访问权限，修改子代理文件中的 `model` 字段改为 Sonnet。

**Q: 如何让子代理输出英文文档？**

修改 `CLAUDE.md` 的 `Language` 部分，将语言改为 English。所有子代理都会读取此配置。
