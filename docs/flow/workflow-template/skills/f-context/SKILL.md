---
name: f-context
description: 上下文管理：保存、加载、查看、清理跨对话的长期任务上下文。当用户说"保存上下文"、"加载上下文"、"查看上下文"、"清理对话记录"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash]
context: fork
version: 2.0.0
---

# 上下文管理 Skill

## 概述

管理跨多个对话的长期任务上下文。支持五个命令：

| 命令 | 用途 |
|------|------|
| `/f-context save [名称]` | 保存当前对话的上下文到持久化文件 |
| `/f-context load [名称]` | 加载指定上下文到当前对话 |
| `/f-context list` | 列出所有活跃的长期任务上下文 |
| `/f-context remove [名称]` | 删除指定的上下文文件 |
| `/f-context clean` | 清理未被上下文引用的对话记录（transcript） |

## 前置检查

如果 `.claude/scripts/context.sh` 不存在，提示"请先运行 /f-init 安装脚本"并退出。

## 上下文文件格式

存储位置：`.claude/context/<名称>.md`

命名规范：kebab-case，无空格（如 `workflow-template`、`user-auth-refactor`）

```markdown
# <任务名称>

## 背景
[一段话描述任务是什么，首次创建时写入]

## 关键文件
- path/to/file1 — 说明
- path/to/file2 — 说明
（每次 save 时可追加新文件，不删除已有条目）

## 会话日志

### YYYY-MM-DD 会话 N
- 完成：...
- 决策：...
- transcript: ~/.claude/projects/.../<uuid>.jsonl

（更早的日志在上方，新日志追加在本节末尾、"当前状态"之前）

## 当前状态
- 进度：...
- 待办：...
```

设计要点：
- **会话日志**：只追加不改写，每次 save 在 `## 当前状态` 之前插入新条目
- **当前状态**：每次 save 时覆盖更新（这是文件中唯一被覆盖的部分）
- **关键文件**：可追加，不删除已有条目
- **transcript 路径**：记录在日志条目中，供 clean 命令扫描
- **防重复**：如果同一对话中多次调用 save，检测到当前 transcript 已存在于日志中时，更新该条目而非新增

---

## 命令 1：`/f-context save [名称]`

### 步骤 1：脚本准备

```bash
bash .claude/scripts/context.sh save-prepare --name="<名称>"
```

解析 JSON 输出，获取 `mode`（create/append/update）、`path`、`transcript`、`existing_name`、`dedup`。

- 如果无名称参数且 `existing_name` 为空 → 先执行 `bash .claude/scripts/context.sh list` 检查文件数量：仅 1 个 → 自动使用该文件名；多个 → AskUserQuestion 让用户选择；0 个 → 分析对话内容建议 kebab-case 名称，用 AskUserQuestion 确认
- 如果 `mode=update`（dedup=true）→ 更新已有日志条目而非新增

### 步骤 2：分析对话要点（LLM 任务，不可替代）

分析本次对话的要点：
- 完成了什么
- 做了什么决策
- 涉及哪些关键文件

### 步骤 3：写入文件

根据 mode 使用 Write/Edit 工具写入文件：
- **create** → 创建完整模板（# 标题 / ## 背景 / ## 关键文件 / ## 会话日志 / ## 当前状态）
- **append** → 在 `## 当前状态` 前插入新日志条目，覆盖当前状态
- **update** → 更新已有日志条目 + 覆盖当前状态

### 步骤 4：输出确认

```
上下文已保存到 .claude/context/<名称>.md
- 模式：创建 / 追加
- transcript: <路径>
- 本次记录：<完成要点摘要>
```

---

## 命令 2：`/f-context load [名称]`

### 有名称参数

```bash
bash .claude/scripts/context.sh load "<名称>"
```

解析 [OUTPUT:MD] 输出，直接展示给用户。

### 无名称参数

```bash
bash .claude/scripts/context.sh list
```

解析 [OUTPUT:MD] 获取上下文列表。
- 无文件 → 输出"没有上下文文件"并结束
- 仅 1 个文件 → 直接加载
- 多个 → AskUserQuestion 让用户选择

---

## 命令 3：`/f-context list`

```bash
bash .claude/scripts/context.sh list
```

解析 [OUTPUT:MD] 输出，直接展示表格。如果输出包含 `[INFO] 没有上下文文件`，告知用户并结束。

---

## 命令 4：`/f-context remove [名称]`

### 有名称参数

```bash
bash .claude/scripts/context.sh remove "<名称>"
```

解析 JSON 输出的 `exists` 字段：
- false → 输出错误信息
- true → AskUserQuestion 确认 → 确认后执行 `bash .claude/scripts/context.sh remove "<名称>" --confirm`

### 无名称参数

先执行 list 获取列表，用 AskUserQuestion 让用户选择后执行 remove。

---

## 命令 5：`/f-context clean`

```bash
bash .claude/scripts/context.sh clean
```

解析 JSON 输出：
- `cleanable` 为空 → 输出"所有对话记录均被引用或为当前会话，无需清理"
- 非空 → 展示可清理列表（文件名、大小）和安全提示 → AskUserQuestion 确认 → 确认后执行 `bash .claude/scripts/context.sh clean --confirm`

---

## 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| transcript 目录不存在 | 警告但继续执行，transcript 字段记为"（未找到）" |
| 同一对话多次 save | 检测 transcript UUID 已存在 → 更新该条目而非新增 |
| save 无名称且无法自动关联 | 分析对话内容建议名称 → AskUserQuestion 确认 |
| clean 时无上下文文件 | 视为全部 transcript 都可清理（除当前），展示列表让用户确认 |
| clean 时全部 transcript 都被引用 | 提示"所有对话记录均被引用，无需清理" |
| remove 后 transcript 变成未引用 | 不自动清理，下次 clean 时处理 |
| 关键文件路径变更 | save 时可追加新路径，旧路径不自动删除（用户手动编辑） |
| `.claude/context/` 目录不存在 | save 时自动创建（`mkdir -p`），list/remove/clean 时提示"没有上下文文件" |
| 追加模式下 `## 当前状态` 缺失 | 追加到文件末尾并补全 `## 当前状态` 节 |
