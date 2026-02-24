---
name: light-dev
description: 轻量功能开发：4 阶段精简流程，适合小功能、UI 增强和简单修改。当用户说"小功能"、"简单修改"、"轻量开发"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 2.0.0
---

# 轻量功能开发 Skill

## 概述

本 Skill 提供 **4 阶段精简流水线**，将 feature-dev 的 7 个阶段合并为 4 个，减少子代理调用次数。适合小功能、UI 增强、简单修改等场景。

**与 feature-dev 的核心区别**：
- 需求分析 + 系统设计合并为 1 个阶段
- 编码 + 测试合并为 1 个阶段（边写代码边写测试，非 TDD）
- 不生成文档（无阶段 7）
- 子代理调用：4 次（vs feature-dev 的 7 次）

## Workspace 工作记忆

与 feature-dev 使用相同的 Workspace 机制和文件命名。

### 目录结构

```
.claude/workspace/feature-YYYYMMDD-$NAME/
├── 00-input.md              # Skill 记录用户原始需求
├── 01-requirements.md       # 阶段 1 输出（精简版需求）
├── 02-design.md             # 阶段 1 输出（精简版设计）
<!-- IF:testing -->
├── 03-testplan.md           # 阶段 2 输出（测试用例列表）
<!-- ENDIF:testing -->
├── 04-implementation.md     # 阶段 2 输出（实现摘要）
├── 05-review.md             # 阶段 3 输出（审查报告）
└── 06-validation.md         # 阶段 4 输出（验证报告）
```

注意：无 `07-delivery.md`（轻量模式不生成文档）。

### 核心规则

与 feature-dev 相同：
1. 每个子代理的 prompt 必须指定读哪些 Workspace 文件
2. 每个子代理完成后必须将产出摘要写入对应的 Workspace 文件
3. 代码和测试写到项目正常位置，Workspace 文件存摘要和决策记录

### 下游摘要传递

从后期阶段开始，Skill 使用下游摘要优化上下文传递：

1. **预读**：调用子代理前，Skill 读取上游 WS 文件末尾的 `## 下游摘要` 节
2. **内联**：将摘要内容写入子代理的 Task prompt
3. **减负**：子代理仅读取标记为"读取"的文件全文，标记为"内联"的由 Skill 传入

各阶段的读取规则见子代理输入中的 `[内联]` 和 `读取` 标记。

## 流程总览

```
初始化              阶段 1           阶段 2           阶段 3           阶段 4
创建 Workspace ──→ 分析与设计 ──→  编码与测试  ──→  代码审查  ──→  集成验证
  │                  │                │                │               │
  ▼                  ▼                ▼                ▼               ▼
00-input.md       01 + 02          03 + 04           05              06
  │                  │                │                │               │
                    ⏸ 确认          自动              ⏸ 确认          自动
```

## 用户确认策略

**2 个确认点**：

| 确认点 | 位置 | 确认内容 | 为什么需要确认 |
|--------|------|----------|----------------|
| **分析设计确认** | 阶段 1 → 2 | 需求理解和改动方案是否正确 | 方向错了后续全部白费 |
| **审查确认** | 阶段 3 → 4 | 审查发现的问题是否接受 | 用户决定质量标准 |

**确认时的用户选项**：

阶段 1 确认点：
- **确认通过** → 进入阶段 2
- **要求修改** → 重新分析设计
- **升级到完整模式** → 01 和 02 已创建，切换到 `/feature-dev` 从阶段 3 继续
- **终止流程** → 保留 Workspace 已有产物

阶段 3 确认点：
- **确认通过** → 进入阶段 4
- **要求修复** → 返回阶段 2 修复后重新审查
- **部分接受** → 标记哪些必须修、哪些可后续处理

---

## 前置步骤：初始化 Workspace 与加载上下文

与 feature-dev 相同。

### 步骤 1：创建 Workspace

```bash
WS=".claude/workspace/feature-$(date +%Y%m%d)-$FEATURE_NAME"
mkdir -p "$WS"
```

### 步骤 2：记录用户原始需求

将用户的功能描述原文写入 `$WS/00-input.md`。

### 步骤 3：加载项目上下文

```
1. 读取 CLAUDE.md → 获取项目规范、技术栈、编码约定
2. 提取关键配置写入 $WS/00-context.md（技术栈、构建命令、测试约定、架构概要、编码规范、i18n 配置、样式规范、新功能步骤、输出语言+提交风格）
3. 读取 CLAUDE.md 中 Architecture 部分引用的核心文件（如类型定义、API 调用模块等）
4.（如 CLAUDE.md 中配置了 Design System）读取设计令牌配置文件
5.（如 CLAUDE.md 中配置了 i18n）扫描 locale 文件目录，确认文件列表
```

