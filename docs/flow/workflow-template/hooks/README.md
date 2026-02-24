# Hook 适配指南

本目录包含 8 个 Git Hook 脚本，用于在 Claude Code 工作流的关键节点自动执行代码保护、质量检查和通知。

安装方法：
```bash
cp .claude/hooks/*.sh .git/hooks/
chmod +x .git/hooks/*.sh
```

---

## Hook 脚本一览

| 脚本 | 触发时机 | 是否需要适配 |
|------|----------|--------------|
| `protect-files.sh` | 每次 commit 前 | 不需要，通用 |
| `lint-check.sh` | 每次 commit 前 | 需要适配路径和命令 |
| `auto-format.sh` | 每次 commit 前 | 不需要，通用 |
| `run-related-tests.sh` | 每次 commit 前 | 需要适配路径和命令 |
| `check-coverage.sh` | 每次 push 前 | 需要适配阈值和路径 |
| `notify-completion.sh` | 每次 commit 后 | 不需要，macOS 通用 |
| `generate-report.sh` | 每次 push 前 | 需要适配 Workspace 前缀 |
| `git-guard.sh` | 每次 Bash 命令前 | 不需要，通用 |

---

## 1. protect-files.sh

### 功能描述

阻止对关键配置文件的直接 commit，防止误操作覆盖生产配置。受保护的文件包括：`package.json`（根目录）、数据库配置文件、环境变量文件（`.env`、`.env.local`、`.env.production`）。

### 何时触发

`pre-commit` — 每次执行 `git commit` 前自动运行。如果检测到受保护文件在暂存区，commit 会被拒绝并给出提示。

### 是否需要修改

**不需要修改**，脚本逻辑通用。如果你的项目有其他需要保护的文件，在脚本中的 `PROTECTED_FILES` 数组中添加：

```bash
# 示例：添加更多受保护文件
PROTECTED_FILES=(
  "package.json"
  ".env"
  ".env.local"
  ".env.production"
  "config/production.yml"   # 添加这行
  "secrets.json"            # 添加这行
)
```

---

## 2. lint-check.sh

### 功能描述

在 commit 前对暂存的源码文件运行 Lint 检查。只检查本次 commit 涉及的文件（非全量检查），避免因历史遗留问题阻塞提交。

### 何时触发

`pre-commit` — 每次执行 `git commit` 前自动运行。检测到暂存文件中有匹配的源码文件时执行 Lint，有 Lint 错误时拒绝 commit。

### 需要修改的行

脚本中有 2 处需要根据项目调整（带有 `PROJECT-SPECIFIC` 注释）：

**第 1 处：文件路径模式**

默认匹配模式：
```bash
# PROJECT-SPECIFIC: 修改为项目实际的源码路径模式
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E "\.(ts|tsx|js|jsx)$" | grep -E "^(src|backend/src)/")
```

根据项目目录结构修改 `grep -E "^(src|backend/src)/"` 部分：

```bash
# 示例：只检查前端 src 目录
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E "\.(ts|tsx)$" | grep -E "^src/")

# 示例：检查 Vue 项目
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E "\.(ts|vue)$" | grep -E "^(src|packages)/")

# 示例：Python 项目
STAGED_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep -E "\.py$" | grep -E "^(app|tests)/")
```

**第 2 处：Lint 命令**

默认命令：
```bash
# PROJECT-SPECIFIC: 修改为项目使用的 Lint 命令
npx eslint $STAGED_FILES --max-warnings 0
```

根据项目工具链修改：

```bash
# 示例：使用 Biome 替代 ESLint
npx biome check $STAGED_FILES

# 示例：使用 oxlint
npx oxlint $STAGED_FILES

# 示例：Python 项目使用 flake8
flake8 $STAGED_FILES --max-line-length 100

# 示例：Go 项目
golangci-lint run $STAGED_FILES
```

---

## 3. auto-format.sh

### 功能描述

在 commit 前自动格式化暂存的源码文件并重新加入暂存区。确保提交的代码符合统一格式，无需手动运行格式化工具。

### 何时触发

`pre-commit` — 每次执行 `git commit` 前自动运行。自动格式化后会重新执行 `git add`，格式化结果会包含在本次 commit 中。

### 是否需要修改

**通常不需要修改**。脚本会自动检测常见格式化工具（Prettier、Black、gofmt）并选择对应工具运行。

