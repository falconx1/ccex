# Moving off an account that is running out of room, onto the one with the most left.

# The lock covers the decision as well as the switch, so a second arrival re-reads the
# numbers the first one has already changed instead of acting on what it saw before them.
rotate() { with_lock rotate_now "$@"; }

rotate_now() {
  local plan pick pass=() a keep=
  for a in "$@"; do                     # --no-launch and --max-age belong to limits, not to the decision
    if [ -n "$keep" ]; then pass+=("$a"); keep=; continue; fi
    case "$a" in --no-launch) pass+=("$a") ;; --max-age) pass+=("$a"); keep=1 ;; esac
  done
  plan=$(limits --all --json ${pass[@]+"${pass[@]}"} | py rotate "$@") || return 1
  IFS=$'\t' read -r verdict a b <<<"$plan"
  case "$verdict" in
    STAY)   printf 'ccex: staying put - %s\n' "$a" ;;
    NONE)   printf 'ccex: %s\n' "$a" >&2; return 1 ;;
    ERR)    die "$a" ;;
    SWITCH) pick=$a
            printf 'ccex: %s\n' "$b"
            case " $* " in *" -n "*|*" --dry-run "*) printf 'ccex: dry run, nothing written\n'; return 0 ;; esac
            local rc=0
            do_use "$pick" ${pass[@]+"${pass[@]}"} || rc=$?
            case "$rc" in
              0) ;;
              3) printf 'ccex: %s was already live; nothing moved\n' "$pick" ;;
              *) printf 'ccex: %s did not become live; nothing changed\n' "$pick" >&2; return 1 ;;
            esac
            ;;
  esac
}
