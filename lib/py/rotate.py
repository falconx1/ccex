"""Print rotation's decision as one tab-separated line for `lib/rotate.sh`. Reads `ccex ls --json`."""
import json, os, sys, time

from ccexlib import USAGE_DIR, hm, hold_auto, load, save, slots, step
from decide import FIVE_AT, FIVE_HOUR, WEEKLY_AT, cap, decide, ranked, reads

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
retired = []        # accounts plan() took out of the pool, in the order it did it


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
    for a in accounts:
        if a.get("held") or a["seven"] is None or a["seven"] < WEEKLY_AT:
            continue                      # a low weekly cap keeps an account in reserve; only a
        why = "weekly at %d%%" % a["seven"]   # week that is genuinely spent retires it
        if dry or hold_auto(a["email"], why):
            retired.append("%s (%s)" % (a["name"], why))
            a["held"], a["held_auto"] = True, why
    return decide([a for a in accounts if a["name"] not in skip],
                  at, blind=verify and not dry)


# An account that has spent its week comes off the list, and only `ccex pool in` puts it
# back. This is the one place it happens: the view predicts, the daemon delegates here.
verdict, target, message = plan()

# Before the slot changes hands, ask the account we are moving to what it actually has left.
# Nothing but a running session reports for an account, and a parked one has none -- so its
# numbers are as old as the last time it was live, which in a day of rotating is hours. A
# window past its reset reads 0% without asking anyone, so the countdown keeps stale numbers
# honest by itself; what it cannot do is see an hour spent on that account somewhere else, or
# invent a first reading for an account nothing has ever measured. Both of those are worth a
# session -- but only for the one account about to be used, and only at the moment it is.
if verify and not dry:
    from ask import ask                   # importing it is what makes a session possible

    dirs, checked, notes, unasked = dict(slots()), [], [], []
    if verdict == "SWITCH":
        # Only a tick that is actually moving writes a trail. This block runs on every tick,
        # so an unguarded step() here says "out of room" on the ticks that stayed put, and
        # clears the read-ahead trail the STAY path below just wrote.
        step(None)                # this switch's trail is its own
        live = next((a for a in accounts if a["name"] == "default"), None)
        if live:
            step("%s is out of room at %s, looking for an account with some" % (
                live["name"], reads(live)))
    while verdict == "SWITCH" and target not in checked and len(checked) < TRIES:
        checked.append(target)
        row = next((a for a in accounts if a["name"] == target), None)
        if row is None or target not in dirs:
            break
        blind = row["five"] is None or row["seven"] is None
        current = row.get("live") or (row.get("age_s") is not None and row["age_s"] < CURRENT)
        if current and not blind:
            # Nothing to ask, but the view should still be told why: this is the common case,
            # and a trail that appears only when a session is opened looks like no trail.
            step("%s reads %s, measured %s ago -- no need to ask" % (
                target, reads(row), hm(row["age_s"]) if row.get("age_s") else "moments"))
            break
        was = None if blind else reads(row)      # "0%" would claim a reading there never was
        st, got = ask(target, dirs[target], was,
                      ", leaving it out" if blind else ", trying the next")
        if st == "ok":
            row = got
            accounts[[a["name"] for a in accounts].index(target)] = row
            if was is None:
                notes.append("%s reads %s, measured for the first time" % (target, reads(row)))
            elif reads(row) != was:
                notes.append("%s reads %s checked just now, not %s" % (target, reads(row), was))
        elif blind:
            # Never measured and it could not be measured now: there is nothing to fall back
            # on, so it leaves the running altogether rather than being guessed at.
            skip.add(target)
            notes.append("%s has never been measured and could not be asked (%s)" % (target, st))
        else:
            # Could not be asked is not the same as has no room -- but an account that can be
            # asked is a better answer than one that cannot, so this tries the next instead of
            # going ahead on numbers nothing has confirmed. It stays a fallback for the case
            # where none of them can be asked, below.
            skip.add(target)
            unasked.append(target)
            notes.append("%s could not be asked (%s), so trying the next account" % (target, st))
        verdict, target, message = plan()

    if verdict == "SWITCH" and target not in checked and len(checked) >= TRIES:
        # The loop stops asking somewhere: three sessions is already most of a minute inside
        # the lock. Whoever is left is used on the numbers on file, which is worth saying.
        notes.append("%s was not asked, %d others were" % (target, len(checked)))

    if verdict != "SWITCH" and unasked:
        # Every account that could be asked is spent, and none of the rest would answer. Room
        # on file is a poor answer but staying on an account with none is a worse one, so the
        # best of them is used after all -- and the line says that is what happened.
        skip.difference_update(unasked)
        verdict, target, message = plan()
        if verdict == "SWITCH":
            notes.append("none of them could be asked, so this is the numbers on file")

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
            from ask import ask
            os.makedirs(USAGE_DIR, exist_ok=True)
            save(AHEAD, {"name": cand["name"], "at": time.time()})   # before, so a crash counts
            step(None)                # this read is its own trail
            step("nearly at the cap, reading %s ahead of the switch" % cand["name"])
            n = cand["name"]
            st, row = ask(n, dirs[n])
            if st == "ok":
                message += "; %s reads %s, read ahead of the switch" % (n, reads(row))
            else:
                message += "; %s could not be read ahead of the switch (%s)" % (n, st)

if retired:
    message += "; out of the pool until `ccex pool in`: " + ", ".join(dict.fromkeys(retired))
# `lib/rotate.sh` clears this once the credential has moved. Leaving it set is deliberate:
# the move itself is the part the view should be showing when it happens.
if verdict == "SWITCH":
    step("switching to %s" % target, log=False)
print("\t".join([verdict] + ([target] if target else []) + [message]))
