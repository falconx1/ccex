"""Which account rotation would move to, and why. Shared by `ccex rotate` and `ccex ls -w`.

One function decides, so the switch the watch view predicts is the switch rotation makes.
Its input is the list `ccex ls --json` prints; nothing here reads files or writes anything.
"""
import time

FIVE_HOUR, SEVEN_DAY = 5 * 3600, 7 * 86400
FIVE_AT = 90        # the default --at; lib/background.sh's own default has to agree
WEEKLY_AT = 99      # --at is about the 5-hour window; see default_for()


def default_for(key, at):
    """The out-of-room percentage for a window nobody has capped.

    --at governs the 5-hour window, which is what actually stops you working. The week
    is not: moving off an account at 80% of its week abandons a fifth of it for six days,
    so the week only counts as spent when it very nearly is.
    """
    return WEEKLY_AT if key == "seven" else at


def cap(a, key, at):
    """Where this account runs out: its own cap for that window, or the default if it has none."""
    v = a.get("cap_" + key)
    return default_for(key, at) if v is None else v


def reads(a):
    """The one phrasing of a pair of numbers. Every line that quotes a reading uses this."""
    return "%d%% 5h / %d%% weekly" % (a["five"] or 0, a["seven"] or 0)


def own(a, key, at):
    return "its own %d%%" % a["cap_" + key] if a.get("cap_" + key) is not None \
        else "%d%%" % default_for(key, at)


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


def usable(a, at):
    """Could rotation land here right now: logged in, has numbers, not held, under its caps."""
    return bool(a.get("logged_in")) and a.get("five") is not None and a.get("seven") is not None \
        and not a.get("held") and a["five"] < cap(a, "five", at) and a["seven"] < cap(a, "seven", at)


def unmeasured(a):
    """Logged in and in the pool, but nothing has ever read its windows.

    Not the same as spent. An account nothing has measured is the one thing the countdown
    cannot help with: a window past its reset reads 0% by arithmetic, but only for an
    account that has some number to count down from. With no reading at all there is
    nothing to infer, so it stays invisible unless something goes and looks.
    """
    return bool(a.get("logged_in")) and not a.get("held") \
        and (a.get("five") is None or a.get("seven") is None)


def ranked(accounts, at=FIVE_AT, blind=False):
    """Every account rotation could move to, cheapest first -- the order it picks in.

    The 5-hour window is what actually stops you working, so it decides. Weekly moves
    slowly enough that it rarely separates two accounts you would otherwise be choosing
    between, so it only breaks ties.

    `blind` adds the accounts nothing has measured, always behind every account that has
    been: a real reading beats a guess, so an unmeasured account is only reached for once
    the known ones are out of room -- which is also the only time it is worth a session to
    go and read it. Whoever passes `blind` is undertaking to verify before switching;
    landing on an account whose numbers nobody knows would be worse than the stale numbers
    this is all meant to fix.
    """
    room = [a for a in accounts if a["name"] != "default" and usable(a, at)]
    room.sort(key=lambda a: (cost(a["five"], a["five_resets"], FIVE_HOUR),
                             cost(a["seven"], a["seven_resets"], SEVEN_DAY),
                             a["name"]))
    if blind:
        room += sorted((a for a in accounts if a["name"] != "default" and unmeasured(a)),
                       key=lambda a: a["name"])
    return room


def decide(accounts, at=FIVE_AT, blind=False):
    """(verdict, target, message): STAY, NONE, ERR, or SWITCH to `target`.

    `message` is the sentence `ccex rotate` prints, which is also the one the watch view
    shows -- one explanation, one code path. `blind` is passed through to `ranked`, and
    means the caller will read an unmeasured account before it lands on one.
    """
    live = next((a for a in accounts if a["name"] == "default"), None)
    if live is None:
        return "ERR", None, "no live account"
    if live["five"] is None or live["seven"] is None:
        return "ERR", None, "no usage numbers for %s yet - run `ccex ls` first" % live["email"]
    if live.get("held") and not live.get("held_auto"):
        return "STAY", None, "%s is held out of the pool, so nothing moves it" % live["email"]

    tripped = [(w, own(live, k, at)) for w, k, v in (("5h", "five", live["five"]),
                                                    ("weekly", "seven", live["seven"]))
               if v >= cap(live, k, at)]
    if not tripped:
        under = "under %s" % own(live, "five", at)
        if own(live, "five", at) != own(live, "seven", at):
            under = "under %s 5h / %s weekly" % (own(live, "five", at), own(live, "seven", at))
        return "STAY", None, "%s is at %s, %s" % (live["email"], reads(live), under)

    others = [a for a in accounts if a["name"] != "default"]
    nodata = [a["name"] for a in others if not a["logged_in"] or a["five"] is None or a["seven"] is None]
    held = [a["name"] for a in others if a.get("held")]
    room = ranked(accounts, at, blind)

    why = "%s is at %s (%s over %s)" % (
        live["email"], reads(live),
        " and ".join(w for w, _ in tripped), " and ".join(sorted({o for _, o in tripped})))
    if live.get("held_auto"):
        why += ", and out of the pool (%s)" % live["held_auto"]

    if not room:
        soon = []
        for a in others:
            if a.get("held") or a["name"] in nodata:
                continue
            blocked = [a[k] for k, w in (("five_resets", "five"), ("seven_resets", "seven"))
                       if a.get(w) is not None and a[w] >= cap(a, w, at)]
            if blocked and all(blocked):
                soon.append((max(blocked), a["name"]))   # free only once the last one resets
        tail = ""
        if soon:
            t, n = min(soon)
            left = int(t - time.time())
            tail = "; soonest room is %s in %dh%02dm" % (n, left // 3600, left % 3600 // 60)
        if nodata:
            tail += "; no usage numbers for " + ", ".join(nodata)
        if held:
            tail += "; out of the pool: " + ", ".join(
                "%s (%s)" % (a["name"], a["held_auto"]) if a.get("held_auto") else a["name"]
                for a in others if a.get("held"))
        capped = []
        for a in others:
            if a["name"] in nodata or a.get("held"):
                continue                   # no numbers, or already named as held
            for w in ("five", "seven"):
                if a.get("cap_" + w) is not None and a[w] >= a["cap_" + w]:
                    capped.append("%s at its own %d%%" % (a["name"], a["cap_" + w]))
                    break
        if capped:
            tail += "; capped by their own limits: " + ", ".join(capped)
        return "NONE", None, "%s, and every other account is too%s" % (why, tail)

    best = room[0]
    if best["five"] is None or best["seven"] is None:
        # Last in the ranking, so every measured account is spent. Whoever asked for `blind`
        # reads this one before the slot moves; there is no percentage to quote yet.
        return "SWITCH", best["name"], "%s, so -> %s, which nothing has measured yet" % (
            why, best["email"])
    note = " (numbers %dm old)" % (best["age_s"] // 60) if (best["age_s"] or 0) > 900 else ""
    soon = ""
    if best["five_resets"] and best["five_resets"] - time.time() < FIVE_HOUR / 5:
        soon = ", 5h resets in %dh%02dm" % divmod(int(best["five_resets"] - time.time()) // 60, 60)
    return "SWITCH", best["name"], "%s, so -> %s at %s%s%s" % (
        why, best["email"], reads(best), soon, note)
