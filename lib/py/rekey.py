"""Carry a login from one slot directory to another: `rekey.py <from> <to>`.

`ccex add` with no name logs in inside a scratch directory and renames it afterwards, once
the account has said who it is. On Linux the login is a file and it moves with the rename.
On macOS it is a keychain item keyed by the directory it was written for, so it has to be
written again under the new name -- otherwise the account that just logged in reads as
never having logged in at all.
"""
import sys

import creds
from ccexlib import cred_move

if len(sys.argv) != 3:
    sys.exit("usage: rekey.py <from-dir> <to-dir>")
try:
    cred_move(sys.argv[1], sys.argv[2])
except creds.CannotWrite as e:
    sys.exit("ccex: %s" % e)
