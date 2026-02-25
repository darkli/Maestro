<!-- IF:NOT:QUICK_MODE -->
---
name: f-dev
description: 端到端功能模块开发：从需求分析到集成测试的完整自动化流程。当用户说"开发新功能"、"创建模块"、"完整开发流程"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 5.4.0
---
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
---
name: f-quick-dev
description: 快速功能开发：完整 7 阶段流程但只在设计和验证时暂停确认。当用户说"快速开发"、"快速模式"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 3.4.0
---
<!-- ENDIF:QUICK_MODE -->

<!-- IF:NOT:QUICK_MODE -->
# 功能模块端到端开发 Skill
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
# 快速功能开发 Skill
<!-- ENDIF:QUICK_MODE -->

## 概述

<!-- IF:NOT:QUICK_MODE -->
这个 Skill 协调完整的功能模块开发流程，从需求分析到文档交付全自动化执行。采用 **7 阶段流水线**，每个阶段由专业子代理负责，通过 **Workspace 工作记忆** 实现可靠的阶段间状态传递。
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
本 Skill 执行与 `/f-dev` 完全相同的 **7 阶段流水线**，唯一区别是只在 **2 个关键节点** 暂停确认，其余阶段自动流转。适合中等规模功能，用户信任流程、希望减少交互次数。
<!-- ENDIF:QUICK_MODE -->

## Workspace 工作记忆

每次启动功能开发时，创建一个独立的 Workspace 目录，作为本次开发全程的 **唯一状态中心**。所有子代理从 Workspace 读取输入、向 Workspace 写入输出，不依赖对话历史传递上下文。

### 目录结构

```
.claude/workspace/feature-YYYYMMDD-$NAME/
├── 00-input.md              # Skill 记录用户原始需求
├── 01-requirements.md       # Requirements Analyst 输出
├── 02-design.md             # System Designer 输出
<!-- IF:testing -->
├── 03-testplan.md           # Test Engineer 输出
<!-- ENDIF:testing -->
├── 04-implementation.md     # Code Engineer 输出（实现摘要）
├── 05-review.md             # Code Reviewer 输出
├── 06-validation.md         # Integration Validator 输出
└── 07-delivery.md           # Documentation Writer 输出
```

### 核心规则

1. **每个子代理的 prompt 必须指定读哪些 Workspace 文件**，写 "读取 `$WS/01-requirements.md`"，绝不写 "基于前面的分析"
2. **每个子代理完成后必须将产出摘要写入对应的 Workspace 文件**，确保下游代理有明确的输入源
3. **代码和文档仍然写到项目正常位置**（参考 CLAUDE.md 中的 Architecture 部分），Workspace 文件存的是摘要和决策记录，不是代码本身
4. **Workspace 目录在流程结束后保留**，作为本次开发的完整归档

### 下游摘要传递

从后期阶段开始，Skill 使用下游摘要优化上下文传递：

1. **预读**：调用子代理前，Skill 读取上游 WS 文件末尾的 `## 下游摘要` 节
2. **内联**：将摘要内容写入子代理的 Task prompt
3. **减负**：子代理仅读取标记为"读取"的文件全文，标记为"内联"的由 Skill 传入

各阶段的读取规则见子代理输入中的 `[内联]` 和 `读取` 标记。

### 命名规范

```
feature-YYYYMMDD-短名称

示例：
  feature-20260225-user-auth
  feature-20260301-payment-gateway
  feature-20260315-file-upload
```

## 流程总览

> 如果检测到上游设计产物（来自 `/f-design`）并被用户确认，阶段 1-2 将被跳过。

