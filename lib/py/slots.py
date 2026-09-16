"""Every slot that still holds a login, live one first -- the bash side's list of accounts.

It lives here rather than in a `grep` for the credential file because on macOS there is no
credential file to grep: `logged_in` asks whichever store this machine keeps logins in.
"""
from ccexlib import slots

for name, _ in slots():
    print(name)
