# Requirements

## Feature: Token-type calibration and budget backtest

### Background
The daily budget forecast (`specs/daily-budget-forecast`) sizes the budget with one number per provider, tokens per percent of the weekly window, found by pooling the tokens logged between pairs of past percent readings (`backend/services/forecast_calibrate.py`). That ratio treats every token as equal, but about 96% of this user's tokens are cache reads, and cache reads, new input and output tokens almost certainly count differently toward a limit. A check on this machine's real readings (leave-one-out, one run, offline) gave 2.22 percentage points of error for the single ratio and 1.62 for a per-token-type fit on Codex (70 pairs), while on Claude (6 usable pairs) the per-type fit was worse (4.42 against 2.87). The panel also reports a loss only for the usage forecast, and nothing that scores the budget itself.

This feature (1) learns how much each kind of token costs the weekly limit, per provider, and uses that when enough readings exist, falling back to the single ratio otherwise, and (2) scores the calibration and the budget on past data and shows the scores in the panel.

### Goals
- Calibrate with per-token-type weights (input, cached, write, output) per provider when the data supports it, and choose between that and the single ratio by error on the user's own readings.
- Convert the learned weights into a tokens-per-percent value for the budget using the user's recent token mix.
- Measure, with held-out data only, how well the calibration predicts past percent changes.
- Measure how often past days stayed within the daily budget as it stood at the start of each day.
- Show both scores and the method, in plain words, in the existing budget panel text.
- Keep the implementation standard-library only and identical on macOS, Windows, and Linux.

### Out of scope
- Per-model weights (too few readings per model); weights are per provider.
- Recording more percent readings over time (a separate follow-up that would help Claude).
- Changing the demand weights, the weekday model, or the 7-day and 2-pair data thresholds from the forecast spec.
- A counterfactual replay of "what if the budget had been followed" (not observable).
- New dependencies, new panels, or new endpoints; the existing `GET /api/forecast` and panel gain fields and a sentence.

### Glossary
- **Calibrator**: the backend component that fits the calibration and chooses between the two methods.
- **Reading pair**: two percent readings of the same weekly window at least 2 points apart, with the tokens logged between them (as in `forecast_calibrate.py`).
- **Single ratio**: the current method, one tokens-per-percent value from pooled raw token totals.
- **Type weights**: four non-negative values, percent of the weekly limit per million tokens, for input, cached, write, and output tokens.
- **By-type fit**: the least-squares fit of the percent rise of each reading pair on its token totals by type, constrained to non-negative weights.
- **Leave-one-out error**: for each reading pair, the absolute error in percentage points of predicting its rise from a fit on all the other pairs, averaged.
- **Rolling error**: for each reading pair in time order from the sixth, the absolute error in percentage points of predicting its rise from a fit on earlier pairs only, averaged.
- **Recent mix**: each token type's share of the provider's tokens over the last 7 local days before today.
- **Effective tokens per percent**: 1 divided by the sum of each type weight times its recent mix share; it is the value the budget uses.
- **Budget check**: for a past day, whether the tokens used that day were at most the budget the formula would have given at the start of that day.

### User stories
1. As a user whose usage is mostly cached tokens, I want the budget to reflect what each kind of token costs my limit, so that the suggested tokens a day matches how I really spend it.
2. As a user with few percent readings, I want the app to keep the simple method when the detailed one cannot be trusted, so that I am not shown a worse number.
3. As a skeptical user, I want to see how accurate the calibration was on past readings and how often I stayed within the budget, so that I can judge the suggestion.

### Requirements

#### REQ-1: Keep token totals by type
THE Forecaster SHALL keep, for each provider, the logged tokens by type with their event times, inside the History window.

Acceptance criteria:
- AC-1.1 THE Forecaster SHALL record for each counted event the four values input, cached, write, and output, and SHALL NOT record reasoning separately, because reasoning is already part of output.
- AC-1.2 THE Forecaster SHALL apply the same newest-copy-wins deduplication and the same exclusion of events without a time as the existing totals.
- AC-1.3 THE Forecaster SHALL make the sum of the four types of every event equal the token total the existing history uses for that event.

#### REQ-2: Fit type weights from reading pairs
WHEN a provider has enough usable reading pairs, THE Calibrator SHALL fit type weights by non-negative least squares.

