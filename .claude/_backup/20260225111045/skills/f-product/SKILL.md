---
name: f-product
description: 产品设计：从模糊想法到 PRD。当用户说"产品设计"、"定义产品"、"PRD"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 1.1.0
---

# 产品设计 Skill

## 概述

本 Skill 执行 **3 个阶段**：问题定义、方案设计、功能规格（PRD）。不写代码、不做技术设计，专注于从产品经理视角定义"做什么"和"为什么做"。适合从模糊想法出发、需要先理清产品方案再进入技术设计的场景。

**产出可衔接后续技术设计**：完成后的 Workspace 包含 03-spec.md（PRD），可直接被 `/f-design` 作为上游输入，进入需求分析和系统设计。

## Workspace 工作记忆

### 目录结构

```
.claude/workspace/product-YYYYMMDD-$NAME/
├── 00-input.md              # Skill 记录用户原始想法
├── 00-context.md            # 项目上下文（Capabilities 等）
├── 01-problem.md            # 阶段 1 输出（问题定义）
├── 02-solution.md           # 阶段 2 输出（方案设计）
└── 03-spec.md               # 阶段 3 输出（PRD）
```

### 核心规则

1. **每个阶段的 prompt 必须指定读哪些 Workspace 文件**，写 "读取 `$WS/01-problem.md`"，绝不写 "基于前面的分析"
2. **每个阶段完成后必须将产出写入对应的 Workspace 文件**，确保下游有明确的输入源
3. **Workspace 目录在流程结束后保留**，作为产品设计的完整归档

### 命名规范

```
product-YYYYMMDD-短名称

示例：
  product-20260225-server-monitor
  product-20260301-user-dashboard
  product-20260315-api-gateway
```

## 流程总览

```
初始化              阶段 1         阶段 2         阶段 3
创建 Workspace ──→ 问题定义 ──→  方案设计  ──→  功能规格  ──→ 完成
  │                  │              │              │
  ▼                  ▼              ▼              ▼
00-input.md      01-problem.md  02-solution.md  03-spec.md
  │                  │              │              │
                    ⏸ 确认        ⏸ 确认        ⏸ 确认
```

## 用户确认策略

**3 个确认点**：

| 确认点 | 位置 | 确认内容 |
|--------|------|----------|
| **问题确认** | 阶段 1 → 2 | 核心问题是否准确、目标用户是否正确、使用场景是否覆盖 |
| **方案确认** | 阶段 2 → 3 | 交互流程是否合理、设计方案是否可行、状态覆盖是否完整 |
| **规格确认** | 阶段 3 → 完成 | 功能清单优先级是否合理、MVP 范围是否恰当、验收标准是否明确 |

**确认时的用户选项**：
- **确认通过** → 继续 / 完成
- **要求修改** → 说明修改意见，回到当前阶段重新执行
- **终止流程** → 保留 Workspace 已有产物

---

## 前置步骤：初始化 Workspace

### 脚本初始化

执行初始化脚本：

```bash
bash .claude/scripts/dev-init.sh --type=product --name="$FEATURE_NAME" --input="$USER_INPUT"
```

解析 JSON 输出：
- `workspace` → 赋值给 `$WS`，后续所有阶段使用此路径
- `warnings` → 非空时展示给用户（如"Testing section 未找到"）
- `capabilities` → 用于判断项目类型（前端/后端/全栈），影响阶段 2 方案设计
- `progress_updated` → 为 true 时告知用户已更新项目进度

将 `$WS` 路径传递给后续每个子代理。

---

## 阶段 1：问题定义（Problem Definition）

**目标**：从模糊想法中提炼清晰的问题、用户和场景

**子代理**：Product Designer（`product-designer.md`，Opus）

**子代理输入**：
- 读取 `$WS/00-input.md`（用户原始想法）
- 读取 `$WS/00-context.md`（项目上下文）

**执行步骤**：
1. 读取 `$WS/00-input.md` 中的用户想法原文
2. 读取 `$WS/00-context.md` 了解项目现状
3. 提炼核心问题（区分问题和解决方案）
4. 识别目标用户画像和典型使用场景
5. 定义可衡量的成功指标
6. 梳理项目已有的可复用能力

**子代理输出** → 写入 `$WS/01-problem.md`（输出格式参照 `product-designer.md` 中的模板）

**检查点**（使用 `docs()` 前缀，因为产品设计只产出文档不写代码）：
```bash
git add "$WS/00-input.md" "$WS/00-context.md" "$WS/01-problem.md"
git commit -m "docs($FEATURE_NAME): 完成问题定义"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/01-problem.md` 已创建
- [ ] 核心问题清晰
- [ ] 目标用户已识别
- [ ] 用户确认问题定义无误

---

## 阶段 2：方案设计（Solution Design）

**目标**：设计产品方案，确定交互流程和信息架构

**子代理**：Product Designer（`product-designer.md`，Opus）

