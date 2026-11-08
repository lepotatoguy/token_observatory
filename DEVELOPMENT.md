# Development notes

## Current architecture and setup

The backend lives in backend/ with a Flask application factory, WSGI security middleware, strict Pydantic contracts, incremental log parsers, stateful services and API blueprints. The frontend lives in frontend/ with React 18, strict TypeScript, Vite, TanStack Query for API caching and Zustand for UI state. Stats is part of the React app.

Use Python 3.10 or later and Node.js 20 or later. Create a virtual environment, install `.[test]`, run `npm ci` in frontend/, then `npm run build`. The build writes frontend/dist and package-owned static assets. Start production with `.venv/bin/python launcher.py --serve`; the default port is 8765. Development uses `npm run dev` in frontend/ and `.venv/bin/python launcher.py --serve --port 8766` so the Vite API proxy reaches the backend.

The factory starts no background workers. The launcher explicitly starts and stops collection, live-limit, price and update workers. Tests construct isolated apps without scanning personal logs. Backend tests run with `.venv/bin/python -m pytest`; frontend tests run with `npm test -- --run` in frontend/.

New daily archives use atomic, private gzip JSON files. Existing plain JSON history remains readable and appears once per day in the selector. Python wheels include backend/static and backend/data/prices.json after the frontend build. Native standalone release builds use packaging/token_observatory.spec; source macOS app builds use build_app.py. Source builds require the selected Python runtime on the same machine.

MiniMax tracking remains local-only. The native read-only SQLite importer and model-tagged response splitting are preserved. Disabling a provider does not hide recorded history. Five-hour hard thresholds and weekly reserves remain independent.

The sections below document accounting and other retained behavior; module names now refer to backend/parsers or backend/services rather than root-level files.


Technical details for people working on Token Observatory or checking exactly what its numbers mean. For installing and using the app, see [README.md](README.md) and [INSTALL.md](INSTALL.md).

## Run from source

```sh
.venv/bin/python launcher.py --serve
```

Open <http://127.0.0.1:8765>. Stop with Ctrl+C. The first scan reads every retained log and can take longer than later updates.

Custom locations and port:

```sh
.venv/bin/python launcher.py --serve --port 8766 --codex-home /path/to/.codex --claude-home /path/to/.claude --data-dir /path/to/history
```

`CODEX_HOME` and `CLAUDE_CONFIG_DIR` are honored. Log defaults: `~/.codex/sessions` and `~/.claude/projects`.

