# Implementation Plan: Token Observatory Codebase Rewrite

## Overview

14 tasks covering backend scaffolding, Pydantic models, log parsers, services, API endpoints, a React/TypeScript frontend, and a final cutover step that deletes the legacy flat files. Tasks are ordered by dependency: infrastructure first, then parsers, services, API, frontend, and finally the production build and cutover.

## Tasks

- [x] 1. Backend scaffolding: Flask factory, security middleware, /api/health, pytest setup
  - Create `pyproject.toml` at repository root declaring package `token-observatory`, source `backend/`, runtime deps `flask`, `pydantic>=2`, `requests`, and pytest config pointing to `tests/`
  - Create `backend/__init__.py` (empty) and `backend/config.py` with `Config` dataclass covering `PORT` (default 8766 during migration), `DATA_DIR`, `CODEX_HOME`, `CLAUDE_HOME`, and boolean env-flag constants
  - Implement `backend/middleware/security.py` — a WSGI middleware class that rejects non-loopback `Host` headers with 403, rejects cross-site POSTs, and injects `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, and `Content-Security-Policy` into every response
  - Implement `backend/app.py` with `create_app(config=None)` that creates the Flask app, attaches `SecurityMiddleware`, registers a `health` Blueprint, and attaches a placeholder `store` key to `app.extensions`
  - Implement `backend/api/health.py` Blueprint with `GET /api/health` returning `{"app":"token-observatory","version":2}` with HTTP 200
  - Create `tests/conftest.py` with a `client` fixture (Flask test client from `create_app`) and a `make_jsonl` factory helper that writes synthetic `.jsonl` files to `tmp_path`
  - Write `tests/test_api/test_health.py` asserting status 200, correct JSON body, and presence of all three security headers on the `/api/health` response
  - Write `tests/test_api/test_security.py` asserting HTTP 403 for requests with a non-loopback `Host` header and for cross-site POST requests

- [x] 2. Pydantic data models
  - Implement `backend/models/session.py` with `TokenEvent` (fields: `at`, `model`, `input`, `cached`, `write`, `output`, `reasoning`, `write_1h`, `cache_unreported`; all int fields `ge=0`), `SessionTotals`, and `Session` matching the `/api/usage` JSON contract; use `model_config = ConfigDict(extra='allow')`
  - Implement `backend/models/limits.py` with `LimitWindow` (id, window_minutes, used_percent, resets_at), `RateLimits` (primary, secondary), and `LiveLimits` (checked_at, errors, claude, codex)
  - Implement `backend/models/providers.py` with `ProviderSettings` (enabled list, setup_done, per-tool port overrides) and `ProviderStatus` (settings, enabled, detected, names, cloud, local)
  - Implement `backend/models/snapshot.py` with `PriceEntry`, `ArchiveManifest`, and `UsageSnapshot` (fields: `at`, `sessions`, `sources`, `warnings`, `limits`, `accounting_version`, `providers`, `live_limits`, `archive`, `limit_control`)
  - Write `tests/test_models/test_session.py` with round-trip serialisation tests and assertions that negative int values raise `ValidationError`
  - Write `tests/test_models/test_snapshot.py` verifying that `UsageSnapshot.model_validate(raw_dict)` succeeds for a realistic synthetic snapshot dict

- [x] 3. Port Claude and Codex parsers
  - Implement `backend/parsers/_helpers.py` with `tokens(usage, claude=False)`, `total(usage)`, and `timestamp(value)` as direct ports of the same helpers in `server.py`
  - Implement `backend/parsers/claude.py` with `ClaudeLog` class: `__init__`, `refresh()` (incremental byte-offset reads, inode-change reset), `consume(data)` (full port of the `claude` branch in `Log.consume`), and `export(titles) -> dict` returning a session dict
  - Implement `backend/parsers/codex.py` with `CodexLog` class (same interface as `ClaudeLog`) and `merge_threads(sessions)` as a direct port of `codex_usage.merge_threads`
  - Ensure `ClaudeLog.consume` sets `marked_1m` when `requestedModel` ends with `[1m]`, and that `CodexLog.consume` handles the `parent_thread_id` / `forked_from_id` / `subagent` fields from `session_meta`
  - Write `tests/test_parsers/test_claude.py`: synthetic assistant-event JSONL, assert token extraction, dedup by response ID, incremental read (second refresh reads zero bytes), `marked_1m` detection, quota-reset extraction
  - Write `tests/test_parsers/test_codex.py`: synthetic `token_count` and `token_usage_record` events, assert delta calculation, legacy counter fallback, `merge_threads` joining parent and subagent logs, foreign-thread exclusion

- [x] 4. Port local proxy and LM Studio parsers
  - Implement `backend/parsers/local_proxy.py` with a `sessions(log_path, enabled)` function that reads `local-usage.jsonl`, groups events by conversation key, and returns a list of session dicts; cache by `(mtime, inode)` to avoid re-parsing unchanged files
  - Implement `backend/parsers/lmstudio.py` with an `LmStudioChats` class (port of `lmstudio_chats.Chats`) that reads `.conversation.json` files, deduplicates step IDs, extracts capacity from load config, and caches unchanged files
  - Write `tests/test_parsers/test_local_proxy.py`: synthetic `local-usage.jsonl`, assert grouping, step-ID dedup, and that a second call with no file change does not re-parse
  - Write `tests/test_parsers/test_lmstudio.py`: synthetic `.conversation.json`, assert token extraction, step-ID dedup, and capacity from load config

- [x] 5. Port pricing, archive, and providers services
  - Implement `backend/services/pricing.py` — port of `pricing.py`: daily download of Anthropic price table, `pricing.json` cache, bundled `prices.json` fallback, `config.json` overrides, `snapshot()` returning list of `PriceEntry`
  - Implement `backend/services/archive.py` — port of `archive.py`: `Archive(data_dir)`, `update(snapshot, signature, force=False)`, `load(day_str)`, gzip atomic writes, one file per calendar day, signature-based dedup within the same minute
  - Implement `backend/services/providers.py` — port of `providers.py`: `Settings(path)`, `detect(claude, codex, data_dir)`, `enabled(detected)`, `update(payload)`, `NAMES`, `CLOUD` constants, first-run pre-selection
  - Write `tests/test_services/test_archive.py`: write a snapshot, assert file exists; call update again with same signature within 1 s, assert no new file; load the saved day, assert round-trip equality
  - Write `tests/test_services/test_providers.py`: assert `detect()` returns empty set when no tools are present; assert `enabled()` returns only detected tools on first run

- [x] 6. Port limits, live limits, MiniMax, limit control, and statusline services
  - Implement `backend/services/claude_limits.py` — port of `claude_limits.py`: `limits(plan_usage, resets, now, capture, live)` merging all sources by recency, `PlanUsage`, `read_capture`, `desktop_folder`
  - Implement `backend/services/live_limits.py` — port of `live_limits.py`: `check(tools, folder)` running `claude -p /usage` and `codex app-server` in parallel (30 s timeout), `find_tool(name)`, result caching via `LIVE_REUSE_SECONDS`
  - Implement `backend/services/minimax.py` — port of `minimax.py`: `split_session(session)`, `usage(folder)`, `configure(payload, folder)`, `validate(payload)`, `status(folder)`
  - Implement `backend/services/limit_control.py` — port of `limit_control.py`: `Control(folder)`, `update(payload)`, `observe(rows)`, `snapshot()`, atomic writes, non-blocking lock, 30-day/1000-event/256 KiB pruning
  - Implement `backend/services/claude_statusline.py` — port of `claude_statusline.py`: `capture(stdin, path)`, `read_json(path)`, `write_json(path, data)`, `update_settings(install)` adding/removing the statusline entry in Claude Code's `settings.json`
  - Write `tests/test_services/test_claude_limits.py`: assert live source wins when newer; assert statusline wins over desktop when same age
  - Write `tests/test_services/test_limit_control.py`: assert history pruned to ≤ 1 000 events; assert atomic write leaves no partial file on simulated error

- [x] 7. Port Store orchestrator and wire /api/usage and /api/refresh
  - Implement `backend/services/store.py` with `Store` class: constructor accepting the same parameters as the current `Store`; `read(force_save=False)` with 1.5 s cache, scan lock, full parser/service orchestration; `refresh_live()` with `LIVE_REUSE_SECONDS` guard and live-lock
  - Update `backend/app.py` to instantiate a real `Store` (using `Config` paths), start the 2 s collector thread and 300 s live-limits thread as daemon threads, and attach the store to `app.extensions['store']`
  - Implement `backend/api/usage.py` Blueprint with `GET /api/usage` (calls `store.read()`) and `POST /api/refresh` (calls `store.refresh_live()`); both serialise with `json.dumps` and return `Content-Type: application/json`
  - Write `tests/test_services/test_store.py`: mock parsers returning synthetic sessions; assert `read()` returns cached dict on second call within 1.5 s; assert `refresh_live()` increments live-check call count
  - Write `tests/test_api/test_usage.py`: `GET /api/usage` returns 200 with `sessions` key; `POST /api/refresh` returns 200; verify body size enforcement (POST with 1025-byte body returns 413)

- [x] 8. Port remaining API endpoints
  - Implement `backend/api/providers.py` Blueprint: `GET /api/providers` and `POST /api/providers` (Pydantic validation, MiniMax credential update, proxy apply, provider status response)
  - Implement `backend/api/pricing.py` Blueprint: `GET /api/pricing` returning pricing service snapshot
  - Implement `backend/api/history.py` Blueprint: `GET /api/history/<day>` with 404/400 error handling
  - Implement `backend/api/limit_control.py` Blueprint: `GET /api/limit-control` and `POST /api/limit-control`
  - Implement `backend/api/updates.py` Blueprint: `GET /api/update`, `POST /api/update/settings`, `POST /api/update/install`; port `updater.py` and `update_install.py` to `backend/services/updater.py`
  - Write `tests/test_api/test_providers.py`: GET returns `enabled` list; POST with invalid payload returns 400; POST with valid payload returns updated status
  - Write `tests/test_api/test_history.py`: GET for a non-existent day returns 404; GET for a written day returns 200 with correct `at` field

- [x] 9. Port session hooks and launcher CLI
  - Implement `backend/services/session_hooks.py` — full port of `session_hooks.py`: `run(stdin, tool, data_dir, plan_usage_path)`, `update_hooks(install)`, `limit_rows(quotas)`, UserPromptSubmit/PreToolUse/PostToolUse logic, non-blocking lock, context-reminder condensing
  - Implement `backend/launcher.py` CLI replicating all flags of the current `launcher.py`: `--serve`, `--port`, `--no-open`, `--stop`, `--statusline`, `--install-statusline`, `--uninstall-statusline`, `--hook`, `--install-hooks`, `--uninstall-hooks`, `--version`; `spawn()` starts `backend/launcher.py --serve`; `serve()` calls `create_app()` and `server.serve_forever()`
  - Write `tests/test_services/test_session_hooks.py`: synthetic limit-settings and hook-state JSON; assert PreToolUse returns block decision when hard threshold exceeded; assert context reminder is emitted above `hook_context_percent`

- [x] 10. Frontend scaffolding
  - Initialise `frontend/` with `package.json` specifying `react@18`, `react-dom@18`, `typescript`, `vite`, `@vitejs/plugin-react`, `@tanstack/react-query`, `zustand`, `vitest`, `@testing-library/react`, and `@testing-library/jest-dom`
  - Write `frontend/vite.config.ts` with `@vitejs/plugin-react` plugin and a dev-server proxy forwarding `/api/*` to `http://127.0.0.1:8766`
  - Write `frontend/tsconfig.json` with `strict: true`, `jsx: react-jsx`, and path alias `@/` → `src/`
  - Implement TypeScript types in `frontend/src/types/`: `session.ts`, `limits.ts`, `providers.ts`, `snapshot.ts` mirroring all Pydantic models
  - Implement `frontend/src/api/client.ts` with typed async functions for all backend endpoints
  - Implement `frontend/src/store/useAppStore.ts` Zustand store with `provider`, `selected`, `paused`, `sort`, `sortDirection`, `day`, `historyDay`, `search`, `agentsIncluded` fields and setter actions
  - Implement TanStack Query hooks: `useUsagePolling.ts` (2 s refetch, disabled when paused), `usePricing.ts` (1 h refetch), `useLimits.ts` (mutation for POST /api/refresh)
  - Implement pure utility modules in `frontend/src/utils/`: `tokens.ts`, `time.ts`, `cost.ts`, `conversations.ts`, `storage.ts`, `theme.ts`, `export.ts`
  - Write Vitest unit tests for `tokens.ts` (`compact` boundary values), `time.ts` (`relative` edge cases), and `conversations.ts` (`groupConversations`, `scoped` time-range filtering)

- [x] 11. Port core dashboard UI
  - Implement `frontend/src/components/layout/Header.tsx` and `Sidebar.tsx` with provider filter, time-range selector, subagent toggle, search, pause/resume, and export buttons wired to Zustand store
  - Implement `frontend/src/components/dashboard/MetricsBar.tsx` displaying Recorded tokens, Input tokens, Output tokens, Cache read share, and Estimated cost tiles
  - Implement `frontend/src/components/dashboard/ActivityChart.tsx` rendering inline SVG bar chart (input green, output orange) with clickable day bars and day-filter pill
  - Implement `frontend/src/components/dashboard/ConversationTable.tsx` with provider icon, title, model, subagent count, context-pressure badge, token count, relative last-activity, bidirectional sort, and free-text search
  - Implement `frontend/src/components/dashboard/Inspector.tsx` with context-window occupancy track, per-field token breakdown, recent usage updates, compaction count, quota snapshots, and combined-view fallback
  - Implement `frontend/src/App.tsx` composing all dashboard components, wrapping with `QueryClientProvider`, and applying theme before first paint
  - Write Vitest + Testing Library tests for `MetricsBar` (renders correct token counts) and `ConversationTable` (renders rows, sort, search)

- [x] 12. Port insights panels
  - Implement `frontend/src/components/insights/LimitsPanel.tsx`: 5-hour and weekly quota bars, reset times, pace forecast, reset-alert notifications
  - Implement `frontend/src/components/insights/BudgetPanel.tsx`: per-provider zone bar proportional to suggested daily share, today's tokens, configurable budget, red outline at ≥ 100%
  - Implement `frontend/src/components/insights/BreakdownPanel.tsx`: token distribution by model and project with cache-read share per group
  - Implement `frontend/src/components/insights/TrendsPanel.tsx`: today vs. 7-day average, last-7 vs. prior-7, busiest day in last 30, 28-day weekday-by-hour heatmap
  - Implement `frontend/src/components/shared/PressureBanner.tsx`: list conversations at ≥ 80% context, badge on table rows, opt-in browser notifications at 80% and 95%
  - Write Vitest tests for `LimitsPanel` (quota bar percentages) and `BudgetPanel` (zone widths)

- [x] 13. Port dialogs
  - Implement `frontend/src/components/dialogs/SettingsDialog.tsx`: theme selector, alert opt-in, daily budget, warn/hard threshold inputs; persist to localStorage `to.*` keys
  - Implement `frontend/src/components/dialogs/ProvidersDialog.tsx`: enable/disable toggles calling `POST /api/providers`, local-proxy port pairs with server-up indicator
  - Implement `frontend/src/components/dialogs/LimitControlsDialog.tsx`: warn percent, hard percent, weekly reserve, pause/block mode; save calls `POST /api/limit-control`
  - Implement `frontend/src/components/dialogs/SourcesDialog.tsx`: log-file directories and file counts per provider from `snapshot.sources`
  - Implement `frontend/src/components/dialogs/UpdateDialog.tsx`: current and latest version, release notes, install button with progress polling, dismiss action
  - Write Vitest tests for `SettingsDialog` (renders saved theme preference) and `UpdateDialog` (shows install button when update available)

- [x] 14. Production build, full test run, and cutover
  - Run `npm run build` inside `frontend/` and assert exit code 0 producing `frontend/dist/`
  - Update `backend/app.py` static-file catch-all to serve `frontend/dist/` when `FLASK_ENV != development`
  - Run `pytest` from repository root and assert zero failures
  - Run `vitest --run` inside `frontend/` and assert zero failures
  - Update `backend/config.py` `PORT` default back to 8765
  - Copy `backend/launcher.py` to `launcher.py` at the repository root for backwards compatibility with existing install scripts and `.command` files
  - Delete legacy flat files from the repository root: `server.py`, `app.js`, `insights.js`, `updates.js`, `setup.js`, `theme.js`, `style.css`, `index.html`, `archive.py`, `claude_context.py`, `claude_limits.py`, `claude_statusline.py`, `codex_usage.py`, `lmstudio_chats.py`, `local_proxy.py`, `live_limits.py`, `limit_control.py`, `minimax.py`, `pricing.py`, `providers.py`, `session_hooks.py`, `updater.py`, `update_install.py`
  - Verify `python launcher.py --version` prints the correct version and `GET http://127.0.0.1:8765/api/health` returns `{"app":"token-observatory","version":2}`

## Task Dependency Graph

```
1 (scaffolding)
└── 2 (models)
    ├── 3 (Claude/Codex parsers)
    │   └── 7 (Store + /api/usage)
    │       └── 8 (remaining API endpoints)
    │           └── 9 (hooks + launcher)
    │               └── 14 (cutover)
    ├── 4 (local proxy + LM Studio parsers)
    │   └── 7
    └── 5 (pricing, archive, providers)
        └── 6 (limits services)
            └── 7
                └── 10 (frontend scaffolding)
                    └── 11 (dashboard UI)
                        └── 12 (insights panels)
                            └── 13 (dialogs)
                                └── 14
```

```json
{
  "waves": [
    {"wave": 1, "tasks": ["1"]},
    {"wave": 2, "tasks": ["2"]},
    {"wave": 3, "tasks": ["3", "4", "5"]},
    {"wave": 4, "tasks": ["6"]},
    {"wave": 5, "tasks": ["7"]},
    {"wave": 6, "tasks": ["8", "9", "10"]},
    {"wave": 7, "tasks": ["11"]},
    {"wave": 8, "tasks": ["12"]},
    {"wave": 9, "tasks": ["13"]},
    {"wave": 10, "tasks": ["14"]}
  ]
}
```

## Notes

- During development the Flask server runs on port 8766 alongside the existing server on 8765. The Vite dev proxy forwards `/api/*` to `http://127.0.0.1:8766`.
- Tasks 3–9 are direct ports of existing Python logic; the goal is behavioural parity, not redesign.
- Tasks 10–13 are direct ports of existing JavaScript logic into React/TypeScript components.
- Task 14 is a hard gate: it must not run until all preceding task tests pass.
- `prices.json` (bundled fallback) is carried over from the existing codebase unchanged.
