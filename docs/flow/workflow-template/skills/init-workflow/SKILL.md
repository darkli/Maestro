---
name: init-workflow
description: 工作流初始化与升级：根据 CLAUDE.md 自动生成项目定制化的 Skills、Agents 和 Hooks。支持 `-u` 升级模式，基于版本号选择性更新已安装文件，通过语义合并保留项目定制和用户手动调整。当用户说"初始化工作流"、"安装开发流程"、"升级工作流"时使用。
tools: [Read, Write, Edit, Grep, Glob, Bash]
context: fork
version: 4.0.0
---

# 工作流初始化 Skill

## 概述

本 Skill 将 `docs/flow/workflow-template/` 中的通用模板自动定制化并安装到项目的 `.claude/` 目录中。通过扫描 CLAUDE.md 提取项目配置，基于 Capabilities 能力标签驱动条件块裁剪和 PROJECT-SPECIFIC 替换。

**前提条件**：
- 模板文件已存在于 `docs/flow/workflow-template/`
- 项目根目录已有 `CLAUDE.md`（如缺失，Phase 0.5 会自动生成）

## 模式选择

本 Skill 支持两种运行模式，根据调用参数自动选择：

| 模式 | 触发方式 | 执行流程 | 适用场景 |
|------|----------|----------|----------|
| **初始化模式** | `/init-workflow`（无参数） | Phase 0/0.5/0.7 → Phase 1-5 | 首次安装工作流 |
| **升级模式** | `/init-workflow -u` 或 `-U` 或 `--upgrade` | U0.5 + U1-U5 | 已安装工作流的版本更新 |

**参数大小写不敏感**：`-u`、`-U`、`--upgrade` 均可触发升级模式。

**参数检测方法**：检查用户消息文本（即 `/init-workflow` 后面的参数部分），若包含 `-u`、`-U` 或 `--upgrade` 任一字符串，则触发升级模式；否则为初始化模式。

**边界情况处理**：
- 如果使用 `-u` 参数但 `.claude/skills/` 目录不存在或目录下不含任何 `SKILL.md` 文件，输出提示"未检测到已安装的工作流文件，建议先运行 `/init-workflow` 进行首次初始化"并退出
- 如果不带参数运行且 `.claude/skills/` 下已有文件，按现有逻辑询问用户是否覆盖

## 命名约束（强制）

以下名称是**系统固定标识符**，在初始化时**禁止修改、重命名或替换**。这些名称在多个文件之间交叉引用，改动任何一个都会导致工作流断裂。

**Skill 目录名和 `name:` 字段**（必须完全一致）：
```
feature-dev / quick-dev / light-dev / fix-bug / design / test / context / workspace / doc-dev
```

**Agent 文件名**（必须完全一致）：
```
requirements-analyst.md / system-designer.md / test-engineer.md
code-engineer.md / code-reviewer.md / integration-validator.md
documentation-writer.md / doc-consistency-checker.md / doc-reviewer.md
```

**Workspace 文件名（代码开发类）**（必须完全一致）：
```
00-input.md / 00-context.md / 01-requirements.md / 02-design.md
03-testplan.md / 04-implementation.md / 05-review.md
06-validation.md / 07-delivery.md
```

**Workspace 文件名（文档开发类）**（必须完全一致）：
```
00-input.md / 01-analysis.md / 02-plan.md / 03-changes.md
04-consistency.md / 05-review.md
```

**初始化时允许定制的内容**（仅限以下范围）：
- `<!-- IF:xxx -->...<!-- ENDIF:xxx -->` 条件块的裁剪（根据 Capabilities 标签值）
- `<!-- PROJECT-SPECIFIC: 说明 -->...<!-- /PROJECT-SPECIFIC -->` 块内的具体路径、命令、文件列表替换
- `CLAUDE.md` 引用替换为具体文件路径

**禁止定制的内容**：Skill 名称、Agent 文件名、Workspace 文件名、SKILL.md 的阶段结构（阶段数量和顺序）、子代理一览表结构。

## 执行流程

### Phase 0：自动探测项目环境

扫描项目根目录的标志文件，推断技术栈。

**探测表**：

| 标志文件/目录 | 推断结果 | 对应能力标签 |
|--------------|---------|-------------|
| `package.json` | Node.js；检查 dependencies 判断 React/Vue/Express/Fastify | frontend, backend-api |
| `go.mod` | Go | static-types=go |
| `pyproject.toml` / `setup.py` / `requirements.txt` | Python | static-types=false |
| `Cargo.toml` | Rust | static-types=rust |
| `pom.xml` / `build.gradle` / `build.gradle.kts` | Java/Kotlin | static-types=java/kotlin |
| `CMakeLists.txt` | C/C++；含 toolchain 文件 → cross-compile 候选 | static-types=c/cpp |
| `Makefile` + `*.c`/`*.h` | C；检查 arm-/avr-/xtensa- 前缀 → 嵌入式 | cross-compile 候选 |
| `platformio.ini` | 嵌入式 (PlatformIO) | cross-compile=true |
| `*.ld`（链接脚本） | 嵌入式 | cross-compile=true |
| `turbo.json` / `nx.json` / `lerna.json` / `pnpm-workspace.yaml` | Monorepo | monorepo=工具名 |
| `.github/workflows/` | CI/CD | ci-cd=github-actions |
| `.gitlab-ci.yml` | CI/CD | ci-cd=gitlab-ci |
| `Jenkinsfile` | CI/CD | ci-cd=jenkins |
| `vitest.config.*` / `jest.config.*` | JS/TS 测试框架 | testing=vitest/jest |
| `pytest.ini` / `conftest.py` / `pyproject.toml`[tool.pytest] | Python 测试 | testing=pytest |
| `*_test.go` | Go 测试 | testing=go-testing |
| `tailwind.config.*` | Design System | design-system=tailwind |
| `locales/` / `i18n/` / `messages/` | 可能有 i18n | i18n 候选 |
| `.eslintrc*` / `ruff.toml` / `golangci-lint` | 已有 lint 工具 | — （记录 lint 命令，用于 Hook LINT_CMD 配置） |
| `prettier.config.*` / `.prettierrc*` | 已有格式化工具 | — （记录格式化命令，用于 Hook FORMAT_CMD 配置） |

