"""Shared helpers for the ccex python modules.

The bash side exports CCEX_BASE and CCEX_ROOT so every module agrees on where
the live account and the parked ones live.
"""
import datetime, json, os, re, time

BASE = os.environ.get("CCEX_BASE") or os.path.expanduser("~/.claude")
ROOT = os.environ.get("CCEX_ROOT") or os.path.expanduser("~/.claude-profiles")
USAGE_DIR = os.path.join(ROOT, ".usage")
STEP = os.path.join(USAGE_DIR, ".step")       # what a switch is doing, while it is doing it
LOG = os.path.join(USAGE_DIR, "rotate.log")   # and afterwards, whether it switched or not
DAEMON = os.path.join(USAGE_DIR, "daemon.json")   # what the background rotator is running at
STEPS = 5                                     # lines of trail the view has room for


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

    Folder trust is the load-bearing part: probe() has to start claude in a directory this
    slot already trusts, or the TUI stops on the trust dialog and no number comes back.
    Nothing here is overwritten, so seeding an already-seeded profile changes nothing.
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


def running_at(default):
    """The threshold rotation is really moving off at, or `default` when nothing is running.

    Reading 90% off the built-in default while the daemon moves off at 80% would be reading
    the wrong number -- and, for anything that warns, warning about a switch that already
    happened. `ccex rotate --stop` deletes the file, so the default is what is left.
    """
    at = fresh(DAEMON).get("at")
    return int(at) if str(at or "").isdigit() else default


def is_base(d):
    global _base_real
    if _base_real is None:
        _base_real = os.path.realpath(BASE)      # asked once per account per tick; it cannot move
    return os.path.realpath(d) == _base_real


def cfg_for(d):
    """Where this slot keeps its config.

    The live slot's is ~/.claude.json only while CLAUDE_CONFIG_DIR is unset. Export it -- as a
    multi-account shell setup does -- and Claude Code writes $CLAUDE_CONFIG_DIR/.claude.json
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
ANCHORS = os.path.join(ROOT, ".anchors.json")
WEEK = 7 * 86400
KEEP_SWITCHES = 20      # rotation can move three times in as many minutes
SWITCH_WINDOW = 1800    # how long a session may go on carrying the account we left


def epoch(resets_at):
    """A reset time as seconds, whether it arrived as an ISO string or already as a number."""
    if isinstance(resets_at, (int, float)):
        return float(resets_at)
    try:
        return datetime.datetime.fromisoformat(resets_at).timestamp()
    except (TypeError, ValueError):
        return None


def week_point(resets_at):
    """Where in the week an account's weekly window comes back, if we can tell.

    A weekly window resets at the same point in every week for the same account, seven days
    on, so this one number survives every rollover -- which makes it the only thing in a
    statusline payload that says which account the payload is about. Claude Code sends the
    numbers of whatever account the session is signed in as and never says which that is.
    """
    t = epoch(resets_at)
    return None if t is None else t % WEEK


def same_point(a, b, slack=900):
    """Two week points, allowing for the quarter hour the reported reset time drifts by."""
    if a is None or b is None:
        return False
    d = abs(a - b) % WEEK
    return min(d, WEEK - d) <= slack


_anchors = (0.0, {})


def anchors(max_age=2.0):
    """email -> its week point, from every source that names the account the numbers came from.

    Claude Code's own `cachedUsageUtilization` is the good one: it carries the accountUuid
    it was fetched for, so it cannot be mistaken for another account's. Departures fill in
    the accounts it has not written yet, and `.anchors.json` remembers what earlier renders
    established, so an account stays recognisable once anything has measured it.
    """
    global _anchors
    if time.time() - _anchors[0] <= max_age:
        return _anchors[1]
    m = {}
    for e in departures():
        p = week_point(((e.get("utilization") or {}).get("seven_day") or {}).get("resets_at"))
        if p is not None and e.get("email"):
            m[e["email"]] = p
    m.update(fresh(ANCHORS))
    for _, d in slots():
        cfg = fresh(cfg_for(d), CFG_KEYS)
        c = cfg.get("cachedUsageUtilization") or {}
        acc = cfg.get("oauthAccount") or {}
        if not c.get("accountUuid") or c["accountUuid"] != acc.get("accountUuid"):
            continue                    # left behind by whoever held this slot before
        p = week_point(((c.get("utilization") or {}).get("seven_day") or {}).get("resets_at"))
        if p is not None and acc.get("emailAddress"):
            m[acc["emailAddress"]] = p
    _anchors = (time.time(), m)
    return m


def learn_anchor(email, resets_at):
    """Remember where this account's week resets, so its numbers stay attributable to it."""
    global _anchors
    p = week_point(resets_at)
    if p is None:
        return
    m = load(ANCHORS)
    if same_point(m.get(email), p):
        return                          # nothing new: do not rewrite the file on every render
    m[email] = p
    try:
        save(ANCHORS, m)
        _anchors = (0.0, {})
    except OSError:
        pass


