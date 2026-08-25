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

FIVE_HOUR, SEVEN_DAY = 5 * 3600, 7 * 86400

def cost(used, resets_at, window):
    """What that usage will actually cost you: a window about to reset barely costs anything.

    Quota you are stuck with for the whole window counts in full; quota that expires in
    twenty minutes counts for almost nothing, because the window refills before you could
    have spent what is left of it.
    """
    if not resets_at:
        return used                       # no reset time known, so assume you are stuck with it
    left = max(0.0, resets_at - time.time())
    return used * min(1.0, left / window)

# The 5-hour window is what actually stops you working, so it decides. Weekly moves slowly
# enough that it rarely separates two accounts you would otherwise be choosing between.
room.sort(key=lambda a: (cost(a["five"], a["five_resets"], FIVE_HOUR),
                         cost(a["seven"], a["seven_resets"], SEVEN_DAY),
                         a["name"]))
best = room[0]
note = " (numbers %dm old)" % (best["age_s"] // 60) if (best["age_s"] or 0) > 900 else ""
soon = ""
if best["five_resets"] and best["five_resets"] - time.time() < FIVE_HOUR / 5:
    soon = ", 5h resets in %dh%02dm" % divmod(int(best["five_resets"] - time.time()) // 60, 60)
print("SWITCH\t%s\t%s, so -> %s at %d%% 5h / %d%% weekly%s%s" %
      (best["name"], why, best["email"], best["five"], best["seven"], soon, note))
