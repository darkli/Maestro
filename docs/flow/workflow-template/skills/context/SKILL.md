---
name: context
description: 上下文管理：保存、加载、查看、清理跨对话的长期任务上下文。当用户说"保存上下文"、"加载上下文"、"查看上下文"、"清理对话记录"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash]
context: fork
version: 1.0.0
---

# 上下文管理 Skill

## 概述

管理跨多个对话的长期任务上下文。支持五个命令：

| 命令 | 用途 |
|------|------|
| `/context save [名称]` | 保存当前对话的上下文到持久化文件 |
| `/context load [名称]` | 加载指定上下文到当前对话 |
| `/context list` | 列出所有活跃的长期任务上下文 |
| `/context remove [名称]` | 删除指定的上下文文件 |
| `/context clean` | 清理未被上下文引用的对话记录（transcript） |

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

## 公共步骤：检测当前 transcript

所有需要 transcript 路径的命令，先执行此步骤：

```bash
# 项目路径 hash（将 / 和 _ 都替换为 -，去掉开头的 -）
PROJECT_HASH=$(echo "$PWD" | sed 's|[/_]|-|g' | sed 's|^-||')

# transcript 目录
TRANSCRIPT_DIR="$HOME/.claude/projects/-${PROJECT_HASH}"

# 当前 transcript = 最新修改的 .jsonl（仅顶层文件，不含子代理目录）
CURRENT=$(ls -t "$TRANSCRIPT_DIR"/*.jsonl 2>/dev/null | head -1)
```

如果 `$TRANSCRIPT_DIR` 不存在或无 .jsonl 文件，警告但继续执行，transcript 字段记为"（未找到）"。

---

## 命令 1：`/context save [名称]`

### 步骤 0：确定当前 transcript 路径

执行公共步骤，获取 `$CURRENT` transcript 路径。

### 步骤 1：确定上下文名称

**有名称参数：**
1. 检查 `.claude/context/<名称>.md` 是否存在
   - 存在 → 追加模式
   - 不存在 → 创建模式

**无名称参数：**
1. 检查当前 transcript 是否已被某个上下文文件引用
   ```bash
   # grep 所有上下文文件，查找当前 transcript 的 UUID
   grep -l "$(basename $CURRENT)" .claude/context/*.md 2>/dev/null
   ```
   - 已引用 → 使用该上下文文件名（等同于有名称的追加场景）
   - 未引用 → 分析当前对话内容，自动建议一个 kebab-case 名称，用 AskUserQuestion 让用户确认或修改

### 步骤 2：检查防重复

检查当前 transcript 的 UUID 是否已在该文件的 `## 会话日志` 中出现：
- 已存在 → 更新该日志条目 + 更新当前状态（不新增条目）
- 不存在 → 新增日志条目 + 更新当前状态

### 步骤 3：分析对话要点

分析本次对话的要点：
- 完成了什么
- 做了什么决策
- 涉及哪些关键文件（追加到关键文件列表，不删除已有条目）

### 步骤 4：写入文件

**创建模式**（文件不存在）：

创建 `.claude/context/<名称>.md`，填写完整模板：
- `# <任务名称>`：从对话内容中提取
- `## 背景`：一段话描述任务
- `## 关键文件`：本次涉及的文件
- `## 会话日志`：首条日志
- `## 当前状态`：当前进度和待办

**追加模式**（文件已存在）：

1. 读取现有文件
2. 在 `## 关键文件` 中追加新文件（去重，不删除已有条目）
3. 定位 `^## 当前状态` 行，在该行正上方插入新的会话日志条目（或更新已有条目），前后各保留一个空行。若未找到 `## 当前状态`，追加到文件末尾并补全 `## 当前状态` 节
4. 覆盖 `## 当前状态` 下的全部内容（从该标题行的下一行到文件末尾或下一个 `##` 标题之前）

### 步骤 5：输出确认

```
上下文已保存到 .claude/context/<名称>.md
- 模式：创建 / 追加
- transcript: <路径>
- 本次记录：<完成要点摘要>
```

---

## 命令 2：`/context load [名称]`

### 有名称参数

1. 检查 `.claude/context/<名称>.md` 是否存在
   - 不存在 → 输出错误信息并结束
   - 存在 → 读取文件完整内容
