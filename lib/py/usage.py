"""Reading the two usage windows: a running session, the on-disk cache, or the clock.

Nothing here spends quota or launches anything -- it only reads files. `limits.py` adds
the one thing that can cost a session (the pty probe); `watch.py` renders these numbers
live. Both read them through here, so they never disagree.
"""
import datetime, os, time

from ccexlib import (BASE, CFG_KEYS, caps, cfg_for, email_for, foreign_report, fresh, held,
                     held_auto, hm, id_for, logged_in, snap_path)

GRACE = 60          # a window inside its last minute has effectively already rolled over
_walk = (0.0, {})   # the last /proc walk, and when


def live_map(max_age=0.0):
    """{config dir: [pids]} for every running Claude Code session, in one /proc pass.

    `max_age` reuses a walk that recent instead of making another: reading cmdline and
    environ for every process on the machine is the one expensive thing in here, and who
    is running does not change between two questions asked a second apart.
    """
    global _walk
    if max_age and time.time() - _walk[0] <= max_age:
        return _walk[1]
    out = {}
    if not os.path.isdir("/proc"):
        return out
    base = os.path.realpath(BASE)
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
    _walk = (time.time(), out)
    return out


def live_sessions(d):
    """PIDs of Claude Code sessions currently running as this account (Linux only)."""
    return live_map(max_age=2).get(os.path.realpath(d), [])


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


def effective(d, key, now=None, snap=None):
    """(percent used, when it resets, whether that zero was inferred rather than measured).

    A window whose reset time has passed is 0% used by arithmetic, not by asking anyone --
    which is why parked accounts can be ranked at all.
    """
    pct, t = reset_at(d, key, snap)
    if pct is None:
        return None, None, False
    if t and t - (now or time.time()) <= GRACE:
        return 0, t, True
    return pct, t, False


def account_json(name, d, now=None, pids=None):
    """One account as `ccex ls --json` prints it -- what `decide.py` and the watch view read.

    `pids` is a `live_map()` result: pass one in and no /proc walk happens here, which is
    what makes reading every account on a timer cheap.
    """
    c = cached(d)
    five, ft, fi = effective(d, "five_hour", now, c)
    seven, st, si = effective(d, "seven_day", now, c)
    c5, c7 = caps(d)
    running = bool(pids.get(os.path.realpath(d))) if pids is not None else bool(live_sessions(d))
    return {"name": name, "id": id_for(d), "email": email_for(d), "five": five, "seven": seven,
            "five_resets": ft, "seven_resets": st, "inferred": fi or si,
            "age_s": int((now or time.time()) - c["fetchedAtMs"] / 1000) if c["fetchedAtMs"] else None,
            "live": c["source"] == "session" and running,
            "held": held(d), "held_auto": held_auto(d),
            "cap_five": c5, "cap_seven": c7, "logged_in": logged_in(d)}


def fill(pct, width):
    """How many cells of a meter that percentage fills -- one rounding rule for every bar."""
    return max(0, min(width, int(round((pct or 0) / 100.0 * width))))


def bar(pct, width=10):
    """How much of the window is spent, the same meter Claude Code's own statusline draws."""
    n = fill(pct, width)
    return "█" * n + "░" * (width - n)


def window(d, key):
    pct, t = reset_at(d, key)
    if pct is None:
        return "-"
    if t is None:
        return "%d%% used" % pct
    left = t - time.time()
    when = time.strftime("%H:%M" if time.strftime("%d-%m") == time.strftime("%d-%m", time.localtime(t))
                         else "%d-%m %H:%M", time.localtime(t))
    if left <= GRACE:
        return "%s    0%% used - window reset at %s, nothing measured since" % (bar(0), when)
    return "%s %4d%% used, resets %s (%s)" % (bar(pct), pct, when, hm(left))


def compact(d, key):
    pct, t = reset_at(d, key)
    if pct is None:
        return "-"
    if t is None:
        return "%d%%" % pct
    left = t - time.time()
    if left <= GRACE:
        return "%s    0%% new" % bar(0)
    return "%s %4d%% %s" % (bar(pct), pct, hm(left))