如果项目使用不在自动检测范围内的格式化工具，在脚本末尾的检测逻辑中添加：

```bash
# 示例：添加 Biome 支持
elif command -v biome &>/dev/null && [ -f "biome.json" ]; then
  biome format --write $STAGED_FILES
  git add $STAGED_FILES
```

---

## 4. run-related-tests.sh

### 功能描述

在 commit 前自动找到与本次变更相关的测试文件并运行。根据暂存的源文件名推断对应的测试文件（如 `Button.tsx` → `Button.test.tsx`），只运行相关测试而非全量测试，保证速度。

### 何时触发

`pre-commit` — 每次执行 `git commit` 前自动运行。如果找不到对应的测试文件，脚本会跳过（不报错）。测试失败时拒绝 commit。

### 需要修改的行

脚本中有 2 处需要根据项目调整（带有 `PROJECT-SPECIFIC` 注释）：

**第 1 处：文件路径模式**

默认配置：
```bash
# PROJECT-SPECIFIC: 修改为项目实际的源码路径模式
STAGED_SRC=$(git diff --cached --name-only --diff-filter=ACM | grep -E "^(src|backend/src)/" | grep -v "\.test\.")
```

根据项目目录结构修改：

```bash
# 示例：只检查 src 目录
STAGED_SRC=$(git diff --cached --name-only --diff-filter=ACM | grep -E "^src/" | grep -v "\.test\.")

# 示例：包含 packages 目录的 monorepo
STAGED_SRC=$(git diff --cached --name-only --diff-filter=ACM | grep -E "^packages/.*/src/" | grep -v "\.test\.")
```

**第 2 处：测试命令**

默认命令：
```bash
# PROJECT-SPECIFIC: 修改为项目的测试命令
npm test -- --run $TEST_FILE
```

根据测试框架修改：

```bash
# 示例：Vitest（后端）
cd backend && npm test -- --run $TEST_FILE

# 示例：Jest
npx jest $TEST_FILE --passWithNoTests

# 示例：Pytest（Python）
python -m pytest $TEST_FILE -x

# 示例：Go test
go test ./$(dirname $TEST_FILE)/...
```

---

## 5. check-coverage.sh

### 功能描述

在 push 前运行完整测试套件并检查覆盖率是否达标。如果覆盖率低于阈值，push 会被拒绝。这是比 `run-related-tests.sh` 更严格的全量检查，在推送到远程仓库前执行。

### 何时触发

`pre-push` — 每次执行 `git push` 前自动运行。比 pre-commit hook 运行更慢（全量测试），但只在推送时触发，不影响日常 commit 速度。

### 需要修改的行

脚本中有 3 处需要根据项目调整（带有 `PROJECT-SPECIFIC` 注释）：

**第 1 处：覆盖率阈值**

默认值：
```bash
# PROJECT-SPECIFIC: 修改为项目要求的最低覆盖率（0-100 的整数）
COVERAGE_THRESHOLD=80
```

根据团队质量要求修改：

```bash
# 示例：提高到 90%
COVERAGE_THRESHOLD=90

# 示例：降低到 70%（遗留项目接入初期）
COVERAGE_THRESHOLD=70
```

**第 2 处：测试和覆盖率生成命令**

默认命令：
```bash
# PROJECT-SPECIFIC: 修改为项目的覆盖率生成命令
npm test -- --coverage --run
```

根据测试框架修改：

```bash
# 示例：Vitest（指定 reporter）
npx vitest run --coverage --coverage.reporter=json

# 示例：Jest
npx jest --coverage --coverageReporters=json-summary

# 示例：Pytest + pytest-cov
python -m pytest --cov=app --cov-report=json

# 示例：Go（go test 原生覆盖率）
go test ./... -coverprofile=coverage.out
go tool cover -func=coverage.out
```

**第 3 处：覆盖率报告文件路径**

默认路径：
```bash
# PROJECT-SPECIFIC: 修改为项目实际的覆盖率报告文件路径
COVERAGE_FILE="coverage/coverage-summary.json"
```

根据测试框架输出修改：

```bash
# 示例：Vitest 默认输出
COVERAGE_FILE="coverage/coverage-summary.json"

# 示例：Jest 默认输出
COVERAGE_FILE="coverage/coverage-summary.json"

# 示例：Istanbul（lcov）
COVERAGE_FILE="coverage/lcov-report/index.html"
```

---

## 6. notify-completion.sh

### 功能描述

