"""Report the 5-hour and weekly limits for one account or all of them.

Nothing here spends quota: the numbers come from a running session, from what was
last measured, or from the clock. Only the live account is ever asked directly.
"""
import json, os, pty, select, signal, sys, time

from ccexlib import (BASE, caps, cfg_for, creds_for, email_for, expand, held, held_auto,
                     id_for, is_base, load, slots)
from usage import (account_json, age, cached, compact, live_sessions, still_counting,
                   window)

argv = sys.argv[1:]
quiet = "--quiet" in argv
every = "--all" in argv
force = "--force" in argv
tsv = "--tsv" in argv
js = "--json" in argv
nolaunch = "--no-launch" in argv

max_age, args, skip = None, [], False
for i, a in enumerate(argv):
    if skip:
        if not a.isdigit():
            sys.exit("ccex: --max-age wants a number of seconds, got '%s'" % a)
        max_age = int(a)
        skip = False
    elif a == "--max-age":     # seconds; numbers older than this are worth a real check even
        # under --no-launch, and 0 turns that off rather than meaning "everything is stale"
        skip = True
    elif not a.startswith("-"):
        args.append(a)
if skip:
    sys.exit("ccex: --max-age wants a number of seconds")


def trusted_dir(cfg):
    for path, v in (load(cfg).get("projects") or {}).items():
        if isinstance(v, dict) and v.get("hasTrustDialogAccepted") and os.path.isdir(path):
            return path
    return None

def probe(d, timeout=int(os.environ.get("CCEX_PROBE_TIMEOUT") or 150)):
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
        if cfg == os.path.join(d, ".claude.json"):
            os.environ["CLAUDE_CONFIG_DIR"] = d
        else:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
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
    for t in [expand(a).lower() for a in args]:
        hit = [(n, d) for n, d in slots() if t in (n.lower(), email_for(d).lower())] or \
              [(n, d) for n, d in slots() if n.lower().startswith(t) or email_for(d).lower().startswith(t)]
        if not hit:
            sys.exit("ccex: no account matches '%s' (see: ccex ls)" % t)
        if len(hit) > 1:
            sys.exit("ccex: '%s' matches %s" % (t, ", ".join(n for n, _ in hit)))
        targets.append(hit[0])

rows, notes = [], []


def stalest_parked():
    """The one parked account this run may measure, or None.

    Rotation picks from what it can see, and nothing reports for an account no session is
    running -- so without this a freshly added account stays invisible for good. One per
    run, stalest first: each probe is a real session, and `ccex ls` over eleven accounts
    must not become eleven of them. Repeated runs fill the pool in, oldest first.
    """
    if not max_age:
        return None
    old = [(cached(d)["fetchedAtMs"] or 0, d) for _, d in targets if not is_base(d)]
    old = [(ms, d) for ms, d in old if not ms or time.time() - ms / 1000 > max_age]
    return min(old)[1] if old else None


measure = stalest_parked()

for name, d in targets:
    have = cached(d)
    age_s = time.time() - have["fetchedAtMs"] / 1000 if have["fetchedAtMs"] else None
    fresh = age_s is not None and age_s < 300
    too_old = bool(max_age) and (age_s is None or age_s > max_age)   # 0 means never
    if have["source"] == "session" and live_sessions(d) and not force:
        st = "ok"                      # a session is open on this account and reporting; touch nothing
    elif fresh and not force:
        st = "ok"                      # someone checked moments ago; no reason to ask again
    elif have["fetchedAtMs"] and not still_counting(d) and not force:
        st = "ok"                      # every window it knew about has since reset, so 0% is certain
    elif d is measure:
        st = probe(d)                  # nothing reports for a parked account; go and look
    elif not is_base(d):
        st = "parked"                  # not the account you are running; leave it alone until it is
    elif live_sessions(d) and not force:
        st = "unhooked"                # never start a second session behind a running one
    elif too_old:
        st = probe(d)                  # nothing is reporting and the numbers have aged out
    elif nolaunch and not force:
        st = "ok"                      # caller would rather have old numbers than a new session
    else:
        st = probe(d)                  # last resort: open the TUI just long enough to read /usage
    if st not in ("ok", "parked"):
        notes.append("ccex: %s: %s" % (name, NOTE.get(st, st)))
    rows.append((name, email_for(d), window(d, "five_hour"), window(d, "seven_day"),
                 "live" if have["source"] == "session" and live_sessions(d) else age(d)))

if js:
    print(json.dumps([account_json(name, d) for name, d in targets]))
elif tsv:
    for name, d in targets:
        c5, c7 = caps(d)
        # One flags field, never empty: IFS=$'\t' collapses runs of tabs, so an empty
        # column would shift every field after it in the shell that reads this.
        flags = ",".join(f for f in ("auto" if held_auto(d) else "", "held" if held(d) else "",
                                     "cap" if (c5 or c7) else "") if f)
        print("\t".join([name, str(id_for(d) or "-"),
                         compact(d, "five_hour").ljust(22), compact(d, "seven_day").ljust(26),
                         "live" if cached(d)["source"] == "session" and live_sessions(d) else age(d),
                         flags or "-",
                         "%s/%s" % (c5 or "-", c7 or "-") if (c5 or c7) else "-"]))
elif quiet and len(rows) == 1:
    name, email, five, seven, a = rows[0]
    print("ccex: limits for %s (%s)" % (email, a if a == "live" else "checked " + a))
    print("        5h      %s" % five)
    print("        weekly  %s" % seven)
    c5, c7 = caps(targets[0][1])
    if c5 or c7:                  # only worth a line when this account sets its own
        print("        cap     %s (its own; uncapped windows follow --at for 5h (default 90), 99%% for the week)" %
              " / ".join("%s %d%%" % (w, v) for w, v in (("5h", c5), ("weekly", c7)) if v))
else:
    print("%-20s %-30s %-44s %-48s %s" % ("ACCOUNT", "EMAIL", "5-HOUR", "WEEKLY", "CHECKED"))
    for name, email, five, seven, a in rows:
        mark = "*" if name == "default" else " "
        print("%s%-19s %-30s %-44s %-48s %s" % (mark, name, email, five, seven, a))
for n in notes:
    print(n, file=sys.stderr)
