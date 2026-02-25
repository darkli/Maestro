# CLAUDE.md 接口契约

本文档定义工作流系统（Skills + 子代理）对 `CLAUDE.md` 的依赖关系。新项目移植时，对照本契约逐条填写 `CLAUDE.md`，确保工作流系统可以正确运行。

---

## 必需部分（8 项用户填写 + 1 项自动生成）

工作流系统的子代理在运行时**必须**能从 `CLAUDE.md` 中找到以下信息。缺失任何一项将导致子代理产出质量下降或逻辑错误。

---

### 1. Project Overview（项目概述）

**用途**：让子代理了解项目的业务背景和技术全貌，避免产出与项目性质不符的方案。

**必需内容**：
- 项目一句话描述（业务用途）
- 技术栈列表（前端框架 + 后端框架 + 数据库 + 特殊运行时）
- 关键端口（前端、后端、其他服务）

**示例格式**：
```markdown
## Project Overview

MyApp 是一个 SaaS 任务管理平台，支持团队协作和工作流自动化。

**Tech Stack:**
- **Frontend:** React 18 + TypeScript + Vite + Tailwind CSS (port 3000)
- **Backend:** Node.js + Express + TypeScript (port 4000)
- **Database:** PostgreSQL
- **Cache:** Redis
```

---

### 2. Build & Development Commands（构建命令）

**用途**：Integration Validator（集成验证子代理）在验证阶段执行构建检查和测试时直接引用这些命令。

**必需内容**：
- 依赖安装命令
- 开发启动命令（前端、后端）
- 生产构建命令（前端、后端）

**示例格式**：
```markdown
## Build & Development Commands

```bash
# 安装依赖
npm install
cd backend && npm install

# 启动开发服务
npm run dev              # 前端 port 3000
cd backend && npm run dev  # 后端 port 4000

# 构建
npm run build
cd backend && npm run build
```
```

---

### 3. Testing（测试规范）

**用途**：Test Engineer 编写测试文件时遵循此规范；Integration Validator 运行测试时使用这些命令；Code Engineer 确认测试环境配置。

**必需内容**：
- 测试框架名称（如 Vitest、Jest）
- 运行测试的命令
- 测试文件的命名规范和存放位置
- 测试中可用的全局 API（如是否需要显式 import）
- Mock 规范（如 react-i18next 的 mock 方式）
- 测试 setup 文件路径（如有）

**示例格式**：
```markdown
## Testing

**Framework:** Vitest

```bash
npm test                    # 运行一次
npm run test:watch          # 监听模式
cd backend && npm test      # 后端测试
```

**Conventions:**
- 测试文件与源文件同目录：`Component.test.tsx`、`util.test.ts`
- 后端测试：`src/**/*.test.ts`
- 前端 Vitest globals 可直接使用，后端需显式 import
- 测试 setup 文件：`test/setup.ts`
```

---

### 4. Architecture（架构）

**用途**：System Designer 设计新功能时参考现有架构；Code Engineer 确认文件应放在哪个目录；所有子代理了解前后端分离边界和通信方式。

**必需内容**：
- 系统架构图（文字或 ASCII art 均可）
- 通信路径表（端点、类型、用途）
- 前端状态管理方式（Context / Redux / Zustand 等）
- 后端分层结构（Routes / Services / Database 等）
- 关键服务文件路径（API 封装、i18n 初始化等）

**示例格式**：
```markdown
## Architecture

```
Frontend (React:3000) ──REST──▶ Backend (Express:4000) ──▶ Database
                     ◀──WS──
```

**Communication paths:**
| Path | Type | Purpose |
|------|------|---------|
| `/api/users` | REST | 用户 CRUD |
| `/ws/notify` | WebSocket | 实时通知 |

**Frontend state management:** React Context (AuthContext, ThemeContext)

**Backend layers:** Routes → Services → Database (database/db.ts)

**Frontend services:** `services/api.ts` 封装所有 REST 调用
```

---

### 5. Code Style（代码风格）

**用途**：Code Engineer 编写代码时遵循此规范；Code Reviewer 审查时以此为准绳。

**必需内容**：
- 缩进风格（空格数 / Tab）
- 组件命名规范（PascalCase / camelCase）
- 文件命名规范（`.tsx` / `.ts` / `.vue` 等）
- TypeScript 严格程度（是否禁 `any`）
- 核心类型定义的位置

