# Skills 速查手册

本目录包含所有可用的 Skill 命令。每个 Skill 是一份流程指引，在 Claude Code 对话中通过 `/命令名` 调用，由 Claude 在主对话中直接执行。

---

## 快速选择

```
有模糊想法、需要产品定义      → /f-product
需要开发功能                  → /f-dev
有 Bug 需要修复               → /f-bugfix
只需要方案不需要代码          → /f-design
测试（自动分析变更并补充）    → /f-test
保存/查看跨对话上下文         → /f-context
查看/清理 workspace 目录      → /f-workspace
重置工作流、全新安装          → /f-clean
文档/模板/工作流文件修改      → /f-doc
深度排查问题根因              → /f-analyze
收到 review 反馈需要处理      → /f-revise
上次中断的任务                → 继续做
```

---

## 命令一览

| 命令 | 用途 | 阶段 | 确认点 |
|------|------|------|--------|
| `/f-product` | 产品设计：从想法到 PRD | 3 | 3 |
| `/f-dev` | 功能开发：需求到交付 | 3 | 2 |
| `/f-bugfix` | Bug 诊断与修复 | 3 | 2 |
| `/f-design` | 需求分析与系统设计（只出方案） | 2 | 2 |
| `/f-test` | 智能测试（分析变更→评估→补充→运行→覆盖率） | 4 | 2 |
| `/f-context` | 跨对话上下文管理 | — | — |
| `/f-workspace` | Workspace 目录查看与清理 | — | 按需 |
| `/f-clean` | 工作流清理（删除已安装文件，保留用户数据） | — | 1 |
| `/f-doc` | 文档与模板开发（含一致性检查） | 3 | 2 |
| `/f-analyze` | 深度问题分析（追踪根因、实验验证） | 3 | 1 |
| `/f-revise` | Review 反馈研判与修订 | 2 | 1 |
| `/f-init` | 工作流初始化（安装与配置） | — | 按需 |

---

## 详细说明

### `/f-product` — 产品设计

**触发词**：产品设计、定义产品、PRD

**流程**：
1. **问题定义** → 归档 `01-problem.md` → *用户确认*
2. **方案设计** → 归档 `02-solution.md` → *用户确认*
3. **功能规格** → 归档 `03-spec.md` → *用户确认*

**特点**：从产品经理视角定义"做什么"和"为什么做"，输出 MoSCoW 优先级功能清单和 MVP 范围。产出可衔接 `/f-design` 进入技术设计。

**Workspace**：`.claude/workspace/product-YYYYMMDD-$NAME/`

---

### `/f-design` — 需求分析与系统设计

**触发词**：分析需求、设计方案、可行性分析、技术选型

**流程**：
1. **需求分析** → 归档 `01-requirements.md` → *用户确认*
2. **系统设计** → 归档 `02-design.md` → *用户确认*

**特点**：只做方案不写代码。产出可直接衔接 `/f-dev` 继续开发。

**Workspace**：`.claude/workspace/design-YYYYMMDD-$NAME/`

---

### `/f-dev` — 功能开发

**触发词**：开发功能、实现功能、创建模块

**流程**：
1. **需求与设计** → 归档 `01-requirements.md` + `02-design.md` → *用户确认*
2. **编码实现** → 写代码 + 写测试
3. **审查与验证** → 归档 `03-summary.md` → *用户确认*

**特点**：复杂度自适应——简单功能快速确认，复杂功能深入设计。智能入口——自动从对话上下文或上游设计中提取需求。

**Workspace**：`.claude/workspace/feature-YYYYMMDD-$NAME/`

---

### `/f-bugfix` — Bug 修复

**触发词**：修复 Bug、调试、报错、异常

**流程**：
1. **诊断分析** → 归档 `01-diagnosis.md` → *用户确认*
2. **修复实现** → 修复代码 + 回归测试
3. **审查与验证** → 归档 `02-summary.md` → *用户确认*

**特点**：核心流程——定位根因 → 修复 → 回归测试。审查重点——是否修复了根因而非症状。

**Workspace**：`.claude/workspace/bugfix-YYYYMMDD-$NAME/`

---

### `/f-test` — 智能测试

**触发词**：跑测试、运行测试、补充测试、测试覆盖率

