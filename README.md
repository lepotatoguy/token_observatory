# Token Observatory

A local dashboard for Claude Code and Codex session telemetry. Python 3.9 or later, no packages or API keys. Runs on macOS, Linux and Windows.

Download a standalone build (Python bundled) from [Releases](https://github.com/lepotatoguy/token_observatory/releases/latest): a macOS app, a Linux `.deb`, or a Windows `.exe`. Or install from source:

```sh
git clone https://github.com/lepotatoguy/token_observatory.git
cd token_observatory
./install.sh
```

- [INSTALL.md](INSTALL.md): install, update, uninstall, options and troubleshooting
- [CONTRIBUTING.md](CONTRIBUTING.md): development setup, tests and project rules
- [LICENSE](LICENSE): MIT

## Start

**macOS.** Build and install the app (also writes `dist/Token Observatory.zip`):

```sh
python3 build_app.py
```

Open it:

```sh
open "$HOME/Applications/Token Observatory.app"
```

Stop the background collector:

```sh
pkill -f "Token Observatory.app/Contents/Resources/dashboard/server.py"
```

The app starts the collector and opens your default browser; opening it again reuses the running collector. The collector keeps running after the browser closes. After a restart, open the app again. No login item is installed.

**Linux.** After `./install.sh`:

```sh
token-observatory
```

**Any platform.** Run from this folder:

```sh
python3 server.py
```

Open <http://127.0.0.1:8765>. Stop with Ctrl+C. The first scan reads retained logs and can take longer than later updates. New data appears after the agent writes usage, not continuously while a response streams.

Custom locations and port:

```sh
python3 server.py --port 8766 --codex-home /path/to/.codex --claude-home /path/to/.claude --data-dir /path/to/history
```

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` are honored. Defaults: `~/.codex/sessions`, `~/.claude/projects`.

## Included

- Per-chat fresh input, cache reads, cache writes, output, and reasoning when recorded.
- One row per conversation, joining Codex log segments and Claude Code or Codex subagents. Select a row for its usage timeline.
- Live refresh every two seconds, with incremental reads after initial discovery.
- Today, last 48 hours, last 7 days, last 30 days, and all retained logs.
- Provider filters, search, subagent filtering, sorting, pause, and CSV/JSON exports of filtered totals. Click Tokens or Last activity to sort in either direction; newest activity is the default.
- Automatic daily JSON archives and a saved-history selector.
- Latest recorded context occupancy and Codex logged context capacity.
- Recorded compaction counts and Codex account quota snapshots, including reset times.
- Source status, malformed-record warnings, and explicit missing-data labels.

## JSON history

Private JSON files are stored in `history/YYYY-MM-DD.json` inside the data folder: `~/Library/Application Support/Token Observatory` on macOS, `$XDG_DATA_HOME/token-observatory` (default `~/.local/share/token-observatory`) on Linux, and `%APPDATA%\Token Observatory` on Windows. The collector captures changes at most once per minute, including when the browser is closed. It retains the latest capture for each calendar day in this computer's time zone, rather than a separate file for every refresh. Each file contains normalized sessions, usage events, context and quota snapshots, source paths, capture time, and schema version. Source prompts and credentials are excluded.

Choose a saved date beside the time-range filter to reopen history. Filters then use the snapshot capture time. Choose **Live** to resume live viewing. Sessions observed earlier in a day remain in its archive if their original log files disappear. Their `last_observed_at` field records the last capture that observed them.

**Export JSON** downloads the current filtered view, including export time, filter settings, lifetime totals, filtered totals, and usage events. Automatic archives always capture the complete local view, regardless of browser filters or pause. Do not move the history folder into the app bundle. It survives app updates.

Writes are atomic, with private file permissions. Save failures appear in the dashboard. Up to one minute of changes can await the next capture; source logs remain the primary record. Collector startup is required for new automatic captures. Existing history can be reopened after startup even if source logs no longer exist.

Build or rebuild the app with `python3 build_app.py`. This refreshes the supplied bundle and the installed copy. Runtime diagnostics are written to `service.log` in the data folder.

## Accounting and limits

Codex input includes cached tokens. The collector separates fresh input from cache reads and writes before summing. Reasoning is already included in output. Codex responses are deduplicated by response ID across log segments. The first session metadata identifies the executing thread; inherited parent metadata cannot overwrite it. Records belonging to other threads are excluded. Legacy segments without response records use cumulative token-count deltas, joined across segments before subtraction. Legacy counters overlapping modern records are excluded. Duplicate quota-only token-count events add no consumption.

Claude response blocks sharing a response ID are deduplicated. Each token field keeps the largest recorded value. Nonempty `cost-state.modelUsage` is a fallback when no response usage exists. Such fallback totals lack per-request timestamps and appear only in the all-logs range. Claude cost is displayed only when reported with known model cost; it is not the subscription bill.

Context is input plus output from the latest recorded response. It is separate from lifetime consumption. Codex window capacity is the value recorded in that session. Claude transcripts do not record capacity. For Claude, capacity is 1M when Claude Code recorded a `[1m]` model ID (in the transcript's `requestedModel` or in `.claude.json`); otherwise it comes from a per-model window in `config.json` in the data folder, shown as "configured capacity". `claude-opus-5-5` defaults to 1,000,000. Add or override models with `{"claude_context_windows": {"claude-sonnet-5-5": 1000000}}` and restart the collector. Models without a recorded or configured window show capacity as unreported. When a transcript has no cost-state, the cost Claude Code saved in `.claude.json` at the end of that project's last session is shown as "Reported cost at session end". Exact system prompt, tool, MCP, memory, and skill attribution, plus auto-compaction thresholds, remain unavailable. The context card shows the latest recorded fresh input, cache read/write, output, and reasoning counts for both providers instead of empty category placeholders. Reasoning is included in output. These values describe the root chat request, while the timeline includes selected subagents. No character-based token estimates are used. Older saved captures without these fields explicitly say the detail was not saved.

Only retained local session files are covered. Archived Codex sessions, remote sessions absent from disk, and consumer ChatGPT/Claude browser chats are not included. Provider overrides are labeled by client (Codex or Claude Code); the model name is taken from telemetry. Codex conversations group by identity, not title. Separate chats can share a title. Codex and Claude Code subagents join their root conversation when Include subagents is checked. Legacy saved captures can contain overlapping Codex file rows and show a warning. New captures replace obsolete rows for the same source files. Other historical JSON files are preserved. Claude Code subagent logs (`<session>/subagents/agent-*.jsonl`, used heavily by the Claude desktop Code tab) carry their parent chat's session ID, so their tokens count toward that chat's row. With no row selected, the inspector combines usage from chats matching the current filters and search. Select a row for its details; select it again or choose All conversations to return to combined usage. Context windows remain specific to each chat. Claude subagent logs often keep only the streaming-start usage snapshot, so their output counts can be low.

Time filters apply to usage timestamps in the browser’s timezone. Context, compactions, cost, and account quotas are explicitly lifetime/latest values. A quota snapshot is account-wide and may be stale. A recent log does not establish that a model is currently generating. Missing usage is unreported, not proof of zero consumption.

The server binds only to `127.0.0.1`, rejects unrelated Host headers and cross-site browser reads, and exposes only its dashboard assets and normalized telemetry. It never uploads data, alters source logs, or changes settings. From Claude Code's `.claude.json` it reads only each project's last session ID, cost and model IDs; it reads no credentials. Local process access remains possible, as with other local tools. Chat titles, project names, session IDs, and file paths appear in local responses and exports. Do not expose this port through a tunnel.

## Check

```sh
python3 -m unittest -v
node --check app.js
node test_app.js
```

Official telemetry references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage).

## Repository files

Source and tests live at the repository root. Generated ZIP files live in `dist/`; the single unpacked app lives in `~/Applications/Token Observatory.app`. Local telemetry snapshots and screenshots live in `private/`. Git ignores both folders, generated graphs, runtime caches, and usage logs. Automatic history remains in the Application Support folder described above.

## Contributing and license

See [CONTRIBUTING.md](CONTRIBUTING.md). Released under the [MIT License](LICENSE).
