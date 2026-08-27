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

with_lock() {   # the daemon and an interactive switch must not interleave
  if [ -n "${CCEX_LOCK_HELD:-}" ] || ! command -v flock >/dev/null 2>&1; then "$@"; return; fi
  mkdir -p "$ROOT"
  # A subshell, so the descriptor closes with it: a loop that switches twice must not still
  # be holding the lock from the first time. flock is per descriptor, so a nested call would
  # wait on a lock this process already has -- CCEX_LOCK_HELD is what makes it a no-op.
  ( export CCEX_LOCK_HELD=1
    # Long enough to sit out a switch that asks the account it is moving to first: up to
    # three of those, a session each. Waiting beats failing, because the thing being waited
    # for is the same switch this command wanted.
    flock -w "${CCEX_LOCK_WAIT:-60}" 9 || \
      die "another ccex is switching accounts; try again in a moment"
    "$@" ) 9>"$ROOT/.lock"
}

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
