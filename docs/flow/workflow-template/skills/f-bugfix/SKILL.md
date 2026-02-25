---
name: f-bugfix
description: Bug 修复流程：诊断根因、实现修复、回归测试。当用户说"修复 Bug"、"调试"、"报错"、"异常"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 2.2.0
---

# Bug 修复 Skill

## 概述

本 Skill 提供 **4 阶段 Bug 修复流水线**，从诊断到验证。与功能开发不同，起点是"问题"而非"需求"，核心是**复现 → 定位根因 → 修复 → 回归测试**。

## Workspace 工作记忆

使用与 f-dev 相同的文件命名规范，但 Workspace 前缀为 `bugfix-`，内容适配 Bug 修复场景。

### 目录结构

```
.claude/workspace/bugfix-YYYYMMDD-$NAME/
├── 00-input.md              # Skill 记录 Bug 描述/错误信息
├── 01-requirements.md       # 阶段 1 输出（Bug 分析 + 根因）
├── 02-design.md             # 阶段 1 输出（修复方案）
<!-- IF:testing -->
├── 03-testplan.md           # 阶段 2 输出（回归测试用例）
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
├── 03-testplan.md           # 阶段 2 输出（手动验证清单）
<!-- ENDIF:NOT:testing -->
├── 04-implementation.md     # 阶段 2 输出（修复变更清单）
├── 05-review.md             # 阶段 3 输出（审查报告）
└── 06-validation.md         # 阶段 4 输出（验证报告）
```

**文件名与 f-dev 一致**，下游子代理（code-reviewer、integration-validator）无需适配，直接复用。

### 核心规则

与 f-dev 相同：
1. 每个子代理的 prompt 必须指定读哪些 Workspace 文件
2. 每个子代理完成后必须将产出摘要写入对应的 Workspace 文件
3. 修复代码写到项目正常位置，Workspace 文件存诊断分析和决策记录

### 下游摘要传递

从后期阶段开始，Skill 使用下游摘要优化上下文传递：

1. **预读**：调用子代理前，Skill 读取上游 WS 文件末尾的 `## 下游摘要` 节
2. **内联**：将摘要内容写入子代理的 Task prompt
3. **减负**：子代理仅读取标记为"读取"的文件全文，标记为"内联"的由 Skill 传入

各阶段的读取规则见子代理输入中的 `[内联]` 和 `读取` 标记。

## 流程总览

> 如果检测到上游设计产物（来自 `/f-design`）并被用户确认使用，诊断阶段可跳过或以设计产物为参考。

```
初始化              阶段 1         阶段 2          阶段 3         阶段 4
创建 Workspace ──→ 诊断分析 ──→  修复与测试  ──→  代码审查  ──→  集成验证
  │                  │              │               │              │
  ▼                  ▼              ▼               ▼              ▼
00-input.md       01 + 02        03 + 04          05             06
  │                  │              │               │              │
                    ⏸ 确认        自动             自动*           自动

* 阶段 3 有 Critical/High 问题时自动返回阶段 2 修复（最多 1 轮）
```

## 用户确认策略

**1 个确认点**：

| 确认点 | 位置 | 确认内容 | 为什么需要确认 |
|--------|------|----------|----------------|
| **诊断确认** | 阶段 1 → 2 | 根因分析是否正确、修复方案是否合理 | 修错方向会引入新 Bug |

Bug 修复的关键决策在"问题在哪、怎么修"。确认方案后，修复 → 审查 → 验证是确定性流程，自动执行。

**确认时的用户选项**：
- **确认通过** → 按方案修复
- **补充信息** → 提供更多 Bug 上下文，重新诊断
- **调整方案** → 指定不同的修复方向
- **终止** → 问题不紧急或需要线下排查

---

## 前置步骤：初始化 Workspace

### 脚本初始化

执行初始化脚本：

```bash
bash .claude/scripts/dev-init.sh --type=bugfix --name="$BUG_NAME" --input="$USER_INPUT"
```

解析 JSON 输出：
- `workspace` → 赋值给 `$WS`，后续所有阶段使用此路径
- `design_source` → 非 null 时表示检测到设计上游（来自 `/f-design`）
- `stages_preloaded` → 非空数组时表示有预加载的阶段（如 `[1, 2]`）
- `warnings` → 非空时展示给用户（如"Testing section 未找到"）
- `capabilities` → 用于判断是否需要 i18n 等条件步骤
- `progress_updated` → 为 true 时告知用户已更新项目进度

将 `$WS` 路径传递给后续每个子代理。

### 上游产物检测

解析 dev-init.sh 返回的 `design_source` 和 `stages_preloaded`：

**当 `stages_preloaded` 非空时**（检测到已有设计产物）：

注意：design 和 bugfix 的 01/02 语义有差异——design 的 01 是需求分析，bugfix 的 01 是 Bug 诊断。因此 bugfix 多提供一个"仅作为参考"选项。

