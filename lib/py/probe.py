"""Launching a real session on one account, just long enough to read its own limits.

The one thing in ccex that costs anything: `usage.py` reads files, this opens the TUI. It
lives on its own because both `ccex ls --force` and rotation's pre-switch check need it,
and neither wants the other's argument parsing.
"""
import json, os, pty, select, signal, sys, time

from ccexlib import BASE, cfg_for, creds_for, is_base, load, save, seed_into
from usage import cached

def trusted_dir(cfg):
    for path, v in (load(cfg).get("projects") or {}).items():
        if isinstance(v, dict) and v.get("hasTrustDialogAccepted") and os.path.isdir(path):
            return path
    return None

TIMEOUT = int(os.environ.get("CCEX_PROBE_TIMEOUT") or 50)   # a slow start may want more


def probe(d, timeout=None):
    """Launch the real `claude` TUI on this account, open /usage, quit. No inference, no cost.

    CCEX_PROBE_TIMEOUT raises the ceiling for a machine where claude starts slowly. Rotation
    may ask up to three accounts before it switches, and it holds the switch lock while it
    does, so raising this raises CCEX_LOCK_WAIT's floor with it.
    """
    timeout = TIMEOUT if timeout is None else timeout
    cfg = cfg_for(d)
    before = cached(d).get("fetchedAtMs") or 0
    cwd = trusted_dir(cfg)
    if not cwd and borrow_trust(d):
        cwd = trusted_dir(cfg)      # a profile that has never been live has trusted nothing
    if not cwd:
        return "untrusted"
    if not os.path.exists(creds_for(d)):
        return "nologin"
    pid, fd = pty.fork()
    if pid == 0:
        for k in list(os.environ):
            if k.startswith("CLAUDE_CODE_") or k in ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT"):
                os.environ.pop(k, None)
        # From the config path, not from is_base: with CLAUDE_CONFIG_DIR exported the live
        # slot's config is inside it, and the child has to be pointed at the same file
        # cfg_for just read, or it reads a stale ~/.claude.json instead.
        if cfg == os.path.join(d, ".claude.json"):
            os.environ["CLAUDE_CONFIG_DIR"] = d
        else:
            os.environ.pop("CLAUDE_CONFIG_DIR", None)
        os.environ.update(TERM="xterm-256color", COLUMNS="120", LINES="45")
        try:
            os.chdir(cwd)
            os.execvp("claude", ["claude", "--model", "claude-haiku-4-5-20251001"])
        except Exception:
            os._exit(127)
    start = time.time()
    sent, refreshed, quit_at, mtime, buf, ready_at, tries = set(), False, None, 0, b"", None, 0
    while time.time() - start < timeout:
        r, _, _ = select.select([fd], [], [], 0.3)
        if r:
            try:
                chunk = os.read(fd, 65536)
                if not chunk:
                    break
                buf = (buf + chunk)[-8192:]
            except OSError:
                break
        el = time.time() - start
        if ready_at is None and (b"\xe2\x9d\xaf" in buf or b"shift+tab" in buf):
            ready_at = time.time()          # the prompt is up; the TUI is listening
        if not refreshed and ready_at and time.time() - ready_at > 1.5 and tries * 7 < el - 1:
            os.write(fd, b"\x1b/usage\r")  # esc first, so a retry never appends to a live prompt
            tries += 1
            sent.add("usage")
        if el > 20 and not refreshed and "nudge" not in sent:
            os.write(fd, b"\r"); sent.add("nudge")
        if not refreshed:
            try:
                m = os.stat(cfg).st_mtime
            except OSError:
                m = mtime
            if m != mtime:
                mtime = m
                refreshed = (cached(d).get("fetchedAtMs") or 0) > before
        if (refreshed or el > timeout - 6) and "quit" not in sent:
            os.write(fd, b"/exit\r"); sent.add("quit"); quit_at = time.time()
        if quit_at and time.time() - quit_at > 2:
            break
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig); time.sleep(0.3)
        except OSError:
            break
    try:
        os.waitpid(pid, os.WNOHANG)
    except OSError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    return "ok" if (cached(d).get("fetchedAtMs") or 0) > before else "timeout"


NOTE = {"untrusted": "no trusted project dir - launch `claude` once in one of your project folders first; showing cached numbers",
        "nologin": "not logged in",
        "timeout": "limits check timed out; showing cached numbers",
        "unhooked": "a session is open on this account, so nothing was launched. For live numbers put "
                    "`ccex record |` in front of your statusLine command (see `ccex --help`); "
                    "showing cached numbers"}


def borrow_trust(d):
    """Give a parked profile what it needs before it can be asked anything.

    Two things stop a launch, and folder trust is only the obvious one. A profile that has
    never been onboarded stops on the theme picker, so `/usage` is never typed and the probe
    waits out its whole timeout looking exactly like a slow account -- which is what two of
    three probes were doing on this machine before `seed_into` covered both.

    Both come from the config of whoever is live, which is what `ccex add` seeds a new
    profile with. Nothing is overwritten, so a profile that has all of it is left alone.
    """
    if is_base(d):
        return False
    cfg = cfg_for(d)
    mine = load(cfg)
    was = json.dumps(mine, sort_keys=True)
    seed_into(mine, load(cfg_for(BASE)))
    if json.dumps(mine, sort_keys=True) == was:
        return False                  # nothing to give it; the live config has none either
    try:
        save(cfg, mine)
    except OSError:
        return False
    print("ccex: seeded onboarding and folder trust into %s, so it could be asked directly"
          % os.path.basename(d.rstrip("/")), file=sys.stderr)
    return True
