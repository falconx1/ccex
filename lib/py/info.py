"""One `ccex ls` row: who the account is, and how long its two OAuth clocks have left."""
import re, sys, time

from ccexlib import cfg_for, creds_for, load

d = sys.argv[1]
account = load(cfg_for(d)).get("oauthAccount") or {}
email = account.get("emailAddress") or ""
tier = re.sub(r"^(default_)?claude_", "", account.get("userRateLimitTier") or "")
oauth = load(creds_for(d)).get("claudeAiOauth") or {}
exp, rexp = oauth.get("expiresAt"), oauth.get("refreshTokenExpiresAt")
rleft = rexp / 1000 - time.time() if rexp else None
if not exp:
    state = "NOT LOGGED IN"
else:
    # How many hours are left on an access token is nobody's business: it renews itself.
    state = "active" if exp / 1000 > time.time() else "stale"
if rexp:
    rstate = time.strftime("%d-%m", time.localtime(rexp / 1000)) if rleft > 0 else "expired"
elif exp:
    rstate = "n/a"
else:
    rstate = "-"
print("\t".join([email or "-", tier or "-", state, rstate]))
