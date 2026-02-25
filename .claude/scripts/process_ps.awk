# process_ps.awk — PROJECT-SPECIFIC 块替换处理器
# 用法: awk -v ps_index="path/to/ps-index.txt" -f process_ps.awk input.md
# ps-index.txt 格式: 说明文本<TAB>替换文件路径
# 兼容: POSIX awk (macOS BSD awk / gawk)

BEGIN {
  in_ps = 0
  if (ps_index != "") {
    while ((getline line < ps_index) > 0) {
      idx = index(line, "\t")
      if (idx > 0) {
        key = substr(line, 1, idx - 1)
        val = substr(line, idx + 1)
        ps_map[key] = val
      }
    }
    close(ps_index)
  }
}

/<!-- PROJECT-SPECIFIC:/ {
  s = $0
  sub(/.*PROJECT-SPECIFIC: */, "", s)
  sub(/ *-->.*/, "", s)
  desc = s
  if (desc in ps_map) {
    in_ps = 1
    f = ps_map[desc]
    while ((getline line < f) > 0) print line
    close(f)
    next
  }
  # not in map: keep as-is (inline comment or fallback to template default)
  print
  next
}

/<!-- \/PROJECT-SPECIFIC -->/ {
  if (in_ps) {
    in_ps = 0
    next
  }
  print
  next
}

{ if (!in_ps) print }

END {
  if (in_ps)
    print "process_ps.awk: WARNING: unclosed PROJECT-SPECIFIC block at EOF" > "/dev/stderr"
}
