"""Hand the live ~/.claude slot over to a parked account, and park the one that was there."""
import os, shutil, sys, time

from ccexlib import (BASE, ROOT, canon, cfg_for, creds_for, email_for, expand, held,
                     id_for, load, logged_in, note_switch, save, seed_into, step)
from decide import FIVE_AT, cap, own, ranked, reads
from usage import account_json, cached

target = expand(sys.argv[1])
dry = "--dry-run" in sys.argv[2:] or "-n" in sys.argv[2:]
asking = "--ask" in sys.argv[2:]
anyway = "--anyway" in sys.argv[2:]
TRIES = 3           # accounts to read before giving up, the same bound rotation uses
IDENTITY = ("oauthAccount", "userID", "cachedUsageUtilization")   # what makes a slot the account

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
if held(src_dir):
    sys.exit("ccex: %s is held out of the pool; `ccex pool in %s` first"
             % (src_email, id_for(src_dir) or src_name))
def taken(d):
    """Someone else's login is in here, and overwriting it would need a fresh browser sign-in."""
    if os.path.realpath(d) == os.path.realpath(src_dir):
        return True
    return logged_in(d) and email_for(d).lower() != (live_email or "").lower()

# What the account you named actually has left, measured against its own cap where it has one
# and otherwise against the threshold the daemon is really running at -- not the built-in
# default. Warning about 90% while the daemon moves off at 80% would stay quiet about exactly
# the switch it is about to undo.
row = account_json(src_name, src_dir)
running = load(os.path.join(ROOT, ".usage", "daemon.json")).get("at")
at = int(running) if str(running or "").isdigit() else FIVE_AT


def no_room(a):
    """Which of this account's windows are spent, against its own cap where it has one."""
    return ["%s over %s" % (w, own(a, k, at)) for k, w in (("five", "5h"), ("seven", "weekly"))
            if a[k] is not None and a[k] >= cap(a, k, at)]


if asking and not dry:
    # The same reading rotation does before it moves, done here for the same reason, through
    # the same ask(), written to the same trail -- a switch you pressed a key for should show
    # its working in the view exactly like one a timer started.
    #
    # And the same answer to a spent destination: hand over to the next account with room.
    # Naming an account is not an instruction to sit at 93%; the daemon would move off it
    # seconds later, which is the bounce all of this exists to stop. `--anyway` is the way to
    # say you meant it.
    from ask import ask
    step(None)                        # this switch's trail is its own
    step("switching to %s by hand, reading it first" % src_name)
    tried, named = set(), src_name
    while True:
        was = None if row["five"] is None else reads(row)
        st, got = ask(src_name, src_dir, was,
                      ", going by what is on file" if src_name == named else ", trying the next")
        tried.add(src_name)
        if st == "ok":
            row = got
        spent = no_room(row)
        # The account you named is used on its numbers on file when it will not answer -- you
        # asked for it by name, and unverified is not the same as spent. An account this
        # picked for you is not: landing on numbers nobody could confirm is what rotation
        # stopped doing, so it moves on to the next one instead.
        if anyway or (not spent and (st == "ok" or src_name == named)):
            break
        why = " and ".join(spent) if spent else "could not be asked (%s)" % st
        # Somewhere it has to stop -- three sessions is already most of a minute, and it holds
        # the switch lock throughout. Not the account that is already live either: a slot left
        # behind by an earlier park still holds its credential, so ranking can offer you the
        # account you are on and the switch comes back "already live; nothing moved".
        nxt = None
        if len(tried) < TRIES:
            rows = [account_json("default", BASE)] + \
                   [account_json(n, d) for n, (d, e) in parked.items() if n not in tried]
            nxt = next((a for a in ranked(rows, at) if a["name"] in parked
                        and a["email"].lower() != (live_email or "").lower()), None)
        if nxt is None:
            # Landing on a known-spent account nobody asked for is the worst of both: not what
            # you named, and moved off again within seconds.
            step("%s %s, and there is nothing else worth reading" % (src_name, why))
            sys.exit("ccex: %s is at %s, %s - and there is nothing else with room, so nothing "
                     "moved (`ccex use %s --anyway` switches to it regardless)"
                     % (src_email, reads(row), why, target))
        step("%s has no room (%s), reading %s instead" % (src_name, why, nxt["name"]))
        print("ccex: %s is at %s, %s - handing over to %s instead (`ccex use %s --anyway` "
              "switches to it regardless)"
              % (src_email, reads(row), why, nxt["email"], target), file=sys.stderr)
        src_name, (src_dir, src_email) = nxt["name"], parked[nxt["name"]]
        row = account_json(src_name, src_dir)

over = no_room(row)
if over:
    print("ccex: %s is at %s, %s - rotation will move off it again"
          % (src_email, reads(row), " and ".join(over)), file=sys.stderr)
elif row["five"] is None:
    print("ccex: nothing has measured %s; its numbers arrive once it reports" % src_email,
          file=sys.stderr)

if asking and not dry:
    step("switching to %s" % src_name, log=False)

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

bak_root = os.path.join(ROOT, ".backups")
bak = os.path.join(bak_root, time.strftime("%Y%m%d-%H%M%S"))
os.makedirs(bak, exist_ok=True)
for stale in sorted(d for d in os.listdir(bak_root) if not d.startswith("."))[:-20]:
    shutil.rmtree(os.path.join(bak_root, stale), ignore_errors=True)   # rotating hourly adds up
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
for k in IDENTITY:
    if k in lcfg:
        pkcfg[k] = lcfg[k]
# probe() needs a folder this slot's own config trusts. A slot that hands its login away is
# deleted, so the seed `ccex add` gave it is gone by the time rotation parks an account here
# again -- without re-seeding now, a parked account answers "untrusted" and can never be
# measured. Seeding at park time is the fix; borrow_trust() only patches it at probe time.
seed_into(pkcfg, lcfg)
save(pk_cred, pk)
save(pk_cfg, pkcfg)

# What the outgoing account was reading, before its numbers are parked with it.
note_switch(live_email, cached(BASE)["utilization"] or {})

lc["claudeAiOauth"] = sc["claudeAiOauth"]
for k in IDENTITY:
    if k in scfg:
        lcfg[k] = scfg[k]
    else:
        lcfg.pop(k, None)
save(live_cred, lc)
save(live_cfg, lcfg)

# the source slot handed its login over, so it must not keep a copy: one account, one slot
if os.path.realpath(src_dir) != os.path.realpath(park_dir):
    sc.pop("claudeAiOauth", None)
    for k in IDENTITY:
        scfg.pop(k, None)
    save(src_cred, sc)
    save(src_cfg, scfg)
    keep = [e for e in os.listdir(src_dir)
            if not os.path.islink(os.path.join(src_dir, e))
            and e not in (".claude.json", ".credentials.json", "backups")]
    if not keep and os.path.dirname(os.path.realpath(src_dir)) == os.path.realpath(ROOT):
        shutil.rmtree(src_dir)      # nothing but the login was ever in here
print("ccex: live account is now %s (rollback: %s)" % (src_email, bak), file=sys.stderr)
