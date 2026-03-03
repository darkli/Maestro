# 工作流模板 — 安装与使用指南

本模板为 Claude Code 项目提供 **AI 辅助开发工作流**，包含 10 个 Skill 命令，覆盖从产品设计到功能交付的全流程。每个 Skill 是一份流程指引——定义阶段、质量门禁和确认点，由 Claude 在主对话中直接执行，充分利用 Claude Code 的原生能力和对话上下文连续性。

---

## 快速开始

### 方式 A：脚本直接执行（推荐，零 LLM token）

```bash
bash docs/flow/workflow-template/scripts/init.sh
```

脚本在 ~10 秒内自动完成：探测项目技术栈 → 解析 CLAUDE.md → 裁剪模板条件块 → 替换项目特定内容 → 安装文件 → 验证 → 报告。

如果项目没有 CLAUDE.md，脚本会自动生成（含 TODO 标记待手动补全）。

可选参数：`--verbose`（详细日志）、`--dry-run`（仅预览不执行）、`--mode=upgrade`（升级模式）。

### 方式 B：通过 Skill 执行

```
/f-init
```

调用同一个脚本，额外提供：报告格式化、TODO 补全提示、异常修复建议。

### 方式 C：手动安装

```bash
# 复制 skills、hooks、scripts 到项目
cp -r workflow-template/skills/* your-project/.claude/skills/
cp -r workflow-template/hooks/* your-project/.claude/hooks/
mkdir -p your-project/.claude/scripts
cp workflow-template/scripts/*.sh workflow-template/scripts/*.awk your-project/.claude/scripts/

# 复制配置文件
cp workflow-template/settings.json your-project/.claude/settings.json

# 创建工作区目录
mkdir -p your-project/.claude/{workspace,context}

# 设置可执行权限
chmod +x your-project/.claude/hooks/*.sh
chmod +x your-project/.claude/scripts/*.sh

# 在项目根目录创建 CLAUDE.md
cp workflow-template/CLAUDE.md.template your-project/CLAUDE.md
# 然后根据项目实际情况填写占位符，参考 claude-md-contract.md
```

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
│   │   └── SKILL.md                   # 功能开发（3 阶段）
│   ├── f-bugfix/
│   │   └── SKILL.md                   # Bug 修复（3 阶段）
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
│   │   └── SKILL.md                   # 文档与模板开发（3 阶段，含一致性检查）
│   └── f-init/
│       └── SKILL.md                   # 工作流初始化（安装脚本）
│
├── hooks/                             # Hook 脚本（6 个）
│   ├── README.md                      # Hook 适配指南（本目录）
│   ├── protect-files.sh               # 保护关键文件不被误删
│   ├── auto-format.sh                 # 自动格式化
│   ├── run-related-tests.sh           # 运行相关测试
│   ├── notify-completion.sh           # 操作完成通知
│   ├── generate-report.sh             # 生成开发报告
│   └── git-guard.sh                   # Git 写操作拦截守卫
│
├── scripts/                           # 自动化脚本
│   ├── init.sh                        # 主初始化脚本（探测+安装+验证，~10秒）
│   ├── common.sh                      # 公共函数库（日志、Markdown 解析、Capabilities 查询）
│   ├── context.sh                     # 上下文管理脚本（f-context 运行时依赖）
│   ├── clean.sh                       # 工作流清理脚本（f-clean 运行时依赖）
│   ├── workspace.sh                   # Workspace 管理脚本（f-workspace 运行时依赖）
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
| `/f-dev` | 功能开发，需求到交付 | 3 阶段 | 2 次 |
| `/f-bugfix` | Bug 修复、调试、异常排查 | 3 阶段 | 2 次 |
| `/f-design` | 前期规划、技术选型、可行性分析 | 2 阶段 | 2 次 |
| `/f-test` | 独立测试（运行/覆盖率/补充测试） | — | 按需 |
| `/f-context` | 跨对话上下文管理（save/load/list/remove/clean） | — | — |
| `/f-workspace` | Workspace 目录查看与清理（list/clean） | — | 按需 |
| `/f-clean` | 工作流清理，删除已安装文件，保留用户数据 | — | 1 次 |
| `/f-doc` | 文档/模板/prompt 编写与修改 | 3 阶段 | 2 次 |

> `/f-init` 是安装脚本本身，不在上表中。安装完成后通过 `/f-init -u` 升级已有工作流。

### 使用示例