Acceptance criteria:
- AC-2.1 THE Calibrator SHALL build reading pairs with the existing segment and pairing rules (same weekly window, rise of at least 2 points) and SHALL drop pairs with no logged tokens and pairs whose total-token ratio is more than four times above or below the median ratio.
- AC-2.2 THE Calibrator SHALL return type weights that are all greater than or equal to zero and that minimize the squared error of the predicted rises over the pairs.
- AC-2.3 WHEN the same pairs are given twice, THE Calibrator SHALL return identical weights.
- AC-2.4 IF a token type has no tokens in any pair, THEN THE Calibrator SHALL set that weight to zero.

#### REQ-3: Choose the method by held-out error
THE Calibrator SHALL use the by-type fit only when it is both supported by enough pairs and more accurate than the single ratio on the user's own readings.

Acceptance criteria:
- AC-3.1 THE Calibrator SHALL compute the leave-one-out error of the single ratio and of the by-type fit over the same pairs.
- AC-3.2 WHEN a provider has at least 20 pairs and the by-type leave-one-out error is at most 90% of the single-ratio error, THE Calibrator SHALL set `calibration_kind` to `by_type`.
- AC-3.3 IF a provider has fewer than 20 pairs, or the by-type error is more than 90% of the single-ratio error, THEN THE Calibrator SHALL set `calibration_kind` to `single`.
- AC-3.4 THE Calibrator SHALL report both leave-one-out errors whenever the by-type fit was tried, and SHALL report the by-type error as `null` when it was not tried.
- AC-3.5 IF a provider has fewer than 2 pairs, THEN THE Calibrator SHALL leave the provider to the existing `insufficient_data` fallback, unchanged.

#### REQ-4: Turn the weights into a budget size
WHEN `calibration_kind` is `by_type`, THE Forecaster SHALL derive the tokens-per-percent value of the budget from the type weights and the recent mix.

Acceptance criteria:
- AC-4.1 THE Forecaster SHALL compute the recent mix from the provider's tokens over the 7 local days before today.
- AC-4.2 IF the provider has no tokens in those 7 days, THEN THE Forecaster SHALL use the mix of the tokens in its reading pairs.
- AC-4.3 THE Forecaster SHALL set the stored `tokens_per_percent` to 1 divided by the sum of each type weight times the recent mix share, so that the budget formula in `forecast_budget.py` is unchanged.
- AC-4.4 IF that sum is zero, THEN THE Forecaster SHALL use the single ratio and set `calibration_kind` to `single`.
- AC-4.5 WHEN `calibration_kind` is `single`, THE Forecaster SHALL store the single ratio exactly as before.

#### REQ-5: Score the calibration with a rolling backtest
THE Forecaster SHALL measure how well the calibration predicted past percent changes using only earlier data.

Acceptance criteria:
- AC-5.1 WHEN a provider has at least 6 pairs, THE Forecaster SHALL replay the pairs in time order and, for each pair from the sixth, predict its percent rise from its tokens using a fit on earlier pairs only.
- AC-5.2 THE Forecaster SHALL use the by-type fit in the replay for a step only when `calibration_kind` is `by_type` and at least 20 earlier pairs exist, and the single ratio otherwise.
- AC-5.3 THE Forecaster SHALL report the mean absolute error in percentage points of the replay, the number of predicted pairs, and the same error for the single ratio over the same pairs.
- AC-5.4 IF a provider has fewer than 6 pairs, THEN THE Forecaster SHALL report the rolling backtest as `null` and SHALL NOT report any error number.

#### REQ-6: Check past days against the budget
THE Forecaster SHALL count how many past days stayed within the budget as it stood at the start of each day.

