# ccex

**cc exchange** — switch which Claude account [Claude Code](https://claude.com/claude-code) runs as, without logging out and back in.

Each account's browser login happens once, ever. After that, switching is instant and
changes nothing but who gets billed: your settings, history, projects, plugins and MCP
tokens stay exactly where they are.

```console
$ ccex ls
ACCOUNT              EMAIL                          TIER                   ACCESS-TOKEN               REFRESH-TOKEN
*default             ada@example.com                default_claude_max_5x  6h56m left                 26d left (2026-09-20)
 personal            ada.lovelace@gmail.com         default_claude_pro     stale (refreshes on use)   27d left (2026-09-21)
 client-acme         ada@acme.example               default_claude_max_5x  4h02m left                 28d left (2026-09-22)

$ ccex use client-acme
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live
ccex: live account is now ada@acme.example (rollback: ~/.claude-profiles/.backups/20260825-094412)
```

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/falconx1/ccex/main/ccex -o ~/.local/bin/ccex
chmod +x ~/.local/bin/ccex
```

Needs `bash`, `python3`, and the `claude` CLI on your PATH.

## Everyday

| Command | What it does |
| --- | --- |
| `ccex ls` | list accounts; `*` marks the live one |
| `ccex use <account>` | make that account live (`-n` / `--dry-run` to plan only) |
| `ccex limits [<account>]` | 5-hour and weekly usage, with reset times (`--all` for every account) |
| `ccex add <name>` | browser login for another account, parked for later |

`<account>` is a slot name, a full email, or any unambiguous prefix of either — so
`ccex use acme`, `ccex use client-acme` and `ccex use ada@acme.example` are the same thing.

## Occasional

| Command | What it does |
| --- | --- |
| `ccex status <account>` | `claude auth status` for one account |
| `ccex login \| logout <account>` | re-auth or drop one account's credential |
| `ccex run <account> [args]` | launch `claude` as a parked account, leaving the live one alone |
| `ccex env <account>` | `eval "$(ccex env work)"` to set `CLAUDE_CONFIG_DIR` in your shell |
| `ccex rename <old> <new>` | rename a parked slot |
| `ccex rm <account>` | delete a parked slot and its credential |
| `ccex which \| path \| link --all \| seed` | plumbing |

## Knowing when you'll hit a limit

Switching accounts is only useful if you know which one has room left, so `ccex use`
reports the account it just switched you to:

```console
$ ccex use client-acme
ccex: ada@example.com -> parked as 'ada'; ada@acme.example -> live
ccex: limits for ada@acme.example (checked just now, from the running session)
        5h      4% used, resets Aug 25 11:59 (1h49m)
        weekly  18% used, resets Aug 26 04:59 (18h49m)
```

`ccex limits` asks the same question any time, and `ccex limits --all` asks it of every
account. Pass `--no-check` to `use` if you'd rather it stayed quiet.

### Where the numbers come from

`ccex` will not spend your quota to tell you about your quota. It takes the first answer
it can get, in this order:

1. **A session you already have open.** Claude Code hands its statusline a
   `rate_limits` block on every render. If you route that through `ccex record` (below),
   any running session keeps its own account's numbers current for free.
2. **The last known numbers**, if they were fetched in the past five minutes — by a
   previous `ccex limits`, or by you opening `/usage` yourself.
3. **Only if neither exists**: `ccex` starts Claude Code on that account in a pty, opens
   `/usage`, reads the answer and quits. It takes about eight seconds, sends no prompt and
   costs nothing — but it is a real session start, so it's the last resort, not the first
   move. `--force` demands it explicitly.

If a session is already open on an account but you haven't installed the recorder, `ccex`
would rather show you slightly old numbers than start a second session behind your back.

### Live numbers from your statusline

`ccex record` is a filter: statusline JSON in, the same JSON out, limits noted on the way
past. Put it in front of whatever your statusline already is, in `settings.json`:

```json
"statusLine": { "type": "command", "command": "ccex record | ~/.claude/statusline-command.sh" }
```

If you don't have a statusline yet, `"command": "ccex record"` on its own works — it emits
nothing, and Claude Code shows no statusline, but the recording still happens.

It writes at most once every 15 seconds per account, into
`~/.claude-profiles/.usage/`, and costs about 7ms on the renders where it does nothing.
Usage numbers are stamped with the account that produced them and with the time of your
last switch, so a session that predates a switch can never be misread as the new account.

## Reading `ccex ls`

**ACCESS-TOKEN** is the short-lived token Claude Code sends with each request; it lasts
hours and Claude Code silently renews it, so `stale (refreshes on use)` is normal and
harmless.

**TIER** is your plan's rate-limit tier with the boilerplate trimmed — `max_5x` rather
than `default_claude_max_5x`.

**REFRESH-TOKEN** is the one that matters. It's what buys new access tokens, it lasts on
the order of a month, and when it's gone that account needs a real browser login again.
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

Open Claude Code sessions keep the account they started on — switching affects the next
session you launch, not the one you're sitting in.

## Caveats

- Credentials stay in plain files, exactly as Claude Code already stores them. `ccex` sets
  mode `600` on everything it writes, but it doesn't add encryption that wasn't there.
- Detecting whether a session is already open on an account reads `/proc`, so it's
  Linux-only. Elsewhere `ccex` just falls through to the next source.
- Only tested on Linux with the credentials-in-`~/.claude/.credentials.json` layout. On
  macOS, where Claude Code can keep the login in the system Keychain instead, `ccex ls`
  will show `NOT LOGGED IN` for accounts it can't see.
- Respect Anthropic's terms for the accounts you're switching between.

## License

MIT
