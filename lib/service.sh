# A resident service, in whichever words this machine has for one: a systemd user unit on
# Linux, a launchd agent on macOS. The choice is made once, here, by defining one set of
# these or the other -- so `ccex rotate --bg` asks four questions and none of the answers
# it gets back mention a platform:
#
#   svc_install <name> <description> <command...>
#   svc_remove  <name>
#   svc_active  <name>        exit status: is it up
#   svc_cmdline <name>        the command it was installed to run
#   svc_stats   <name>        state<TAB>since<TAB>resident bytes<TAB>cpu nanoseconds

if [ "$OS" = Darwin ]; then

  svc_install() { local name=$1 desc=$2; shift 2; py launchd install "$name" "$desc" "$@"; }
  svc_remove()  { py launchd remove  "$1"; }
  svc_active()  { py launchd active  "$1"; }
  svc_cmdline() { py launchd cmdline "$1"; }
  svc_stats()   { py launchd stats   "$1"; }

else

  UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"   # where a user unit goes

  svc_install() {
    local name=$1 desc=$2; shift 2
    unit_install "$name" <<UNITEOF
[Unit]
Description=$desc
StartLimitIntervalSec=0

[Service]
Type=simple
Restart=always
RestartSec=10
Nice=5
$(unit_env)
ExecStart=$*

[Install]
WantedBy=default.target
UNITEOF
  }

  svc_remove()  { unit_remove "$1"; }
  svc_active()  { systemctl --user is-active "$1.service" >/dev/null 2>&1; }
  svc_cmdline() { sed -n 's/^ExecStart=//p' "$UNIT/$1.service" 2>/dev/null; }

  svc_stats() {
    local k v state=inactive since= mem=0 cpu=0
    while IFS='=' read -r k v; do
      case $k in
        ActiveState) state=$v ;; ExecMainStartTimestamp) since=$v ;;
        MemoryCurrent) mem=$v ;; CPUUsageNSec) cpu=$v ;;
      esac
    done < <(systemctl --user show "$1.service" \
               -p ActiveState -p ExecMainStartTimestamp -p MemoryCurrent -p CPUUsageNSec 2>/dev/null)
    case "$mem" in *[!0-9]*|'') mem=0 ;; esac
    case "$cpu" in *[!0-9]*|'') cpu=0 ;; esac
    printf '%s\t%s\t%s\t%s\n' "$state" "$since" "$mem" "$cpu"
  }

  unit_install() {   # unit_install <name>, with the unit body on stdin: write it, then run it
    mkdir -p "$UNIT"
    cat > "$UNIT/$1.service"
    systemctl --user daemon-reload
    systemctl --user reenable "$1.service" >/dev/null 2>&1 || \
      systemctl --user enable "$1.service" >/dev/null 2>&1
    systemctl --user restart "$1.service"
  }

  unit_remove() {
    systemctl --user disable --now "$1.service" 2>/dev/null || true
    rm -f "$UNIT/$1.service"
    systemctl --user daemon-reload
  }

  unit_env() {   # what every ccex unit needs in its environment: `claude` on PATH, because a
    # switch may ask an account what it has left, and the profile root if this ccex was told one.
    # Command substitution eats the trailing newline, so this goes on a line of its own in a unit
    local c=
    c=$(command -v claude 2>/dev/null) && c="$(dirname "$c"):" || c=
    printf 'Environment=PATH=%s%%h/.local/bin:/usr/local/bin:/usr/bin:/bin\n' "$c"
    [ -z "${CC_PROFILE_ROOT:-}" ] || printf 'Environment=CC_PROFILE_ROOT=%s\n' "$CC_PROFILE_ROOT"
  }

fi
