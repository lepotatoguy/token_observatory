# Verification record

## Feature: Token-type calibration and budget backtest

Recorded on 2026-11-06 on macOS only. Windows and Linux were not run, so cross-platform verification is incomplete (root `AGENTS.md`).

## Platform matrix

| Platform | Backend suite | Frontend suite | Type check | Status |
|---|---|---|---|---|
| macOS (Darwin arm64, Python 3.11.7, native) | 561 passed, 1 failed, 1 skipped | 81 passed (13 files) | `tsc --noEmit` clean | Run, with 1 unrelated failure |
| Windows | not run | not run | not run | Unverified gap |
| Linux | not run | not run | not run | Unverified gap |

Commands: `.venv/bin/python -m pytest -q` in the repo root; `npx vitest run` and `npx tsc --noEmit -p .` in `frontend/`.

## Failure in the full backend suite
- `tests/test_services/test_source_release_compatibility.py::test_legacy_linux_restart_keeps_arguments`: "No bundled Python runtime for Linux architecture aarch64". Environment-dependent, unrelated to this feature, and the same failure was seen before this feature.

## New tests
- `test_forecast_weights.py` (18) and `test_forecast_score.py` (12) are new; `test_forecast_history.py`, `test_forecast.py`, `test_forecast_budget.py`, and `test_forecast_api.py` gained cases; `insights.test.tsx` gained 3 panel tests.
- The scoring module takes 0.09 seconds to choose the method and replay 100 synthetic pairs (limit 0.5 seconds).
- The existing cold-fit timing test over 30 synthetic files of 5.68 MB each still passes: 2.33 seconds on this machine in one run (it was 1.9 seconds before typed rows were added; limit 3 seconds). A warm request took 0.014 milliseconds.

## Run on this machine's real data (aggregates only, one run)
- Codex: by-type calibration chosen. 70 readings; leave-one-out error 1.62 points against 2.22 for the single ratio. Fitted weights (percent of weekly limit per million tokens) input 3.35, cached 0.089, write 0.0, output 48.08. Rolling held-out error 1.75 points against 2.33 for the single ratio over 65 readings. Budget check: 4 of 19 scoreable past days within budget. The suggested daily budget moved from 653,969 to 772,730 tokens, which is about 18% higher, because the recent mix is slightly more cache-heavy than before (this is a single result for this data).
- Claude: single ratio kept (6 readings, leave-one-out error 2.87). The rolling backtest has 1 predicted reading, so its error (1.55 points, the same as the single ratio) says little. Budget check: 1 of 5 scoreable past days within budget.
- MiniMax: 1 reading, left to the previous system (`insufficient_data`).
- These match the earlier offline check in direction (by-type helps Codex, not Claude), and the Claude backtest is too short to judge.

## Acceptance criteria coverage
- REQ-1 to REQ-6 and NFR-2 to NFR-4: covered by the backend tests above.
- REQ-7: fields covered by `test_forecast.py`, `test_forecast_budget.py`, and `test_forecast_api.py`; panel sentences covered by the frontend tests.
- NFR-1 AC-1.3 (native runs on all three systems): not satisfied, see the matrix.