**探测执行逻辑**（伪代码）：

```
1. 列出项目根目录所有文件和一级子目录
2. 逐条匹配探测表
3. 对 package.json 做额外处理：
   a. 解析 dependencies + devDependencies
   b. 检查是否含 react/vue/angular/svelte → 设置 frontend
   c. 检查是否含 express/fastify/koa/nest → 设置 backend-api
   d. 检查是否含 vitest/jest → 设置 testing
   e. 检查是否含 react-i18next/vue-i18n/next-intl → 设置 i18n
   f. 检查是否含 tailwindcss → 设置 design-system
   g. 检查是否含 typescript → 设置 static-types=typescript
4. 汇总所有探测结果
5. 输出探测结果表（标签 / 推断值 / 置信度 / 来源）
6. 深度信息提取（提取可直接填入 CLAUDE.md 的可操作值）：
   a. 解析 package.json scripts 区域：
      - scripts.dev / scripts.start → DEV_CMD
      - scripts.build → BUILD_CMD
      - scripts.test → TEST_CMD
      - scripts.test:watch / scripts.test:coverage → TEST_WATCH_CMD
      - scripts.lint → LINT_CMD
      - scripts.format / scripts.prettier → FORMAT_CMD
   b. 检测包管理器（lock 文件）→ INSTALL_CMD：
      - package-lock.json → "npm install"
      - yarn.lock → "yarn"
      - pnpm-lock.yaml → "pnpm install"
   c. 扫描目录结构（根目录 + src/ 下一级）→ ARCHITECTURE_OVERVIEW
   d. 抽样 3 个源码文件前 10 行，检测缩进风格 → INDENTATION（2-space/4-space/tab）
   e. 检查 tsconfig.json → STRICT_MODE、类型定义位置（types.ts / src/types/）
   f. 分析 git log 最近 10 条 → COMMIT_LANG（中文/英文/混合）、COMMIT_FORMAT（conventional/free）
   g. 读取 package.json description 或 README.md 首段 → PROJECT_DESC
   h. 识别多目录构建模式：
      - 根目录有 package.json + 子目录也有 package.json → 记录各子目录路径
      - 用于生成正确的多步骤安装/构建/测试命令
   i. 汇总为 DEEP_INFO 结构，供 Phase 0.5 / 0.7 / Phase 3.3 使用
```

**多语言仓库处理**：
- 如果检测到多种语言（如 package.json + go.mod + pyproject.toml）
- 列出所有检测结果
- 交互确认：询问用户"检测到多种语言，请确认项目主要语言"

**探测失败处理**：
- 某个标签无法自动探测 → 值设为 `unknown`，在 Phase 0.7 中询问用户
- 探测结果可被用户覆盖

### Phase 0.5：生成 CLAUDE.md（如缺失）

**执行条件**：仅当项目根目录无 CLAUDE.md 时执行

**核心原则**：利用 Phase 0 的能力标签 + DEEP_INFO **最大化自动填充**，仅对确实无法探测的信息保留 TODO。

**执行步骤**：
1. 从 `docs/flow/workflow-template/CLAUDE.md.template` 读取模板（如模板文件不存在，输出错误提示并终止 Phase 0.5）
2. 利用 Phase 0 的全部探测结果填充模板占位符：
   - `$PROJECT_DESCRIPTION` → DEEP_INFO.PROJECT_DESC（来自 package.json description 或 README.md 首段）；如未探测到 → `<!-- TODO: 请补充项目一句话描述 -->`
   - `$FRONTEND_STACK` → 探测到的前端框架 + 语言（如 "React 18 + TypeScript + Vite"）；无 → "N/A"
   - `$BACKEND_STACK` → 探测到的后端框架（如 "Node.js + Express + TypeScript"）；无 → "N/A"
   - `$DATABASE` → 探测到的数据库；无 → "N/A"
   - `$INSTALL_COMMAND` → DEEP_INFO.INSTALL_CMD（如 "npm install && cd backend && npm install"）
   - `$DEV_COMMAND` → DEEP_INFO.DEV_CMD（如 "npm run dev"）
   - `$BUILD_COMMAND` → DEEP_INFO.BUILD_CMD（如 "npm run build"）
   - `$TEST_FRAMEWORK` → 探测到的测试框架名
   - `$TEST_COMMAND` → DEEP_INFO.TEST_CMD（如 "npm test"）
   - `$TEST_WATCH_COMMAND` → DEEP_INFO.TEST_WATCH_CMD（如 "npm run test:watch"）
   - `$ARCHITECTURE_DIAGRAM` → DEEP_INFO.ARCHITECTURE_OVERVIEW（基于目录结构生成的简易架构图）
   - `$INDENTATION` → DEEP_INFO.INDENTATION（如 "2-space"）
   - `$COMMIT_LANGUAGE` → DEEP_INFO.COMMIT_LANG（如 "Chinese"）
   - 其他占位符：能从 DEEP_INFO 推导的一律自动填入
