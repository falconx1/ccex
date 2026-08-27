"""`ccex ls -w`: the account list, live, with the rotation monitor folded into it.

Two cadences, one process. The countdowns re-render every second from reset timestamps
that are already known, which costs nothing; the numbers behind them are re-read on the
slower --every tick, and only that tick walks /proc or asks systemd anything. Nothing
here starts a session unless --refresh says it may, and then off the render loop, so the
view never freezes waiting for one.
"""
import os, re, select, shutil, subprocess, sys, tempfile, termios, threading, time, tty

import burn
from ccexlib import ROOT, USAGE_DIR, fresh, hm, id_for, save, slots
from decide import FIVE_AT, cap, decide, ranked, reads
from usage import GRACE, account_json, age_text, bar, live_map

PRESETS = [10, 30, 60, 300, 900, 1800]
PROC_EVERY = 15         # seconds between /proc walks: the one read that is not free
WEEKLY_NEAR = 90        # below this the week is not what the next switch will be about
NO_UNIT = {"active": False, "legacy": False, "at": None, "refresh": None, "every": None}


BEAT = ".beat"       # touched every time the daemon reads the numbers


def paced(txt):
    """"10s", "5m" -> seconds. What the daemon's own --every says, whichever way it says it."""
    m = re.match(r"\s*(\d+)\s*([smh]?)", txt or "")
    return int(m.group(1)) * {"": 1, "s": 1, "m": 60, "h": 3600}[m.group(2)] if m else 0
DAEMON = os.path.join(ROOT, ".usage", "daemon.json")     # written by the daemon itself
LIMITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "limits.py")
CCEX = os.environ.get("CCEX_BIN") or "ccex"

RESET, BOLD, DIM, REV = "\033[0m", "\033[1m", "\033[2m", "\033[7m"
RED, GREEN, YELLOW, CYAN, GREY = "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[90m"


def handover(old, cmd):
    """Give the terminal to something interactive, then take it back.

    A browser login prints URLs and waits on keys, so it cannot run behind an alternate
    screen or in cbreak mode -- and it cannot run in a thread either, because it wants
    this terminal. So the view steps out of the way and redraws when it is done.
    """
    sys.stdout.write("\033[?25h\033[?1049l")
    sys.stdout.flush()
    if old:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
    try:
        return subprocess.call(cmd)
    except (OSError, KeyboardInterrupt):
        return 1
    finally:
        sys.stdout.write("\033[?1049h\033[?25l")
        sys.stdout.flush()
        if old:
            tty.setcbreak(sys.stdin.fileno())


# A switch may read up to three accounts before it moves, and each reading is a session
# launch. Cutting it off part way through is the very failure the temporary file below exists
# to prevent, so the ceiling follows what a reading is actually allowed to take.
SWITCH_WAIT = 60 + 3 * int(os.environ.get("CCEX_PROBE_TIMEOUT") or 50)


def run_lines(cmd, timeout=SWITCH_WAIT):
    """Run something that switches accounts, and hand back the lines it had to say.

    Into a temporary file rather than a pipe. A pipe belongs to this process: if the view
    goes away mid-switch -- restarting into new code, or killed -- the read end closes and
    the switch dies of a broken pipe with the credential half moved. A file has no reader to
    lose, so the child finishes whatever it was doing either way.
    """
    with tempfile.TemporaryFile("w+", errors="replace") as f:
        subprocess.run(cmd, stdout=f, stderr=f, timeout=timeout)
        f.seek(0)
        return [l for l in f.read().splitlines() if l.strip()]


