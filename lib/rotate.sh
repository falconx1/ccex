# Moving off an account that is running out of room, onto the one with the most left.

rotate() {
  local plan pick nolaunch=
  case " $* " in *" --no-launch "*) nolaunch=--no-launch ;; esac
  plan=$(limits --all --json $nolaunch | py rotate "$@") || return 1
  IFS=$'\t' read -r verdict a b <<<"$plan"
  case "$verdict" in
    STAY)   printf 'ccex: staying put - %s\n' "$a" ;;
    NONE)   printf 'ccex: %s\n' "$a" >&2; return 1 ;;
    ERR)    die "$a" ;;
    SWITCH) pick=$a
            printf 'ccex: %s\n' "$b"
            case " $* " in *" -n "*|*" --dry-run "*) printf 'ccex: dry run, nothing written\n'; return 0 ;; esac
            do_use "$pick" ;;
  esac
}
