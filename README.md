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
| `ccex use <account>` | make that account live (`-n` / `--dry-run` to plan only) |
| `ccex rotate` | if the live account is running out of room, switch to the one with the most left |
| `ccex rotate --bg` | keep rotating in the background, every 5 minutes |
| `ccex rotate --watch` | follow it in this terminal |
| `ccex add <name>` | browser login for another account, parked for later |

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
| `ccex rm <account>` | delete a parked slot and its credential |
| `ccex record` | the statusline filter that keeps limits current — see below |
| `ccex record --install` | wire it into your statusline, once |

Run `ccex <command> -h` for that command's flags. To re-authenticate an account whose
login has expired, `ccex add` it again under the same name.

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

Pass `--no-check` to `use` if you'd rather it stayed quiet.

### Rotating off a full account

```console
$ ccex rotate
ccex: staying put - ada@example.com is at 45% 5h / 23% weekly, under 80%

$ ccex rotate --at 40
ccex: ada@example.com is at 45% 5h / 23% weekly (5h over 40%), so -> ada@acme.example at 4% 5h / 18% weekly
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live
ccex: limits for ada@acme.example (checked just now)
        5h      8% used, resets 11:59 (1h27m)
        weekly  18% used, resets 26-08 04:59 (18h27m)
```

It switches only if the live account has crossed `--at` (default 80%) on either window —
either one running out is enough to make an account useless to you.

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

Parked numbers can be out of date, and rotation leans on them. That mostly self-corrects:
switching runs a real check on the account it just made live, so if the true numbers come
back over the threshold, the next `ccex rotate` moves again. What it can't see is an
account being spent from another machine — `--refresh` is what catches that.

### Leaving it running

```console
$ ccex rotate --bg
ccex: rotating every 5m at 80%, re-checking anything older than 15m; logs in ~/.claude-profiles/.usage/rotate.log

$ ccex rotate --watch
ccex: watching every 5m, threshold 80%, rotation by the timer
TIME      ACCOUNT                        5H              WEEKLY            CHECKED
10:37:31  ada@example.com                57% - 3h01m     25% - 14h21m      4m ago
10:42:31  ada@example.com                82% - 2h56m     25% - 14h16m      live
10:47:31  ada@acme.example               8% - 1h22m      18% - 18h22m      live
  ^ rotated: ada@example.com -> ada@acme.example
```

`--bg` writes a systemd user timer (`--every 5m`, `--at 80`, `--refresh 15m`, all
adjustable) that runs the same rotation and logs any switch it makes. `--status` shows when
it last ran and what it did, `--log` lists every switch, `--stop` removes the timer.

`--watch` prints a line per check in the foreground, and takes keys while it runs: `1`–`6`
re-pace it (10s, 30s, 1m, 5m, 15m, 30m), `r` checks immediately, `q` quits. If the timer is
running, watch only reports what it does; if it isn't, watch does the rotating itself, so
it works as a foreground alternative to `--bg`.

The timer runs while you're logged in. `loginctl enable-linger $USER` if you want it to
keep going when you aren't.

The timer runs with `--no-launch`, so it can't turn into a session launcher every five
minutes — but it isn't blind either. If nothing has reported for `--refresh` (15 minutes
by default) it does one real check, then goes quiet again. That covers the case your own
sessions can't: an account being spent from another machine, or a stretch with no session
open at all.

### Keeping an account out of it

```console
$ ccex pool out 4
ccex: ada.lovelace@gmail.com is out of the rotation pool; its login is untouched
```

A held account is marked `x` in `ccex ls` and is never chosen as a rotation destination.
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
answer is already 0%, and it stays 0% until a session reports otherwise. Parked accounts
are never launched at all — their numbers sit at whatever they were when that account was
last live, ticking down as their windows expire, and get a real check the moment you
`ccex use` them. If a session is already open on the live account but you haven't installed the recorder,
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

It writes at most once every 15 seconds per account, into `~/.claude-profiles/.usage/`,
and costs about 7ms on the renders where it does nothing. Numbers are filed under the
account the session is billing at the time it renders, which is why they stay right across
a switch.

## Reading `ccex ls`

**TOKEN** is the short-lived token Claude Code sends with each request. Claude Code
renews it silently, so `stale` is normal and harmless — it only means nothing has used
that account lately.

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
- Switches take an `flock` so the background timer and an interactive `ccex use` can't
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

43 checks against a throwaway `HOME` with three fake accounts — listing, numbering,
switching by name and number, exit codes, the pool, rotation decisions, the statusline
install, help for every command, and that parking never overwrites another account's
login. No network, no `claude`
binary, nothing written outside a temp directory.

## Layout

```
bin/ccex              argument dispatch and the help text, nothing else
lib/common.sh         where the accounts live, plus die / dir_for / profiles / py
lib/profile.sh        symlinking a profile to your real config, and making an account live
lib/limits.sh         the limits command, and the statusline recorder's throttle
lib/rotate.sh         turning a decision into a switch
lib/background.sh     the systemd timer and the foreground watch
lib/py/ccexlib.py     paths, JSON read/write, slots, numbers, the pool -- imported by the rest
lib/py/use.py         the credential handover, the one place accounts move
lib/py/limits.py      the usage engine: session, cache, clock, and the pty probe
lib/py/rotate.py      which account to move to, and why
lib/py/record.py      statusline payload in, limits snapshot out
lib/py/statusline.py  the one-time statusLine edit in settings.json
lib/py/info.py        one `ccex ls` row
lib/py/seed.py        onboarding and trust for a fresh profile
lib/py/pool.py        holding an account out of rotation, and putting it back
lib/py/forget.py      releasing a number when an account is removed
share/statusline.sh   the bundled statusline, installed when you have none
test/run.sh           the suite above
```

Each bash module is sourced by `bin/ccex`; each python module is run by the `py` helper
with `CCEX_BASE` and `CCEX_ROOT` in the environment, so nothing has to be passed down
through argument lists.

## License

MIT