3. 根据能力标签推断并生成 Capabilities 表（紧跟 `## Project Overview` 之后）
4. 根据能力标签**自动启用模板中的可选段落**（取消 HTML 注释标记并填入内容）：
   - 探测到 i18n 库 → 取消 i18n 段落注释，填入 locale 目录和库名
   - 探测到 design-system → 取消 Design System 段落注释，填入配置文件路径
   - 探测到 database → 取消 Database 段落注释，填入数据库类型和访问层路径
   - 探测到 cross-compile → 取消 Agent Versioning 段落注释，填入编译命令
   - 未探测到的可选段落保持注释状态
5. 写入 CLAUDE.md 到项目根目录
6. 输出生成摘要：已自动填充 X 项，剩余 Y 个 TODO 待补充（列出具体 TODO 位置）

### Phase 0.7：验证并补全 CLAUDE.md

**执行条件**：总是执行（无论 CLAUDE.md 是已有还是刚生成的）

**核心原则**：对缺失或含 TODO 的段落，**先自动生成预填内容，再请用户确认**，而不是让用户从零填写。

**执行步骤**：

1. 对照 `claude-md-contract.md` 检查 8 个必需节 + Capabilities 节：
   - [ ] Project Overview
   - [ ] Build & Development Commands
   - [ ] Testing
   - [ ] Architecture
   - [ ] Code Style
   - [ ] Adding New Features
   - [ ] Commit Style
   - [ ] Language
   - [ ] Capabilities（如尚未生成，此处补生成）

2. 检查每个节的内容是否完整（无 TODO 占位符、无空白、非模板原文）

3. 对缺失或不完整的段落，利用 Phase 0 探测结果 + DEEP_INFO **自动生成预填内容**：
   - Build Commands 缺失 → 从 DEEP_INFO.INSTALL_CMD / DEV_CMD / BUILD_CMD 生成
   - Testing 缺失 → 从 DEEP_INFO.TEST_CMD + 能力标签 testing 值生成
   - Architecture 缺失 → 从 DEEP_INFO.ARCHITECTURE_OVERVIEW 生成目录结构 + 通信路径表
   - Code Style 缺失 → 从 DEEP_INFO.INDENTATION + tsconfig 信息生成
   - Adding New Features 缺失 → 根据技术栈（前端/后端/全栈）生成通用步骤清单
   - Commit Style 缺失 → 从 DEEP_INFO.COMMIT_LANG + COMMIT_FORMAT 生成
   - Language 缺失 → 从 DEEP_INFO.COMMIT_LANG 推断（中文提交 → 中文输出），默认中文
   - Project Overview 含 TODO → 从 DEEP_INFO.PROJECT_DESC + 技术栈列表补全
   - Capabilities 缺失 → 从 Phase 0 能力标签生成完整的 Capabilities 表

4. 如所有必需节均完整 → 输出"CLAUDE.md 验证通过，所有必需节完整"，直接进入 Phase 1

5. 如有缺失或不完整的段落 → 将预填内容**一次性展示**给用户：
   ```
   CLAUDE.md 补全：

   ✅ 已完整（无需修改）：Project Overview, Architecture, Language

   🔧 已自动生成以下段落（请确认）：

   ### Build & Development Commands（自动生成）
   [基于 DEEP_INFO 生成的命令]

   ### Testing（自动生成）
   [基于 DEEP_INFO 生成的测试配置]

   ...

   请选择：
   1. 全部写入 CLAUDE.md（推荐）
   2. 逐个确认（可逐项修改后写入）
   3. 跳过，保持现状继续初始化
   ```

6. 选择 1 → 将所有预填内容写入 CLAUDE.md 对应位置
7. 选择 2 → 逐个展示，用户可修改后确认或跳过单项
8. 选择 3 → 继续初始化（预填内容不写入，但后续 Phase 3 可能因缺失信息导致生成文件质量较低）

### Phase 1：提取配置 + 推断派生标签

读取经 Phase 0.7 补全后的 `CLAUDE.md`，提取以下配置信息（**纯读取，不再写入 CLAUDE.md**——Capabilities 已在 Phase 0.5/0.7 生成）：

**必需项（9 项，含 Capabilities）**：
1. **Project Overview** — 技术栈（前端框架、后端框架、语言）
2. **Build Commands** — 依赖安装、构建、启动命令
3. **Testing** — 测试框架、测试命令、覆盖率要求
4. **Architecture** — 目录结构、通信路径、核心文件位置
5. **Code Style** — 缩进、命名约定、语言
6. **Adding New Features** — 新功能开发步骤
7. **Commit Style** — 提交消息格式
8. **Language** — 输出语言（中文/英文等）
9. **Capabilities** — 10 个能力标签的值（直接读取，不重新推断）

