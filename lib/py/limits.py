"""Report the 5-hour and weekly limits for one account or all of them.

Nothing here spends quota: the numbers come from a running session, from what was
last measured, or from the clock. Only the live account is ever asked directly.
"""
import datetime, json, os, pty, select, signal, sys, time

from ccexlib import (BASE, cfg_for, creds_for, email_for, hm, is_base,
                     load, logged_in, slots, snap_path, switched_at)

argv = sys.argv[1:]
quiet = "--quiet" in argv
every = "--all" in argv
force = "--force" in argv
tsv = "--tsv" in argv
js = "--json" in argv
nolaunch = "--no-launch" in argv
args = [a for a in argv if not a.startswith("-")]






def live_sessions(d):
    """PIDs of Claude Code sessions currently running as this account (Linux only)."""
    out = []
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
            cd = env.get(b"CLAUDE_CONFIG_DIR", b"").decode("utf8", "replace") or BASE
            if os.path.realpath(cd) != os.path.realpath(d):
                continue
            if os.path.getctime("/proc/" + pid) * 1000 < switched_at():
                continue      # started before the last switch, so it still holds the old account
            out.append(int(pid))
        except (OSError, ValueError):
            continue
    return out


def cached(d):
    """Freshest limits we have: a running session's statusline beats the on-disk cache."""
    cfg = load(cfg_for(d))
    c = cfg.get("cachedUsageUtilization") or {}
    if c.get("accountUuid") and c["accountUuid"] != (cfg.get("oauthAccount") or {}).get("accountUuid"):
        c = {}                     # left behind by whoever held this slot before
    best = {"fetchedAtMs": c.get("fetchedAtMs") or 0,
            "utilization": c.get("utilization") or {}, "source": "cache"}
    snap = load(snap_path(email_for(d)))
    if snap.get("startedAtMs", 0) < switched_at():
        snap = {}
    if (snap.get("fetchedAtMs") or 0) > best["fetchedAtMs"]:
        best = {"fetchedAtMs": snap["fetchedAtMs"], "utilization": snap.get("utilization") or {},
                "source": "session"}
    return best


def trusted_dir(cfg):
    for path, v in (load(cfg).get("projects") or {}).items():
        if isinstance(v, dict) and v.get("hasTrustDialogAccepted") and os.path.isdir(path):
            return path
    return None

def probe(d, timeout=50):
    """Launch the real `claude` TUI on this account, open /usage, quit. No inference, no cost."""
    cfg = cfg_for(d)
    before = cached(d).get("fetchedAtMs") or 0
    cwd = trusted_dir(cfg)
    if not cwd:
        return "untrusted"
    if not os.path.exists(creds_for(d)):
        return "nologin"
    pid, fd = pty.fork()
    if pid == 0:
        for k in list(os.environ):
            if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"):
                os.environ.pop(k, None)
        if is_base(d):
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        else:
            os.environ["CLAUDE_CONFIG_DIR"] = d
        os.environ.update(TERM="xterm-256color", COLUMNS="120", LINES="45")
        try:
            os.chdir(cwd)
            os.execvp("claude", ["claude", "--model", "claude-haiku-4-5-20251001"])
        except Exception:
            os._exit(127)
    start = time.time()
    sent, refreshed, quit_at, mtime, buf, ready_at, tries = set(), False, None, 0, b"", None, 0
    while time.time() - start < timeout:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf = (buf + chunk)[-8192:]
            except OSError:
                break
        el = time.time() - start
        if ready_at is None and (b"\xe2\x9d\xaf" in buf or b"shift+tab" in buf):
            ready_at = time.time()          # the prompt is up; the TUI is listening
        if not refreshed and ready_at and time.time() - ready_at > 1.5 and tries * 7 < el - 1:
            os.write(fd, b"\x1b/usage\r")  # esc first, so a retry never appends to a live prompt
            tries += 1
            sent.add("usage")
        if el > 20 and not refreshed and "nudge" not in sent:
            os.write(fd, b"\r"); sent.add("nudge")
        if not refreshed:
            try:
                m = os.stat(cfg).st_mtime
            except OSError:
                m = mtime
            if m != mtime:
                mtime = m
                refreshed = (cached(d).get("fetchedAtMs") or 0) > before
        if (refreshed or el > timeout - 6) and "quit" not in sent:
            os.write(fd, b"/exit\r"); sent.add("quit"); quit_at = time.time()
        if quit_at and time.time() - quit_at > 2:
            break
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig); time.sleep(0.3)
        except OSError:
            break
    try:
        os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    return "ok" if (cached(d).get("fetchedAtMs") or 0) > before else "timeout"

def reset_at(d, key):
    v = (cached(d)["utilization"] or {}).get(key)
    if not isinstance(v, dict) or v.get("utilization") is None:
        return None, None
    ra = v.get("resets_at")
    try:
        return v["utilization"], datetime.datetime.fromisoformat(ra).timestamp() if ra else None
    except (TypeError, ValueError):
        return v["utilization"], None

