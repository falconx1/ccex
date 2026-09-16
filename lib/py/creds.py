"""Where a login lives, and the two answers to that question on the two systems ccex runs on.

Claude Code writes a login as `.credentials.json` on Linux and as a login Keychain item on
macOS, and on macOS it treats the file as a fallback the item overrides. Both are the same
four questions -- is there a login here, what is it, put this one here, and where is `here`
in words a person can go and look at -- so they are one interface with two implementations,
chosen once. Everything that moves a login talks to that interface and to nothing else,
which is why `use.py` has no idea which system it is running on.

Neither class knows where slots live or how this repo reads JSON: those arrive in the
constructor from `ccexlib`, which is the module that does know. A third store would be a
third class here and no change anywhere else.

The contract both keep: after `save(d, doc)`, `load(d)` gives back the login in `doc` and
`has(d)` agrees; saving a document with no `claudeAiOauth` in it takes the login away, and
nothing else that document carried is promised to survive that -- nothing but a login has
ever been in one.
"""
import hashlib, json, os, re, shutil, subprocess, sys, time, unicodedata


class CannotWrite(Exception):
    """A login could not be put where it belongs.

    Worth a class of its own because of when it happens: mid-switch, with one half of a
    handover already done. The stores raise it and say nothing else -- which of the two
    commands that write is running, and what it should tell you, is not theirs to know.
    """


def pick(kind=None):
    """Which store this machine keeps logins in.

    `CCEX_CRED_STORE` overrides it -- the tests ask for files whatever they are running on,
    and it is the way out if a machine ever wants the Linux layout on macOS.
    """
    return (kind or os.environ.get("CCEX_CRED_STORE")
            or ("keychain" if sys.platform == "darwin" else "file"))


class FileStore:
    """A login as Claude Code writes one on Linux: JSON in the slot's own directory."""

    kind = "file"

    def __init__(self, path_for, read_json, write_json):
        self._path_for = path_for      # slot directory -> the file its login is in
        self._read = read_json         # a stat-gated read, so a view can ask every second
        self._write = write_json       # atomic, mode 600

    def where(self, d):
        return self._path_for(d)

    def load(self, d):
        return self._read(self._path_for(d))

    def has(self, d):
        return "claudeAiOauth" in self.load(d)

    def save(self, d, doc):
        self._write(self._path_for(d), doc)

    def backup(self, into, slots):
        """Copy what a rollback would need into `into`; `slots` is (tag, directory, email)."""
        for tag, d, _ in slots:
            p = self._path_for(d)
            if os.path.exists(p):
                shutil.copy2(p, os.path.join(into, "%s.credentials.json" % tag))


class KeychainStore:
    """A login as Claude Code writes one on macOS: an item in the login Keychain.

    One item per config directory -- `Claude Code-credentials` for the slot claude runs
    with CLAUDE_CONFIG_DIR unset, and that name plus the first eight hex of sha256 of the
    directory for every other, which is what already makes a parked profile its own login
    rather than a second name for the live one.

    Writes go out as hex on `security`'s stdin, which is the shape Claude Code writes them
    in: it keeps the token off the command line, and out of every quoting question a JSON
    document would otherwise raise. Reads cost a process, so they are cached for the same
    30 seconds Claude Code caches its own for.
    """

    kind = "keychain"
    TIMEOUT = 10
    STDIN_MAX = 4032      # what Claude Code sends through `security -i` before using argv
    TTL = 30

    def __init__(self, uses_config_dir, write_json, prefix=None):
        self._suffixed = uses_config_dir    # slot directory -> does claude set CLAUDE_CONFIG_DIR for it
        self._write = write_json
        self._prefix = prefix or os.environ.get("CCEX_KEYCHAIN_SERVICE") or "Claude Code"
        self._cache = {}                    # service -> (when, document)

    @property
    def account(self):
        """The item's account name, chosen the way Claude Code chooses it."""
        u = os.environ.get("USER") or ""
        if not u:
            try:
                import getpass
                u = getpass.getuser()
            except Exception:
                u = ""
        return u if re.match(r"^[A-Za-z0-9._-]+$", u) else "claude-code-user"

    def service_for(self, d):
        """The item this slot's login belongs in.

        The suffix is over the directory as a string, because that is what Claude Code
        hashes: the value of CLAUDE_CONFIG_DIR, NFC-normalised.
        """
        svc = self._prefix + "-credentials"
        if self._suffixed(d):
            svc += "-" + hashlib.sha256(
                unicodedata.normalize("NFC", d).encode("utf8")).hexdigest()[:8]
        return svc

    def where(self, d):
        return "keychain item '%s'" % self.service_for(d)

    def load(self, d):
        svc = self.service_for(d)
        hit = self._cache.get(svc)
        if hit and time.time() - hit[0] < self.TTL:
            return hit[1]
        p = self._run(["find-generic-password", "-a", self.account, "-s", svc, "-w"])
        doc = {}
        if p and p.returncode == 0:
            try:
                doc = json.loads(p.stdout.strip())
            except ValueError:
                doc = {}
        if not isinstance(doc, dict):
            doc = {}
        self._cache[svc] = (time.time(), doc)
        return doc

    def has(self, d):
        """Whether there is a login here -- answered without reading the secret itself."""
        svc = self.service_for(d)
        hit = self._cache.get(svc)
        if hit and time.time() - hit[0] < self.TTL:
            return bool(hit[1].get("claudeAiOauth"))
        p = self._run(["find-generic-password", "-a", self.account, "-s", svc])
        return bool(p and p.returncode == 0)

    def save(self, d, doc):
        svc = self.service_for(d)
        self._cache.pop(svc, None)
        if not doc.get("claudeAiOauth"):
            self._run(["delete-generic-password", "-a", self.account, "-s", svc])
            return
        hexed = json.dumps(doc, separators=(",", ":")).encode("utf8").hex()
        line = 'add-generic-password -U -a "%s" -s "%s" -X "%s"\n' % (self.account, svc, hexed)
        if len(line) <= self.STDIN_MAX:
            p = self._run(["-i"], stdin=line)
        else:
            p = self._run(["add-generic-password", "-U", "-a", self.account, "-s", svc,
                           "-X", hexed])
        if not p or p.returncode != 0 or not self.has(d):
            raise CannotWrite("could not write the login into %s%s" %
                              (self.where(d), (": " + p.stderr.strip()) if p and p.stderr else ""))

    def backup(self, into, slots):
        """Which item ended up holding which account.

        Copying the logins out would leave tokens on disk that were not there before, and
        a rollback does not need them: the items are still where this says they are, and
        `ccex use` the other way round puts them back.
        """
        self._write(os.path.join(into, "keychain.json"),
                    {tag: {"email": email, "dir": d, "service": self.service_for(d)}
                     for tag, d, email in slots})

    def _run(self, args, stdin=None):
        """`security`, or None when it could not be asked at all -- which is not the same
        as an item that is not there, and only the caller knows which of those matters."""
        try:
            return subprocess.run(["security"] + args, input=stdin, capture_output=True,
                                  text=True, timeout=self.TIMEOUT)
        except (OSError, subprocess.SubprocessError):
            return None
