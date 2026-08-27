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
                                               time.gmtime(FIVE_AT[email]))},
                    "seven_day": {"utilization": seven,
                                  "resets_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00",
                                               time.gmtime(WEEK_AT[email]))}}}})
# An account's weekly window comes back at its own point in the week, and no two here share
# one: that point is how ccex tells whose numbers a statusline is carrying. Their 5-hour
# windows differ too -- that one does not identify an account for long, but it does not
# drift while it is open, so it says which account a lagging render is still reporting.
EMAILS = ("a@example.com", "b@example.com", "c@example.com")
WEEK_AT = {e: int(time.time()) + 86400 + n * 3600 for n, e in enumerate(EMAILS)}
FIVE_AT = {e: int(time.time()) + 3600 + n * 600 for n, e in enumerate(EMAILS)}
account(h + "/.claude", h + "/.claude.json", "a@example.com", 90, 40)
account(h + "/.claude-profiles/bee", h + "/.claude-profiles/bee/.claude.json", "b@example.com", 10, 20)
account(h + "/.claude-profiles/cee", h + "/.claude-profiles/cee/.claude.json", "c@example.com", 50, 30)
json.dump({"week": WEEK_AT, "five": FIVE_AT}, open(h + "/resets.json", "w"))
PY
}

teardown() { [ -n "${HOME:-}" ] && [ "${HOME#/tmp/}" != "$HOME" ] && rm -rf "$HOME"; }

live_email() { "$CCEX" ls | awk '/\*/ {print $4}'; }

render_from() {   # render_from <transcript-path> <5h> <weekly>: a payload that says which
  # session it came from, so provenance rather than the numbers can decide. No reset times:
  # with no boundary to compare, only the transcript can tell whose numbers these are.
  rm -f "$CC_PROFILE_ROOT/.usage/.stamp-default"
  printf '{"transcript_path":"%s","rate_limits":{"five_hour":{"used_percentage":%s},"seven_day":{"used_percentage":%s}}}' \
    "$1" "$2" "$3" | "$CCEX" record >/dev/null
}

transcript() {   # transcript <path> <seconds-ago>: a session whose last reply arrived then
  python3 -c 'import datetime, json, sys, time
t = datetime.datetime.fromtimestamp(time.time() - float(sys.argv[2]), datetime.timezone.utc)
json.dump({"type": "assistant", "requestId": "req_1", "timestamp": t.isoformat()},
          open(sys.argv[1], "w"))' "$1" "$2"
}

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

echo "adding an account"
teardown; setup
stub_claude() {   # a `claude auth login` that succeeds, as whoever CCEX_TEST_EMAIL says
  mkdir -p "$HOME/bin"
  cat > "$HOME/bin/claude" <<'EOF'
#!/usr/bin/env bash
python3 - "$CLAUDE_CONFIG_DIR" "$CCEX_TEST_EMAIL" <<'PYEOF'
import json, os, sys, time
d, email = sys.argv[1], sys.argv[2]
json.dump({"claudeAiOauth": {"accessToken": "t-" + email, "refreshToken": "r-" + email,
           "expiresAt": int(time.time() + 3600) * 1000,
           "refreshTokenExpiresAt": int(time.time() + 30 * 86400) * 1000}},
          open(d + "/.credentials.json", "w"))
p = d + "/.claude.json"
cfg = json.load(open(p)) if os.path.exists(p) else {}
cfg["oauthAccount"] = {"emailAddress": email, "accountUuid": email,
                       "userRateLimitTier": "default_claude_max_5x"}
json.dump(cfg, open(p, "w"))
PYEOF
EOF
  chmod +x "$HOME/bin/claude"
}
adds() { PATH="$HOME/bin:$PATH" CCEX_TEST_EMAIL="$1" "$CCEX" add ${2+"$2"}; }
stub_claude
t  "add with no name takes the account's" "parked as new" adds new@example.com
t  "and it is a real account now"         "new@example.com"        "$CCEX" ls
t  "the scratch slot is gone"             "no .adding"             bash -c '[ -e "$1/.adding" ] && echo "still there" || echo "no .adding"' _ "$CC_PROFILE_ROOT"
t  "the same account again re-authenticates" "re-authenticated"    adds new@example.com
absent "and does not make a second slot"  "new-2"                  "$CCEX" ls
t  "the live account is recognised"       "already running"        adds a@example.com
t  "a name still works"                   "logging in to profile"  adds other@example.com work
t  "and is used as given"                 "work"                   "$CCEX" ls
t  "a login that fails adds nothing"      "nothing was added"      bash -c 'PATH=/nonexistent:/usr/bin:/bin "$1" add' _ "$CCEX"

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

