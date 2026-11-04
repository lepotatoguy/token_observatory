# Requirements Document

## Introduction

Token Observatory is a local AI token-usage dashboard that reads Claude Code, Codex, Ollama, LM Studio, llama.cpp, and MiniMax session logs and serves a live browser dashboard on loopback. The rewrite modernises the codebase from a flat ~30-file Python/vanilla-JS structure into a properly layered monorepo: a Flask + Pydantic v2 backend in `backend/` and a React 18 + TypeScript + Vite frontend in `frontend/`. All existing user-facing features are preserved; no functionality is removed.

---

## Glossary

- **Token Observatory**: The application being rewritten — a local AI token-usage dashboard.
- **JSONL**: JSON Lines format; a file where each line is a valid JSON object. Used by Claude Code and Codex for session logs.
- **Session**: A single conversation log file parsed into a structured object containing token events, metadata, and context information.
- **Conversation**: One or more sessions grouped by conversation ID; subagent sessions are rolled up into their parent conversation.
- **Provider**: A source of AI token usage — Claude Code, Codex, Ollama, LM Studio, llama.cpp, or MiniMax.
- **Store**: The central orchestrator that owns all parser instances, drives the scan cycle, and holds the cached snapshot.
- **Snapshot**: The full serialised state returned by `GET /api/usage` — a point-in-time capture of all sessions, limits, sources, and archive metadata.
- **Live limits**: Rate-limit percentages fetched in real time from `claude -p /usage` or `codex app-server`, as opposed to values inferred from log files.
- **Loopback-only**: A security constraint requiring all HTTP requests to originate from `127.0.0.1` or `localhost`, enforced by the security middleware.
- **Application factory**: The `create_app()` function pattern in Flask that creates and configures the app instance, enabling test isolation.
- **Pydantic model**: A Python class that declares field types and validates data at construction time, used here to define the JSON contract between backend layers and the API.
- **Zustand**: A lightweight React state-management library used to hold UI-only state (filters, selection, sort order).
- **TanStack Query**: A React data-fetching library that manages API polling, caching, and refetch intervals, replacing the manual `setInterval` polling loop.
- **Cutover**: The final migration step where the new stack takes over port 8765 and legacy flat files are deleted.
- **Migration period**: The period during Tasks 1–13 when both the old server (port 8765) and the new server (port 8766) run simultaneously.

---

## Requirements

### 1. Backend Scaffolding and Security

1.1 The system MUST expose a Flask application created via an application factory (`create_app`) in `backend/app.py`, accepting configuration through environment variables and a `config.py` module.

1.2 The system MUST enforce loopback-only access by rejecting any HTTP request whose `Host` header is not `127.0.0.1:<port>` or `localhost:<port>`, returning HTTP 403 for non-loopback requests.

1.3 The system MUST reject cross-site browser reads by checking `Sec-Fetch-Site` and `Origin` headers on every request, returning HTTP 403 for cross-site requests.

1.4 All mutable API endpoints (`POST /api/refresh`, `POST /api/providers`, `POST /api/limit-control`, `POST /api/update/settings`, `POST /api/update/install`) MUST require `Content-Type: application/json` and reject request bodies larger than 1 024 bytes with HTTP 413.

1.5 The system MUST expose `GET /api/health` returning `{"app":"token-observatory","version":2}` with HTTP 200, usable as a liveness probe without authentication.

1.6 The system MUST set `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and a `Content-Security-Policy` of `default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'` on every response.

1.7 The system MUST include a pytest test suite under `tests/` with a `conftest.py` providing a Flask test client and fixture factories for synthetic log data.

---

### 2. Pydantic Data Models

2.1 The system MUST define Pydantic v2 models covering all data structures exchanged between the backend layers and the API: `TokenEvent`, `SessionTotals`, `Session`, `UsageSnapshot`, `LimitWindow`, `RateLimits`, `ProviderSettings`, `PriceEntry`, and `ArchiveManifest`.

2.2 All models MUST use strict types; integer token counts MUST be `int >= 0`, cost values MUST be `float >= 0.0`, and timestamps MUST be `float | None`.

2.3 The system MUST provide `model_validate` entry points so that raw log dicts can be parsed directly into typed objects without manual field mapping in parser code.

