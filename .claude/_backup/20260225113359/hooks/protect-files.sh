#!/bin/bash
# @version 1.0.0
# 从 stdin 读取 JSON，检查目标文件是否为敏感文件
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty')

if [ -z "$FILE_PATH" ]; then
  exit 0
fi

# 子串匹配列表（文件路径包含则拒绝）
PROTECTED_SUBSTRINGS=(".env" "package-lock.json" "yarn.lock" "credentials")

# 后缀匹配列表（文件以此结尾则拒绝）
PROTECTED_SUFFIXES=(".key" ".pem")

for pattern in "${PROTECTED_SUBSTRINGS[@]}"; do
  case "$FILE_PATH" in
    *"$pattern"*)
      echo "拒绝编辑敏感文件: $FILE_PATH" >&2
      exit 2
      ;;
  esac
done

for suffix in "${PROTECTED_SUFFIXES[@]}"; do
  case "$FILE_PATH" in
    *"$suffix")
      echo "拒绝编辑敏感文件: $FILE_PATH" >&2
      exit 2
      ;;
  esac
done

exit 0  # exit 0 = 允许
