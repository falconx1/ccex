"""Decide whether to move off the live account, and onto which one. Reads `ccex limits --json`."""
import json, sys, time

accounts = json.load(sys.stdin)
argv = sys.argv[1:]
at = 80
for i, a in enumerate(argv):
    if a == "--at" and i + 1 < len(argv):
        at = int(argv[i + 1])

live = next((a for a in accounts if a["name"] == "default"), None)
if live is None:
    print("ERR\tno live account"); raise SystemExit
if live["five"] is None or live["seven"] is None:
    print("ERR\tno usage numbers for %s yet - run `ccex limits` first" % live["email"]); raise SystemExit

tripped = [w for w, v in (("5h", live["five"]), ("weekly", live["seven"])) if v >= at]
if not tripped:
    print("STAY\t%s is at %d%% 5h / %d%% weekly, under %d%%" %
          (live["email"], live["five"], live["seven"], at)); raise SystemExit

others = [a for a in accounts if a["name"] != "default"]
nodata = [a["name"] for a in others if not a["logged_in"] or a["five"] is None or a["seven"] is None]
room = [a for a in others if a["name"] not in nodata and a["five"] < at and a["seven"] < at]

why = "%s is at %d%% 5h / %d%% weekly (%s over %d%%)" % (
    live["email"], live["five"], live["seven"], " and ".join(tripped), at)

if not room:
    soon = [(a[k], a["name"]) for a in accounts for k in ("five_resets", "seven_resets")
            if a.get(k) and a[k] > time.time()]
    tail = ""
    if soon:
        t, n = min(soon)
        left = int(t - time.time())
        tail = "; soonest room is %s in %dh%02dm" % (n, left // 3600, left % 3600 // 60)
    if nodata:
        tail += "; no usage numbers for " + ", ".join(nodata)
    print("NONE\t%s, and every other account is too%s" % (why, tail)); raise SystemExit

room.sort(key=lambda a: (-min(100 - a["five"], 100 - a["seven"]), a["seven"], a["name"]))
best = room[0]
note = " (numbers %dm old)" % (best["age_s"] // 60) if (best["age_s"] or 0) > 900 else ""
print("SWITCH\t%s\t%s, so -> %s at %d%% 5h / %d%% weekly%s" %
      (best["name"], why, best["email"], best["five"], best["seven"], note))
