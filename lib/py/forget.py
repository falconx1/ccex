"""Drop an account's number and pool entry, so `ccex rm` really removes it."""
import sys

from ccexlib import IDS, POOL, email_for, load, save

email = email_for(sys.argv[1])
if email:
    for path in (IDS, POOL):
        m = load(path)
        if m.pop(email, None) is not None:
            save(path, m)