```
# 从模糊想法开始产品设计
/f-product 我想给服务器管理平台加一个监控面板

# 开发功能
/f-dev 添加用户角色权限系统，支持管理员、编辑、只读三种角色

# 修复 Bug
/f-bugfix 上传文件超时后没有显示错误提示

# 只做方案设计
/f-design 评估将前端状态管理从 Context 迁移到 Zustand 的方案

# 运行测试
/f-test run                      # 全量测试
/f-test run frontend             # 前端测试

# 保存当前对话上下文
/f-context save my-task-name

# 继续上次未完成的任务
继续做
```

### 选择哪个命令

```
有模糊想法、需要产品定义      → /f-product
需要开发功能                  → /f-dev
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

## 设计理念

每个 Skill 是一份**流程指引**，不是自动化框架。Skill 定义"经过哪些阶段、在哪里确认、质量门禁是什么"，由 Claude 在主对话中直接执行，充分利用：

- **Claude Code 的原生能力**：读代码、设计方案、写代码、跑测试、审查代码
- **对话上下文的连续性**：不需要通过文件传递上下文，对话中自然记住
- **CLAUDE.md 的项目约束**：i18n、design system、测试规范等项目特定信息

Skill 只叠加 Claude 原生不具备的：阶段定义、确认点、质量门禁、Workspace 归档。

---

## 命名约束（重要）

以下名称是**系统固定标识符**，在任何项目中都**不可修改**：

- **Skill 命令名**：`f-product`、`f-dev`、`f-bugfix`、`f-design`、`f-test`、`f-context`、`f-workspace`、`f-doc`、`f-clean`、`f-init` — 目录名和 SKILL.md 中的 `name:` 字段必须完全一致
- **Workspace 目录前缀**：`feature-`、`bugfix-`、`design-`、`product-`、`doc-` — Skill 通过前缀识别类型

---

## 自定义指南

### 必须做：填写 CLAUDE.md

工作流的所有 Skill 都依赖 `CLAUDE.md` 提供项目上下文。新项目必须填写完整的 `CLAUDE.md`，详细格式要求见 `claude-md-contract.md`。

**最低必填项**：

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

`hooks/` 目录中的脚本提供代码保护和自动化检查。根据项目情况调整后，安装到 `.git/hooks/`。具体的适配方法见 `hooks/README.md`。

---

## 条件块语法

模板文件中使用两种标记实现项目适配：

### 条件块（IF/ENDIF）

根据 CLAUDE.md Capabilities 节的能力标签值，自动包含或排除模板内容：

```markdown
<!-- IF:i18n -->
此部分仅在项目启用 i18n 时保留。
<!-- ENDIF:i18n -->
```

### 替换标记（PROJECT-SPECIFIC）

标记需要替换为项目具体值的内容块：

```markdown
<!-- PROJECT-SPECIFIC: 测试命令 -->
npm test
<!-- /PROJECT-SPECIFIC -->
```

`/f-init` 在初始化时自动处理这两种标记（Pass 1: 条件块裁剪 → Pass 2: PROJECT-SPECIFIC 替换）。

---

## 常见问题

**Q: Workspace 文件越来越多怎么办？**

使用 `/f-workspace clean` 交互式清理已完成的 workspace 目录。也可以用 `/f-workspace list` 先查看状态。建议在 `.gitignore` 中添加 `.claude/workspace/`。

**Q: 中途中断了怎么恢复？**

同一对话中直接继续。跨对话时，Skill 会自动扫描最近的未完成 Workspace 目录，读取已有文件推断进度，向用户确认后从中断点继续。

**Q: 什么时候用 /f-product 而不是 /f-design？**

如果你只有一个模糊想法，还不清楚具体要做什么功能，用 `/f-product`。如果你已经很清楚要做什么（有明确的功能需求），直接用 `/f-design` 即可。

**Q: 什么时候用 /f-design 而不是 /f-dev？**

如果你还不确定是否要做这个功能，或者功能很复杂需要先看方案再决定，用 `/f-design`。`/f-design` 只产出文档不写代码，完成后可以直接衔接 `/f-dev`。

**Q: /f-doc 和直接修改文件有什么区别？**

`/f-doc` 提供一致性检查（7 类跨文件一致性规则），能检测引用断裂、版本号不同步等问题。单文件修改直接改即可，多文件修改建议用 `/f-doc`。

**Q: 如何重置工作流？**

```
/f-clean         # 清理工作流文件
/f-init          # 重新初始化
```