echo "verifying before the switch"
# probe() launches the real TUI; this stands in for it, writing what /usage would have
# refreshed and exiting. Nothing else in the suite needs a `claude` on PATH.
fake_claude() {
  mkdir -p "$HOME/fakebin"
  cat > "$HOME/fakebin/claude" <<'FAKE'
#!/usr/bin/env bash
printf 'x' >> "$HOME/fake-calls"
python3 - <<'PY'
import json, os, time
d = os.environ.get("CLAUDE_CONFIG_DIR")
cfg = os.path.join(d, ".claude.json") if d else os.path.expanduser("~/.claude.json")
c = json.load(open(cfg))
email = (c.get("oauthAccount") or {}).get("emailAddress")
say = json.load(open(os.path.expanduser("~/fake-usage.json"))).get(email)
if say:
    def when(secs):
        return time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + secs))
    u = c.setdefault("cachedUsageUtilization", {
        "accountUuid": (c.get("oauthAccount") or {}).get("accountUuid"),
        "utilization": {"five_hour": {"resets_at": when(3600)},
                        "seven_day": {"resets_at": when(2 * 86400)}}})
    u["fetchedAtMs"] = int(time.time() * 1000)
    u["utilization"]["five_hour"]["utilization"] = say[0]
    u["utilization"]["seven_day"]["utilization"] = say[1]
    json.dump(c, open(cfg, "w"))
PY
FAKE
  chmod +x "$HOME/fakebin/claude"
  PATH="$HOME/fakebin:$PATH"
  # a profile with no trusted folder cannot be launched in, so the live config gets one
  # for `borrow_trust` to copy over -- which is the path a never-live profile takes.
  python3 -c 'import json,sys
c = json.load(open(sys.argv[1]))
c["projects"] = {sys.argv[2]: {"hasTrustDialogAccepted": True}}
json.dump(c, open(sys.argv[1], "w"))' "$HOME/.claude.json" "$HOME"
  printf '%s' "$1" > "$HOME/fake-usage.json"
  : > "$HOME/fake-calls"
}

calls() { wc -c < "$HOME/fake-calls" | tr -d ' '; }   # how many sessions the fake ran

age_numbers() {   # nothing reports for a parked account, so its numbers are hours old
  python3 -c 'import glob, json, sys, time
for cfg in glob.glob(sys.argv[1] + "/*/.claude.json"):
    c = json.load(open(cfg))
    if "cachedUsageUtilization" not in c:
        continue                     # nothing measured here; there is no age to set
    c["cachedUsageUtilization"]["fetchedAtMs"] = int((time.time() - 3600) * 1000)
    json.dump(c, open(cfg, "w"))' "$CC_PROFILE_ROOT"
}

teardown; setup                 # a is live at 90/40; bee reads 10/20 on file, 95 for real
fake_claude '{"b@example.com": [95, 20], "c@example.com": [5, 30]}'
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
t  "a candidate with no room is passed over" "> c@example.com" echo "$out"
t  "and that account really is live now"     "c@example.com"   live_email
t  "and the line says what it really read"   "95% 5h"          echo "$out"
t  "it seeded what it needed to launch"      "onboarding and folder trust" echo "$out"

teardown; setup                 # this time bee really does have room
fake_claude '{"b@example.com": [12, 20]}'
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
t  "a verified candidate is switched to"     "b@example.com"   echo "$out"
t  "and its checked numbers are reported"    "12% 5h"          echo "$out"

teardown; setup
fake_claude '{"b@example.com": [95, 20]}'
age_numbers
out=$("$CCEX" rotate --at 80 --no-verify 2>&1)
t  "--no-verify asks nothing"                "b@example.com"   echo "$out"
absent "and reports no check"                "checked just now" echo "$out"

teardown; setup                 # bee will not answer, cee will: the next candidate is used
fake_claude '{"c@example.com": [50, 30]}'
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
t  "an account that will not answer is passed over" "trying the next account" echo "$out"
t  "and the next one is asked instead"              "c@example.com"  live_email
absent "so the silent one is not used"              "b@example.com"  live_email

teardown; setup                 # no `claude` to launch at all: nothing can be asked
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
t  "with nothing answering it says so"        "none of them could be asked" echo "$out"
t  "and falls back to the numbers on file"    "b@example.com"        live_email
rlog() { cat "$CC_PROFILE_ROOT/.usage/rotate.log" 2>&1; }
step_trail() { cat "$CC_PROFILE_ROOT/.usage/.step" 2>/dev/null || echo nothing; }
t  "the log records the probe starting"       "asking bee"           rlog
t  "and how it went"                          "did not answer"       rlog

