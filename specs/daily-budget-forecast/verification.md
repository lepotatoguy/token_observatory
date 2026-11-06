# Verification record

## Feature: Demand-weighted daily budget forecast

Recorded on 2026-11-06 on the branch rebased onto `origin/main` at `749a1b1`. Only macOS was run. Windows and Linux were not run, so cross-platform verification is incomplete (root `AGENTS.md`). The owner chose to push to `main` with that gap open.

## Platform matrix

| Platform | Backend suite | Frontend suite | Type check | Status |
|---|---|---|---|---|
| macOS (Darwin arm64, Python 3.11.7, native) | 383 passed, 2 failed, 2 skipped | 53 passed (10 files) | `tsc --noEmit` clean | Run, with 2 failures listed below |
| Windows | not run | not run | not run | Unverified gap |
| Linux | not run | not run | not run | Unverified gap |

Commands: `python -m pytest -q` in the repo root; `npx vitest run` and `npx tsc --noEmit -p .` in `frontend/`.

## New tests (87 backend tests passing together on macOS, plus 4 frontend tests)
- `tests/test_services/test_claude_limits.py` (3 added), `test_forecast_history.py`, `test_forecast_demand.py`, `test_forecast_calibrate.py`, `test_forecast_budget.py`, `test_forecast.py`, `test_forecast_timing.py`, `tests/test_api/test_forecast_api.py`.
- `frontend/src/components/insights/insights.test.tsx`: 4 forecast panel tests added.
- The two daylight-saving cases in `test_forecast_budget.py` use `time.tzset()`, which Windows lacks, so they skip there; daylight-saving behavior on Windows is unverified.

## Failures in the full backend suite
- `tests/test_integration/test_runtime.py::test_real_servers_keep_usage_and_stop_by_port`: HTTP 404 from a real server. It fails the same way on a clean checkout of `origin/main` in the same worktree, so it is not caused by this change; the cause was not investigated (the worktree has no built `frontend/dist`, which may be the reason; unverified).
- `tests/test_services/test_source_release_compatibility.py::test_legacy_linux_restart_keeps_arguments`: "No bundled Python runtime for Linux architecture aarch64". Environment-dependent and unrelated to this change.

## Measured performance (NFR-2), one run on this machine
- Cold fit over 30 synthetic daily files of 5.68 MB JSON each (1.2 million events): 1.9 seconds, limit 3 seconds.
- Warm request: 0.01 milliseconds, limit 50 milliseconds.
- The same fit on this machine's 22 real archive files plus live data: 0.32 seconds.

## Smoke run on this machine's real data (aggregates only, one run, final code)
- Claude: budgeted, 30 days, 6 calibration pairs, `flat` demand. Backtest mean absolute error equal for model and baseline: 42.5 million tokens a day over 16 test days.
- Codex: budgeted, 30 days, 70 pairs, `flat` demand. Backtest error equal for model and baseline: 50.5 million tokens a day over 16 test days.
- MiniMax: 3 days and 1 pair, so it is left to the previous browser system (`insufficient_data`).
- Weekday weighting was not selected for any provider, so on this data the budget is the calibrated even split. This is a result for these 30 days only.

## Acceptance criteria coverage
- REQ-1 to REQ-5 and NFR-2 to NFR-4: covered by the backend tests above.
- REQ-6 (including AC-6.8 algorithm and error display): endpoint and privacy covered by `test_forecast_api.py`; panel behavior covered by the frontend tests.
- NFR-1 AC-1.4 (native runs on all three systems): not satisfied, see the matrix.