def hms(sec):
    """A countdown that visibly moves: seconds while they matter, days when they don't."""
    sec = int(max(0, sec))
    if sec >= 86400:
        return "%dd %02dh %02dm" % (sec // 86400, sec % 86400 // 3600, sec % 3600 // 60)
    if sec >= 3600:
        return "%dh %02dm %02ds" % (sec // 3600, sec % 3600 // 60, sec % 60)
    return "%dm %02ds" % (sec // 60, sec % 60)


class Line:
    """A row built from coloured pieces, truncated by what it actually shows.

    Slicing a string with escapes in it cuts colour codes in half; keeping the visible
    text separate from its colour is the cheapest way not to.
    """

    def __init__(self):
        self.parts = []

    def add(self, text, colour="", pad=None):
        text = str(text)
        if pad:
            text = text[:pad].ljust(pad)
        self.parts.append((text, colour))
        return self

    def render(self, width, colour=True):
        out, room = [], width
        for text, c in self.parts:
            if room <= 0:
                break
            text = text[:room]
            room -= len(text)
            out.append(("%s%s%s" % (c, text, RESET)) if (colour and c) else text)
        return "".join(out)


GAP = "    "        # between the two windows: each is a percentage, a bar and a clock, and
                    # they read as one thing only if there is space around them


def layout(width):
    """Column sizes for this terminal: the meters get the room, the rest gives way.

    Widest first -- a longer bar is worth more than a second on the clock, which is worth
    more than the age of a reading the panel also gives you.
    """
    bar = 16 if width >= 124 else 12 if width >= 100 else 10
    secs = width >= 104                      # a countdown to the second, not just the minute
    mail = 30 if width >= 130 else 26 if width >= 114 else 20
    cell = 5 + bar + 1 + (11 if secs else 10)
    fixed = 2 + 4 + mail + cell + len(GAP) + cell + 12
    return bar, secs, mail, cell, width >= fixed + 9


def fit_email(email, width):
    """Shorten an address without losing the part that tells accounts apart.

    Several accounts on one domain differ only to the left of the @, so a cut-off domain
    is the one thing worth dropping.
    """
    if len(email) <= width:
        return email
    local, at, _ = email.partition("@")
    if at and len(local) + 2 <= width:
        return local + "@…"
    return email[:max(0, width - 1)] + "…"


def meter(pct, limit, width=10, colour=True):
    """A bar, coloured by how close this window is to the cap that applies to it.

    The cap is drawn into the bar as a tick, because "79%" means something different on
    an account capped at 60 than on one running to 95.
    """
    pct = 0 if pct is None else pct
    cells = list(bar(pct, width))          # same fill rule as `ccex ls`, then decorated
    n = cells.count("█")
    ratio = pct / float(limit) if limit else 0
    c = GREEN if ratio < 0.5 else (YELLOW if ratio < 0.85 else RED)
    mark = int(round((limit or 100) / 100.0 * width)) - 1
    if 0 <= mark < width and mark >= n:
        cells[mark] = "╵"
    if not colour:
        return [("".join(cells), "")]
    return [("".join(cells[:n]), c), ("".join(cells[n:]), GREY)]


class View:
    def __init__(self, every=10, at=FIVE_AT, refresh=0, act=False, at_given=False,
                 verify=True):
        self.every, self.at, self.refresh, self.act = every, at, refresh, act
        self.at_given, self.verify = at_given, verify
        self.started = time.time()
        self.rows, self.live = [], None
        self.verdict, self.message = "", ""
        self.timer, self.note, self.busy = dict(NO_UNIT), "", ""
        self.asked, self.walked, self.pids = 0.0, 0.0, {}
        self.serving = False
        self.last_live, self.switches = None, []
        self.typed = ""                # account number being typed, waiting for y to confirm
        self.cursor = None             # email of the selected row, kept across re-sorts
        self.editing = None            # which window's cap is being typed: five, seven, None
        self.entry, self.capbuf = "", {}
        self.sampled = 0.0
        self.stamp = self.mtime()

    # ---- data -----------------------------------------------------------------

    def mtime(self):
        """Newest mtime across ccex's own files: a view left up for days must not run stale code.

        The dispatcher counts as ccex's code too -- a `git pull` that only touches
        `bin/ccex` has to restart this just as much as one that touches a module.
        """
        newest, lib = 0.0, os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for root, _, files in os.walk(lib):
            for f in files:
                if f.endswith((".py", ".sh")):
                    try:
                        newest = max(newest, os.stat(os.path.join(root, f)).st_mtime)
                    except OSError:
                        pass
        try:
            newest = max(newest, os.stat(CCEX).st_mtime)
        except OSError:
            pass
        return newest

    def systemd(self):
        if self.serving:
            return dict(NO_UNIT)       # this process *is* the daemon; it must not stand down
        if time.time() - self.asked < 30:
            return self.timer          # a unit does not start and stop between two ticks
        self.asked = time.time()
        return self.systemd_now()

    def systemd_now(self):
        """What the daemon is actually set to -- not what this view's flags say.

        A view that assumed its own defaults would happily predict against a threshold
        nothing is using, so the numbers come from the daemon itself.
        """
        out = dict(NO_UNIT)
        try:
            out["active"] = subprocess.run(
                ["systemctl", "--user", "is-active", "ccex-rotate.service"],
                capture_output=True, timeout=5).returncode == 0
            if not out["active"]:      # an older ccex left a wake-up timer; it still rotates
                out["legacy"] = subprocess.run(
                    ["systemctl", "--user", "is-active", "ccex-rotate.timer"],
                    capture_output=True, timeout=5).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return out
        if out["active"]:
            # `ccex rotate --bg` writes down what it installed, so this reads a number
            # rather than re-parsing the command line it was installed with.
            out.update({k: v for k, v in fresh(DAEMON).items() if k in out})
        return out

    def sample(self):
        """One data tick: re-read every account, record the burn, re-run the decision.

        The JSON is stat-gated and tiny; walking /proc for running sessions is neither, so
        it happens on its own slower clock. A session that started ten seconds ago showing
        up as `live` ten seconds late costs nothing; doing it every tick costs 10ms a tick.
        """
        now = time.time()
        if not self.serving and now - self.walked >= max(PROC_EVERY, self.every):
            self.pids, self.walked = live_map(), now      # nothing headless reads `live`
        rows = []
        for name, d in slots():
            a = account_json(name, d, now, self.pids)
            a["id"] = id_for(d) or 0
            burn.note(a["email"], a["five"], a["seven"])
            # Only the forecast reads a rate, and it only forecasts the account you are on.
            forecast = not self.serving and name == "default"
            a["rate_five"] = burn.rate(a["email"], "five_hour", now) if forecast else None
            a["rate_seven"] = burn.rate(a["email"], "seven_day", now) if forecast else None
            rows.append(a)
        rows.sort(key=lambda a: (a["id"] or 99, a["name"]))
        self.rows = rows
        self.timer = self.systemd()
        if not self.at_given and self.timer["at"]:
            self.at = int(self.timer["at"])   # the daemon's threshold is the one that will fire
        # `blind` has to match the tick's, or this view predicts NONE while the tick
        # switches to an account nothing has measured. Verification is what reads it.
        self.verdict, _, self.message = decide(rows, self.at, blind=self.verify)
        self.live = next((a for a in rows if a["name"] == "default"), None)
        if self.live:
            if self.last_live and self.last_live != self.live["email"]:
                self.switches.append((time.strftime("%H:%M:%S"),
                                      "%s -> %s" % (self.last_live, self.live["email"])))
                self.switches = self.switches[-3:]
            self.last_live = self.live["email"]
        self.sampled = now

    def tick_cmd(self):
        """`ccex rotate --tick`: it takes the lock, decides again and logs what it did.

        The view never moves a credential itself. Deciding twice is cheap, and the second
        decision is the authoritative one: `rotate` holds the lock across it.
        """
        return [CCEX, "rotate", "--tick", "--at", str(self.at), "--refresh", str(self.refresh)] \
            + ([] if self.verify else ["--no-verify"])

    def maybe_act(self):
        """Act on what the last sample said, if this view is the one doing the acting."""
        if self.timer["active"] or self.timer["legacy"]:
            return                     # something else is rotating and checking; only report
        if self.act and self.verdict == "SWITCH":
            self.background("rotating", self.tick_cmd())
        elif self.refresh and self.live and not self.live["live"]:
            old = self.live["age_s"]
            if old is None or old > self.refresh:
                # Nothing is reporting and the numbers have aged out: the one case where
                # this view is allowed to start a session, and never on the render thread.
                self.background("checking", [sys.executable, LIMITS, "--quiet",
                                             "--no-launch", "--max-age", str(self.refresh)])

    def background(self, label, cmd):
        """Anything that can take seconds runs here, so the second-by-second view never stalls."""
        if self.busy:
            return
        self.busy = label

        def run():
            try:
                lines = run_lines(cmd)
                self.note = lines[0][:160] if lines else ""
            except (OSError, subprocess.SubprocessError) as e:
                self.note = "%s failed: %s" % (label, e)
            finally:
                self.busy = ""
                self.sampled = 0.0        # whatever it changed, show it on the next tick

        threading.Thread(target=run, daemon=True).start()

    # ---- the prediction -------------------------------------------------------

    def forecast(self):
        """When the live account trips a cap, and where rotation would send it.

        Two separate questions: the cap it is heading for (needs a burn rate) and the
        account waiting for it (needs none). The second always answers, so a view with no
        history yet still tells you where you are going.
        """
        # Same ranking rotation will use, `blind` included, or the account named here is
        # not the one the switch goes to.
        live, room = self.live, ranked(self.rows, self.at, blind=self.verify)
        dest = room[0] if room else None
        if not live:
            return None, None, dest, "no live account"
        if live.get("held"):
            return None, None, None, "held out of the pool; rotation leaves it alone"
        windows = [("5h", "five", "rate_five", "five_resets")]
        # The 5-hour window is what moves you. The week only enters the forecast once it is
        # near its own cap -- before that, saying "the week runs out in three days" is true
        # and useless, and it would hide the 5-hour answer you actually act on.
        if (live["seven"] or 0) > WEEKLY_NEAR:
            windows.append(("weekly", "seven", "rate_seven", "seven_resets"))
        best, resets_first = None, []
        for label, key, rk, pk in windows:
            limit = cap(live, key, self.at)
            secs, resets = burn.eta(live[key], limit, live[rk], live[pk])
            if resets:
                resets_first.append(label)
            if secs is not None and (best is None or secs < best[0]):
                best = (secs, label, live[key], limit, live[rk])
        if best:
            return best, resets_first, dest, ""
        if any(live[k] is not None and live[k] >= cap(live, k, self.at) for _, k, _, _ in windows):
            return None, resets_first, dest, "already over its cap"
        if resets_first:
            return None, resets_first, dest, "%s window%s resets before the cap" % (
                " and ".join(resets_first), "" if len(resets_first) == 1 else "s")
        if live["rate_five"] is None and live["rate_seven"] is None:
            return None, resets_first, dest, "no burn rate yet - two readings apart needed"
        return None, resets_first, dest, "not climbing"

    def picked(self):
        """The account the digits typed so far name, if they name one yet."""
        return next((a for a in self.rows if str(a["id"]) == self.typed), None) if self.typed else None

    def selected(self):
        """The row the cursor is on: what the arrows moved to, or the account you are using."""
        return next((a for a in self.rows if a["email"] == self.cursor), None) or self.live

    def cap_start(self, window="five"):
        """Open the cap editor on the selected account, prefilled with what it caps now."""
        on = self.selected()
        if not on:
            return
        self.typed = ""
        self.editing = window
        if window == "five":
            self.capbuf = {}
        have = on["cap_" + window]
        self.entry = str(have) if have else ""

    def cap_key(self, key):
        """Digits, backspace, - to leave a window uncapped, enter to move on, esc to drop it."""
        if key.isdigit() and len(self.entry) < 3:
            self.entry += key
        elif key in ("\x7f", "\b"):
            self.entry = self.entry[:-1]
        elif key in ("-", "x", "X"):
            self.entry = ""
        elif key in ("\r", "\n"):
            self.capbuf[self.editing] = int(self.entry) if self.entry else None
            if self.editing == "five":
                return self.cap_start("seven")
            self.cap_apply()
        elif key in ("\x1b", "\x03"):
            self.editing, self.entry, self.capbuf = None, "", {}

    def cap_apply(self):
        """Hand the two numbers to `ccex pool cap`, which owns what a cap means."""
        on = self.selected()
        self.editing, self.entry = None, ""
        if not on:
            return
        cmd = [CCEX, "pool", "cap", on["email"]]
        if any(v is None for v in self.capbuf.values()):
            cmd.append("--clear")      # a window left empty goes back to the default
        for flag, w in (("--5h", "five"), ("--weekly", "seven")):
            if self.capbuf.get(w):
                cmd += [flag, str(self.capbuf[w])]
        self.capbuf = {}
        self.background("capping", cmd)

    def move(self, delta):
        """Walk the cursor, by account rather than by index, so a re-sort cannot lose it."""
        if not self.rows:
            return
        here = self.selected()
        at = self.rows.index(here) if here in self.rows else 0
        self.cursor = self.rows[max(0, min(len(self.rows) - 1, at + delta))]["email"]
        self.typed = ""

    # ---- rendering ------------------------------------------------------------

    def frame(self, width, height, colour=True):
        L, now = [], time.time()
        bar, secs, mail, cell, agecol = layout(width)
        live = self.live

        head = Line().add(" ccex ", BOLD + REV).add(" ")
        head.add("%d accounts" % len(self.rows), CYAN).add("  ")
        head.add("live: %s" % (live["email"] if live else "?")).add("  ")
        head.add("switch at %d%%%s" % (self.at, "" if self.at_given
                                        else " (daemon)" if self.timer.get("at") else ""), YELLOW).add("  ")
        head.add("every %s" % hm_short(self.every), GREY).add("  ")
        head.add(self.busy + "..." if self.busy else "", YELLOW)
        head.add(time.strftime(" %H:%M:%S"), DIM)
        L.append(head)

        hdr = Line().add("    # ", REV).add("ACCOUNT", REV, mail)
        hdr.add("5H", REV, cell + len(GAP)).add("WEEKLY", REV, cell)
        hdr.add(" ROTATION", REV, 12)
        if agecol:
            hdr.add("CHECKED", REV, 9)
        L.append(hdr)

        # What rotation is doing right now, one line per thing done, printed below everything
        # else and gone the moment the next switch starts its own. A switch that asks three
        # accounts takes most of a minute, and "now" on its own reads like a frozen view.
        # Anything older than a few minutes is a tick that died without clearing up.
        trail, age = [], 0
        try:
            age = now - os.path.getmtime(os.path.join(USAGE_DIR, ".step"))
            if age < 300:
                with open(os.path.join(USAGE_DIR, ".step")) as f:
                    trail = [l.strip() for l in f.read().splitlines() if l.strip()]
        except OSError:
            pass

        shown = self.rows
        # The trail is charged to the same height the accounts come out of, so a switch grows
        # the frame by nothing and the view does not scroll out from under itself.
        room = height - 9 - (1 if self.switches else 0) - (len(trail) + 1 if trail else 0)
        if len(shown) > room > 0:
            keep = [a for a in shown if a["name"] == "default"][:1]
            shown = (keep + [a for a in shown if a not in keep])[:room]
        for a in shown:
            here = a["name"] == "default"
            # The account you are billing is the one fact you look for first, so it gets an
            # arrow, not a punctuation mark in a column of them.
            on = self.selected()
            cursor = bool(on and on["email"] == a["email"])
            row = Line().add("›", CYAN + BOLD) if cursor else Line().add(" ")
            row.add("▶", GREEN + BOLD) if here else row.add(" ")
            row.add("%3s " % (a["id"] or "-"), BOLD if here else GREY)
            row.add(fit_email(a["email"], mail - 1), BOLD if here else DIM, mail)
            for n, (key, rk, pk) in enumerate((("five", "rate_five", "five_resets"),
                                               ("seven", "rate_seven", "seven_resets"))):
                limit = cap(a, key, self.at)
                pct = a[key]
                if pct is None:
                    row.add("-", GREY, cell)
                else:
                    row.add("%3d%% " % pct, BOLD if here else "")
                    for text, c in meter(pct, limit, bar, colour):
                        row.add(text, c)
                    row.add(" ")
                    t, clock = a[pk], cell - bar - 6
                    left = t - now if t else None
                    if left is None:
                        row.add("", "", clock)
                    elif left <= GRACE:
                        row.add("new".ljust(clock), GREEN)
                    else:
                        row.add(hms(left) if secs else hm(left),
                                YELLOW if left < 600 else "", clock)
                if n == 0:
                    row.add(GAP)
            # Why rotation would or would not choose this account, in words: the marks it
            # used to be (c, x, X) all meant something about this one question.
            state, tint = "in pool", GREY      # not `colour`: that is this frame's own flag
            if a["held_auto"]:
                state, tint = "retired", RED
            elif a["held"]:
                state, tint = "held", YELLOW
            elif a["cap_five"] or a["cap_seven"]:
                state, tint = "cap %s/%s" % (a["cap_five"] or "-", a["cap_seven"] or "-"), CYAN
            row.add(" " + state, tint, 12)
            if agecol:
                row.add("live" if a["live"] else age_text(a["age_s"]),
                        GREEN if a["live"] else GREY, 9)
            L.append(row)

        L.append(Line())               # a blank line, not a rule: the panel below is words
        best, resets_first, dest, why = self.forecast()
        nxt = Line().add(" next switch  ", BOLD)
        if self.verdict == "SWITCH":
            nxt.add("now", RED).add(": %s" % self.message)
        elif best:
            secs, label, pct, limit, rate = best
            nxt.add("in %s" % hms(secs), RED if secs < 900 else YELLOW)
            nxt.add(" (%s)" % time.strftime("%H:%M", time.localtime(now + secs)), DIM)
            nxt.add("  %s is at %d%%, climbing %.1f%% an hour to its %d%% cap"
                    % (label, pct, rate, limit))
        elif self.verdict == "NONE":
            nxt.add("nowhere to go", RED).add(": %s" % self.message)
        else:
            nxt.add("not yet", GREEN).add("  %s" % (why or self.message))
        L.append(nxt)

        to = Line().add("              ", "")
        if dest:
            to.add("-> ", GREY).add("%s %s" % (dest["id"], dest["email"]), GREEN + BOLD)
            if dest["five"] is None or dest["seven"] is None:
                # Reached only once every measured account is spent. There is no percentage
                # to draw, and the switch reads it before landing on it.
                to.add(", which nothing has measured yet", GREY)
            else:
                to.add(" at %s" % reads(dest))
                if dest["age_s"] and dest["age_s"] > 900:
                    to.add(" (numbers %dm old)" % (dest["age_s"] // 60), GREY)
        elif self.verdict != "SWITCH":
            to.add("no account is under its cap right now", RED)
        if resets_first and best:
            to.add("; %s resets first" % " and ".join(resets_first), GREY)
        L.append(to)

        t = self.timer
        rot = Line().add(" rotation     ", BOLD)
        if t["active"]:
            rot.add("rotating on data change", GREEN)
            # When the next read is due. The daemon also wakes on a data change, so it can
            # come sooner than this -- never later, which is what makes it worth counting.
            due, ev = "", paced(t["every"])
            try:
                left = ev - (now - os.path.getmtime(os.path.join(USAGE_DIR, BEAT)))
                if ev:
                    due = ", next read due now" if left < 1 else ", next read in %ds" % round(left)
            except OSError:
                pass
            rot.add(", every %s%s at %s%%" % (t["every"] or "?", due, t["at"] or "?"))
            if t["refresh"]:
                rot.add(", one real check after %ss of silence" % t["refresh"])
        elif t.get("legacy"):
            rot.add("old wake-up timer", YELLOW).add(" is doing it; `ccex rotate --bg` "
                                                     "switches to the moment usage says so")
        elif self.act:
            rot.add("rotating from here", YELLOW).add(", nothing running in the background")
        else:
            rot.add("watching only", GREY).add("  (`ccex ls -w --rotate`, or `ccex rotate --bg`)")
        if self.note:
            rot.add("  %s" % self.note, DIM)
        L.append(rot)

        if self.switches:
            L.append(Line().add(" rotated      ", BOLD)
                     .add("  ".join("%s %s" % s for s in self.switches[-2:]), CYAN))

        keys, pick = Line(), self.picked()
        on = self.selected()
        if self.editing and on:
            keys.add(" cap           ", BOLD)
            keys.add("%s %s" % (on["id"], on["email"]), CYAN + BOLD).add("   ")
            for w, label in (("five", "5h"), ("seven", "weekly")):
                if w == self.editing:
                    keys.add("%s: " % label, BOLD).add((self.entry or "-") + "▏", YELLOW + BOLD)
                else:
                    was = self.capbuf.get(w) if w in self.capbuf else on["cap_" + w]
                    keys.add("%s: %s" % (label, was or "-"), GREY)
                keys.add("  ")
            keys.add("enter", REV).add(" next  ").add("-", REV).add(" uncapped  ")
            keys.add("esc", REV).add(" cancel", "")
        elif pick:
            keys.add(" switch to    ", BOLD)
            keys.add("%s %s" % (pick["id"], pick["email"]), GREEN + BOLD)
            keys.add("?  ").add("y", REV).add(" yes, anything else cancels", YELLOW)
        elif self.typed:
            keys.add(" switch to    ", BOLD).add(self.typed, YELLOW + BOLD)
            keys.add("?  no account has that number -- keep typing, or any other key to cancel",
                     YELLOW)
        else:
            keys.add(" keys         ", BOLD)
            keys.add("↑↓", REV).add(" select  ").add("enter", REV).add(" switch  ")
            keys.add("←→", REV).add(" out/in  ")
            keys.add("a", REV).add(" add  ").add("c", REV).add(" cap  ")
            keys.add("+/-", REV).add(" pace  ").add("r", REV).add(" refresh  ")
            keys.add("q", REV).add(" quit   ")
            keys.add("up %s" % hm(now - self.started), GREY)
        L.append(keys)

        if trail:
            L.append(Line().add(" switching    ", BOLD)
                     .add(hm_short(int(age)) + " ago", GREY))
            for i, one in enumerate(trail):
                last = i == len(trail) - 1
                L.append(Line().add("              ", "")
                         .add(("-> " if last else "   "), GREY)
                         .add(one, YELLOW if last else GREY))
        return [l.render(width, colour) for l in L]


def hm_short(sec):
    return "%ds" % sec if sec < 60 else ("%dm" % (sec // 60) if sec < 3600 else "%dh" % (sec // 3600))


def serve(v):
    """`ccex rotate --serve`: the data loop with no screen, switching the moment a cap goes.

    A timer that fires every five minutes leaves a crossed cap sitting for up to five
    minutes. This notices within one --every, because a statusline write is a file whose
    mtime it is already watching, and it costs a stat per file to find out.
    """
    beat, said = 0.0, 0.0
    try:                    # what is actually running, for `ccex ls -w` to predict against
        save(DAEMON, {"at": v.at, "every": "%ds" % v.every, "refresh": v.refresh,
                      "since": time.strftime("%F %T")})
    except OSError:
        pass
    print("ccex: rotating on data change, every %ds at %d%%%s" %
          (v.every, v.at, ", one real check when nothing has reported for %ds" % v.refresh
           if v.refresh else ""), flush=True)
    while True:
        v.sample()
        try:                # one stat's worth of "I just looked", for the countdown to use
            with open(os.path.join(USAGE_DIR, BEAT), "w") as f:
                f.write(v.message + "\n")
        except OSError:
            pass
        due = v.refresh and time.time() - beat >= v.refresh
        if v.verdict == "SWITCH" or due:
            beat = time.time()
            try:
                for line in run_lines(v.tick_cmd()):
                    print(line, flush=True)     # the journal, and only when something happened
            except (OSError, subprocess.SubprocessError) as e:
                print("ccex: tick failed: %s" % e, flush=True)
        elif time.time() - said >= 60:
            # `ccex rotate --status` asks when this last looked. With nothing to switch there
            # is no tick to write that down, so the loop says so itself.
            said = time.time()
            try:
                with open(os.path.join(ROOT, ".usage", ".monitor-last"), "w") as f:
                    f.write("%s\nccex: %s\n" % (time.strftime("%F %T"), v.message))
            except OSError:
                pass
        if v.mtime() != v.stamp and not v.busy:
            print("ccex: ccex was updated; restarting into it", flush=True)
            return 0                   # Restart=always brings it straight back, on new code
        time.sleep(v.every)


def main():
    argv = sys.argv[1:]
    every, at, refresh, act, once = 10, FIVE_AT, 0, False, "--once" in argv
    verify = "--no-verify" not in argv
    at_given = False
    for i, a in enumerate(argv):
        if a == "--every" and i + 1 < len(argv):
            every = max(1, int(argv[i + 1]))
        elif a == "--at" and i + 1 < len(argv):
            at, at_given = int(argv[i + 1]), True
        elif a == "--refresh" and i + 1 < len(argv):
            refresh = int(argv[i + 1])
        elif a == "--rotate":
            act = True
    if "--serve" in argv:
        v = View(every, at, refresh, False, at_given, verify)
        v.serving = True
        return serve(v)
    v = View(every, at, refresh, act, at_given, verify)
    v.sample()

    tty_in, tty_out = sys.stdin.isatty(), sys.stdout.isatty()
    if once or not tty_out:
        # Piped to a file or a test: plain text, no escapes, one block per data tick.
        while True:
            width = shutil.get_terminal_size((120, 40)).columns if tty_out else 120
            print("\n".join(v.frame(width, 40, colour=False)), flush=True)
            if once:
                return 0
            time.sleep(v.every)
            v.sample()

    old = termios.tcgetattr(sys.stdin) if tty_in else None
    painted, size_was = [], None
    sys.stdout.write("\033[?1049h\033[?25l")
    try:
        if tty_in:
            tty.setcbreak(sys.stdin.fileno())
        while True:
            size = shutil.get_terminal_size((120, 40))
            lines = v.frame(size.columns, size.lines)[:size.lines]
            if size != size_was:
                painted, size_was = [], size
                sys.stdout.write("\033[2J")
            out = []
            for i, l in enumerate(lines):
                if i >= len(painted) or painted[i] != l:
                    out.append("\033[%d;1H%s\033[K" % (i + 1, l))
            if len(painted) > len(lines):
                out.append("\033[%d;1H\033[J" % (len(lines) + 1))
            painted = lines
            if out:
                sys.stdout.write("".join(out))
                sys.stdout.flush()
            typing = ""
            if tty_in:
                r, _, _ = select.select([sys.stdin], [], [], 1.0)
                if r:
                    # Read the descriptor, not the buffered stream: `stdin.read(1)` leaves
                    # the rest of a fast "12y" sitting in Python's buffer, where select
                    # cannot see it, and each key then waits out a whole second.
                    try:
                        typing = os.read(sys.stdin.fileno(), 64).decode("utf8", "replace")
                    except OSError:
                        typing = ""

            else:
                time.sleep(1.0)
            i = 0
            while i < len(typing):
                key = typing[i]
                if key == "\x1b" and typing[i + 1:i + 2] in ("[", "O"):
                    arrow = typing[i + 2:i + 3]      # \x1b[A / \x1bOA, terminal depending
                    i += 3
                    if v.editing:
                        continue                     # arrows mean nothing to a percentage
                    if arrow in ("A", "B"):
                        v.move(-1 if arrow == "A" else 1)
                    elif arrow in ("C", "D"):
                        # Sideways is in and out of the pool: right pushes the account out
                        # of rotation, left brings it back -- including one it retired.
                        on = v.selected()
                        if on:
                            v.background("pool", [CCEX, "pool",
                                                  "out" if arrow == "C" else "in", on["email"]])
                    continue
                i += 1
                if v.editing:
                    v.cap_key(key)
                    continue
                if key in ("q", "Q", "\x03"):
                    return 0
                if key in ("c", "C"):
                    v.cap_start()
                elif key in ("\r", "\n"):
                    on = v.picked() or v.selected()
                    if on and on["name"] != "default":
                        v.background("switching", [CCEX, "use", on["email"], "--no-report"])
                    v.typed = ""
                elif key.isdigit() and (v.typed or key != "0") and len(v.typed) < 3:
                    # The numbers in the # column are the ones `ccex use` takes, so typing
                    # one here means the same thing it means there -- and they are typed
                    # rather than read one key at a time, so account 12 is reachable.
                    v.typed += key
                    if v.picked():
                        v.cursor = v.picked()["email"]   # typing moves the cursor too
                elif key in ("\x7f", "\b") and v.typed:
                    v.typed = v.typed[:-1]
                elif key in ("y", "Y") and v.picked():
                    v.background("switching", [CCEX, "use", v.picked()["email"], "--no-report"])
                    v.typed = ""
                elif key in ("a", "A"):
                    v.typed = ""
                    handover(old, [CCEX, "add"])
                    painted, size_was = [], None      # the login wrote all over the screen
                    v.sampled = v.walked = 0.0
                elif key in ("+", "="):
                    v.every = next((p for p in PRESETS if p > v.every), PRESETS[-1])
                    v.typed = ""
                elif key in ("-", "_"):
                    v.every = next((p for p in reversed(PRESETS) if p < v.every), PRESETS[0])
                    v.typed = ""
                elif key in ("r", "R"):
                    v.typed = ""
                    v.sampled = v.walked = 0.0  # r means everything, /proc included
                    if v.refresh:               # and "ask for real", where asking is allowed
                        v.background("checking", [sys.executable, LIMITS, "--quiet", "--force"])
                else:
                    v.typed = ""                # anything else cancels what was typed
            if time.time() - v.sampled >= v.every:
                v.sample()
                v.maybe_act()
                # ccex changed under us: restart into the new code -- but not while a
                # switch is running in the background. Replacing this process closes the
                # pipes its child is writing to, and the child dies on its next line, half
                # way through moving a credential. It restarts on the next tick instead.
                if v.mtime() != v.stamp and not v.busy:
                    sys.stdout.write("\033[?25h\033[?1049l")
                    sys.stdout.flush()
                    if old:
                        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
                    os.execv(CCEX, [CCEX, "ls", "-w"] + argv)
    except KeyboardInterrupt:
        return 0
    finally:
        sys.stdout.write("\033[?25h\033[?1049l")
        sys.stdout.flush()
        if old:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)


if __name__ == "__main__":
    sys.exit(main())
