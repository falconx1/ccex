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
t  "rotation leaves it alone"    "held out of the pool"  "$CCEX" rotate --at 1 -n
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
t  "clearing restores the default" "back on the --at default" "$CCEX" pool cap cee --clear
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

echo "help"
for c in ls use rotate pool add run env record; do
  t "ccex $c -h" "ccex $c" "$CCEX" "$c" -h
done
exits "unknown command exits 1"  1                       "$CCEX" bogus

teardown
printf '\n%d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
