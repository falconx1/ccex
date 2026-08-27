"""Statusline filter: note the limits Claude Code renders, so nothing has to be launched to learn them."""
import datetime, json, os, sys, time

import burn
from ccexlib import (BASE, USAGE_DIR, cfg_for, foreign_window, lagging_session, load,
                     past_window, save, snap_path, stale_report)

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
    out = snap_path(email)
    prev = load(out)
    # This session has not caught up with a switch yet: these are the previous account's
    # numbers, and this account must not be credited with them. One bad boundary condemns
    # the whole payload -- being behind is a fact about the session, so every window it
    # reports came out of the same overtaken response.
    if (past_window(util) or foreign_window(prev, util) or lagging_session(payload)
            or stale_report(util)):
        raise SystemExit
    os.makedirs(USAGE_DIR, exist_ok=True)
    # a payload missing a window must not erase what we had
    util = {**(prev.get("utilization") or {}), **util}
    save(out, {"email": email, "fetchedAtMs": int(time.time() * 1000), "utilization": util,
               "sessionId": payload.get("session_id")}, unique=True)
    # A render is the only moment anyone sees a fresh number, so it is where the burn
    # rate behind `ccex ls -w`'s "switch in ~2h" comes from.
    burn.note(email, *[(util.get(k) or {}).get("utilization") for k in ("five_hour", "seven_day")])
except Exception:
    pass
