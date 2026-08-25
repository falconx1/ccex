"""Wire `ccex record` into the statusLine in settings.json, once.

Whatever statusline is already there becomes the pipe target, so the only visible
change is that limits stay current. With no statusline at all, the bundled bar is
installed so there is something to look at.
"""
import json, os, shutil, sys, time

from ccexlib import BASE, ROOT, load, save

CCEX = os.environ.get("CCEX_BIN") or "ccex"
HERE = os.path.abspath(__file__)                      # <checkout>/lib/py/statusline.py
BAR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(HERE))), "share", "statusline.sh")
RECORD = "%s record" % CCEX

settings = os.path.join(BASE, "settings.json")
conf = load(settings)
line = conf.get("statusLine") or {}

if not isinstance(line, dict):
    sys.exit("ccex: statusLine in %s is not an object; leaving it alone" % settings)
if line and line.get("type") not in (None, "command"):
    sys.exit("ccex: statusLine type '%s' is not a command; leaving it alone" % line.get("type"))

existing = (line.get("command") or "").strip()
if "ccex record" in existing or RECORD in existing:
    print("ccex: already recording from your statusline (%s)" % settings)
    sys.exit(0)

if existing:
    command = "%s | %s" % (RECORD, existing)
    what = "kept your statusline, recording in front of it"
else:
    if not os.access(BAR, os.X_OK):    # never write a statusLine that points at nothing
        sys.exit("ccex: cannot find the bundled statusline at %s" % BAR)
    command = "%s | %s" % (RECORD, BAR)
    what = "installed the bundled statusline"

if os.path.exists(settings):        # the only file this touches, so one copy is the whole undo
    bak = os.path.join(ROOT, ".backups", time.strftime("%Y%m%d-%H%M%S"))
    os.makedirs(bak, exist_ok=True)
    shutil.copy2(settings, os.path.join(bak, "settings.json"))
    print("ccex: backed up settings.json to %s" % bak)
else:
    os.makedirs(BASE, exist_ok=True)

conf["statusLine"] = {"type": "command", "command": command}
save(settings, conf)
print("ccex: %s" % what)
print("ccex: statusLine = %s" % command)
print("ccex: open a new session, or /statusline to reload; live limits from now on")
if existing:
    print('ccex: to undo, set "command" back to: %s' % existing)
else:
    print("ccex: to undo, remove the statusLine block from %s" % settings)
