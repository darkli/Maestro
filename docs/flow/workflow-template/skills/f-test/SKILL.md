---
name: f-test
description: 独立测试：运行测试、补充测试、分析覆盖率。当用户说"跑测试"、"运行测试"、"补充测试"、"测试覆盖率"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash, Task]
context: fork
version: 2.1.0
---

# 独立测试 Skill

## 前置检查

读取 CLAUDE.md 的 Capabilities 节，检查 `testing` 标签值：

- 如果 `testing: false`：
  ```
  ⚠️ 测试框架未配置

  本项目的 Capabilities 中 `testing` 标签为 `false`，/f-test 命令无法运行。

  如需配置测试框架：
  1. 安装测试框架（如 vitest/pytest/go test）
  2. 更新 CLAUDE.md 的 Testing 节
  3. 更新 Capabilities 节的 testing 标签
  4. 运行 /f-init -u 更新工作流

  如仅需手动验证，请直接执行验证步骤。
  ```
  然后退出。

- 如果 `testing` 为非 false 值 → 正常执行

## 概述

独立于开发流程的测试工具，支持三个命令：

| 命令 | 用途 |
|------|------|
| `/f-test run [范围]` | 运行测试并报告结果 |
| `/f-test cover [范围]` | 分析测试覆盖率 |
| `/f-test write [目标]` | 为已有代码补充测试 |

---

## 命令 1：`/f-test run [范围]` — 运行测试

执行测试并报告结果。支持按范围和类型灵活组合。

### 参数说明

**范围参数（可组合）**：

| 参数 | 说明 |
|------|------|
| 无参数 | 运行全量测试（CLAUDE.md 中定义的全量测试命令） |
<!-- IF:frontend -->
| `frontend` | 仅前端测试 |
<!-- ENDIF:frontend -->
<!-- IF:backend-api -->
| `backend` | 仅后端测试 |
<!-- ENDIF:backend-api -->
| `<文件路径>` | 运行指定文件的测试 |
| `<模块名>` | 智能匹配：查找相关测试文件后运行 |

**类型参数（可选，追加在范围后）**：

<!-- PROJECT-SPECIFIC: 测试类型匹配模式 -->
| 参数 | 说明 |
|------|------|
| `unit` | 仅单元测试（匹配 `*.test.ts`，排除 `integration/e2e` 目录） |
| `integration` | 仅集成测试（匹配 `tests/integration/` 或 `*.integration.test.ts`） |
| `e2e` | 仅端到端测试（匹配 `tests/e2e/` 或 `*.e2e.test.ts`） |
<!-- /PROJECT-SPECIFIC -->

**示例**：
```
/f-test run                     → 全量测试
<!-- IF:frontend -->
/f-test run frontend            → 前端全部测试
<!-- ENDIF:frontend -->
<!-- IF:backend-api -->
/f-test run backend unit        → 后端仅单元测试
/f-test run backend integration → 后端仅集成测试
<!-- ENDIF:backend-api -->
/f-test run src/services/api.ts → 指定文件的测试
```

### 执行流程

#### 步骤 1-2：构造测试命令

使用 Bash 工具执行（source 和函数调用必须在同一条命令中）：

```bash
source .claude/scripts/common.sh && construct_test_command "<scope>" "<type>" "<file_path>"
```

输出格式为 `[OUTPUT:JSON] {"command": "...", "scope": "...", "type": "..."}`。去掉 `[OUTPUT:JSON] ` 前缀后解析 JSON，获取 `command` 字段。

**特殊参数处理**（LLM 任务）：
- **文件路径** → 确认文件存在。如果是源文件，查找对应测试文件（参考 CLAUDE.md 命名约定）。不存在则提示使用 `/f-test write`
- **模块名** → 用 Grep/Glob 查找匹配的测试文件，多个则让用户选择

#### 步骤 3：执行测试

使用 Bash 工具执行步骤 1-2 获取的测试命令，超时 5 分钟。

#### 步骤 4：解析结果

将测试输出传入解析函数（source 和调用必须在同一条 Bash 命令中）：

```bash
source .claude/scripts/common.sh && echo "$TEST_OUTPUT" | parse_test_output
```