```
初始化              阶段 1       阶段 2       阶段 3       阶段 4       阶段 5       阶段 6       阶段 7
创建 Workspace ──→ 需求分析 ──→ 系统设计 ──→ 测试设计 ──→ 编码实现 ──→ 代码审查 ──→ 集成验证 ──→ 文档交付
  │                  │            │            │            │            │            │            │
  ▼                  ▼            ▼            ▼            ▼            ▼            ▼            ▼
00-input.md       01-req.md    02-design.md 03-test.md  04-impl.md  05-review.md 06-valid.md  07-delivery.md
  │                  │            │            │            │            │            │            │
<!-- IF:NOT:QUICK_MODE -->
                    ⏸ 确认       ⏸ 确认       自动         ⏸ 确认       ⏸ 确认       ⏸ 确认       自动
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
                    自动         ⏸ 确认       自动         自动         自动*        ⏸ 确认       自动
<!-- ENDIF:QUICK_MODE -->

<!-- IF:NOT:QUICK_MODE -->
每个阶段的子代理：读取上游 Workspace 文件 → 执行 → 写入本阶段 Workspace 文件 → git commit
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
* 阶段 5 有 Critical/High 问题时自动返回阶段 4 修复（最多 2 轮）
<!-- ENDIF:QUICK_MODE -->
```

<!-- IF:NOT:testing -->
> **注意**：`testing: false` 时阶段 3（测试设计）自动跳过，流程从阶段 2 直接进入阶段 4。
<!-- ENDIF:NOT:testing -->

## 用户确认策略

<!-- IF:NOT:QUICK_MODE -->
流程在 **5 个关键节点** 暂停等待用户确认，防止方向偏离：

| 确认点 | 位置 | 确认内容 | 为什么需要确认 |
|--------|------|----------|----------------|
| **需求确认** | 阶段 1 → 2 | 需求理解是否准确、验收标准是否完整 | 需求是一切的基础，偏差会逐级放大 |
| **设计确认** | 阶段 2 → 3 | 架构方案、技术选型、接口设计是否合理 | 设计决定了后续所有实现细节 |
| **实现确认** | 阶段 4 → 5 | 代码逻辑、UI 效果、功能是否符合预期 | 在审查前先确认大方向没偏 |
| **审查确认** | 阶段 5 → 6 | 审查报告中的问题是否接受、修复是否到位 | 用户决定质量标准的取舍 |
| **验证确认** | 阶段 6 → 7 | 测试结果、覆盖率、API 契约是否达标 | 最后一道质量门禁 |

**确认时的用户选项**：
- **确认通过** → 进入下一阶段
- **要求修改** → 说明修改意见，回到当前阶段重新执行
- **调整方向** → 回退到更早的阶段
- **终止流程** → 停止开发，保留 Workspace 中的已有产物
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
只在 **2 个关键节点** 暂停确认：

| 确认点 | 位置 | 确认内容 | 为什么需要确认 |
|--------|------|----------|----------------|
| **设计确认** | 阶段 2 → 3 | 架构方案、技术选型、接口设计是否合理 | 设计决定了所有后续实现，必须确认方向正确 |
| **验证确认** | 阶段 6 → 7 | 测试结果、覆盖率、API 契约是否达标 | 最终质量门禁，确保代码可交付 |

**确认时的用户选项**：
- **确认通过** → 进入下一阶段
- **要求修改** → 说明修改意见，回到当前阶段重新执行
- **终止流程** → 停止开发，保留 Workspace 中的已有产物
<!-- ENDIF:QUICK_MODE -->

**确认时的展示内容**：
1. 本阶段 Workspace 文件的核心摘要
2. 关键决策点列表
3. 下一阶段预览
4. 明确询问："以上内容是否确认？是否有需要调整的地方？"

---

## 前置步骤：初始化 Workspace 与加载上下文

### 脚本初始化

执行初始化脚本：

```bash
bash .claude/scripts/dev-init.sh --type=feature --name="$FEATURE_NAME" --input="$USER_INPUT"
```

解析 JSON 输出：
- `workspace` → 赋值给 `$WS`，后续所有阶段使用此路径
- `upstream_detected` → 非 null 时在阶段 1 子代理 prompt 中补充上游引用
- `available_upstreams` → 非空时询问用户是否使用某个上游产品设计
- `design_source` → 非 null 时表示检测到设计上游（来自 `/f-design`）
- `stages_preloaded` → 非空数组时表示有预加载的阶段（如 `[1, 2]`）
- `warnings` → 非空时展示给用户（如"Testing section 未找到"）
- `capabilities` → 用于判断是否需要 i18n/Design System 等条件步骤
- `progress_updated` → 为 true 时告知用户已更新项目进度

