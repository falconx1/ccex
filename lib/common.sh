# Where everything lives, and the small helpers every other module leans on.

BASE="$HOME/.claude"
ROOT="${CC_PROFILE_ROOT:-$HOME/.claude-profiles}"
SHARED_FILES=(settings.json CLAUDE.md)
SHARED_DIRS=(plugins projects todos tasks file-history)
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

export CCEX_BASE="$BASE" CCEX_ROOT="$ROOT"
export PYTHONPATH="$CCEX_PY${PYTHONPATH:+:$PYTHONPATH}"

die() { printf 'ccex: %s\n' "$*" >&2; exit 1; }

py() { python3 "$CCEX_PY/$1.py" "${@:2}"; }

dir_for() {
  case "$1" in
    default) printf '%s\n' "$BASE" ;;
    ''|.|..|*/*) die "bad profile name: '$1'" ;;
    *) printf '%s\n' "$ROOT/$1" ;;
  esac
}

profiles() {   # the live account, then every parked slot that still holds a login
  printf 'default\n'
  [ -d "$ROOT" ] || return 0
  local p
  for p in "$ROOT"/*/; do
    [ -d "$p" ] && grep -qs claudeAiOauth "$p/.credentials.json" && basename "$p"
  done
}

info() { py info "$1"; }

live_email() { IFS=$'\t' read -r e _ < <(info "$BASE"); printf '%s' "$e"; }

secs() {   # 30s / 5m / 1h / plain seconds
  case "$1" in
    [!0-9]*) ;;
    *[!0-9]*[smh]) ;;
    *s) printf '%s' "${1%s}"; return ;;
    *m) printf '%s' "$(( ${1%m} * 60 ))"; return ;;
    *h) printf '%s' "$(( ${1%h} * 3600 ))"; return ;;
    *[!0-9]*) ;;
    *) printf '%s' "$1"; return ;;
  esac
  die "cannot read '$1' as a duration; try 30s, 5m or 1h"
}