teardown; setup
age_numbers
out=$("$CCEX" rotate --at 80 -n 2>&1)
absent "a dry run asks nothing"              "could not be asked" echo "$out"

teardown; setup                 # the trail a switch writes is its own, not the last one's
age_numbers
printf 'asking zzz\n' > "$CC_PROFILE_ROOT/.usage/.step"
"$CCEX" rotate --at 80 >/dev/null 2>&1
absent "a new switch clears the old trail" "asking zzz"        step_trail
t      "and writes its own instead"       "asking"             step_trail

teardown; setup                 # a tick that stays put has no story to tell
age_numbers
out=$("$CCEX" rotate --at 99 2>&1)
t      "staying put still says so"           "staying put"        echo "$out"
absent "and writes no trail"                 "out of room"        step_trail
absent "nor a line to the log"               "out of room"        rlog

# An account nothing has measured is invisible to ranking, so it can never be the candidate
# that gets checked -- unless being unmeasured is itself allowed to reach the check.
spend_live() {   # spend_live five|seven <pct>: move the live account's own window
  python3 -c 'import json, sys
c = json.load(open(sys.argv[1]))
w = {"five": "five_hour", "seven": "seven_day"}[sys.argv[2]]
c["cachedUsageUtilization"]["utilization"][w]["utilization"] = int(sys.argv[3])
json.dump(c, open(sys.argv[1], "w"))' "$HOME/.claude.json" "$1" "$2"
}

spend_five() {   # put an account's 5-hour window near the end of itself
  python3 -c 'import json, sys
c = json.load(open(sys.argv[1]))
c["cachedUsageUtilization"]["utilization"]["five_hour"]["utilization"] = int(sys.argv[2])
json.dump(c, open(sys.argv[1], "w"))' "$CC_PROFILE_ROOT/$1/.claude.json" "$2"
}

unmeasure() {   # wipe every reading for one account, as a freshly added one has none
  python3 -c 'import json, sys
c = json.load(open(sys.argv[1]))
c.pop("cachedUsageUtilization", None)
json.dump(c, open(sys.argv[1], "w"))' "$CC_PROFILE_ROOT/$1/.claude.json"
  rm -f "$CC_PROFILE_ROOT/.usage/$2"
}

teardown; setup                 # bee has no numbers at all; cee is spent, so bee is all there is
unmeasure bee b_example_com.json
spend_five cee 95
t  "an unmeasured account is not reached blind" "every other account is too" \
   "$CCEX" rotate --at 80 --no-verify
fake_claude '{"b@example.com": [7, 11]}'
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
t  "but the check can reach it"              "b@example.com"   live_email
t  "and it lands with real numbers"          "7% 5h"           echo "$out"
t  "said to be a first measurement"          "first time"      echo "$out"

teardown; setup                 # bee is the only candidate, and nothing can read it
unmeasure bee b_example_com.json
spend_five cee 95
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
absent "an unmeasured account it cannot read is not used" "b@example.com" live_email
t  "and it says why"                         "never been measured" echo "$out"

teardown; setup                 # cee has room and is measured, so bee is never asked
unmeasure bee b_example_com.json
fake_claude '{"c@example.com": [50, 30]}'
age_numbers
out=$("$CCEX" rotate --at 80 2>&1)
t  "a measured account wins over an unmeasured one" "c@example.com"  live_email
absent "and the unmeasured one is not asked"        "b@example.com"  echo "$out"

teardown; setup                 # a tick that asks and stays put still leaves a trace
unmeasure bee b_example_com.json
spend_five cee 95
age_numbers
"$CCEX" rotate --at 93 >/dev/null 2>&1
t  "a read-ahead is logged even with no switch" "reading bee ahead" \
   cat "$CC_PROFILE_ROOT/.usage/rotate.log"

teardown; setup                 # a is live at 90%; at --at 93 it is inside the 5-point band
unmeasure bee b_example_com.json
spend_five cee 95
fake_claude '{"b@example.com": [7, 11]}'
age_numbers
out=$("$CCEX" rotate --at 93 2>&1)
t  "near the cap it does not switch"        "is at 90%"       echo "$out"
t  "but it reads the next account first"    "read ahead"      echo "$out"
t  "and files real numbers for it"          "7% 5h"           echo "$out"
out=$("$CCEX" rotate --at 93 2>&1)
absent "reading ahead does not repeat"      "read ahead"      echo "$out"

