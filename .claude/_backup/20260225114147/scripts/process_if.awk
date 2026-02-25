# process_if.awk — IF/IF:NOT/ENDIF 条件块裁剪处理器
# 用法: awk -v caps="frontend=React,testing=vitest,websocket=true" -f process_if.awk input.md
# 兼容: POSIX awk (macOS BSD awk / gawk)

BEGIN {
  n = split(caps, arr, ",")
  for (i = 1; i <= n; i++) {
    idx = index(arr[i], "=")
    if (idx > 0) {
      key = substr(arr[i], 1, idx - 1)
      val = substr(arr[i], idx + 1)
      cap[key] = val
    }
  }
  depth = 0
  skip_depth = 0
}

# <!-- IF:NOT:xxx --> (must match before IF:xxx to avoid mismatch)
/<!-- IF:NOT:/ {
  s = $0
  sub(/.*<!-- IF:NOT:/, "", s)
  sub(/ *-->.*/, "", s)
  gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
  tag = s
  depth++
  if (skip_depth > 0) next
  val = (tag in cap) ? cap[tag] : "false"
  if (val != "false") skip_depth = depth
  next
}

# <!-- IF:xxx --> (exclude IF:NOT)
/<!-- IF:/ {
  if ($0 ~ /<!-- IF:NOT:/) next  # already handled above
  s = $0
  sub(/.*<!-- IF:/, "", s)
  sub(/ *-->.*/, "", s)
  gsub(/^[[:space:]]+|[[:space:]]+$/, "", s)
  tag = s
  depth++
  if (skip_depth > 0) next
  val = (tag in cap) ? cap[tag] : "false"
  if (val == "false") skip_depth = depth
  next
}

# <!-- ENDIF:NOT:xxx -->
/<!-- ENDIF:NOT:/ {
  if (skip_depth == depth) skip_depth = 0
  if (depth > 0) depth--
  next
}

# <!-- ENDIF:xxx --> (exclude ENDIF:NOT)
/<!-- ENDIF:/ {
  if ($0 ~ /<!-- ENDIF:NOT:/) next  # already handled above
  if (skip_depth == depth) skip_depth = 0
  if (depth > 0) depth--
  next
}

{ if (skip_depth == 0) print }

END {
  if (depth != 0)
    print "process_if.awk: WARNING: unbalanced IF/ENDIF, depth=" depth > "/dev/stderr"
  if (skip_depth != 0)
    print "process_if.awk: WARNING: unclosed skip block, skip_depth=" skip_depth > "/dev/stderr"
}
