"""Take an account out of the rotation pool, or put it back. The login stays either way."""
import sys

from ccexlib import POOL, email_for, expand, load, save, slots

action = sys.argv[1]
target = expand(sys.argv[2]).lower()

hit = [(n, d) for n, d in slots()
       if target in (n.lower(), email_for(d).lower())] or \
      [(n, d) for n, d in slots()
       if n.lower().startswith(target) or email_for(d).lower().startswith(target)]
if not hit:
    sys.exit("ccex: no account matches '%s' (see: ccex ls)" % sys.argv[2])
if len(hit) > 1:
    sys.exit("ccex: '%s' matches %s" % (sys.argv[2], ", ".join(n for n, _ in hit)))

name, d = hit[0]
email = email_for(d)
out = load(POOL)
if action == "out":
    out[email] = True
    print("ccex: %s is out of the rotation pool; its login is untouched" % email)
else:
    out.pop(email, None)
    print("ccex: %s is back in the rotation pool" % email)
save(POOL, out)
