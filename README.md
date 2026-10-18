# Token Observatory

A local dashboard for Claude Code and Codex session telemetry. Python 3.9 or later, no packages or API keys.

## Start

On macOS, open **Token Observatory** from your user Applications folder (`~/Applications`). Build a local app copy in `dist/Token Observatory.app` with `python3 build_app.py`. It starts the local collector and opens your default browser, without a Terminal window. Reopening the app reuses the running collector.

The collector continues after the browser closes. Reopen the app after a restart to resume collection. No login item is installed. The app uses the Python 3 runtime already installed on this Mac.

Or run from this folder:

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
- Live refresh every two seconds, with incremental reads after initial discovery.
- Today, last 48 hours, last 7 days, last 30 days, and all retained logs.
- Provider filters, search, subagent filtering, sorting, pause, and CSV/JSON exports of filtered totals.
- Automatic daily JSON archives and a saved-history selector.
- Latest recorded context occupancy and Codex logged context capacity.
- Recorded compaction counts and Codex account quota snapshots, including reset times.
- Source status, malformed-record warnings, and explicit missing-data labels.

## JSON history

Private JSON files are stored in `~/Library/Application Support/Token Observatory/history/YYYY-MM-DD.json`. The collector captures changes at most once per minute, including when the browser is closed. It retains the latest capture for each calendar day in America/Chicago, rather than a separate file for every refresh. Each file contains normalized sessions, usage events, context and quota snapshots, source paths, capture time, and schema version. Source prompts and credentials are excluded.

Choose a saved date beside the time-range filter to reopen history. Filters then use the snapshot capture time. Choose **Live** to resume live viewing. Sessions observed earlier in a day remain in its archive if their original log files disappear. Their `last_observed_at` field records the last capture that observed them.

**Export JSON** downloads the current filtered view, including export time, filter settings, lifetime totals, filtered totals, and usage events. Automatic archives always capture the complete local view, regardless of browser filters or pause. Do not move the history folder into the app bundle. It survives app updates.

Writes are atomic, with private file permissions. Save failures appear in the dashboard. Up to one minute of changes can await the next capture; source logs remain the primary record. Collector startup is required for new automatic captures. Existing history can be reopened after startup even if source logs no longer exist.

Build or rebuild the app with `python3 build_app.py`. This refreshes the supplied bundle and the installed copy. Runtime diagnostics are written to `~/Library/Application Support/Token Observatory/service.log`.

## Accounting and limits

Codex input includes cached tokens. The collector separates fresh input from cache reads and writes before summing. Reasoning is already included in output. Cumulative token-count deltas are authoritative when present; response records are used only as fallback. Duplicate quota-only token-count events add no consumption.

Claude response blocks sharing a response ID are deduplicated. Each token field keeps the largest recorded value. Nonempty `cost-state.modelUsage` is a fallback when no response usage exists. Such fallback totals lack per-request timestamps and appear only in the all-logs range. Claude cost is displayed only when reported with known model cost; it is not the subscription bill.

Context is input plus output from the latest recorded response. It is separate from lifetime consumption. Codex window capacity is the value recorded in that session. Claude logs inspected here do not record capacity. Exact system prompt, tool, MCP, memory, and skill attribution, plus auto-compaction thresholds, remain unavailable. No character-based token estimates are presented as exact measurements.

Only retained local session files are covered. Archived Codex sessions, remote sessions absent from disk, and consumer ChatGPT/Claude browser chats are not included. Provider overrides are labeled by client (Codex or Claude Code); the model name is taken from telemetry. Forks can contain inherited history, so aggregate chat totals may overlap. Subagents are separately listed when their source identifies them.

Time filters apply to usage timestamps in the browser’s timezone. Context, compactions, cost, and account quotas are explicitly lifetime/latest values. A quota snapshot is account-wide and may be stale. A recent log does not establish that a model is currently generating. Missing usage is unreported, not proof of zero consumption.

The server binds only to `127.0.0.1`, rejects unrelated Host headers and cross-site browser reads, and exposes only its dashboard assets and normalized telemetry. It never uploads data, alters source logs, changes settings, or reads credentials. Local process access remains possible, as with other local tools. Chat titles, project names, session IDs, and file paths appear in local responses and exports. Do not expose this port through a tunnel.

## Check

```sh
python3 -m unittest -v test_server.py test_archive.py
node --check app.js
```

Official telemetry references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage).

## Repository files

Source and tests live at the repository root. Generated app bundles and ZIP files live in `dist/`. Local telemetry snapshots and screenshots live in `private/`. Git ignores both folders, generated graphs, runtime caches, and usage logs. Automatic history remains in the Application Support folder described above.
