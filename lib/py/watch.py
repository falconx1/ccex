"""`ccex ls -w`: the account list, live, with the rotation monitor folded into it.

Two cadences, one process. The countdowns re-render every second from reset timestamps
that are already known, which costs nothing; the numbers behind them are re-read on the
slower --every tick, and only that tick walks /proc or asks systemd anything. Nothing
here starts a session unless --refresh says it may, and then off the render loop, so the
view never freezes waiting for one.
"""
import os, select, shutil, subprocess, sys, termios, threading, time, tty

import burn
from ccexlib import ROOT, fresh, hm, id_for, save, slots
from decide import FIVE_AT, cap, decide, ranked
from usage import GRACE, account_json, age_text, bar, live_map

PRESETS = [10, 30, 60, 300, 900, 1800]
PROC_EVERY = 15         # seconds between /proc walks: the one read that is not free
WEEKLY_NEAR = 90        # below this the week is not what the next switch will be about
NO_UNIT = {"active": False, "legacy": False, "at": None, "refresh": None, "every": None}
DAEMON = os.path.join(ROOT, ".usage", "daemon.json")     # written by the daemon itself
LIMITS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "limits.py")
CCEX = os.environ.get("CCEX_BIN") or "ccex"

RESET, BOLD, DIM, REV = "\033[0m", "\033[1m", "\033[2m", "\033[7m"
RED, GREEN, YELLOW, CYAN, GREY = "\033[31m", "\033[32m", "\033[33m", "\033[36m", "\033[90m"


