# Installing Token Observatory

Token Observatory is a local dashboard for Claude Code and Codex token usage. It reads the session logs those tools already write on your machine. It has no dependencies, needs no API keys, and uploads nothing.

## Requirements

- Python 3.9 or later, available as `python3`
- Claude Code and/or Codex, used on the same machine (otherwise there is nothing to show)
- macOS or Linux. On Windows, see [Run from source](#run-from-source).

Check your Python version:

```sh
python3 --version
```

On macOS, the Xcode Command Line Tools include Python 3.9. Install them with `xcode-select --install` if `python3` is missing.

## Install

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

The server listens on `127.0.0.1` only and rejects requests whose `Host` header isn't the loopback address.

## Update

```sh
git pull
./install.sh
```

Then quit the running collector so the new version starts on next launch. On macOS run `pkill -f "Token Observatory.app/Contents/Resources/dashboard/server.py"`; on Linux run `pkill -f token-observatory/app/server.py`. Saved history is kept.

## Uninstall

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
| Numbers change only after a reply finishes | Expected. The tools write usage after each response, not while it streams. |
| A chat is missing | Only sessions kept on local disk are read. Browser chats on claude.ai or chatgpt.com, and remote or cloud sessions, are not included. |

The service log is `service.log` in the history folder listed for your platform above.