输出格式为 `[OUTPUT:JSON] {"passed": N, "failed": N, "skipped": N, "duration": "Xs", "total": N}`。去掉 `[OUTPUT:JSON] ` 前缀后解析 JSON。

#### 步骤 5：展示结果

**全部通过时**：

```
测试结果：✅ 全部通过

| 指标 | 数量 |
|------|------|
| 通过 | 42 |
| 失败 | 0 |
| 跳过 | 2 |
| 耗时 | 3.2s |
```

**有失败时**：

```
测试结果：❌ 有失败

| 指标 | 数量 |
|------|------|
| 通过 | 40 |
| 失败 | 2 |
| 跳过 | 2 |
| 耗时 | 3.5s |

### 失败详情

<!-- PROJECT-SPECIFIC: 测试失败示例 -->
1. **src/services/api.test.ts:45** — `should handle network error`
   - 期望：`toThrow('Network error')`
   - 实际：未抛出异常

2. **src/components/Login.test.tsx:23** — `should show error on invalid credentials`
   - 期望：`toBeInTheDocument()`
   - 实际：元素未找到
<!-- /PROJECT-SPECIFIC -->
```

---

## 命令 2：`/f-test cover [范围]` — 覆盖率分析

分析测试覆盖率，找出薄弱环节。范围参数与 `/f-test run` 相同（无参数/frontend/backend）。

### 执行流程

#### 步骤 1-2：构造覆盖率命令

```bash
source .claude/scripts/common.sh && construct_coverage_command "<scope>"
```

输出格式为 `[OUTPUT:JSON] {"command": "...", "scope": "..."}`。去掉前缀后解析 JSON 获取 `command` 字段。如果覆盖率工具未安装，提示用户安装。

#### 步骤 3：执行覆盖率测试

使用 Bash 工具执行步骤 1-2 获取的覆盖率命令。

#### 步骤 4-5：解析覆盖率报告

```bash
source .claude/scripts/common.sh && echo "$COVERAGE_OUTPUT" | parse_coverage_output
```

输出格式为 `[OUTPUT:JSON] {...}`。去掉前缀后解析 JSON 获取：
- `statements`、`branches`、`functions`、`lines`：四项覆盖率指标
- `lowest_files`：覆盖率最低的 Top 10 文件（含各项指标）

用表格展示覆盖率摘要（对比 CLAUDE.md 中的目标值，如未定义则默认 80%）和 Top 10 最低文件。

#### 步骤 6：询问是否补充测试

使用 AskUserQuestion 询问用户：

```
是否为覆盖率较低的文件补充测试？
- 是，为最低覆盖的文件补充 → 进入 /f-test write 流程
- 选择特定文件补充 → 让用户指定后进入 /f-test write
- 否，仅查看报告 → 结束
```

---

## 命令 3：`/f-test write [目标]` — 补充测试

为已有代码编写测试，是本 Skill 的核心价值。

### 参数说明

| 参数 | 说明 |
|------|------|
| `<文件路径>` | 为指定文件编写测试 |
| `<模块名>` | 为指定模块编写测试 |
| 无参数 | 分析覆盖率，自动选择最需要测试的文件 |

### 执行流程

#### 步骤 1：确定目标文件

- **有文件路径** → 确认文件存在，不存在则报错结束
- **有模块名** → 用 Grep/Glob 查找相关源文件，如找到多个让用户选择
- **无参数** → 执行 `/f-test cover` 流程，从覆盖率最低的文件中让用户选择

#### 步骤 2：分析目标代码

1. 读取源文件，理解：
   - 导出的函数/类/组件及其签名
   - 分支逻辑（if/else、switch、三元表达式）
   - 边界条件（空值、异常、极端输入）
   - 依赖关系（import 了哪些模块，需要 Mock 什么）

2. 检查是否已有测试文件（同目录下的 `.test.ts` / `.test.tsx`）：
   - 已有 → 读取现有测试，分析已覆盖的场景
   - 未有 → 标记为"全新测试文件"

3. 判断文件类型和测试环境：
   - 参考 CLAUDE.md Testing 部分的约定，确定测试环境、import 方式、Mock 策略
<!-- IF:frontend -->
   - 前端组件 → 使用 CLAUDE.md 中约定的组件测试方式
   - 前端工具/服务 → 使用相应的测试环境
