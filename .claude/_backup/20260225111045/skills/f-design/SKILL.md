---
name: f-design
description: 需求分析与系统设计：只做方案不写代码。当用户说"分析需求"、"设计方案"、"可行性分析"、"技术选型"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 1.2.0
---

# 需求分析与系统设计 Skill

## 概述

本 Skill 只执行 **2 个阶段**：需求分析和系统设计。不写代码、不跑测试，专注于输出高质量的需求文档和设计方案。适合前期规划、可行性分析、技术选型等场景。

**产出可衔接后续开发**：完成后的 Workspace 包含 01-requirements.md 和 02-design.md，可直接被 `/f-dev` 或 `/f-light-dev` 从后续阶段继续。

## Workspace 工作记忆

### 目录结构

```
.claude/workspace/design-YYYYMMDD-$NAME/
├── 00-input.md              # Skill 记录用户原始需求
├── 01-requirements.md       # 阶段 1 输出（完整需求文档）
└── 02-design.md             # 阶段 2 输出（完整设计方案）
```

### 核心规则

与 f-dev 相同：
1. 每个子代理的 prompt 必须指定读哪些 Workspace 文件
2. 每个子代理完成后必须将产出摘要写入对应的 Workspace 文件

## 流程总览

```
初始化              阶段 1         阶段 2
创建 Workspace ──→ 需求分析 ──→  系统设计  ──→ 完成
  │                  │              │
  ▼                  ▼              ▼
00-input.md    01-requirements.md  02-design.md
  │                  │              │
                    ⏸ 确认        ⏸ 确认
```

## 用户确认策略

**2 个确认点**：

| 确认点 | 位置 | 确认内容 |
|--------|------|----------|
| **需求确认** | 阶段 1 → 2 | 需求理解是否准确、验收标准是否完整 |
| **设计确认** | 阶段 2 → 完成 | 架构方案、技术选型、接口设计是否合理 |

**确认时的用户选项**：
- **确认通过** → 继续 / 完成
- **要求修改** → 说明修改意见，回到当前阶段重新执行
- **终止流程** → 保留 Workspace 已有产物

---

## 前置步骤：初始化 Workspace

执行初始化脚本：

```bash
bash .claude/scripts/dev-init.sh --type=design --name="$FEATURE_NAME" --input="$USER_INPUT"
```

解析 JSON 输出：
- `workspace` → 赋值给 `$WS`，后续所有阶段使用此路径
- `upstream_detected` → 非 null 时在阶段 1 子代理 prompt 中补充上游引用
- `available_upstreams` → 非空时询问用户是否使用某个上游产品设计
- `warnings` → 非空时展示给用户
- `progress_updated` → 为 true 时告知用户已更新项目进度

将 `$WS` 路径传递给后续每个子代理。

---

## 阶段 1：需求分析

**目标**：理解并文档化功能需求

**子代理**：Requirements Analyst（`requirements-analyst.md`，Opus）

**子代理输入**：
- 读取 `$WS/00-input.md`（用户原始需求）
- 读取 `$WS/00-context.md`（项目上下文）

**执行步骤**：
1. 读取 `$WS/00-input.md` 中的用户需求原文
2. 与用户交互澄清需求（如有歧义）
3. 识别核心功能点、边界情况、约束条件
4. 定义可测试的验收标准
5. 评估对现有模块的影响范围

**子代理输出** → 写入 `$WS/01-requirements.md`：
```markdown
# 需求分析：$FEATURE_NAME

## 功能概述
[一段话描述]

## 核心功能点
- [ ] 功能点 1：描述 + 验收标准
- [ ] 功能点 2：描述 + 验收标准
...

## 边界情况
- 场景 1：...

## 非功能需求
- 性能：...
- 安全：...

## 约束条件
- 技术约束：...

## 影响范围
- 影响的现有模块：...
- 需要修改的文件：...

## 验收标准汇总
- [ ] 标准 1
- [ ] 标准 2
...

## 风险评估
- 风险 1：[描述] → [应对策略]
```

**检查点**：
```bash
git add "$WS/00-input.md" "$WS/01-requirements.md"
git commit -m "docs($FEATURE_NAME): 完成需求分析"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/01-requirements.md` 已创建
- [ ] 验收标准已定义
- [ ] 用户确认需求理解无误

---

## 阶段 2：系统设计

**目标**：设计技术架构和接口

**子代理**：System Designer（`system-designer.md`，Opus）