def window(d, key):
    pct, t = reset_at(d, key)
    if pct is None:
        return "-"
    if t is None:
        return "%d%% used" % pct
    left = t - time.time()
    when = time.strftime("%H:%M" if time.strftime("%d-%m") == time.strftime("%d-%m", time.localtime(t))
                         else "%d-%m %H:%M", time.localtime(t))
    if left <= 0:
        return "0%% used - window reset at %s, nothing measured since" % when
    return "%d%% used, resets %s (%s)" % (pct, when, hm(left))

def compact(d, key):
    pct, t = reset_at(d, key)
    if pct is None:
        return "-"
    if t is None:
        return "%d%%" % pct
    left = t - time.time()
    return "%d%% - %s" % (pct, hm(left)) if left > 0 else "0% (new)"

def still_counting(d):
    """True while some window we know about has not provably run out - i.e. old numbers still lie."""
    return any(pct is not None and (t is None or t > time.time())
               for pct, t in (reset_at(d, k) for k in ("five_hour", "seven_day")))

def age(d):
    c = cached(d)
    f, src = c.get("fetchedAtMs"), c.get("source")
    if not f:
        return "never checked"
    a = time.time() - f / 1000
    when = "just now" if a < 90 else "%s ago" % hm(a)
    return "%s, from the running session" % when if src == "session" else when

NOTE = {"untrusted": "no trusted project dir - launch `claude` once in one of your project folders first; showing cached numbers",
        "nologin": "not logged in",
        "timeout": "limits check timed out; showing cached numbers",
        "unhooked": "a session is open on this account, so nothing was launched. For live numbers put "
                    "`ccex record |` in front of your statusLine command (see `ccex --help`); "
                    "showing cached numbers"}

targets = []
if every:
    targets = slots()
elif not args:
    targets = [("default", BASE)]
else:
    for t in [a.lower() for a in args]:
        hit = [(n, d) for n, d in slots() if t in (n.lower(), email_for(d).lower())] or \
              [(n, d) for n, d in slots() if n.lower().startswith(t) or email_for(d).lower().startswith(t)]
        if not hit:
            sys.exit("ccex: no account matches '%s' (see: ccex ls)" % t)
        if len(hit) > 1:
            sys.exit("ccex: '%s' matches %s" % (t, ", ".join(n for n, _ in hit)))
        targets.append(hit[0])

rows, notes = [], []
for name, d in targets:
    have = cached(d)
    fresh = have["fetchedAtMs"] and time.time() - have["fetchedAtMs"] / 1000 < 300
    if have["source"] == "session" and live_sessions(d):
        st = "ok"                      # a session is open on this account and reporting; touch nothing
    elif fresh and not force:
        st = "ok"                      # someone checked moments ago; no reason to ask again
    elif have["fetchedAtMs"] and not still_counting(d) and not force:
        st = "ok"                      # every window it knew about has since reset, so 0% is certain
    elif not is_base(d):
        st = "parked"                  # not the account you are running; leave it alone until it is
    elif live_sessions(d) and not force:
        st = "unhooked"                # don't start a second session behind a running one
    elif nolaunch:
        st = "ok"                      # caller would rather have old numbers than a new session
    else:
        st = probe(d)                  # last resort: open the TUI just long enough to read /usage
    if st not in ("ok", "parked"):
        notes.append("ccex: %s: %s" % (name, NOTE.get(st, st)))
    rows.append((name, email_for(d), window(d, "five_hour"), window(d, "seven_day"),
                 "live" if have["source"] == "session" and live_sessions(d) else age(d)))

if js:
    def eff(d, key):
        pct, t = reset_at(d, key)
        if pct is None:
            return None, None, False
        if t and t <= time.time():
            return 0, t, True          # window rolled over: zero, and we know it without asking
        return pct, t, False
    out = []
    for name, d in targets:
        five, ft, fi = eff(d, "five_hour")
        seven, st_, si = eff(d, "seven_day")
        c = cached(d)
        out.append({"name": name, "email": email_for(d), "five": five, "seven": seven,
                    "five_resets": ft, "seven_resets": st_, "inferred": fi or si,
                    "age_s": int(time.time() - c["fetchedAtMs"] / 1000) if c["fetchedAtMs"] else None,
                    "live": c["source"] == "session" and bool(live_sessions(d)),
                    "logged_in": logged_in(d)})
    print(json.dumps(out))
elif tsv:
    for name, d in targets:
        print("\t".join([name, compact(d, "five_hour"), compact(d, "seven_day"),
                         "live" if cached(d)["source"] == "session" and live_sessions(d) else age(d)]))
elif quiet and len(rows) == 1:
    name, email, five, seven, a = rows[0]
    print("ccex: limits for %s (%s)" % (email, "live, from the running session" if a == "live" else "checked " + a))
    print("        5h      %s" % five)
    print("        weekly  %s" % seven)
else:
    print("%-20s %-30s %-31s %-38s %s" % ("ACCOUNT", "EMAIL", "5-HOUR", "WEEKLY", "CHECKED"))
    for name, email, five, seven, a in rows:
        mark = "*" if name == "default" else " "
        print("%s%-19s %-30s %-31s %-38s %s" % (mark, name, email, five, seven, a))
for n in notes:
    print(n, file=sys.stderr)