**示例格式**：
```markdown
### Code Style
- 2 空格缩进，TypeScript throughout
- 组件：PascalCase `.tsx` 文件
- 函数/变量：camelCase
- 禁止 `any` 类型
- 核心类型定义：根目录 `types.ts`
```

---

### 6. Adding New Features（新功能流程）

**用途**：Code Engineer 添加新功能时遵循此顺序，确保不遗漏步骤（如忘记更新 locale 文件）。

**必需内容**：
- 新增功能时需要修改的文件类型和顺序
- 强制步骤（如：每次 UI 变更都必须更新 locale 文件）

**示例格式**：
```markdown
### Adding New Features
1. 在 `types.ts` 添加类型
2. 在 `backend/src/routes/` 添加路由
3. 在 `services/api.ts` 添加 API 调用
4. 创建或修改组件
5. 更新所有 locale 文件（如有 UI 文本变更）
```

---

### 7. Commit Style（提交风格）

**用途**：所有 Skill 在每个阶段结束时执行 `git commit`，提交消息格式从此处读取。

**必需内容**：
- 提交消息的语言（中文 / 英文）
- 格式规范（如 Conventional Commits：`type(scope): message`）
- 示例

**示例格式**：
```markdown
## Commit Style

提交消息使用中文，格式：`type($scope): 动作描述`

示例：
- `feat(user): 添加用户角色管理`
- `fix(auth): 修复 token 过期未跳转问题`
- `docs(api): 更新接口文档`
```

---

### 8. Language（输出语言）

**用途**：所有子代理输出文档、注释、Workspace 文件时遵循此规范。

**必需内容**：
- 文档和注释使用的语言
- 代码标识符使用的语言（通常为英文）

**示例格式**：
```markdown
## Language

所有输出（分析文档、设计文档、代码注释、Workspace 文件）使用**中文**。
代码标识符（变量名、函数名、类型名）保持英文。
```

---

### 9. Capabilities（能力标签）— 自动生成

**用途**：`/f-init` 在生成定制化文件时，读取此节的标签值来裁剪模板中的 `IF:xxx` 条件块。各 Agent 模板在运行时也引用此节判断哪些检查项适用。

**生成方式**：由 `/f-init` Phase 1 自动推断并写入，也可手动编辑。**用户无需手动创建此节**——Phase 0.7 验证的仍是原有 8 个必需节，Capabilities 在 Phase 1 自动补全。

**位置**：紧跟在 `## Project Overview` 之后

**必需内容**：
- 10 个能力标签的表格（标签名 + 值）
- 每个标签值为框架名/工具名或 `false`

**标签值语义**：
- 值为 `false` → 条件 `IF:xxx` 判定为**假**，`IF:NOT:xxx` 判定为**真**
- 值为任何非 `false` 字符串 → 条件 `IF:xxx` 判定为**真**，`IF:NOT:xxx` 判定为**假**
- 标签不存在 → 等同于 `false`（安全默认值）

**示例格式**：

```markdown
## Capabilities

| 能力 | 值 |
|------|-----|
| frontend | React |
| backend-api | Express |
| database | mysql |
| i18n | react-i18next |
| testing | vitest |
| cross-compile | false |
| design-system | tailwind |
| ci-cd | github-actions |
| monorepo | false |
| static-types | typescript |
```

当项目技术栈变化时，运行 `/f-init -u` 会自动检测差异并建议更新。

**隐式派生标签**（不出现在 Capabilities 表中，从 CLAUDE.md 内容推断）：

| 派生标签 | 推断规则 | 推断来源 |
|---------|---------|---------|
| `websocket` | Architecture 通信路径表中含 Type=WebSocket 的行 | `## Architecture` |

---

## 可选部分（7 项）

以下部分在特定技术栈或项目场景下需要，若不涉及可省略。

---

### 1. i18n（国际化）

**适用场景**：前端包含多语言支持时必须填写，否则 Code Engineer 不知道需要更新哪些文件。

**用途**：Code Engineer 在实现包含 UI 文本的功能时，知道需要更新哪些 locale 文件；Integration Validator 在验证阶段执行 i18n 完整性检查。

**需要填写的内容**：
- 使用的 i18n 库（react-i18next / vue-i18n / 其他）
- locale 文件位置和文件列表
- 翻译键命名规范
- 基准语言