### 步骤 4：更新项目进度（如属于多阶段项目）

```
检查 .claude/workspace/_progress-*.md 是否记录了本任务。
如果是，将对应子任务状态更新为"进行中"，记录 Workspace 路径和开始时间。
```

---

## 阶段 1：分析与设计（合并需求分析 + 系统设计）

**目标**：理解需求并设计改动方案

**子代理**：System Designer（`system-designer.md`，Opus）

**为什么用 System Designer**：合并阶段需要较强的分析和设计能力，Opus 模型更适合。

**子代理 prompt 要点**：
```
你的任务是同时完成需求分析和系统设计（轻量模式）。

1. 先读取 $WS/00-input.md 了解用户需求
2. 读取 $WS/00-context.md 及其 Architecture 部分引用的核心文件了解项目现状
3. 分析需求，识别功能点和验收标准
4. 设计改动方案：要改哪些文件、怎么改、影响范围

输出两个文件：
- $WS/01-requirements.md：功能点列表 + 验收标准（精简版）
- $WS/02-design.md：改动方案 + 影响范围 + 文件清单（精简版）

注意：这是轻量模式第一阶段，Workspace 中尚无其他文件。
```

**子代理输出** → 写入 `$WS/01-requirements.md` 和 `$WS/02-design.md`（输出格式参照 `system-designer.md` Agent 文件中的模板）

**检查点**：
```bash
git add "$WS/00-input.md" "$WS/01-requirements.md" "$WS/02-design.md"
git commit -m "feat($FEATURE_NAME): 完成分析与设计（轻量）"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/01-requirements.md` 已创建
- [ ] `$WS/02-design.md` 已创建
- [ ] 用户确认方案

向用户展示 01 和 02 的核心摘要，询问：
- 确认通过 / 要求修改 / 升级到完整模式 / 终止

---

## 阶段 2：编码与测试（合并编码实现 + 测试）

**目标**：实现功能并编写测试，确保测试通过

**子代理**：Code Engineer（`code-engineer.md`，Sonnet）

**子代理 prompt 要点**：
```
你的任务是实现功能并编写测试（轻量模式，边写代码边写测试）。

1. 读取 $WS/01-requirements.md 了解功能点
2. 读取 $WS/02-design.md 了解改动方案
3. 读取 $WS/00-context.md 了解编码规范
4. 按设计方案实现代码
<!-- IF:testing -->
5. 为每个功能点编写测试
6. 运行测试直到全部通过
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
5. 手动验证功能正确性
6. 记录验证结果
<!-- ENDIF:NOT:testing -->
7.（如 00-context.md 中配置了 i18n）更新所有 locale 文件（如有 UI 文本变更）

输出两个 Workspace 文件：
<!-- IF:testing -->
- $WS/03-testplan.md：测试用例列表（精简）
<!-- ENDIF:testing -->
- $WS/04-implementation.md：变更清单 + 测试结果 + 需求覆盖核对
```

<!-- IF:testing -->
**子代理输出** → 写入 `$WS/03-testplan.md` 和 `$WS/04-implementation.md`（输出格式参照 `code-engineer.md` Agent 文件中的模板）
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
**子代理输出** → 写入 `$WS/04-implementation.md`（输出格式参照 `code-engineer.md` Agent 文件中的模板）
<!-- ENDIF:NOT:testing -->

**检查点**：
```bash
git add "$WS/03-testplan.md" "$WS/04-implementation.md" [变更文件列表参考 $WS/04-implementation.md]
git commit -m "feat($FEATURE_NAME): 完成编码与测试（轻量）"
```

**阶段门禁**（自动验证，不暂停）：
<!-- IF:testing -->
- [ ] 测试全部通过
<!-- ENDIF:testing -->
- [ ] `$WS/04-implementation.md` 已创建
- 自动进入阶段 3

---

## 阶段 3：代码审查

**目标**：发现代码质量和安全问题

**子代理**：Code Reviewer（`code-reviewer.md`，Sonnet）

<!-- IF:testing -->
**Skill 预读**：读取 `$WS/01-requirements.md` 和 `$WS/03-testplan.md` 的 `## 下游摘要` 节
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
**Skill 预读**：读取 `$WS/01-requirements.md` 的 `## 下游摘要` 节
<!-- ENDIF:NOT:testing -->

**子代理输入**：
- [内联] `$WS/01-requirements.md` 下游摘要（功能点+验收标准清单）
- 读取 `$WS/02-design.md`（核对实现是否符合设计——全文，质量红线）
<!-- IF:testing -->
- [内联] `$WS/03-testplan.md` 下游摘要（边界场景清单）
<!-- ENDIF:testing -->
- 读取 `$WS/04-implementation.md`（获取变更文件清单，只审查这些文件）
- 读取 `$WS/00-context.md`（核对项目规范）