teardown; setup                 # read ahead at 93, then cross the cap moments later
unmeasure bee b_example_com.json
spend_five cee 95
fake_claude '{"b@example.com": [7, 11]}'
age_numbers
"$CCEX" rotate --at 93 >/dev/null 2>&1              # inside the band, so it reads ahead
t  "reading ahead took one session"            "1"              calls
out=$("$CCEX" rotate --at 80 2>&1)                  # now over it: the switch itself
t  "the switch goes through on what it read"   "b@example.com"  live_email
t  "and asks nothing more, being seconds old"  "1"              calls

teardown; setup                 # no reset time for the live window: nothing to bound it by
unmeasure bee b_example_com.json
spend_five cee 95
fake_claude '{"b@example.com": [7, 11]}'
age_numbers
python3 -c 'import json, sys
c = json.load(open(sys.argv[1]))
c["cachedUsageUtilization"]["utilization"]["five_hour"].pop("resets_at", None)
json.dump(c, open(sys.argv[1], "w"))' "$HOME/.claude.json"
out=$("$CCEX" rotate --at 93 2>&1)
absent "with no window to bound it, it reads nothing ahead" "read ahead" echo "$out"
t  "and still says where it stands"            "a@example.com"  echo "$out"

teardown; setup                 # 5h is nowhere near, but the week is: that is what will trip
unmeasure bee b_example_com.json
spend_five cee 95
spend_live five 28
spend_live seven 96
fake_claude '{"b@example.com": [7, 11]}'
age_numbers
out=$("$CCEX" rotate --at 90 2>&1)
t  "a near weekly window still stays put"         "staying put" echo "$out"
t  "but the week reads ahead as well"             "read ahead"  echo "$out"

teardown; setup                 # nothing can read bee, and asking again would be a timer
unmeasure bee b_example_com.json
spend_five cee 95
age_numbers
out=$("$CCEX" rotate --at 93 2>&1)
t  "a read-ahead that fails says so"        "could not be read ahead" echo "$out"
out=$("$CCEX" rotate --at 93 2>&1)
absent "and is not attempted again"         "could not be read ahead" echo "$out"

teardown; setup                 # 90% against a 99% cap is four points too far away
unmeasure bee b_example_com.json
spend_five cee 95
fake_claude '{"b@example.com": [7, 11]}'
age_numbers
absent "far from the cap it reads nothing"  "read ahead" \
   "$CCEX" rotate --at 99
absent "and --no-verify never reads ahead"  "read ahead" \
   "$CCEX" rotate --at 93 --no-verify

teardown; setup                 # the view predicts; the tick acts. They must say the same thing
unmeasure bee b_example_com.json
spend_five cee 95
t  "the view offers the unmeasured account too"  "nothing has measured yet" \
   "$CCEX" ls -w --once --at 80
t  "and without the check it does not"           "every other account is too" \
   "$CCEX" ls -w --once --at 80 --no-verify

echo "taken from the open pull requests"
teardown; setup                 # CLAUDE_CONFIG_DIR setups keep the live config inside the dir
python3 -c 'import json, os, sys
os.makedirs(sys.argv[1], exist_ok=True)
json.dump({"oauthAccount": {"emailAddress": "inner@example.com"}},
          open(os.path.join(sys.argv[1], ".claude.json"), "w"))' "$HOME/.claude"
t  "the inner config wins when it exists" "inner@example.com" \
   env CCEX_BASE="$HOME/.claude" CCEX_ROOT="$CC_PROFILE_ROOT" \
   PYTHONPATH="$(dirname "$CCEX")/../lib/py" python3 -c \
   'import json, os
from ccexlib import BASE, cfg_for
print(json.load(open(cfg_for(BASE)))["oauthAccount"]["emailAddress"])'