**流程**：
1. **上下文分析** → 自动识别变更文件（对话上下文 / git diff / 最近 commit），定位相关测试
2. **测试评估与设计** → 评估现有测试完善度，设计补充用例 → *用户确认*
3. **编写测试** → 按计划实现测试用例
4. **运行与验证** → 运行测试 + 覆盖率分析 → *用户确认*

**特点**：无需参数，全自动。复杂度自适应——小变更快速评估，大变更深入分析。测试已完善时跳过编写直接运行验证。

---

### `/f-context` — 上下文管理

**触发词**：保存上下文、加载上下文、查看上下文、清理对话记录

**子命令**：

| 命令 | 用途 |
|------|------|
| `/f-context save [名称]` | 保存当前对话上下文 |
| `/f-context load [名称]` | 加载指定上下文到当前对话 |
| `/f-context list` | 列出所有长期任务上下文 |
| `/f-context remove [名称]` | 删除指定的上下文文件 |
| `/f-context clean` | 清理未被引用的对话记录 |

**存储位置**：`.claude/context/<名称>.md`

---

### `/f-workspace` — Workspace 管理

**触发词**：查看 workspace、清理 workspace、workspace 列表

**子命令**：

| 命令 | 用途 |
|------|------|
| `/f-workspace list` | 列出所有 workspace |
| `/f-workspace clean` | 交互式清理已完成的 workspace |

---

### `/f-clean` — 工作流清理

**触发词**：清理工作流、重置工作流、删除工作流文件

删除所有已安装的 Skills（包括自身和 f-init）、Hooks、Scripts 和 settings.json，保留用户数据（context、workspace）。清理后通过 `bash docs/flow/workflow-template/scripts/init.sh` 重新安装。

---

### `/f-doc` — 文档与模板开发

**触发词**：修改模板、更新文档、编写 Skill、修改工作流

**流程**：
1. **分析与计划** → 归档 `01-plan.md` → *用户确认*
2. **编写实现** → 执行文档修改
3. **一致性检查与审查** → 归档 `02-summary.md` → *用户确认*

**特点**：核心差异化是 7 类一致性检查（跨文件引用、版本号同步、README 更新等）。

**Workspace**：`.claude/workspace/doc-YYYYMMDD-$NAME/`

---

### `/f-analyze` — 深度问题分析

**触发词**：分析原因、排查问题、调查、为什么会这样

**流程**：
1. **问题定义与初步追踪** → 归档 `01-scope.md` → 自动推进
2. **深度调查与实验验证**（按需）→ 归档 `02-investigation.md`
3. **根因报告** → 归档 `03-conclusion.md` → *用户确认*

**特点**：全程不修改主分支代码、不产生 git commit/push。需要临时改代码验证时使用 worktree 隔离实验，实验完即销毁。复杂度自适应——简单问题跳过阶段 2 直接出结论。产出可衔接 `/f-bugfix` 进行修复。

**Workspace**：`.claude/workspace/analyze-YYYYMMDD-$NAME/`

---

### `/f-revise` — Review 反馈研判

**触发词**：看下这个 review、review 结果、修订代码

**流程**：
1. **研判分析** → 逐条分析 review 意见，给出同意/部分同意/不同意的独立判断 → *用户确认*
2. **实施修订** → 按确认后的修改清单逐条修改代码

**特点**：先判断再动手——对每条 review 意见独立研判，有分歧先反馈讨论，达成共识后才改代码。无 Workspace，轻量快速。

---

### `/f-init` — 工作流初始化

**触发词**：初始化工作流、安装工作流

`/f-init` 是 `scripts/init.sh` 的薄包装器。用户也可以直接 `bash docs/flow/workflow-template/scripts/init.sh` 零 LLM 执行。

- 初始化模式：`/f-init`
- 升级模式：`/f-init -u`

---

## 通用机制

### Workspace（产物归档）

所有开发类 Skill 使用 `.claude/workspace/` 目录归档阶段产物。每个任务一个独立目录，互不干扰。Workspace 是归档记录，不是上下文传递管道。

### 中断恢复

同一对话中直接继续。跨对话时 Skill 自动扫描最近的未完成 Workspace，读取已有文件推断进度。

### 多任务追踪

大型任务被 `/f-design` 拆分为多个子任务时，进度记录在 `.claude/workspace/_progress-$PROJECT.md`。说"继续做"会自动读取进度文件。
