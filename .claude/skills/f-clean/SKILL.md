---
name: f-clean
description: 工作流清理：删除所有已安装的 Skills、Hooks 和配置文件，保留 f-init 和用户数据，为重新初始化做准备。当用户说"清理工作流"、"重置工作流"、"删除工作流文件"时使用。
version: 2.1.0
---

# 工作流清理 Skill

## 概述

本 Skill 清理所有已安装的工作流文件（Skills、Hooks、Scripts、settings.json），保留 f-init 初始化工具和用户数据（context、workspace），为重新执行 `/f-init` 做准备。

**注意**：f-clean 运行时会删除 `.claude/skills/`（包括自身），这是预期行为。下次 `/f-init` 会重新安装它。

## 前置检查

如果 `.claude/scripts/clean.sh` 不存在，提示"请先运行 /f-init 安装脚本"并退出。

## 执行流程

### 步骤 1：扫描目标

```bash
bash .claude/scripts/clean.sh scan
```

解析 JSON 输出，获取 `delete`（将删除列表）和 `preserve`（将保留列表）。

### 步骤 2：展示清单

以表格分别展示"将删除"和"将保留"两类，请用户确认。

**将删除**：遍历 `delete` 数组，展示路径、内容、状态（exists 为 false 时显示"不存在（跳过）"）。
**将保留**：遍历 `preserve` 数组，展示路径和保留原因。

使用 AskUserQuestion 确认。用户拒绝 → 输出"已取消清理"并退出。

### 步骤 3：执行清理

```bash
bash .claude/scripts/clean.sh execute --confirm
```

### 步骤 4：展示结果

解析 JSON 输出：
- 展示已删除列表（`deleted` 数组）
- 展示已保留列表（`preserved` 数组）
- 验证状态（`verified` 字段）

输出后续操作建议：运行 `/f-init` 重新初始化工作流。