**可选项（7 项）**：
10. **i18n** — 国际化框架、locale 文件列表、基准语言
11. **Design System** — 设计令牌配置文件、主题系统
12. **Database** — 数据库类型、ORM/查询方式
13. **Agent/DevOps** — Agent 版本管理、部署相关
14. **Environment Variables** — 环境变量配置
15. **Multi-Phase Project Tracking** — 多阶段项目追踪格式
16. **Ongoing Work** — 跨对话上下文管理配置

将提取结果暂存为结构化数据，供后续阶段使用。

#### 步骤 1.5：推断隐式派生标签

- 扫描 Architecture 节的通信路径表
- 检查 Type 列是否包含 `WebSocket`（匹配 WebSocket / WS / ws 等变体）→ 设置 websocket=true
- 将派生标签存入内存（不写入 CLAUDE.md，仅在条件块处理时使用）
- 在 Phase 5 报告中输出所有派生标签的推断结果，供用户确认

### Phase 2：最终验证

对照 `docs/flow/workflow-template/claude-md-contract.md` 中定义的契约，进行**最终验证**（经 Phase 0.7 补全后的二次确认）：

1. 检查 8 个必需部分 + Capabilities 是否都存在且有实质内容
2. 记录哪些可选部分已配置（用于后续条件块处理）
3. 对仍缺失的必需部分（Phase 0.7 中用户选择了"跳过"），采取**自动降级处理**：
   - 从 Phase 0 的 DEEP_INFO 中提取可用值，自动填入 CLAUDE.md（不再询问）
   - 无法从 DEEP_INFO 获取的，使用基于技术栈的合理默认值填入
   - 填入后标注 `<!-- AUTO-FILLED: 建议检查并调整 -->`，供用户后续审查
4. 如果经过自动降级处理后仍有必需部分完全为空（极端情况：Phase 0 也无法探测到任何信息），**阻断并明确告知**用户需要手动补充的具体内容和原因

**输出**：配置摘要表

以下为示例输出（实际值将根据你项目的 CLAUDE.md 内容动态生成）：

```
| 配置项 | 状态 | 提取值（示例） |
|--------|------|----------------|
| Project Overview | OK | [你的技术栈] |
| Build Commands | OK | [你的构建命令] |
| Testing | OK | [测试框架, 覆盖率要求] |
| Architecture | OK | [源码目录结构] |
| Code Style | OK | [缩进风格, 命名约定] |
| Adding New Features | OK | [开发步骤] |
| Commit Style | OK | [提交格式] |
| Language | OK | [输出语言] |
| Capabilities | OK | [10 个能力标签] |
| i18n | OK/N/A | [locale 数量和基准语言，如配置] |
| Design System | OK/N/A | [设计令牌系统，如配置] |
| Database | OK/N/A | [数据库类型，如配置] |
| Agent/DevOps | OK/N/A | [DevOps 配置，如配置] |
| Environment Variables | OK/WARN | [环境变量] |
| Multi-Phase Tracking | OK/N/A | [进度追踪格式，如配置] |
| Ongoing Work | OK/N/A | [上下文管理配置，如配置] |
```

### Phase 3：生成定制化文件（两遍处理）

#### 3.1 生成目标目录

```bash
mkdir -p .claude/{skills/{feature-dev,quick-dev,light-dev,fix-bug,design,test,context,workspace,doc-dev},agents,hooks,workspace,context}
```

#### 3.2 两遍处理引擎

对每个模板文件执行两遍处理：

**Pass 1：条件块裁剪**

```
对文件内容逐行扫描：
1. 遇到 <!-- IF:xxx --> 时：
   a. 查找 xxx 在 Capabilities 中的值
   b. 如果 xxx 是隐式派生标签（如 websocket），从内存中查找
   c. 值为非 false → 条件为真：移除 IF/ENDIF 注释行，保留中间内容
   d. 值为 false 或不存在 → 条件为假：移除 IF 行 + 中间内容 + ENDIF 行

2. 遇到 <!-- IF:NOT:xxx --> 时：
   a. 逻辑与 IF:xxx 相反

3. 嵌套处理：使用栈跟踪嵌套层级
   a. 外层条件为假 → 内层整体移除
   b. 外层条件为真 → 递归处理内层

4. 边界情况：所有标签均为 false 时
   a. 所有 IF:xxx 块被移除，所有 IF:NOT:xxx 块被保留
   b. 生成的文件可能内容较少但仍有效（通用部分 + NOT 块）
   c. 不报错，正常继续 Pass 2
```

**Pass 2：PROJECT-SPECIFIC 替换**