`python3 launcher.py` starts the collector in the background once and opens the browser (`--no-open`, `--stop`, `--port N`, `--version`; also `--statusline`, `--hook [claude|codex|minimax]`, `--install-statusline`, `--install-hooks` and their `--uninstall-*` forms). It is also the entry point of the standalone builds.

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
- Shared limit settings store warn and hard as used percentages, plus weekly_reserve as a remaining percentage; null disables each action. Existing hard values remain five-hour thresholds with a 3% weekly reserve after migration. Warning-only settings keep weekly stops disabled. The shared hard_threshold helper selects reported 300-minute and 10080-minute windows independently. Warning cannot exceed the five-hour hard threshold. Theme and dashboard defaults remain browser settings.
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
- Cost estimate (`pricing.py`, `prices.json`): `GET /api/pricing` returns price entries in precedence order: config overrides, daily cached Anthropic prices, then bundled prices. OpenAI/MiniMax bundled entries carry official source URLs and verification dates. `eventPricing` applies per-model `long_prompt` thresholds (default 100k for legacy Anthropic entries; 272k for the verified OpenAI entries). Null component rates contribute $0 with an unreported flag; known components still contribute. Local providers override model prices to $0. `costOf` tracks known-price/local token coverage and fallback model names. Cards and breakdowns append * when unreported prices contribute $0. Set `TOKEN_OBSERVATORY_PRICE_UPDATES=0` or `"price_updates": false` to skip the Anthropic download.
- Conversation hooks use UserPromptSubmit, PreToolUse and PostToolUse. PreToolUse denies supported calls; prompts return decision:block and continue:false; post-tool events return continue:false. Warnings supply systemMessage and additionalContext. Hard enforcement repeats on each event; history remains deduplicated per window/policy. Prompt checks and tool checks throttled to 30 seconds use one-second interface timeouts. Fresh usage clears only its own window below its threshold. Expired snapshots do not block. Metadata-only hook-state.json uses atomic writes and a nonblocking process lock; errors or contention fail open. In-flight work, parallel requests and unsupported host paths limit enforcement. Context reminders condense and continue above hook_context_percent, default 60, unless a hard condition is active. Installation preserves other hooks and requires Codex trust through /hooks.
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
.venv/bin/python -m pytest
cd frontend
npm test -- --run
npm run build
```

## Building and releasing

The standalone builds are made with PyInstaller from `packaging/token_observatory.spec`:

```sh
pip install pyinstaller==6.11.1
pyinstaller --noconfirm packaging/token_observatory.spec
```

On macOS this makes `dist/Token Observatory.app`; on Linux and Windows a one-file `dist/token-observatory` executable. `python3 packaging/build_deb.py dist/token-observatory <version> out.deb` wraps the Linux executable as a `.deb` (needs `dpkg-deb`).

To release:

1. Bump `VERSION` in `backend/version.py` and the package version in `pyproject.toml` and add an entry to [CHANGELOG.md](CHANGELOG.md).
2. Optionally run **Release** from the Actions tab to build and smoke-test all three platforms without publishing.
3. Tag and push: `git tag -a v1.2.3 -m "Token Observatory v1.2.3" && git push origin v1.2.3`. The workflow checks the tag against `VERSION`, builds on macOS (Apple silicon), Ubuntu, and Windows runners, smoke-tests each build, adds a `git archive` source tarball (`TokenObservatory-<version>-source.tar.gz`, used by source installs to update), and publishes the release with `SHA256SUMS.txt`. The in-app updater looks for these exact asset names, so keep them stable.

`python3 build_app.py` builds the source-based macOS app in `~/Applications`, with a private environment using the selected Python 3.10 or later installation. Checkout builds regenerate the frontend; release source archives carry compiled assets. The source app still requires its base Python installation.

### Floating widget

The floating widget needs Qt, a required dependency (PySide6-Essentials). It is a separate process: the `Widget` service in `backend/services/widget_control.py` stores the on/off setting in `widget.json` and starts `launcher.py --float --port N` detached while the setting is on. A widget started that way is marked managed (`TOKEN_OBSERVATORY_WIDGET_MANAGED=1`): it polls `GET /api/quota?client=widget` and `GET /api/widget` every 5 seconds and quits when the setting is off or the collector is unreachable for 3 polls. A hand-started `--float` is unmanaged and ignores the setting. A `QLockFile` keeps one widget running; a second exits with code 75.

| Path | Purpose |
|---|---|
| backend/services/quota.py | Reduces a snapshot to one row per account: model, session window, weekly window |
| backend/services/float_model.py | Display model and palette, free of any GUI toolkit so it can be tested without a display |
| backend/services/float_window.py | The Qt widget: the pill, its meters, dragging and the position file |
| backend/services/float_panel.py | Entry point that reports the missing extra instead of failing |

`float_window` imports PySide6 at module level and `float_panel` imports it through `importlib`. `packaging/token_observatory.spec` imports PySide6 unconditionally, so a build without it fails, and the release workflow keeps Qt installed for packaging.

### Window warm-up

`backend/services/warmup.py` stores per-provider daily times in `warmup.json` and one outcome per slot (provider, date, time) in `warmup-state.json` (last 200). A `Runtime` job calls `tick()` every 30 seconds: due slots are sent, slots 30 minutes or more late are recorded as `missed`, and slots are skipped as `skipped_active` when the five-hour window has a future reset and some usage. `backend/services/warmup_send.py` runs `claude -p hello --model haiku --effort low --no-session-persistence --tools ''` or `codex exec --sandbox read-only -c model_reasoning_effort=low hello` (60 second timeout, one send at a time) and discards the reply. When the window is used up (100% with a future reset) at a due slot, the slot is deferred to `resets_at + 60` seconds, kept in `warmup-state.json`, re-checked at that time, and recorded `missed` if it is 30 minutes or more late. A due warm-up reads fresh limits through `Store.refresh_live` first. Slots use local wall-clock time, so a time inside a spring daylight-saving gap is recorded as `missed`.

The warm-up Claude run creates an empty project folder under `~/.claude/projects` for the data folder. A Codex warm-up is a normal Codex session, so its few tokens appear in usage like any other session.

## Repository layout

| Path | Purpose |
|---|---|
| backend/app.py, backend/config.py, backend/middleware/ | Flask factory, configuration and request security |
| backend/parsers/ | Incremental Claude/Codex logs, local proxy and LM Studio records |
| backend/services/ | Store, limits, pricing, history, providers, hooks, native MiniMax and updates |
| backend/models/ | Strict Pydantic contracts |
| backend/api/ | Health and dashboard routes |
| backend/data/prices.json | Package-owned fallback prices, copied from root prices.json |
| backend/static/ | Generated production frontend included in packages |
| frontend/src/ | React components, typed API client, query hooks, UI store and pure utilities |
| frontend/dist/ | Generated Vite production output |
| tests/ | Backend, API, lifecycle, installer and packaging tests |
| launcher.py, backend/launcher.py | Compatibility entry point and CLI implementation |
| packaging/, .github/workflows/release.yml | Standalone native packages and release workflow |
| install.sh, uninstall.sh, scripts/ | Source installation and launchers |
| build_app.py, launch-app.sh | Source-based macOS application |

Generated assets, node_modules, dist, build, and private runtime data are ignored by git. Build the frontend before building a Python wheel so its static assets are included.

### MiniMax accounting

MiniMax tracking is local-only. The read-only native SQLite importer and model-tagged Claude/Codex splitting retain recorded usage without account API calls. Codex segments merge before splitting, so cumulative counters are not counted twice. Unknown quotas and capacities remain unreported. The legacy manual credential API is retained for compatibility, but the dashboard does not offer credentials and collection/hooks do not call remote MiniMax quotas.
