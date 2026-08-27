"""Print rotation's decision as one tab-separated line for `lib/rotate.sh`. Reads `ccex ls --json`."""
import json, os, sys, time

from ccexlib import USAGE_DIR, hold_auto, load, save, slots
from decide import FIVE_AT, FIVE_HOUR, WEEKLY_AT, cap, decide, ranked

accounts = json.load(sys.stdin)
argv = sys.argv[1:]
at = FIVE_AT
for i, a in enumerate(argv):
    if a == "--at" and i + 1 < len(argv):
        at = int(argv[i + 1])
dry = "-n" in argv or "--dry-run" in argv
verify = "--no-verify" not in argv
TRIES = 3           # candidates to ask directly before going with what we already had
CURRENT = 300       # numbers this recent are worth nothing extra to re-ask for
NEAR = 5            # percentage points below the cap that count as about to switch
AHEAD = os.path.join(USAGE_DIR, ".readahead.json")   # what was already read for this window
skip = set()        # candidates this run has ruled out, so re-deciding does not offer them again


def opened(live):
    """When the live account's current 5-hour window began, or None if it cannot be known.

    Used only to bound how often reading ahead may happen -- once per window. It is far too
    wide to serve as freshness: a reading from four hours ago is inside this window and is
    exactly the kind of stale number the check before a switch exists to replace.
    """
    if not live or not live.get("five_resets"):
        return None
    return live["five_resets"] - FIVE_HOUR


def asked_since(cand, since):
    """Has this account been read since that moment. False if there is no moment to compare."""
    if since is None or cand["five"] is None or cand["age_s"] is None:
        return False
    return time.time() - cand["age_s"] >= since


def plan():
    """Retire what has spent its week, then decide. Both, because verification can turn up
    the number that retires an account, and it should retire it like any other would.

    Only verification can offer an unmeasured account, so `blind` follows it exactly: with
    nothing going to read that account first, being unmeasured has to keep it out.
    """
    retired = []
    for a in accounts:
        if a.get("held") or a["seven"] is None or a["seven"] < WEEKLY_AT:
            continue                      # a low weekly cap keeps an account in reserve; only a
        why = "weekly at %d%%" % a["seven"]   # week that is genuinely spent retires it
        if dry or hold_auto(a["email"], why):
            retired.append("%s (%s)" % (a["name"], why))
            a["held"], a["held_auto"] = True, why
    return decide([a for a in accounts if a["name"] not in skip],
                  at, blind=verify and not dry) + (retired,)


def reads(a):
    return "%d%% 5h / %d%% weekly" % (a["five"] or 0, a["seven"] or 0)


# An account that has spent its week comes off the list, and only `ccex pool in` puts it
# back. This is the one place it happens: the view predicts, the daemon delegates here.
verdict, target, message, retired = plan()

# Before the slot changes hands, ask the account we are moving to what it actually has left.
# Nothing but a running session reports for an account, and a parked one has none -- so its
# numbers are as old as the last time it was live, which in a day of rotating is hours. A
# window past its reset reads 0% without asking anyone, so the countdown keeps stale numbers
# honest by itself; what it cannot do is see an hour spent on that account somewhere else, or
# invent a first reading for an account nothing has ever measured. Both of those are worth a
# session -- but only for the one account about to be used, and only at the moment it is.
if verify and not dry:
    from probe import probe                # importing it is what makes a session possible
    from usage import account_json

    dirs, checked, notes = dict(slots()), [], []
    while verdict == "SWITCH" and target not in checked and len(checked) < TRIES:
        checked.append(target)
        row = next((a for a in accounts if a["name"] == target), None)
        if row is None or target not in dirs:
            break
        blind = row["five"] is None or row["seven"] is None
        current = row.get("live") or (row.get("age_s") is not None and row["age_s"] < CURRENT)
        if current and not blind:
            break                          # measured moments ago; there is nothing to ask
        was = None if blind else reads(row)      # "0%" would claim a reading there never was
        st = probe(dirs[target])
        if st == "ok":
            row = account_json(target, dirs[target])
            accounts[[a["name"] for a in accounts].index(target)] = row
            if was is None:
                notes.append("%s reads %s, measured for the first time" % (target, reads(row)))
            elif reads(row) != was:
                notes.append("%s reads %s checked just now, not %s" % (target, reads(row), was))
        elif blind:
            # Nothing to fall back on: landing on an account whose windows nobody has ever
            # read would be a worse guess than the stale numbers this is here to replace.
            skip.add(target)
            notes.append("%s has never been measured and could not be asked (%s)" % (target, st))
        else:
            # Unverified is not the same as out of room: a probe that cannot run must not
            # empty the pool, so the switch goes ahead on the numbers we had, and says so.
            notes.append("%s could not be checked first (%s)" % (target, st))
            break
        verdict, target, message, more = plan()
        retired += more
    for n in notes:
        message += "; " + n

# Not over the cap yet, but close enough to it that the next account is worth reading now.
# Nearness is a usage distance, not a clock: how far the live account's percentage is from
# the point that will move it.
#
# What this buys is mostly a better decision rather than a saved session. Ranking picks from
# the numbers on file, and those are what go wrong -- an account read 85% while the account
# itself said 100%, which made a spent one look like the best candidate. Reading it while the
# switch is still approaching fixes the ranking before it is used. The switch that follows
# still asks for itself unless this landed inside CURRENT.
#
# Once per 5-hour window is the bound that keeps it from becoming a timer, and a read that
# failed counts as a read: otherwise an account that cannot be read is re-asked every tick.
if verify and not dry and verdict == "STAY":
    live = next((a for a in accounts if a["name"] == "default"), None)
    # Either window can be the one that trips, so either being close is close enough. The
    # live account may sit at 28% for the hour and still be days from a weekly cap it will
    # cross first.
    close = live and any(live[k] is not None and live[k] >= cap(live, k, at) - NEAR
                         for k in ("five", "seven"))
    room = ranked(accounts, at, blind=True) if close else []
    dirs = dict(slots()) if room else {}
    cand = room[0] if room and room[0]["name"] in dirs else None   # the one it would pick
    since = opened(live)
    if cand and since is not None:
        # A reading from this window is enough on its own. An attempt from this window is
        # enough too, because a read-ahead that failed will fail again: without this, an
        # account that cannot be read would be re-asked every tick, which is the timer none
        # of this is supposed to be.
        tried = load(AHEAD)
        done = asked_since(cand, since) or \
            (tried.get("name") == cand["name"] and (tried.get("at") or 0) >= since)
        if not done:
            from probe import probe
            from usage import account_json
            os.makedirs(USAGE_DIR, exist_ok=True)
            save(AHEAD, {"name": cand["name"], "at": time.time()})   # before, so a crash counts
            st = probe(dirs[cand["name"]])
            if st == "ok":
                row = account_json(cand["name"], dirs[cand["name"]])
                message += "; %s reads %d%% 5h / %d%% weekly, read ahead of the switch" % (
                    cand["name"], row["five"] or 0, row["seven"] or 0)
            else:
                message += "; %s could not be read ahead of the switch (%s)" % (cand["name"], st)

if retired:
    message += "; out of the pool until `ccex pool in`: " + ", ".join(dict.fromkeys(retired))
print("\t".join([verdict] + ([target] if target else []) + [message]))
