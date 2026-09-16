# Where everything lives, and the small helpers every other module leans on.

BASE="$HOME/.claude"
ROOT="${CC_PROFILE_ROOT:-$HOME/.claude-profiles}"
SHARED_FILES=(settings.json CLAUDE.md)
SHARED_DIRS=(plugins projects todos tasks file-history)
OS=$(uname -s 2>/dev/null || printf 'unknown')

export CCEX_BASE="$BASE" CCEX_ROOT="$ROOT"
export PYTHONPATH="$CCEX_PY${PYTHONPATH:+:$PYTHONPATH}"

die() { printf 'ccex: %s\n' "$*" >&2; exit 1; }

py() {   # shift rather than "${@:2}": bash 3.2, which macOS ships, joins that slice into
  # one word whenever IFS has been changed -- as it is around every `read -r a b < <(py ...)`
  local m=$1; shift
  python3 "$CCEX_PY/$m.py" "$@"
}

# Two accounts cannot change hands at once: the daemon and an interactive `ccex use` must
# not interleave. `with_lock` is the rule -- once held, held -- and `hold_lock` is whichever
# mechanism this machine has for it, chosen here rather than on every call.

if command -v flock >/dev/null 2>&1; then

  hold_lock() {
    # A subshell, so the descriptor closes with it: a loop that switches twice must not still
    # be holding the lock from the first time. flock is per descriptor, so a nested call would
    # wait on a lock this process already has -- CCEX_LOCK_HELD is what makes it a no-op.
    ( export CCEX_LOCK_HELD=1
      # Long enough to sit out a switch that asks the accounts it is moving to first: three of
      # them, a session each, and a session that will not answer waits out its own timeout.
      # Waiting beats failing, because what is being waited for is the switch this command
      # wanted anyway.
      flock -w "${CCEX_LOCK_WAIT:-180}" 9 || \
        die "another ccex is switching accounts; try again in a moment"
      "$@" ) 9>"$ROOT/.lock"
  }

else

  hold_lock() {   # macOS ships without flock. A directory is the mutex instead: mkdir is
    # atomic wherever there is a filesystem, and the pid written inside it is how a lock left
    # behind by a killed switch is told from one a live switch is still holding.
    local d="$ROOT/.lock.d" waited=0 owner= rc=0
    until mkdir "$d" 2>/dev/null; do
      owner=$(cat "$d/pid" 2>/dev/null) || owner=
      if [ -n "$owner" ] && ! kill -0 "$owner" 2>/dev/null; then
        rm -rf "$d"; continue
      fi
      [ "$waited" -lt "${CCEX_LOCK_WAIT:-180}" ] || \
        die "another ccex is switching accounts; try again in a moment"
      sleep 1; waited=$((waited + 1))
    done
    printf '%s\n' "$$" > "$d/pid"
    ( export CCEX_LOCK_HELD=1; "$@" ) || rc=$?
    rm -rf "$d"
    return "$rc"
  }

fi

with_lock() {
  if [ -n "${CCEX_LOCK_HELD:-}" ]; then "$@"; return; fi
  mkdir -p "$ROOT"
  hold_lock "$@"
}

dir_for() {
  case "$1" in
    default) printf '%s\n' "$BASE" ;;
    ''|.|..|*/*) die "bad profile name: '$1'" ;;
    *) printf '%s\n' "$ROOT/$1" ;;
  esac
}

profiles() {   # the live account, then every parked slot that still holds a login
  # Asked of the python side because what counts as a login is not always a file: on macOS
  # it is a keychain item, and there is nothing in the directory to grep for.
  py slots
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
