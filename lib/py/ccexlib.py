"""Shared helpers for the ccex python modules.

The bash side exports CCEX_BASE and CCEX_ROOT so every module agrees on where
the live account and the parked ones live.
"""
import datetime, json, os, re, time

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

SEED_KEYS = ("hasCompletedOnboarding", "lastOnboardingVersion", "lastReleaseNotesSeen", "theme",
             "installMethod", "autoUpdates", "respectGitignore", "tipsHistory", "hasSeenTasksHint",
             "showExpandedTodos", "copyOnSelect", "migrationVersion", "hasIdeOnboardingBeenShown")


def seed_into(dst, src):
    """Copy the non-account config -- onboarding, theme, folder trust -- into a profile.

    Folder trust is the load-bearing part: `limits.probe` has to start claude in a directory
    this slot already trusts, or the TUI stops on the trust dialog and no number ever comes
    back. Nothing here is overwritten, so seeding an already-seeded profile changes nothing.
    """
    for k in SEED_KEYS:
        if k in src and k not in dst:
            dst[k] = src[k]
    proj = dst.setdefault("projects", {})
    for k, v in (src.get("projects") or {}).items():
        proj.setdefault(k, v)
    return len(proj)


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


def _ts(v):
    """A window boundary as epoch seconds, whichever way it was written.

    A statusline payload carries a whole-second epoch, so `record` renders it with no
    fraction; a probe lets Claude Code write its own, microseconds and all -- and the two
    land a quarter-second either side of a minute. Compared as strings, an account's own
    window reads as a different window.
    """
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return datetime.datetime.fromisoformat(v).timestamp()
    except (TypeError, ValueError):
        return None


def past_window(util, slack=120):
    """True when a payload names a window boundary that has already gone by.

    A window a session is really in has not reset yet, so its boundary is ahead of now. A
    boundary days behind is a session that made its last request under a different account
    and has re-rendered ever since without asking anyone -- statusline output costs no
    request, so nothing ever corrects it. Cheapest check there is, and it needs no history.
    """
    now = time.time()
    for v in (util or {}).values():
        t = _ts((v or {}).get("resets_at"))
        if t is not None and t < now - slack:
            return True
    return False


def foreign_window(prev, util, slack=120):
    """True when a payload names a boundary this account cannot have moved to yet.

    A window's boundary only advances once the old one has passed. So a report naming a
    different boundary while the one we last measured is still in the future did not come
    from this account: it is a session that has not caught up with a switch. Deciding that
    needs nothing but this account's own file -- no switch record rotation keeps
    overwriting, no other account's snapshot that a reset may have removed.

    There is deliberately no way out by capitulation. A refusal that eventually believes a
    payload it cannot verify is a refusal a persistent liar wins, and idle sessions repeat
    themselves for days. What breaks the deadlock instead is `limits.probe`, which asks the
    account itself.
    """
    # cm:edge protocol -> lib/py/limits.py — refusing every report freezes this account's
    # numbers, and rotation steers by them. limits.py and watch.py must probe a live account
    # whose snapshot has aged out, rather than trusting that an open session is a reporting one.
    now = time.time()
    known = prev.get("utilization") or {}
    for k, v in (util or {}).items():
        old = _ts((known.get(k) or {}).get("resets_at"))
        new = _ts((v or {}).get("resets_at"))
        if old is None or new is None or old <= now:
            continue
        if abs(new - old) > slack:
            return True
    return False


SWITCH = os.path.join(USAGE_DIR, ".switch.json")


def note_switch(email, util):
    """Remember which windows the account we are switching away from was reading.

    `foreign_window` decides from what the incoming account itself last measured, which is
    nothing at all the first time an account is used. That is exactly when a late render is
    most likely -- a switch just happened -- so the windows being left behind are written
    down, and recognised if they turn up under the new name.

    Reset times, not percentages: a lagging session re-renders every few seconds and its
    percentages drift, so matching on those misses everything after the first render. The
    boundary it carries stays the one the old account had until its next request.
    """
    try:
        os.makedirs(USAGE_DIR, exist_ok=True)
        save(SWITCH, {"at": int(time.time()), "email": email,
                      "bounds": {k: (util.get(k) or {}).get("resets_at")
                                 for k in ("five_hour", "seven_day")},
                      "five": (util.get("five_hour") or {}).get("utilization"),
                      "seven": (util.get("seven_day") or {}).get("utilization")})
    except OSError:
        pass


def last_api_reply(path, tail=1 << 18):
    """When this session last had a reply from the API, or None if it cannot be told.

    A statusline render costs no request, so a session's rate limits are exactly as old as
    its last reply -- and nothing the statusline hands over says which account answered it.
    The transcript does say when it arrived, and that is enough.

    Only main-thread assistant lines with a request behind them count: metadata lines carry
    no exchange, and a subagent's replies do not refresh what the statusline renders.
    """
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - tail))
            chunk = f.read().decode("utf-8", "ignore")
    except OSError:
        return None
    for line in reversed(chunk.splitlines()):
        if '"assistant"' not in line or '"requestId"' not in line:
            continue
        try:
            o = json.loads(line)
        except ValueError:
            continue                  # a tail can start mid-line; the next one up is whole
        if o.get("type") != "assistant" or o.get("isSidechain") or not o.get("timestamp"):
            continue
        try:
            return datetime.datetime.fromisoformat(o["timestamp"].replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def lagging_session(payload):
    """True when this session has not heard from the API since the last account switch.

    Provenance, where the two checks above only have coincidence to go on: numbers that
    reached a session before the switch were answered by the account we have since left,
    whatever they happen to look like.

    One switch time is all this needs, which is why `.switch.json` holding a single slot is
    no longer the weakness it was for `stale_report`: time is ordered, so a session that
    predates the newest switch predates every earlier one too.

    It abstains rather than guesses. No switch on record, or no readable transcript, and
    the boundary checks decide -- being unable to tell is never a reason to accept.
    """
    at = load(SWITCH).get("at")
    if not at:
        return False
    t = last_api_reply(payload.get("transcript_path") or "")
    return t is not None and t < at


def stale_report(util, window=600, slack=120):
    """True when these are the numbers the account we just switched away from had.

    Boundaries decide when both sides carry them, because they survive the drift; a
    payload rendered while a window has just rolled over carries none, and there the
    percentages are all there is to match on.
    """
    s = load(SWITCH)
    if not s or time.time() - (s.get("at") or 0) >= window:
        return False
    old = s.get("bounds") or {}
    shared = [k for k in old if _ts(old.get(k)) is not None and _ts((util.get(k) or {}).get("resets_at")) is not None]
    if shared:
        return all(abs(_ts(old[k]) - _ts(util[k]["resets_at"])) <= slack for k in shared)
    pct = [(util.get(k) or {}).get("utilization") for k in ("five_hour", "seven_day")]
    return any(p is not None for p in pct) and pct == [s.get("five"), s.get("seven")]


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
