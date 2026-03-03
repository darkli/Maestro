# Hook 适配指南

本目录包含 6 个 Hook 脚本，通过 Claude Code 的 Hook 机制在关键节点自动执行代码保护、质量检查和通知。

Hook 通过 `settings.json` 配置，由 `/f-init` 自动安装到 `.claude/hooks/`。

---

## Hook 脚本一览

| 脚本 | 触发事件 | 是否需要适配 |
|------|----------|--------------|
| `protect-files.sh` | `PreToolUse(Edit\|Write)` — 编辑/写入文件前 | 不需要，通用 |
| `auto-format.sh` | `PostToolUse(Edit\|Write)` — 编辑/写入文件后 | 由 f-init 自动配置 |
| `run-related-tests.sh` | `PostToolUse(Edit)` (async, 300s timeout) — 编辑文件后 | 由 f-init 自动配置 |
| `git-guard.sh` | `PreToolUse(Bash)` — 执行 Bash 命令前 | 不需要，通用 |
| `notify-completion.sh` | `Stop` (async) — 会话结束时 | 不需要，macOS 通用 |
| `generate-report.sh` | `Stop` (async) — 会话结束时 | 由 f-init 自动配置 |

---

## 1. protect-files.sh

### 功能描述

阻止对敏感文件的直接修改，防止误操作覆盖锁文件、密钥文件或环境变量。使用两种匹配规则：

- **子串匹配**（路径中包含则拒绝）：`.env`、`package-lock.json`、`yarn.lock`、`credentials`
- **后缀匹配**（文件名以此结尾则拒绝）：`.key`、`.pem`

例如 `.env`、`.env.local`、`.env.production` 都会被子串规则命中。

### 何时触发

`PreToolUse(Edit|Write)` — 每次 Claude Code 使用 Edit 或 Write 工具前自动运行。如果检测到目标文件匹配保护规则，操作会被拦截。

### 是否需要修改

**不需要修改**，脚本逻辑通用。如果你的项目有其他需要保护的文件，在脚本中对应数组中添加：

```bash
# 子串匹配：路径包含以下字符串则拒绝
PROTECTED_SUBSTRINGS=(".env" "package-lock.json" "yarn.lock" "credentials"
  "config/production"   # 添加这行
)

# 后缀匹配：文件以此结尾则拒绝
PROTECTED_SUFFIXES=(".key" ".pem"
  ".secret"             # 添加这行
)
```

---

## 2. auto-format.sh

### 功能描述

在文件编辑/写入后自动格式化源码文件。确保代码符合统一格式，无需手动运行格式化工具。

### 何时触发

`PostToolUse(Edit|Write)` — 每次 Claude Code 使用 Edit 或 Write 工具后自动运行。

### 配置方式

脚本顶部有两个配置变量，由 `/f-init` 根据项目技术栈自动填充：

```bash
# === 配置区域（由 f-init 填充） ===
FORMAT_CMD=""                          # 格式化命令（如 "npx prettier --write"）
FILE_PATTERNS="*.ts|*.tsx|*.js|*.jsx"  # 需要格式化的文件 glob 模式（管道分隔）
# === 配置区域结束 ===
```

`FORMAT_CMD` 为空时脚本自动跳过（不执行格式化）。如需手动配置，直接修改这两个变量：

```bash
# 示例：Prettier
FORMAT_CMD="npx prettier --write"
FILE_PATTERNS="*.ts|*.tsx|*.js|*.jsx|*.css"

# 示例：Black (Python)
FORMAT_CMD="black"
FILE_PATTERNS="*.py"

# 示例：gofmt
FORMAT_CMD="gofmt -w"
FILE_PATTERNS="*.go"
```

---

## 3. run-related-tests.sh

### 功能描述

在文件编辑后自动找到与本次变更相关的测试文件并运行。根据变更的源文件名推断对应的测试文件（如 `Button.tsx` → `Button.test.tsx`），只运行相关测试而非全量测试，保证速度。

### 何时触发

`PostToolUse(Edit)` (async, 300s timeout) — 每次 Claude Code 使用 Edit 工具后异步运行。如果找不到对应的测试文件，脚本会跳过（不报错）。测试失败时会在后台通知。

### 配置方式

脚本顶部有 4 个配置变量，由 `/f-init` 根据项目技术栈自动填充：

```bash
# === 配置区域（由 f-init 填充） ===
CAPABILITY_TESTING="vitest"                        # 测试框架名，"false" 表示项目未配置测试
TEST_CMD="npm test"                                # 测试命令
SOURCE_PATTERNS="src/*.ts|src/*.tsx"                # 源码文件 glob 模式（管道分隔）
TEST_FILE_PATTERNS="src/*.test.ts|src/*.test.tsx"   # 测试文件 glob 模式（管道分隔）
# === 配置区域结束 ===
```

**工作原理**：脚本从 Hook stdin JSON 中提取被编辑的 `file_path`，用 `match_patterns` 匹配 `SOURCE_PATTERNS`（支持深层路径，如 `src/*.ts` 可匹配 `src/utils/helper.ts`）。如果匹配成功且文件不是测试文件本身，则通过 `run_test` 函数执行测试——该函数根据 `CAPABILITY_TESTING` 和 `TEST_CMD` 格式自动构造正确的命令（如 `npm test` 会自动添加 `--` 分隔符）。`CAPABILITY_TESTING` 为 `false` 时脚本直接跳过。

