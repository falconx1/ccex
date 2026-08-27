"""Shared helpers for the ccex python modules.

The bash side exports CCEX_BASE and CCEX_ROOT so every module agrees on where
the live account and the parked ones live.
"""
import json, os, re, time

BASE = os.environ.get("CCEX_BASE") or os.path.expanduser("~/.claude")
ROOT = os.environ.get("CCEX_ROOT") or os.path.expanduser("~/.claude-profiles")
USAGE_DIR = os.path.join(ROOT, ".usage")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


_cached = {}
CFG_KEYS = ("oauthAccount", "cachedUsageUtilization")   # all anyone reads from a .claude.json


def fresh(path, keep=None):
    """load(), but only re-parsed when the file has actually changed.

    A long-lived reader (`ccex ls -w`) re-reads the same handful of files every few
    seconds, and a `.claude.json` is most of a megabyte of project history. One stat is
    the whole cost of finding out there is nothing new in it -- and `keep` names the
    top-level keys worth remembering, so a resident process holds a few hundred bytes of
    each rather than the whole document.
    """
    try:
        st = os.stat(path)
    except OSError:
        _cached.pop((path, keep), None)
        return {}
    key = (st.st_mtime_ns, st.st_size)
    hit = _cached.get((path, keep))
    if hit and hit[0] == key:
        return hit[1]
    data = load(path)
    if keep:
        data = {k: data[k] for k in keep if k in data}
    _cached[(path, keep)] = (key, data)
    return data


def save(path, obj, unique=False):
    """Write JSON where a reader can only ever see the old file or the new one.

    `unique` when two processes may write the same file at once -- they then race on the
    rename rather than on one shared temporary.
    """
    tmp = "%s.ccex.tmp%s" % (path, ".%d" % os.getpid() if unique else "")
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


_base_real = None


def is_base(d):
    global _base_real
    if _base_real is None:
        _base_real = os.path.realpath(BASE)      # asked once per account per tick; it cannot move
    return os.path.realpath(d) == _base_real


def cfg_for(d):
    """Where this slot keeps its config.

    The live slot's is ~/.claude.json only while CLAUDE_CONFIG_DIR is unset. Export it —
    as a multi-account shell setup does — and Claude Code writes $CLAUDE_CONFIG_DIR/.claude.json
    instead, leaving ~/.claude.json a stale file no session reads. Preferring the inner one
    when it exists is what keeps `use` parking under the account that was really live, rather
    than under whatever name that stale file last held.
    """
    if not is_base(d):
        return os.path.join(d, ".claude.json")
    inner = os.path.join(BASE, ".claude.json")
    return inner if os.path.exists(inner) else os.path.expanduser("~/.claude.json")


def creds_for(d):
    return os.path.join(d, ".credentials.json")


def email_for(d):
    return (fresh(cfg_for(d), CFG_KEYS).get("oauthAccount") or {}).get("emailAddress") or ""


def logged_in(d):
    return "claudeAiOauth" in fresh(creds_for(d))


def slots():
    """(name, dir) for the live account and every parked one, live first.

    A directory with no login left in it is leftover session state, not an account.
    """
    out = [("default", BASE)]
    if os.path.isdir(ROOT):
        for name in sorted(os.listdir(ROOT)):
            d = os.path.join(ROOT, name)
            if not name.startswith(".") and os.path.isdir(d) and logged_in(d):
                out.append((name, d))
    return out


def snap_path(email):
    return os.path.join(USAGE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", email.lower()) + ".json")


SWITCH = os.path.join(USAGE_DIR, ".switch.json")


def note_switch(email, five, seven):
    """Remember what the account we are switching away from was reading.

    A session that renders just after a switch still carries the old account's limits --
    Claude Code only learns the new ones on its next request -- while `.claude.json`
    already names the new account. Filing those numbers would credit an hour of someone
    else's usage to the account you just moved to, and the burn rate would follow. So the
    numbers we are leaving behind are written down, and recognised if they turn up again.
    """
    try:
        os.makedirs(USAGE_DIR, exist_ok=True)
        save(SWITCH, {"at": int(time.time()), "email": email, "five": five, "seven": seven})
    except OSError:
        pass


def stale_report(five, seven, window=600):
    """True when these are the numbers the account we just switched away from had."""
    s = load(SWITCH)
    if not s or (five is None and seven is None):
        return False
    return time.time() - (s.get("at") or 0) < window and \
        (five, seven) == (s.get("five"), s.get("seven"))


IDS = os.path.join(ROOT, ".ids.json")
POOL = os.path.join(ROOT, ".pool.json")
CAPS = os.path.join(ROOT, ".caps.json")


def held(d):
    """True when this account is off the rotation list, whether you took it off or rotation did."""
    return bool(fresh(POOL).get(email_for(d)))


def held_auto(d):
    """Why rotation retired this account itself, if it did -- `ccex pool in` is the way back."""
    v = fresh(POOL).get(email_for(d))
    return v.get("auto") if isinstance(v, dict) else None


def hold_auto(email, why):
    """Retire an account that has spent its week. It stays out until you put it back.

    A 5-hour window refills while you work, so running one down is ordinary rotation. A
    week does not: an account at the end of its week is no use again for days, and coming
    back every few seconds to rediscover that is noise. So rotation takes it off the list
    and leaves bringing it back to you.
    """
    m = load(POOL)
    if m.get(email):
        return False                  # already out, by your hand or an earlier retirement
    m[email] = {"auto": why, "since": time.strftime("%F %T")}
    save(POOL, m)
    return True


def caps(d):
    """This account's own out-of-room percentages, per window, or None where it has none.

    A cap is how far you are willing to let one account be spent, whatever `--at` says:
    lower to keep room in reserve on it, higher to run it down before moving on. Unset
    windows fall back to --at, so an account nobody has capped behaves exactly as before.
    """
    c = fresh(CAPS).get(email_for(d)) or {}
    return c.get("five_hour"), c.get("seven_day")


def ids():
    """A small stable integer per account, so `ccex use 2` means the same account tomorrow.

    Numbers are keyed to the email, not to position, so rotating or adding an account
    never renumbers the others, and the lowest free number goes to each new account. The
    map is read through `fresh`, not remembered: `ccex ls -w` runs for days, and an account
    added while it is up has to get a number like any other.
    """
    m = fresh(IDS)
    used, new = set(m.values()), {}
    for _, d in slots():
        e = email_for(d)
        if e and e not in m and e not in new:
            n = 1
            while n in used:
                n += 1
            new[e] = n
            used.add(n)
    if not new:
        return m
    m = {**m, **new}                    # never mutate what `fresh` handed back
    try:
        save(IDS, m)                    # `ccex rm` is what releases one again
    except OSError:
        pass
    return m


def id_for(d):
    e = email_for(d)
    known = fresh(IDS)                  # the common case: one stat, no scan of the slots
    return known[e] if e in known else ids().get(e)


def expand(target):
    """Turn a number into the email it stands for; anything else is passed through."""
    if target.isdigit():
        for email, n in ids().items():
            if n == int(target):
                return email
    return target


def canon(email):
    return re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-") or "account"


def hm(sec):
    sec = int(sec)
    if sec >= 86400:
        return "%dd %dh%02dm" % (sec // 86400, sec % 86400 // 3600, sec % 3600 // 60)
    return "%dh%02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm" % (sec // 60)
