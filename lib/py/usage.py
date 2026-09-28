"""Reading the two usage windows: a running session, the on-disk cache, or the clock.

Nothing here spends quota or launches anything -- it only reads files. `limits.py` adds
the one thing that can cost a session (the pty probe); `watch.py` renders these numbers
live. Both read them through here, so they never disagree.
"""
import datetime, os, re, subprocess, sys, time

import burn

from ccexlib import (BASE, CFG_KEYS, caps, cfg_for, email_for, foreign_report, fresh, held,
                     held_auto, hm, id_for, logged_in, refresh_at, snap_path)

GRACE = 60          # a window inside its last minute has effectively already rolled over
# A statusline render is the only thing that files a reading, and it happens on the main
# thread. Work that has moved into subagents leaves the process, the window and the last
# snapshot exactly where they were and files nothing while it runs -- so a session-sourced
# reading older than this is not a session reporting, it is one that has gone quiet, and the
# percentage in it is where the account was rather than where it is.
REPORTING = 300
BUSY = 180          # a transcript appended to this recently is a session still being answered
_walk = (0.0, {})   # the last /proc walk, and when
_busy = {}          # per account: (when we looked, what we found)


def proc_map(base):
    """{config dir: [pids]} for every running Claude Code session, in one /proc pass."""
    out = {}
    if not os.path.isdir("/proc"):
        return out
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as f:
                cmd = f.read().split(b"\0")
            if not cmd or os.path.basename(cmd[0].decode("utf8", "replace")) != "claude":
                continue
            with open("/proc/%s/environ" % pid, "rb") as f:
                env = dict(e.split(b"=", 1) for e in f.read().split(b"\0") if b"=" in e)
            cd = env.get(b"CLAUDE_CONFIG_DIR", b"").decode("utf8", "replace")
            out.setdefault(os.path.realpath(cd) if cd else base, []).append(int(pid))
        except (OSError, ValueError):
            continue
    return out