```
对 Pass 1 输出逐行扫描：
1. 遇到 <!-- PROJECT-SPECIFIC: 说明 --> 时：
   a. 标记进入 PROJECT-SPECIFIC 区块
   b. 根据"说明"文本确定替换来源
   c. 从 CLAUDE.md 中提取对应配置值

2. 遇到 <!-- /PROJECT-SPECIFIC --> 时：
   a. 标记离开区块
   b. 移除开始/结束注释行
   c. 用项目具体值替换块内容

3. 替换映射表（说明 → 来源）：
   - "文件结构示例" → Architecture 部分的目录结构
   - "i18n 文件列表" → i18n 节的 locale 文件列表
   - "测试命令" → Testing 节的测试命令
   - "构建命令" → Build Commands 节的构建命令
   - "交叉编译命令" → Build Commands 节的交叉编译命令
   - "类型检查命令" → Build Commands 节的类型检查命令
   - "依赖安装命令" → Build Commands 节的安装命令
   - "构建验证命令" → Build Commands 节的构建命令
   - "集成测试命令" → Testing 节的集成测试命令
   - "后端服务地址" → Architecture 部分的后端端口
   - "覆盖率指标" → Testing 节的覆盖率要求
   - "测试框架约定" → Testing 节的 Conventions
   - "React 项目示例" / 框架特定 → 根据 Capabilities.frontend 值选择
   - 未匹配的说明文本 → 保留原内容不替换，输出警告日志
```

#### 3.3 生成 Hook 脚本

从 `docs/flow/workflow-template/hooks/` 复制所有脚本到 `.claude/hooks/`。

处理规则：
- 填充脚本头部的配置变量区域（`=== 配置区域 ===`）：
  - `CAPABILITY_TESTING` → Capabilities.testing 的值
  - `LINT_CMD` → 从 CLAUDE.md 或 Phase 0 探测结果获取 lint 工具
  - `FORMAT_CMD` → 从 CLAUDE.md 或 Phase 0 探测结果获取格式化工具
  - `FILE_PATTERNS` → 从 Architecture 部分推断源码目录和扩展名
  - `TEST_CMD` → Testing 节的测试命令
  - `COVERAGE_FILE` → Testing 节的覆盖率报告路径
  - `THRESHOLD` → Testing 节的覆盖率要求
- 设置可执行权限：`chmod +x .claude/hooks/*.sh`

从 `docs/flow/workflow-template/settings.json` 复制到 `.claude/settings.json`（如已存在则合并）。

#### 3.4 生成 Agent 文件

从 `docs/flow/workflow-template/agents/` 复制所有 `.md` 文件到 `.claude/agents/`。

对每个文件执行 3.2 中的两遍处理（Pass 1 条件块裁剪 + Pass 2 PROJECT-SPECIFIC 替换）。

#### 3.5 生成 Skill 文件

从 `docs/flow/workflow-template/skills/` 复制所有 `SKILL.md` 到 `.claude/skills/` 对应目录。

对每个文件执行 3.2 中的两遍处理（Pass 1 条件块裁剪 + Pass 2 PROJECT-SPECIFIC 替换）。

**注意**：`context/SKILL.md`、`test/SKILL.md`、`workspace/SKILL.md` 和 `doc-dev/SKILL.md` 不含条件块或 PROJECT-SPECIFIC 标记，直接复制即可。

### Phase 4：验证生成结果

执行以下检查：

1. **文件数量检查**：
   - `.claude/skills/` 下应有 9 个 `SKILL.md`
   - `.claude/agents/` 下应有 9 个 `.md`
   - `.claude/hooks/` 下应有 8 个 `.sh`
   - `.claude/settings.json` 应存在
   - `.claude/context/` 目录应存在

2. **权限检查**：所有 `.sh` 文件有可执行权限

3. **残留标记检查与自动修复**：
   ```bash
   grep -r "<!-- IF:" .claude/skills/ .claude/agents/
   grep -r "<!-- PROJECT-SPECIFIC" .claude/skills/ .claude/agents/
   grep -r "如 CLAUDE.md 中配置了" .claude/skills/ .claude/agents/
   ```
   如发现残留标记：
   a. 对含 `<!-- IF:xxx -->` 残留的文件 → 根据 Capabilities 标签值重新执行 Pass 1 条件块裁剪
   b. 对含 `<!-- PROJECT-SPECIFIC -->` 残留的文件 → 根据 CLAUDE.md 对应节内容重新执行 Pass 2 替换
   c. 重新执行后仍有残留（CLAUDE.md 中确实缺少对应内容）→ 移除残留标记块，用 `<!-- 未配置：[说明] -->` 替代，并在 Phase 5 报告中列出
   d. 重新验证直到无残留

4. **引用完整性**：SKILL 中引用的 agent 文件名在 `.claude/agents/` 中都存在

### Phase 5：输出报告

生成初始化报告：