2. 输出上下文摘要：
   - 任务名称（`#` 标题）
   - 背景（`## 背景` 内容）
   - 当前状态（`## 当前状态` 内容）
   - 关键文件列表（`## 关键文件` 内容）
   - 最近一条会话日志
3. 输出确认：
   ```
   已加载上下文：<名称>
   - 会话数：N
   - 最后更新：YYYY-MM-DD
   - 当前状态：<进度摘要>
   ```

### 无名称参数

1. 列出 `.claude/context/` 下所有 `.md` 文件
   - 无文件 → 输出"没有上下文文件"并结束
   - 仅 1 个文件 → 直接加载该文件
   - 多个文件 → 用 AskUserQuestion 让用户选择加载哪个
2. 后续同有名称流程

---

## 命令 3：`/context list`

### 步骤 1：扫描上下文文件

```bash
ls .claude/context/*.md 2>/dev/null
```

无文件 → 输出"没有上下文文件"并结束。

### 步骤 2：提取摘要

对每个 `.md` 文件，提取：
- **名称**：文件名（去掉 `.md` 后缀）
- **当前状态**：`## 当前状态` 下 `- 进度：` 行的内容（去掉 `- 进度：` 前缀）
- **会话数**：`### YYYY-MM-DD 会话` 标题的数量
- **最后更新**：最后一条会话日志的日期

### 步骤 3：表格输出

```
| 名称 | 当前状态 | 会话数 | 最后更新 |
|------|----------|--------|----------|
| workflow-template | 模板提取和 review 已完成 | 3 | 2026-02-22 |
```

---

## 命令 4：`/context remove [名称]`

### 有名称参数

1. 检查 `.claude/context/<名称>.md` 是否存在
   - 不存在 → 输出错误信息并结束
   - 存在 → 用 AskUserQuestion 确认删除
2. 确认后删除文件

### 无名称参数

1. 列出 `.claude/context/` 下所有 `.md` 文件
   - 无文件 → 输出"没有上下文文件"并结束
   - 有文件 → 用 AskUserQuestion 让用户选择删除哪个
2. 确认后删除

---

## 命令 5：`/context clean`

### 步骤 1：确定 transcript 目录

```bash
PROJECT_HASH=$(echo "$PWD" | sed 's|[/_]|-|g' | sed 's|^-||')
TRANSCRIPT_DIR="$HOME/.claude/projects/-${PROJECT_HASH}"
```

如果目录不存在 → 输出"未找到 transcript 目录"并结束。

### 步骤 2：收集被引用的 transcript

```bash
# 从所有上下文文件中提取 transcript 路径中的文件名（UUID 部分）
grep -h "transcript:" .claude/context/*.md 2>/dev/null | grep -oiE '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.jsonl'
```

得到"被引用的 transcript 集合"。

### 步骤 3：列出全部 transcript

```bash
# 仅扫描顶层 .jsonl 文件（子代理 transcript 在同名子目录中，随主文件一起清理）
ls "$TRANSCRIPT_DIR"/*.jsonl 2>/dev/null
```

得到"全部 transcript 集合"。

### 步骤 4：计算可清理列表

差集 = 全部 - 被引用 - 当前正在使用的（修改时间最新的那个）

注意：**跳过当前正在使用的 transcript**（修改时间最新的 .jsonl 文件），即使它未被任何上下文引用。

### 步骤 5：展示并确认

如果差集为空 → 输出"所有对话记录均被引用或为当前会话，无需清理"并结束。

否则展示列表：
- 每个文件显示：文件名、大小、最后修改日期
- 如果该文件有同名子目录（子代理 transcript），显示子目录大小
- 显示总数和总大小
- 输出安全提示："以下 transcript 未被任何上下文文件引用。如果有未保存的工作，请先执行 `/context save` 再清理。"
- 用 AskUserQuestion 确认是否删除

### 步骤 6：执行清理

确认后批量删除可清理的 transcript 文件及其同名子目录（子代理 transcript）：
```bash
# 对每个待清理的 transcript 文件
rm "$file"
rm -rf "${file%.jsonl}/"   # 清理对应的子代理目录（如果存在）
```

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