def ps_map(base):
    """The same map, asked of `ps` -- macOS has no /proc but does hand you your own env.

    `-E` appends each process's environment to its command line, for processes of this user,
    which is the one thing this needs: the config dir a running session was started with.
    """
    out = {}
    try:
        p = subprocess.run(["ps", "-Ewwo", "pid=,command="],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return out
    if p.returncode != 0:
        return out
    for line in p.stdout.splitlines():
        pid, _, rest = line.strip().partition(" ")
        if not pid.isdigit() or not rest:
            continue
        if os.path.basename(rest.split(" ", 1)[0]) != "claude":
            continue
        hit = re.search(r"(?:^| )CLAUDE_CONFIG_DIR=(\S*)", rest)
        cd = hit.group(1) if hit else ""
        out.setdefault(os.path.realpath(cd) if cd else base, []).append(int(pid))
    return out


SCAN = ps_map if sys.platform == "darwin" else proc_map   # asked once, not once per walk


def live_map(max_age=0.0):
    """{config dir: [pids]} for every running Claude Code session, in one pass.

    `max_age` reuses a walk that recent instead of making another: reading the command and
    environment of every process on the machine is the one expensive thing in here, and who
    is running does not change between two questions asked a second apart.
    """
    global _walk
    if max_age and time.time() - _walk[0] <= max_age:
        return _walk[1]
    _walk = (time.time(), SCAN(os.path.realpath(BASE)))
    return _walk[1]


def live_sessions(d):
    """PIDs of Claude Code sessions currently running as this account (Linux only)."""
    return live_map(max_age=2).get(os.path.realpath(d), [])


def working(d, within=BUSY, max_age=30.0):
    """(main thread answered recently, a subagent answered recently) for this account.

    The one signal that survives a subagent run. A session whose work has moved into
    subagents stops rendering its statusline and stops appending to its own transcript, so
    from outside it is indistinguishable from an idle one -- but every reply a subagent gets
    is appended to a transcript of its own, in a directory beside the session file, and that
    is a file with a time on it.

    The two are kept apart because only the pair says what is happening. Main quiet with
    subagents answering is a session spending the account with nothing reporting it, and it
    is the only state worth treating a reading as out of date rather than merely old. Main
    answering means renders are coming; neither answering means nobody is spending anything.

    The walk is a few thousand stats and takes about as many milliseconds; it is cached
    anyway, because the caller asks once a tick and nobody's transcripts move in between.
    """
    hit = _busy.get(d)
    now = time.time()
    if hit and now - hit[0] <= max_age:
        return hit[1]
    main = sub = False
    cut = now - within
    for root, _, files in os.walk(os.path.join(d, "projects")):
        under_sub = os.path.basename(root) == "subagents"
        if sub if under_sub else main:
            continue                  # already found one of this kind; nothing to learn here
        for f in files:
            if not f.endswith(".jsonl"):
                continue
            try:
                if os.stat(os.path.join(root, f)).st_mtime >= cut:
                    if under_sub:
                        sub = True
                    else:
                        main = True
                    break
            except OSError:
                continue
        if main and sub:
            break
    _busy[d] = (now, (main, sub))
    return main, sub


def busy(d, within=BUSY, max_age=30.0):
    """True when anything on this account -- main thread or subagent -- answered recently."""
    return any(working(d, within, max_age))


def blacked_out(d, snap, running, now=None):
    """True when this account is being spent and nothing is filing what it costs.

    Three things at once, and all three are needed. Nothing has rendered in REPORTING, so
    the reading on file is not current. Subagents are still being answered, so the account
    is being spent right now. And the main thread is quiet, which is why no render is coming
    -- a main thread that is answering will file one within seconds and there is nothing to
    estimate.
    """
    if not running or reporting(snap, running, now):
        return False        # nothing is running it, so nothing is spending it -- and no walk
    main, sub = working(d)
    return sub and not main


def reporting(snap, running, now=None):
    """True when a session on this account is filing readings now, not merely open.

    `snap` came from a statusline only in the sense that one wrote it; how long ago it did
    is the part that decides. A process being up says nothing on its own -- see REPORTING.
    """
    ms = snap.get("fetchedAtMs") or 0
    return bool(running) and snap.get("source") == "session" and ms > 0 \
        and (now or time.time()) - ms / 1000 <= REPORTING


def cached(d):
    """Freshest limits we have, window by window.

    A running session's statusline beats the on-disk cache, but it does not always carry
    both windows -- Claude Code omits one that has just rolled over. Taking the freshest
    source wholesale would then lose that window entirely, so each is chosen separately.
    """
    cfg = fresh(cfg_for(d), CFG_KEYS)
    c = cfg.get("cachedUsageUtilization") or {}
    if c.get("accountUuid") and c["accountUuid"] != (cfg.get("oauthAccount") or {}).get("accountUuid"):
        c = {}                     # left behind by whoever held this slot before
    snap = fresh(snap_path(email_for(d)))
    # Numbers a session filed here while it was still signed in as another account. The
    # week point says so however old the reading is, so a slot that was mis-credited
    # before falls back to what Claude Code cached for it rather than staying wrong.
    if foreign_report(email_for(d), snap.get("utilization") or {}, window=0):
        snap = {}
    sources = [(snap.get("fetchedAtMs") or 0, snap.get("utilization") or {}, "session"),
               (c.get("fetchedAtMs") or 0, c.get("utilization") or {}, "cache")]
    sources.sort(key=lambda x: -x[0])

    util, ages, names = {}, [], set()
    for key in ("five_hour", "seven_day"):
        for ms, u, name in sources:
            v = u.get(key)
            if isinstance(v, dict) and v.get("utilization") is not None:
                util[key] = v
                ages.append(ms)
                names.add(name)
                break
    # The row is only as current as its stalest window, and only "live" if a session is
    # reporting all of them -- otherwise a frozen window hides behind a fresh one.
    return {"fetchedAtMs": min(ages) if ages else 0,
            "utilization": util,
            "source": "session" if names == {"session"} else "cache"}


def reset_at(d, key, snap=None):
    v = ((snap or cached(d))["utilization"] or {}).get(key)
    if not isinstance(v, dict) or v.get("utilization") is None:
        return None, None
    ra = v.get("resets_at")
    try:
        return v["utilization"], datetime.datetime.fromisoformat(ra).timestamp() if ra else None
    except (TypeError, ValueError):
        return v["utilization"], None


def still_counting(d, snap=None):
    """True while some window we know about has not provably run out - i.e. old numbers still lie."""
    snap = snap or cached(d)
    return any(pct is not None and (t is None or t - time.time() > GRACE)
               for pct, t in (reset_at(d, k, snap) for k in ("five_hour", "seven_day")))


def age_text(seconds):
    """How old a reading is, in the one wording `ccex ls` and `ccex ls -w` both use."""
    if seconds is None:
        return "never checked"
    return "just now" if seconds < 90 else "%s ago" % hm(seconds)


def age(d, snap=None):
    f = (snap or cached(d)).get("fetchedAtMs")
    return age_text(time.time() - f / 1000 if f else None)


def projected(d, key, pct, snap, running, now=None):
    """Where this window has probably got to since the last reading, or `pct` unchanged.

    Only during a blackout: subagents being answered, the main thread quiet, and nothing
    rendered in REPORTING. There the number on file is not merely old, it is known to be
    wrong and known which way, and staying put on it is how an account reaches 100% with
    ccex still reading 36%.

    The rate is burn's, unchanged. What makes that safe is what it refuses: fewer than two
    readings in its lookback, or a run that did not climb, and it returns None -- which is
    exactly the account that has just been switched to or has been sitting idle, the one
    there is nothing to extrapolate from. No rate, no estimate, and the reading on file
    stands as it does today.

    It only ever goes up. A rate is an estimate and a reading is not, so the estimate is
    never allowed to talk a measured number downwards.
    """
    now = now or time.time()
    ms = (snap or {}).get("fetchedAtMs") or 0
    if not ms or not blacked_out(d, snap or {}, running, now):
        return pct, False
    rate = burn.rate(email_for(d), key, now)
    if not rate:
        return pct, False
    grown = min(100.0, max(pct, pct + rate * (now - ms / 1000) / 3600.0))
    if grown > pct:
        # Filed so the render that ends this blackout can score it. Written on every call
        # rather than once, because the estimate that matters is the last one standing --
        # the one a switch would have acted on.
        burn.note_guess(email_for(d), key, pct, grown, rate, now - ms / 1000)
    return grown, grown > pct


def effective(d, key, now=None, snap=None, running=None):
    """(percent used, when it resets, whether that number was inferred rather than measured).

    A window whose reset time has passed is 0% used by arithmetic, not by asking anyone --
    which is why parked accounts can be ranked at all. That check comes first: a window that
    has already rolled over has nothing to project forward.
    """
    pct, t = reset_at(d, key, snap)
    if pct is None:
        return None, None, False
    if t and t - (now or time.time()) <= GRACE:
        return 0, t, True
    if running is None:
        running = live_sessions(d)
    pct, guessed = projected(d, key, pct, snap or cached(d), running, now)
    return pct, t, guessed


def account_json(name, d, now=None, pids=None):
    """One account as `ccex ls --json` prints it -- what `decide.py` and the watch view read.

    `pids` is a `live_map()` result: pass one in and no /proc walk happens here, which is
    what makes reading every account on a timer cheap.
    """
    c = cached(d)
    running = bool(pids.get(os.path.realpath(d))) if pids is not None else bool(live_sessions(d))
    five, ft, fi = effective(d, "five_hour", now, c, running)
    seven, st, si = effective(d, "seven_day", now, c, running)
    c5, c7 = caps(d)
    return {"name": name, "id": id_for(d), "email": email_for(d), "five": five, "seven": seven,
            "five_resets": ft, "seven_resets": st, "inferred": fi or si,
            # What was actually read off a statusline, before any projection or rollover
            # arithmetic. `five`/`seven` are what to act on; these are the only numbers fit to
            # record as history, because a rate built from its own output stops being evidence.
            "five_measured": reset_at(d, "five_hour", c)[0],
            "seven_measured": reset_at(d, "seven_day", c)[0],
            "age_s": int((now or time.time()) - c["fetchedAtMs"] / 1000) if c["fetchedAtMs"] else None,
            "live": reporting(c, running, now),
            "held": held(d), "held_auto": held_auto(d),
            "cap_five": c5, "cap_seven": c7, "logged_in": logged_in(d),
            "refresh_at": refresh_at(d)}


def fill(pct, width):
    """How many cells of a meter that percentage fills -- one rounding rule for every bar."""
    return max(0, min(width, int(round((pct or 0) / 100.0 * width))))


def bar(pct, width=10):
    """How much of the window is spent, the same meter Claude Code's own statusline draws."""
    n = fill(pct, width)
    return "█" * n + "░" * (width - n)


# What a row shows when the percentage in it is carried forward rather than measured. It
# goes where a space was, so no column moves and no number is quoted as if someone read it.
GUESS = "~"


def window(d, key):
    pct, t, guessed = effective(d, key)
    if pct is None:
        return "-"
    mark = GUESS if guessed else " "
    if t is None:
        return "%s%d%% used" % (mark.strip(), pct)
    left = t - time.time()
    when = time.strftime("%H:%M" if time.strftime("%d-%m") == time.strftime("%d-%m", time.localtime(t))
                         else "%d-%m %H:%M", time.localtime(t))
    if left <= GRACE:
        return "%s    0%% used - window reset at %s, nothing measured since" % (bar(0), when)
    return "%s %s%3d%% used, resets %s (%s)" % (bar(pct), mark, pct, when, hm(left))


def compact(d, key):
    pct, t, guessed = effective(d, key)
    if pct is None:
        return "-"
    mark = GUESS if guessed else " "
    if t is None:
        return "%s%d%%" % (mark.strip(), pct)
    left = t - time.time()
    if left <= GRACE:
        return "%s    0%% new" % bar(0)
    return "%s %s%3d%% %s" % (bar(pct), mark, pct, hm(left))