1. 读取已复制到 `$WS` 中的 `01-requirements.md` 和/或 `02-design.md` 的核心摘要
2. 向用户展示：
   - 来源 workspace 路径（`design_source` 值）
   - 预加载的内容摘要
3. 询问用户（AskUserQuestion，3 选项）：
   - **使用已有设计，跳过诊断阶段**（推荐）→ 跳过阶段 1（诊断分析），直接进入阶段 2（修复与测试）
   - **仅作为参考** → 阶段 1 仍然执行，但 System Designer 的 prompt 中追加 design 产物作为参考材料（提示子代理："以下是之前的设计分析，供参考，请结合实际代码重新诊断"）
   - **忽略，重新诊断** → 删除预加载文件，从头开始
4. 用户选择跳过时：
   - 跳过阶段 1 的子代理调用和检查点 commit
   - 直接进入阶段 2（修复与测试）

**当 `stages_preloaded` 为空时**：正常流程，从阶段 1 开始。

---

## 阶段 1：诊断分析（合并需求分析 + 系统设计）

**目标**：定位 Bug 根因，制定修复方案

**子代理**：System Designer（`system-designer.md`，Opus）

**为什么用 Opus**：Bug 诊断需要强推理能力——跨文件追踪数据流、分析竞态条件、推断边界情况。

**子代理 prompt 要点**：
```
你的任务是诊断 Bug 并制定修复方案。

1. 读取 $WS/00-input.md 了解 Bug 描述和错误信息
2. 根据 Bug 描述定位相关源码文件，仔细阅读
3. 分析复现路径：什么操作序列触发了这个 Bug
4. 定位根因：问题出在哪个文件的哪个逻辑
5. 评估影响范围：这个 Bug 还会影响哪些功能
6. 制定修复方案：怎么改、改哪些文件

输出两个文件：
- $WS/01-requirements.md：Bug 分析（复现路径 + 根因 + 影响范围 + 严重程度）
- $WS/02-design.md：修复方案（修复策略 + 文件变更计划 + 回归风险 + 注意事项）

注意：这是 Bug 修复流程，01 和 02 的内容是诊断和修复方案，不是功能需求和系统设计。
```

**检查点**：
```bash
git add "$WS/00-input.md" "$WS/01-requirements.md" "$WS/02-design.md"
git commit -m "fix($BUG_NAME): 完成 Bug 诊断"
```

**⏸ 阶段门禁**（需用户确认）：

向用户展示：
1. 根因分析摘要
2. 修复方案要点
3. 影响范围和回归风险

询问：确认修复方案 / 补充信息 / 调整方案 / 终止

---

## 阶段 2：修复与测试

**目标**：实现修复，编写回归测试

**子代理**：Code Engineer（`code-engineer.md`，Sonnet）

**子代理输入**：
- 读取 `$WS/01-requirements.md`（根因和影响范围）
- 读取 `$WS/02-design.md`（修复方案和文件清单）
- 读取 `$WS/00-context.md`（编码规范）

**子代理 prompt 要点**：
```
你的任务是修复 Bug 并编写回归测试。

1. 读取 $WS/01-requirements.md 了解根因
2. 读取 $WS/02-design.md 按修复方案实现
<!-- IF:testing -->
3. 编写回归测试：覆盖原始 Bug 场景 + 边界情况
4. 运行测试确保修复有效且不破坏其他功能
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
3. 手动验证修复效果：覆盖原始 Bug 场景
4. 编写手动验证清单记录在 $WS/03-testplan.md 中
<!-- ENDIF:NOT:testing -->
5.（如 CLAUDE.md 中配置了 i18n）更新 locale 文件（如修复涉及 UI 文本）

输出：
- $WS/03-testplan.md：回归测试用例列表（Bug 场景 / 测试用例 / 类型 / 文件）
- $WS/04-implementation.md：修复变更清单 + 测试结果 + 根因修复确认
```

**子代理输出** → 写入 `$WS/03-testplan.md` 和 `$WS/04-implementation.md`（输出格式参照 `code-engineer.md` 中的模板）

**检查点**：
```bash
git add "$WS/03-testplan.md" "$WS/04-implementation.md" [修复涉及的文件]
git commit -m "fix($BUG_NAME): 完成修复与回归测试"
```

**阶段门禁**（自动流转）：
<!-- IF:testing -->
- [ ] 回归测试通过
- [ ] 全量测试通过
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
- [ ] 手动验证清单已完成
<!-- ENDIF:NOT:testing -->
- 自动进入阶段 3

---

## 阶段 3：代码审查

**目标**：确认修复不会引入新问题

**子代理**：Code Reviewer（`code-reviewer.md`，Sonnet）

<!-- IF:testing -->
**Skill 预读**：读取 `$WS/01-requirements.md` 和 `$WS/03-testplan.md` 的 `## 下游摘要` 节
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
**Skill 预读**：读取 `$WS/01-requirements.md` 的 `## 下游摘要` 节
<!-- ENDIF:NOT:testing -->

