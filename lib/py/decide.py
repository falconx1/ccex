"""Which account rotation would move to, and why. Shared by `ccex rotate` and `ccex ls -w`.

One function decides, so the switch the watch view predicts is the switch rotation makes.
Its input is the list `ccex ls --json` prints; nothing here reads files or writes anything.
"""
import time

from burn import eta            # arithmetic only, on a rate the caller has already read
from ccexlib import hm

FIVE_HOUR, SEVEN_DAY = 5 * 3600, 7 * 86400
FIVE_AT = 90        # the default --at; lib/background.sh's own default has to agree
WEEKLY_AT = 99      # --at is about the 5-hour window; see default_for()

# How a cap gives way as the week it protects runs out: from two days, five points every
# twelve hours, and the last five hours are the default -- one window left to spend it in.
RELAX_FROM, RELAX_EVERY, RELAX_BY, LAST = 48 * 3600, 12 * 3600, 5, 5 * 3600
REFILL_SOON = 3600      # a 5-hour window this close to over is quota you get twice over
LOGIN_FLOOR = 300       # a login with less left than this will not outlast the switch onto it


def expired(a, now=None):
    """Whether this account's login is past saving without a browser.

    The refresh token is the clock that ends in a login prompt, and an account whose token
    has run out is not slow, not spent and not held: it cannot be used at all until somebody
    signs in. Landing on one puts a login screen in front of whatever was running, which is
    the one failure a switch is supposed to prevent rather than cause. Minutes from the end
    count as the end -- the switch itself takes longer than that, and an account that dies a
    moment after you arrive strands you just as completely.

    An account with no expiry on file is left alone: nothing about it says expired, and
    reading a missing date as one would empty the fleet over a credential we have not seen.
    """
    t = a.get("refresh_at")
    return t is not None and t - (now or time.time()) <= LOGIN_FLOOR


def default_for(key, at):
    """The out-of-room percentage for a window nobody has capped.

    --at governs the 5-hour window, which is what actually stops you working. The week
    is not: moving off an account at 80% of its week abandons a fifth of it for six days,
    so the week only counts as spent when it very nearly is.
    """
    return WEEKLY_AT if key == "seven" else at


