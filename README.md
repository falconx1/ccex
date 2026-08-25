# ccex

**cc exchange** — switch which Claude account [Claude Code](https://claude.com/claude-code) runs as, without logging out and back in.

Each account's browser login happens once, ever. After that, switching is instant and
changes nothing but who gets billed: your settings, history, projects, plugins and MCP
tokens stay exactly where they are.

```console
$ ccex ls
ACCOUNT         EMAIL                    TIER    TOKEN    REFRESH      5H            WEEKLY           CHECKED
*default        ada@example.com          max_5x  6h56m    26d (20-09)  41% - 3h21m   23% - 14h41m     live
 personal       ada.lovelace@gmail.com   pro     stale    27d (21-09)  4% - 1h41m    18% - 18h41m     8m ago
 client-acme    ada@acme.example         max_5x  4h02m    28d (22-09)  9% - 2h51m    36% - 4d 8h41m   4m ago

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
| `ccex add <name>` | browser login for another account, parked for later |

`<account>` is a slot name, a full email, or any unambiguous prefix of either — so
`ccex use acme`, `ccex use client-acme` and `ccex use ada@acme.example` are the same thing.

## Occasional

| Command | What it does |
| --- | --- |
| `ccex limits [<account>]` | the same limits in full, with reset clock times |
| `ccex status <account>` | `claude auth status` for one account |
| `ccex login \| logout <account>` | re-auth or drop one account's credential |
| `ccex run <account> [args]` | launch `claude` as a parked account, leaving the live one alone |
| `ccex env <account>` | `eval "$(ccex env work)"` to set `CLAUDE_CONFIG_DIR` in your shell |
| `ccex rename <old> <new>` | rename a parked slot |
| `ccex rm <account>` | delete a parked slot and its credential |
| `ccex which \| path \| link --all \| seed` | plumbing |

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

### Where the numbers come from

`ccex` will not spend your quota to tell you about your quota, and it will not start a
session on an account you aren't using. It takes the first answer it can get:

1. **The clock.** A window whose reset time has passed is 0% used. That needs no asking,
   so accounts you haven't touched in a while cost nothing to report accurately.
2. **A session you already have open.** Claude Code hands its statusline a `rate_limits`
   block on every render. Route that through `ccex record` (below) and any running session
   keeps its own account's numbers current for free.
3. **The last known numbers**, if they were fetched in the past five minutes.
4. **Only for the account you're actually running**, and only if none of the above
   answered: `ccex` starts Claude Code in a pty, opens `/usage`, reads the answer and
   quits. About eight seconds, no prompt sent, no cost — but it is a real session start,
   so it's the last resort. `--force` demands it.

Parked accounts are never launched. Their numbers sit at whatever they were when that
account was last live, ticking down to 0% as their windows expire, and get a real check
the moment you `ccex use` them. If a session is already open on the live account but you
haven't installed the recorder, `ccex` shows slightly old numbers rather than starting a
second session behind your back.

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
hours and Claude Code silently renews it, so `stale` is normal and harmless — it just
means nothing has used that account lately.

**TOKEN** and **REFRESH** are the two OAuth clocks. **TIER** is your plan's rate-limit tier with the boilerplate trimmed — `max_5x` rather
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
