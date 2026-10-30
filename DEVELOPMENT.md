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
- Provider settings (`providers.py`, `providers.json` in the data folder): which of Claude Code, Codex, Ollama, LM Studio and llama.cpp are tracked, with a first-run prompt that preselects what `detect()` finds (log folders, a server answering on the usual port, the command on PATH, or the app folder). Until setup runs, Claude Code and Codex stay on as before. Turned-off tools are not scanned, not asked for live limits, and left out of `/api/usage`.
- Local LLMs (`local_proxy.py`): a recording pass-through per enabled tool on `127.0.0.1` (default 11435 to 11434 for Ollama, 1235 to 1234 for LM Studio, 8081 to 8080 for llama.cpp). It forwards requests unchanged (except adding `stream_options.include_usage` to streamed OpenAI-style requests that don't set it), streams replies back, and reads Ollama's `prompt_eval_count` / `eval_count` or the OpenAI `usage` object from the reply. Each answered POST with counts appends `{at, tool, model, input, output, endpoint}` to `local-usage.jsonl`, plus `conversation` (a SHA-256 prefix of the model and first user message) and `title` (that message's first 60 characters) for chat requests. Chat apps resend the whole conversation each turn, so the first user message identifies the chat. Replies and the rest of the prompts are never stored. Requests without chat messages are grouped by tool, model and local day.
- Limit forecast: logged tokens per quota percent in the current window, projected at the pace of the last hour (5-hour) or last day (weekly). Reset alerts remember each window's reset time in the browser and, once it passes for a window at least 50% used, show a note for 30 minutes and send a desktop notification when Alerts are on.
- Dark theme: every color is a CSS variable with a dark value; `theme.js` applies the saved Auto, Light or Dark choice before the page draws.
- Provider filters, search, subagent filtering, pause, and CSV/JSON exports of filtered totals. Tokens and Last activity sort in either direction; newest activity is the default.
- Limit controls (`limit_control.py`, `/api/limit-control` GET/POST): `limit-settings.json` shares per-provider modes and thresholds with hooks. Defaults migrate `hook_limit_percent`. Atomic writes and cross-process locking protect preferences and `limit-events.json`. History is pruned to 30 days, 1,000 events and 256 KiB with at most 64 watched windows. It stores metadata only and is attached to live usage after archive capture to avoid duplication in daily snapshots. Pause events are recorded only for actual hook emissions. The collector tracks resets without an open page; notifications use the existing opt-in browser Alerts path while the dashboard is open. Reset clears the pause automatically, but hooks cannot start an idle chat turn. Settings apply on the next hook event without reinstalling.
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
- Conversation hooks (`session_hooks.py`, `launcher.py --hook`): `UserPromptSubmit` and `PostToolUse` deliver `hookSpecificOutput.additionalContext`. These are appended to the host conversation, not retractable messages. `hook-state.json` stores per-provider/session and per-limit window transitions, with nonblocking cross-process locking and atomic writes. Primary and secondary limits are read from saved captures, live checks and Codex rollouts. Threshold (default 90%) and exhaustion (100%) notices are distinct; reset events expire only the affected window. A 60-second reset timestamp tolerance suppresses source jitter. Legacy `handoff` state is migrated. Every user prompt attempts a fresh lookup through `live_limits.py` (one-second interface timeout, under the installed five-second hook timeout) and delivers a policy superseding historical Token Observatory pauses even if state was pruned. Lookup failure still delivers recovery instructions: accept explicit user-confirmed reset; a fresh exhausted limit prevents resumption for that limit. Fresh readings are retained so older saved snapshots cannot re-pause work on the next tool event. Handoffs preserve authorization and never mandate another conversation. Hooks do not interpret user intent or enforce model behavior; the host model applies the conditional resumption policy. Unknown reset times remain unreported. Context reminders condense and continue at `hook_context_percent` (default 60), re-armed below threshold, suppressed while usage is above its pause threshold to avoid conflicting instructions. Sessions are pruned after seven days. Hook errors or lock contention return no output. Installation merges settings, preserves other hooks, and requires Codex trust through `/hooks` when the command changes.
- Daily budget and alert settings live in the browser's localStorage (`to.*` keys), per browser. The budget counts every recorded token today across providers, subagents and cache reads included.
- Breakdown by model (from each usage event) or project (from the session's working folder), with each group's share of input served from cache.
- Trends use every retained log for the selected provider, independent of the time range: today vs the average of the previous 7 days, the last 7 days vs the 7 before, the busiest of the last 30 days, and a 28-day weekday-by-hour heatmap.
- Context pressure: chats active in the last hour whose latest request uses 80% or more of a known window are listed in a banner and flagged in the conversation list. With Alerts on, the browser notifies once per chat at 80% and 95%, and once per day at 80% and 100% of the budget.
- Updates (`updater.py`, `update_install.py`, `updates.js`): at start (when the last check is over an hour old) and then every 24 hours, a collector thread reads `https://api.github.com/repos/lepotatoguy/token_observatory/releases/latest` (no auth, 10-second timeout). Drafts, pre-releases, tags that aren't plain `x.y.z` and versions not newer than `VERSION` are ignored; failures go to `service.log`. Results are cached in `update-check.json`, and the dashboard's choices (`notify`, `dismissed`) in `update-settings.json`. `notify: false` stops checks. `GET /api/update` returns `current`, `install`, `latest` (version, notes, url), `prompt` and `progress`. `POST /api/update/settings` takes `{"notify": bool}` and/or `{"dismiss": "x.y.z"}`; `POST /api/update/install` starts the update in a thread and the page polls `GET /api/update` until `current` is the new version, then reloads. Both POSTs have the `/api/refresh` Host, Origin and cross-site checks, and also require `Content-Type: application/json` and a body of at most 1 KB. The asset for the install type (`update_install.kind`: `macos-app`, `windows-exe`, `linux-deb`, `source-app`, `source-linux`, `git`, `unknown`) must be listed at `github.com/<repo>/releases/download/<tag>/`; redirects may only go to `github.com`, `objects.githubusercontent.com`, `release-assets.githubusercontent.com` or `codeload.github.com` over HTTPS. Its SHA-256 must match `SHA256SUMS.txt` (and GitHub's `digest` field when present). The collector then restarts with `os.execve` (same PID; history is saved first; launcher-started collectors re-run `--serve`). Windows instead writes a `cmd` helper to the temp folder that waits for both PyInstaller processes to exit, swaps the `.exe` and starts it with `--no-open`. A macOS app swap keeps the old app in a `.token-observatory-update-*` folder beside it until the new collector is serving (`update-state.json`). `TOKEN_OBSERVATORY_UPDATE_CHECKS=0` turns checks off (the tests set it). For testing only, `TOKEN_OBSERVATORY_UPDATE_SERVER=http://127.0.0.1:<port>` sends the API request and downloads to a loopback server instead of GitHub.
- Cache: the inspector shows the share of input served from cache and, for Claude, cache writes split into 5-minute and 1-hour (`write_1h` on each Claude event, from `usage.cache_creation`).

## Data folder and JSON history

| Platform | Data folder |
|---|---|
| macOS | `~/Library/Application Support/Token Observatory` |
| Linux | `$XDG_DATA_HOME/token-observatory` (default `~/.local/share/token-observatory`) |
| Windows | `%APPDATA%\Token Observatory` |

It holds `history/YYYY-MM-DD.json`, `service.log`, `collector.pid`, the optional `config.json`, and, when used, `claude-rate-limits.json`, `live-limits.json`, `pricing.json` (downloaded prices), `hook-state.json`, `update-check.json`, `update-settings.json` and an `updates` folder for downloads.

The collector captures changes at most once per minute, including when the browser is closed. It keeps the latest capture for each calendar day in this computer's time zone. Each file contains normalized sessions, usage events, context and quota snapshots, source paths, capture time, and schema version. Prompts and credentials are excluded.

Choose a saved date beside the time-range filter to reopen history; filters then use the snapshot capture time. Choose **Live** to go back. Sessions observed earlier in a day stay in its archive if their log files disappear; `last_observed_at` records the last capture that saw them. Writes are atomic with private permissions, and save failures appear in the dashboard. Up to one minute of changes can await the next capture.

**Export JSON** downloads the current filtered view: export time, filters, lifetime totals, filtered totals, and usage events. Automatic archives always capture the full local view.

## Accounting

LM Studio desktop chats (`lmstudio_chats.py`) are read from saved `.conversation.json` files. Usage sums `genInfo.stats.promptTokensCount` and `predictedTokensCount`, including retained response versions. Repeated step IDs count once per chat. Context capacity comes from the saved load configuration. Token counts are not inferred from message text or the chat-level `tokenCount`. Response times use the recorded millisecond prefix in recognized step IDs; unknown formats remain undated and appear only in All retained logs. The reader caches unchanged files and retains the last valid capture during partial writes. LM Studio can change this internal file format; missing statistics remain unreported.

**Codex.** Input includes cached tokens, so fresh input is separated from cache reads and writes before summing. Reasoning is already included in output. Responses are deduplicated by response ID across log segments. The first session metadata identifies the executing thread; inherited parent metadata can't overwrite it. Records belonging to other threads are excluded. Legacy segments without response records use cumulative token-count deltas, joined across segments before subtraction. Legacy counters that overlap modern records are excluded. Quota-only token-count events add nothing.

**Claude Code.** Response blocks sharing a response ID are deduplicated, keeping the largest value for each token field. Nonempty `cost-state.modelUsage` is a fallback when no response usage exists; those totals have no per-request timestamps and appear only in the all-logs range. Cost is shown only when Claude Code reports it with a known model cost. It is not a subscription bill. Subagent logs (`<session>/subagents/agent-*.jsonl`, used heavily by the desktop Code tab) carry the parent chat's session ID, so their tokens count toward that chat. They often keep only the streaming-start usage snapshot, so subagent output counts can be low.

**Context.** Input plus output from the latest recorded response, separate from lifetime totals. The card shows that request's fresh input, cache read and write, output, and reasoning. Codex capacity is the value recorded in the session. Claude transcripts don't record capacity, so it is 1M when Claude Code recorded a `[1m]` model ID (in `requestedModel` or `.claude.json`), otherwise the per-model window from `config.json` (shown as "configured capacity"). Models documented as 1M by default ([model configuration](https://code.claude.com/docs/en/model-config): Opus 4.7 and later, Sonnet 5 and later, Haiku 5.5) are preset to 1,000,000; `CLAUDE_CODE_DISABLE_1M_CONTEXT=1` would make that wrong, so override it in `config.json` if you use it. When a transcript has no cost-state, the cost Claude Code saved in `.claude.json` at the end of that project's last session is shown as "Reported cost at session end". System prompt, tool, MCP, memory, and skill attribution and auto-compaction thresholds aren't logged by either tool. No character-based estimates are used.

**Coverage.** Only session files kept on local disk are read. Archived Codex sessions, remote sessions, and claude.ai or chatgpt.com browser chats are not included. Codex conversations group by identity, not title. Forks can contain inherited history. Time filters use usage timestamps in the browser's time zone. Context, compactions, cost, and quotas are lifetime or latest values; a quota snapshot is account-wide and may be stale. "Recent" means a log changed within five minutes, not that a model is generating. Missing usage is unreported, not zero.

## Security

The server binds only to `127.0.0.1`, rejects unrelated Host headers and cross-site browser reads, and serves only its dashboard assets and normalized telemetry. It never uploads data or alters source logs, it replaces itself only after you choose **Update now** and the download matches the release checksums, and it changes Claude Code or Codex settings only when you run an `--install-*` or `--uninstall-*` command. The local LLM pass-throughs also listen only on `127.0.0.1` and forward the client's `Origin` header unchanged, so the local server's own origin checks still apply. `POST /api/refresh`, `POST /api/providers`, `POST /api/update/settings` and `POST /api/update/install` have the same Host and cross-site checks and also reject a foreign `Origin`; the provider and update POSTs also require a JSON content type. From Claude Code's `.claude.json` it reads only each project's last session ID, cost, and model IDs. Chat titles, project names, session IDs, and file paths appear in local responses and exports. Don't expose the port through a tunnel.

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
3. Tag and push: `git tag -a v1.2.3 -m "Token Observatory v1.2.3" && git push origin v1.2.3`. The workflow checks the tag against `VERSION`, builds on macOS (Apple silicon), Ubuntu, and Windows runners, smoke-tests each build, adds a `git archive` source tarball (`TokenObservatory-<version>-source.tar.gz`, used by source installs to update), and publishes the release with `SHA256SUMS.txt`. The in-app updater looks for these exact asset names, so keep them stable.

`python3 build_app.py` builds the older source-based macOS app in `~/Applications`, which runs `server.py` with the Mac's own Python.

## Repository layout

| Path | Purpose |
|---|---|
| `server.py` | Log discovery, parsing, HTTP API (`/api/usage`, `/api/history/<day>`, `/api/health`, `/api/update`, `/api/providers`, `POST /api/refresh`, `POST /api/providers`, `POST /api/update/settings`, `POST /api/update/install`) |
| `codex_usage.py`, `claude_context.py` | Codex accounting; Claude capacity and cost |
| `claude_limits.py`, `claude_statusline.py` | Claude usage limits; status line capture and settings install |
| `pricing.py` | Downloads and parses Anthropic's published prices daily (`GET /api/pricing`), plus `config.json` price overrides |
| `prices.json` | Bundled fallback prices used when the online prices cannot be fetched |
| `lmstudio_chats.py` | Read-only LM Studio desktop chat usage |
| `providers.py`, `local_proxy.py` | Provider choices, detection and first-run state; local LLM pass-through and its usage log |
| `live_limits.py` | Live limit checks through `claude -p /usage` and `codex app-server` |
| `session_hooks.py` | Conversation hooks for the 5-hour limit and context, and their install |
| `updater.py`, `update_install.py` | Update check, prompt settings, verified downloads; per-install replacement and restart |
| `archive.py` | Daily JSON snapshots and per-platform data folder |
| `launcher.py` | Start-once launcher, status line and hook modes; entry point of the standalone builds |
| `index.html`, `app.js`, `insights.js`, `updates.js`, `setup.js`, `theme.js`, `style.css`, `logo.svg` | Dashboard UI (`insights.js`: limits, forecast, reset alerts, budget, breakdown, trends, alerts; `updates.js`: update prompt; `setup.js`: providers and first-run setup; `theme.js`: theme choice) |
| `packaging/` | PyInstaller spec, icons, `.deb` builder, release notes |
| `.github/workflows/release.yml` | Release builds |
| `install.sh`, `uninstall.sh`, `scripts/` | Source install for macOS and Linux |
| `build_app.py`, `launch-app.sh` | Source-based macOS app |
| `test_*.py`, `test_app.js` | Tests |

`dist/`, `build/`, and `private/` are ignored by git.

Telemetry references: [Codex App Server](https://learn.chatgpt.com/docs/app-server), [Claude Code monitoring](https://code.claude.com/docs/en/monitoring-usage), [Claude Code status line](https://code.claude.com/docs/en/statusline).
