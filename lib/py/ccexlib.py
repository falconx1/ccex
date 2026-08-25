"""Shared helpers for the ccex python modules.

The bash side exports CCEX_BASE and CCEX_ROOT so every module agrees on where
the live account and the parked ones live.
"""
import json, os, re

BASE = os.environ.get("CCEX_BASE") or os.path.expanduser("~/.claude")
ROOT = os.environ.get("CCEX_ROOT") or os.path.expanduser("~/.claude-profiles")
USAGE_DIR = os.path.join(ROOT, ".usage")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def save(path, obj):
    tmp = path + ".ccex.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def is_base(d):
    return os.path.realpath(d) == os.path.realpath(BASE)


def cfg_for(d):
    """Where this slot keeps its config. The live slot's is ~/.claude.json, not inside ~/.claude."""
    return os.path.expanduser("~/.claude.json") if is_base(d) else os.path.join(d, ".claude.json")


def creds_for(d):
    return os.path.join(d, ".credentials.json")


def email_for(d):
    return (load(cfg_for(d)).get("oauthAccount") or {}).get("emailAddress") or ""


def logged_in(d):
    return "claudeAiOauth" in load(creds_for(d))


def slots():
    """(name, dir) for the live account and every parked one, live first.

    A directory with no login left in it is leftover session state, not an account.
    """
    out = [("default", BASE)]
    if os.path.isdir(ROOT):
        for name in sorted(os.listdir(ROOT)):
            d = os.path.join(ROOT, name)
            if not name.startswith(".") and os.path.isdir(d) and logged_in(d):
                out.append((name, d))
    return out


def snap_path(email):
    return os.path.join(USAGE_DIR, re.sub(r"[^A-Za-z0-9]+", "_", email.lower()) + ".json")


IDS = os.path.join(ROOT, ".ids.json")
POOL = os.path.join(ROOT, ".pool.json")


def held(d):
    """True when this account has been taken out of the rotation pool."""
    return bool(load(POOL).get(email_for(d)))


_ids = None


def ids():
    """A small stable integer per account, so `ccex use 2` means the same account tomorrow.

    Numbers are keyed to the email, not to position, so rotating or adding an account
    never renumbers the others. The lowest free number goes to each new account.
    """
    global _ids
    if _ids is not None:
        return _ids
    m = load(IDS)
    used, new = set(m.values()), False
    for _, d in slots():
        e = email_for(d)
        if e and e not in m:
            n = 1
            while n in used:
                n += 1
            m[e], new = n, True
            used.add(n)
    if new:
        try:
            save(IDS, m)                # written once and reused; `ccex rm` releases one
        except OSError:
            pass
    _ids = m
    return m


def id_for(d):
    return ids().get(email_for(d))


def expand(target):
    """Turn a number into the email it stands for; anything else is passed through."""
    if target.isdigit():
        for email, n in ids().items():
            if n == int(target):
                return email
    return target


def canon(email):
    return re.sub(r"[^a-z0-9]+", "-", email.split("@")[0].lower()).strip("-") or "account"


def hm(sec):
    sec = int(sec)
    if sec >= 86400:
        return "%dd %dh%02dm" % (sec // 86400, sec % 86400 // 3600, sec % 3600 // 60)
    return "%dh%02dm" % (sec // 3600, sec % 3600 // 60) if sec >= 3600 else "%dm" % (sec // 60)