**子代理输入**：
- [内联] `$WS/01-requirements.md` 下游摘要（根因+影响范围）
- 读取 `$WS/02-design.md`（修复方案——确认实现与方案一致——全文）
<!-- IF:testing -->
- [内联] `$WS/03-testplan.md` 下游摘要（回归测试场景清单）
<!-- ENDIF:testing -->
- 读取 `$WS/04-implementation.md`（变更清单——逐文件审查）
- 读取 `$WS/00-context.md`（编码规范）

**审查重点**（Bug 修复特有）：
1. 修复的是**根因**还是只是掩盖症状
2. 修复是否引入**新的边界情况**
3. 回归测试是否覆盖了原始 Bug 场景
4. 修复范围是否超出必要（避免过度修改）

**审查结果处理**：
```
APPROVE → 自动进入阶段 4
REQUEST CHANGES → 自动返回阶段 2 修复（最多 1 轮）
APPROVE WITH COMMENTS → 记录建议，自动进入阶段 4
```

**子代理输出** → 写入 `$WS/05-review.md`

**检查点**（如有修复）：
```bash
git add "$WS/05-review.md" [修复涉及的文件]
git commit -m "fix($BUG_NAME): 修复审查问题"
```

**阶段门禁**（自动流转）：
- 审查结果按上述逻辑自动处理（APPROVE/REQUEST CHANGES/APPROVE WITH COMMENTS）
- 自动进入阶段 4（如需修复则先返回阶段 2，最多 1 轮）

---

## 阶段 4：集成验证

**目标**：确保修复后系统整体正常

**子代理**：Integration Validator（`integration-validator.md`，Sonnet）

<!-- IF:testing -->
**Skill 预读**：读取 01~05 所有 WS 文件的 `## 下游摘要` 节
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
**Skill 预读**：读取 01、02、04、05 WS 文件的 `## 下游摘要` 节
<!-- ENDIF:NOT:testing -->

**子代理输入**（全部通过下游摘要内联传入）：
- [内联] `$WS/01-requirements.md` 下游摘要（影响范围）
- [内联] `$WS/02-design.md` 下游摘要（修复方案+文件清单）
<!-- IF:testing -->
- [内联] `$WS/03-testplan.md` 下游摘要（回归测试文件+覆盖目标）
<!-- ENDIF:testing -->
- [内联] `$WS/04-implementation.md` 下游摘要（变更文件+测试结果）
- [内联] `$WS/05-review.md` 下游摘要（整体评估+未修复问题）
- 读取 `$WS/00-context.md`（项目规范）

**执行步骤**：
<!-- IF:frontend -->
1. 前端构建验证
<!-- ENDIF:frontend -->
<!-- IF:backend-api -->
2. 后端构建验证
<!-- ENDIF:backend-api -->
<!-- IF:static-types -->
3. 类型检查
<!-- ENDIF:static-types -->
<!-- IF:testing -->
4. 运行完整测试套件（重点关注回归测试）
5. 检查测试覆盖率
<!-- ENDIF:testing -->
6. 审查问题修复验证
7.（如 CLAUDE.md 中配置了 i18n）i18n 验证（如修复涉及 UI）

**子代理输出** → 写入 `$WS/06-validation.md`

**阶段门禁**（自动完成）：
- PASS → 流程完成，输出修复总结
- FAIL → 报告失败项和修复建议

**最终提交**：
```bash
git add "$WS/06-validation.md"
git commit -m "fix($BUG_NAME): 验证通过"
```

**更新项目进度**（如属于多阶段项目）：
```
如果 .claude/workspace/_progress-*.md 中记录了本任务，更新对应子任务状态为"已完成"，
并记录 Workspace 路径和完成时间。如果所有子任务均已完成，标记项目整体为"已完成"。
```

---

## 检查点与恢复

**检查点策略**：每阶段完成后 commit，消息格式：
- `fix($BUG): 完成 Bug 诊断` → $WS/01+02
- `fix($BUG): 完成修复与回归测试` → $WS/03+04
- `fix($BUG): 修复审查问题`（如有）→ $WS/05
- `fix($BUG): 验证通过` → $WS/06

**从指定阶段恢复**：指定 BUG_NAME 和目标阶段，Skill 自动查找 `bugfix-*-$NAME/`，检查前序文件是否存在，从指定阶段继续。

---

## 子代理一览

| 子代理 | 文件 | 模型 | 阶段 | 读取 | 写入 |
|--------|------|------|------|------|------|
| System Designer | `system-designer.md` | Opus | 1 | 00-input | 01 + 02 |
| Code Engineer | `code-engineer.md` | Sonnet | 2 | 01, 02 | 03 + 04 |
| Code Reviewer | `code-reviewer.md` | Sonnet | 3 | 01↓, 02, 03↓, 04 | 05 |
| Integration Validator | `integration-validator.md` | Sonnet | 4 | 01↓, 02↓, 03↓, 04↓, 05↓ | 06 |

> `↓` = 通过下游摘要内联传入（非全文读取）