将 `$WS` 路径传递给后续每个子代理。

### 上游产物检测

解析 dev-init.sh 返回的 `design_source` 和 `stages_preloaded`：

**当 `stages_preloaded` 非空时**（检测到已有设计产物）：

1. 读取已复制到 `$WS` 中的 `01-requirements.md` 和/或 `02-design.md` 的核心摘要
2. 向用户展示：
   - 来源 workspace 路径（`design_source` 值）
   - 预加载的阶段内容摘要（功能概述、架构要点、关键设计决策）
3. 询问用户（AskUserQuestion，3 选项）：
   - **使用已有设计，跳过阶段 1-2**（推荐）→ 直接进入阶段 3（或阶段 4 如 `testing=false`）
   - **重新分析设计** → 删除预加载的 01/02 文件，从阶段 1 正常开始
   - **终止流程**
4. 用户选择跳过时：
   - 跳过阶段 1-2 的子代理调用和检查点 commit
   - 从阶段 3（TDD）或阶段 4（编码，若 `testing=false`）继续

**当 `stages_preloaded` 为空时**：正常流程，从阶段 1 开始。

---

## 阶段 1：需求分析（Requirements Analysis）

**目标**：理解并文档化功能需求

**子代理**：Requirements Analyst（`requirements-analyst.md`）

**子代理输入**：
- 读取 `$WS/00-input.md`（用户原始需求）
- 读取 `$WS/00-context.md`（项目上下文）

**执行步骤**：
1. 读取 `$WS/00-input.md` 中的用户需求原文
2. 与用户交互澄清需求
3. 识别核心功能点、边界情况、约束条件
4. 定义可测试的验收标准
5. 评估对现有模块的影响范围

**子代理输出** → 写入 `$WS/01-requirements.md`（输出格式参照 `requirements-analyst.md` 中的模板）

**检查点**：
```bash
git add "$WS/00-input.md" "$WS/01-requirements.md"
git commit -m "feat($FEATURE_NAME): 完成需求分析"
```

<!-- PROJECT-SPECIFIC: commit 格式参照 CLAUDE.md Commit Style 部分 -->

<!-- IF:NOT:QUICK_MODE -->
**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/01-requirements.md` 已创建
- [ ] 验收标准已定义
- [ ] 用户确认需求理解无误
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
**阶段门禁**（自动流转，不暂停）：
- [ ] `$WS/01-requirements.md` 已创建
- [ ] 验收标准已定义
- 自动进入阶段 2
<!-- ENDIF:QUICK_MODE -->

---

## 阶段 2：系统设计（System Design）

**目标**：设计技术架构和接口

**子代理**：System Designer（`system-designer.md`）

**子代理输入**：
- 读取 `$WS/01-requirements.md`（需求文档）
- 读取 `$WS/00-context.md`（项目规范）
- 读取 CLAUDE.md 中 Architecture 部分引用的核心代码文件（如类型定义、API 调用模块）

<!-- PROJECT-SPECIFIC: 具体文件路径由 CLAUDE.md Architecture 部分定义 -->

**执行步骤**：
1. 读取 `$WS/01-requirements.md`，逐条对照需求
2. 分析现有代码库结构
3. 设计架构（组件划分、数据流、接口定义）
4. 绘制架构图（Mermaid）

**子代理输出** → 写入 `$WS/02-design.md`（输出格式参照 `system-designer.md` 中的模板）

**检查点**：
```bash
git add "$WS/02-design.md"
git commit -m "feat($FEATURE_NAME): 完成系统设计"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/02-design.md` 已创建
- [ ] 架构图已生成
- [ ] 接口已定义
- [ ] 数据模型合理
- [ ] 用户确认设计方案

---

## 阶段 3：TDD 测试设计（Test-Driven Design）

<!-- IF:testing -->
**目标**：在编码前编写测试用例

**子代理**：Test Engineer（`test-engineer.md`）

**子代理输入**：
- 读取 `$WS/01-requirements.md`（验收标准 → 转化为测试用例）
- 读取 `$WS/02-design.md`（接口定义 → 确定测试对象）

**执行步骤**：
1. 逐条读取 `$WS/01-requirements.md` 的验收标准
2. 逐条读取 `$WS/02-design.md` 的接口定义
3. 为每个验收标准编写至少一个测试用例
4. 编写单元测试骨架（先失败的测试）
5. 创建 Mock 数据和 Fixture

**测试类型**：
- **单元测试**（70%）：核心函数、边界情况
- **集成测试**（20%）：模块间交互、API 调用
- **E2E 测试**（10%，如适用）：完整用户流程

**子代理输出** → 写入 `$WS/03-testplan.md`（输出格式参照 `test-engineer.md` 中的模板）

同时创建实际的测试文件（写入项目测试目录，参考 CLAUDE.md 中的 Testing 部分）。

**检查点**：
```bash
git add "$WS/03-testplan.md" [测试文件，参考 CLAUDE.md Testing 部分约定的测试目录]
git commit -m "feat($FEATURE_NAME): 完成测试设计（TDD）"
```

**阶段门禁**（自动验证，无需用户确认）：
- [ ] `$WS/03-testplan.md` 已创建
- [ ] 测试文件已创建
- [ ] 运行测试全部失败（TDD 预期）
- 自动通过后直接进入阶段 4
<!-- ENDIF:testing -->

<!-- IF:NOT:testing -->
**阶段已跳过**：项目未配置测试框架（`testing: false`），TDD 阶段自动跳过。
直接进入阶段 4。

注意：阶段 4 的 Code Engineer 不读取 `$WS/03-testplan.md`（该文件不生成）。
<!-- ENDIF:NOT:testing -->

---

## 阶段 4：编码实现（Implementation）

**目标**：实现功能，通过测试

**子代理**：Code Engineer（`code-engineer.md`）

**Skill 预读**：读取 `$WS/01-requirements.md` 的 `## 下游摘要` 节