2.4 The `UsageSnapshot` model MUST include fields for `at`, `sessions`, `sources`, `warnings`, `limits`, `accounting_version`, `providers`, `live_limits`, `archive`, and `limit_control`, matching the JSON contract consumed by the existing and new frontend.

---

### 3. Claude and Codex Log Parsers

3.1 The system MUST implement a Claude log parser in `backend/parsers/claude.py` that reads `.jsonl` files under `~/.claude/projects` and extracts per-response token events (`input`, `cached`, `write`, `output`, `reasoning`, `write_1h`), conversation metadata, context occupancy, compaction counts, and quota-reset times with identical accounting to the current `server.py` `Log` class.

3.2 The system MUST implement a Codex log parser in `backend/parsers/codex.py` that reads `.jsonl` session files under `~/.codex/sessions`, handles legacy cumulative-counter segments, deduplicates by response ID, merges subagent threads into their parent conversation, and extracts rate-limit snapshots.

3.3 The Claude parser MUST detect 1M-context model IDs (the `[1m]` suffix on `requestedModel`) and record `marked_1m` on the session, so the context-window service can apply the correct capacity.

3.4 The Codex parser MUST implement `merge_threads` logic that joins split log segments, excludes foreign thread records, and produces a single `Session` per conversation.

3.5 Both parsers MUST support incremental reads: they MUST track the byte offset of the last-read position and read only new lines on subsequent calls without re-reading from the beginning of the file.

3.6 Both parsers MUST record `parse_errors` (count of malformed lines) and surface them through the `Session` model so the dashboard warning banner can report them.

---

### 4. Local Proxy and LM Studio Parsers

4.1 The system MUST implement a local-proxy usage parser in `backend/parsers/local_proxy.py` that reads `local-usage.jsonl` and groups events into `Session` objects by conversation key, matching the current `local_proxy.sessions()` behaviour.

4.2 The system MUST implement an LM Studio chat parser in `backend/parsers/lmstudio.py` that reads `.conversation.json` files from the LM Studio chat folder, extracts `genInfo.stats.promptTokensCount` and `predictedTokensCount`, deduplicates step IDs, and applies context capacity from the saved load configuration.

4.3 Both parsers MUST cache unchanged files (keyed by inode identity and mtime) so repeated calls within a scan cycle do not re-parse unmodified files.

---

### 5. Pricing, Archive, and Providers Services

5.1 The system MUST implement a pricing service in `backend/services/pricing.py` that fetches Anthropic's published price table at most once per day, caches the result as `pricing.json` in the data folder, falls back to the bundled `prices.json` on failure, accepts `config.json` price overrides, and exposes a `snapshot()` method returning a list of `PriceEntry` objects.

5.2 The system MUST implement an archive service in `backend/services/archive.py` that writes a gzip-compressed daily JSON snapshot at most once per minute when the session signature changes, keeps one file per calendar day, and exposes `update(snapshot, signature)` and `load(day_str)` methods.

5.3 The system MUST implement a providers service in `backend/services/providers.py` that reads and writes `providers.json`, detects which tools are installed (Claude Code, Codex, Ollama, LM Studio, llama.cpp, MiniMax) via file-system and port checks, and exposes `enabled(detected)` and `update(payload)` methods.

5.4 The providers service MUST preserve the first-run detection behaviour: on first launch with no `providers.json`, it MUST pre-select only the tools that `detect()` finds active on the machine.

---

### 6. Limits, Live Limits, MiniMax, Limit Control, and Statusline Services

6.1 The system MUST implement a Claude limits service in `backend/services/claude_limits.py` that reads `claude-rate-limits.json` (statusline capture), `plan-usage-history.json` (desktop app), and live-check results, merges them by recency, and returns the authoritative Claude rate-limit object.

6.2 The system MUST implement a live-limits service in `backend/services/live_limits.py` that runs `claude -p /usage` and `codex app-server` in parallel (30-second timeout each), parses their JSON output, caches the result for `LIVE_REUSE_SECONDS` (10 s), and persists it to `live-limits.json`.