```markdown
# 工作流初始化报告

## 项目配置摘要
[Phase 2 的配置表]

## Capabilities 能力标签

| 能力 | 值 | 来源 |
|------|-----|------|
| frontend | [值] | [推断来源] |
| backend-api | [值] | [推断来源] |
| ... | ... | ... |

## 已生成文件

### Skills（9 个）
- .claude/skills/feature-dev/SKILL.md — 7 阶段完整开发
- .claude/skills/quick-dev/SKILL.md — 7 阶段快速开发
- .claude/skills/light-dev/SKILL.md — 4 阶段轻量开发
- .claude/skills/fix-bug/SKILL.md — 4 阶段 Bug 修复
- .claude/skills/design/SKILL.md — 2 阶段设计
- .claude/skills/test/SKILL.md — 独立测试（运行/覆盖率/补充）
- .claude/skills/context/SKILL.md — 跨对话上下文管理
- .claude/skills/workspace/SKILL.md — Workspace 目录查看与清理
- .claude/skills/doc-dev/SKILL.md — 5 阶段文档与模板开发

### Agents（9 个）
- .claude/agents/requirements-analyst.md
- .claude/agents/system-designer.md
- .claude/agents/test-engineer.md
- .claude/agents/code-engineer.md
- .claude/agents/code-reviewer.md
- .claude/agents/integration-validator.md
- .claude/agents/documentation-writer.md
- .claude/agents/doc-consistency-checker.md
- .claude/agents/doc-reviewer.md

### Hooks（8 个 + 配置）
- .claude/hooks/*.sh（8 个脚本）
- .claude/settings.json

## 可用命令

| 命令 | 说明 |
|------|------|
| `/feature-dev` | 启动完整功能开发流程 |
| `/quick-dev` | 启动快速开发流程 |
| `/light-dev` | 启动轻量开发流程 |
| `/fix-bug` | 启动 Bug 修复流程 |
| `/design` | 启动需求分析与设计 |
| `/test` | 独立测试（运行/覆盖率/补充测试） |
| `/context` | 跨对话上下文管理 |
| `/workspace` | Workspace 目录查看与清理 |
| `/doc-dev` | 文档与模板开发（含一致性扫描） |

## 条件功能状态

| 能力标签 | 状态 | 影响范围 |
|---------|------|---------|
| frontend | 已启用/未启用 | Code Reviewer 前端检查、Design System 审查 |
| testing | 已启用/未启用 | TDD 阶段、集成测试、Hook 测试脚本 |
| i18n | 已启用/未启用 | Code Engineer i18n 步骤、Integration Validator i18n 验证 |
| ... | ... | ... |

## 后续建议
1. 运行 `/design` 测试工作流是否正常
2. 根据需要调整 Hook 脚本（参考 docs/flow/workflow-template/hooks/README.md）
3. 将 `.claude/` 目录提交到版本控制
```

## 升级流程（`-u` 模式）

当使用 `/init-workflow -u`（或 `-U`、`--upgrade`）触发时，执行以下升级流程。

**升级的核心挑战**：已安装文件包含两层定制——(1) init-workflow 生成时的 PROJECT-SPECIFIC 替换结果，(2) 用户在 init 之后的手动调整。升级必须在引入模板新改进的同时**保留这两层定制**。

### 阶段 U0.5：配置同步

在 U1 之前执行，确保 Capabilities 节存在且是最新的。

**执行步骤**：
1. 读取 CLAUDE.md 的 Capabilities 节
2. 如不存在 Capabilities 节：
   a. 执行 Phase 0 探测（同初始化模式，包含深度信息提取）
   b. 根据探测结果推断 10 个能力标签值（推断规则同 Phase 0 探测表）
   c. 写入 Capabilities 节到 CLAUDE.md
   d. 输出："已为现有项目生成 Capabilities 节"
3. 如已存在 Capabilities 节：
   a. 执行 Phase 0 探测，根据探测结果重新推断能力标签值
   b. 对比推断值与已有值
   c. 如有不一致：
      ```
      Capabilities 变更检测：
      | 标签 | 当前值 | 推断值 | 操作 |
      |------|--------|--------|------|
      | testing | jest | vitest | 建议更新 |
      | ci-cd | false | github-actions | 建议新增 |

      是否更新？[y/n/逐个选择]
      ```
   d. 根据用户选择更新 Capabilities 节
4. 将最新能力标签传递给后续 U1-U5 阶段
5. 扫描 CLAUDE.md 的 8 个必需节（同 Phase 0.7 的检查列表），对缺失段落执行**主动补全**：
   a. 如步骤 2 未执行 Phase 0 探测，此时执行一次（确保探测结果可用）
   b. 对每个缺失段落，根据 Phase 0 探测结果 + `CLAUDE.md.template` 中对应段落的模板，生成预填内容
   c. 将所有缺失段落及其预填内容一次性展示给用户：
      ```
      CLAUDE.md 缺失段落补全：

      以下段落缺失，已根据项目探测结果预填内容，请确认：

      ### Build & Development Commands（预填）
      ```bash
      npm install
      npm run dev    # port 3000
      npm run build
      ```

      ### Testing（预填）
      **Framework:** vitest
      npm test

      ...

      请选择：
      1. 全部写入（推荐）
      2. 逐个确认
      3. 跳过，稍后手动补充
      ```
   d. 选择 1 → 将所有预填内容写入 CLAUDE.md 对应位置
   e. 选择 2 → 逐个展示，用户可修改后确认或跳过
   f. 选择 3 → 输出缺失段落提醒表（同之前的警告格式），不阻塞升级流程
   g. 对于 DEEP_INFO 可部分探测的段落（如 Code Style 的缩进风格、Commit Style 的语言和格式），用探测值预填已知部分，未知部分标注 `<!-- TODO: 请根据项目实际情况补充 -->`

### 阶段 U1：扫描已安装版本

遍历 `.claude/` 下所有工作流文件，按类型提取版本号：

| 文件类型 | 版本号位置 | 示例 |
|----------|-----------|------|
| SKILL.md | YAML frontmatter `version:` 字段 | `version: 1.0.0` |
| Agent .md | YAML frontmatter `version:` 字段 | `version: 1.0.0` |
| Hook .sh | 第二行 `# @version X.Y.Z` 注释 | `# @version 2.0.0` |
| settings.json | `_workflow_version` 字段 | `"_workflow_version": "2.0.0"` |

