# Installing Token Observatory

Token Observatory is a local dashboard for Claude Code and Codex token usage. It reads the session logs those tools already write on your machine. It has no dependencies, needs no API keys, and uploads nothing. Its only network request is an optional download of published model prices ([Cost estimates](#cost-estimates)).

## Requirements

- Python 3.9 or later, available as `python3`
- Claude Code and/or Codex, used on the same machine (otherwise there is nothing to show)
- macOS or Linux. On Windows, see [Run from source](#run-from-source).

Check your Python version:

```sh
python3 --version
```

On macOS, the Xcode Command Line Tools include Python 3.9. Install them with `xcode-select --install` if `python3` is missing.

## Download a release

Standalone builds bundle Python, so nothing else needs to be installed. Get them from [Releases](https://github.com/lepotatoguy/token_observatory/releases/latest).

| Platform | File | Install |
|---|---|---|
| macOS (Apple silicon) | `TokenObservatory-<version>-macos-arm64.zip` | Unzip, move **Token Observatory.app** to Applications, then right-click it and choose **Open** (it isn't notarized) |
| Linux (Debian, Ubuntu; x86-64) | `TokenObservatory-<version>-linux-amd64.deb` | `sudo apt install ./TokenObservatory-<version>-linux-amd64.deb`, then run `token-observatory` or use the menu entry |
| Windows (x86-64) | `TokenObservatory-<version>-windows-x64.exe` | Run it. If SmartScreen warns, choose **More info**, then **Run anyway** |

Every build takes the same options: `--no-open`, `--stop`, `--port N` and `--version`. On macOS the executable is `Token Observatory.app/Contents/MacOS/TokenObservatory`.

On Intel Macs, or to build from source, use the steps below.

## Install from source

```sh
git clone https://github.com/lepotatoguy/token_observatory.git
cd token_observatory
./install.sh
```

### macOS

`install.sh` builds **Token Observatory.app** and installs it in `~/Applications`. Open it from Finder, Spotlight or Launchpad. The app starts a background collector and opens the dashboard in your default browser; reopening it reuses the collector that is already running.

- History and the service log: `~/Library/Application Support/Token Observatory/`
- The collector keeps running after the browser closes. After a restart, open the app again to resume collection. No login item is installed.

The app is built on your machine and isn't code-signed. If macOS blocks it, right-click the app and choose **Open** once.

### Linux

`install.sh` copies the dashboard to `~/.local/share/token-observatory/app` (or `$XDG_DATA_HOME/token-observatory/app`), installs the `token-observatory` command in `~/.local/bin`, and adds a **Token Observatory** desktop menu entry.

```sh
token-observatory            # start the collector if needed, then open the browser
token-observatory --no-open  # start the collector only and print the URL
```

- History and the service log: `~/.local/share/token-observatory/`
- If `~/.local/bin` isn't on your `PATH`, the installer tells you. Add it in your shell profile.

## Run from source

No install is needed. From the repository folder:

```sh
python3 server.py
```

Then open <http://127.0.0.1:8765>. Stop with Ctrl+C. This also works on Windows (use `python` or `py` in place of `python3`), though Windows hasn't been tested.

`scripts/token-observatory` does the same thing in the background and opens the browser.

## Options

| Setting | Flag | Environment variable | Default |
|---|---|---|---|
| Port | `--port` | `TOKEN_OBSERVATORY_PORT` (launcher only) | `8765` |
| Claude Code home | `--claude-home` | `CLAUDE_CONFIG_DIR` | `~/.claude` |
| Codex home | `--codex-home` | `CODEX_HOME` | `~/.codex` |
| History folder | `--data-dir` | none | see the platform sections above |

Example:

```sh
python3 server.py --port 8766 --claude-home /path/to/.claude --codex-home /path/to/.codex
```

### Live usage limits

When you open the dashboard, click **Refresh**, and every 5 minutes, the collector asks both tools for current usage:

- Claude Code: `claude -p /usage`, the documented `/usage` report ([Agent SDK reference](https://code.claude.com/docs/en/agent-sdk/typescript)). It is a local command: no model request, no tokens, and no saved session. It needs a claude.ai Pro or Max sign-in in Claude Code itself (check with `claude auth status`, sign in with `claude /login`); signing in to the Claude desktop app doesn't count.
- Codex: `codex app-server` and its `account/rateLimits/read` method ([App Server docs](https://learn.chatgpt.com/docs/app-server)).

Both tools use their own sign-in; Token Observatory never reads credentials. The `claude` and `codex` commands must be on `PATH` or in `/opt/homebrew/bin`, `/usr/local/bin`, `~/.local/bin` or `~/.claude/local`. If a check fails, the card says why and keeps the last good numbers. Results are saved as `live-limits.json` in the data folder.

The status line below is optional. It records the limits after every reply in terminal sessions, which keeps them current between checks.

### Claude status line

Claude Code shares your plan's 5-hour and weekly usage with its status line after each reply (Pro and Max plans; see the [status line docs](https://code.claude.com/docs/en/statusline)). To have Token Observatory record them, add its status line to Claude Code's settings once:

| Install | Command |
|---|---|
| macOS release app | `"/Applications/Token Observatory.app/Contents/MacOS/TokenObservatory" --install-statusline` |
| Linux `.deb` | `token-observatory --install-statusline` |
| Windows | `TokenObservatory-<version>-windows-x64.exe --install-statusline` |
| From source | `python3 launcher.py --install-statusline` |

This sets `statusLine` in `~/.claude/settings.json` (or `$CLAUDE_CONFIG_DIR/settings.json`) after saving a copy as `settings.json.bak`. It won't replace a status line you already have. Your terminal's status line then shows the model, context and both limits. Remove it with `--uninstall-statusline`.

The newest of the live check, the status line and the Claude desktop app's occasional usage samples is shown. The Claude desktop app's Code tab doesn't run status lines.

### Conversation hooks

Token Observatory can add two Claude Code [hooks](https://code.claude.com/docs/en/hooks) (`UserPromptSubmit` and `PostToolUse`). They run in terminal sessions and in the desktop app's Code tab, and add a note to the conversation when:

- your 5-hour limit reaches 90%: the model is asked to finish or pause the current step, start no new work, and write a handoff summary (goal, state, done, not done, next steps, key files, open questions) to `.claude/handoffs/` in the project. Once per 5-hour window per conversation.
- the conversation's context reaches 60% of its window: the model is asked to condense what it needs from earlier work, keep output short, and continue. Once each time the context crosses the threshold, so it can fire again after a compaction.

A hook can't start compaction; the note asks the model to suggest `/compact` if the context keeps growing. To make Claude Code compact earlier by itself, its documented [auto-compact window](https://code.claude.com/docs/en/model-config#set-the-auto-compact-window) can be lowered, for example `/autocompact 600k` or `"autoCompactWindow": 600000` in `settings.json`. Token Observatory doesn't change it.

Install or remove the hooks:

| Install | Command |
|---|---|
| macOS release app | `"/Applications/Token Observatory.app/Contents/MacOS/TokenObservatory" --install-hooks` |
| Linux `.deb` | `token-observatory --install-hooks` |
| Windows | `TokenObservatory-<version>-windows-x64.exe --install-hooks` |
| From source | `python3 launcher.py --install-hooks` |

This adds entries to the `hooks` section of `~/.claude/settings.json` (backup in `settings.json.bak`) and keeps every other hook. Running it again changes nothing. When `~/.codex` exists, the same hooks go into `~/.codex/hooks.json` for [Codex](https://learn.chatgpt.com/docs/hooks), using Codex's own 5-hour limit and context window; Codex skips new hooks until you trust them with `/hooks`. `--uninstall-hooks` removes only Token Observatory's entries.

Change the thresholds in `config.json` in the data folder:

```json
{"hook_limit_percent": 90, "hook_context_percent": 60}
```

The 5-hour number comes from the newest of the live check, the status line capture, the desktop app sample, and (for Codex) the conversation's own log. A number older than its window is ignored. Each hook run takes about 50 ms and never blocks or fails the conversation; on any error it prints nothing.

### Claude context window

Claude Code transcripts don't record the context window size. To show a percentage, Token Observatory uses a recorded `[1m]` model ID when there is one, otherwise a window you configure per model. Models Claude Code runs with a 1M window by default are preset to 1,000,000 (listed below). To add or change models, create `config.json` in the data folder (next to `history/`):

```json
{"claude_context_windows": {"claude-sonnet-5-5": 1000000, "claude-haiku-5-5": 200000}}
```

Restart the collector afterwards. The dashboard labels these values "configured capacity" so they aren't mistaken for logged ones. Models documented as 1M by default (`claude-opus-5-5`, `claude-opus-5`, `claude-opus-4-8`, `claude-opus-4-7`, `claude-sonnet-5-5`, `claude-sonnet-5`, `claude-haiku-5-5`) are preset.

The server listens on `127.0.0.1` only and rejects requests whose `Host` header isn't the loopback address.

## Update

```sh
git pull
./install.sh
```

Then quit the running collector so the new version starts on next launch. On macOS run `pkill -f "Token Observatory.app/Contents/Resources/dashboard/server.py"`; on Linux run `pkill -f token-observatory/app/server.py`. Saved history is kept.

## Uninstall

If you added the Claude Code status line or the conversation hooks, remove them first with `--uninstall-statusline` and `--uninstall-hooks` (see [Claude status line](#claude-status-line) and [Conversation hooks](#conversation-hooks)); otherwise Claude Code and Codex keep calling a program that's gone.

```sh
./uninstall.sh           # stop the collector and remove the app; keep saved history
./uninstall.sh --purge   # also delete saved history and the service log
```

## Troubleshooting

| Symptom | What to check |
|---|---|
| Dashboard says a log directory was not found | The tool hasn't been used on this machine, or it uses a custom home. Pass `--claude-home` or `--codex-home`, or set `CLAUDE_CONFIG_DIR` or `CODEX_HOME`. |
| Browser shows "Collector disconnected" | The collector stopped. Reopen the app or run `token-observatory`, then check `service.log`. |
| Port 8765 is in use | Another program owns the port. Use `--port` or `TOKEN_OBSERVATORY_PORT`. |
| A limit shows "Live check failed" | The `claude` or `codex` command wasn't found or isn't signed in. Claude's `/usage` report needs a claude.ai Pro or Max sign-in. If it says Claude Code is signed out, run `claude /login` in a terminal, then click **Refresh**. |
| Numbers change only after a reply finishes | Expected. The tools write usage after each response, not while it streams. |
| A chat is missing | Only sessions kept on local disk are read. Browser chats on claude.ai or chatgpt.com, and remote or cloud sessions, are not included. |

The service log is `service.log` in the history folder listed for your platform above.

## Cost estimates

The **Estimated cost** card prices each model's tokens at published API list prices. The collector downloads Anthropic's pricing page (read-only, no data sent) about once a day and caches the parsed prices as `pricing.json` in the data folder; if the download fails it keeps the last good prices and falls back to `prices.json`, which ships with the app (edit it to change the fallback). OpenAI publishes no machine-readable price page, so those models use the estimates in `prices.json`. Set or correct any model in `config.json`:

```json
{"prices": {"gpt-6-luna": {"input": 0.1, "cache_read": 0.01, "output": 0.5}}, "price_updates": false}
```

`cache_read` and `cache_write` default to `input`; per-million-token USD. `"price_updates": false` stops the download. Models with no known price are left out of the total.