**子代理输入**：
- [内联] `$WS/01-requirements.md` 下游摘要（功能点+验收标准清单）
- 读取 `$WS/02-design.md`（架构、接口、数据模型——严格遵循）
<!-- IF:testing -->
- 读取 `$WS/03-testplan.md`（测试用例——代码要通过这些测试）
<!-- ENDIF:testing -->
- 读取 `$WS/00-context.md`（编码规范）
- 读取 CLAUDE.md 中 Architecture 部分引用的核心代码文件（如类型定义、API 调用模块）

<!-- PROJECT-SPECIFIC: 具体文件路径由 CLAUDE.md Architecture 部分定义 -->

**执行步骤**：
1. 逐条读取 `$WS/02-design.md` 的文件结构，创建文件
<!-- IF:backend-api -->
2. 按设计文档的接口定义实现后端
<!-- ENDIF:backend-api -->
<!-- IF:frontend -->
3. 按设计文档的组件划分实现前端
<!-- ENDIF:frontend -->
4. 按 `$WS/01-requirements.md` 的功能清单逐条核对
5.（如 00-context.md 中配置了 i18n）更新所有 locale 文件
6.（如 00-context.md 中配置了 Design System）确保使用 Design Token 和对应的暗色模式写法
<!-- IF:testing -->
7. 运行 `$WS/03-testplan.md` 中列出的测试并修复失败
<!-- ENDIF:testing -->
8. 自我审查

**编码标准**：
- 遵循 00-context.md 中的编码规范
- 静态类型语言使用严格类型检查
-（如 00-context.md 中配置了 Database）数据库查询使用参数化
- 遵循 00-context.md 中定义的命名约定和缩进风格

**子代理输出** → 写入 `$WS/04-implementation.md`（输出格式参照 `code-engineer.md` 中的模板）

**检查点**：
```bash
# 根据 $WS/04-implementation.md 中的文件变更清单，暂存所有修改文件
git add "$WS/04-implementation.md" [变更文件列表参考 $WS/04-implementation.md]
git commit -m "feat($FEATURE_NAME): 完成编码实现"
```

<!-- IF:NOT:QUICK_MODE -->
**⏸ 阶段门禁**（需用户确认）：