**示例格式**：
```markdown
### i18n (Mandatory)
所有 UI 文本必须使用 `t('key')`。变更 UI 文本时更新所有 locale 文件：
`locales/`：en-US（基准）、zh-CN、... （根据项目实际支持的语言列出）
翻译键格式：`component.element`（如 `nav.dashboard`）
```

---

### 2. Design System（设计系统）

**适用场景**：项目有自定义设计 Token（Tailwind 或 CSS Variables）时填写，避免 Code Engineer 使用硬编码颜色值。

**用途**：Code Engineer 编写 UI 组件时使用正确的 Token 名称；Code Reviewer 检查是否有硬编码颜色。

**需要填写的内容**：
- Token 定义文件路径（如 `tailwind.config.js`）
- 关键 Token 家族（颜色、背景、边框、文字、圆角等）
- 暗色模式实现方式

**示例格式**：
```markdown
### Design System (Tailwind)
Token 定义见 `tailwind.config.js`。关键 Token 家族：
- 颜色：`primary-*`、`danger-*`、`success-*`
- 背景：`surface-base`、`surface-card`
- 文字：`text-primary`、`text-muted`
- 圆角：`rounded-component`、`rounded-card`

暗色模式：`dark:` class 前缀，所有 UI 必须适配。
```

---

### 3. Database（数据库规范）

**适用场景**：项目有特定的数据库访问规范、ORM 约定或安全要求时填写。

**用途**：Code Engineer 编写数据库查询时遵循安全规范；System Designer 设计数据模型时了解数据库类型。

**需要填写的内容**：
- 数据库类型和版本
- ORM / 查询客户端（如 mysql2、Prisma、TypeORM）
- 安全要求（如：必须使用参数化查询）
- 数据库访问层文件路径

**示例格式**：
```markdown
### Database
- PostgreSQL 14 / MySQL 8.0，访问层：`database/db.ts`（文件名应与项目实际情况一致）
- 所有查询**必须**使用参数化（防 SQL 注入）：`db.query('SELECT * FROM t WHERE id = ?', [id])`
- 禁止字符串拼接 SQL
```

---

### 4. Agent / DevOps（代理 / 运维）

**适用场景**：项目包含独立部署的 Agent 二进制、CI/CD 流程或特殊编译要求时填写。

**用途**：Code Engineer 修改 Agent 代码时知道需要版本号和重新编译；Integration Validator 了解完整的构建流程。

**需要填写的内容**：
- Agent / 特殊组件的技术栈
- 版本管理规范
- 编译命令

**示例格式**：
```markdown
### Agent Versioning
Agent 使用语义化版本，每次代码变更必须更新 `agent/version/version.json`。
重新编译（面向 Linux）：`cd agent && GOOS=linux GOARCH=amd64 go build -o your-agent-binary .`
```

---

### 5. Environment Variables（环境变量）

**适用场景**：功能依赖外部 API Key 或特殊环境配置时填写。

**用途**：Code Engineer 和 Integration Validator 了解本地运行时需要哪些环境变量；文档生成子代理在用户指南中提示配置步骤。

**需要填写的内容**：
- 环境变量文件名（如 `.env.local`）
- 关键变量名称和用途

**示例格式**：
```markdown
## Environment Variables

前端 `.env.local`：
- `YOUR_API_KEY`：外部服务 API Key（根据项目实际填写）
- `VITE_API_BASE_URL`：后端 API 地址（默认 http://localhost:8000）
```

---

### 6. Multi-Phase Project Tracking（多阶段项目追踪）

**适用场景**：大型任务会被 `/f-design` Skill 拆分为多个子任务时，需要此部分定义进度文件格式和管理规范。

**用途**：`/f-design` Skill 完成时创建进度文件；所有 Skill 启动时检查并更新进度文件；用户说"继续做"时读取进度文件确定下一步。

**需要填写的内容**：
- 进度文件路径规范
- 进度文件格式（子任务状态字段）
- 自动更新时机

**示例格式**：
```markdown
## Multi-Phase Project Tracking

进度文件路径：`.claude/workspace/_progress-$PROJECT.md`

格式：
- 子任务状态：已完成 / 进行中 / 待执行 / 已阻塞
- 每个 Skill 启动时将对应任务置为"进行中"，完成时置为"已完成"

用户说"继续做"时：读取进度文件 → 找到下一个"待执行"子任务 → 自动启动
```

