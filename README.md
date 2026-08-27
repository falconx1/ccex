# ccex

**cc exchange** — switch which Claude account [Claude Code](https://claude.com/claude-code) runs as, without logging out and back in.

Each account's browser login happens once, ever. After that, switching is instant and
changes nothing but who gets billed: your settings, history, projects, plugins and MCP
tokens stay exactly where they are.

```console
$ ccex ls
#   ACCOUNT        EMAIL                    TIER    TOKEN   REFRESH  5H                     WEEKLY                     CHECKED
1   *default       ada@example.com          max_5x  active  20-09    ████░░░░░░   41% 3h21m ██░░░░░░░░   23% 14h41m   live
2    personal      ada.lovelace@gmail.com   pro     stale   21-09    ░░░░░░░░░░    4% 1h41m ██░░░░░░░░   18% 18h41m   8m ago
3    client-acme   ada@acme.example         max_5x  active  22-09    █░░░░░░░░░    9% 2h51m ████░░░░░░   36% 4d 8h41m  4m ago

$ ccex use 3
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live

$ ccex use client-acme
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live
ccex: live account is now ada@acme.example (rollback: ~/.claude-profiles/.backups/20260825-094412)
```

## Install

```sh
git clone https://github.com/falconx1/ccex.git ~/src/ccex
~/src/ccex/install.sh
```

That symlinks `~/.local/bin/ccex` to the checkout, so `git pull` is the whole update
story. Pass a different directory to install elsewhere: `install.sh ~/bin`. Keep the
checkout where it is — the symlink and the systemd unit both point at it.

Then, once:

```sh
ccex record --install
```

That puts `ccex record` in front of your statusline in `settings.json`, which is what keeps
every usage number current without ever starting a session to ask. It keeps the statusline
you already have and pipes into it; if you don't have one, it installs the bundled bar.
[More below.](#live-numbers-from-your-statusline)

Needs `bash`, `python3`, and the `claude` CLI on your PATH.

## Everyday

| Command | What it does |
| --- | --- |
| `ccex ls` | list accounts; `*` marks the live one |
| `ccex ls -w` | the same table, live: countdowns ticking and the next switch on it |
| `ccex use <account>` | make that account live (`-n` / `--dry-run` to plan only) |
| `ccex rotate` | if the live account is running out of room, switch to the one with the most left |
| `ccex rotate --bg` | keep rotating in the background, as soon as usage says so |
| `ccex rotate --watch` | follow it in this terminal, one line per check |
| `ccex add` | browser login for another account, parked under its own name |

`<account>` is the number from the `#` column, a slot name, a full email, or any
unambiguous prefix of either — so `ccex use 3`, `ccex use acme`, `ccex use client-acme` and
`ccex use ada@acme.example` all mean the same account.

Those numbers are stored in `~/.claude-profiles/.ids.json`, keyed by email rather than by
position, so they don't move when you rotate or add an account. An account keeps its number
until you `ccex rm` it, which releases the number for the next account to take.

## Occasional

| Command | What it does |
| --- | --- |
| `ccex ls <account>` | that account's two windows in full, with reset clock times |
| `ccex run <account> [args]` | launch `claude` as a parked account, leaving the live one alone |
| `ccex env <account>` | `eval "$(ccex env work)"` to set `CLAUDE_CONFIG_DIR` in your shell |
| `ccex pool out \| in <account>` | take an account out of the rotation pool, or put it back |
| `ccex pool cap <account>` | how far rotation may spend that one account — see below |
| `ccex rm <account>` | delete a parked slot and its credential |
| `ccex record` | the statusline filter that keeps limits current — see below |
| `ccex record --install` | wire it into your statusline, once |

Run `ccex <command> -h` for that command's flags.

`ccex add` needs no name: it logs in, then parks the account under its own — `ada@acme.example`
becomes `acme`. Logging in as an account you already have re-authenticates that slot rather
than making a second one, which is what an expired REFRESH date calls for. `a` in
`ccex ls -w` runs the whole thing without leaving the view.

## Knowing when you'll hit a limit

The `5H` and `WEEKLY` columns are how much of each window you've burned and how long until
it resets — `41% - 3h21m`. `CHECKED` says how old that is; `live` means a session is open
on that account and reporting continuously. `ccex use` prints the same thing for the
account it just switched you to:

```console
$ ccex use client-acme
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live
ccex: limits for ada@acme.example (live, from the running session)
        5h      4% used, resets 11:59 (1h49m)
        weekly  18% used, resets 26-08 04:59 (18h49m)
```

That answer is read **before** the slot moves, not after. A switch onto an account with no
room left is worth knowing about while it is still a keystroke away, rather than surfacing a
minute later as a rotation you didn't ask for:

```console
$ ccex use dev-team011
ccex: dev_team011@jimdrive.com is at 100% 5h / 62% weekly, over 5h - rotation will move off it again
ccex: ada@example.com -> parked as 'ada'; dev_team011@jimdrive.com -> live
```

It still moves — you named it, and holding an account you asked for is not this tool's
business. The report afterwards reads the same answer, so asking first costs one session
rather than two. Rotation does its own asking, so this belongs only to a switch you typed.

Pass `--no-check` to `use` if you'd rather it neither asked nor reported.

### Watching it, live

```console
$ ccex ls -w
```

```
 ccex  3 accounts  live: ada@example.com  switch at 90% (daemon)  every 10s   00:35:36
    # ACCOUNT                   5H                               WEEKLY                        ROTATION   CHECKED
›▶  1 ada@example.com            62% ███████░░░╵░ 2h 49m 22s      23% ███░░░░░░░░╵ 14h 09m 22s in pool    1m ago
    2 ada@acme.example            9% █░░░░░░░░░╵░ 2h 19m 22s      36% ████░░░░░░░╵ 4d 08h 09m  in pool    1m ago
    3 ada.lovelace@gmail.com      4% ░░░░░╵░░░░░░ 1h 09m 22s      18% ██░╵░░░░░░░░ 18h 09m 22s cap 50/30  1m ago

 next switch  in 2h 27m 22s (03:02)  5h is at 62%, climbing 11.4% an hour to its 90% cap
              -> 3 ada.lovelace@gmail.com at 4% 5h / 18% weekly
 rotation     rotating on data change, every 10s at 90%
 keys         ↑↓ select  enter switch to it  number by number  +/- pace  r refresh  q quit   up 0m
```

`ccex ls` tells you where you stand; `ccex ls -w` leaves it on screen and folds the
rotation monitor into the bottom of it, so the question you actually have — *when does
this switch, and to what* — is answered in one place.

The countdowns tick every second, the `╵` in each bar is the percentage that account
counts as out of room at, and `next switch` is the estimate: how fast the live account's
5-hour window is climbing, when that meets its cap, and which account rotation would hand
you. It reads the 5-hour window because that is what actually stops you working; the week
only joins the estimate once it is past 90%, since "the week runs out in three days" is
true and useless. Where an account caps itself the estimate uses its own number.

That estimate needs readings to exist: two of them, five minutes apart, from a window
that hasn't reset in between. Until then it says so rather than guessing. The
destination needs no readings at all, so it is always there. A window that refills
before the cap is reached says `weekly resets first` instead of naming a time that would
never arrive.

Each row is one account by email, then each window as a percentage, a bar, and how long
until it resets. `▶` marks the account you are billing and `›` the one the arrows are on.
`ROTATION` answers the only question the old `x`/`c`/`X` marks were answering — whether
rotation may choose this account — in words: `in pool`, `held`, `retired`, or `cap 50/30`.

| Key | |
| --- | --- |
| `↑` / `↓` | move the selection; `enter` switches to it |
| `0`–`9` | or type an account's number, `y` to confirm (backspace edits) |
| `a` | add an account — the browser login runs here, then the table has it |
| `c` | cap the selected account: type the 5-hour percentage, `enter`, then the weekly one (`-` leaves a window uncapped) |
| `→` / `←` | take it out of the rotation pool, or put it back — the way to revive a retired account |
| `+` / `-` | re-pace the data tick (10s, 30s, 1m, 5m, 15m, 30m) |
| `r` | re-read everything now, `/proc` included |
| `q` | quit |

| Flag | |
| --- | --- |
| `--every 10s` | how often the numbers behind the countdown are re-read |
| `--at N` | threshold to predict against; defaults to whatever `--bg` is running at |
| `--refresh 15m` | allow one real check when nothing has reported for that long |
| `--rotate` | switch from here, not just report it |

Nothing is launched unless `--refresh` says it may (it is off by default), and never while
the background daemon is running; when it does happen, the check runs off the render loop,
so the view keeps counting down instead of freezing for eight seconds.

It is built to be left running for days. A minute of it costs **0.13s of CPU** — about
0.2% of one core — 17 MB of RSS and 1.3 KB/s of terminal output, and twelve simulated hours
of ticks leave the live object count unchanged, because the three clocks in it are paced by
what they actually cost: the second-by-second repaint is arithmetic on
timestamps it already has and only rewrites the lines that changed, the file re-read is
skipped entirely for any file whose `mtime` hasn't moved, and the one expensive read — a
`/proc` walk to find which accounts have sessions open — happens every 15 seconds rather
than every tick. Percentages themselves change no faster than `ccex record` writes them,
which is once every 15 seconds per account.

If ccex updates underneath it (a `git pull` while it's up), it re-executes itself into the
new code rather than running the old one for another week. `--rotate` makes it switch
accounts itself, and it stands down automatically while [the daemon](#leaving-it-running)
is running, so the two never both act. `ccex rotate --watch` is still there and unchanged —
one line per check, no full-screen draw — for when you want a log rather than a screen.

### Rotating off a full account

```console
$ ccex rotate
ccex: staying put - ada@example.com is at 45% 5h / 23% weekly, under 90% 5h / 99% weekly

$ ccex rotate --at 40
ccex: ada@example.com is at 45% 5h / 23% weekly (5h over 40%), so -> ada@acme.example at 4% 5h / 18% weekly
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live
ccex: limits for ada@acme.example (checked just now)
        5h      8% used, resets 11:59 (1h27m)
        weekly  18% used, resets 26-08 04:59 (18h27m)
```

It switches only if the live account is out of room on either window. `--at` (default
90%) is that line for the 5-hour window; **the week's is 99%**, whatever `--at` says.
Moving off an account at 90% of its week would abandon a tenth of it for six days, while
90% of a 5-hour window is gone in minutes — so the two windows get different numbers.
Either one running out is enough to make an account useless to you.

Among the accounts still under the threshold, it ranks on what their usage will actually
**cost** you, which is not the same as what it reads:

```
cost = used% x (time left in the window / length of the window)
```

Quota you're stuck with for the whole window counts in full. Quota that expires in twenty
minutes counts for almost nothing — the window refills before you could have spent what
was left of it. **5-hour cost decides; weekly cost only breaks ties**, because the 5-hour
window is what actually stops you working, while the weekly figure moves too slowly to
separate two accounts you'd otherwise be choosing between.

That weighting is not cosmetic. Given these four:

```
CANDIDATE       5H          RESETS IN   5H COST   WEEKLY COST
personal         0% used      2h09m       0.00       0.06      <- picked
client-acme     11% used      0h29m       1.07       1.87
team-shared      9% used      1h39m       2.97      22.18
side-project    88% used      2h09m      37.87       2.25
```

`side-project` has the second-cheapest week of the four and still comes last: 88% of its
5-hour window is gone and it has two hours to wait, so it's no use to you now.
`client-acme` reads worse than `team-shared` on raw 5-hour usage (11% against 9%) but
costs less, because its window resets in half an hour.

Eligibility still uses the raw figures — an account has to be usable *now* — but the
choice between usable accounts is made on cost. `-n` plans without switching.

If every other account is over the threshold too, it stays put, tells you which account
frees up soonest, and exits 1 — so `ccex rotate` is a usable cron or `/loop` line that
only makes noise when there's genuinely nowhere to go.

Parked numbers can be out of date, and eligibility leans on them. Nothing reports for an
account that isn't running, so its numbers are as old as the last time it was live — hours,
on a day of rotating. While an account sits parked nothing here can spend it, so old
numbers are a safe over-estimate of what it has used; what they can't see is that account
being spent **somewhere else**, which reads as free.

So before the slot changes hands, the account being moved to is asked directly: one short
session on it, a few seconds, exactly what `ccex ls <account> --force` does. This is worth
what it costs — on the machine this was built for, `ccex ls` believed an account was at 85%
of its 5-hour window while the account itself reported **100%**. Under the stale figure it
was eligible, and rotation would have landed on an account with no room at all.

```console
$ ccex rotate --at 50
ccex: ada@example.com is at 60% 5h / 17% weekly (5h over 50%), so -> ada@acme.example at 3% 5h / 43% weekly
      ; ada-work reads 95% 5h / 62% weekly checked just now, not 0%/6%
ccex: ada-work -> ada@acme.example -> live
```

One rule covers every answer: **if it can't be asked, try the next one.** An account that
turns out to have no room is passed over. So is one that *won't answer* — no `claude` to
launch, no folder it trusts, a check that times out — because an account that can be asked
is a better answer than one that cannot. Up to three are asked; asking is a session each,
and three is already most of a minute.

Only when *none* of them will answer does it fall back to the numbers on file, and the line
says that is what happened. Broken check machinery must not quietly empty the pool — staying
on an account with no room left is worse than moving to one that probably has some. An
account that has never been measured is the exception, and gets no fallback: there are no
numbers to fall back to.

Two things stop a launch, and folder trust is only the obvious one. A profile that has never
been onboarded stops on the theme picker, so `/usage` is never typed and the check waits out
its whole timeout looking exactly like a slow account — on the machine this was written on,
two probes in three were failing that way at 50 seconds each. Both the onboarding and the
folder trust come from the live account's config, which is what `ccex add` seeds a new profile
with, and `ccex use` re-seeds at park time so a slot that hands its login away does not lose
them. With both in place a check takes about six seconds.

`CCEX_PROBE_TIMEOUT` raises the ceiling on a machine where claude starts slowly. Rotation may
ask up to three accounts and holds the switch lock while it does, so raising it raises
`CCEX_LOCK_WAIT` (180s) with it. While a check is running the live view says `asking <name>…`,
because a switch that spends three sessions otherwise looks like a view that has stopped.

Because the check exists, an account **nothing has ever measured** can be a candidate too —
ranked behind every account that has been, so it is only reached for once the measured ones
are out of room, which is also the only moment it is worth a session to go and read one.
Without that it could never be reached at all: ranking needs numbers, so an unmeasured
account would never be chosen, never be checked, and stay invisible for good. This is the
one case where a failed check means the account is **skipped** rather than used anyway —
there are no numbers to fall back on, and landing on windows nobody has read would be a
worse guess than the stale ones this is here to replace. `--no-verify` therefore drops
unmeasured accounts from the running: with nothing going to read them first, being
unmeasured has to keep them out.

Nothing checks accounts on a timer, and nothing needs to. A window whose reset time has
passed reads 0% by arithmetic, so the countdown keeps stale numbers honest on its own — for
free, for every parked account at once. What it cannot do is see an hour spent on that
account from another machine, or invent a first reading. Those are worth a session, and only
for the one account about to be used.

**Near the switch, not on a schedule.** Nearness is a usage distance, not a clock: how far
the live account's percentage is from the point that will move it. Once *either* window is
within 5 points of its cap — the week counts, and often trips first — the account it would
move to is read *then*. When the cap is finally crossed, the switch is a file copy with no
session held open inside the lock.

Reading ahead happens **at most once per live 5-hour window**, and that bound is what keeps
it from becoming a timer. A read that *failed* counts as a read for this purpose — otherwise
an account that cannot be read would be re-asked every tick, which is the timer none of this
is supposed to be. Sitting at 88% for an hour asks once, not once a tick.

What reading ahead is worth is mostly a **better decision**, not a saved session. Ranking
picks the cheapest account from the numbers on file, and those numbers are what go wrong —
one of the accounts here read 85% while the account itself said 100%, which made a spent
account look like the best candidate. Reading it while the switch is still approaching fixes
the ranking before it is used. The switch that follows still asks for itself unless the
read-ahead landed within the last five minutes; a reading from earlier in the same window
can be hours old, which is the staleness being checked for, so the window is far too wide to
count as fresh.

The one case that re-arms is a window sitting inside the band for days, which the week can
do: once per 5-hour window, so at worst about five sessions a day while a switch is genuinely
imminent. `NEAR` in `lib/py/rotate.py` is the knob, and `--no-verify` turns the whole thing
off.

`--no-verify` switches on the numbers on file without asking, and `-n` never asks. The
answer is filed the same way any other reading is, so an account that has been asked once
is also recognisable afterwards — see [Live numbers from your
statusline](#live-numbers-from-your-statusline).

### Leaving it running

```console
$ ccex rotate --bg
ccex: rotating at 90% the moment a session reports it, checked every 10s; logs in ~/.claude-profiles/.usage/rotate.log

$ ccex rotate --status
ccex: rotating on data change (active since Tue 2026-08-25 22:41:03 UTC)
ccex: rotate --serve --at 90 --every 10s --refresh 0
ccex: 17 MB resident, 4.2s of cpu used so far

last check:
  2026-08-25 23:14:52
  ccex: staying put - ada@example.com is at 62% 5h / 23% weekly, under its own 80% 5h / 90% weekly
```

`--bg` installs a systemd user service that stays up and re-reads the numbers every
`--every` (10s). Every statusline render writes a snapshot; the moment one of those crosses
the threshold, the switch happens — seconds after the number lands, not at the next tick of
a five-minute clock. `--status` says whether it is running and what it has cost, `--log`
lists every switch, `--stop` removes it. Installing over an older ccex replaces its
wake-up timer with the watcher and says so.

It stays cheap by not doing anything expensive: a file whose `mtime` has not moved is not
re-read, only the handful of keys anyone reads are kept from each config, nothing walks
`/proc` or computes a burn rate for a screen that isn't there, and the switch itself is
delegated to `ccex rotate --tick` — the only part that takes the lock and writes anything.
Measured over a minute of the real service: **16 ms of CPU** (0.03% of one core, ~24 s a
day) and 7.9 MB resident, `Nice=5` so it yields to your actual work.

It runs while you're logged in. `loginctl enable-linger $USER` if you want it to keep going
when you aren't.

Nothing it does can start a session: it decides from files your own sessions have already
written. `--refresh` is what would allow one real check after a stretch of silence, and it
is **off by default** — with switching driven by the data, there is nothing to poll for.
Turn it on (`ccex rotate --bg --refresh 15m`) if you want the one case files can't cover:
an account being spent from another machine, or a long stretch with no session open at all.

```console
$ ccex rotate --watch
ccex: watching every 5m, threshold 90%, rotation in the background
TIME      ACCOUNT                        5H              WEEKLY            CHECKED
10:37:31  ada@example.com                57% - 3h01m     25% - 14h21m      4m ago
10:42:31  ada@example.com                82% - 2h56m     25% - 14h16m      live
10:47:31  ada@acme.example               8% - 1h22m      18% - 18h22m      live
  ^ rotated: ada@example.com -> ada@acme.example
```

`--watch` is the one-line-per-check view, if you want a log rather than a screen: `1`–`6`
re-pace it (10s, 30s, 1m, 5m, 15m, 30m), `r` checks immediately, `q` quits. When the daemon
is running, watch only reports what it does; when it isn't, watch rotates itself. `ccex ls -w`
[shows the same thing with the whole table](#watching-it-live), which is usually what you
want.

Two things can decide to switch at once — the daemon and a `ccex use` you type, or a
`ccex ls -w --rotate` you left open. They can't collide: the view stands down entirely
while the daemon is active, and a switch takes an `flock` either way, so the second one to
arrive re-decides under the lock and finds there is nothing left to do. A switch that asks
the account it is moving to first holds that lock for a session or three, so the wait is a
minute rather than the seconds a plain switch needs — long enough to sit it out, because
what the second command is waiting for is the switch it wanted anyway.

The view and the switch run the same `decide()` on the same numbers, so what the monitor
predicts is what the tick does — including whether accounts nobody has measured are in the
running, which depends on whether anything is going to read them first. `--no-verify`
therefore changes both together, or neither.

### Keeping an account out of it

```console
$ ccex pool out 4
ccex: ada.lovelace@gmail.com is out of the rotation pool; its login is untouched
```

A held account is marked `x` in `ccex ls` (`X` when rotation retired it itself, below) and
is never chosen as a rotation destination.
Its login is kept, so `ccex pool in 4` puts it straight back with no browser round-trip —
useful for a personal account you don't want work billed to, or one you're saving.

Held means rotation leaves it alone in both directions: it is never chosen, and if you're
sitting on one, nothing moves you off it however spent it looks. `ccex use 4` refuses too,
and tells you which command undoes it:

```console
$ ccex use 4
ccex: ada.lovelace@gmail.com is held out of the pool; `ccex pool in 4` first
```

When nothing is eligible, the message names the accounts that were held, so an empty pool
never looks like a bug.

### A spent week takes itself out

An account at 99% of its week is no use again for days. Rotation notices that and takes it
off the list itself, once:

```console
$ ccex rotate
ccex: ada@example.com is at 34% 5h / 99% weekly (weekly over 99%), so -> ada@acme.example at
9% 5h / 36% weekly; out of the pool until `ccex pool in`: default (weekly at 99%)

$ ccex ls
#   ACCOUNT      EMAIL              TIER    ...  5H                     WEEKLY
1 X default      ada@example.com    max_5x  ...  ███░░░░░░░   34% 2h11m █████████░   99% 5d 4h11m
```

A retired account is marked `X` — the same column as the `x` from `ccex pool out`, because
it is the same state, reached by itself. Nothing brings it back automatically, not even the
week rolling over: `ccex pool in 1` is the only way, so an account you were saving cannot be
drained again the moment its window resets while you weren't looking.

Only the week does this. Running a 5-hour window down is ordinary rotation — it refills
while you work — so nothing is retired for it. And rotation still moves you *off* a retired
account you are sitting on; being retired only stops it coming back.

### Capping one account's share

`--at` (and the week's 99%) is one threshold for every account. A cap is the per-account
version: how far *that* account may be spent, in either window, whatever the defaults say.

```console
$ ccex pool cap 2 --5h 50 --weekly 30
ccex: ada.lovelace@gmail.com is out of room at 5h 50%, weekly 30%

$ ccex pool cap client-acme --5h 95
ccex: ada@acme.example is out of room at 5h 95%
ccex: weekly still follows the default (--at for 5h, 99% for the week)
```

The account is named the same way as everywhere else — the number from `ccex ls`, a slot
name, an email, or an unambiguous prefix.

Lower than the default to keep something in reserve — half of every 5-hour window and 70% of the
week stay unspent on `personal` above, so it is there when you need it rather than being
drained by rotation first. Higher than `--at` to run an account right down before moving on,
which is what you want for the account you'd rather bill.

A cap works in both directions, like `--at` does: rotation moves off that account once it
crosses its own cap, and won't land on it above its cap either. Windows you don't cap keep
following the defaults, so one account can protect its week and share everyone else's 5-hour
threshold. The messages say which number applied, so a rotation that looks early or late
explains itself:

```console
$ ccex rotate
ccex: staying put - ada@acme.example is at 90% 5h / 40% weekly, under its own 95% 5h / 99% weekly

$ ccex rotate
ccex: ada@example.com is at 92% 5h / 40% weekly (5h over 90%), and every other account is
too; capped by their own limits: personal at its own 50%
```

Capped accounts are marked `c` in `ccex ls`, which also grows a `CAP` column once anything
is capped — `60/99` caps both windows, `-/25` only the week, `-` neither. The column isn't
there at all until you cap something, so a setup that doesn't use caps reads exactly as
before:

```console
$ ccex ls
#   ACCOUNT        EMAIL                    TIER    TOKEN   REFRESH  5H                     WEEKLY                     CAP     CHECKED
1   *default       ada@example.com          max_5x  active  20-09    ████░░░░░░   41% 3h21m ██░░░░░░░░   23% 14h41m   -       live
2   c personal     ada.lovelace@gmail.com   pro     stale   21-09    ░░░░░░░░░░    4% 1h41m ██░░░░░░░░   18% 18h41m   50/30   8m ago
3    client-acme   ada@acme.example         max_5x  active  22-09    █░░░░░░░░░    9% 2h51m ████░░░░░░   36% 4d 8h41m  95/-    4m ago
```

`ccex ls <account>` prints it in full:

```console
$ ccex ls personal
ccex: limits for ada.lovelace@gmail.com (checked 4m ago)
        5h      ████░░░░░░   41% used, resets 14:10 (3h21m)
        weekly  ██░░░░░░░░   23% used, resets 26-08 13:10 (14h41m)
        cap     5h 50% / weekly 30% (its own; uncapped windows follow --at for 5h (default 90), 99% for the week)
```

`c` in `ccex ls -w` does the same thing without the typing: it asks for the 5-hour
percentage, then the weekly one, and `-` leaves a window on the default. `→` and `←` there
are `pool out` and `pool in` on whichever account the arrows are on.

`ccex pool cap <account>` on its own reports what is set; `--clear` puts the account back on
the `--at` default. Caps live in `~/.claude-profiles/.caps.json`, keyed by email like the
account numbers, so they survive rotations and renames. A held account outranks its own cap
— rotation may not touch it at all — so `ccex ls` shows `x` rather than `c` for one that is
both.

### Where the numbers come from

`ccex` will not spend your quota to tell you about your quota, and it will not start a
session on an account you aren't using. It takes the first answer it can get:

1. **The clock.** A window whose reset time has passed — or is inside its last minute — is
   0% used. That follows from arithmetic, not from asking anyone, and it holds for the
   account you're running just as much as for the ones you aren't. Such a window reads
   `0% new`, to distinguish a window that reset from one that was measured at zero.
2. **A session you already have open.** Claude Code hands its statusline a `rate_limits`
   block on every render. Route that through `ccex record` (below) and any running session
   keeps its own account's numbers current for free.
3. **The last known numbers**, if they were fetched in the past five minutes.
4. **Only for the account you're actually running**, only when it has a window still
   counting down, and only if none of the above answered: `ccex` starts Claude Code in a
   pty, opens `/usage`, reads the answer and quits. About eight seconds, no prompt sent,
   no cost — but it is a real session start, so it's the last resort. `--force` demands it;
   `--max-age <seconds>` allows it only once the numbers have aged past a limit you set,
   which is how the background monitor stays honest without polling.

In practice step 4 is reachable in one situation: you have no session open on the live
account and its windows haven't run out yet — which is what `ccex use` walks into before
you start working. Once a session is running, its statusline answers everything.

Nothing is launched for an account whose windows have all expired, parked or live: the
answer is already 0%, and it stays 0% until a session reports otherwise. A parked account
is not launched on its own account either — its numbers sit at whatever they were when it
was last live, ticking down as their windows expire. Two things ask one directly, and both
are things you asked for: `ccex ls <account> --force`, and rotation checking the account it
is about to move to. If a session is already open on the live account but you haven't installed the recorder,
`ccex` shows slightly old numbers rather than starting a second session behind your back —
that holds even past `--refresh`, so the promise has no exception.

### Live numbers from your statusline

`ccex record` is a filter: statusline JSON in, the same JSON out, limits noted on the way
past. One command wires it in:

```console
$ ccex record --install
ccex: backed up settings.json to ~/.claude-profiles/.backups/20260825-121904
ccex: kept your statusline, recording in front of it
ccex: statusLine = ~/src/ccex/bin/ccex record | ~/.claude/statusline-command.sh
ccex: open a new session, or /statusline to reload; live limits from now on
```

Whatever statusline you already have becomes the pipe target, so the only thing that
changes is that the numbers stay current. With no statusline of your own, it installs the
bundled one — model, context, cost, and both usage windows as bars, in the same colours
`ccex ls` uses:

```
Opus 5 │ ctx:███░░░░░░░ 37% │ $1.23 │ 5h:██████░░░░ 62% │ 7d:█░░░░░░░░░ 18%
```

It is a one-time install: `settings.json` is backed up first, running it again changes
nothing, and the line that undoes it is printed. The hand-written equivalent is one key in
`settings.json`, if you would rather:

```json
"statusLine": { "type": "command", "command": "ccex record | ~/.claude/statusline-command.sh" }
```

`"command": "ccex record"` on its own works too — it emits nothing, so Claude Code shows no
statusline, but the recording still happens.

A render that arrives just after a switch is the one case this has to get right: the
session still carries the old account's limits, while `.claude.json` already names the new
one, so filing them would credit someone else's spent hour to the account you just moved
to — and `ccex rotate` would move straight off it again.

Two things say whose numbers a payload is carrying, because the payload itself does not.
A weekly window comes back at the same point in every week for the same account, so that
point identifies it however far the percentages have moved since; the accounts' own points
are learned from what Claude Code caches per account in `.claude.json`, which it tags with
the account it fetched for, and kept in `~/.claude-profiles/.anchors.json`. Failing that —
an account nothing has measured yet has no point — the numbers left behind at each switch
in the last half hour are written down and recognised if they turn up again. Recognised
either way, the render is skipped; a reading already filed against the wrong account is not
believed when it is read back either.

Each account also gets a small ring of `(time, 5h%, weekly%)` samples next to its
snapshot — appended only when a number actually moves, capped at 200 — which is where
`ccex ls -w`'s `+11.4%/h` and its estimate come from. Nothing else reads it, and losing
it costs nothing but the estimate until the next two readings land.

It writes at most once every 15 seconds per account, into `~/.claude-profiles/.usage/`,
and costs about 7ms on the renders where it does nothing. Numbers are filed under the
account whose numbers they are rather than under whoever is live, which is why they stay
right across a switch.

## Reading `ccex ls`

**TOKEN** is the short-lived token Claude Code sends with each request. Claude Code
renews it silently, so `stale` is normal and harmless — it only means nothing has used
that account lately.

**CAP** is only present once some account has one, and shows that account's own
out-of-room percentages as `5h/weekly` — `-` for a window that still follows `--at`.

**5H** and **WEEKLY** each show how much of that window is spent, then how long until it
resets. Note that the two don't rank accounts the same way: `22% 26m` is a better place to
land than `18% 17h24m`, because the first is minutes from starting over. `ccex rotate`
weighs that; the bar just shows you the spend.

**TOKEN** and **REFRESH** are the two OAuth clocks. **TIER** is your plan's rate-limit tier with the boilerplate trimmed — `max_5x` rather
than `default_claude_max_5x`.

**REFRESH** is the one that matters. It's what buys new access tokens, it lasts on the
order of a month, and when that date passes the account needs a real browser login again.
Both values are read straight out of `.credentials.json` (`expiresAt` and
`refreshTokenExpiresAt`) — nothing is sent anywhere to compute them.

## How it works

The live account is just the ordinary `~/.claude`. Everything else is parked under
`~/.claude-profiles/<name>/`.

`ccex use` moves exactly one key — `claudeAiOauth` in `.credentials.json` — plus the
matching `oauthAccount` / `userID` identity block and the account's cached usage numbers
in `.claude.json`. The account that was
live gets parked under its own email's local part; the one you named becomes live. Nothing
else is touched.

Parked slots symlink `settings.json`, `CLAUDE.md`, `plugins/`, `projects/`, `todos/`,
`tasks/` and `file-history/` back to `~/.claude`, so `ccex run` and `ccex add` see the same
configuration and history as your main account rather than a blank one.

Every write first copies the four files it's about to touch into
`~/.claude-profiles/.backups/<timestamp>/`, so any switch is undoable by hand.

Sessions you already have open follow the switch. Claude Code re-reads
`.credentials.json`, so a session started an hour ago bills the account that is live now,
not the one it started on — which is what makes rotating away from a spent account
actually help the work you're in the middle of.

## Caveats

- Credentials stay in plain files, exactly as Claude Code already stores them. `ccex` sets
  mode `600` on everything it writes, but it doesn't add encryption that wasn't there.
- Switches take an `flock` so the background daemon and an interactive `ccex use` can't
  interleave. Claude Code itself doesn't take that lock, so a switch landing in the same
  millisecond as one of its own writes to `~/.claude.json` could still lose that write. The
  window is sub-millisecond and the file is rewritten from a read taken immediately before,
  but it isn't zero.
- The last 20 switch backups are kept and the rotation log is capped at 200 lines.
- Detecting whether a session is already open on an account reads `/proc`, so it's
  Linux-only. Elsewhere `ccex` just falls through to the next source.
- Only tested on Linux with the credentials-in-`~/.claude/.credentials.json` layout. On
  macOS, where Claude Code can keep the login in the system Keychain instead, `ccex ls`
  will show `NOT LOGGED IN` for accounts it can't see.
- Respect Anthropic's terms for the accounts you're switching between.

## Tests

```sh
./test/run.sh
```

140 checks against a throwaway `HOME` with three fake accounts — listing, numbering,
switching by name and number, exit codes, the pool, per-account caps, the week's own 99%
and the retirement it triggers, rotation decisions, the statusline install, rendered frames
of the live view (including the switch prompt and two-digit account numbers) and the
burn-rate arithmetic behind its estimate, the daemon switching on a data change, staying
quiet when it shouldn't and restarting itself on an update, two rotations racing each other,
the keys driven through a real pty — all four arrows, enter, `a` and `c` — adding an account
with and without a name, capping and holding from the view, help for every command, and that parking never overwrites another account's login.
No network, no real `claude` binary, nothing written outside a temp directory.

## Layout

```
bin/ccex              argument dispatch and the help text, nothing else
lib/common.sh         where the accounts live, plus die / dir_for / profiles / py
lib/profile.sh        symlinking a profile to your real config, and making an account live
lib/limits.sh         the limits command, and the statusline recorder's throttle
lib/rotate.sh         turning a decision into a switch
lib/background.sh     the systemd service, the foreground watch, and one tick
lib/py/ccexlib.py     paths, JSON read/write, slots, numbers, the pool -- imported by the rest
lib/py/use.py         the credential handover, the one place accounts move
lib/py/usage.py       reading the two windows: session, cache, clock -- no launching
lib/py/probe.py       the one thing that costs a session: the pty probe, and folder trust for it
lib/py/limits.py      the usage engine on top of that
lib/py/decide.py      which account to move to, and why -- shared by rotate and the view
lib/py/rotate.py      that decision as one line for the shell, once the target is verified
lib/py/burn.py        how fast a window is climbing, and when it hits its cap
lib/py/watch.py       `ccex ls -w`: the live table with the monitor folded in
lib/py/record.py      statusline payload in, limits snapshot out
lib/py/statusline.py  the one-time statusLine edit in settings.json
lib/py/info.py        one `ccex ls` row
lib/py/seed.py        onboarding and trust for a fresh profile
lib/py/pool.py        holding an account out of rotation, and capping how far it is spent
lib/py/forget.py      releasing a number, pool entry and cap when an account is removed
share/statusline.sh   the bundled statusline, installed when you have none
test/run.sh           the suite above
```

Each bash module is sourced by `bin/ccex`; each python module is run by the `py` helper
with `CCEX_BASE` and `CCEX_ROOT` in the environment, so nothing has to be passed down
through argument lists.

## License

MIT