向用户展示 `$WS/04-implementation.md` 摘要，特别是需求覆盖核对表。

用户选项：
- **确认** → 进入阶段 5
- **要求修改** → Code Engineer 重新执行
- **回退到设计** → 回到阶段 2 调整
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
**阶段门禁**（自动流转，不暂停）：
<!-- IF:testing -->
- [ ] 测试全部通过
<!-- ENDIF:testing -->
- [ ] `$WS/04-implementation.md` 已创建
- 自动进入阶段 5
<!-- ENDIF:QUICK_MODE -->

---

## 阶段 5：代码审查（Code Review）

**目标**：发现并修复代码质量和安全问题

**子代理**：Code Reviewer（`code-reviewer.md`）

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

**执行步骤**：
1. 从 `$WS/04-implementation.md` 获取变更文件列表
2. 逐文件审查代码
3. 对照 `$WS/01-requirements.md` 的功能清单：是否全部实现
4. 对照 `$WS/02-design.md` 的接口定义：实现是否一致
<!-- IF:testing -->
5. 对照 `$WS/03-testplan.md` 的异常场景：是否有处理
<!-- ENDIF:testing -->
6. 安全审计、i18n 检查（如适用）、性能检查
7. 生成审查报告

<!-- IF:NOT:QUICK_MODE -->
**审查结果处理**：
```
APPROVE → 进入阶段 6
REQUEST CHANGES → 返回阶段 4 修复 → 重新阶段 5（最多 2 轮）
APPROVE WITH COMMENTS → 记录建议，进入阶段 6
```
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
**审查结果处理**（自动，不暂停）：
```
APPROVE → 自动进入阶段 6
REQUEST CHANGES → 自动返回阶段 4 修复 → 重新阶段 5（最多 2 轮）
APPROVE WITH COMMENTS → 记录建议，自动进入阶段 6
```
<!-- ENDIF:QUICK_MODE -->

**子代理输出** → 写入 `$WS/05-review.md`（输出格式参照 `code-reviewer.md` 中的模板）

**检查点**（如有修复）：
```bash
git add "$WS/05-review.md" [修复的文件，参考 $WS/04-implementation.md 变更清单]
git commit -m "fix($FEATURE_NAME): 修复代码审查发现的问题"
```

<!-- IF:NOT:QUICK_MODE -->
**⏸ 阶段门禁**（需用户确认）：

向用户展示 `$WS/05-review.md` 摘要。

用户选项：
- **确认通过** → 进入阶段 6
- **要求修复** → 指定问题，返回阶段 4 修复后重新审查
- **部分接受** → 标记哪些必须修、哪些可后续处理
<!-- ENDIF:NOT:QUICK_MODE -->
<!-- IF:QUICK_MODE -->
**阶段门禁**（自动流转，不暂停）：
- 审查通过后自动进入阶段 6
<!-- ENDIF:QUICK_MODE -->

---

## 阶段 6：集成验证（Integration Validation）

**目标**：验证模块集成和整体功能

**子代理**：Integration Validator（`integration-validator.md`）

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

**执行步骤**：
1. 构建验证（参考 CLAUDE.md 中 Build & Development Commands 部分）
2. 静态类型检查
3. 运行完整测试套件（参考 CLAUDE.md 中 Testing 部分）
4. 检查测试覆盖率
5. API 契约验证（对照 `$WS/02-design.md` 的接口定义）
6.（如 CLAUDE.md 中配置了 i18n）i18n 完整性验证
7. 安全检查
8. 审查问题修复验证（对照 `$WS/05-review.md` 中 Critical/High 问题）
9. 性能基准（如适用）

<!-- PROJECT-SPECIFIC: 构建命令和测试命令由 CLAUDE.md Build & Development Commands / Testing 部分定义 -->

**子代理输出** → 写入 `$WS/06-validation.md`（输出格式参照 `integration-validator.md` 中的模板）

**检查点**（如有修复）：
```bash
git add "$WS/06-validation.md"
git commit -m "fix($FEATURE_NAME): 修复集成验证发现的问题"
```

**⏸ 阶段门禁**（需用户确认）：

向用户展示 `$WS/06-validation.md` 摘要。