<!-- ENDIF:frontend -->
<!-- IF:backend-api -->
   - 后端代码 → 使用 CLAUDE.md Testing 部分约定的后端测试方式
<!-- ENDIF:backend-api -->

#### 步骤 3：调用 Test Engineer 设计测试用例

使用 Task 工具调用 Test Engineer 子代理（subagent_type: `test-engineer`）：

**输入**：
- 源代码内容
- 现有测试文件内容（如有）
- CLAUDE.md 中的测试规范
- 文件类型（前端组件/前端工具/后端）

**输出**：测试计划，包含：
- 用例列表（描述、输入、期望输出）
- Mock 策略（需要 Mock 哪些依赖）
- 边界场景（错误处理、空值、并发等）

#### 步骤 4：展示测试计划

向用户展示测试计划摘要：

```
## 测试计划：src/services/api.ts

### 已有覆盖
- fetchServers: 2 个用例（成功、网络错误）

### 新增用例（8 个）
1. fetchServers — 空结果集处理
2. fetchServers — 超时处理
3. createServer — 正常创建
4. createServer — 参数校验失败
5. createServer — 服务端错误
6. deleteServer — 正常删除
7. deleteServer — 删除不存在的服务器
8. updateServer — 部分更新

### Mock 策略
- Mock fetch API（使用 vi.fn()）
- Mock localStorage（JWT token）

是否按此计划编写测试？
```

使用 AskUserQuestion 让用户确认或调整。

#### 步骤 5：编写测试代码

根据确认的测试计划编写测试代码，遵循项目规范：

**通用规范**：
- AAA 模式（Arrange-Act-Assert）
- 描述性的测试名称（`should xxx when yyy`）
- 每个测试独立，不依赖执行顺序

<!-- IF:frontend -->
**前端组件测试**：
- 参考 CLAUDE.md Testing 部分的组件测试约定
- 使用项目配置的测试工具和 DOM 环境
<!-- ENDIF:frontend -->

<!-- IF:backend-api -->
**后端测试**：
- 参考 CLAUDE.md Testing 部分的后端测试约定
- Mock 外部依赖（数据库、网络连接等）
<!-- ENDIF:backend-api -->

<!-- PROJECT-SPECIFIC: 测试文件放置规范 -->
**文件放置**：
- 测试文件与源文件同目录：`Component.test.tsx`、`service.test.ts`
- 如已有测试文件，在现有文件中追加新用例（使用 Edit 工具）
- 如无测试文件，创建新文件（使用 Write 工具）
<!-- /PROJECT-SPECIFIC -->

#### 步骤 6：运行测试验证

运行新写的测试文件，确保全部通过：

使用 CLAUDE.md Testing 部分的测试命令运行指定测试文件。

- **全部通过** → 进入步骤 7
- **有失败** → 分析失败原因，修复测试代码，重新运行（最多重试 3 次）
- **3 次仍失败** → 展示失败详情，让用户决定是否继续

#### 步骤 7：输出结果摘要

```
## 测试编写完成

| 项目 | 详情 |
|------|------|
| 目标文件 | src/services/api.ts |
| 测试文件 | src/services/api.test.ts |
| 新增用例 | 8 个 |
| 总用例数 | 10 个（含已有 2 个） |
| 测试结果 | ✅ 全部通过 |
```

---

## 边界情况处理

| 场景 | 处理方式 |
|------|----------|
| 测试命令不存在 | 读取 CLAUDE.md Testing 段落获取正确命令 |
| 指定文件无对应测试 | 提示"该文件暂无测试"，建议使用 `/f-test write` |
| run 指定类型但项目无对应目录 | 提示"未找到该类型的测试文件"并结束 |
| write 目标文件不存在 | 报错并结束 |
| write 目标已有完善测试 | 分析后提示覆盖率已充足，询问是否仍要补充 |
| 覆盖率工具未配置 | 提示用户安装对应测试框架的覆盖率插件 |
| 模块名匹配到多个文件 | 用 AskUserQuestion 让用户选择 |
| 测试编写后验证失败 | 自动修复最多 3 次，仍失败则展示详情让用户决定 |