在 commit 完成后发送 macOS 系统通知，显示提交的文件数量和 commit hash。避免长时间 Claude Code 操作结束后用户没有注意到。

### 何时触发

`post-commit` — 每次 commit **成功完成后**自动运行（不影响 commit 结果）。

### 是否需要修改

**不需要修改**，使用 macOS 内置的 `osascript` 发送通知，无需额外依赖。

在 Linux 系统上，`osascript` 不可用，脚本会静默跳过（不报错）。如果需要在 Linux 上启用通知，将 `osascript` 替换为 `notify-send`：

```bash
# 示例：Linux 通知（需要 libnotify-bin）
notify-send "Git Commit 完成" "提交了 ${FILE_COUNT} 个文件 (${COMMIT_HASH})"
```

---

## 7. generate-report.sh

### 功能描述

在 push 前扫描当前的 Workspace 目录，汇总本次开发周期的所有 Workspace 文件（需求、设计、测试、实现、审查、验证）并生成 Markdown 格式的开发报告，保存到 `docs/reports/` 目录。

### 何时触发

`pre-push` — 每次执行 `git push` 前自动运行。报告会自动 add 到当前 commit（如果 push 时有文件待暂存），或者作为单独的文件存在于工作目录。

### 需要修改的行

脚本中有 2 处需要根据项目调整（带有 `PROJECT-SPECIFIC` 注释）：

**第 1 处：Workspace 前缀**

默认配置：
```bash
# PROJECT-SPECIFIC: 修改为项目使用的 Workspace 命名前缀
# feature-dev/quick-dev/light-dev 使用 "feature-"
# fix-bug 使用 "bugfix-"
# design 使用 "design-"
WORKSPACE_PREFIXES=("feature-" "bugfix-" "design-")
WORKSPACE_BASE=".claude/workspace"
```

如果修改了 Workspace 命名规范，对应更新此处。默认值与所有 Skill 的命名规范一致，通常不需要修改。

如果 Workspace 存放在不同路径，修改 `WORKSPACE_BASE`：

```bash
# 示例：Workspace 放在项目根目录
WORKSPACE_BASE="workspace"

# 示例：Workspace 放在 .dev 目录
WORKSPACE_BASE=".dev/workspace"
```

**第 2 处：阶段文件名**

默认配置：
```bash
# PROJECT-SPECIFIC: 修改为与 Skill 中定义的 Workspace 文件名一致
STAGE_FILES=(
  "00-input.md"
  "01-requirements.md"
  "02-design.md"
  "03-testplan.md"
  "04-implementation.md"
  "05-review.md"
  "06-validation.md"
  "07-delivery.md"
)
```

这些文件名与 Skill 定义的 Workspace 结构一一对应。如果修改了 Skill 中的文件命名，在此处同步更新。默认值与所有 Skill 定义一致，通常不需要修改。

---

## 8. git-guard.sh

### 功能描述

拦截 Claude Code 执行的 git 写操作（add、commit、push、reset、checkout、merge 等），保护代码仓库安全。只读 git 命令（status、log、diff、show、branch、tag、config 等）不受影响，可自由执行。

### 何时触发

`PreToolUse (Bash)` — 每次 Claude Code 执行 Bash 命令前自动检查。如果命令包含非白名单 git 子命令，执行会被拦截（exit 2），Claude 需向用户说明命令内容，由用户手动执行。

### 是否需要修改

**不需要修改**，脚本逻辑通用。如果需要额外放行某些 git 子命令（如 `fetch`、`stash`），在脚本中的 `READONLY_PATTERN` 白名单中添加：

```bash
# 示例：放行 git fetch 和 git stash
READONLY_PATTERN="^(status|log|diff|show|branch|remote|...|fetch|stash)$"
```

---

## 完整安装验证

安装 Hook 后，执行以下步骤验证是否正常工作：

```bash
# 1. 检查 Hook 文件已安装且有执行权限
ls -la .git/hooks/

# 2. 触发 pre-commit hook 测试
git add README.md
git commit -m "test: 测试 Hook 安装"
# 应该看到 protect-files、lint-check、run-related-tests 依次执行

# 3. 触发 pre-push hook 测试（模拟 push，不实际推送）
git push --dry-run
# 应该看到 check-coverage、generate-report 依次执行
```

如果某个 Hook 执行失败，检查脚本的 `PROJECT-SPECIFIC` 标记处是否已正确适配。