用户选项：
- **确认通过** → 进入阶段 7
- **要求修复** → 返回阶段 4 修复后重新验证
- **接受现状** → 记录已知问题，继续进入文档阶段

---

## 阶段 7：文档与交付（Documentation & Delivery）

**目标**：完善文档，准备交付

**子代理**：Documentation Writer（`documentation-writer.md`）

**Skill 预读**：读取 01、04、05、06 的 `## 下游摘要` 节

**子代理输入**：
- [内联] `$WS/01-requirements.md` 下游摘要（功能描述 → 用户指南素材）
- 读取 `$WS/02-design.md`（API 定义 → API 文档素材——全文）
- [内联] `$WS/04-implementation.md` 下游摘要（变更清单 → 变更日志素材）
- [内联] `$WS/05-review.md` 下游摘要（审查决策 → 开发报告素材）
- [内联] `$WS/06-validation.md` 下游摘要（测试结果 → 开发报告素材）

**执行步骤**：
1. 生成 API 文档（参考 CLAUDE.md 中 Architecture 部分确定文档目录约定）
2. 生成用户指南
3. 更新变更日志（如项目维护变更日志）
4. 生成开发总结报告 → `$WS/07-delivery.md`

<!-- PROJECT-SPECIFIC: 文档目录约定由 CLAUDE.md Architecture 部分定义 -->

**子代理输出** → 写入 `$WS/07-delivery.md`（输出格式参照 `documentation-writer.md` 中的模板）

**最终提交**：
```bash
git add "$WS/07-delivery.md" [文档文件]
git commit -m "docs($FEATURE_NAME): 完成文档与交付"
```

**更新项目进度**（如属于多阶段项目）：
```
如果 .claude/workspace/_progress-*.md 中记录了本任务，更新对应子任务状态为"已完成"，
并记录 Workspace 路径和完成时间。如果所有子任务均已完成，标记项目整体为"已完成"。
```

---

## 检查点与恢复机制

每个阶段完成后自动执行 git commit 并写入 Workspace 文件，形成阶段快照。

### 从指定阶段恢复

查找 Workspace 目录 → 检查前序 Workspace 文件是否存在 → 全部存在则从指定阶段开始 → 缺失则提示先完成对应阶段。
恢复时子代理直接读取 Workspace 文件，不依赖对话历史，因此上下文完全可靠。

**失败处理**：阶段失败时将原因写入当前 Workspace 文件，提供修复建议，询问用户：重试 / 修改策略 / 跳过。代码审查和集成验证的修复循环最多 2 轮。

---

## 子代理一览

| 子代理 | 文件 | 模型 | 读取 | 写入 |
|--------|------|------|------|------|
| Requirements Analyst | `requirements-analyst.md` | Opus | 00-input | 01-requirements |
| System Designer | `system-designer.md` | Opus | 01-requirements | 02-design |
<!-- IF:testing -->
| Test Engineer | `test-engineer.md` | Sonnet | 01-requirements, 02-design | 03-testplan |
<!-- ENDIF:testing -->
<!-- IF:testing -->
| Code Engineer | `code-engineer.md` | Sonnet | 01↓, 02, 03 | 04-implementation |
| Code Reviewer | `code-reviewer.md` | Sonnet | 01↓, 02, 03↓, 04 | 05-review |
| Integration Validator | `integration-validator.md` | Sonnet | 01↓, 02↓, 03↓, 04↓, 05↓ | 06-validation |
<!-- ENDIF:testing -->
<!-- IF:NOT:testing -->
| Code Engineer | `code-engineer.md` | Sonnet | 01↓, 02 | 04-implementation |
| Code Reviewer | `code-reviewer.md` | Sonnet | 01↓, 02, 04 | 05-review |
| Integration Validator | `integration-validator.md` | Sonnet | 01↓, 02↓, 04↓, 05↓ | 06-validation |
<!-- ENDIF:NOT:testing -->
| Documentation Writer | `documentation-writer.md` | Sonnet | 01↓, 02, 04↓, 05↓, 06↓ | 07-delivery |

> `↓` = 通过下游摘要内联传入（非全文读取）