6.3 The system MUST implement a MiniMax service in `backend/services/minimax.py` that checks the MiniMax Coding Plan quota via authenticated API, splits mixed-model Codex sessions into separate MiniMax rows, and stores credentials outside the usage-history folder with atomic writes.

6.4 The system MUST implement a limit-control service in `backend/services/limit_control.py` that reads/writes `limit-settings.json` and `limit-events.json` using atomic writes and a cross-process non-blocking lock, prunes history to 30 days / 1 000 events / 256 KiB, and exposes `update(payload)` and `observe(rows)` methods.

6.5 The system MUST implement a statusline service in `backend/services/claude_statusline.py` that parses the Claude Code status-line JSON from stdin, writes it atomically to `claude-rate-limits.json`, and provides `update_settings(install)` to add/remove the status-line entry from Claude Code's `settings.json`.

---

### 7. Store Orchestrator and Core API Endpoints

7.1 The system MUST implement a `Store` class in `backend/services/store.py` that owns the parser instances, services, scan lock, and snapshot cache, and exposes `read()` (returning a cached `UsageSnapshot` refreshed at most every 1.5 s) and `refresh_live()` (triggers a live-limits check then calls `read()`).

7.2 `GET /api/usage` MUST call `store.read()` and return the full `UsageSnapshot` as JSON with HTTP 200. The response MUST be identical in structure to the current `/api/usage` JSON so the existing and new frontend can both consume it during migration.

7.3 `POST /api/refresh` MUST call `store.refresh_live()` and return the refreshed `UsageSnapshot`.

7.4 The Store MUST run a background thread that calls `read()` every 2 seconds and a separate background thread that calls `refresh_live()` every 300 seconds, matching the current collector behaviour.

---

### 8. Remaining API Endpoints

8.1 `GET /api/providers` MUST return the current provider status (settings, enabled list, detected tools, local proxy health, MiniMax status).

8.2 `POST /api/providers` MUST accept a JSON payload, validate it with Pydantic, update `providers.json`, optionally configure MiniMax credentials, and return the updated provider status.

8.3 `GET /api/pricing` MUST return the pricing snapshot from the pricing service.

8.4 `GET /api/history/<day>` MUST load and return the archived daily snapshot for the given `YYYY-MM-DD` string, returning HTTP 404 if not found and HTTP 400 if the file is unreadable.

8.5 `GET /api/limit-control` MUST return the current limit-control snapshot.

8.6 `POST /api/limit-control` MUST accept and validate a JSON payload, update limit settings, rescan, and return the updated snapshot.

8.7 `GET /api/update` MUST return the current update status (current version, latest version, install progress, prompt).

8.8 `POST /api/update/settings` and `POST /api/update/install` MUST behave identically to the current implementation, including the SHA-256 asset verification and same-origin Host/Origin checks.

---

### 9. Session Hooks and Launcher CLI

9.1 The system MUST preserve the `session_hooks` behaviour in `backend/services/session_hooks.py`: UserPromptSubmit, PreToolUse, and PostToolUse hooks enforce the 5-hour limit, context reminders, and hard-stop logic, reading from `limit-settings.json` with a non-blocking lock.

9.2 The system MUST provide a `backend/launcher.py` CLI entry point that replicates all flags of the current `launcher.py`: `--serve`, `--port`, `--no-open`, `--stop`, `--statusline`, `--install-statusline`, `--uninstall-statusline`, `--hook [claude|codex|minimax]`, `--install-hooks`, `--uninstall-hooks`, and `--version`.

9.3 The launcher MUST start the Flask server as a background process (one instance per port), wait up to 60 seconds for `GET /api/health` to return successfully, and open the browser unless `--no-open` is passed.

---

### 10. Frontend Scaffolding

10.1 The system MUST scaffold a React 18 + TypeScript + Vite project under `frontend/` with `package.json`, `vite.config.ts`, and `tsconfig.json`.

10.2 The frontend MUST use Zustand for global UI state (provider filter, selected conversation, sort order, day filter, pause state, history day) and TanStack Query for all API data fetching and polling.

10.3 The frontend MUST configure a Vite dev-server proxy so that `/api/*` requests are forwarded to `http://127.0.0.1:8766` during development, enabling hot-reload without CORS issues.

