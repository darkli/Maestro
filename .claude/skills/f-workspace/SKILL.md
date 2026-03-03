---
name: f-workspace
description: Workspace 管理：查看和清理工作流产物目录。当用户说"查看 workspace"、"清理 workspace"、"workspace 列表"时使用。
version: 2.1.0
---

# Workspace 管理 Skill

## 概述

管理 `.claude/workspace/` 下的工作流产物目录。支持两个命令：

| 命令 | 用途 |
|------|------|
| `/f-workspace list` | 列出所有 workspace，显示类型、日期、进度、大小、状态 |
| `/f-workspace clean` | 交互式清理已完成且未被引用的 workspace 目录 |

## 前置检查

如果 `.claude/scripts/workspace.sh` 不存在，提示"请先运行 /f-init 安装脚本"并退出。

---

## 命令 1：`/f-workspace list`

```bash
bash .claude/scripts/workspace.sh list
```

解析 [OUTPUT:MD] 输出，直接展示表格。如果输出包含 `[INFO] 没有 workspace`，告知用户并结束。

---

## 命令 2：`/f-workspace clean`

```bash
bash .claude/scripts/workspace.sh clean
```

解析 JSON 输出：
- 如果 `cleanable` 为空 → 输出"所有 workspace 均在使用中，无需清理"
- 如果有受保护目录，先展示受保护列表
- 展示可清理目录表格（目录名、文件数、大小、最后修改）和总大小

使用 AskUserQuestion 确认：
- **全部清理** — 执行 `bash .claude/scripts/workspace.sh clean --confirm`
- **选择保留** — 列出可清理目录让用户选择保留的（其余手动 `rm -rf`）
- **取消** — 不做任何操作

展示清理结果。

---

## 保护机制

| 对象 | 原因 |
|------|------|
| `_progress-*.md` 文件 | 项目追踪文件，不是 workspace 产物 |
| 散文件（非目录） | 不在清理范围，只处理目录 |
| 被 `_progress-*.md` 引用且状态非"已完成"的目录 | 任务仍在进行中 |

注意：状态为"已完成"的 workspace 目录**可以被清理**。

---

## 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| `.claude/workspace/` 不存在 | 输出"没有 workspace 目录"并结束 |
| 目录为空或只有 `_progress-*.md` 文件 | 输出"没有可清理的 workspace"并结束 |
| 全部目录都受保护 | 展示受保护列表，输出"所有 workspace 均在使用中" |
| 无 `_progress-*.md` 文件 | 所有子目录都视为可清理 |
| 目录名不符合 `type-YYYYMMDD-name` 格式 | 类型标记为"其他"，日期标记为"未知"，仍可正常清理 |
