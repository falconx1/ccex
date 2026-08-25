"""Hand the live ~/.claude slot over to a parked account, and park the one that was there."""
import os, shutil, sys, time

from ccexlib import BASE, ROOT, canon, cfg_for, creds_for, email_for, expand, load, logged_in, save

target = expand(sys.argv[1])
dry = "--dry-run" in sys.argv[2:] or "-n" in sys.argv[2:]

def slot(d):
    "credential path, config path, email"
    return creds_for(d), cfg_for(d), email_for(d)

live_cred, live_cfg, live_email = slot(BASE)
if "claudeAiOauth" not in load(live_cred):
    sys.exit("ccex: no account is logged in right now; use `ccex add <name>`")

parked = {}
if os.path.isdir(ROOT):
    for name in sorted(os.listdir(ROOT)):
        d = os.path.join(ROOT, name)
        if name.startswith(".") or not os.path.isdir(d):
            continue
        cred, cfg, email = slot(d)
        if "claudeAiOauth" in load(cred):
            parked[name] = (d, email)

t = target.lower()
if t in ("default", "live", "active"):
    sys.exit("ccex: 'default' is whichever account is live; name the account you want")
hits = [n for n, (d, e) in parked.items() if t in (n.lower(), e.lower())] or \
       [n for n, (d, e) in parked.items() if e.lower().startswith(t) or n.lower().startswith(t)]
if not hits:
    if t in (live_email.lower(), canon(live_email)) or live_email.lower().startswith(t):
        print("ccex: %s is already live" % (live_email or "that account"))
        sys.exit(0)
    sys.exit("ccex: no parked account matches '%s' (see: ccex ls)" % target)
if len(set(hits)) > 1:
    sys.exit("ccex: '%s' matches %s" % (target, ", ".join(sorted(set(hits)))))

src_name = hits[0]
src_dir, src_email = parked[src_name]
def taken(d):
    """Someone else's login is in here, and overwriting it would need a fresh browser sign-in."""
    if os.path.realpath(d) == os.path.realpath(src_dir):
        return True
    return logged_in(d) and email_for(d).lower() != (live_email or "").lower()

base_name = canon(live_email) if live_email else "previous"
park_name, n = base_name, 1
while taken(os.path.join(ROOT, park_name)):
    n += 1
    park_name = "%s-%d" % (base_name, n)
park_dir = os.path.join(ROOT, park_name)

print("ccex: %s -> parked as '%s'; %s -> live" % (live_email or "current", park_name, src_email))
if dry:
    print("ccex: dry run, nothing written")
    sys.exit(0)

bak = os.path.join(ROOT, ".backups", time.strftime("%Y%m%d-%H%M%S"))
os.makedirs(bak, exist_ok=True)
src_cred, src_cfg, _ = slot(src_dir)
for tag, path in (("live.credentials.json", live_cred), ("live.claude.json", live_cfg),
                  ("incoming.credentials.json", src_cred), ("incoming.claude.json", src_cfg)):
    if os.path.exists(path):
        shutil.copy2(path, os.path.join(bak, tag))

os.makedirs(park_dir, exist_ok=True)
lc, sc = load(live_cred), load(src_cred)
lcfg, scfg = load(live_cfg), load(src_cfg)

pk_cred = os.path.join(park_dir, ".credentials.json")
pk_cfg = os.path.join(park_dir, ".claude.json")
pk = load(pk_cred)
pk["claudeAiOauth"] = lc["claudeAiOauth"]
pkcfg = load(pk_cfg)
for k in ("oauthAccount", "userID", "cachedUsageUtilization"):
    if k in lcfg:
        pkcfg[k] = lcfg[k]
save(pk_cred, pk)
save(pk_cfg, pkcfg)

lc["claudeAiOauth"] = sc["claudeAiOauth"]
for k in ("oauthAccount", "userID", "cachedUsageUtilization"):
    if k in scfg:
        lcfg[k] = scfg[k]
    else:
        lcfg.pop(k, None)
save(live_cred, lc)
save(live_cfg, lcfg)

# the source slot handed its login over, so it must not keep a copy: one account, one slot
if os.path.realpath(src_dir) != os.path.realpath(park_dir):
    sc.pop("claudeAiOauth", None)
    for k in ("oauthAccount", "userID", "cachedUsageUtilization"):
        scfg.pop(k, None)
    save(src_cred, sc)
    save(src_cfg, scfg)
    keep = [e for e in os.listdir(src_dir)
            if not os.path.islink(os.path.join(src_dir, e))
            and e not in (".claude.json", ".credentials.json", "backups")]
    if not keep and os.path.dirname(os.path.realpath(src_dir)) == os.path.realpath(ROOT):
        shutil.rmtree(src_dir)      # nothing but the login was ever in here
print("ccex: live account is now %s (rollback: %s)" % (src_email, bak), file=sys.stderr)