**兼容性**：缺失版本号的文件视为 `0.0.0`（兼容旧版安装）。

扫描范围：
- `.claude/skills/*/SKILL.md`（注意：`init-workflow` 自身不被安装到 `.claude/skills/`，不在升级扫描范围内）
- `.claude/agents/*.md`
- `.claude/hooks/*.sh`
- `.claude/settings.json`

### 阶段 U2：版本对比与变更计划

逐一对比已安装版本 vs 模板版本（`docs/flow/workflow-template/` 中对应文件），生成变更计划表。

**分类规则**：

| 对比结果 | 分类 | 操作 |
|----------|------|------|
| 版本相同 | 无需更新 | 跳过 |
| 模板版本更高 | 需要更新 | 进入 U3 合并 |
| 已安装版本更高 | 异常 | 跳过并输出警告 |
| 模板有但未安装 | 新增 | 走初始化模式 Phase 3 逻辑生成 |
| 已安装但模板无 | 自定义文件 | 跳过，保留不动 |

**⏸ 确认点**：展示变更计划表，等待用户选择：

```
变更计划：
| 文件 | 已安装版本 | 模板版本 | 操作 |
|------|-----------|---------|------|
| skills/feature-dev/SKILL.md | 1.0.0 | 2.0.0 | 需要更新 |
| agents/code-engineer.md | 0.0.0 | 1.0.0 | 需要更新 |
| hooks/protect-files.sh | 1.0.0 | 1.0.0 | 无需更新 |
| skills/custom-skill/SKILL.md | — | — | 自定义文件，跳过 |
...

请选择：
1. 全部更新
2. 选择性更新（逐个确认）
3. 取消升级
```

选择 2 时，对每个"需要更新"的文件依次询问：
```
更新 skills/feature-dev/SKILL.md（1.0.0 → 2.0.0）？[y/n/q（跳过剩余全部）]
```

### 阶段 U3：执行更新（语义合并策略）

**这是与初始化模式的核心区别**。升级不是"从模板重新生成"，而是**三输入语义合并**。

#### 三输入源

对每个需要更新的文件，读取三个输入源：

| 输入 | 来源 | 作用 |
|------|------|------|
| 新模板 | `docs/flow/workflow-template/` 对应文件 | 提供结构改进、prompt 优化、新特性 |
| 已安装文件 | `.claude/` 对应文件 | 提供项目定制内容（PROJECT-SPECIFIC 替换结果 + 手动调整） |
| CLAUDE.md | 项目根目录 | 提供最新的项目配置（路径、命令、技术栈） |

#### 合并原则（按优先级排序）

1. **结构和流程以新模板为准** — 阶段数量、阶段顺序、子代理调度方式、确认点数量等采用新模板的设计
2. **项目专属内容从已安装文件继承** — 具体文件路径、命令、条件块的启用/禁用状态、locale 列表等从已安装文件提取，如果 CLAUDE.md 有更新则以 CLAUDE.md 为准
3. **用户手动调整保留** — 如果已安装文件中存在新模板中没有的内容（例如用户手动增加的检查步骤、调整的 prompt 措辞），在合并结果中保留这些内容，放置在语义上合适的位置
4. **新增内容直接引入** — 新模板中新增的章节、步骤、检查项，在合并结果中直接引入
5. **删除内容谨慎处理** — 如果新模板移除了某些内容，但已安装文件中该内容包含项目定制信息，保留并标注`（模板已移除，项目保留）`

#### 合并判断规则

**判断"用户手动调整"的启发式方法**：
1. 将已安装文件与新模板逐段对比，找出"已安装文件中有但新模板中没有"的段落
2. 对这些段落进一步判断：
   - 如果段落包含 prompt 逻辑、检查步骤、流程说明等有意义的内容 → 认定为**用户手动添加**，保留
   - 如果段落仅含过时的绝对路径占位符或已失效的命令，且无 prompt 逻辑 → 认定为**过时残留**，可安全移除
3. 简化原则：**有疑问时一律保留**，宁可多保留也不误删用户定制

**判断"删除内容是否包含项目定制"的方法**：
1. 检查被模板删除的段落中是否包含：具体文件路径（如 `src/services/api.ts`）、具体命令（如 `npm test`）、locale 列表、条件块启用/禁用结果
2. 如果包含上述任一项 → 保留并标注`（模板已移除，项目保留）`
3. 如果全是通用描述性文字（无项目特征） → 安全移除

**合并冲突处理**（同一语义位置，新模板和已安装文件均有变化）：
- 优先级：新模板的结构和文字描述 > 已安装文件中的项目定制值
- 具体做法：使用新模板的措辞和结构框架，将已安装文件中的具体值（路径、命令、配置项）嵌入其中
- 如果无法确定如何嵌入，在合并结果中用 `<!-- MERGE-REVIEW: 请检查此处合并结果 -->` 标记，供用户在 U5 报告后手动审查

#### 具体操作流程