10.4 The frontend MUST define TypeScript types in `src/types/` mirroring all Pydantic models: `Session`, `TokenEvent`, `UsageSnapshot`, `LimitWindow`, `RateLimits`, `ProviderSettings`, and `PriceEntry`.

10.5 The frontend MUST implement a typed API client in `src/api/client.ts` covering all backend endpoints with proper error handling and typed return values.

---

### 11. Core Dashboard UI

11.1 The system MUST implement a metrics bar component that displays Recorded tokens, Input tokens, Output tokens, Cache read share, and Estimated cost tiles, matching the visual layout and data logic of the current dashboard.

11.2 The system MUST implement an activity chart component that renders an SVG bar chart of input (green) and output (orange) tokens per time bucket, with clickable day bars for drill-down, a day-filter dismissal pill, and a chart-range label.

11.3 The system MUST implement a conversation table component that lists conversations with provider icon, title, model, subagent count, context-pressure badge, token count, and relative last-activity time; supports token and last-activity sort in both directions; and supports free-text search filtering.

11.4 The system MUST implement a conversation inspector component that shows context-window occupancy, per-field token breakdown, recent usage updates, compaction count, rate-limit quota snapshots, and a combined-view fallback when no row is selected.

11.5 The system MUST implement time-range and provider filters, subagent toggle, pause/resume, and CSV/JSON export matching the current feature set.

---

### 12. Insights Panels

12.1 The system MUST implement a limits panel showing the Claude and Codex 5-hour and weekly quota bars with used-percent, reset times, forecast at current pace, and reset-alert notifications.

12.2 The system MUST implement a budget panel showing a per-provider zone bar (proportional to suggested daily share), today's tokens, and configurable daily budget with localStorage persistence.

12.3 The system MUST implement a breakdown panel showing token distribution by model and by project, with cache-read share per group, matching the current insights tab.

12.4 The system MUST implement a trends panel showing today vs. 7-day average, last-7 vs. prior-7, the busiest day in the last 30, and a 28-day weekday-by-hour heatmap.

12.5 The system MUST display a context-pressure banner listing conversations active in the last hour that are at or above 80% context occupancy, with browser notifications on opt-in Alerts.

---

### 13. Dialogs

13.1 The system MUST implement a settings dialog covering theme (Auto/Light/Dark), alert opt-in, budget, and warn/hard limit thresholds stored in localStorage.

13.2 The system MUST implement a providers dialog that displays detected and configured providers, allows enabling/disabling each, and shows local-proxy listen/target port pairs with server-up status.

13.3 The system MUST implement a limit-controls dialog that surfaces the limit-control settings (warn percent, hard percent, weekly reserve, pause/block mode) with live save to `POST /api/limit-control`.

13.4 The system MUST implement a sources dialog listing the log-file directories and counts for each active provider.

13.5 The system MUST implement an update dialog that shows the current and latest version, release notes, an install button (with progress polling), and a dismiss option, matching the current `updates.js` behaviour.

---

### 14. Production Build and Cutover

14.1 The system MUST configure Flask to serve the compiled Vite `dist/` output as static files when `FLASK_ENV != development`, so a single `python backend/launcher.py` serves both the API and the frontend.

14.2 After the new stack is stable and all tests pass, the legacy flat files (`server.py`, `app.js`, `insights.js`, `updates.js`, `setup.js`, `theme.js`, `style.css`, `index.html`, `archive.py`, `claude_context.py`, `claude_limits.py`, `claude_statusline.py`, `codex_usage.py`, `lmstudio_chats.py`, `local_proxy.py`, `live_limits.py`, `limit_control.py`, `minimax.py`, `pricing.py`, `providers.py`, `session_hooks.py`, `updater.py`, `update_install.py`, `launcher.py`) MUST be deleted from the repository root.

14.3 The system MUST include a `pyproject.toml` at the repository root declaring the package as `token-observatory`, specifying `backend/` as the package source, listing runtime dependencies (Flask, Pydantic v2, requests), and configuring pytest to discover tests under `tests/`.

14.4 All backend tests (`pytest`) and frontend tests (`vitest --run`) MUST pass with zero failures before the cutover step executes.
