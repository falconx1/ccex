# The background rotator: a resident service that switches as soon as a number lands,
# and a foreground view of what it does.

bg_running() {   # is anything already rotating in the background: the daemon, or an old timer
  systemctl --user is-active ccex-rotate.service >/dev/null 2>&1 ||
    systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1
}

monitor() {
  local sub=${1:-status}; shift || true
  local at=90 every= refresh=0 rsec age=()   # 90 is decide.py's FIVE_AT
  while [ $# -gt 0 ]; do
    case "$1" in
      --at)    [ $# -ge 2 ] || die "--at needs a percentage"; at=$2; shift 2 ;;
      --every) [ $# -ge 2 ] || die "--every needs a duration like 5s"; every=$2; shift 2 ;;
      --refresh) [ $# -ge 2 ] || die "--refresh needs a duration like 15m"; refresh=$2; shift 2 ;;
      *)       die "unknown option '$1'" ;;
    esac
  done
  mkdir -p "$ROOT/.usage"
  # The daemon reacts to a file landing, so it wants seconds; --watch prints a line per
  # check, which nobody wants five times a minute.
  [ -n "$every" ] || case "$sub" in install|serve) every=10s ;; *) every=5m ;; esac
  secs "$every" >/dev/null                    # fail here, not on every tick
  rsec=$(secs "$refresh"); [ "$rsec" = 0 ] || age=(--max-age "$rsec")
  case "$sub" in
    tick)
      local before after out rc ts log
      log="$ROOT/.usage/rotate.log"
      before=$(live_email)
      out=$(rotate --at "$at" --no-launch ${age[@]+"${age[@]}"} 2>&1) && rc=0 || rc=$?
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
      local iv last='' now five seven when name id flags capcell out key
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
        "$(bg_running && printf ', rotation in the background' || printf ', rotating here')"
      printf '%-9s %-30s %-22s %-26s %s\n' TIME ACCOUNT 5H WEEKLY CHECKED
      stamp=$(stamp)
      while :; do
        if [ "$(stamp)" != "$stamp" ]; then     # ccex changed on disk; a loop this long-lived should not run stale code
          printf 'ccex: reloading, ccex was updated\n'
          exec "$CCEX_BIN" rotate --watch --every "$every" --at "$at" --refresh "$refresh"
        fi
        out=
        if ! bg_running; then
          out=$(rotate --at "$at" --no-launch ${age[@]+"${age[@]}"} 2>&1) || true
          case "$out" in
            *"staying put"*) out= ;;                 # the boring case; the row below says it
            *) printf '%s\n' "$out" ;;              # nowhere to go, or something broke
          esac
        fi
        IFS=$'\t' read -r name id five seven when flags capcell \
          < <(limits --tsv --no-launch ${age[@]+"${age[@]}"}) || true
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
    serve)
      exec python3 "$CCEX_PY/watch.py" --serve --at "$at" --every "$(secs "$every")" \
        --refresh "$rsec"
      ;;
    install)
      local claude_dir=
      claude_dir=$(command -v claude 2>/dev/null) && claude_dir="$(dirname "$claude_dir"):" || claude_dir=
      mkdir -p "$UNIT"
      cat > "$UNIT/ccex-rotate.service" <<UNITEOF
[Unit]
Description=ccex: move off a Claude account that is out of room, as soon as it is
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=10
Nice=5
Environment=PATH=$claude_dir%h/.local/bin:/usr/local/bin:/usr/bin:/bin${CC_PROFILE_ROOT:+
Environment=CC_PROFILE_ROOT=$CC_PROFILE_ROOT}
ExecStart=$CCEX_BIN rotate --serve --at $at --every $every --refresh $refresh

[Install]
WantedBy=default.target
UNITEOF
      if [ -f "$UNIT/ccex-rotate.timer" ]; then     # from when this woke up instead of watching
        systemctl --user disable --now ccex-rotate.timer >/dev/null 2>&1 || true
        rm -f "$UNIT/ccex-rotate.timer"
        printf 'ccex: replaced the old wake-up timer with a resident watcher\n' >&2
      fi
      systemctl --user daemon-reload
      systemctl --user reenable ccex-rotate.service >/dev/null 2>&1 || \
        systemctl --user enable ccex-rotate.service >/dev/null 2>&1
      systemctl --user restart ccex-rotate.service
      printf 'ccex: rotating at %s%% the moment a session reports it, checked every %s; logs in %s\n' \
        "$at" "$every" "$ROOT/.usage/rotate.log"
      [ "$rsec" = 0 ] || \
        printf 'ccex: and one real check when nothing has reported for %s\n' "$refresh"
      [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = yes ] || \
        printf 'ccex: it runs while you are logged in; `loginctl enable-linger %s` to keep it running otherwise\n' "$USER" >&2
      ;;
    stop)
      systemctl --user disable --now ccex-rotate.service 2>/dev/null || true
      systemctl --user disable --now ccex-rotate.timer 2>/dev/null || true
      rm -f "$UNIT/ccex-rotate.timer" "$UNIT/ccex-rotate.service" "$ROOT/.usage/daemon.json"
      systemctl --user daemon-reload
      printf 'ccex: background rotation removed; `ccex rotate --bg` puts it back\n'
      ;;
    status)
      if systemctl --user is-active ccex-rotate.service >/dev/null 2>&1; then
        local k v state= since= mem= cpu=
        while IFS='=' read -r k v; do          # what it costs to leave running, in its own words
          case $k in
            ActiveState) state=$v ;; ExecMainStartTimestamp) since=$v ;;
            MemoryCurrent) mem=$v ;; CPUUsageNSec) cpu=$v ;;
          esac
        done < <(systemctl --user show ccex-rotate.service \
                   -p ActiveState -p ExecMainStartTimestamp -p MemoryCurrent -p CPUUsageNSec)
        printf 'ccex: rotating on data change (%s since %s)\n' "$state" "${since:-?}"
        case "$mem$cpu" in
          *[!0-9]*|'') ;;
          *) printf 'ccex: %s MB resident, %s.%ss of cpu used so far\n' \
               "$((mem / 1048576))" "$((cpu / 1000000000))" "$(((cpu / 100000000) % 10))" ;;
        esac
        sed -n 's/^ExecStart=[^ ]* /ccex: /p' "$UNIT/ccex-rotate.service"
      elif systemctl --user is-active ccex-rotate.timer >/dev/null 2>&1; then
        printf 'ccex: an older wake-up timer is still doing this; `ccex rotate --bg` replaces it\n'
        systemctl --user list-timers ccex-rotate.timer --no-pager | sed -n 2p
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