def run_lines(cmd, timeout=180):
    """Run something that switches accounts, and hand back the lines it had to say."""
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return [l for l in (out.stdout + out.stderr).splitlines() if l.strip()]


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
    def __init__(self, every=10, at=FIVE_AT, refresh=0, act=False, at_given=False):
        self.every, self.at, self.refresh, self.act = every, at, refresh, act
        self.at_given = at_given
        self.started = time.time()
        self.rows, self.live = [], None
        self.verdict, self.message = "", ""
        self.timer, self.note, self.busy = dict(NO_UNIT), "", ""
        self.asked, self.walked, self.pids = 0.0, 0.0, {}
        self.serving = False
        self.last_live, self.switches = None, []
        self.typed = ""                # account number being typed, waiting for y to confirm
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
            # Rates are drawn, not decided on, so the daemon computes none of them, and
            # only the live account's week is ever forecast.
            a["rate_five"] = None if self.serving else burn.rate(a["email"], "five_hour", now)
            a["rate_seven"] = (None if self.serving or name != "default"
                               else burn.rate(a["email"], "seven_day", now))
            rows.append(a)
        rows.sort(key=lambda a: (a["id"] or 99, a["name"]))
        self.rows = rows
        self.timer = self.systemd()
        if not self.at_given and self.timer["at"]:
            self.at = int(self.timer["at"])   # the daemon's threshold is the one that will fire
        self.verdict, _, self.message = decide(rows, self.at)
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
        return [CCEX, "rotate", "--tick", "--at", str(self.at), "--refresh", str(self.refresh)]

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
        live, room = self.live, ranked(self.rows, self.at)
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

    # ---- rendering ------------------------------------------------------------

    def frame(self, width, height, colour=True):
        L, now = [], time.time()
        capcol = any(a["cap_five"] or a["cap_seven"] for a in self.rows)
        wide = width >= 132
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

        hdr = Line().add("  # ", REV).add("ACCOUNT", REV, 20)
        if wide:
            hdr.add("EMAIL", REV, 29)
        hdr.add("5H", REV, 29).add("WEEKLY", REV, 29)
        if capcol:
            hdr.add("CAP", REV, 7)
        hdr.add("RATE", REV, 9).add("CHECKED", REV, 9)
        L.append(hdr)

        shown = self.rows
        room = height - 9 - (1 if self.switches else 0)
        if len(shown) > room > 0:
            keep = [a for a in shown if a["name"] == "default"][:1]
            shown = (keep + [a for a in shown if a not in keep])[:room]
        for a in shown:
            mark = "*" if a["name"] == "default" else " "
            if a["held_auto"]:
                mark += "X"
            elif a["held"]:
                mark += "x"
            elif a["cap_five"] or a["cap_seven"]:
                mark += "c"
            else:
                mark += " "
            row = Line().add("%3s" % (a["id"] or "-"), BOLD if mark[0] == "*" else "")
            row.add(mark, YELLOW if "x" in mark.lower() else CYAN)
            row.add(a["name"][:18], BOLD if mark[0] == "*" else "", 19)
            if wide:
                row.add(a["email"], DIM, 29)
            for key, rk, pk in (("five", "rate_five", "five_resets"),
                                ("seven", "rate_seven", "seven_resets")):
                limit = cap(a, key, self.at)
                pct = a[key]
                if pct is None:
                    row.add("-", GREY, 29)
                    continue
                for text, c in meter(pct, limit, 10, colour):
                    row.add(text, c)
                row.add("%4d%% " % pct, "")
                t = a[pk]
                left = t - now if t else None
                if left is None:
                    row.add("", "", 13)
                elif left <= GRACE:
                    row.add("new".ljust(13), GREEN)
                else:
                    row.add(hms(left), YELLOW if left < 600 else "", 13)
            if capcol:
                own = a["cap_five"] or a["cap_seven"]
                row.add("%s/%s" % (a["cap_five"] or "-", a["cap_seven"] or "-") if own else "-",
                        GREY, 7)
            row.add("+%.1f%%/h" % a["rate_five"] if a["rate_five"] else "-", GREY, 9)
            row.add("live" if a["live"] else age_text(a["age_s"]),
                    GREEN if a["live"] else GREY, 9)
            L.append(row)

        L.append(Line().add("─" * width, GREY))
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
            to.add("-> ", GREY).add("%s %s" % (dest["id"], dest["name"]), GREEN + BOLD)
            to.add(" at %d%% 5h / %d%% weekly" % (dest["five"], dest["seven"]))
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
            rot.add(", every %s at %s%%" % (t["every"] or "?", t["at"] or "?"))
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
        if pick:
            keys.add(" switch to    ", BOLD)
            keys.add("%s %s" % (pick["id"], pick["name"]), GREEN + BOLD)
            keys.add(" (%s)" % pick["email"], DIM)
            keys.add("?  ").add("y", REV).add(" yes, anything else cancels", YELLOW)
        elif self.typed:
            keys.add(" switch to    ", BOLD).add(self.typed, YELLOW + BOLD)
            keys.add("?  no account has that number -- keep typing, or any other key to cancel",
                     YELLOW)
        else:
            keys.add(" keys         ", BOLD)
            keys.add("number", REV).add(" switch to that account (y to confirm)  ")
            keys.add("+/-", REV).add(" pace  ").add("r", REV).add(" refresh  ")
            keys.add("q", REV).add(" quit   ")
            keys.add("up %s" % hm(now - self.started), GREY)
        L.append(keys)
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
        if v.mtime() != v.stamp:
            print("ccex: ccex was updated; restarting into it", flush=True)
            return 0                   # Restart=always brings it straight back, on new code
        time.sleep(v.every)


def main():
    argv = sys.argv[1:]
    every, at, refresh, act, once = 10, FIVE_AT, 0, False, "--once" in argv
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
        v = View(every, at, refresh, False, at_given)
        v.serving = True
        return serve(v)
    v = View(every, at, refresh, act, at_given)
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
                if typing.startswith("\x1b"):
                    typing = ""             # an arrow or function key, not something typed
            else:
                time.sleep(1.0)
            for key in typing:
                if key in ("q", "Q", "\x03"):
                    return 0
                if key.isdigit() and (v.typed or key != "0") and len(v.typed) < 3:
                    # The numbers in the # column are the ones `ccex use` takes, so typing
                    # one here means the same thing it means there -- and they are typed
                    # rather than read one key at a time, so account 12 is reachable.
                    v.typed += key
                elif key in ("\x7f", "\b") and v.typed:
                    v.typed = v.typed[:-1]
                elif key in ("y", "Y") and v.picked():
                    v.background("switching", [CCEX, "use", v.typed, "--no-check"])
                    v.typed = ""
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
                if v.mtime() != v.stamp:  # ccex changed under us: restart into the new code
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