teardown; setup                 # parking must leave the slot able to answer a probe later
python3 -c 'import json, sys
c = json.load(open(sys.argv[1]))
c["projects"] = {sys.argv[2]: {"hasTrustDialogAccepted": True}}
c["theme"] = "dark"
json.dump(c, open(sys.argv[1], "w"))' "$HOME/.claude.json" "$HOME"
"$CCEX" use bee --no-check >/dev/null 2>&1
parked() { python3 -c 'import json,sys
c = json.load(open(sys.argv[1]))
print(sorted((c.get("projects") or {}).keys()), c.get("theme"))' \
  "$CC_PROFILE_ROOT/a/.claude.json"; }
t  "the parked slot keeps the trust it will need" "$HOME"  parked
t  "and the rest of the config with it"           "dark"   parked

teardown; setup                 # a session that has not heard from the API since the switch
"$CCEX" use bee --no-check >/dev/null 2>&1        # now live: b@example.com
transcript "$HOME/old.jsonl" 600                  # its last reply was ten minutes ago
render_from "$HOME/old.jsonl" 77 66              # numbers no boundary can place
filed_b() {   # what b has on file, or "nothing" when the render was refused outright
  python3 -c 'import json, sys
try:
    u = json.load(open(sys.argv[1])).get("utilization") or {}
except OSError:
    print("nothing"); raise SystemExit
print((u.get("five_hour") or {}).get("utilization"))' \
    "$CC_PROFILE_ROOT/.usage/b_example_com.json"
}
t  "a render older than the switch is refused"    "nothing"  filed_b
transcript "$HOME/new.jsonl" -5                   # a session that has replied since
render_from "$HOME/new.jsonl" 44 33
t  "and one newer than it is kept"                "44"       filed_b

echo "a switch you typed"
teardown; setup                 # cee is spent; naming it anyway must say so before it moves
spend_five cee 95
fake_claude '{"c@example.com": [95, 30], "b@example.com": [10, 20]}'
age_numbers
out=$("$CCEX" use cee 2>&1)
t  "it asks the account before moving"      "asking cee"      rlog
t  "and the one it moves on to as well"     "asking bee"      rlog
t  "and says it has no room"                "5h over 90%"     echo "$out"
t  "so it hands over to one that has"       "b@example.com"   echo "$out"
t  "and that is where it lands"             "b@example.com"   live_email
t  "the trail says why it moved on"         "no room"         step_trail

teardown; setup                 # the account it picks for you has to answer for itself
spend_five cee 95
fake_claude '{"c@example.com": [95, 30]}'          # bee will not answer
age_numbers
out=$("$CCEX" use cee 2>&1)
t  "an unverified fall-through is not used"  "nothing moved"  echo "$out"
t  "so nothing moved at all"                 "a@example.com"  live_email

teardown; setup                 # a slot left over from an earlier park holds the live login
cp -r "$CC_PROFILE_ROOT/bee" "$CC_PROFILE_ROOT/leftover"
python3 -c 'import json,sys; p=sys.argv[1]; d=json.load(open(p)); d.setdefault("claudeAiOauth",{})["account"]={"email_address":"a@example.com"}; json.dump(d,open(p,"w"))' \
  "$CC_PROFILE_ROOT/leftover/.credentials.json"
spend_five cee 95
fake_claude '{"c@example.com": [95, 30], "b@example.com": [10, 20]}'
age_numbers
out=$("$CCEX" use cee 2>&1)
absent "the account already live is not offered" "handing over to a@example.com" echo "$out"
t      "it picks a real other account instead"   "b@example.com"  live_email

teardown; setup                 # --anyway means you meant it: the spent account goes live
spend_five cee 95
fake_claude '{"c@example.com": [95, 30]}'
age_numbers
out=$("$CCEX" use cee --anyway 2>&1)
t  "--anyway takes the spent account"       "c@example.com"   live_email
t  "and still says what it read"            "5h over 90%"     echo "$out"
t  "asking only the account you named"      "1"               calls

teardown; setup                 # naming the account already live must not start a session
fake_claude '{"a@example.com": [90, 40]}'
"$CCEX" use a >/dev/null 2>&1 || true
t  "the live account is not asked behind you" "0"             calls

teardown; setup                 # under the default 90 but over its own 60: still no room
spend_five cee 70
"$CCEX" pool cap cee --5h 60 >/dev/null 2>&1
fake_claude '{"c@example.com": [70, 30]}'
age_numbers
out=$("$CCEX" use cee 2>&1)
t  "an own cap counts, not just the default" "over its own 60%"  echo "$out"
absent "and the default is not quoted"       "over 90%"          echo "$out"

teardown; setup                 # a switch you pressed a key for writes the same trail
fake_claude '{"b@example.com": [10, 20]}'
age_numbers
"$CCEX" use bee >/dev/null 2>&1
t  "a typed switch leaves a trail"          "by hand"            step_trail
t  "saying it asked the account"            "asking bee"         step_trail
t  "and what came back"                     "bee answered"       step_trail

teardown; setup                 # --no-check asks nothing, so it has nothing to say
fake_claude '{"b@example.com": [10, 20]}'
age_numbers
"$CCEX" use bee --no-check >/dev/null 2>&1
absent "asking nothing writes no trail"     "by hand"            step_trail

teardown; setup                 # bee has room, so there is nothing to warn about
fake_claude '{"b@example.com": [10, 20]}'
age_numbers
out=$("$CCEX" use bee 2>&1)
absent "a switch with room warns about nothing" "rotation will move off" echo "$out"
t  "and it lands"                            "b@example.com"  live_email
teardown; setup                 # --no-report is what the live view switches with: ask, stay quiet
fake_claude '{"b@example.com": [10, 20]}'
age_numbers
out=$("$CCEX" use bee --no-report 2>&1)
t  "--no-report still asks the account"      "1"              calls
absent "but prints no table"                 "limits for"     echo "$out"
t  "and switches"                            "b@example.com"  live_email

teardown; setup                 # --no-check means neither the asking nor the report
fake_claude '{"b@example.com": [10, 20]}'
age_numbers
out=$("$CCEX" use bee --no-check 2>&1)
t  "--no-check asks nothing at all"          "0"              calls
absent "and reports nothing either"          "limits for"     echo "$out"
t  "but it still switches"                   "b@example.com"  live_email

echo "a late render after a switch"
teardown; setup                 # a is live at 90/40; bee, once live, is at 10/20
"$CCEX" use bee --no-check >/dev/null 2>&1
snap="$CC_PROFILE_ROOT/.usage/b_example_com.json"
reset_at() {   # reset_at week|five <account>: when that account's window comes back
  python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]][sys.argv[3]])' \
    "$HOME/resets.json" "$1" "$2@example.com"
}
week_at() { reset_at week "$1"; }
render() {   # a statusline payload, as Claude Code hands it to `ccex record`
  rm -f "$CC_PROFILE_ROOT/.usage/.stamp-default"      # the 15s throttle is not under test
  local week=${3:-}
  [ -z "$week" ] || week=",\"resets_at\":$(week_at "$week")"
  printf '{"rate_limits":{"five_hour":{"used_percentage":%s},"seven_day":{"used_percentage":%s%s}}}' \
    "$1" "$2" "$week" | "$CCEX" record >/dev/null
}
render 90 40
absent "the old account's numbers are dropped" "90"        bash -c 'cat "$1" 2>/dev/null || echo none' _ "$snap"
render 12 22
t  "the new account's own numbers land" "12"               cat "$snap"
t  "the filter stays transparent"  "rate_limits"              bash -c 'printf "{\"rate_limits\":{}}" | "$1" record' _ "$CCEX"

