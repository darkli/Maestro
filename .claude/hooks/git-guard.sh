#!/bin/bash
# @version 1.0.0
# Git 操作守卫 Hook — 拦截 git 写操作，保护代码仓库安全
#
# 策略：
#   - 允许只读 git 命令（status, log, diff, show, branch, tag, config 等）
#   - 拦截所有非白名单 git 子命令（含 add, commit, push, reset, checkout, merge 等），安全优先
#   - 被拦截时 Claude 应向用户说明命令内容，由用户手动执行
#
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# jq 不可用或命令为空时，安全起见拦截含 git 命令调用的命令
if [ -z "$COMMAND" ]; then
  # 尝试从原始输入中检测 git 命令调用（jq 可能不可用）
  # 要求 "git" 后跟空格，避免匹配文件路径中的 "git"（如 git-guard.sh）
  if echo "$INPUT" | grep -qE '(^|[[:space:]])git[[:space:]]'; then
    echo "Git 操作被拦截：无法解析命令（jq 可能未安装）。请先向用户说明你要执行的命令，由用户决定是否手动执行。" >&2
    exit 2
  fi
  exit 0
fi

# 不含 git 命令调用则放行
# 要求 "git" 后跟空格，排除文件路径中的 "git"（如 diff .../git-guard.sh）
if ! echo "$COMMAND" | grep -qE '(^|[[:space:]])git[[:space:]]'; then
  exit 0
fi

# 只读 git 子命令白名单
READONLY_PATTERN="^(status|log|diff|show|branch|remote|ls-files|ls-tree|rev-parse|describe|shortlog|blame|reflog|rev-list|cat-file|name-rev|tag|config)$"

# 提取命令中所有 git 子命令
GIT_SUBCMDS=$(echo "$COMMAND" | \
  grep -oE '(^|[[:space:]])git[[:space:]][^;&|]*' | \
  sed -E 's/^[[:space:]]*//' | \
  sed -E 's/[[:space:]]+(-C|-c|--git-dir|--work-tree|--namespace)[[:space:]]+[^ ]+/ /g' | \
  sed -E 's/[[:space:]]+--[a-z][-a-z]*=[^ ]+/ /g' | \
  sed -E 's/[[:space:]]+--no-[a-z][-a-z]*/ /g' | \
  sed -E 's/[[:space:]]+--bare/ /g' | \
  grep -oE 'git[[:space:]]+[a-z][-a-z]*' | \
  awk '{print $2}')

if [ -z "$GIT_SUBCMDS" ]; then
  echo "Git 操作被拦截：无法识别 git 子命令。请先向用户说明你要执行的命令，由用户决定是否手动执行。被拦截命令：${COMMAND}" >&2
  exit 2
fi

for subcmd in $GIT_SUBCMDS; do
  if ! echo "$subcmd" | grep -qE "$READONLY_PATTERN"; then
    echo "Git 写操作被拦截（git $subcmd）：请先向用户说明你要执行的命令及原因，由用户决定是否手动执行。被拦截命令：${COMMAND}" >&2
    exit 2
  fi
done

exit 0