---

### 7. Ongoing Work（长期任务上下文）

**适用场景**：项目有跨多次对话的长期任务（如持续迭代的功能、长期维护的模块）时填写，配合 `/f-context` Skill 使用。

**用途**：`/f-context save` 保存和恢复跨对话上下文；新对话开始时 Claude 自动读取上下文文件快速了解任务背景；`/f-context clean` 清理未被引用的对话记录。

**需要填写的内容**：
- 上下文文件存储位置
- 可用的 `/f-context` 命令列表

**示例格式**：
```markdown
## Ongoing Work

长期任务的上下文记录在 `.claude/context/`。每个文件对应一个跨多次对话的长期任务，包含背景、关键文件、会话日志和当前状态。

- 新对话开始时，如果用户提到某个长期任务，先读取 `.claude/context/` 下对应的上下文文件再开始工作
- 使用 `/f-context save` 在对话结束前保存上下文
- 使用 `/f-context load` 在新对话中加载之前的上下文
- 使用 `/f-context list` 查看所有活跃的长期任务
- 使用 `/f-context remove` 删除不再需要的上下文文件
- 使用 `/f-context clean` 定期清理未被引用的对话记录
```

---

## 命名约束

工作流系统的 Skill 名称（`f-dev`、`f-quick-dev` 等）、Agent 文件名（`code-engineer.md` 等）、Workspace 文件名（`01-requirements.md` 等）是**系统固定标识符**，在 `CLAUDE.md` 和其他配置中**不应引用自定义名称**。这些名称在所有项目中保持一致，确保跨项目的统一执行方式。

---

## 契约检查清单

新项目接入工作流系统时，逐条核对：

### 必需部分（8 项用户填写 + 1 项自动生成）

- [ ] **Project Overview**：项目描述、技术栈、关键端口已填写
- [ ] **Build Commands**：安装、启动、构建命令已填写
- [ ] **Testing**：测试框架、命令、文件位置、命名规范已填写
- [ ] **Architecture**：架构图、通信路径、分层结构、关键文件路径已填写
- [ ] **Code Style**：缩进、命名、TypeScript 严格程度、类型定义位置已填写
- [ ] **Adding New Features**：新增功能的必要步骤和顺序已填写
- [ ] **Commit Style**：语言、格式规范已填写
- [ ] **Language**：文档语言、代码标识符语言已填写
- [ ] **Capabilities**（自动生成）：10 个能力标签已填写，值与项目实际技术栈一致。此节由 `/f-init` 自动创建，Phase 0.7 不检查此节。

### 可选部分（按需）

- [ ] **i18n**：若有多语言，locale 文件位置、命名规范、基准语言已填写
- [ ] **Design System**：若有自定义 Token，Token 家族和暗色模式规范已填写
- [ ] **Database**：若有特定访问规范，ORM、安全要求已填写
- [ ] **Agent/DevOps**：若有 Agent 或特殊编译流程，版本管理和编译命令已填写
- [ ] **Environment Variables**：若有外部 API Key，变量名和文件名已填写
- [ ] **Multi-Phase Project Tracking**：若需要多阶段任务追踪，进度文件规范已填写
- [ ] **Ongoing Work**：若有跨多对话的长期任务，上下文存储位置和命令已填写

### 隐式条件（从 Capabilities 节读取）

以下条件不再需要"从必需部分推断"，而是直接从 Capabilities 节读取：

- **前端框架**：`Capabilities.frontend`。如值非 `false`，Code Reviewer 将执行对应的前端最佳实践检查。
- **WebSocket**：从 Architecture 通信路径表推断的隐式派生标签（仅在内存中，不写入 Capabilities）。如包含 WebSocket 通信路径，Code Engineer 的自检清单将包含 WebSocket 事件格式检查。
- **静态类型语言**：`Capabilities.static-types`。如值非 `false`，Integration Validator 将执行类型检查步骤。

### 功能验证

- [ ] 运行 `/f-dev 创建一个测试功能`，确认子代理能正确读取 CLAUDE.md
- [ ] 检查 Code Engineer 输出的代码是否符合项目代码风格
- [ ] 检查 Integration Validator 是否能成功执行构建和测试命令