# The numbers a session carries go on moving after the switch, so they stop matching what we
# wrote down as we left. The week they reset in is still the old account's.
teardown; setup
"$CCEX" use bee --no-check >/dev/null 2>&1
snap="$CC_PROFILE_ROOT/.usage/b_example_com.json"
render 93 41 a
absent "numbers that moved on are still the old account's" "93" \
  bash -c 'cat "$1" 2>/dev/null || echo none' _ "$snap"
render 12 22 b
t  "and the new account's own still land" "12"             cat "$snap"

# A 5-hour window does not move while it is open, so the reset time a lagging session
# carries is the account it left with, long after the percentage has climbed away from it.
teardown; setup
"$CCEX" use bee --no-check >/dev/null 2>&1
snap="$CC_PROFILE_ROOT/.usage/b_example_com.json"
render_five() {   # one window only, with the reset time of whichever account is named
  rm -f "$CC_PROFILE_ROOT/.usage/.stamp-default"
  printf '{"rate_limits":{"five_hour":{"used_percentage":%s,"resets_at":%s}}}' \
    "$1" "$(reset_at five "$2")" | "$CCEX" record >/dev/null
}
render_five 97 a
absent "a reset time outlives the percentage" "97"         bash -c 'cat "$1" 2>/dev/null || echo none' _ "$snap"
render_five 97 b
t  "the same number under our own reset lands" "97"        cat "$snap"

# Two switches inside the half hour: the account we left first has to stay recognisable.
teardown; setup
"$CCEX" use bee --no-check >/dev/null 2>&1
"$CCEX" use cee --no-check >/dev/null 2>&1
snap="$CC_PROFILE_ROOT/.usage/c_example_com.json"
render 90 40
absent "two switches back is still recognised" "90"        bash -c 'cat "$1" 2>/dev/null || echo none' _ "$snap"
render 10 20
absent "and so is one switch back"            "10"         bash -c 'cat "$1" 2>/dev/null || echo none' _ "$snap"
render 55 33
t  "the live account still reports"           "55"         cat "$snap"

