# Development notes

Technical details for people working on Token Observatory or checking exactly what its numbers mean. For installing and using the app, see [README.md](README.md) and [INSTALL.md](INSTALL.md).

## Run from source

```sh
python3 server.py
```

Open <http://127.0.0.1:8765>. Stop with Ctrl+C. The first scan reads every retained log and can take longer than later updates.

Custom locations and port:

```sh
python3 server.py --port 8766 --codex-home /path/to/.codex --claude-home /path/to/.claude --data-dir /path/to/history
```

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` are honored. Log defaults: `~/.codex/sessions` and `~/.claude/projects`.

`python3 launcher.py` starts the collector in the background once and opens the browser (`--no-open`, `--stop`, `--port N`, `--version`). It is also the entry point of the standalone builds.

## Features

- Per-chat fresh input, cache reads, cache writes, output, and reasoning when recorded.
- One row per conversation, joining Codex log segments and Claude Code or Codex subagents.
- Live refresh every two seconds, with incremental reads after initial discovery.
- Time ranges: today, last 48 hours, last 7 days, last 30 days, and all retained logs.
- Provider filters, search, subagent filtering, pause, and CSV/JSON exports of filtered totals. Tokens and Last activity sort in either direction; newest activity is the default.
- With no row selected, the inspector combines usage from chats matching the current filters and search. Select a row for its details; select it again or choose All conversations to go back.
- Automatic daily JSON archives and a saved-history selector.
- Latest recorded context occupancy, compaction counts, and Codex account quota snapshots with reset times.
- Source status, malformed-record warnings, and explicit missing-data labels.

## Data folder and JSON history

| Platform | Data folder |
|---|---|
| macOS | `~/Library/Application Support/Token Observatory` |
| Linux | `$XDG_DATA_HOME/token-observatory` (default `~/.local/share/token-observatory`) |
| Windows | `%APPDATA%\Token Observatory` |

It holds `history/YYYY-MM-DD.json`, `service.log`, `collector.pid`, and the optional `config.json`.

The collector captures changes at most once per minute, including when the browser is closed. It keeps the latest capture for each calendar day in this computer's time zone. Each file contains normalized sessions, usage events, context and quota snapshots, source paths, capture time, and schema version. Prompts and credentials are excluded.

Choose a saved date beside the time-range filter to reopen history; filters then use the snapshot capture time. Choose **Live** to go back. Sessions observed earlier in a day stay in its archive if their log files disappear; `last_observed_at` records the last capture that saw them. Writes are atomic with private permissions, and save failures appear in the dashboard. Up to one minute of changes can await the next capture.

**Export JSON** downloads the current filtered view: export time, filters, lifetime totals, filtered totals, and usage events. Automatic archives always capture the full local view.

## Accounting

**Codex.** Input includes cached tokens, so fresh input is separated from cache reads and writes before summing. Reasoning is already included in output. Responses are deduplicated by response ID across log segments. The first session metadata identifies the executing thread; inherited parent metadata can't overwrite it. Records belonging to other threads are excluded. Legacy segments without response records use cumulative token-count deltas, joined across segments before subtraction. Legacy counters that overlap modern records are excluded. Quota-only token-count events add nothing.

**Claude Code.** Response blocks sharing a response ID are deduplicated, keeping the largest value for each token field. Nonempty `cost-state.modelUsage` is a fallback when no response usage exists; those totals have no per-request timestamps and appear only in the all-logs range. Cost is shown only when Claude Code reports it with a known model cost. It is not a subscription bill. Subagent logs (`<session>/subagents/agent-*.jsonl`, used heavily by the desktop Code tab) carry the parent chat's session ID, so their tokens count toward that chat. They often keep only the streaming-start usage snapshot, so subagent output counts can be low.

**Context.** Input plus output from the latest recorded response, separate from lifetime totals. The card shows that request's fresh input, cache read and write, output, and reasoning. Codex capacity is the value recorded in the session. Claude transcripts don't record capacity, so it is 1M when Claude Code recorded a `[1m]` model ID (in `requestedModel` or `.claude.json`), otherwise the per-model window from `config.json` (shown as "configured capacity"; `claude-opus-5-5` defaults to 1,000,000). When a transcript has no cost-state, the cost Claude Code saved in `.claude.json` at the end of that project's last session is shown as "Reported cost at session end". System prompt, tool, MCP, memory, and skill attribution and auto-compaction thresholds aren't logged by either tool. No character-based estimates are used.

**Coverage.** Only session files kept on local disk are read. Archived Codex sessions, remote sessions, and claude.ai or chatgpt.com browser chats are not included. Codex conversations group by identity, not title. Forks can contain inherited history. Time filters use usage timestamps in the browser's time zone. Context, compactions, cost, and quotas are lifetime or latest values; a quota snapshot is account-wide and may be stale. "Recent" means a log changed within five minutes, not that a model is generating. Missing usage is unreported, not zero.

## Security

The server binds only to `127.0.0.1`, rejects unrelated Host headers and cross-site browser reads, and serves only its dashboard assets and normalized telemetry. It never uploads data, alters source logs, or changes settings. From Claude Code's `.claude.json` it reads only each project's last session ID, cost, and model IDs. Chat titles, project names, session IDs, and file paths appear in local responses and exports. Don't expose the port through a tunnel.

## Tests

```sh
python3 -m unittest -v
node --check app.js
node test_app.js
```

## Building and releasing

The standalone builds are made with PyInstaller from `packaging/token_observatory.spec`:

```sh
pip install pyinstaller==6.11.1
pyinstaller --noconfirm packaging/token_observatory.spec
```

On macOS this makes `dist/Token Observatory.app`; on Linux and Windows a one-file `dist/token-observatory` executable. `python3 packaging/build_deb.py dist/token-observatory <version> out.deb` wraps the Linux executable as a `.deb` (needs `dpkg-deb`).

To release:

1. Bump `VERSION` in `launcher.py` and add an entry to [CHANGELOG.md](CHANGELOG.md).
2. Optionally run **Release** from the Actions tab to build and smoke-test all three platforms without publishing.
3. Tag and push: `git tag -a v1.2.3 -m "Token Observatory v1.2.3" && git push origin v1.2.3`. The workflow checks the tag against `VERSION`, builds on macOS (Apple silicon), Ubuntu, and Windows runners, smoke-tests each build, and publishes the release with `SHA256SUMS.txt`.

`python3 build_app.py` builds the older source-based macOS app in `~/Applications`, which runs `server.py` with the Mac's own Python.

## Repository layout

| Path | Purpose |
|---|---|
| `server.py` | Log discovery, parsing, HTTP API (`/api/usage`, `/api/history/<day>`, `/api/health`) |
| `codex_usage.py`, `claude_context.py` | Codex accounting; Claude capacity and cost |
| `archive.py` | Daily JSON snapshots and per-platform data folder |
| `launcher.py` | Start-once launcher; entry point of the standalone builds |
| `index.html`, `app.js`, `style.css`, `logo.svg` | Dashboard UI |
| `packaging/` | PyInstaller spec, icons, `.deb` builder, release notes |
| `.github/workflows/release.yml` | Release builds |
| `install.sh`, `uninstall.sh`, `scripts/` | Source install for macOS and Linux |
| `build_app.py`, `launch-app.sh` | Source-based macOS app |
| `test_*.py`, `test_app.js` | Tests |

`dist/`, `build/`, and `private/` are ignored by git.

Telemetry references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage).
