"""ccex on the panel: what the live account has left, and every other account one click away.

An AppIndicator, which is what the desktop's own tray extension already draws -- nothing
pinned to a GNOME version and no shell extension to install. The numbers are read here the
way `ccex ls` reads them, from files, so putting ccex in the top bar never starts a session;
a click goes back out through `ccex use`, so it gets the same reading, the same lock and the
same refusals the terminal would.
"""
import os
import sys
import time

import gi

gi.require_version("Gtk", "3.0")

IND = None
for ns in ("AyatanaAppIndicator3", "AppIndicator3"):   # the fork, then the name it was before
    try:
        gi.require_version(ns, "0.1")
        IND = getattr(__import__("gi.repository", fromlist=[ns]), ns)
        break
    except (ValueError, ImportError):
        continue
if IND is None:
    sys.exit("ccex: the tray needs the appindicator typelib\n"
             "      sudo apt install gir1.2-ayatanaappindicator3-0.1")

from gi.repository import Gio, GLib, Gtk    # noqa: E402  -- after require_version, as gi insists

from ccexlib import BASE, ROOT, canon, hm, id_for, load, slots
from decide import FIVE_AT, cap
from usage import GRACE, account_json, live_map

CCEX = os.environ.get("CCEX_BIN") or "ccex"
SHARE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                     "share")
EVERY = 10            # seconds between reads: some file reads and one /proc walk, no session
GUIDE = "wwwwwwwwwwwwww 100%"    # how much room the panel keeps for the label, at its widest
WIDTH = 10            # cells per meter, the same ten `ccex ls` draws
USED, ROOM, OVER = "█", "▒", "░"    # spent, still yours to spend, and past the cap: three
                                    # shades because a menu label cannot carry three colours
FIG = "\u2007"        # a space exactly as wide as a digit, which is what a panel menu has
                      # instead of columns: its font is proportional, but its digits are not
NEAR = 5              # points below where rotation would move off: close enough to say so
FILL = ("\u2009", "\u200a")   # a thin space and a hair space: the coarse one does most of the
                             # padding and the fine one closes what it cannot, to the pixel


def notify(summary, body=""):
    """Say how a switch went, through the desktop's own notification service.

    Called straight over D-Bus rather than through libnotify, because that is one less
    typelib to have installed for a line of text.
    """
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        r = bus.call_sync("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                          "org.freedesktop.Notifications", "Notify",
                          GLib.Variant("(susssasa{sv}i)",
                                       ("ccex", notify.last, "ccex", summary, body, [], {}, 6000)),
                          None, Gio.DBusCallFlags.NONE, 2000, None)
        notify.last = r.unpack()[0]      # replace the last one rather than stack up a column
    except GLib.Error:
        pass                             # a desktop with no notifications is not a reason to stop


notify.last = 0


def meter(p, limit):
    """`██████▒▒░░` -- spent, what is left before rotation moves off, and what the cap holds
    back from you entirely. A window with no reading yet draws as an empty one.

    The terminal's bar has two parts because it has colour and a CAP column to say the rest.
    A menu row has neither, so the third part is drawn: an account capped at 60% shows four
    cells it will never be allowed to spend, which is the thing a plain meter hides.

    All three glyphs come from the same block and are the same width, so a row's later
    columns land where every other row's do.
    """
    # A window nobody has measured is drawn as the empty one it is, not as an unavailable
    # one: ░ means "you will never be allowed to spend this", and a fresh account is the
    # opposite of that. The row says `new` beside it either way.
    used = int(round(min(p or 0, 100) / 100.0 * WIDTH))
    room = max(0, int(round(min(limit, 100) / 100.0 * WIDTH)) - used)
    return USED * used + ROOM * room + OVER * (WIDTH - used - room)


def pct(p):
    return ("%d%%" % p).rjust(4, FIG) if p is not None else FIG * 3 + "-"


def num(n):
    return str(n or "-").rjust(2, FIG)


def left(t, now):
    """How long until that window comes back -- or `new`, in the terminal's own word for one
    that already came back and has had nothing measured since."""
    return hm(t - now) if t and t - now > GRACE else "new"


def threshold():
    """What rotation is actually running at, which is not always the built-in default.

    Warning about 90% while the daemon moves off at 80% would be a warning about the wrong
    number -- and about a switch that already happened.
    """
    at = load(os.path.join(ROOT, ".usage", "daemon.json")).get("at")
    return int(at) if str(at or "").isdigit() else FIVE_AT


def read():
    """Every account as the panel draws it: the live one, then the rest in `ccex ls` order."""
    now, pids = time.time(), live_map()
    rows = []
    for name, d in slots():
        a = account_json(name, d, now, pids)
        a["id"] = id_for(d)
        a["current"] = os.path.realpath(d) == os.path.realpath(BASE)
        a["short"] = canon(a["email"]) if a["email"] else name
        rows.append(a)
    # Emptiest 5-hour window first. The menu answers one question -- which account do I go
    # to -- and the account with the most room answers it far more often than the account
    # with the lowest number. The numbers stay in their column, which is what keeps
    # `ccex use 3` and the third row the same account when the order moves.
    rows.sort(key=lambda a: (a["five"] or 0, a["seven"] or 0, a["id"] or 999))
    return now, rows


