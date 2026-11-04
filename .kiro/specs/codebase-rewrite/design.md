# Design Document

## Overview

The Token Observatory codebase rewrite splits the current flat ~30-file Python + vanilla JS layout into a modern monorepo with two top-level packages: a Flask + Pydantic v2 backend in `backend/` and a React 18 + TypeScript + Vite frontend in `frontend/`. During migration the new stack runs on port 8766 alongside the existing server on 8765; after all tests pass the old flat files are deleted and port reverts to 8765.

All user-facing features are preserved. No data formats visible to the browser are changed, so the same `/api/usage` JSON schema is consumed by both the old vanilla-JS dashboard (during migration) and the new React frontend.

---

## Architecture

### High-level component map

```
token_observatory/
├── backend/                    # Flask API server + all Python logic
│   ├── app.py                  # create_app() application factory
│   ├── config.py               # Paths, port defaults, env-var constants
│   ├── middleware/security.py  # Loopback + cross-site request filter
│   ├── parsers/                # Stateful incremental log readers
│   │   ├── _helpers.py         # tokens(), total(), timestamp() shared helpers
│   │   ├── claude.py           # ClaudeLog — reads .jsonl under ~/.claude/projects
│   │   ├── codex.py            # CodexLog + merge_threads — reads ~/.codex/sessions
│   │   ├── local_proxy.py      # Reads local-usage.jsonl
│   │   └── lmstudio.py         # Reads LM Studio .conversation.json files
│   ├── services/               # Stateful singletons, one per concern
│   │   ├── store.py            # Store — owns parsers, drives scan/snapshot cycle
│   │   ├── pricing.py          # Fetches + caches Anthropic price table
│   │   ├── archive.py          # Daily JSON snapshot writer/reader
│   │   ├── providers.py        # Provider detection + settings
│   │   ├── live_limits.py      # Runs claude/codex live-limit checks
│   │   ├── claude_limits.py    # Merges all Claude rate-limit sources
│   │   ├── claude_context.py   # Applies context-window capacities to sessions
│   │   ├── claude_statusline.py# Parses + writes statusline capture
│   │   ├── limit_control.py    # Reads/writes limit-settings + limit-events
│   │   ├── session_hooks.py    # Hook logic for 5-hour limit + context reminders
│   │   ├── minimax.py          # MiniMax quota + session-splitting
│   │   └── updater.py          # GitHub release check + in-place update
│   ├── api/                    # Flask Blueprint route handlers
│   │   ├── health.py           # GET /api/health
│   │   ├── usage.py            # GET /api/usage, POST /api/refresh
│   │   ├── providers.py        # GET/POST /api/providers
│   │   ├── pricing.py          # GET /api/pricing
│   │   ├── history.py          # GET /api/history/<day>
│   │   ├── limit_control.py    # GET/POST /api/limit-control
│   │   └── updates.py          # GET /api/update, POST /api/update/settings|install
│   ├── models/                 # Pydantic v2 data models
│   │   ├── session.py          # TokenEvent, SessionTotals, Session
│   │   ├── limits.py           # LimitWindow, RateLimits, LiveLimits
│   │   ├── providers.py        # ProviderSettings, ProviderStatus
│   │   └── snapshot.py         # UsageSnapshot, ArchiveManifest, PriceEntry
│   └── launcher.py             # CLI entry point (mirrors current launcher.py flags)
├── frontend/                   # React 18 + TypeScript + Vite
│   ├── package.json
│   ├── vite.config.ts          # Dev proxy /api/* → http://127.0.0.1:8766
│   ├── tsconfig.json
│   └── src/
│       ├── App.tsx             # Root — QueryClientProvider, router, layout
│       ├── store/useAppStore.ts# Zustand store for UI state
│       ├── api/client.ts       # Typed fetch wrappers for all endpoints
│       ├── hooks/              # TanStack Query wrappers
│       │   ├── useUsagePolling.ts   # polls /api/usage every 2 s
│       │   ├── usePricing.ts        # polls /api/pricing every 1 h
│       │   └── useLimits.ts         # mutation for POST /api/refresh
│       ├── types/              # TypeScript mirrors of Pydantic models
│       │   ├── session.ts
│       │   ├── limits.ts
│       │   ├── providers.ts
│       │   └── snapshot.ts
│       ├── utils/              # Pure helpers (no React deps)
│       │   ├── tokens.ts       # compact(), exact(), eventTotal()
│       │   ├── time.ts         # relative(), date(), dayKey(), shiftDay()
│       │   ├── cost.ts         # costOf(), money()
│       │   ├── conversations.ts# groupConversations(), scoped(), sum()
│       │   ├── storage.ts      # localStorage helpers (budget, alerts, theme)
│       │   ├── theme.ts        # applies Auto/Light/Dark choice before paint
│       │   └── export.ts       # buildCsvRows(), buildJsonPayload()
│       └── components/
│           ├── layout/         # Sidebar, Header
│           ├── dashboard/      # MetricsBar, ActivityChart, ConversationTable, Inspector
│           ├── insights/       # LimitsPanel, BudgetPanel, BreakdownPanel, TrendsPanel
│           ├── dialogs/        # SettingsDialog, ProvidersDialog, LimitControlsDialog, SourcesDialog, UpdateDialog
│           └── shared/         # Toast, ProviderBadge
├── tests/
│   ├── conftest.py             # Flask test client + log-fixture factories
│   ├── test_models/            # Pydantic model round-trip tests
│   ├── test_parsers/           # Claude, Codex, local-proxy, LM Studio parser tests
│   ├── test_services/          # Store, pricing, archive, providers, limits tests
│   └── test_api/               # Route-level integration tests via Flask test client
└── pyproject.toml              # package: token-observatory; deps: Flask, pydantic>=2, requests
```

