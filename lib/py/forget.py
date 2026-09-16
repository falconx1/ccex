"""Drop an account's number, pool entry, cap and login, so `ccex rm` really removes it.

The first three are keyed by email, so anything left behind would attach itself to the next
account added under the same address rather than to the one that earned it. The login is
keyed by the directory, and on macOS it does not live in the directory: deleting the slot
takes the files with it and would leave the keychain item behind for a slot that no longer
exists, ready to be picked up by the next profile of the same name.
"""
import sys

import creds
from ccexlib import ANCHORS, CAPS, IDS, POOL, cred_save, email_for, load, save

email = email_for(sys.argv[1])
if email:
    for path in (IDS, POOL, CAPS, ANCHORS):
        m = load(path)
        if m.pop(email, None) is not None:
            save(path, m)

try:
    cred_save(sys.argv[1], {})
except creds.CannotWrite as e:
    print("ccex: %s; the login is still there" % e, file=sys.stderr)