def cap(a, key, at):
    """Where this account runs out: its own cap for that window, or the default if it has none.

    A cap is set against a week -- it keeps you from spending the whole of one early and
    leaving nothing for the days after. As that week ends it is protecting less and less,
    because what it holds back expires at the reset either way, unspent by you and by anyone
    else sharing the account. So it gives way on a ladder: five points every twelve hours
    from two days out, and the default for the last five hours, which is the one window left
    to spend the week in.

    The 5-hour ceiling is the number other people on a shared account actually feel, so it
    alone holds until that last band. Nothing is remembered: this is the clock, read, which
    is why the cap you set is back the moment the new week starts.
    """
    v = a.get("cap_" + key)
    if v is None:
        return default_for(key, at)
    t = a.get("seven_resets")
    left = (t - time.time()) if t else None
    if left is None or left <= 0:
        return v                          # never measured, or a reset that has already passed
    if left <= LAST:
        return default_for(key, at)
    if key == "five" or left > RELAX_FROM:
        return v
    steps = int((RELAX_FROM - left) // RELAX_EVERY) + 1
    return min(default_for(key, at), v + RELAX_BY * steps)


def reads(a):
    """The one phrasing of a pair of numbers. Every line that quotes a reading uses this."""
    return "%d%% 5h / %d%% weekly" % (a["five"] or 0, a["seven"] or 0)


def own(a, key, at):
    v = a.get("cap_" + key)
    if v is None:
        return "%d%%" % default_for(key, at)
    now = cap(a, key, at)
    return "its own %d%%" % v if now == v else "%d%%, its own %d%% given way to as the week ends" % (now, v)


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


def reach(a, at):
    """How much of this account there is to spend soon: what its 5-hour window has left, and
    the whole of the next one when that one is nearly here.

    An account whose window is minutes from over is worth more than its percentage says, not
    less: what is left of it goes unspent otherwise, and a full window lands right behind it.
    An account reading `new` has already reset and is waiting -- a 5-hour window is anchored
    to first use, so it has no clock running and the whole of it is there when you arrive.
    """
    lim = cap(a, "five", at)
    room = max(0, lim - (a["five"] or 0))
    t = a.get("five_resets")
    return room + (lim if t and 0 < t - time.time() <= REFILL_SOON else 0)


def pressure(a, at):
    """How fast this account has to be spent to finish its week: points left per day left.

    A week that ends with points unspent has thrown them away, and the fleet holds more
    quota than there are hours to spend it in -- so what matters between two accounts is not
    which one is further along but which one is further behind. An account with a quarter of
    its week left and five days to spend it is in no danger; one with all of it left and the
    same five days is where the waste will be, and it goes first.
    """
    t = a.get("seven_resets")
    if not t:
        return 0.0
    left = max(0, cap(a, "seven", at) - (a["seven"] or 0))
    return left / max(1.0, (t - time.time()) / 86400)


def capped(a):
    """Whether this account manages its own share, which is what makes it the fallback.

    An account you capped is one you would rather rotation left alone -- shared with someone,
    or held in reserve -- so it comes after every account that has no cap of its own, however
    much either has left. It is reached when nothing else has room, which is what a reserve is.
    """
    return a.get("cap_five") is not None or a.get("cap_seven") is not None


def reachable(a, now=None):
    """Whether rotation may land here at all, whatever its numbers say.

    In the pool, and logged in -- which is two things, and the credential file only says one
    of them. A parked account keeps its `claudeAiOauth` long after the refresh token in it has
    expired, so `expired` asks the other one: whether that login would still be a login on
    arrival. Every reason an account is out of reach goes here, so each place that ranks,
    waits for or reads an account asks one question rather than repeating three.
    """
    return bool(a.get("logged_in")) and not a.get("held") and not expired(a, now)


def pool_state(a):
    """What the POOL column says about this account: `in`, `held` or `expired`.

    A dead login outranks a hold. Both keep rotation off the account, but only one of them
    is undone by `ccex pool in`: this one wants `ccex add`, and a cell that said `held` would
    send you to the wrong command. The tuple order is also the order the column sorts in.
    """
    return "expired" if expired(a) else "held" if a.get("held") else "in"


POOL_STATES = ("in", "held", "expired")


def usable(a, at):
    """Could rotation land here right now: reachable, has numbers, under its caps."""
    return reachable(a) and a.get("five") is not None and a.get("seven") is not None \
        and a["five"] < cap(a, "five", at) and a["seven"] < cap(a, "seven", at)


def unmeasured(a):
    """Logged in and in the pool, but nothing has ever read its windows.

    Not the same as spent. An account nothing has measured is the one thing the countdown
    cannot help with: a window past its reset reads 0% by arithmetic, but only for an
    account that has some number to count down from. With no reading at all there is
    nothing to infer, so it stays invisible unless something goes and looks.
    """
    return reachable(a) and (a.get("five") is None or a.get("seven") is None)


def ranked(accounts, at=FIVE_AT, blind=False):
    """Every account rotation could move to, most to spend first -- the order it picks in.

    Uncapped accounts come first, all of them, because a cap is how you say an account is
    someone else's or held back. Within each group it is what there is to spend that decides
    -- `reach`, which counts a window about to turn over as the two windows it really is.

    The week breaks ties, by `pressure` -- what it has left against the time it has left to
    spend it in. Two accounts with the same room now are not the same account to reach for:
    the one that has to spend fastest to finish its week is the one whose quota is about to
    go unspent, and the one that could finish any time this week keeps. Equal pressure goes
    in the order the weeks end.

    `blind` adds the accounts nothing has measured, always behind every account that has
    been: a real reading beats a guess, so an unmeasured account is only reached for once
    the known ones are out of room -- which is also the only time it is worth a session to
    go and read it. Whoever passes `blind` is undertaking to verify before switching;
    landing on an account whose numbers nobody knows would be worse than the stale numbers
    this is all meant to fix.
    """
    room = [a for a in accounts if a["name"] != "default" and usable(a, at)]
    room.sort(key=lambda a: (capped(a), -reach(a, at), -pressure(a, at),
                             cost(a["seven"], a["seven_resets"], SEVEN_DAY),
                             a["name"]))
    if blind:
        room += sorted((a for a in accounts if a["name"] != "default" and unmeasured(a)),
                       key=lambda a: a["name"])
    return room


def listing(accounts, at=FIVE_AT):
    """Every account in the order a view shows them: live first, then rotation's order.

    A view answers the same question rotation does -- which account is next -- so it reads
    top down in the order the answer comes: the account in use, then the one a switch would
    land on, then the one after that. What rotation will not reach at all (held, spent,
    still capped out) falls to the bottom in account order, where it is a list rather than a
    queue.
    """
    live = [a for a in accounts if a["name"] == "default"]
    order = ranked(accounts, at, blind=True)
    seen = {id(a) for a in live + order}
    rest = sorted((a for a in accounts if id(a) not in seen),
                  key=lambda a: (a["id"] or 99, a["name"]))
    return live + order + rest


def soonest_room(accounts, at, now=None):
    """When the fleet next has an account rotation could land on: (seconds, name).

    (None, None) when nothing is due back. Only an account that is merely spent comes back
    on a clock: one that is held, refused or never measured is waiting on somebody rather
    than on a window, and "when can I work again" is not a question it answers. An account
    with both windows over their caps is free only once the later of the two has reset.
    """
    now = now or time.time()
    soon = []
    for a in accounts:
        # A window comes back on a clock; a hold or a dead login does not.
        if a["name"] == "default" or not reachable(a, now) or a["five"] is None \
                or a["seven"] is None:
            continue
        blocked = [a[k] for k, w in (("five_resets", "five"), ("seven_resets", "seven"))
                   if a[w] >= cap(a, w, at)]
        if blocked and all(blocked):
            soon.append((max(blocked) - now, a["name"]))
    return min(soon) if soon else (None, None)


def runway(live, at, now=None):
    """(seconds until the live account trips the cap that will move it, which window).

    Needs `rate_five`/`rate_seven` on the row, so only a caller that has read the burn
    history gets an answer; without a rate there is nothing honest to say. Whichever window
    arrives first is the one that counts, because it is the one that will move you.
    """
    best = (None, None)
    for label, key, rk, pk in (("5h", "five", "rate_five", "five_resets"),
                               ("weekly", "seven", "rate_seven", "seven_resets")):
        secs, _ = eta(live.get(key), cap(live, key, at), live.get(rk), live.get(pk), now)
        if secs is not None and (best[0] is None or secs < best[0]):
            best = (secs, label)
    return best


def gap(accounts, at, now=None):
    """The hole between the live account running out and anything else having room.

    `(runway, wait, name)` -- how long this account lasts, how long until the fleet has room
    again (None if nothing is due back) and whose account that is -- or None when there is no
    hole to warn about.

    An estimate is only a countdown to a switch while there is somewhere to switch to. When
    every other account is spent it becomes a countdown to not being able to work at all, and
    that is worth saying while there is still time to do something about it -- land what is
    running, or lift a cap -- rather than at the moment it happens, which is what the `NONE`
    verdict already says. So this is deliberately silent once the cap is actually crossed:
    by then it is not a warning, it is the news.
    """
    now = now or time.time()
    live = next((a for a in accounts if a["name"] == "default"), None)
    if live is None or live.get("held"):
        return None
    if ranked(accounts, at, blind=True):
        return None                       # somewhere to go: the switch is the answer
    secs, _ = runway(live, at, now)
    if secs is None:
        return None                       # no rate yet, or not climbing at anything
    wait, who = soonest_room(accounts, at, now)
    if wait is not None and wait <= secs:
        return None                       # what is waiting is back before this runs out
    return secs, wait, who


def gap_words(g):
    """The one sentence a coming gap is said in, wherever it is said.

    Three places say it -- the daemon's journal, the tray, the live view -- and they say it
    the same way, because it is one fact and somebody reading two of them at once should not
    have to work out whether they agree.
    """
    secs, wait, who = g
    left = hm(secs) if secs >= 60 else "under a minute"
    if wait is None:
        return "about %s of room left, and nothing else has any" % left
    return "about %s of room left, and nothing else has any until %s in %s (a %s gap)" % (
        left, who, hm(wait), hm(wait - secs))


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
    gone = [a["name"] for a in others if expired(a)]
    room = ranked(accounts, at, blind)

    why = "%s is at %s (%s over %s)" % (
        live["email"], reads(live),
        " and ".join(w for w, _ in tripped), " and ".join(sorted({o for _, o in tripped})))
    if live.get("held_auto"):
        why += ", and out of the pool (%s)" % live["held_auto"]

    if not room:
        tail = ""
        left, n = soonest_room(accounts, at)
        if left is not None:
            left = int(left)
            tail = "; soonest room is %s in %dh%02dm" % (n, left // 3600, left % 3600 // 60)
        if gone:
            # Out of reach for a reason no clock fixes and `ccex pool in` does not either --
            # and the more useful thing to say about an account that also has no numbers,
            # since signing it back in is what would get it some.
            tail += "; login expired, needs `ccex add`: " + ", ".join(gone)
        blank = [n for n in nodata if n not in gone]
        if blank:
            tail += "; no usage numbers for " + ", ".join(blank)
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
