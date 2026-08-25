"""Statusline filter: note the limits Claude Code renders, so nothing has to be launched to learn them."""
import datetime, json, os, sys, time

from ccexlib import BASE, USAGE_DIR, cfg_for, snap_path, switched_at

raw = sys.stdin.read()
try:
    payload = json.loads(raw)
    rl = payload.get("rate_limits") or {}
    cfg = cfg_for(os.environ.get("CLAUDE_CONFIG_DIR") or BASE)
    with open(cfg) as f:
        email = (json.load(f).get("oauthAccount") or {}).get("emailAddress")
    if not (email and rl):
        raise SystemExit
    util = {}
    for k in ("five_hour", "seven_day"):
        v = rl.get(k)
        if not isinstance(v, dict):
            continue
        ra = v.get("resets_at")
        util[k] = {"utilization": v.get("used_percentage"),
                   "resets_at": datetime.datetime.fromtimestamp(ra, datetime.timezone.utc).isoformat() if ra else None}
    started, pid = None, os.getppid()             # a session predating a switch is not this account
    for _ in range(4):                            # statusline runs under the session; walk up to it
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as f:
                argv = f.read().split(b"\0")
            if argv and os.path.basename(argv[0].decode("utf8", "replace")) == "claude":
                started = int(os.path.getctime("/proc/%d" % pid) * 1000)
                break
            with open("/proc/%d/stat" % pid) as f:
                pid = int(f.read().split(") ", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    if started is None:                          # no /proc: the transcript's age is the best we have
        try:
            started = int(os.path.getctime(payload.get("transcript_path") or "") * 1000)
        except OSError:
            started = 0
    if started < switched_at():
        raise SystemExit          # older than the last switch: these numbers are the old account's
    os.makedirs(USAGE_DIR, exist_ok=True)
    out = snap_path(email)
    tmp = out + ".tmp.%d" % os.getpid()
    with open(tmp, "w") as f:
        json.dump({"email": email, "fetchedAtMs": int(time.time() * 1000), "utilization": util,
                   "sessionId": payload.get("session_id"), "startedAtMs": started}, f)
    os.replace(tmp, out)
except Exception:
    pass