如需手动配置，直接修改这些变量：

```bash
# 示例：前后端分离项目
SOURCE_PATTERNS="src/*.ts|src/*.tsx|backend/src/*.ts"
TEST_FILE_PATTERNS="src/*.test.ts|src/*.test.tsx|backend/src/*.test.ts"
TEST_CMD="npx vitest run"

# 示例：Python 项目
SOURCE_PATTERNS="src/*.py|lib/*.py"
TEST_FILE_PATTERNS="tests/*.py"
TEST_CMD="pytest"
```

---

## 4. git-guard.sh

### 功能描述

拦截 Claude Code 执行的 git 写操作（add、commit、push、reset、checkout、merge 等），保护代码仓库安全。只读 git 命令（status、log、diff、show、branch、tag、config 等）不受影响，可自由执行。

### 何时触发

`PreToolUse(Bash)` — 每次 Claude Code 执行 Bash 命令前自动检查。如果命令包含非白名单 git 子命令，执行会被拦截（exit 2），Claude 需向用户说明命令内容，由用户手动执行。

### 是否需要修改

**不需要修改**，脚本逻辑通用。如果需要额外放行某些 git 子命令（如 `fetch`、`stash`），在脚本中的 `READONLY_PATTERN` 白名单中添加：

```bash
# 示例：放行 git fetch 和 git stash
READONLY_PATTERN="^(status|log|diff|show|branch|remote|...|fetch|stash)$"
```

---

## 5. notify-completion.sh

### 功能描述

在会话结束时发送 macOS 系统通知，提示用户 Claude Code 操作已完成。避免长时间操作结束后用户没有注意到。

### 何时触发

`Stop` (async) — 每次 Claude Code 会话结束时异步运行（不影响会话结果）。

### 是否需要修改

**不需要修改**，使用 macOS 内置的 `osascript` 发送通知，无需额外依赖。

在 Linux 系统上，`osascript` 不可用，脚本会静默跳过（不报错）。如果需要在 Linux 上启用通知，将 `osascript` 替换为 `notify-send`：

```bash
# 示例：Linux 通知（需要 libnotify-bin）
notify-send "Claude Code 会话结束" "操作已完成"
```

---

## 6. generate-report.sh

### 功能描述

在会话结束时扫描当前的 Workspace 目录，汇总本次开发周期的所有 Workspace 文件（需求、设计、测试、实现、审查、验证）并生成 Markdown 格式的开发报告，保存到 `docs/reports/` 目录。

### 何时触发

`Stop` (async) — 每次 Claude Code 会话结束时异步运行。报告作为文件存在于工作目录，需要手动提交。

### 配置方式

脚本中有 2 处可根据项目调整（带有 `[PROJECT-SPECIFIC]` 注释）：

**第 1 处：Workspace 前缀**

默认配置通过 `ls -dt` glob 模式查找最近修改的 Workspace 目录：

```bash
# [PROJECT-SPECIFIC] 修改 Workspace 目录 glob 模式
WS_DIR=$(ls -dt .claude/workspace/feature-* .claude/workspace/bugfix-* .claude/workspace/design-* .claude/workspace/product-* .claude/workspace/doc-* 2>/dev/null | head -1)
```

默认值覆盖所有 Skill 的 Workspace 前缀（`feature-`、`bugfix-`、`design-`、`product-`、`doc-`），通常不需要修改。

**第 2 处：报告输出目录**

```bash
# [PROJECT-SPECIFIC] 修改报告输出目录
REPORT_DIR="./docs/reports"
```

**文件检测方式**：脚本使用 `find "$WS_DIR" -maxdepth 1 -name "*.md"` 动态检测 Workspace 中的所有 Markdown 文件，自动适配各 Skill 不同的文件命名（如 f-dev 的 `01-requirements.md`、f-bugfix 的 `01-diagnosis.md` 等），无需手动配置文件名列表。

---

## 共享依赖

`auto-format.sh` 和 `run-related-tests.sh` 依赖 `scripts/common.sh` 提供的 `match_patterns` 函数（文件模式匹配）。Hook 启动时通过相对路径 `../scripts/common.sh` 加载。`/f-init` 会同时安装 hooks 和 scripts，确保依赖关系完整。

---

## 完整安装验证

Hook 由 `/f-init` 自动安装。安装完成后，可通过以下方式验证：

```bash
# 1. 检查 Hook 文件已安装且有执行权限
ls -la .claude/hooks/*.sh

# 2. 检查 settings.json 已包含 Hook 配置
cat .claude/settings.json | jq '.hooks'

# 3. Hook 数量应为 6
ls .claude/hooks/*.sh | wc -l
# 输出应为 6

# 4. 检查 scripts/common.sh 存在（Hook 共享依赖）
ls .claude/scripts/common.sh
```

如果某个 Hook 执行失败，检查脚本的 `PROJECT-SPECIFIC` 标记处是否已正确适配。
