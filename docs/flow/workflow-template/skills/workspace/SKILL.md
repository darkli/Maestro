---
name: workspace
description: Workspace 管理：查看和清理工作流产物目录。当用户说"查看 workspace"、"清理 workspace"、"workspace 列表"时使用。
tools: [Read, Grep, Glob, Bash]
context: fork
version: 1.0.0
---

# Workspace 管理 Skill

## 概述

管理 `.claude/workspace/` 下的工作流产物目录。支持两个命令：

| 命令 | 用途 |
|------|------|
| `/workspace list` | 列出所有 workspace，显示类型、日期、进度、大小、状态 |
| `/workspace clean` | 交互式清理已完成且未被引用的 workspace 目录 |

---

## 保护机制（clean 时不清理的对象）

| 对象 | 原因 |
|------|------|
| `_progress-*.md` 文件 | 项目追踪文件，不是 workspace 产物 |
| 散文件（非目录） | 不在清理范围，只处理目录 |
| 被 `_progress-*.md` 引用且对应子任务状态非"已完成"的目录 | 任务仍在进行中 |

注意：对应子任务状态为"已完成"的 workspace 目录**可以被清理**。

---

## 命令 1：`/workspace list`

### 步骤 1：扫描 workspace

列出 `.claude/workspace/` 下所有子目录。

如果目录不存在或为空 → 输出"没有 workspace"并结束。

### 步骤 2：提取每个 workspace 的信息

对每个子目录提取以下信息：

- **类型**：从目录名前缀推断（`feature` / `bugfix` / `design` / `doc`，无匹配前缀则标记为"其他"）
- **日期**：从目录名中提取 `YYYYMMDD` 部分
- **进度**：根据类型检查 Workspace 文件存在情况，推算当前阶段：
  - `doc` 类型：检查 `00-input.md` 到 `05-review.md`（共 6 个文件，阶段数 5），显示如"阶段 3/5"
  - 其他类型：检查 `00-input.md` 到 `07-delivery.md`（共 8 个文件，阶段数 7），显示如"阶段 4/7"
- **大小**：使用 `du -sh` 获取目录大小
- **状态**：检查是否被 `_progress-*.md` 引用：
  - 被引用且对应子任务状态非"已完成" → "受保护"
  - 被引用且对应子任务状态为"已完成" → "可清理"
  - 未被引用 → "可清理"

### 步骤 3：表格输出

```
| 目录名 | 类型 | 日期 | 进度 | 大小 | 状态 |
|--------|------|------|------|------|------|
| feature-20260220-user-auth | feature | 2026-02-20 | 阶段 7/7 | 128K | 可清理 |
| bugfix-20260221-upload-fix | bugfix | 2026-02-21 | 阶段 4/4 | 64K | 可清理 |
| doc-20260223-skill-upgrade | doc | 2026-02-23 | 阶段 5/5 | 48K | 可清理 |
| design-20260222-zustand | design | 2026-02-22 | 阶段 2/2 | 32K | 受保护 |
```

---

## 命令 2：`/workspace clean`

### 步骤 1：扫描 workspace

列出 `.claude/workspace/` 下所有子目录。

排除规则：
- 排除 `_progress-*.md` 文件（项目追踪文件）
- 排除散文件（非目录）

如果目录不存在或无子目录 → 输出"没有 workspace 目录"并结束。

### 步骤 2：收集受保护的 workspace

扫描 `.claude/workspace/_progress-*.md` 中的 `Workspace:` 字段：

```bash
grep -h "Workspace:" .claude/workspace/_progress-*.md 2>/dev/null
```

对每个提取到的路径：
1. 定位路径对应的目录名
2. 检查该条目所属子任务的状态（在 `Workspace:` 行的上方查找 `**状态**:` 行）
3. 仅当状态为"进行中"、"待执行"或"已阻塞"时，将该目录标记为受保护

状态为"已完成"的目录**不受保护**，可以被清理。

### 步骤 3：计算可清理列表

可清理 = 全部子目录 - 受保护目录

### 步骤 4：展示并确认

展示两部分信息：

**受保护目录**（如有）：
```
受保护的 workspace（不会被清理）：
- design-20260222-zustand — 进行中（_progress-zustand-migration.md）
```

**可清理目录**：
```
可清理的 workspace：
| 目录名 | 文件数 | 大小 | 最后修改 |
|--------|--------|------|----------|
| feature-20260220-user-auth | 8 个文件 | 128K | 2026-02-20 |
| bugfix-20260221-upload-fix | 5 个文件 | 64K | 2026-02-21 |

共 2 个目录，可释放约 192K 空间
```

如果可清理列表为空 → 输出"所有 workspace 均在使用中，无需清理"并结束。

使用 AskUserQuestion 确认：
- **全部清理** — 删除上述所有可清理目录
- **选择保留** — 列出可清理目录，让用户选择要保留的（其余删除）
- **取消** — 不做任何操作

### 步骤 5：执行清理

根据用户选择，使用 `rm -rf` 删除确认的目录。

输出清理结果：
```
清理完成：
- 已删除：2 个 workspace 目录
- 释放空间：192K
- 保留：1 个受保护目录
```

---

## 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| `.claude/workspace/` 不存在 | 输出"没有 workspace 目录"并结束 |
| 目录为空或只有 `_progress-*.md` 文件 | 输出"没有可清理的 workspace"并结束 |
| 全部目录都受保护 | 展示受保护列表，输出"所有 workspace 均在使用中" |
| 无 `_progress-*.md` 文件 | 所有子目录都视为可清理 |
| 目录名不符合 `type-YYYYMMDD-name` 格式 | 类型标记为"其他"，日期标记为"未知"，仍可正常清理 |
