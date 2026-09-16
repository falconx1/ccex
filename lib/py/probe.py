"""Launching a real session on one account, just long enough to read its own limits.

The one thing in ccex that costs anything: `usage.py` reads files, this opens the TUI. It
lives on its own because both `ccex ls --force` and rotation's pre-switch check need it,
and neither wants the other's argument parsing.

Opening the TUI to read `/usage` spends no quota at all. The one call that does is `allowed`,
a single Haiku turn asked only of an account that has already failed to answer -- because
that is the only way to hear the difference between an account that was slow and one that is
not permitted to run.
"""
import json, os, pty, re, select, signal, subprocess, sys, time

from ccexlib import (BASE, cfg_for, email_for, is_base, load, logged_in, note_probe,
                     save, seed_into)
from usage import cached

MODEL = "claude-haiku-4-5-20251001"   # the cheapest thing that still counts as a session
DROP = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT")


def session_env(d, cfg, **extra):
    """The environment a `claude` run for this account needs, without what it must not see.

    Anything CLAUDE_CODE_* belongs to the session this is running inside, and a child that
    inherits it reports itself as that session. CLAUDE_CONFIG_DIR comes from the config path
    rather than from `is_base`, because with it already exported the live slot's config is
    inside it, and the child has to be pointed at the same file `cfg_for` just read.
    """
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("CLAUDE_CODE_") and k not in DROP}
    env.pop("CLAUDE_CONFIG_DIR", None)
    if cfg == os.path.join(d, ".claude.json"):
        env["CLAUDE_CONFIG_DIR"] = d
    env.update(extra)
    return env


def trusted_dir(cfg):
    for path, v in (load(cfg).get("projects") or {}).items():
        if isinstance(v, dict) and v.get("hasTrustDialogAccepted") and os.path.isdir(path):
            return path
    return None

# A probe on its own takes about 6s. The second of three in a row was measured at 47s on an
# account that had just answered in 6 -- and claude reads the system keychain at startup, so
# the likeliest reason is a keyring dialog nobody had answered yet. Waiting longer for a
# dialog is not waiting for an answer, so the ceiling stays where it is; CCEX_PROBE_TIMEOUT
# raises it on a machine where launches really are just slow.
TIMEOUT = int(os.environ.get("CCEX_PROBE_TIMEOUT") or 50)



# An organisation can turn Claude Code off for its accounts, and then nothing on that account
# works -- not a reading, and not any real session either. It says so in two places, and both
# are worth catching, because whichever arrives first ends the same way: the account is
# held out of the pool and the switch goes on to the next candidate.
#
# The panel says it when /usage is answered at all, as the error painted where the numbers
# go. The call says it in plain words, and says it even when the panel never answers.
REFUSED = (b"permission_error", b"notallowedforthisorganization")
DISABLED = ("disabled claude subscription access", "not allowed for this organization")
ASK_TIMEOUT = 40


def allowed(d):
    """Whether this account may run Claude Code at all, or None if it did not say.

    One Haiku turn in print mode, and only ever after a launch has already come back with
    nothing. The /usage panel cannot answer this question: an organisation with subscription
    access turned off leaves it spinning rather than refusing, asking it again cancels the
    request in flight, and enough of those rate-limit the account -- after which a refusal
    and a slow machine are the same blank panel. A real call is refused in seconds, in words.

    This is the one thing in ccex that spends anything, which is why it is on the failure
    path only. What it buys is worth a few tokens: an account nothing can run on is one
    rotation would otherwise keep, and keep choosing, because a window past its reset reads
    0% with nobody asked and stale numbers only ever look emptier.
    """
    cfg = cfg_for(d)
    cwd = trusted_dir(cfg)
    if not cwd:
        return None
    try:
        r = subprocess.run(["claude", "-p", "hi", "--model", MODEL], cwd=cwd,
                           env=session_env(d, cfg), timeout=ASK_TIMEOUT,
                           stdin=subprocess.DEVNULL, capture_output=True,
                           text=True, errors="replace")
    except (OSError, subprocess.TimeoutExpired):
        return None            # it did not get as far as being told no
    if not r.returncode:
        return True
    said = ((r.stdout or "") + (r.stderr or "")).lower()
    return False if any(k in said for k in DISABLED) else None