# Agreeing with the account we left in one window is not being it.
teardown; setup                 # a leaves at 90/40; cee, now live, is its own account
"$CCEX" use cee --no-check >/dev/null 2>&1
snap="$CC_PROFILE_ROOT/.usage/c_example_com.json"
render 90 22
t  "one number in common is not enough" "22"               cat "$snap"

# Numbers filed against the wrong account before this went in are not read back.
teardown; setup
python3 - "$CC_PROFILE_ROOT" "$(week_at a)" <<'MISCREDIT'
import json, os, sys, time
root, week = sys.argv[1], int(sys.argv[2])
os.makedirs(root + "/.usage", exist_ok=True)
json.dump({"email": "c@example.com", "fetchedAtMs": int(time.time() * 1000), "utilization": {
    "five_hour": {"utilization": 97, "resets_at": time.strftime(
        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() + 3600))},
    "seven_day": {"utilization": 44, "resets_at": time.strftime(
        "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(week))}}},
          open(root + "/.usage/c_example_com.json", "w"))
MISCREDIT
absent "a mis-credited reading is not believed" "97"       "$CCEX" ls cee
t  "the account's own cache is used instead"   "50"        "$CCEX" ls cee
# ...and it is not merged back in either, when a render carries only the other window
printf '{"rate_limits":{"five_hour":{"used_percentage":7}}}' | \
  CLAUDE_CONFIG_DIR="$CC_PROFILE_ROOT/cee" "$CCEX" record >/dev/null
filed() {   # one window's percentage out of a snapshot, so no timestamp can pass for it
  python3 -c 'import json,sys
u = (json.load(open(sys.argv[1])).get("utilization") or {}).get(sys.argv[2]) or {}
print(u.get("utilization"))' "$CC_PROFILE_ROOT/.usage/c_example_com.json" "$1"
}
t  "nor merged under a half payload"           "None"      filed seven_day
t  "which still records what it did carry"     "7"         filed five_hour

echo "the daemon"
teardown; setup                 # a is live at 90/40, bee at 10/20, cee at 50/30
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
t  "and beats once per read"     "under"                  cat "$CC_PROFILE_ROOT/.usage/.beat"
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
absent "piped output has no escapes" "$(printf '\033')[" frame 80
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
t  "the keys line offers switching" "enter"                  frame 80
t  "a number asks before moving"    "switch to"            prompt_line "$(number_of)"
t  "and names the account"          "b@example.com"        prompt_line "$(number_of)"
t  "an unknown number says so"      "no account has that number" prompt_line 47
renumber
t  "a two-digit number is reachable" "b@example.com"       prompt_line 12
teardown; setup
drive() {   # <keys> through a real pty: what the view drew, escapes and all
  python3 - "$CCEX" "$1" ${2+"$2"} <<'PYEOF'
import os, pty, select, sys, time
ccex = sys.argv[1]
keys = sys.argv[2].encode().decode("unicode_escape").encode()
later = sys.argv[3].encode().decode("unicode_escape").encode() if len(sys.argv) > 3 else None
limit = 6 if later else 4      # a second burst has to wait for what the first one started
pid, fd = pty.fork()
if pid == 0:
    os.environ.update(TERM="xterm-256color", COLUMNS="120", LINES="20")
    os.execvp(ccex, ["ccex", "ls", "-w", "--at", "80"])
buf, start, sent = b"", time.time(), False
while time.time() - start < limit:
    r, _, _ = select.select([fd], [], [], 0.2)
    if r:
        try:
            c = os.read(fd, 65536)
        except OSError:
            break
        if not c:
            break
        buf += c
    if not sent and time.time() - start > 1.5:
        os.write(fd, keys)      # arrows first, then whatever confirms
        sent = True
    if sent and later and time.time() - start > 3.0:
        os.write(fd, later)     # a second burst: what the first one made possible
        later = None
try:
    os.write(fd, b"q")
    time.sleep(0.3)
except OSError:
    pass
print(buf.decode("utf8", "replace"))
PYEOF
}
drove=$(drive '\x1b[B\r')
t  "arrows mark the selected row"  "›"                       echo "$drove"
t  "the live row keeps its arrow" "▶"                        echo "$drove"
t  "enter switches to the selection" "b@example.com"          live_email

teardown; setup                 # that pty run switched accounts; the rest wants a live again
stub_claude
export CCEX_TEST_EMAIL=ui@example.com PATH="$HOME/bin:$PATH"
drive a >/dev/null
unset CCEX_TEST_EMAIL
t  "a adds an account from the view" "ui@example.com"           "$CCEX" ls
t  "and names its slot after it"     "ui"                       "$CCEX" ls

teardown; setup                 # add, then switch to what was added, in one view
stub_claude
export CCEX_TEST_EMAIL=fresh@example.com PATH="$HOME/bin:$PATH"
drove=$(drive a 4y)
unset CCEX_TEST_EMAIL
matches "a new account gets a number" " 4 [^ ]*fresh@example\.com" echo "$drove"
t  "and switching to it works"       "fresh@example.com"        live_email

teardown; setup
cap_prompt() {   # <keys typed into the editor> -> the line it shows, or what it wrote
  CCEX_BASE="$HOME/.claude" CCEX_ROOT="$CC_PROFILE_ROOT" \
  PYTHONPATH="$(dirname "$CCEX")/../lib/py" python3 - "$1" <<'PYEOF'
import sys
import watch
v = watch.View(at=80)
v.sample()
v.background = lambda label, cmd: print("would run: %s" % " ".join(cmd[1:]))
v.cap_start()
for key in sys.argv[1]:
    v.cap_key("\r" if key == "|" else key)
print(v.frame(126, 20, colour=False)[-1])
print("editing=%s" % v.editing)
PYEOF
}
t  "c opens a cap editor"          "cap "                     cap_prompt ""
t  "on the selected account"       "a@example.com"            cap_prompt ""
t  "digits fill the 5h field"      "5h: 60"                   cap_prompt "60|"
t  "then it asks for the week"     "weekly:"                  cap_prompt "60|"
t  "enter on both applies"         "editing=None"             cap_prompt "60|80|"
t  "and passes both numbers on"    "cap a@example.com --5h 60 --weekly 80" cap_prompt "60|80|"
t  "a dash leaves one uncapped"    "cap a@example.com --clear --weekly 30" cap_prompt "-|30|"
absent "esc runs nothing"          "would run"                cap_prompt "60|$(printf '\033')"
drive 'c60\r45\r' >/dev/null
t  "the view really writes a cap"  "5h 60%, weekly 45%"       "$CCEX" pool cap 1
t  "and ls shows it"               "60/45"                    "$CCEX" ls
drive '\x1b[C' >/dev/null
t  "right takes it out of the pool" "a@example.com"            cat "$CC_PROFILE_ROOT/.pool.json"
drive '\x1b[D' >/dev/null
absent "and left puts it back"      "a@example.com"            cat "$CC_PROFILE_ROOT/.pool.json"

teardown; setup
mkdir -p "$CC_PROFILE_ROOT/.usage"
cat > "$CC_PROFILE_ROOT/.usage/daemon.json" <<'DJ'
{"at": 99, "every": "10s", "refresh": 0, "since": "2026-08-27 16:00:00"}
DJ
: > "$CC_PROFILE_ROOT/.usage/.beat"
t  "the next read is counted down"  "next read in"   frame 99
touch -d '30 seconds ago' "$CC_PROFILE_ROOT/.usage/.beat"
t  "an overdue read says so"        "due now"        frame 99
rm -f "$CC_PROFILE_ROOT/.usage/daemon.json" "$CC_PROFILE_ROOT/.usage/.beat"

printf 'asking bee (on file: 10%% 5h / 20%% weekly)\nbee did not answer (timeout), trying the next\nswitching to cee\n' \
  > "$CC_PROFILE_ROOT/.usage/.step"
t  "the view says what rotation is doing" "asking bee"          frame 99
t  "and what it had on file"               "10% 5h"             frame 99
t  "every action on its own line"          "trying the next"    frame 99
t  "with the newest one marked"            "-> switching to cee" frame 99
matches "one line each, in order" 'asking bee.*\n.*did not answer.*\n.*switching to cee' frame 99
trail_pos() {                   # it belongs under the whole view, not inside it
  local out k s
  out=$(frame 99 2>&1)
  k=$(printf '%s\n' "$out" | grep -n ' keys ' | head -1 | cut -d: -f1)
  s=$(printf '%s\n' "$out" | grep -n 'asking bee' | head -1 | cut -d: -f1)
  if [[ -n $k && -n $s && $s -gt $k ]]; then echo below
  else echo "not below (keys=$k trail=$s)"; fi
}
t  "the trail prints below the view"      "below"              trail_pos
t  "and says how long ago it ran"        "switching    "       frame 99
touch -d '10 minutes ago' "$CC_PROFILE_ROOT/.usage/.step"
absent "a trail nobody cleared goes stale" "asking bee"  frame 99
rm -f "$CC_PROFILE_ROOT/.usage/.step"
absent "and stops once nothing is"         "asking bee"  frame 99
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
