# The panel indicator: the `ccex ls` table folded into the top bar, with a switch behind
# every row. The drawing is tray.py's; this is where it is checked for and kept running.

tray_ready() {   # the typelib the indicator is drawn with -- the package is one apt away
  python3 - <<'PY' 2>/dev/null
import gi
for ns in ("AyatanaAppIndicator3", "AppIndicator3"):
    try:
        gi.require_version(ns, "0.1")
        raise SystemExit(0)
    except ValueError:
        pass
raise SystemExit(1)
PY
}

tray_needs() {
  tray_ready || die "the tray needs the appindicator typelib for python:
       sudo apt install gir1.2-ayatanaappindicator3-0.1"
  # GNOME draws no tray of its own, so an indicator with nothing to render it is invisible
  # rather than broken -- worth saying once, at install time, not on every start.
  case "${XDG_CURRENT_DESKTOP:-}" in
    *GNOME*)
      command -v gnome-extensions >/dev/null 2>&1 || return 0
      gnome-extensions list --enabled 2>/dev/null | grep -qi appindicator ||
        printf 'ccex: GNOME shows no tray icons on its own; enable an AppIndicator extension (Ubuntu ships one) or nothing will appear\n' >&2 ;;
  esac
  return 0
}

tray() {
  local sub=${1:-run}
  case "$sub" in
    run)
      exec python3 "$CCEX_PY/tray.py" ;;     # which says the same thing about a missing typelib
    install)
      tray_needs
      # Bound to the desktop session rather than to login: an indicator with no session to
      # sit in has nowhere to draw itself, and would restart forever trying.
      unit_install ccex-tray <<UNITEOF
[Unit]
Description=ccex: the live Claude account in the top bar
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
Restart=on-failure
RestartSec=10
Nice=5
$(unit_env)
ExecStart=$CCEX_BIN tray

[Install]
WantedBy=graphical-session.target
UNITEOF
      printf 'ccex: in the top bar now, and at every login (ccex tray --stop removes it)\n' ;;
    stop)
      unit_remove ccex-tray
      printf 'ccex: out of the top bar; `ccex tray --install` puts it back\n' ;;
    status)
      if systemctl --user is-active ccex-tray.service >/dev/null 2>&1; then
        printf 'ccex: in the top bar (%s)\n' \
          "$(systemctl --user show ccex-tray.service -p ExecMainStartTimestamp --value)"
      else
        printf 'ccex: not in the top bar (ccex tray --install)\n'
      fi
      tray_ready || printf 'ccex: and the appindicator typelib is missing: sudo apt install gir1.2-ayatanaappindicator3-0.1\n' >&2
      return 0 ;;
    *) die "usage: ccex tray [--install|--stop|--status]" ;;
  esac
}
