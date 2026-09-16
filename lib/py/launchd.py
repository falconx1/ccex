"""The macOS half of `ccex rotate --bg`: a launchd agent where Linux has a systemd unit.

Same shape either way -- install it, ask whether it is running, ask what it costs, take it
away. Only the words differ, so `background.sh` reads the same on both. The agent is
bootstrapped into `gui/<uid>` rather than `user/<uid>` on purpose: that is the session with
the login keychain unlocked, and a rotator that cannot read a login cannot rotate onto it.

  launchd.py install <name> <description> <command...>
  launchd.py remove|active|cmdline|stats <name>
"""
import os, plistlib, re, subprocess, sys

LABEL = "com.ccex."
AGENTS = os.path.expanduser("~/Library/LaunchAgents")
UID = os.getuid()


def label(name):
    return LABEL + name


def plist_path(name):
    return os.path.join(AGENTS, label(name) + ".plist")


def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None


def launchctl(*args):
    return run("launchctl", *args)


def printed(name):
    """`launchctl print` for this agent, as text, or "" when it is not loaded."""
    p = launchctl("print", "gui/%d/%s" % (UID, label(name)))
    return p.stdout if p and p.returncode == 0 else ""


def env_for():
    """What the agent needs in its environment that launchd will not hand it.

    A login shell's PATH is not an agent's, and the agent runs `claude` and `security`.
    """
    path = os.environ.get("PATH", "")
    claude = ""
    for d in path.split(os.pathsep):
        if d and os.path.exists(os.path.join(d, "claude")):
            claude = d
            break
    parts = [p for p in (claude, os.path.expanduser("~/.local/bin"), "/opt/homebrew/bin",
                         "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin") if p]
    seen, keep = set(), []
    for p in parts:
        if p not in seen:
            seen.add(p)
            keep.append(p)
    env = {"PATH": os.pathsep.join(keep), "HOME": os.path.expanduser("~")}
    for k in ("CC_PROFILE_ROOT", "CCEX_LIB", "CCEX_CRED_STORE", "CCEX_KEYCHAIN_SERVICE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def install(name, description, cmd):
    os.makedirs(AGENTS, exist_ok=True)
    logs = os.path.join(os.environ.get("CCEX_ROOT") or os.path.expanduser("~/.claude-profiles"),
                        ".usage")
    os.makedirs(logs, exist_ok=True)
    log = os.path.join(logs, name + ".log")
    doc = {
        "Label": label(name),
        "ProgramArguments": list(cmd),
        "RunAtLoad": True,
        "KeepAlive": True,
        "ThrottleInterval": 10,
        "Nice": 5,
        "ProcessType": "Background",
        "EnvironmentVariables": env_for(),
        "StandardOutPath": log,
        "StandardErrorPath": log,
    }
    if description:
        doc["ServiceDescription"] = description
    path = plist_path(name)
    with open(path, "wb") as f:
        plistlib.dump(doc, f)
    launchctl("bootout", "gui/%d/%s" % (UID, label(name)))     # whatever was there before
    p = launchctl("bootstrap", "gui/%d" % UID, path)
    if not p or p.returncode != 0:
        p = launchctl("load", "-w", path)                      # older launchctl
        if not p or p.returncode != 0:
            sys.exit("ccex: launchd would not take the agent%s"
                     % ((": " + p.stderr.strip()) if p and p.stderr else ""))
    launchctl("enable", "gui/%d/%s" % (UID, label(name)))
    launchctl("kickstart", "-k", "gui/%d/%s" % (UID, label(name)))


def remove(name):
    launchctl("bootout", "gui/%d/%s" % (UID, label(name)))
    path = plist_path(name)
    if os.path.exists(path):
        launchctl("unload", "-w", path)
        os.remove(path)


def pid_of(name):
    m = re.search(r"^\s*pid = (\d+)$", printed(name), re.M)
    return int(m.group(1)) if m else 0


def active(name):
    out = printed(name)
    if not out:
        return False
    return "state = running" in out or pid_of(name) > 0


def cmdline(name):
    try:
        with open(plist_path(name), "rb") as f:
            return " ".join(plistlib.load(f).get("ProgramArguments") or [])
    except OSError:
        return ""


def stats(name):
    """state, when it started, resident bytes, cpu nanoseconds -- what `--status` prints."""
    pid = pid_of(name)
    state = "running" if active(name) else "inactive"
    since, rss, cpu = "", 0, 0
    if pid:
        p = run("ps", "-o", "lstart=,rss=,time=", "-p", str(pid))
        if p and p.returncode == 0 and p.stdout.strip():
            row = p.stdout.strip()
            m = re.match(r"^(.{24})\s+(\d+)\s+(\S+)$", row)
            if m:
                since, rss = m.group(1).strip(), int(m.group(2)) * 1024
                t = m.group(3).split(":")          # [[hh:]mm:]ss.ff
                secs = 0.0
                for part in t:
                    secs = secs * 60 + float(part)
                cpu = int(secs * 1e9)
    return "%s\t%s\t%d\t%d" % (state, since, rss, cpu)


if __name__ == "__main__":      # also imported, by the view that asks whether it is running
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    verb, what = sys.argv[1], sys.argv[2]
    if verb == "install":
        install(what, sys.argv[3] if len(sys.argv) > 3 else "", sys.argv[4:])
    elif verb == "remove":
        remove(what)
    elif verb == "active":
        sys.exit(0 if active(what) else 1)
    elif verb == "cmdline":
        print(cmdline(what))
    elif verb == "stats":
        print(stats(what))
    else:
        sys.exit("launchd.py: unknown verb '%s'" % verb)