Acceptance criteria:
- AC-6.1 THE Forecaster SHALL consider each of the last 30 local days before today as scoreable only when a reading of the same weekly window with a known reset time exists within 12 hours before that day's start and the day is not after that reset.
- AC-6.2 THE Forecaster SHALL compute that day's budget as the capacity at the day's start (the calibrated tokens for the percent left at the reading, plus the tokens logged between the reading and the day's start) multiplied by the day's share of the days left, using a calibration fitted on pairs that ended before the day.
- AC-6.3 THE Forecaster SHALL mark a scoreable day as within budget when the provider's tokens that day were at most that budget.
- AC-6.4 THE Forecaster SHALL report the number of days within budget and the number of scoreable days.
- AC-6.5 IF fewer than 5 days are scoreable, THEN THE Forecaster SHALL report the budget check as `null`.

#### REQ-7: Show the method and the scores
THE system SHALL return the calibration method and scores in `GET /api/forecast`, and THE panel SHALL explain them in plain words.

Acceptance criteria:
- AC-7.1 THE system SHALL add to each provider entry `calibration_kind`, `calibration_readings`, the rolling backtest (`mae_points`, `single_mae_points`, `readings`) or `null`, and the budget check (`within`, `scored`) or `null`.
- AC-7.2 WHERE `calibration_kind` is `by_type`, THE panel SHALL say that the provider's calibration learns how much each kind of token (new input, cached input, output) costs the limit.
- AC-7.3 WHERE a provider has a rolling backtest, THE panel SHALL state its error in percentage points against the single-ratio error and the number of readings.
- AC-7.4 WHERE a provider has a budget check, THE panel SHALL state how many of the scored past days stayed within budget.
- AC-7.5 WHERE `calibration_kind` is `single`, THE panel SHALL say that the provider uses one tokens-per-percent ratio because there are too few readings or the detailed method was not more accurate.
- AC-7.6 THE system SHALL NOT include prompt text, session titles, project names, or file paths in the added fields.

### Non-functional requirements

#### NFR-1: Cross-platform behavior
THE feature SHALL behave the same on macOS, Windows, and Linux.

Acceptance criteria:
- AC-1.1 THE feature SHALL use only the Python standard library and SHALL NOT add a dependency to `pyproject.toml`.
- AC-1.2 THE feature SHALL use local-time day boundaries built from naive local datetimes, as the forecast does.
- AC-1.3 BEFORE the feature is merged to `main`, THE check results SHALL be recorded from native runs on macOS, Windows, and Linux per the root `AGENTS.md`, and any platform not run SHALL be reported as an unverified gap.

#### NFR-2: Performance
THE feature SHALL keep the daily fit fast.

Acceptance criteria:
- AC-2.1 THE existing timing test (30 synthetic daily files of about 5 MB) SHALL still fit in under 3 seconds with the added typed history and scoring.
- AC-2.2 THE Calibrator and the scoring SHALL add under 0.5 seconds for a provider with 100 reading pairs, measured by a test that records the time.
- AC-2.3 WHEN stored model state for today exists, THE Forecaster SHALL answer without recomputing the calibration or the scores.

#### NFR-3: Privacy
THE stored and returned values SHALL be aggregates only.

Acceptance criteria:
- AC-3.1 THE Forecast store SHALL hold only counts, weights, ratios, shares, errors, dates, and warnings.
- AC-3.2 THE feature SHALL NOT make any network request.

#### NFR-4: Honesty of reported numbers
THE feature SHALL report only values computed from recorded data.

Acceptance criteria:
- AC-4.1 THE feature SHALL report `null`, never an estimated or default number, for any error or count it could not compute.
- AC-4.2 THE feature SHALL compute every held-out error from predictions made without the data being predicted.

#### NFR-5: Test coverage
THE feature SHALL ship with automated tests in the existing layout.

Acceptance criteria:
- AC-5.1 THE backend tests under `tests/test_services/` and `tests/test_api/` SHALL cover each acceptance criterion of REQ-1 to REQ-7 on synthetic data with known answers, without network access.
- AC-5.2 THE frontend tests in `frontend/src/components/insights/insights.test.tsx` SHALL cover AC-7.2 to AC-7.5.

### Open questions
- **Spec folder:** a `.kiro/specs` folder exists in the repository, but the earlier forecast spec lives in `specs/`; this spec follows the forecast spec and uses `specs/`.
- **Day-check approximations:** the as-of calibration for the budget check uses the chosen method on pairs before the day, and the day's share uses the final stored demand weights (not refitted per day). The weights are flat on the current data, so the effect is expected to be small; this is an assumption.
- **Thresholds:** 20 pairs, the 90% margin, 6 pairs for the rolling backtest, 5 scoreable days, the 12-hour reading gap, and the 7-day mix window are assumptions to tune against real history.
- **Claude coverage:** with about 6 usable pairs, Claude is expected to stay on the single ratio, so the by-type gains will first show on Codex; this is a prediction from the offline check, not a result of this feature.
