# Tasks

## Feature: Always-available floating widget, manual update check, and scheduled window warm-up

Spec: requirements.md, design.md

### T1: Ship the widget runtime in every build [REQ-2]
- [x] 1.1 Add a packaging test in `tests/test_integration/` that fails while `PySide6-Essentials` is absent from core `dependencies` in `pyproject.toml` and while `release.yml` still uninstalls Qt.
- [x] 1.2 Move `PySide6-Essentials>=6.5,<7` from the `float` extra to core dependencies in `pyproject.toml`; keep an empty `float` extra for backward compatibility.
- [x] 1.3 Remove the "drop Qt" step in `.github/workflows/release.yml` and make `packaging/token_observatory.spec` always bundle Qt.
- [x] 1.4 Make `build_app.py` always install the runtime (drop the `--with-float` gate, keep the flag accepted) and update `install.sh`, `build_deb.py` (declare the Qt system libraries) and the docs (`README.md`, `INSTALL.md`, `DEVELOPMENT.md`).

### T2: Widget service and routes [REQ-1, REQ-3, NFR-1, NFR-3]
- [x] 2.1 Write failing unit tests for `Widget` (default off, atomic persist, `set_enabled` type check, `ensure` spawns once, 30-second spawn grace, three early exits set `error`, `touch` marks running) using a fake spawner and clock.
- [x] 2.2 Implement `backend/services/widget_control.py` with detached spawn arguments per operating system and `widget.log` redirection.
- [x] 2.3 Add `GET /api/widget`, `POST /api/widget` and the `client=widget` touch on `GET /api/quota` in `backend/api/routes.py`; add API tests for 400, 413 and 415.
- [x] 2.4 Register `Widget` in `create_app` and add the `ensure` job (10 seconds) to `Runtime.start` in `backend/app.py`.

### T3: Widget process follows the setting [REQ-1, NFR-2]
- [x] 3.1 In `backend/services/float_window.py`, poll `GET /api/widget` with each quota poll and quit when `enabled` is false or after 3 unreachable polls; add a toolkit-free helper so the decision is testable in `tests/test_services/test_float_window.py`.
- [x] 3.2 Make the Quit menu action post `{"enabled": false}` before exit.
- [x] 3.3 Add a `QLockFile` single-instance guard in `run()` and a test that a second instance exits without a window.
- [x] 3.4 Keep the macOS Dock-hiding environment setup and confirm `--float` from the command line still runs in the foreground (AC-5.2).

### T4: Widget toggle in Settings [REQ-3, NFR-4]
- [x] 4.1 Add `widget` and `setWidget` to `frontend/src/api/client.ts` and `frontend/src/hooks/useWidget.ts`.
- [x] 4.2 Write failing vitest cases in `dialogs.test.tsx`: toggle shows server state, reverts on error, disabled with reason when unavailable, shows "Starting".
- [x] 4.3 Add the "Floating widget" section to `SettingsDialog.tsx` with a labeled toggle and a polite live region.

### T5: Manual update check [REQ-4, NFR-1, NFR-4, NFR-5]
- [x] 5.1 Write failing tests in `tests/test_services/test_updater.py` for `check(force=True)` bypassing the interval, 5-second coalescing, the disabled status and a feed failure that keeps the old status.
- [x] 5.2 Implement `force` in `Updates.check` in `backend/services/updater.py`.
- [x] 5.3 Add `POST /api/update/check` with API tests (200, 413, 415); confirm `GET /api/update` and the install route are unchanged.
- [x] 5.4 Add `checkNow` to `frontend/src/hooks/useUpdates.ts`, write vitest cases (up to date, newer version with open-dialog action, failed, disabled), and add the "Check for updates" section to `SettingsDialog.tsx`.

### T6: Warm-up scheduler and configuration [REQ-5, REQ-6, REQ-8, NFR-3]
- [x] 6.1 Write failing unit tests for `Warmup` with a fake clock and sender: time validation (format, duplicates, more than 8, enabled with zero times), due, catch-up under 30 minutes, missed at 30 minutes, one outcome per slot, active window skip, unknown window send, midnight rollover, daylight-saving gap and overlap, 200-row cap, corrupt state file recovery.
- [x] 6.2 Implement `backend/services/warmup.py` (config, state, `tick`, `snapshot`, active window test using `quota.pick`).
- [x] 6.3 Confirm the active-window assumption against live `claude -p /usage` and Codex rate-limit output on this machine, then set or adjust the rule in `warmup.py` and record the result in Deviations.
- [x] 6.4 Add `GET /api/warmup` and `POST /api/warmup` with API tests (400, 413, 415) and register the 30-second tick job and `Runtime.stop` cleanup in `backend/app.py`.

