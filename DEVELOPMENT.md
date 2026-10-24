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

`python3 launcher.py` starts the collector in the background once and opens the browser (`--no-open`, `--stop`, `--port N`, `--version`; also `--statusline`, `--hook [claude|codex]`, `--install-statusline`, `--install-hooks` and their `--uninstall-*` forms). It is also the entry point of the standalone builds.

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
- Day drill-down: ranges of two days or more draw one bar per calendar day; clicking a bar limits every panel to that day (hourly bars). The JSON export records `day` and `until`.
- Live limits (`live_limits.py`): `POST /api/refresh` (the Refresh button, also sent on page load) and a collector thread every 5 minutes run `claude -p /usage --output-format stream-json --verbose --no-session-persistence --strict-mcp-config --setting-sources ""` and read `usage_report.rate_limits.limits` (kind `session` is the 5-hour window, `weekly_all` the weekly one; [Agent SDK reference](https://code.claude.com/docs/en/agent-sdk/typescript)), and run `codex app-server` with `initialize`, `initialized` and `account/rateLimits/read` ([App Server docs](https://learn.chatgpt.com/docs/app-server)). Both in parallel, about 2 seconds, 30-second timeout each. `/usage` is a local command: the result reports 0 turns and 0 tokens, and no transcript is written. Clicks within 10 seconds reuse the last check. A failed check keeps the previous answer and its error appears in `live_limits.errors`. Results are saved in `live-limits.json` in the data folder (the account ID is dropped). Neither path reads credentials; each tool uses its own sign-in.
- Usage limits: the newest of the Codex live check and the newest Codex `rate_limits` snapshot across sessions (`limits.codex` in `/api/usage`, with `observed_at` and `source: live` for the live check). For Claude (`limits.claude`, see `claude_limits.py`), the newest of the live check (`source: live`) and the status line capture wins when it is at least as new as the desktop sample; otherwise, best source first: the status line capture `claude-rate-limits.json` in the data folder, written by `launcher.py --statusline` from the `rate_limits.five_hour` / `rate_limits.seven_day` fields Claude Code passes to its [status line](https://code.claude.com/docs/en/statusline) (Pro and Max plans, after the first reply; `source: statusline`); otherwise the Claude desktop app's `plan-usage-history.json` (newest sample's `u.fh` and `u.sd`, undocumented; the organization ID is never read out) with reset times from `quotaLimits` that Claude Code logs when a request is rejected at a limit, kept only while still in the future (`source: desktop`). The capture wins when it is at least as new as the desktop sample. `--install-statusline` sets `statusLine` in Claude Code's `settings.json` (backup in `settings.json.bak`) and refuses to replace someone else's status line.
- Suggested daily budget: for each provider with a weekly percentage of at least 1 and a reset time, tokens used from the window start (reset minus 7 days) to the snapshot, divided by that percentage, times the percentage left, spread over the days to reset (at least one). Claude's quota is shared with claude.ai and desktop chats that aren't in these logs, so the Claude share tends to be low.
- Budget meter: one zone per provider, its width proportional to that provider's suggested daily share (scaled to a custom budget when one is set), filled by that provider's tokens today, with a line per provider underneath. Without a suggestion the providers' tokens stack on one track. A zone at or over 100% gets a red outline and red text.
- Cost estimate (`pricing.py`, `prices.json`): `GET /api/pricing` returns price entries in precedence order: `config.json` overrides, the parsed table from Anthropic's pricing page (downloaded at most daily, cached as `pricing.json` beside `config.json`, last good copy kept on failure), then the bundled `prices.json`. The dashboard prices each event by its model (Haiku 5.5 switches rate above a 100k prompt) and sums it for the card and breakdown. Set `TOKEN_OBSERVATORY_PRICE_UPDATES=0` or `"price_updates": false` to skip the download.
- Conversation hooks (`session_hooks.py`, `launcher.py --hook`): Claude Code `UserPromptSubmit` and `PostToolUse` command hooks ([hooks reference](https://code.claude.com/docs/en/hooks)), and the same for Codex in `~/.codex/hooks.json` (`--hook codex`, [Codex hooks](https://learn.chatgpt.com/docs/hooks)). Hook input carries no usage numbers, so the hook reads the last megabyte of `transcript_path` for the latest request's context (Claude capacity as in **Context** below; Codex `model_context_window`) and the newest current 5-hour percentage from `claude-rate-limits.json`, `live-limits.json`, the desktop sample (counted for 5 hours) or, for Codex, the rollout's `rate_limits`. A window whose `resets_at` has passed is ignored. At `hook_limit_percent` (default 90) it returns `hookSpecificOutput.additionalContext` asking for a handoff summary in `<cwd>/.claude/handoffs/` (or `.codex/handoffs/`), once per window per session; at `hook_context_percent` (default 60) it asks the model to condense and continue, once per crossing (re-armed when the context drops below). State is in `hook-state.json` in the data folder (sessions pruned after 7 days). Any error prints nothing and exits 0; a run takes about 40 to 60 ms. Hooks can block compaction (`PreCompact`) but not start it, so the note suggests `/compact`; the documented `autoCompactWindow` setting and `CLAUDE_CODE_AUTO_COMPACT_WINDOW` make Claude Code compact earlier on its own. `--install-hooks` merges into `settings.json` (backup `settings.json.bak`) and `hooks.json` (backup `hooks.json.bak`), removes only handlers whose command contains `--hook` and the launcher, uses a 5-second timeout, and writes nothing when already up to date. Codex runs new or changed hooks only after `/hooks` trusts them.
- Daily budget and alert settings live in the browser's localStorage (`to.*` keys), per browser. The budget counts every recorded token today across providers, subagents and cache reads included.
- Breakdown by model (from each usage event) or project (from the session's working folder), with each group's share of input served from cache.
- Trends use every retained log for the selected provider, independent of the time range: today vs the average of the previous 7 days, the last 7 days vs the 7 before, the busiest of the last 30 days, and a 28-day weekday-by-hour heatmap.
- Context pressure: chats active in the last hour whose latest request uses 80% or more of a known window are listed in a banner and flagged in the conversation list. With Alerts on, the browser notifies once per chat at 80% and 95%, and once per day at 80% and 100% of the budget.
- Cache: the inspector shows the share of input served from cache and, for Claude, cache writes split into 5-minute and 1-hour (`write_1h` on each Claude event, from `usage.cache_creation`).

## Data folder and JSON history

| Platform | Data folder |
|---|---|
| macOS | `~/Library/Application Support/Token Observatory` |
| Linux | `$XDG_DATA_HOME/token-observatory` (default `~/.local/share/token-observatory`) |
| Windows | `%APPDATA%\Token Observatory` |

It holds `history/YYYY-MM-DD.json`, `service.log`, `collector.pid`, the optional `config.json`, and, when used, `claude-rate-limits.json`, `live-limits.json`, `pricing.json` (downloaded prices) and `hook-state.json`.

The collector captures changes at most once per minute, including when the browser is closed. It keeps the latest capture for each calendar day in this computer's time zone. Each file contains normalized sessions, usage events, context and quota snapshots, source paths, capture time, and schema version. Prompts and credentials are excluded.

Choose a saved date beside the time-range filter to reopen history; filters then use the snapshot capture time. Choose **Live** to go back. Sessions observed earlier in a day stay in its archive if their log files disappear; `last_observed_at` records the last capture that saw them. Writes are atomic with private permissions, and save failures appear in the dashboard. Up to one minute of changes can await the next capture.

**Export JSON** downloads the current filtered view: export time, filters, lifetime totals, filtered totals, and usage events. Automatic archives always capture the full local view.

## Accounting

**Codex.** Input includes cached tokens, so fresh input is separated from cache reads and writes before summing. Reasoning is already included in output. Responses are deduplicated by response ID across log segments. The first session metadata identifies the executing thread; inherited parent metadata can't overwrite it. Records belonging to other threads are excluded. Legacy segments without response records use cumulative token-count deltas, joined across segments before subtraction. Legacy counters that overlap modern records are excluded. Quota-only token-count events add nothing.

**Claude Code.** Response blocks sharing a response ID are deduplicated, keeping the largest value for each token field. Nonempty `cost-state.modelUsage` is a fallback when no response usage exists; those totals have no per-request timestamps and appear only in the all-logs range. Cost is shown only when Claude Code reports it with a known model cost. It is not a subscription bill. Subagent logs (`<session>/subagents/agent-*.jsonl`, used heavily by the desktop Code tab) carry the parent chat's session ID, so their tokens count toward that chat. They often keep only the streaming-start usage snapshot, so subagent output counts can be low.

**Context.** Input plus output from the latest recorded response, separate from lifetime totals. The card shows that request's fresh input, cache read and write, output, and reasoning. Codex capacity is the value recorded in the session. Claude transcripts don't record capacity, so it is 1M when Claude Code recorded a `[1m]` model ID (in `requestedModel` or `.claude.json`), otherwise the per-model window from `config.json` (shown as "configured capacity"). Models documented as 1M by default ([model configuration](https://code.claude.com/docs/en/model-config): Opus 4.7 and later, Sonnet 5 and later, Haiku 5.5) are preset to 1,000,000; `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` would make that wrong, so override it in `config.json` if you use it. When a transcript has no cost-state, the cost Claude Code saved in `.claude.json` at the end of that project's last session is shown as "Reported cost at session end". System prompt, tool, MCP, memory, and skill attribution and auto-compaction thresholds aren't logged by either tool. No character-based estimates are used.

**Coverage.** Only session files kept on local disk are read. Archived Codex sessions, remote sessions, and claude.ai or chatgpt.com browser chats are not included. Codex conversations group by identity, not title. Forks can contain inherited history. Time filters use usage timestamps in the browser's time zone. Context, compactions, cost, and quotas are lifetime or latest values; a quota snapshot is account-wide and may be stale. "Recent" means a log changed within five minutes, not that a model is generating. Missing usage is unreported, not zero.

## Security

The server binds only to `127.0.0.1`, rejects unrelated Host headers and cross-site browser reads, and serves only its dashboard assets and normalized telemetry. It never uploads data or alters source logs, and it changes Claude Code or Codex settings only when you run an `--install-*` or `--uninstall-*` command. `POST /api/refresh` has the same Host and cross-site checks and also rejects a foreign `Origin`. From Claude Code's `.claude.json` it reads only each project's last session ID, cost, and model IDs. Chat titles, project names, session IDs, and file paths appear in local responses and exports. Don't expose the port through a tunnel.

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
| `server.py` | Log discovery, parsing, HTTP API (`/api/usage`, `/api/history/<day>`, `/api/health`, `POST /api/refresh`) |
| `codex_usage.py`, `claude_context.py` | Codex accounting; Claude capacity and cost |
| `claude_limits.py`, `claude_statusline.py` | Claude usage limits; status line capture and settings install |
| `pricing.py` | Downloads and parses Anthropic's published prices daily (`GET /api/pricing`), plus `config.json` price overrides |
| `prices.json` | Bundled fallback prices used when the online prices cannot be fetched |
| `live_limits.py` | Live limit checks through `claude -p /usage` and `codex app-server` |
| `session_hooks.py` | Conversation hooks for the 5-hour limit and context, and their install |
| `archive.py` | Daily JSON snapshots and per-platform data folder |
| `launcher.py` | Start-once launcher, status line and hook modes; entry point of the standalone builds |
| `index.html`, `app.js`, `insights.js`, `style.css`, `logo.svg` | Dashboard UI (`insights.js`: limits, budget, breakdown, trends, alerts) |
| `packaging/` | PyInstaller spec, icons, `.deb` builder, release notes |
| `.github/workflows/release.yml` | Release builds |
| `install.sh`, `uninstall.sh`, `scripts/` | Source install for macOS and Linux |
| `build_app.py`, `launch-app.sh` | Source-based macOS app |
| `test_*.py`, `test_app.js` | Tests |

`dist/`, `build/`, and `private/` are ignored by git.

Telemetry references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage), [Claude Code status line](https://code.claude.com/docs/en/statusline).
