"""Report the 5-hour and weekly limits for one account or all of them.

The numbers come from a running session, from what was last measured, or from the clock.
Only `--force` asks an account directly, which is the one thing here that starts a session.
"""
import json, sys, time

from ccexlib import BASE, caps, email_for, expand, held, held_auto, id_for, is_base, slots
from decide import FIVE_AT, cap as in_force
from probe import NOTE, probe
from usage import (account_json, age, cached, compact, live_sessions, still_counting,
                   window)

argv = sys.argv[1:]
quiet = "--quiet" in argv
every = "--all" in argv
force = "--force" in argv
tsv = "--tsv" in argv
js = "--json" in argv
nolaunch = "--no-launch" in argv

max_age, args, skip = None, [], False
for i, a in enumerate(argv):
    if skip:
        if not a.isdigit():
            sys.exit("ccex: --max-age wants a number of seconds, got '%s'" % a)
        max_age = int(a)
        skip = False
    elif a == "--max-age":     # seconds; numbers older than this are worth a real check even
        # under --no-launch, and 0 turns that off rather than meaning "everything is stale"
        skip = True
    elif not a.startswith("-"):
        args.append(a)
if skip:
    sys.exit("ccex: --max-age wants a number of seconds")


targets = []
if every:
    targets = slots()
elif not args:
    targets = [("default", BASE)]
else:
    for t in [expand(a).lower() for a in args]:
        hit = [(n, d) for n, d in slots() if t in (n.lower(), email_for(d).lower())] or \
              [(n, d) for n, d in slots() if n.lower().startswith(t) or email_for(d).lower().startswith(t)]
        if not hit:
            sys.exit("ccex: no account matches '%s' (see: ccex ls)" % t)
        if len(hit) > 1:
            sys.exit("ccex: '%s' matches %s" % (t, ", ".join(n for n, _ in hit)))
        targets.append(hit[0])

def in_force_pair(name, d):
    """The two percentages this account is actually held to now, which near its weekly reset
    is not what it set: `cap` steps aside as the week it protects runs out."""
    row = account_json(name, d)
    return in_force(row, "five", FIVE_AT), in_force(row, "seven", FIVE_AT)


def cap_cell(name, d, c5, c7):
    """The CAP column: the percentages in force, with a * when they are not the ones set.

    A window this account did not cap stays a dash -- it follows --at like everyone else,
    and printing the default there would read as a cap it never set."""
    if not (c5 or c7):
        return "-"
    e5, e7 = in_force_pair(name, d)
    gave = (c5 and e5 != c5) or (c7 and e7 != c7)
    return "%s/%s%s" % ("%d" % e5 if c5 else "-", "%d" % e7 if c7 else "-", "*" if gave else "")


rows, notes = [], []
for name, d in targets:
    have = cached(d)
    age_s = time.time() - have["fetchedAtMs"] / 1000 if have["fetchedAtMs"] else None
    fresh = age_s is not None and age_s < 300
    too_old = bool(max_age) and (age_s is None or age_s > max_age)   # 0 means never
    if have["source"] == "session" and live_sessions(d) and not force:
        st = "ok"                      # a session is open on this account and reporting; touch nothing
    elif fresh and not force:
        st = "ok"                      # someone checked moments ago; no reason to ask again
    elif have["fetchedAtMs"] and not still_counting(d) and not force:
        st = "ok"                      # every window it knew about has since reset, so 0% is certain
    elif not is_base(d) and not force:
        st = "parked"                  # not the account you are running; leave it alone until asked
    elif live_sessions(d) and not force:
        st = "unhooked"                # never start a second session behind a running one
    elif too_old:
        st = probe(d)                  # nothing is reporting and the numbers have aged out
    elif nolaunch and not force:
        st = "ok"                      # caller would rather have old numbers than a new session
    else:
        st = probe(d)                  # last resort: open the TUI just long enough to read /usage
    if st not in ("ok", "parked"):
        notes.append("ccex: %s: %s" % (name, NOTE.get(st, st)))
    rows.append((name, email_for(d), window(d, "five_hour"), window(d, "seven_day"),
                 "live" if have["source"] == "session" and live_sessions(d) else age(d)))

if js:
    print(json.dumps([account_json(name, d) for name, d in targets]))
elif tsv:
    for name, d in targets:
        c5, c7 = caps(d)
        # One flags field, never empty: IFS=$'\t' collapses runs of tabs, so an empty
        # column would shift every field after it in the shell that reads this.
        flags = ",".join(f for f in ("auto" if held_auto(d) else "", "held" if held(d) else "",
                                     "cap" if (c5 or c7) else "") if f)
        print("\t".join([name, str(id_for(d) or "-"),
                         compact(d, "five_hour").ljust(22), compact(d, "seven_day").ljust(26),
                         "live" if cached(d)["source"] == "session" and live_sessions(d) else age(d),
                         flags or "-",
                         cap_cell(name, d, c5, c7)]))
elif quiet and len(rows) == 1:
    name, email, five, seven, a = rows[0]
    print("ccex: limits for %s (%s)" % (email, a if a == "live" else "checked " + a))
    print("        5h      %s" % five)
    print("        weekly  %s" % seven)
    c5, c7 = caps(targets[0][1])
    if c5 or c7:                  # only worth a line when this account sets its own
        print("        cap     %s (its own; uncapped windows follow --at for 5h (default 90), 99%% for the week)" %
              " / ".join("%s %d%%" % (w, v) for w, v in (("5h", c5), ("weekly", c7)) if v))
        e5, e7 = in_force_pair(name, targets[0][1])
        if (e5, e7) != (c5, c7):
            print("        in force 5h %d%% / weekly %d%% -- its cap steps aside as its week ends" % (e5, e7))
else:
    print("%-20s %-30s %-44s %-48s %s" % ("ACCOUNT", "EMAIL", "5-HOUR", "WEEKLY", "CHECKED"))
    for name, email, five, seven, a in rows:
        mark = "*" if name == "default" else " "
        print("%s%-19s %-30s %-44s %-48s %s" % (mark, name, email, five, seven, a))
for n in notes:
    print(n, file=sys.stderr)