---

## Components and Interfaces

See the detailed component descriptions below.

## Data Models

All persistent and exchanged data is defined as Pydantic v2 models in `backend/models/`. The key structures are `TokenEvent`, `SessionTotals`, `Session`, `UsageSnapshot`, `LimitWindow`, `RateLimits`, `ProviderSettings`, `PriceEntry`, and `ArchiveManifest`. Full field definitions are given in the Component Design section below.

## Component Design

### Backend application factory (`backend/app.py`)

`create_app(config=None)` returns a configured Flask app. It:
1. Reads `Config` from `backend/config.py` (port, data-dir, env flags).
2. Attaches the `SecurityMiddleware` WSGI wrapper.
3. Registers all API Blueprints with the `/api` prefix.
4. Creates a `Store` singleton and attaches it to `app.extensions['store']`.
5. Starts the collector thread (2 s scan loop) and live-limits thread (300 s loop) using `threading.Thread(daemon=True)`.
6. Registers a static-file catch-all route that serves the Vite `dist/` folder when `FLASK_ENV != development`.

### Security middleware (`backend/middleware/security.py`)

A thin WSGI middleware (wraps the Flask `app.wsgi_app`) that runs before any route. For every request it:
- Checks `Host` against `127.0.0.1:<port>` and `localhost:<port>`.
- For mutating methods (POST/PUT/PATCH/DELETE) checks `Sec-Fetch-Site != cross-site` and `Origin` netloc.
- Injects the response headers (`Cache-Control`, `X-Content-Type-Options`, `Content-Security-Policy`) into the response on the way out.
- Returns a plain 403 immediately for blocked requests without invoking Flask routing.

### Parsers

Each parser class (`ClaudeLog`, `CodexLog`) has the same interface as the current `Log`:
- `__init__(path, provider)` — initialises all state fields.
- `refresh()` — `stat()` the file; if inode/size changed, reset state; seek to `self.offset`; read new complete lines; call `consume(data)` for each valid JSON object.
- `consume(data)` — identical field-extraction logic to the current `Log.consume`, but writes into Pydantic models rather than plain dicts where practical.
- `export(titles)` — returns a `Session` model instance.

The `merge_threads` function in `codex.py` is a direct port of the current `codex_usage.merge_threads`.

`LocalProxyParser` and `LmStudioParser` are stateless readers (they re-parse the file on each call) but cache by `(path, mtime, inode)` to avoid redundant work.

### Store (`backend/services/store.py`)

```python
class Store:
    def __init__(self, codex, claude, data_dir, ...):
        ...  # same constructor signature as current Store

    def read(self, force_save=False) -> dict:
        # Acquire self.lock; return cached snapshot if < 1.5 s old;
        # otherwise run full scan: discover logs, refresh parsers, export sessions,
        # apply context windows, merge threads, split minimax, add limits, archive.
        ...

    def refresh_live(self) -> dict:
        # Acquire self.live_lock; if last check > LIVE_REUSE_SECONDS ago,
        # run live_limits.check() in parallel for enabled tools;
        # reset self.scanned; call self.read().
        ...
```

The `Store` attaches to `app.extensions['store']` so Blueprint handlers can retrieve it via `current_app.extensions['store']`.

### API Blueprints