**子代理输入**：
- 读取 `$WS/01-problem.md`（问题定义）
- 读取 `$WS/00-context.md`（项目上下文，含 Capabilities 标签用于项目类型适配）

**执行步骤**：
1. 读取 `$WS/01-problem.md`，确认问题和场景
2. 根据 `$WS/00-context.md` 的 Capabilities 判断项目类型（前端/后端/全栈/CLI）
3. 按项目类型设计对应维度的方案（以下为各类型要点概览，详细步骤见 `product-designer.md`）：



**通用项目**：
- 功能流程、输入输出设计、错误处理

4. 设计数据展示方案和权限视角
5. 记录关键设计决策及理由

**子代理输出** → 写入 `$WS/02-solution.md`（输出格式参照 `product-designer.md` 中的模板）

**检查点**：
```bash
git add "$WS/02-solution.md"
git commit -m "docs($FEATURE_NAME): 完成方案设计"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/02-solution.md` 已创建
- [ ] 交互流程/功能流程已设计
- [ ] 状态矩阵/输入输出无遗漏
- [ ] 用户确认方案可行

---

## 阶段 3：功能规格（Product Specification）

**目标**：输出结构化 PRD，明确功能范围和验收标准

**子代理**：Product Designer（`product-designer.md`，Opus）

**Skill 预读**：读取 `$WS/01-problem.md` 的 `## 下游摘要` 节（核心问题+用户+场景+指标，避免子代理重复全文读取）

**子代理输入**：
- [内联] `$WS/01-problem.md` 下游摘要（核心问题+用户+场景+指标）
- 读取 `$WS/02-solution.md`（方案设计全文）
- 读取 `$WS/00-context.md`（项目约束）

**执行步骤**：
1. 读取 `$WS/02-solution.md`，从方案中提取功能点
2. 按 MoSCoW 标注优先级
3. 划定 MVP 范围
4. 为每个 Must Have 功能定义验收标准
5. 梳理功能间的依赖关系
6. 识别风险和假设

**子代理输出** → 写入 `$WS/03-spec.md`（输出格式参照 `product-designer.md` 中的模板）

**检查点**：
```bash
git add "$WS/03-spec.md"
git commit -m "docs($FEATURE_NAME): 完成产品规格（PRD）"
```

**⏸ 阶段门禁**（需用户确认）：
- [ ] `$WS/03-spec.md` 已创建
- [ ] 功能清单按 MoSCoW 分类
- [ ] MVP 范围明确
- [ ] 验收标准已定义
- [ ] 用户确认产品规格

---

## 完成与后续衔接

产品设计完成后，输出总结：

```
产品设计完成！产出文件：
- 问题定义：$WS/01-problem.md
- 方案设计：$WS/02-solution.md
- 产品规格：$WS/03-spec.md

如需继续技术设计和开发，可使用以下命令：
- 技术设计：/f-design（上游 Workspace: $WS）
- 完整开发：/f-dev（上游 Workspace: $WS）
- 轻量开发：/f-light-dev（上游 Workspace: $WS）
```

**更新项目进度**（如属于多阶段项目）：
```
如果 .claude/workspace/_progress-*.md 中记录了本任务，更新对应子任务状态为"已完成"，
并记录 Workspace 路径和完成时间。
```

---

## 检查点与恢复机制

每个阶段完成后自动执行 git commit 并写入 Workspace 文件，形成阶段快照。

### 从指定阶段恢复

查找 Workspace 目录 → 检查前序 Workspace 文件是否存在 → 全部存在则从指定阶段开始 → 缺失则提示先完成对应阶段。
恢复时子代理直接读取 Workspace 文件，不依赖对话历史，因此上下文完全可靠。

**失败处理**：阶段失败时将原因写入当前 Workspace 文件，提供修复建议，询问用户：重试 / 修改策略 / 终止。

---

## 子代理一览

| 子代理 | 文件 | 模型 | 阶段 | 读取 | 写入 |
|--------|------|------|------|------|------|
| Product Designer | `product-designer.md` | Opus | 1 | 00-input | 01-problem |
| Product Designer | `product-designer.md` | Opus | 2 | 01-problem | 02-solution |
| Product Designer | `product-designer.md` | Opus | 3 | 01↓, 02 | 03-spec |

> `↓` = 通过下游摘要内联传入（非全文读取）

---

## 适用场景

- 模糊想法具体化（如"我想做一个监控面板"）
- 新功能的产品定义（先定义再设计再开发）
- 产品方案评审（只产出 PRD 不写代码）
- MVP 范围划定（如"这个功能先做哪些"）
- 复杂功能的前期拆解（如"用户权限系统怎么定义"）

不适合：
- 已有明确需求直接做技术设计 → 用 `/f-design`
- 已有设计方案直接写代码 → 用 `/f-dev`、`/f-light-dev`、`/f-quick-dev`
- Bug 修复 → 用 `/f-bugfix`
