# Usage limits: reading them, and letting running sessions report them for free.

limits() { py limits "$@"; }

record() {   # read a Claude Code statusline payload on stdin, note the limits, pass it through
  local input now last stamp
  IFS= read -r -d '' input || true
  printf '%s' "$input"             # a statusline filter must be transparent, always
  now=$(date +%s)                  # not printf %(%s)T: bash 3.2, which is what macOS ships
  stamp="$ROOT/.usage/.stamp-$(basename "${CLAUDE_CONFIG_DIR:-default}")"
  last=0; [ -f "$stamp" ] && read -r last < "$stamp" || true
  [ $((now - last)) -lt 15 ] && return 0    # renders are constant; one write every 15s is plenty
  mkdir -p "$ROOT/.usage" && printf '%s\n' "$now" > "$stamp"
  printf '%s' "$input" | py record >/dev/null
}