Each file in `backend/api/` defines a Flask `Blueprint`. Route functions:
1. Retrieve `store = current_app.extensions['store']`.
2. For POST routes: call `request.get_json(force=False)`, validate with Pydantic, return 400/415 on failure.
3. Enforce the 1 024-byte body limit by checking `request.content_length` before calling `get_json`.
4. Serialise return values with `jsonify(model.model_dump())` or plain `json.dumps` for performance-critical paths.

### Pydantic models

```python
# backend/models/session.py
class TokenEvent(BaseModel):
    at: float | None
    model: str
    input: int = Field(ge=0)
    cached: int = Field(ge=0)
    write: int = Field(ge=0)
    output: int = Field(ge=0)
    reasoning: int = Field(ge=0)
    write_1h: int = Field(ge=0, default=0)
    cache_unreported: bool = False

class SessionTotals(BaseModel):
    input: int = Field(ge=0)
    cached: int = Field(ge=0)
    write: int = Field(ge=0)
    output: int = Field(ge=0)
    reasoning: int = Field(ge=0)
    total: int = Field(ge=0)

class Session(BaseModel):
    id: str
    session_id: str
    provider: str
    title: str
    project: str
    model: str
    models: list[str]
    last: float | None
    modified: float
    subagent: bool
    parent: str | None
    totals: SessionTotals
    events: list[TokenEvent]
    context: int | None
    capacity: int | None
    capacity_source: str | None
    compactions: int
    rate_limits: dict | None
    rate_limits_at: float | None
    reported_cost: float | None
    source: str
    parse_errors: int
    usage_source: str
    conversation_id: str
    latest_usage: dict | None
    latest_usage_at: float | None
```

Models use `model_config = ConfigDict(extra='allow')` so that fields added in future versions of the log format do not break parsing.

### Frontend architecture

**State split**: API server state lives in TanStack Query caches; UI-only state (selected row, filter, sort, pause) lives in Zustand.

```typescript
// src/store/useAppStore.ts
interface AppState {
  provider: string;         // 'all' | provider key
  selected: string | null;  // conversation id
  paused: boolean;
  sort: 'tokens' | 'recent';
  sortDirection: 'asc' | 'desc';
  day: string | null;       // YYYY-MM-DD drill-down
  historyDay: string;       // '' = live, date = archived snapshot
  search: string;
  agentsIncluded: boolean;
  // actions
  setProvider: (p: string) => void;
  setSelected: (id: string | null) => void;
  togglePause: () => void;
  ...
}
```

**Polling**: `useUsagePolling` wraps `useQuery` with `refetchInterval: 2000`, disabled when `paused || historyDay !== ''`. `usePricing` polls every 3 600 000 ms. `useLimits` exposes a `refresh()` mutation that calls `POST /api/refresh`.

**Conversation grouping and scoping**: `groupConversations()` and `scoped()` are pure TypeScript functions in `src/utils/conversations.ts`, ported from the current `app.js`. They run inside `useMemo` hooks in the consuming components.

**Activity chart**: rendered as an inline `<svg>` (not a charting library), matching the current SVG output. Day-bar click handlers update `day` in the Zustand store.

**Export**: `buildCsvRows()` and `buildJsonPayload()` in `src/utils/export.ts` produce the same CSV and JSON structures as the current `$('exportButton')` and `$('jsonButton')` handlers.

### Launcher CLI (`backend/launcher.py`)

