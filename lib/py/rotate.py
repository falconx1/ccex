"""Print rotation's decision as one tab-separated line for `lib/rotate.sh`. Reads `ccex ls --json`."""
import json, sys

from ccexlib import hold_auto
from decide import FIVE_AT, WEEKLY_AT, decide

accounts = json.load(sys.stdin)
argv = sys.argv[1:]
at = FIVE_AT
for i, a in enumerate(argv):
    if a == "--at" and i + 1 < len(argv):
        at = int(argv[i + 1])
dry = "-n" in argv or "--dry-run" in argv

# An account that has spent its week comes off the list, and only `ccex pool in` puts it
# back. This is the one place it happens: the view predicts, the daemon delegates here.
retired = []
for a in accounts:
    if a.get("held") or a["seven"] is None or a["seven"] < WEEKLY_AT:
        continue                      # a low weekly cap keeps an account in reserve; only a
    why = "weekly at %d%%" % a["seven"]   # week that is genuinely spent retires it
    if dry or hold_auto(a["email"], why):
        retired.append("%s (%s)" % (a["name"], why))
        a["held"], a["held_auto"] = True, why

verdict, target, message = decide(accounts, at)
if retired:
    message += "; out of the pool until `ccex pool in`: " + ", ".join(retired)
print("\t".join([verdict] + ([target] if target else []) + [message]))
