# Tasks

## Feature: Demand-weighted daily budget forecast

Spec: requirements.md, design.md

### T1: Expose all Claude desktop usage samples [REQ-3, NFR-3]
- [x] 1.1 Write tests first in `tests/test_services/test_claude_limits.py`: `PlanUsage.samples()` returns `(t_seconds, five_hour, seven_day)` for every valid sample sorted by time, skips malformed samples, returns an empty list for a missing or unreadable file, and never includes the organization id.
- [x] 1.2 Add `samples()` to `PlanUsage` in `backend/services/claude_limits.py`, reusing the existing validity checks and mtime cache, and leaving `read()` unchanged.

### T2: Build the daily history from the archive [REQ-1, NFR-4, NFR-2]
- [x] 2.1 Write tests first in `tests/test_services/test_forecast_history.py` for AC-1.1 to AC-1.6: local-day assignment and the `total()` token definition, newest-wins dedup of a session that appears in several day files, `skipped_events` for events without `at`, exclusion of today, 30-day limit, zero-fill from the first event to yesterday, no days before the first event, and an unreadable file producing a warning while the rest still load.
- [x] 2.2 Create `backend/services/forecast_history.py` with frozen dataclasses `Sample` and `History` and `collect(snapshot, archive, plan_samples, today, providers, days=30)`: consume the live snapshot first, then archive files newest to oldest, skip session ids already seen, load each file at most once, and build the per-provider sorted event index and zero-filled daily series.
- [x] 2.3 Gather weekly percent samples in `collect`: `rate_limits` of deduplicated sessions, the `limits` of the live and each archived snapshot (weekly window through `quota.pick`), and the Claude desktop samples; drop duplicates by provider, time rounded to the second, and percent. Cover this with tests.

### T3: Fit demand weights with a backtest [REQ-2, NFR-4]
- [x] 3.1 Write tests first in `tests/test_services/test_forecast_demand.py` for AC-2.1 to AC-2.6: `flat` with all weights 1.0 under 18 days, `weekday_regression` chosen only when it beats the flat baseline on a synthetic series with a real weekday pattern, `flat` chosen on a noisy series without one, weights always positive, reported `model_mae` and `baseline_mae` computed from the backtest, `backtest` is `None` when not run, confidence levels at 6, 7, 17, and 18 days, and identical output on repeated runs.
- [x] 3.2 Create `backend/services/forecast_demand.py` with frozen dataclasses `Backtest` and `Demand` and `fit_demand(series, last_day)`: trailing 14-day level, weekday ratios, weight `(1 - lam) + lam * ratio` floored at 0.05 for `lam` in `{0, 0.25, 0.5, 0.75, 1}`, rolling-origin backtest from index 14, smallest `lam` on ties, and the confidence mapping.

### T4: Calibrate tokens per percent from history [REQ-3]
- [x] 4.1 Write tests first in `tests/test_services/test_forecast_calibrate.py` for AC-3.1 to AC-3.5 and AC-3.7: pairs only within one weekly window, a percent drop or a different `resets_at` starts a new segment, pairs need at least 2 points of change, zero-token pairs and ratios beyond four times the median are dropped, the pooled estimate is total tokens over total percent, and `None` is returned when no pair remains.
- [x] 4.2 Create `backend/services/forecast_calibrate.py` with frozen dataclass `Calibration` and `tokens_per_percent(samples, events)` using prefix sums and `bisect` over the sorted event index.

### T5: Compute the weekly budget [REQ-4, NFR-1]
- [x] 5.1 Write tests first in `tests/test_services/test_forecast_budget.py` for AC-4.1 to AC-4.7: remaining capacity and start-of-day capacity, today's share from weekday weights scaled by the fraction of each day inside the window, a flat model equals the calibrated even split, the budget stays the same at 9am and 9pm when nothing else changes, 100 percent used gives a budget no higher than tokens used today, a window that starts today, a 23-hour and a 25-hour daylight-saving day, `no_weekly_quota` and `no_calibration` exclusions, the current-week fallback with `calibration = current_week`, the `estimated` flag, and no change to `Control` state.
- [x] 5.2 Create `backend/services/forecast_budget.py` with the pure function `budget(state, snapshot, now)` that returns the per-provider entries and total described in the API section of design.md, using naive local datetimes for day boundaries and real day lengths.

