# The background rotator: a systemd timer, and a foreground view of what it does.

monitor() {
  local sub=${1:-status}; shift || true
  local at=80 every= refresh=15m a
  while [ $# -gt 0 ]; do
    case "$1" in
      --at)    [ $# -ge 2 ] || die "--at needs a percentage"; at=$2; shift 2 ;;
      --every) [ $# -ge 2 ] || die "--every needs a duration like 5m"; every=$2; shift 2 ;;
      --refresh) [ $# -ge 2 ] || die "--refresh needs a duration like 15m"; refresh=$2; shift 2 ;;
      *)       die "unknown option '$1'" ;;
    esac
  done
  mkdir -p "$ROOT/.usage"
  [ -n "$every" ] || every=5m
  secs "$every" >/dev/null; secs "$refresh" >/dev/null    # fail here, not on every tick
  case "$sub" in
    tick)
      local before after out rc ts log
      log="$ROOT/.usage/rotate.log"
      before=$(live_email)
      out=$(rotate --at "$at" --no-launch --max-age "$(secs "$refresh")" 2>&1) && rc=0 || rc=$?
      after=$(live_email)
      ts=$(date '+%F %T')
      printf '%s\n%s\n' "$ts" "$out" > "$ROOT/.usage/.monitor-last"
      if [ "$before" != "$after" ] || [ "$rc" != 0 ]; then
        printf '%s  %s\n' "$ts" "$(printf '%s' "$out" | tr '\n' '~' | sed 's/~/ | /g')" >> "$log"
        if [ "$(wc -l < "$log")" -gt 200 ]; then    # months of switches, not years
          tail -n 200 "$log" > "$log.new" && mv "$log.new" "$log"
        fi
      fi
      printf '%s\n' "$out"
      return "$rc"
      ;;
    watch)
      local iv last='' now line five seven when name out key
      local presets=(10s 30s 1m 5m 15m 30m)
      iv=$(secs "$every"); [ "$iv" -ge 5 ] 2>/dev/null || die "--every must be at least 5s"
      # A watch you cannot re-pace is a watch you end up killing and restarting.
      wait_key() {
        [ -t 0 ] || { sleep "$iv"; return 0; }      # piped to a file: no keys to read
        key=; read -rsn1 -t "$iv" key || true
        case "$key" in
          [1-6]) every=${presets[$((key - 1))]}; iv=$(secs "$every")
                 printf 'ccex: interval %s\n' "$every" ;;
          r|R)   printf 'ccex: refreshing\n' ;;
          q|Q)   printf '\n'; exit 0 ;;
          ?)     printf 'ccex: %s? keys: 1-6 interval (%s), r refresh, q quit\n' \
                   "$key" "${presets[*]}" ;;
        esac
      }
      local stamp
      stamp() { find "$CCEX_LIB" "$CCEX_BIN" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1; }
      trap 'printf "\n"; exit 0' INT
      [ -t 0 ] && printf 'ccex: keys: 1-6 set interval (%s), r refresh now, q quit\n' "${presets[*]}"
      printf 'ccex: watching every %s, threshold %s%%%s\n' "$every" "$at" \
        "$(systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1 \
             && printf ', rotation by the timer' || printf ', rotating here')"
      printf '%-9s %-30s %-22s %-26s %s\n' TIME ACCOUNT 5H WEEKLY CHECKED
      stamp=$(stamp)
      while :; do
        if [ "$(stamp)" != "$stamp" ]; then     # ccex changed on disk; a loop this long-lived should not run stale code
          printf 'ccex: reloading, ccex was updated\n'
          exec "$CCEX_BIN" rotate --watch --every "$every" --at "$at" --refresh "$refresh"
        fi
        out=
        if ! systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1; then
          out=$(rotate --at "$at" --no-launch --max-age "$(secs "$refresh")" 2>&1) || true
          case "$out" in
            *"staying put"*) out= ;;                 # the boring case; the row below says it
            *) printf '%s\n' "$out" ;;              # nowhere to go, or something broke
          esac
        fi
        name= id= five= seven= when= flags= capcell=
        IFS=$'\t' read -r name id five seven when flags capcell \
          < <(limits --tsv --no-launch --max-age "$(secs "$refresh")") || true
        now=$(live_email)
        if [ -z "$five" ]; then
          printf '%-9s %s\n' "$(date +%T)" "limits unavailable"; wait_key; continue
        fi
        printf '%-9s %-30s %s %s %s\n' "$(date +%T)" "$now" "$five" "$seven" "$when"
        [ -n "$last" ] && [ "$last" != "$now" ] && printf '  ^ rotated: %s -> %s\n' "$last" "$now"
        last=$now
        wait_key
      done
      ;;
    install)
      local claude_dir=
      claude_dir=$(command -v claude 2>/dev/null) && claude_dir="$(dirname "$claude_dir"):" || claude_dir=
      mkdir -p "$UNIT"
      cat > "$UNIT/ccex-rotate.service" <<UNITEOF
[Unit]
Description=ccex: move off a Claude account that is out of room

[Service]
Type=oneshot
Environment=PATH=$claude_dir%h/.local/bin:/usr/local/bin:/usr/bin:/bin${CC_PROFILE_ROOT:+
Environment=CC_PROFILE_ROOT=$CC_PROFILE_ROOT}
ExecStart=$CCEX_BIN rotate --tick --at $at --refresh $refresh
UNITEOF
      cat > "$UNIT/ccex-rotate.timer" <<UNITEOF
[Unit]
Description=ccex: check Claude account limits every $every

[Timer]
OnStartupSec=1m
OnUnitActiveSec=$every
AccuracySec=30s
Persistent=true

[Install]
WantedBy=timers.target
UNITEOF
      systemctl --user daemon-reload
      systemctl --user enable --now ccex-rotate.timer
      printf 'ccex: rotating every %s at %s%%, re-checking anything older than %s; logs in %s\n' \
        "$every" "$at" "$refresh" "$ROOT/.usage/rotate.log"
      [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = yes ] || \
        printf 'ccex: the timer runs while you are logged in; `loginctl enable-linger %s` to keep it running otherwise\n' "$USER" >&2
      ;;
    stop)
      systemctl --user disable --now ccex-rotate.timer 2>/dev/null || true
      rm -f "$UNIT/ccex-rotate.timer" "$UNIT/ccex-rotate.service"
      systemctl --user daemon-reload
      printf 'ccex: background rotation removed; `ccex rotate --bg` puts it back\n'
      ;;
    status)
      if systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1; then
        systemctl --user list-timers ccex-rotate.timer --no-pager | sed -n '1,2p'
      else
        printf 'ccex: not running in the background (ccex rotate --bg)\n'
      fi
      [ -f "$ROOT/.usage/.monitor-last" ] && { printf '\nlast check:\n'; sed 's/^/  /' "$ROOT/.usage/.monitor-last"; }
      [ -s "$ROOT/.usage/rotate.log" ] && { printf '\nrotations:\n'; tail -5 "$ROOT/.usage/rotate.log" | sed 's/^/  /'; }
      return 0
      ;;
    log) [ -s "$ROOT/.usage/rotate.log" ] && cat "$ROOT/.usage/rotate.log" || printf 'ccex: no rotations logged yet\n' ;;
    *) die "usage: ccex rotate --bg|--watch|--status|--log|--stop" ;;
  esac
}