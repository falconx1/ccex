"""Statusline filter: note the limits Claude Code renders, so nothing has to be launched to learn them."""
import datetime, json, os, sys, time

import burn
from ccexlib import BASE, USAGE_DIR, cfg_for, foreign_report, learn_anchor, save, snap_path

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
        if v.get("used_percentage") is None:
            continue                  # reported but empty: keep whatever we already had
        ra = v.get("resets_at")
        util[k] = {"utilization": v.get("used_percentage"),
                   "resets_at": datetime.datetime.fromtimestamp(ra, datetime.timezone.utc).isoformat() if ra else None}
    # This session has not caught up with a switch yet: these are the previous account's
    # numbers, and this account must not be credited with them.
    if foreign_report(email, util):
        raise SystemExit
    learn_anchor(email, (util.get("seven_day") or {}).get("resets_at"))
    os.makedirs(USAGE_DIR, exist_ok=True)
    out = snap_path(email)
    try:                          # a payload missing a window must not erase what we had
        with open(out) as f:
            had = json.load(f).get("utilization") or {}
        if not foreign_report(email, had, window=0):   # unless what we had was never ours
            util = {**had, **util}
    except (OSError, ValueError):
        pass
    save(out, {"email": email, "fetchedAtMs": int(time.time() * 1000), "utilization": util,
               "sessionId": payload.get("session_id")}, unique=True)
    # A render is the only moment anyone sees a fresh number, so it is where the burn
    # rate behind `ccex ls -w`'s "switch in ~2h" comes from.
    burn.note(email, *[(util.get(k) or {}).get("utilization") for k in ("five_hour", "seven_day")])
except Exception:
    pass