### T6: Fit once per day and persist the model [REQ-5, NFR-3, NFR-2]
- [x] 6.1 Write tests first in `tests/test_services/test_forecast.py` for AC-5.1 to AC-5.6: first request of a day fits and writes `forecast.json`, a second request reads no archive file (patched `Archive.load` is never called), the budget changes when the live weekly percent changes without a refit, the write is atomic through a temporary file and `os.replace`, a corrupt or old-schema file is refitted, a missed-days start fits only today, `refresh` refits but is ignored within 60 seconds, and an unwritable folder still returns the budget with a warning.
- [x] 6.2 Create `backend/services/forecast.py` with `Forecaster(store, folder)`, a lock, the stored state read and write, the 60-second refit interval, and `payload(refresh=False, now=None)` that combines `collect`, `fit_demand`, `tokens_per_percent`, and `budget`.
- [x] 6.3 Add a timing test for NFR-2 that fits 30 synthetic daily snapshots of about 5 MB each in under 3 seconds and answers a warm request in under 50 milliseconds, and a test for NFR-3 that patches `socket` to fail and confirms the forecast makes no network call and that `forecast.json` holds only counts, ratios, dates, and warnings.

### T7: Add the API endpoint and wire the service [REQ-6, NFR-3]
- [x] 7.1 Write tests first in `tests/test_api/test_routes.py` (or a new `tests/test_api/test_forecast_api.py`) for AC-6.1, AC-6.2, AC-6.3 on the backend side, and AC-6.7: response shape, `refresh=1`, a store without an archive returns 200 with excluded or current-week providers, and the body has no session titles, project names, organization id, or paths.
- [x] 7.2 Add `GET /forecast` to `backend/api/routes.py` and register `app.extensions['forecast'] = Forecaster(store, folder)` in `backend/app.py`.

### T8: Use the forecast in the budget panel [REQ-6]
- [x] 8.1 Write tests first in `frontend/src/components/insights/insights.test.tsx` for AC-6.3 to AC-6.6: the panel shows forecast values in the total, the per-provider split, the "Use suggested" button, and the note; a provider without a forecast uses the browser value labeled as an even split; a failed request shows today's suggestion unchanged; the history view ignores the forecast; the note states confidence and days used. Keep the existing `suggestedBudget` test passing.
- [x] 8.2 Add `frontend/src/types/forecast.ts` and `api.forecast(refresh?)` in `frontend/src/api/client.ts`.
- [x] 8.3 Update `frontend/src/components/insights/BudgetPanel.tsx`: add a `useForecast` effect that fetches on mount and every 60 seconds and not while `historyDay` is set, merge forecast values with `suggestedBudget()` per provider, and update the note text. Leave the budget form, the alerts, and the styles unchanged.

### T9: Verify on all three operating systems [NFR-1, NFR-5]
- [x] 9.1 Run the full backend suite (`pytest`) and the frontend suite (Vitest) and confirm the new tests pass with no network access.
- [ ] 9.2 Run the backend and frontend suites natively on macOS, Windows, and Linux, including the daylight-saving and path tests, and record each result and where its evidence is kept in a verification note under `specs/daily-budget-forecast/`.
- [ ] 9.3 Report any operating system that was not run as an unverified gap, and do not describe the feature as fully verified or push it to `main` until all three pass, as the root `AGENTS.md` requires.

## Deviations
- Post-review change: thin data now falls back to the previous browser system (`insufficient_data`), the server-side current-week calibration was removed, and the panel states the algorithm and measured error (AC-3.3 to AC-3.5, AC-6.8).
- T7: `GET /api/forecast` does not wrap internal faults into a 200 response with warnings as design.md says; an unexpected fault returns a 500 and the panel falls back to the browser even split (AC-6.6). Swallowing unexpected exceptions would hide bugs.
- T6: the daily model is also held in memory after the first read, so warm requests do not touch the file; the file is still the source after a restart on the same day.
- T9: only macOS was run. Windows and Linux runs (9.2) and the resulting gap report (9.3) are open; see `verification.md`. The daylight-saving tests skip on Windows because `time.tzset()` is unavailable there.
- T9: three unrelated tests fail in the full backend suite (two need PySide6, one needs an aarch64 Linux runtime); see `verification.md`.
- Environment: `.venv` was created for the tests with the user's approval; it is excluded through `.git/info/exclude` because `.gitignore` does not list it.