def note_switch(email, util):
    """Remember what the account we are switching away from was reading.

    A session that renders just after a switch still carries the old account's limits --
    Claude Code only learns the new ones on its next request -- while `.claude.json`
    already names the new account. Filing those numbers would credit an hour of someone
    else's usage to the account you just moved to, and the burn rate would follow. So the
    numbers we are leaving behind are written down, and recognised if they turn up again.
    """
    try:
        os.makedirs(USAGE_DIR, exist_ok=True)
        now = int(time.time())
        log = [e for e in departures() if now - (e.get("at") or 0) < SWITCH_WINDOW]
        log.append({"at": now, "email": email, "utilization": util or {}})
        save(SWITCH, {"departures": log[-KEEP_SWITCHES:]})
    except OSError:
        pass


def departures():
    """Every account we have switched away from lately, oldest first.

    One slot was not enough. Rotation moves several times in a few minutes, and each move
    forgot the one before it -- so a session still carrying the numbers of the account we
    left two switches ago went unrecognised, and those numbers were filed against whoever
    happened to be live by then.
    """
    s = load(SWITCH)
    if isinstance(s.get("departures"), list):
        return s["departures"]
    if s.get("email"):              # the single record earlier versions wrote
        return [{"at": s.get("at"), "email": s["email"],
                 "utilization": {"five_hour": {"utilization": s.get("five")},
                                 "seven_day": {"utilization": s.get("seven")}}}]
    return []


def same_reading(mine, was):
    """One window of a payload against the one we wrote down as we left: the same account's.

    The reset time is the better half of this. It does not move while the window is open, so
    a session lagging an hour behind a switch still carries the exact one it left with, where
    the percentage has climbed away from it. Percentages are the fallback, and only ever to
    within a point: a render sends whole numbers, what Claude Code caches holds floats, and
    56.99999999999999 is not 57.
    """
    ra, rb = epoch(mine.get("resets_at")), epoch(was.get("resets_at"))
    if ra is not None and rb is not None:
        return abs(ra - rb) <= 60
    a, b = mine.get("utilization"), was.get("utilization")
    return a is not None and b is not None and abs(a - b) < 1


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
        return epoch(o["timestamp"].replace("Z", "+00:00"))
    return None


def lagging_session(payload):
    """True when this session has not heard from the API since the last account switch.

    Provenance, where the week point only has coincidence to go on: numbers that reached a
    session before the switch were answered by the account we have since left, whatever they
    happen to look like. It catches a late render whose window boundary is missing, or whose
    week point happens to collide with the account now live.

    Only the newest departure matters. Time is ordered, so a session that predates the most
    recent switch predates every earlier one too.

    It abstains rather than guesses. No switch on record, or no readable transcript, and the
    week point decides on its own -- being unable to tell is never a reason to accept.
    """
    at = max((e.get("at") or 0) for e in departures()) if departures() else 0
    if not at:
        return False
    t = last_api_reply((payload or {}).get("transcript_path") or "")
    return t is not None and t < at


def foreign_report(email, util, window=SWITCH_WINDOW):
    """True when this payload is another account's numbers rather than `email`'s.

    Two ways to tell one. The weekly window's week point belongs to one account, so a
    payload resetting where another account we know resets is that account's, whatever the
    percentages have moved to since. Failing that -- an account nothing has measured yet
    has no week point -- a departure from the last half hour is recognised by its numbers.

    Every window the payload carries has to match that departure for it to count as one:
    two fresh accounts sitting at 0% for the hour agree on that number without being the
    same account, and skipping a real reading is as wrong as filing a foreign one.
    """
    point = week_point((util.get("seven_day") or {}).get("resets_at"))
    if point is not None:
        known = anchors()
        if same_point(known.get(email), point):
            return False               # our own week; there is nothing else it could be
        if any(same_point(p, point) for e, p in known.items() if e != email):
            return True
    now = time.time()
    for e in departures():
        if e.get("email") == email or now - (e.get("at") or 0) >= window:
            continue
        left = e.get("utilization") or {}
        pairs = [(util[k] or {}, left.get(k) or {}) for k in ("five_hour", "seven_day") if util.get(k)]
        if pairs and all(same_reading(m, w) for m, w in pairs):
            return True
    return False


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


def step(msg, log=True):
    """Add a line to what rotation is doing, for the live view to show. None clears it.

    A switch that asks three accounts spends most of a minute doing it, and until it is over
    the only thing the view can honestly say is "now" -- which looks identical to a view that
    has stopped. One line per thing done, in order, so the view can print the trail without
    parsing anything.

    The same lines go to rotate.log, because `lib/background.sh` only records a tick that
    changed the live account -- so a tick that spent three sessions asking and then stayed
    put left no trace of having asked at all.
    """
    try:
        if not msg:
            if os.path.exists(STEP):
                os.remove(STEP)
            return
        os.makedirs(USAGE_DIR, exist_ok=True)
        try:
            with open(STEP) as f:
                had = [l for l in f.read().splitlines() if l.strip()]
        except OSError:
            had = []
        with open(STEP, "w") as f:
            f.write("\n".join((had + [msg])[-STEPS:]) + "\n")
        if log:
            with open(LOG, "a") as f:      # O_APPEND, so the tick's own line cannot interleave
                f.write("%s  ccex: %s\n" % (
                    datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg))
    except OSError:
        pass