**执行步骤**：与 feature-dev 阶段 5 完全相同。

**审查结果处理**：
```
APPROVE → 进入阶段 4
REQUEST CHANGES → 返回阶段 2 修复 → 重新阶段 3（最多 1 轮）
APPROVE WITH COMMENTS → 记录建议，进入阶段 4
```

**子代理输出** → 写入 `$WS/05-review.md`（格式与 feature-dev 相同）

**检查点**（如有修复）：
```bash
git add "$WS/05-review.md" [修复涉及的文件]
git commit -m "fix($FEATURE_NAME): 修复审查问题（轻量）"
```

**⏸ 阶段门禁**（需用户确认）：
向用户展示 `$WS/05-review.md` 摘要。

用户选项：
- **确认通过** → 进入阶段 4
- **要求修复** → 返回阶段 2 修复后重新审查
- **部分接受** → 标记必须修和可后续处理

---

## 阶段 4：集成验证

**目标**：验证模块集成和整体功能

**子代理**：Integration Validator（`integration-validator.md`，Sonnet）

<!-- IF:testing -->
**Skill 预读**：读取 01~05 所有 WS 文件的 `## 下游摘要` 节
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
**Skill 预读**：读取 01、02、04、05 WS 文件的 `## 下游摘要` 节
<!-- ENDIF:NOT:testing -->

**子代理输入**（全部通过下游摘要内联传入）：
- [内联] `$WS/01-requirements.md` 下游摘要（验收标准清单）
- [内联] `$WS/02-design.md` 下游摘要（API 契约表）
<!-- IF:testing -->
- [内联] `$WS/03-testplan.md` 下游摘要（测试文件+覆盖目标）
<!-- ENDIF:testing -->
- [内联] `$WS/04-implementation.md` 下游摘要（变更文件+测试结果）
- [内联] `$WS/05-review.md` 下游摘要（整体评估+未修复问题）
- 读取 `$WS/00-context.md`（项目规范）

**执行步骤**：与 feature-dev 阶段 6 完全相同。

**子代理输出** → 写入 `$WS/06-validation.md`（格式与 feature-dev 相同）

**检查点**：
```bash
git add "$WS/06-validation.md"
git commit -m "test($FEATURE_NAME): 完成集成验证（轻量）"
```

**阶段门禁**（自动完成）：
- PASS → 流程完成，输出总结
- FAIL → 报告失败项和修复建议，询问用户是否修复
- PASS WITH WARNINGS → 输出总结 + 警告信息

**更新项目进度**（如属于多阶段项目）：
```
如果 .claude/workspace/_progress-*.md 中记录了本任务，更新对应子任务状态为"已完成"，
并记录 Workspace 路径和完成时间。如果所有子任务均已完成，标记项目整体为"已完成"。
```

---

## 检查点与恢复

### 检查点策略

```
commit 1: feat($FEATURE): 完成分析与设计（轻量）  → $WS/01 + 02
commit 2: feat($FEATURE): 完成编码与测试（轻量）  → $WS/03 + 04
commit 3: fix($FEATURE): 审查修复（如有）         → $WS/05
commit 4: test($FEATURE): 集成验证（轻量）        → $WS/06
```

### 从指定阶段恢复

查找 `.claude/workspace/feature-*-$NAME/`，检查前序 Workspace 文件是否存在，从对应阶段继续。

### 升级到完整模式

在阶段 1 确认时选择"升级到完整模式"，Skill 会：
1. 保留已创建的 01 和 02
2. 提示用户执行：`/feature-dev 从阶段 3 继续，Workspace: $WS`

---

## 子代理一览

| 子代理 | 文件 | 模型 | 阶段 | 读取 | 写入 |
|--------|------|------|------|------|------|
| System Designer | `system-designer.md` | Opus | 1 | 00-input | 01 + 02 |
<!-- IF:testing -->
| Code Engineer | `code-engineer.md` | Sonnet | 2 | 01, 02 | 03 + 04 |
| Code Reviewer | `code-reviewer.md` | Sonnet | 3 | 01↓, 02, 03↓, 04 | 05 |
| Integration Validator | `integration-validator.md` | Sonnet | 4 | 01↓, 02↓, 03↓, 04↓, 05↓ | 06 |
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
| Code Engineer | `code-engineer.md` | Sonnet | 2 | 01, 02 | 04 |
| Code Reviewer | `code-reviewer.md` | Sonnet | 3 | 01↓, 02, 04 | 05 |
| Integration Validator | `integration-validator.md` | Sonnet | 4 | 01↓, 02↓, 04↓, 05↓ | 06 |
<!-- ENDIF:NOT:testing -->

> `↓` = 通过下游摘要内联传入（非全文读取）