```
对每个需要更新的文件：
  1. 读取新模板、已安装文件、CLAUDE.md
  2. 识别新模板相对已安装文件的变化类型：
     - 结构性变化（新增/删除/重排章节）
     - 内容优化（prompt 措辞改进、token 优化）
     - 新增特性（新的检查项、新的步骤）
  3. 识别已安装文件中的项目定制内容：
     - PROJECT-SPECIFIC 替换结果（文件路径、命令等）
     - 用户手动添加/修改的内容
  4. 执行合并：新模板结构 + 项目定制内容 + 用户手动调整
  5. 处理 CLAUDE.md 中新的/变化的配置（如新增了 locale、改了构建命令）
  6. 更新文件的 version 字段为模板版本号
  7. 写入合并结果
```

#### settings.json 特殊处理

- **hooks 配置**：以 hook 的 `command` 字段值（脚本路径）为 key，模板新增的条目追加到对应事件类型下，已存在相同 `command` 的条目更新其 `timeout`/`async` 等参数，用户自定义（`command` 不在模板中）的条目保留不动
- **`_workflow_version`**：更新为模板版本
- **其他用户自定义顶层字段**：保留不动

#### 新增文件处理

模板中有但未安装的文件 → 走初始化模式的 Phase 3 逻辑（从模板 + CLAUDE.md 生成）。**注意**：新增 hook 脚本时，还需检查并追加 `.claude/settings.json` 中对应的 hook 注册条目（参考模板 `settings.json` 中该 hook 的 matcher 和配置）。

### 阶段 U4：验证更新结果

复用初始化模式阶段 4 的全部检查，并新增版本一致性检查：

1. **文件数量检查**：
   - `.claude/skills/` 下应有 9 个 `SKILL.md`
   - `.claude/agents/` 下应有 9 个 `.md`
   - `.claude/hooks/` 下应有 8 个 `.sh`
   - `.claude/settings.json` 应存在

2. **权限检查**：所有 `.sh` 文件有可执行权限

3. **残留标记检查**：
   ```bash
   grep -r "<!-- IF:" .claude/skills/ .claude/agents/
   grep -r "<!-- PROJECT-SPECIFIC" .claude/skills/ .claude/agents/
   grep -r "如 CLAUDE.md 中配置了" .claude/skills/ .claude/agents/
   ```
   确认无残留的模板标记。若发现残留，返回 U3 重新执行该文件的合并（合并时需确保将模板条件块和标记块替换为已安装文件中对应的项目定制值，或根据 CLAUDE.md 和 Capabilities 重新处理）。

4. **引用完整性**：SKILL 中引用的 agent 文件名在 `.claude/agents/` 中都存在

5. **版本一致性检查**（升级模式新增）：已更新文件的版本号 == 对应模板版本号

### 阶段 U5：输出升级报告

```markdown
# 工作流升级报告

## 升级摘要
| 指标 | 数值 |
|------|------|
| 扫描文件总数 | N |
| 已更新 | X |
| 跳过（版本相同） | Y |
| 新增 | Z |

## 更新明细
| 文件 | 旧版本 | 新版本 | 更新方式 | 关键变化说明 |
|------|--------|--------|----------|-------------|
| skills/feature-dev/SKILL.md | 3.0.0 | 4.0.0 | 语义合并 | 新增 token 优化策略、调整确认点 |
| agents/code-engineer.md | 0.0.0 | 1.0.0 | 语义合并 | 新增安全检查清单 |

## 合并决策记录
（记录合并过程中的关键决策，例如：）
- feature-dev/SKILL.md：用户手动添加的"数据库迁移检查"步骤已保留在阶段 5
- code-engineer.md：项目的 9 个 locale 文件路径已从旧版继承

## 后续建议
1. 运行 `git diff .claude/` 查看完整变更
2. 用 `/design [简单任务]` 或 `/light-dev [简单任务]` 验证工作流 Skill 可正常触发
3. 提交更新
```

## 注意事项

### 通用
- 如果项目没有 CLAUDE.md，Phase 0.5 会自动从模板生成并利用 DEEP_INFO 最大化预填
- Phase 0.5 和 Phase 0.7 会写入 CLAUDE.md（生成 Capabilities 节、补全缺失段落）；Phase 1 开始后 CLAUDE.md 只读取不修改
- Phase 0.7 对缺失段落采用"自动预填 + 用户确认"策略，而非"引导用户从零填写"
- 如果 `.claude/` 下已有同名文件，会询问用户是否覆盖（仅限初始化模式；升级模式通过 U2 的变更计划确认统一处理）
- 生成的文件是项目定制版，不再包含模板标记
- 如需重新初始化，直接再次运行本 Skill 即可

### 升级模式
- 升级范围仅限 `.claude/skills/`、`.claude/agents/`、`.claude/hooks/`、`.claude/settings.json`，**绝不触碰** `.claude/workspace/` 和 `.claude/context/` 用户数据
- 建议升级前先 `git commit` 当前工作流文件，方便对比和回滚
- 可通过 `git restore .claude/skills/ .claude/agents/ .claude/hooks/ .claude/settings.json` 回滚工作流文件变更（不影响 workspace 和 context 数据）。Git < 2.23 可用：`git checkout -- .claude/skills/ .claude/agents/ .claude/hooks/ .claude/settings.json`
- `-u` 和 `-U` 效果相同，大小写不敏感，`--upgrade` 亦可
