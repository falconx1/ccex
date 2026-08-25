"""Rotation rules for one account: whether it may be chosen, and how far it may be spent.

Neither touches the login. `out` takes the account off the rotation list entirely; a cap
is the softer version -- it stays in rotation, but only until the window it names.
"""
import sys

from ccexlib import CAPS, POOL, email_for, expand, load, save, slots

WINDOWS = {"--5h": "five_hour", "--weekly": "seven_day"}
LABEL = {"five_hour": "5h", "seven_day": "weekly"}

action = sys.argv[1]
argv = sys.argv[2:]
if not argv or argv[0].startswith("-"):
    sys.exit("ccex: %s wants an account (see: ccex ls)" % action)
target = expand(argv[0]).lower()

hit = [(n, d) for n, d in slots()
       if target in (n.lower(), email_for(d).lower())] or \
      [(n, d) for n, d in slots()
       if n.lower().startswith(target) or email_for(d).lower().startswith(target)]
if not hit:
    sys.exit("ccex: no account matches '%s' (see: ccex ls)" % argv[0])
if len(hit) > 1:
    sys.exit("ccex: '%s' matches %s" % (argv[0], ", ".join(n for n, _ in hit)))

name, d = hit[0]
email = email_for(d)

if action in ("in", "out"):
    out = load(POOL)
    if action == "out":
        out[email] = True
        print("ccex: %s is out of the rotation pool; its login is untouched" % email)
    else:
        out.pop(email, None)
        print("ccex: %s is back in the rotation pool" % email)
    save(POOL, out)
    raise SystemExit

# ccex pool cap <account> [--5h N] [--weekly N] [--clear]
set_, clear, rest = {}, False, argv[1:]
i = 0
while i < len(rest):
    a = rest[i]
    if a == "--clear":
        clear = True
        i += 1
    elif a in WINDOWS:
        if i + 1 >= len(rest):
            sys.exit("ccex: %s wants a percentage" % a)
        v = rest[i + 1]
        if not v.isdigit() or not 1 <= int(v) <= 100:
            sys.exit("ccex: %s wants a percentage from 1 to 100, got '%s'%s" %
                     (a, v, " (0 would mean never: that is `ccex pool out`)" if v == "0" else ""))
        set_[WINDOWS[a]] = int(v)
        i += 2
    else:
        sys.exit("ccex: cap: unknown option '%s' (try: ccex pool -h)" % a)

caps = load(CAPS)
mine = dict(caps.get(email) or {})

if not set_ and not clear:                  # no flags: report, so `cap <account>` is safe to type
    if mine:
        print("ccex: %s is capped at %s" % (email, ", ".join(
            "%s %d%%" % (LABEL[k], mine[k]) for k in ("five_hour", "seven_day") if k in mine)))
        print("ccex: `ccex pool cap %s --clear` puts it back on the --at default" % name)
    else:
        print("ccex: %s has no cap of its own; rotation uses --at (default 80)" % email)
    raise SystemExit

if clear and not set_:
    if not mine:
        print("ccex: %s had no cap of its own; nothing to clear" % email)
        raise SystemExit
    caps.pop(email, None)
    save(CAPS, caps)
    print("ccex: %s is back on the --at default (default 80)" % email)
    raise SystemExit

mine = set_ if clear else {**mine, **set_}   # --clear with a flag means "only this from now on"
caps[email] = mine
save(CAPS, caps)
print("ccex: %s is out of room at %s" % (email, ", ".join(
    "%s %d%%" % (LABEL[k], mine[k]) for k in ("five_hour", "seven_day") if k in mine)))
missing = [LABEL[k] for k in ("five_hour", "seven_day") if k not in mine]
if missing:
    print("ccex: %s still follows --at" % " and ".join(missing))
