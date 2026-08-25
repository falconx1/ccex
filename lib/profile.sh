# Making an account live, and keeping parked profiles wired to your real config.

link_shared() {
  local d="$1" f stamp
  [ "$d" = "$BASE" ] && return 0
  stamp=$(date +%s)
  mkdir -p "$d"
  for f in "${SHARED_FILES[@]}" "${SHARED_DIRS[@]}"; do
    [ -e "$BASE/$f" ] || continue
    if [ -e "$d/$f" ] && [ ! -L "$d/$f" ]; then
      mv "$d/$f" "$d/$f.local.$stamp"
      printf 'ccex: kept a real %s aside as %s.local.%s\n' "$f" "$f" "$stamp" >&2
    fi
    ln -sfn "$BASE/$f" "$d/$f"
  done
}

link_shared_all() { local p; while read -r p; do link_shared "$(dir_for "$p")"; done < <(profiles); }

seed() {   # copy non-account config (onboarding, theme, folder trust) into a new profile
  local d="$1"
  [ "$d" = "$BASE" ] && return 0
  mkdir -p "$d"
  py seed "$d"
}

use_acct() { py use "$@"; }   # move a parked account's credential into the live ~/.claude slot

mark_switch() {   # sessions started before this moment still hold the old account's token
  mkdir -p "$ROOT/.usage"
  date +%s000 > "$ROOT/.usage/.switched"
}

do_use() {   # the one way an account becomes live; returns 3 if nothing actually moved
  local target=$1 check=1 before after a; shift
  local flags=()
  for a in "$@"; do
    case "$a" in --no-check) check=0 ;; *) flags+=("$a") ;; esac
  done
  before=$(live_email)
  use_acct "$target"
  after=$(live_email)
  [ "$before" = "$after" ] && return 3
  link_shared_all
  mark_switch                       # only now: sessions older than this hold the previous login
  [ "$check" = 1 ] && limits --quiet ${flags[@]+"${flags[@]}"}
  return 0
}
