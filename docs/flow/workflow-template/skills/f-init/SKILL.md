---
name: f-init
description: 工作流初始化与升级：根据 CLAUDE.md 自动生成项目定制化的 Skills 和 Hooks。支持 `-u` 升级模式。当用户说"初始化工作流"、"安装开发流程"、"升级工作流"时使用。
version: 6.1.0
---

# 工作流初始化 Skill

## 概述

本 Skill 是 `docs/flow/workflow-template/scripts/init.sh` 的调用包装器。init.sh 负责 100% 的初始化工作（项目探测、CLAUDE.md 处理、模板裁剪、安装、验证），本 Skill 仅负责调用脚本并展示结果。

用户也可以直接运行 `bash docs/flow/workflow-template/scripts/init.sh` 跳过 LLM，效果完全相同。

## 版本自检

1. 读取已安装版本：`grep 'version:' .claude/skills/f-init/SKILL.md`
2. 读取模板版本：`grep 'version:' docs/flow/workflow-template/skills/f-init/SKILL.md`
3. 如果模板版本更高：
   - 复制 `docs/flow/workflow-template/skills/f-init/SKILL.md` → `.claude/skills/f-init/SKILL.md`
   - 输出"f-init 已自我更新到 vX.Y.Z"
4. 如果版本相同：输出"f-init 版本已是最新 (vX.Y.Z)"

## 模式选择

检查用户消息文本：包含 `-u`、`-U` 或 `--upgrade` → 升级模式；否则 → 初始化模式。

## 初始化模式

### 步骤 1：执行脚本

```bash
bash docs/flow/workflow-template/scripts/init.sh --verbose
```

### 步骤 2：解析输出

- 脚本以 `[INFO]`/`[WARN]`/`[ERROR]` 前缀输出日志
- 脚本末尾输出安装报告，包含：能力检测结果、安装统计、错误/警告

### 步骤 3：展示报告

将脚本输出格式化为用户友好的 markdown 报告（能力检测、安装统计、TODO 数量）。

### 步骤 4：自动补全 CLAUDE.md TODO 标记

如果 CLAUDE.md 中 TODO 标记数 > 0，**必须自动补全**，不留给用户手动处理。

1. 读取 CLAUDE.md，统计 `<!-- TODO: 请手动填写 -->` 标记数量
2. 按下表逐项分析并替换（使用 Edit 工具）：

| TODO 所在占位符 | 检索策略 |
|---|---|
| `$PROJECT_DESCRIPTION` | 读 README.md 第一段 + package.json `description` 字段，综合为一句话 |
| `$FRONTEND_PORT` | 读 vite.config.ts/js 中 `port:` 或 package.json `scripts.dev` 中 `--port`，默认按框架推断（Vite→5173, Next→3000） |
| `$BACKEND_PORT` | 读 backend 入口文件（index.ts/app.ts）中 `.listen(` 参数，或 .env 中 `PORT=` |
| `$ARCHITECTURE_DIAGRAM` | 读项目目录结构 + 入口文件 import 关系，画 ASCII 架构图（参考现有 CLAUDE.md 的格式） |
| `$STATE_MANAGEMENT` | Glob `src/contexts/` 或 `src/store/`，列出 Context/Store 名称及用途 |
| `$BACKEND_LAYERS` | 读 backend/src/ 目录结构，总结分层（Routes → Services → Database） |
| `$KEY_SERVICE_FILES` | Glob `services/*.ts` 或 `src/services/*.ts`，列出文件名及一句话用途 |
| `$AGENT_VERSION_FILE` | Glob `agent/**/version*`，取路径（仅当 cross-compile=true 时适用） |
| `$AGENT_BUILD_COMMAND` | 读 agent 目录的 Makefile 或 go.mod，推断编译命令（仅当 cross-compile=true 时适用） |

3. 替换完成后输出："已自动补全 N 个 TODO，建议快速检查准确性"

如果 TODO 数为 0，跳过此步骤。

### 步骤 5：处理异常

- **脚本返回非零退出码**：展示错误信息，提示用户检查 `--verbose` 输出

## 升级模式

### 步骤 1：执行脚本

```bash
bash docs/flow/workflow-template/scripts/init.sh --mode=upgrade --verbose
```

### 步骤 2：展示变更

脚本会自动：备份到 `.claude/_backup/YYYYMMDDHHMMSS/` → 重新安装 → 输出 diff 摘要。

展示变更摘要，告知用户：
- 备份位置
- 变更文件数量
- 如有定制内容被覆盖，可从 `.claude/_backup/` 恢复

## 三种使用路径

| 路径 | 场景 | 操作 | LLM 参与 |
|------|------|------|---------|
| A | 已有完整 CLAUDE.md | `bash init.sh` | 0 token |
| B | CLAUDE.md 缺 Capabilities | `bash init.sh` → 自动补充 | 0 token |
| C | 无 CLAUDE.md | `bash init.sh` → 生成 CLAUDE.md → LLM 自动补全剩余 TODO | 步骤 4 |
