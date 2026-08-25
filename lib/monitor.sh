# The background rotator: a systemd timer, and a foreground view of what it does.

monitor() {
  local sub=${1:-status}; shift || true
  local at=80 every= refresh=15m a
  while [ $# -gt 0 ]; do
    case "$1" in
      --at)    [ $# -ge 2 ] || die "monitor: --at needs a percentage"; at=$2; shift 2 ;;
      --every) [ $# -ge 2 ] || die "monitor: --every needs a duration like 5m"; every=$2; shift 2 ;;
      --refresh) [ $# -ge 2 ] || die "monitor: --refresh needs a duration like 15m"; refresh=$2; shift 2 ;;
      *)       die "monitor: unknown option '$1'" ;;
    esac
  done
  mkdir -p "$ROOT/.usage"
  [ -n "$every" ] || every=5m
  case "$sub" in
    tick)
      local before after out rc ts
      before=$(live_email)
      out=$(rotate --at "$at" --no-launch --max-age "$(secs "$refresh")" 2>&1) && rc=0 || rc=$?
      after=$(live_email)
      ts=$(date '+%F %T')
      printf '%s\n%s\n' "$ts" "$out" > "$ROOT/.usage/.monitor-last"
      if [ "$before" != "$after" ] || [ "$rc" != 0 ]; then
        printf '%s  %s\n' "$ts" "$(printf '%s' "$out" | tr '\n' '~' | sed 's/~/ | /g')" \
          >> "$ROOT/.usage/rotate.log"
      fi
      printf '%s\n' "$out"
      return "$rc"
      ;;
    watch)
      local iv last='' now line five seven when name out
      iv=$(secs "$every"); [ "$iv" -ge 5 ] 2>/dev/null || die "monitor watch: --every must be at least 5s"
      local stamp
      stamp() { find "$CCEX_LIB" "$CCEX_BIN" -type f -printf '%T@\n' 2>/dev/null | sort -rn | head -1; }
      trap 'printf "\n"; exit 0' INT
      printf 'ccex: watching every %s, threshold %s%%%s\n' "$every" "$at" \
        "$(systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1 \
             && printf ', rotation by the timer' || printf ', rotating here')"
      printf '%-9s %-30s %-22s %-26s %s\n' TIME ACCOUNT 5H WEEKLY CHECKED
      stamp=$(stamp)
      while :; do
        if [ "$(stamp)" != "$stamp" ]; then     # ccex changed on disk; a loop this long-lived should not run stale code
          printf 'ccex: reloading, ccex was updated\n'
          exec "$CCEX_BIN" monitor watch --every "$every" --at "$at" --refresh "$refresh"
        fi
        if ! systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1; then
          out=$(rotate --at "$at" --no-launch --max-age "$(secs "$refresh")" 2>&1) || true
        fi
        name= five= seven= when=
        IFS=$'\t' read -r name five seven when < <(limits --tsv --no-launch --max-age "$(secs "$refresh")") || true
        now=$(live_email)
        if [ -z "$five" ]; then
          printf '%-9s %s\n' "$(date +%T)" "limits unavailable"; sleep "$iv"; continue
        fi
        printf '%-9s %-30s %s %s %s\n' "$(date +%T)" "$now" "$five" "$seven" "$when"
        [ -n "$last" ] && [ "$last" != "$now" ] && printf '  ^ rotated: %s -> %s\n' "$last" "$now"
        last=$now
        sleep "$iv"
      done
      ;;
    install)
      mkdir -p "$UNIT"
      cat > "$UNIT/ccex-rotate.service" <<UNITEOF
[Unit]
Description=ccex: move off a Claude account that is out of room

[Service]
Type=oneshot
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin${CC_PROFILE_ROOT:+
Environment=CC_PROFILE_ROOT=$CC_PROFILE_ROOT}
ExecStart=$CCEX_BIN monitor tick --at $at --refresh $refresh
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
    stop|uninstall)
      systemctl --user disable --now ccex-rotate.timer 2>/dev/null || true
      [ "$sub" = uninstall ] && rm -f "$UNIT/ccex-rotate.timer" "$UNIT/ccex-rotate.service" && systemctl --user daemon-reload
      printf 'ccex: monitor %s\n' "$([ "$sub" = uninstall ] && echo removed || echo stopped)"
      ;;
    status)
      if systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1; then
        systemctl --user list-timers ccex-rotate.timer --no-pager | sed -n '1,2p'
      else
        printf 'ccex: monitor not installed (ccex monitor install --every 5m --at 80)\n'
      fi
      [ -f "$ROOT/.usage/.monitor-last" ] && { printf '\nlast check:\n'; sed 's/^/  /' "$ROOT/.usage/.monitor-last"; }
      [ -s "$ROOT/.usage/rotate.log" ] && { printf '\nrotations:\n'; tail -5 "$ROOT/.usage/rotate.log" | sed 's/^/  /'; }
      return 0
      ;;
    log) [ -s "$ROOT/.usage/rotate.log" ] && cat "$ROOT/.usage/rotate.log" || printf 'ccex: no rotations logged yet\n' ;;
    *) die "usage: ccex monitor watch|install|status|stop|uninstall|tick|log" ;;
  esac
}