**子代理输入**：
- 读取 `$WS/01-requirements.md`（需求文档）
- 读取 `$WS/00-context.md`（项目规范）
- 读取 CLAUDE.md 中 Architecture 部分引用的核心代码文件（如类型定义、API 调用模块）

**执行步骤**：
1. 读取 `$WS/01-requirements.md`，逐条对照需求
2. 分析现有代码库结构
3. 设计架构（组件划分、数据流、接口定义）
4. 绘制架构图（Mermaid）
5. 需求覆盖检查

**子代理输出** → 写入 `$WS/02-design.md`：
```markdown
# 系统设计：$FEATURE_NAME

## 架构概览
[Mermaid 架构图]

## 模块划分
- 模块 A：职责、文件位置
- 模块 B：职责、文件位置

## API 接口定义
| 端点 | 方法 | 请求 | 响应 | 描述 |
|------|------|------|------|------|

## 数据模型
[TypeScript interface 定义]

## 数据库设计（如适用）
[数据库建表语句（如适用）]

## 前后端契约
[需要新增的共享类型定义]

## 关键设计决策
| 决策点 | 选项 | 选择 | 理由 |
|--------|------|------|------|

## 文件结构
[新增/修改文件清单]

## 安全设计
- 认证：...
- 授权：...

## 需求覆盖检查
- [ ] 功能点 1 → 由模块 A 实现
- [ ] 功能点 2 → 由模块 B 实现
...（与 01-requirements.md 逐条对应）
```

**检查点**：
```bash
git add "$WS/02-design.md"
git commit -m "docs($FEATURE_NAME): 完成系统设计"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/02-design.md` 已创建
- [ ] 架构图已生成
- [ ] 接口已定义
- [ ] 数据模型合理
- [ ] 用户确认设计方案

---

## 完成与后续衔接

设计完成后，检查 `$WS/02-design.md` 是否包含多阶段实施计划：

**如果设计方案建议拆分为多个子任务**，创建项目进度文件：

```bash
# 从 $FEATURE_NAME 提取项目名
PROGRESS_FILE=".claude/workspace/_progress-$FEATURE_NAME.md"
```

写入进度文件（格式与 CLAUDE.md 中 Multi-Phase Project Tracking 一致）：
```markdown
# 项目进度：$FEATURE_NAME

**创建时间**: YYYY-MM-DD
**整体设计**: .claude/workspace/design-YYYYMMDD-$FEATURE_NAME/02-design.md

## 子任务

### 1. [从 02-design.md 的实施阶段中提取]
- **状态**: 待执行
- **Workspace**: （执行时填写）
- **进度**: 未开始
- **备注**: 无

### 2. ...
- **状态**: 待执行
- **依赖**: 子任务 1
- **进度**: 未开始
- **备注**: 无
```

**然后输出总结**：

```
设计完成！产出文件：
- 需求文档：$WS/01-requirements.md
- 设计方案：$WS/02-design.md
- 项目进度：.claude/workspace/_progress-$FEATURE_NAME.md（多阶段项目）

后续只需说"继续做"或"继续 $FEATURE_NAME"，将自动读取进度文件确定下一步。
```

**如果是单次可完成的任务**（无需拆分），直接输出：

```
设计完成！产出文件：
- 需求文档：$WS/01-requirements.md
- 设计方案：$WS/02-design.md

如需继续开发，可使用以下命令：
- 完整开发：/f-dev 从阶段 3 继续，Workspace: $WS
- 轻量开发：/f-light-dev 从阶段 2 继续，Workspace: $WS
```

---

## 子代理一览

| 子代理 | 文件 | 模型 | 阶段 | 读取 | 写入 |
|--------|------|------|------|------|------|
| Requirements Analyst | `requirements-analyst.md` | Opus | 1 | 00-input | 01-requirements |
| System Designer | `system-designer.md` | Opus | 2 | 01-requirements | 02-design |

---

## 适用场景

- 前期方案规划（如"评估是否应该加用户角色系统"）
- 技术选型讨论（如"分析 WebSocket vs SSE 的方案"）
- 可行性分析（如"评估数据库迁移方案的影响"）
- 大功能前的方案设计（先设计再决定是否开发）
- 重构方案设计（如"设计前端状态管理的重构方案"）

不适合：
- 需要写代码的任务 → 用 `/f-dev`、`/f-light-dev` 或 `/f-bugfix`
- 代码分析讨论 → 直接与 Claude 对话