# The usage panel, once it is up. Retyping `/usage` behind an open one is not a retry, it is
# a cancel: the escape that clears the prompt clears the request in flight with it. On an
# account whose answer takes a few seconds that meant the answer never landed at all, and
# asking six times in a row got the endpoint to rate-limit the account instead of answering
# it. The retry is for a `/usage` the TUI was not yet listening for, and it has done its job
# the moment the panel appears.
PANEL = (b"loadingusagedata", b"usagestats")


def flatten(buf):
    """What the screen says, with the drawing of it taken out.

    The panel wraps at whatever width it was handed and paints as it goes, so a message in
    the buffer has escape sequences and line breaks through the middle of it. Only with
    those gone is there a string to look for.
    """
    return re.sub(rb"\x1b\[[0-9;?]*[a-zA-Z]|\s+", b"", buf).lower()


def refused(buf):
    """Whether the panel came back refusing this account, rather than not coming back."""
    return any(k in flatten(buf) for k in REFUSED)


def showing(buf):
    """Whether the usage panel is up, so that asking for it again would only close it."""
    return any(k in flatten(buf) for k in PANEL)


def probe(d, timeout=None):
    """Launch this account and read it, keeping a record of whether the launch worked.

    Every caller comes through here -- rotation asking before a switch, `ccex ls --force`,
    the age-out read -- and every one of them files what it heard, because the tick that
    acts on a refusal is not always the tick that was told.

    A launch that comes back empty is asked one more question, because "it did not answer"
    covers both an account that was slow and an account that is not allowed to run at all,
    and only the second one should cost it its place in the pool.
    """
    st = launch(d, timeout)
    if st == "timeout" and allowed(d) is False:
        st = "noauth"          # it was not too slow to answer; it was told it may not
    note_probe(email_for(d), st)
    return st


def launch(d, timeout=None):
    """Launch the real `claude` TUI on this account, open /usage, quit. No inference, no cost.

    CCEX_PROBE_TIMEOUT moves the ceiling. Rotation may ask up to three accounts before it
    switches and holds the switch lock while it does, so raising this raises CCEX_LOCK_WAIT's
    floor with it.
    """
    timeout = TIMEOUT if timeout is None else timeout
    cfg = cfg_for(d)
    before = cached(d).get("fetchedAtMs") or 0
    cwd = trusted_dir(cfg)
    if not cwd and borrow_trust(d):
        cwd = trusted_dir(cfg)      # a profile that has never been live has trusted nothing
    if not cwd:
        return "untrusted"
    if not logged_in(d):        # asked of the store, not of a file: macOS keeps no file
        return "nologin"
    pid, fd = pty.fork()
    if pid == 0:
        env = session_env(d, cfg, TERM="xterm-256color", COLUMNS="120", LINES="45")
        os.environ.clear()          # built first: session_env reads the environment it replaces
        os.environ.update(env)
        try:
            os.chdir(cwd)
            os.execvp("claude", ["claude", "--model", MODEL])
        except Exception:
            os._exit(127)
    start = time.time()
    sent, refreshed, quit_at, mtime, buf, ready_at, tries = set(), False, None, 0, b"", None, 0
    denied = panel = False
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
        panel = panel or showing(buf)
        denied = denied or refused(buf)
        if not refreshed and not panel and ready_at and time.time() - ready_at > 1.5 \
                and tries * 7 < el - 1:
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
        if (refreshed or denied or el > timeout - 6) and "quit" not in sent:
            try:
                os.write(fd, b"/exit\r")
            except OSError:
                break              # it has already gone; there is nothing left to ask it
            sent.add("quit"); quit_at = time.time()
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
    if (cached(d).get("fetchedAtMs") or 0) > before:
        return "ok"
    return "noauth" if denied else "timeout"


NOTE = {"noauth": "not allowed to use Claude Code - its organisation has disabled "
                  "subscription access, so nothing can read it and nothing can run on it; "
                  "showing cached numbers",
        "untrusted": "no trusted project dir - launch `claude` once in one of your project folders first; showing cached numbers",
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
