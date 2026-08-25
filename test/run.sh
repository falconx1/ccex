#!/usr/bin/env bash
# Exercises ccex against a throwaway HOME with fake accounts. No network, no claude binary,
# nothing outside the temp dir. Run it before pushing.
set -uo pipefail

CCEX=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)/bin/ccex
pass=0 fail=0

setup() {                       # three accounts: a is live, b and c are parked
  HOME=$(mktemp -d)
  export HOME CC_PROFILE_ROOT="$HOME/.claude-profiles"
  python3 - "$HOME" <<'PY'
import json, os, sys, time
h = sys.argv[1]
def w(p, o):
    os.makedirs(os.path.dirname(p), exist_ok=True)
    json.dump(o, open(p, "w"))
def account(dir_, cfg, email, five, seven):
    w(dir_ + "/.credentials.json", {"claudeAiOauth": {
        "accessToken": "t-" + email, "refreshToken": "r-" + email,
        "expiresAt": int(time.time() + 3600) * 1000,
        "refreshTokenExpiresAt": int(time.time() + 30 * 86400) * 1000,
        "userRateLimitTier": "default_claude_max_5x"}})
    w(cfg, {"oauthAccount": {"emailAddress": email, "accountUuid": email,
                             "userRateLimitTier": "default_claude_max_5x"},
            "cachedUsageUtilization": {
                "fetchedAtMs": int(time.time() * 1000), "accountUuid": email,
                "utilization": {
                    "five_hour": {"utilization": five,
                                  "resets_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                               time.gmtime(time.time() + 3600))},
                    "seven_day": {"utilization": seven,
                                  "resets_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                               time.gmtime(time.time() + 86400))}}}})
account(h + "/.claude", h + "/.claude.json", "a@example.com", 90, 40)
account(h + "/.claude-profiles/bee", h + "/.claude-profiles/bee/.claude.json", "b@example.com", 10, 20)
account(h + "/.claude-profiles/cee", h + "/.claude-profiles/cee/.claude.json", "c@example.com", 50, 30)
PY
}

teardown() { [ -n "${HOME:-}" ] && [ "${HOME#/tmp/}" != "$HOME" ] && rm -rf "$HOME"; }

t() {   # t <name> <expected substring> <command...>
  local name=$1 want=$2; shift 2
  local got; got=$("$@" 2>&1)
  if [[ $got == *"$want"* ]]; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$name"
  else
    fail=$((fail + 1)); printf '  FAIL %s\n       wanted: %s\n       got:    %s\n' \
      "$name" "$want" "$(printf '%s' "$got" | head -2)"
  fi
}

absent() {   # absent <name> <substring that must not appear> <command...>
  local name=$1 nope=$2; shift 2
  local got; got=$("$@" 2>&1)
  if [[ $got != *"$nope"* ]]; then
    pass=$((pass + 1)); printf '  ok   %s\n' "$name"
  else
    fail=$((fail + 1)); printf '  FAIL %s\n       should not contain: %s\n' "$name" "$nope"
  fi
}

exits() {   # exits <name> <expected code> <command...>
  local name=$1 want=$2; shift 2
  "$@" >/dev/null 2>&1; local got=$?
  if [ "$got" = "$want" ]; then pass=$((pass + 1)); printf '  ok   %s\n' "$name"
  else fail=$((fail + 1)); printf '  FAIL %s (exit %s, wanted %s)\n' "$name" "$got" "$want"; fi
}

matches() {   # matches <name> <regex> <command...>
  local name=$1 re=$2; shift 2
  local got; got=$("$@" 2>&1)
  if [[ $got =~ $re ]]; then pass=$((pass + 1)); printf '  ok   %s\n' "$name"
  else fail=$((fail + 1)); printf '  FAIL %s\n       no match for: %s\n' "$name" "$re"; fi
}

echo "listing and numbering"
setup
t  "ls shows every account"      "c@example.com"        "$CCEX" ls
t  "live account is marked"      "*"                    "$CCEX" ls
t  "numbers are assigned"        "1"                    "$CCEX" ls
t  "ls <account> reads one"      "b@example.com"        "$CCEX" ls bee
t  "ls never launches"           "90% used"             "$CCEX" ls a@example.com

echo "switching"
t  "use by name"                 "b@example.com -> live" "$CCEX" use bee --no-check
t  "use by number"               "-> live"               "$CCEX" use 3 --no-check
t  "already live is not an error" "already live"         "$CCEX" use 3 --no-check
exits "already live exits 0"     0                       "$CCEX" use 3 --no-check
t  "unknown account is refused"  "no parked account"     "$CCEX" use nope
exits "unknown account exits 1"  1                       "$CCEX" use nope
t  "unknown flag is refused"     "unknown option"        "$CCEX" use bee --dryrun

echo "numbers survive"
n_before=$("$CCEX" ls | awk '/b@example.com/ {print $1}')
"$CCEX" use bee --no-check >/dev/null 2>&1
n_after=$("$CCEX" ls | awk '/b@example.com/ {print $1}')
t  "number unchanged by a switch" "$n_before"            echo "$n_after"

echo "the pool"
mark_of() { "$CCEX" ls | awk -v e="$1" '$0 ~ e {print substr($0, 5, 2)}'; }
t  "hold an account"             "out of the rotation"   "$CCEX" pool out a@example.com
t  "held is marked x"            "x"                     mark_of a@example.com
t  "use on a held account stops" "held out of the pool"  "$CCEX" use a@example.com
exits "and exits 1"              1                       "$CCEX" use a@example.com
t  "rotation leaves it alone"    "out of the pool: a"    "$CCEX" rotate --at 1 -n
t  "release it"                  "back in the rotation"  "$CCEX" pool in a@example.com
t  "mark is cleared"             ""                      mark_of a@example.com

echo "per-account caps"
teardown; setup                 # earlier sections have rotated; start from a is live, 90/40
absent "no caps means no CAP column" "CAP"                 "$CCEX" ls
t  "cap needs a real percentage"  "1 to 100"              "$CCEX" pool cap bee --5h 101
t  "and 0 points at pool out"     "pool out"              "$CCEX" pool cap bee --5h 0
t  "an unknown cap flag is refused" "unknown option"      "$CCEX" pool cap bee --5hr 60
t  "no cap is the --at default"   "no cap of its own"     "$CCEX" pool cap bee
t  "set one window"               "5h 5%"                 "$CCEX" pool cap bee --5h 5
t  "the other still follows --at" "weekly still follows"  "$CCEX" pool cap bee --5h 5
t  "capped is marked c"           "c"                     mark_of b@example.com
n_bee=$("$CCEX" ls | awk '/b@example.com/ {print $1}')
t  "cap by account number"        "5h 60%, weekly 99%"    "$CCEX" pool cap "$n_bee" --5h 60 --weekly 99
t  "and reads back by number"     "is capped at"          "$CCEX" pool cap "$n_bee"
t  "ls grows a CAP column"        "CAP"                   "$CCEX" ls
t  "showing both windows"         "60/99"                 "$CCEX" ls
t  "and a dash for an uncapped one" "5/-"                 bash -c '"$1" pool cap cee --5h 5 >/dev/null; "$1" ls' _ "$CCEX"
"$CCEX" pool cap cee --clear >/dev/null
t  "an unknown number is refused" "no account matches"    "$CCEX" pool cap 9 --5h 60
"$CCEX" pool cap bee --5h 5 >/dev/null
t  "a cap above --at protects it" "under its own 95%"     bash -c '"$1" pool cap a@example.com --5h 95 >/dev/null; "$1" rotate --at 80 -n --no-launch' _ "$CCEX"
t  "a capped account is skipped"  "c@example.com"         bash -c '"$1" pool cap a@example.com --clear >/dev/null; "$1" rotate --at 80 -n --no-launch' _ "$CCEX"
t  "and the reason is named"      "capped by their own"   bash -c '"$1" pool cap cee --5h 45 >/dev/null; "$1" rotate --at 80 -n --no-launch' _ "$CCEX"
exits "nowhere to go exits 1"     1                       "$CCEX" rotate --at 80 -n --no-launch
t  "clearing restores the default" "back on the defaults" "$CCEX" pool cap cee --clear
t  "held wins over a cap in ls"   "x"                     bash -c '"$1" pool out bee >/dev/null; "$1" ls | awk "/b@example.com/ {print substr(\$0, 5, 2)}"' _ "$CCEX"
"$CCEX" pool in bee >/dev/null
t  "rm releases the cap too"      "no b@example.com"      bash -c 'printf "y\n" | "$1" rm bee >/dev/null 2>&1; grep -q b@example.com "$2/.caps.json" && echo "still there" || echo "no b@example.com"' _ "$CCEX" "$CC_PROFILE_ROOT"

echo "rotation"
teardown; setup                 # the cap section removed an account; rotation wants all three
t  "under threshold stays"       "staying put"           "$CCEX" rotate --at 99 -n
t  "over threshold plans a move" "so ->"                 "$CCEX" rotate --at 45 -n --no-launch
t  "dry run writes nothing"      "dry run"               "$CCEX" rotate --at 45 -n --no-launch
t  "mistyped mode is refused"    "unknown option"        "$CCEX" rotate --stopp
t  "bad duration is refused"     "cannot read"           "$CCEX" rotate --watch --every m

echo "parking never clobbers another account"
teardown; setup
python3 - "$HOME" <<'PY'
import json, os, sys
h = sys.argv[1]                       # a slot already named after the live account's local part
d = h + "/.claude-profiles/a"
os.makedirs(d, exist_ok=True)
json.dump({"claudeAiOauth": {"accessToken": "KEEP", "refreshToken": "KEEP-R"}},
          open(d + "/.credentials.json", "w"))
json.dump({"oauthAccount": {"emailAddress": "keep@example.com", "accountUuid": "k"}},
          open(d + "/.claude.json", "w"))
PY
"$CCEX" use bee --no-check >/dev/null 2>&1
t  "the other login survives"    "KEEP-R"  cat "$HOME/.claude-profiles/a/.credentials.json"

echo "statusline install"
teardown; setup
t  "install wires the recorder"  "statusLine ="            "$CCEX" record --install
t  "settings.json has the pipe"  "record | "               cat "$HOME/.claude/settings.json"
installed_cmd() {   # the statusLine command as Claude Code would run it
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["statusLine"]["command"])' \
    "$HOME/.claude/settings.json"
}
target_runs() {     # a statusLine pointing at a file that is not there is the bug this catches
  local bar; bar=${1#*| }
  [ -x "$bar" ] && echo ok || echo "not executable: $bar"
}
renders() { printf '{"rate_limits":{"five_hour":{"used_percentage":62}}}' | eval "$1"; }
cmd=$(installed_cmd)
t  "the bundled bar is the target" "/share/statusline.sh"  echo "$cmd"
t  "and that path really exists"  "ok"                     target_runs "$cmd"
t  "the whole pipeline renders"   "5h:"                    renders "$cmd"
t  "installing twice is a no-op" "already recording"       "$CCEX" record --install
python3 - "$HOME" <<'PY2'
import json, sys                       # a statusline of your own must survive the install
h = sys.argv[1]
json.dump({"statusLine": {"type": "command", "command": "my-own-bar"}},
          open(h + "/.claude/settings.json", "w"))
PY2
t  "your own statusline is kept"  "kept your statusline"    "$CCEX" record --install
t  "and it pipes into it"        "record | my-own-bar"     cat "$HOME/.claude/settings.json"
t  "settings.json is backed up"  "settings.json"           find "$HOME/.claude-profiles/.backups/" -name settings.json
t  "a bad flag does not hang"    "unknown option"          "$CCEX" record --instal

echo "a spent week"
teardown; setup                 # a is live at 90/40, bee at 10/20, cee at 50/30
t  "the week follows 99, not --at" "under 95% 5h / 99% weekly" "$CCEX" rotate --at 95 -n --no-launch
spend_week() {   # put an account's weekly window at the end of itself
  python3 - "$HOME" "$1" "$2" <<'PYEOF'
import json, sys, time
h, cfg, pct = sys.argv[1], sys.argv[2], int(sys.argv[3])
c = json.load(open(cfg))
c["cachedUsageUtilization"]["utilization"]["seven_day"]["utilization"] = pct
json.dump(c, open(cfg, "w"))
PYEOF
}
spend_week "$HOME/.claude.json" 99
t  "a spent week is over the line" "so ->"                 "$CCEX" rotate --at 80 --no-launch
t  "and that account is retired"   "weekly at 99%"         cat "$CC_PROFILE_ROOT/.pool.json"
t  "ls marks it X"                 "X"                     bash -c '"$1" ls | awk "/a@example.com/ {print substr(\$0, 5, 2)}"' _ "$CCEX"
absent "rotation will not go back to it" "a@example.com"    "$CCEX" rotate --at 1 -n --no-launch
t  "pool in is the way back"       "back in the rotation"  "$CCEX" pool in a@example.com
absent "and it clears the mark"    "X"                     bash -c '"$1" ls | awk "/a@example.com/ {print substr(\$0, 5, 2)}"' _ "$CCEX"
pool_file() { cat "$CC_PROFILE_ROOT/.pool.json" 2>/dev/null || echo "{}"; }
teardown; setup
spend_week "$HOME/.claude.json" 99
absent "a dry run retires nothing" "a@example.com"          bash -c '"$1" rotate --at 80 -n --no-launch >/dev/null; cat "$2/.pool.json" 2>/dev/null' _ "$CCEX" "$CC_PROFILE_ROOT"
teardown; setup                 # a's week is untouched here: only its 5-hour window is spent
absent "a spent 5h window does not retire" "a@example.com"  bash -c '"$1" rotate --at 45 --no-launch >/dev/null 2>&1; cat "$2/.pool.json" 2>/dev/null' _ "$CCEX" "$CC_PROFILE_ROOT"

echo "a late render after a switch"
teardown; setup                 # a is live at 90/40; bee, once live, is at 10/20
"$CCEX" use bee --no-check >/dev/null 2>&1
snap="$CC_PROFILE_ROOT/.usage/b_example_com.json"
render() {   # a statusline payload, as Claude Code hands it to `ccex record`
  rm -f "$CC_PROFILE_ROOT/.usage/.stamp-default"      # the 15s throttle is not under test
  printf '{"rate_limits":{"five_hour":{"used_percentage":%s},"seven_day":{"used_percentage":%s}}}' \
    "$1" "$2" | "$CCEX" record >/dev/null
}
render 90 40
absent "the old account's numbers are dropped" "90"        bash -c 'cat "$1" 2>/dev/null || echo none' _ "$snap"
render 12 22
t  "the new account's own numbers land" "12"               cat "$snap"
t  "the filter stays transparent"  "rate_limits"              bash -c 'printf "{\"rate_limits\":{}}" | "$1" record' _ "$CCEX"

echo "the daemon"
teardown; setup                 # a is live at 90/40, bee at 10/20, cee at 50/30
live_email() { "$CCEX" ls | awk '/\*/ {print $4}'; }
before=$(live_email)
timeout 6 "$CCEX" rotate --serve --at 45 --every 1s >"$HOME/serve.out" 2>&1
after=$(live_email)
t  "serve says what it is doing"  "on data change"        cat "$HOME/serve.out"
t  "and switches without a timer" "b@example.com"          echo "$after"
absent "off the account it started on" "$before"           echo "$after"
t  "the switch is logged"         "so ->"                  cat "$CC_PROFILE_ROOT/.usage/rotate.log"
teardown; setup
timeout 4 "$CCEX" rotate --serve --at 99 --every 1s >"$HOME/quiet.out" 2>&1
t  "under threshold it stays quiet" "1"                    bash -c 'wc -l < "$1/quiet.out"' _ "$HOME"
t  "and rotates nothing"          "a@example.com"          bash -c '"$1" ls | awk "/\*/ {print \$4}"' _ "$CCEX"
t  "refresh off never probes"     "0"                      bash -c 'grep -c max-age "$1/quiet.out" || true' _ "$HOME"
t  "it notes when it last looked" "under"                  cat "$CC_PROFILE_ROOT/.usage/.monitor-last"
reloads() {   # a service left running for weeks must not keep running the code it started with
  "$CCEX" rotate --serve --at 99 --every 1s >"$HOME/reload.out" 2>&1 &
  local pid=$!
  sleep 2; touch "$(dirname "$CCEX")/../lib/py/watch.py"; sleep 3
  kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
  cat "$HOME/reload.out"
}
t  "and restarts itself on an update" "restarting into it" reloads

echo "the live view"
teardown; setup                 # a is live at 90/40, bee at 10/20, cee at 50/30
frame() { "$CCEX" ls -w --once --at "$1"; }
t  "one frame lists the accounts" "b@example.com"        frame 80
t  "and draws the meters"         "█"                    frame 80
matches "the countdown ticks in seconds" '[0-9]+m [0-9][0-9]s'  frame 80
matches "and the cap is drawn into the bar" '▕?[█░]*╵'    frame 80
t  "it folds in the monitor"      "next switch"          frame 80
t  "over threshold: switch now"   "now"                  frame 80
t  "and names where it would go"  "b@example.com"        frame 80
t  "under threshold: not yet"     "not yet"              frame 99
t  "it says what it is watching"  "rotation"             frame 99
absent "piped output has no escapes" "["$(printf '\033')"" frame 80
exits "--once exits 0"            0                      "$CCEX" ls -w --once --at 80
prompt_line() {   # <digits> -> the line the view shows once they are typed
  CCEX_BASE="$HOME/.claude" CCEX_ROOT="$CC_PROFILE_ROOT" \
  PYTHONPATH="$(dirname "$CCEX")/../lib/py" python3 - "$1" <<'PYEOF'
import sys
import watch
v = watch.View(at=80)
v.sample()
v.typed = sys.argv[1]
print("\n".join(v.frame(120, 24, colour=False)))
PYEOF
}
number_of() { python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["b@example.com"])' \
                "$CC_PROFILE_ROOT/.ids.json"; }
renumber() { python3 - "$CC_PROFILE_ROOT/.ids.json" <<'PYEOF'
import json, sys                       # give one account a two-digit number
p = sys.argv[1]
m = json.load(open(p))
m["b@example.com"] = 12
json.dump(m, open(p, "w"))
PYEOF
}
t  "the keys line offers switching" "switch to that account" frame 80
t  "a number asks before moving"    "switch to"            prompt_line "$(number_of)"
t  "and names the account"          "b@example.com"        prompt_line "$(number_of)"
t  "an unknown number says so"      "no account has that number" prompt_line 47
renumber
t  "a two-digit number is reachable" "b@example.com"       prompt_line 12
t  "a bad watch flag is refused"  "not a --watch option" "$CCEX" ls -w --bogus
t  "and a bad duration too"       "cannot read"          "$CCEX" ls -w --every m
t  "plain ls is untouched by it"  "CHECKED"              "$CCEX" ls
"$CCEX" pool out a@example.com >/dev/null
t  "a held live account is left"  "held out of the pool"   frame 80
"$CCEX" pool in a@example.com >/dev/null
"$CCEX" pool cap a@example.com --5h 95 --weekly 95 >/dev/null
t  "its own cap is predicted against" "not yet"            frame 80
"$CCEX" pool cap a@example.com --clear >/dev/null

burn_says() {   # the estimate is arithmetic, so it is testable without a terminal
  CCEX_BASE="$HOME/.claude" CCEX_ROOT="$CC_PROFILE_ROOT" \
  PYTHONPATH="$(dirname "$CCEX")/../lib/py" python3 - "$1" <<'PYEOF'
import json, os, sys, time
import burn
from ccexlib import USAGE_DIR
os.makedirs(USAGE_DIR, exist_ok=True)
now = int(time.time())
# ten percent of the 5-hour window in ten minutes: 60%/h, so 20% -> 80% is another hour
json.dump({"email": "a@example.com",
           "samples": [[now - 600, 20, 5], [now - 300, 25, 5], [now, 30, 5]]},
          open(burn.hist_path("a@example.com"), "w"))
rate = burn.rate("a@example.com", "five_hour")
if sys.argv[1] == "rate":
    print("%.0f%%/h" % rate)
elif sys.argv[1] == "eta":
    secs, resets = burn.eta(30, 80, rate)
    print("%dm" % (secs / 60))
elif sys.argv[1] == "resets":
    secs, resets = burn.eta(30, 80, rate, now + 600)   # window refills long before the cap
    print("resets first" if resets and secs is None else "predicted %s" % secs)
elif sys.argv[1] == "backwards":
    json.dump({"email": "a@example.com",                # a reset inside the window
               "samples": [[now - 900, 90, 5], [now - 600, 2, 5], [now, 8, 5]]},
              open(burn.hist_path("a@example.com"), "w"))
    print("%.0f%%/h" % burn.rate("a@example.com", "five_hour"))
PYEOF
}
t  "a burn rate from two readings" "60%/h"               burn_says rate
t  "an eta to the cap"             "50m"                 burn_says eta
t  "a window that resets first"    "resets first"        burn_says resets
t  "a reset does not read as negative" "36%/h"           burn_says backwards

echo "help"
for c in ls use rotate pool add run env record; do
  t "ccex $c -h" "ccex $c" "$CCEX" "$c" -h
done
exits "unknown command exits 1"  1                       "$CCEX" bogus

teardown
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