def parts(a, now):
    """One row's cells, before any of them is padded to line up with the rows around it."""
    return {"lead": "●" if a["current"] else num(a["id"]),
            "name": a["short"],
            "five": left(a["five_resets"], now),
            "week": left(a["seven_resets"], now)}


class Columns:
    """The menu's columns padded to one width each, in a font that has no fixed one.

    A menu label is plain text -- no markup survives the trip to the panel -- and the shell
    draws it in the desktop's UI font, where no two letters are the same width. Counting
    characters cannot line up a column in that; measuring can. Pango is asked what each cell
    comes to in that font, and the difference is made up in thin and hair spaces, which
    lands every row's next column on the same pixel.

    Everything is measured in Pango units and padded in fixed spaces, so both scale with the
    font and the columns hold at whatever size the panel is drawn.
    """

    PADDED = ("lead", "name", "five")      # the week's clock is last on the row: nothing
                                           # comes after it to line up with

    def __init__(self):
        self.layout = Gtk.Label().create_pango_layout("")
        self.fill = sorted((w, c) for w, c in ((self.width(c), c) for c in FILL) if w)[::-1]
        self.pads = {}

    def width(self, text):
        self.layout.set_text(text, -1)
        return self.layout.get_size()[0]

    def measure(self, rows, now):
        """Re-measure every column. The countdowns change width as they tick, so this is
        every draw, not only when the accounts change -- some thirty text measurements."""
        seen = {k: set() for k in self.PADDED}
        for a in rows:
            cells = parts(a, now)
            for k in self.PADDED:
                seen[k].add(cells[k])
        self.pads = {k: self.even(v) for k, v in seen.items()}

    def even(self, cells):
        w = {c: self.width(c) for c in cells}
        wide = max(w.values()) if w else 0
        if not self.fill:      # a font with none of those spaces: fall back to counting letters
            longest = max((len(c) for c in cells), default=0)
            return {c: c.ljust(longest) for c in cells}
        out = {}
        for c, got in w.items():
            gap, padded = wide - got, c
            for unit, ch in self.fill:
                padded += ch * (gap // unit)
                gap %= unit
            out[c] = padded
        return out

    def __call__(self, key, cell):
        return self.pads.get(key, {}).get(cell, cell)


def row_label(a, now, col, at):
    """`2  dev-team011   5h  90% █████████░ 50m  ·  wk  71% ███████▒▒▒ 5d 9h30m` -- one row.

    The columns of the live view in its order -- the number, the account, then each window
    as a percentage, its meter and the clock it resets on. The live account gets the same
    row as everyone else, marked where its number would be.
    """
    c = parts(a, now)
    tail = "  ·  retired" if a["held_auto"] else ("  ·  held" if a["held"] else "")
    return "%s  %s   5h %s %s %s  ·  wk %s %s %s%s" % (
        col("lead", c["lead"]), col("name", c["name"]),
        pct(a["five"]), meter(a["five"], cap(a, "five", at)), col("five", c["five"]),
        pct(a["seven"]), meter(a["seven"], cap(a, "seven", at)), c["week"], tail)


class Tray:
    """One indicator, one menu, rebuilt only when the accounts themselves change."""

    def __init__(self):
        self.ind = IND.Indicator.new_with_path(
            "ccex", "ccex-symbolic", IND.IndicatorCategory.APPLICATION_STATUS, SHARE)
        self.ind.set_status(IND.IndicatorStatus.ACTIVE)
        self.ind.set_title("ccex")
        self.menu = Gtk.Menu()
        self.ind.set_menu(self.menu)
        self.items = {}       # email -> the row that switches to it, so a tick can relabel it
        self.head = None
        self.shape = None     # which accounts the menu was built for
        self.busy = False     # a switch is out; the numbers it lands on are the ones to show
        self.on = None        # who was live at the last tick, so a move can announce itself
        self.warned = {}      # (email, window) -> the reset we already warned about
        self.cols = Columns()  # what each cell comes to in the panel's own font
        self.tick()
        GLib.timeout_add_seconds(EVERY, self.tick)

    # -- drawing -------------------------------------------------------------------------

    def tick(self):
        try:
            self.draw()
        except Exception as e:              # a bad read must not take the timeout with it:
            self.ind.set_label("ccex ?", GUIDE)   # PyGObject drops a source that raises, and
            print("ccex: tray: %s" % e, file=sys.stderr, flush=True)   # the panel would freeze
        return True           # GLib keeps a timeout that says so

    def draw(self):
        now, rows = read()
        here = next((a for a in rows if a["current"]), None)
        others = [a for a in rows if not a["current"]]
        shape = tuple(a["email"] for a in others)
        if shape != self.shape:
            self.build(others)
            self.shape = shape
        self.cols.measure(rows, now)
        at = threshold()      # where rotation is really moving off, which is what a cap caps
        self.head.set_label(row_label(here, now, self.cols, at) if here
                            else "no account is logged in")
        for a in others:
            item = self.items.get(a["email"])
            if item:
                item.set_label(row_label(a, now, self.cols, at))
        if not self.busy:
            self.ind.set_label("" if here is None else "%s %s" % (here["short"],
                                                                 (pct(here["five"])).strip()),
                               GUIDE)
        self.moved(here, now)
        if here:
            self.nearly(here)

    def moved(self, here, now):
        """One place says an account changed, whoever changed it.

        A click, `ccex use` in a terminal and the daemon rotating at three in the morning
        all land the same way -- as a different account being live at the next tick -- so
        the panel says so once, from here, rather than only for the switches it started.
        """
        was, self.on = self.on, here and here["email"]
        if was and self.on and was != self.on:
            notify("now on %s" % here["short"],
                   "5h %s  ·  week %s  ·  5h window resets %s"
                   % (pct(here["five"]).strip(), pct(here["seven"]).strip(),
                      left(here["five_resets"], now)))

    def nearly(self, a):
        """A word before rotation moves, not after: this account is nearly out of room.

        Once per window, not once per tick -- the reset time is what re-arms it, so a
        window that starts over can warn again and one that is simply sitting at 87% does
        not say so every ten seconds.
        """
        at = threshold()
        for key, word in (("five", "5h"), ("seven", "weekly")):
            limit, p = cap(a, key, at), a[key]
            if p is None or not limit - NEAR <= p < limit:
                continue          # under it, or already over it -- and over it is the switch
            token = (a["email"], key)
            if self.warned.get(token) == a[key + "_resets"]:
                continue
            self.warned[token] = a[key + "_resets"]
            notify("%s is near %d%%" % (a["short"], limit),
                   "%s window at %d%%; rotation moves off at %d%%" % (word, p, limit))

    def build(self, others):
        """The menu, whenever the set of accounts is not the one it was built from."""
        for child in self.menu.get_children():
            self.menu.remove(child)
        self.items = {}
        self.head = Gtk.MenuItem(label="")
        self.head.set_sensitive(False)
        self.menu.append(self.head)
        self.menu.append(Gtk.SeparatorMenuItem())
        for a in others:
            item = Gtk.MenuItem(label="")
            item.connect("activate", self.on_switch, a["email"], a["short"])
            self.menu.append(item)
            self.items[a["email"]] = item
        if not others:
            none = Gtk.MenuItem(label="no other account is parked  ·  ccex add")
            none.set_sensitive(False)
            self.menu.append(none)
        self.menu.append(Gtk.SeparatorMenuItem())
        rotate = Gtk.MenuItem(label="Rotate now")
        rotate.connect("activate", self.on_rotate)
        self.menu.append(rotate)
        quit_ = Gtk.MenuItem(label="Quit")
        quit_.connect("activate", lambda *_: Gtk.main_quit())
        self.menu.append(quit_)
        self.menu.show_all()

    # -- acting --------------------------------------------------------------------------

    def run(self, cmd, doing, nope):
        """Hand the work to the CLI and stay responsive while it thinks.

        A verified switch reads the account first and can sit on the lock behind the daemon,
        which is a minute the panel must not spend frozen -- so it goes out asynchronously
        and the label says what is happening until it answers.
        """
        if self.busy:
            return
        self.busy = True
        self.ind.set_label(doing, GUIDE)
        try:
            p = Gio.Subprocess.new(cmd, Gio.SubprocessFlags.STDOUT_PIPE |
                                   Gio.SubprocessFlags.STDERR_MERGE)
        except GLib.Error as e:
            self.busy = False
            notify("ccex: could not run %s" % cmd[0], e.message)
            return self.tick()
        p.communicate_utf8_async(None, None, self.done, nope)

    def done(self, proc, res, nope):
        self.busy = False
        try:
            _, out, _ = proc.communicate_utf8_finish(res)
            ok = proc.get_successful()
        except GLib.Error as e:
            out, ok = e.message, False
        # A switch that worked is announced by the tick that sees a different account live,
        # so there is nothing to say here about one -- only about one that did not happen.
        # `ccex use` explains those in full, down to the flag that insists, and that is what
        # goes in the notification rather than a verdict of the tray's own invention.
        if not ok:
            said = [l.strip()[6:] if l.strip().startswith("ccex: ") else l.strip()
                    for l in (out or "").splitlines() if l.strip()]
            notify(nope, "\n".join(said[-3:]) or "it said nothing")
        self.tick()

    def on_switch(self, _item, email, short):
        self.run([CCEX, "use", email, "--no-report"], "switching…", "%s: nothing moved" % short)

    def on_rotate(self, _item):
        self.run([CCEX, "rotate"], "rotating…", "rotate: nothing moved")


def main():
    if "--help" in sys.argv[1:] or "-h" in sys.argv[1:]:
        print(__doc__.strip())
        return 0
    Tray()
    Gtk.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