Mirrors all flags of the current `launcher.py`. Differences:
- Calls `waitress-serve` (or Python's built-in `ThreadingHTTPServer` in development) rather than directly running `server.py`.
- Uses `sys.executable backend/launcher.py --serve --port <N>` as the restart command.
- All hook, statusline, and update-related flag handling delegates to the same service modules.

### Production build and cutover

After all tests pass:
1. `vite build` produces `frontend/dist/`.
2. Flask's static-file catch-all serves `frontend/dist/index.html` for any unmatched GET route and `frontend/dist/assets/*` for assets.
3. `backend/launcher.py` is moved to `launcher.py` at the repository root (for backwards compatibility with existing install scripts).
4. Old flat files are deleted from the repository root.
5. Port reverts to 8765 in `backend/config.py`.

---

## Data Flow

```
Browser (React)
  │
  │  GET /api/usage  (every 2 s via TanStack Query)
  ▼
Flask Handler (backend/api/usage.py)
  │  store.read()
  ▼
Store (backend/services/store.py)
  │  acquire scan lock
  │  if snapshot fresh → return cached
  │  else:
  │    for each .jsonl path → ClaudeLog.refresh() / CodexLog.refresh()
  │    merge_threads()
  │    minimax.split_session()
  │    apply context windows
  │    compute limits (claude_limits, live cache)
  │    archive.update(snapshot, signature)
  │    limit_control.observe(rows)
  │    return snapshot dict
  ▼
JSON response → TanStack Query cache → Zustand selectors → React components
```

---

## Security Design

The `SecurityMiddleware` is the single enforcement point. It runs at the WSGI layer before Flask routing so that even 404 and 405 responses go through it. This matches the current `Handler.allowed()` behaviour.

POST body size is enforced at the Blueprint level (check `request.content_length` before `get_json`) rather than globally, so GET routes are unaffected.

The local-LLM pass-through proxies (`local_proxy.py`) continue to listen only on `127.0.0.1` and forward the client's `Origin` header unchanged.

---

## Error Handling

- **Parser errors**: Malformed JSONL lines increment `parse_errors` on the session and are skipped; the scanner never raises on bad input.
- **Missing log directories**: The Store records a warning string (e.g. `"claude: log directory not found"`) in `snapshot.warnings` and continues scanning other providers.
- **Live-limit failures**: A failed `claude` or `codex` live check keeps the last good cached value; the error message is surfaced in `live_limits.errors` in the snapshot.
- **Archive write failures**: A failed snapshot write appends an error string to `snapshot.warnings`; the app continues running with in-memory state.
- **Pricing fetch failures**: The pricing service falls back to the previous cached `pricing.json` or the bundled `prices.json`; a failed fetch is logged to `service.log`.
- **API validation errors**: Flask Blueprint handlers return HTTP 400 with a plain-text description when Pydantic validation fails on a POST body, HTTP 413 when the body exceeds 1 024 bytes, and HTTP 415 when `Content-Type` is not `application/json`.
- **Update verification failures**: A SHA-256 mismatch during an in-app update aborts the install and returns an error via `GET /api/update`; no files are replaced.



During development the new Flask server runs on port **8766**. The existing `server.py` continues to run on **8765**. This allows side-by-side comparison and means no user workflow is disrupted until the cutover is deliberately executed as the final task.

The Vite dev server proxies `/api/*` to `http://127.0.0.1:8766`, so the React frontend can be developed and tested against the real data without any production build step.

---

## Testing Strategy

| Layer | Tool | What is tested |
|---|---|---|
| Models | pytest | Round-trip serialisation; field validation; `ge=0` constraints |
| Parsers | pytest | Synthetic `.jsonl` fixtures; incremental reads; dedup; merge_threads |
| Services | pytest | Store read/refresh; archive write/load; pricing fallback; provider detection |
| API routes | pytest (Flask test client) | Status codes; JSON schema; security header presence; 403 on bad Host |
| Frontend utils | Vitest | `groupConversations`, `scoped`, `compact`, `relative`, `buildCsvRows` |
| Frontend components | Vitest + Testing Library | MetricsBar, ActivityChart, ConversationTable render with mock data |

---

## Correctness Properties

### Property 1: Loopback enforcement
For any HTTP request with a `Host` header not equal to `127.0.0.1:<port>` or `localhost:<port>`, the response status MUST be 403.

**Validates: Requirements 1.2, 1.3**

### Property 2: Token non-negativity
For any parsed session, every token field in `SessionTotals` and every `TokenEvent` MUST satisfy `value >= 0`.

**Validates: Requirements 2.2, 3.1, 3.2**

### Property 3: Snapshot freshness
Calling `store.read()` twice in rapid succession (< 1.5 s apart) MUST return the same object reference (cache hit), avoiding redundant log rescans.

**Validates: Requirements 7.1**

### Property 4: Incremental reads
After a `ClaudeLog.refresh()` or `CodexLog.refresh()`, the byte offset MUST advance by exactly the number of bytes of complete lines consumed; a subsequent `refresh()` with no new data MUST read zero bytes.

**Validates: Requirements 3.5**

### Property 5: Archive idempotency
Calling `archive.update(snapshot, signature)` with an unchanged signature within the same calendar minute MUST NOT write a new file to disk.

**Validates: Requirements 5.2**

### Property 6: Body size enforcement
Any POST request with `Content-Length > 1024` MUST receive HTTP 413 before the body is parsed.

**Validates: Requirements 1.4**

### Property 7: CSV round-trip
The CSV exported by `buildCsvRows()` MUST contain exactly one data row per session in `scoped()`, and the `total` column for each row MUST equal the sum of `input + cached + write + output` for that session's events in the selected range.

**Validates: Requirements 11.5**