### T7: Claude and Codex senders [REQ-7, NFR-1, NFR-3]
- [x] 7.1 Write failing tests for `warmup_send` command construction, model override validation, one-at-a-time lock, 60-second timeout kill, missing tool, signed-out failure, and reply discarded.
- [x] 7.2 Implement `backend/services/warmup_send.py` for Claude (`haiku`, effort `low`, no persistence, no tools) and Codex (read-only, git check skipped, low reasoning, optional `-m`) using `find_tool` and `tool_env`.
- [~] 7.3 Run one real send for each of Claude and Codex on this machine, confirm that `--tools ""` runs and that the Codex session created by the send is ignored by `backend/parsers/codex.py` (add a fixture test; record any unavoidable difference in Deviations).

### T8: MiniMax sender [REQ-7, NFR-1]
- [x] 8.1 Verify the MiniMax request path and lowest-cost model id against MiniMax documentation and record the source under Deviations; if not verifiable, ship the sender returning `failed: unavailable` and mark the provider unavailable in `GET /api/warmup`.
- [-] 8.2 Write failing tests with a fake HTTPS opener for key use through `minimax.credentials()`, HTTP error to `failed`, key never in logs or responses.
- [-] 8.3 Implement the MiniMax branch in `warmup_send.py`.

### T9: Warm-up section in Settings [REQ-5, REQ-8, NFR-4]
- [x] 9.1 Add `warmup` and `setWarmup` to `frontend/src/api/client.ts` and `frontend/src/hooks/useWarmup.ts`.
- [x] 9.2 Write failing vitest cases: provider toggle, add and remove a time, server error display, next slot and last outcome rendering, paid-plan and quota notice text, labels and live region.
- [x] 9.3 Implement `frontend/src/components/dialogs/WarmupSection.tsx` and mount it in `SettingsDialog.tsx`.

### T10: Docs, version and cross-platform verification [NFR-1, NFR-2, NFR-5]
- [x] 10.1 Update `CONTRIBUTING.md` with the opt-in warm-up exception, `CHANGELOG.md`, `DEVELOPMENT.md`, and bump `backend/version.py` and `pyproject.toml`.
- [x] 10.2 Run `.venv/bin/python -m pytest` and `cd frontend && npm test -- --run && npm run build`; fix regressions.
- [x] 10.3 Run the native macOS check (widget on and off, visibility, background process, no Dock entry, update check, one warm-up send per available provider) and write `verification.md` with results and evidence paths.
- [ ] 10.4 Run the same checks on native Windows and Linux runners or machines; record each result in `verification.md`. If an environment is unavailable, record the gap and leave cross-platform verification marked incomplete; do not push to main.

### T11: Wait for an exhausted limit [REQ-9]
- [x] 11.1 Add failing tests in `tests/test_services/test_warmup.py` for deferral, send at reset plus 60 seconds, re-deferral, active skip, 30-minute missed, restart persistence, and dropping on change.
- [x] 11.2 Implement deferral in `backend/services/warmup.py` (`exhausted`, `run_deferred`, `deferred` state) and fresh limits in `backend/app.py`.
- [x] 11.3 Show the waiting message in `WarmupSection.tsx` with a vitest case.

## Deviations
- 2026-11-06 T7.3: the real Claude send ran on macOS (exit 0, 5.2 s, `--tools ""` accepted, no session file written). The real Codex send was not run: this account's weekly Codex limit showed 99% used, so a send could lock it out. Codex flags were checked against `codex exec --help` only.
- 2026-11-06 T7.3: the design said Codex parsers should ignore the warm-up session. Not done on purpose: hiding real token use from an observability tool is misleading, so a Codex warm-up counts as a normal tiny session. A Claude run creates an empty project folder under `~/.claude/projects` for the data folder; no session file.
- 2026-11-06 T8: MiniMax request path and cheapest model could not be verified (see `.claude/retrieved/minimax-anthropic-api.md`). Per T8.1 the sender reports `unavailable` and the UI disables the toggle. T8.2 and T8.3 are not done.
- 2026-11-06 T6.3: live-limits.json on this machine shows Codex and MiniMax windows with a future `resets_at` and `used_percent` 0 when idle, and Claude at 64% with a future reset when in use. The rule (future reset and used above 0) fits all three. An idle Claude window was not observed.
- 2026-11-06 T6.2: a time inside a spring daylight-saving gap is recorded as `missed` (naive wall-clock arithmetic puts the first tick 30 minutes late), not attempted. Times just after the gap are sent.
- 2026-11-06 T5: a manual check ignores the notify preference as well as the interval (REQ-4 asks for an immediate check); the environment switch still disables it.
- 2026-11-06 T2: `GET /api/widget` and the 5-second widget poll use a managed flag (`TOKEN_OBSERVATORY_WIDGET_MANAGED=1`) so a hand-started `--float` is not closed by the off setting (AC-5.2). The server also clears the last-seen time when it sees its own widget process exit, so a quick off then on restarts the widget at once.
- 2026-11-06 T10.2: `tests/test_services/test_source_release_compatibility.py::test_legacy_linux_restart_keeps_arguments` fails (no bundled Linux Python for aarch64 on this Mac). It fails the same way on the commit before these changes.
