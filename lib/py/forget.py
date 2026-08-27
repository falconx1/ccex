"""Drop an account's number, pool entry and cap, so `ccex rm` really removes it.

All three are keyed by email, so anything left behind would attach itself to the next
account added under the same address rather than to the one that earned it.
"""
import sys

from ccexlib import ANCHORS, CAPS, IDS, POOL, email_for, load, save

email = email_for(sys.argv[1])
if email:
    for path in (IDS, POOL, CAPS, ANCHORS):
        m = load(path)
        if m.pop(email, None) is not None:
            save(path, m)
