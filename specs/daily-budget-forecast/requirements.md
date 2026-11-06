# Requirements

## Feature: Demand-weighted daily budget forecast

### Background
The Insights tab has a "Today's budget" panel (`frontend/src/components/insights/BudgetPanel.tsx`) that shows tokens used today against a budget and offers a "Suggested" daily budget. Today that suggestion is computed in the browser by `suggestedBudget()`: it divides the tokens used in the current weekly window by the weekly `used_percent` to get tokens per percent, multiplies by the remaining percent, and splits the result evenly over the days left. This has two weaknesses. First, every remaining day receives the same share, even though the user's usage differs by weekday. Second, it needs at least 1% of the weekly window used before it can produce anything, and it calibrates tokens per percent from a single week, which is noisy early in the week.

The app already keeps one gzip JSON snapshot per local day (`backend/services/archive.py`, files `YYYY-MM-DD.json.gz`) containing sessions with timestamped token events. This feature replaces the even split with a forecast: the remaining weekly allowance stays the base, it is divided across the remaining days in proportion to how much the user is predicted to use on each day, and the conversion from percent to tokens is calibrated from up to 30 days of history. The forecast is based on the weekly limit that is left and on how the user has actually used it.

### Goals
- Make the suggested daily budget depend on the weekly limit left and on the user's own usage history (at most the last 30 days).
- Split the remaining weekly allowance across remaining days in proportion to predicted daily demand.
- Calibrate tokens per percent from history so that a budget is available early in a weekly window.
- Work with any amount of history, and fall back to the current even split when the history is too short.
- Fit the model once per local day, and apply it to the live limits on every request.
- Use only the Python standard library, so behavior is identical on macOS, Windows, and Linux.
- Report only values computed from recorded usage, with a measured backtest error.

### Out of scope
- Heavy machine learning (XGBoost, scikit-learn, numpy, pandas) and any new dependency in `pyproject.toml`.
- Budgeting against the 5-hour session window; only the weekly window drives the budget.
- Per-model limits or per-model budgets (limits exist per provider account; models are not forecast separately).
- Changing, enforcing, or pausing on limits; `backend/services/limit_control.py` is not modified.
- Sending any data off the machine.
- Redesigning the panel layout; the existing panel, the "Change budget" form, the "Use suggested" button, and the 80% and 100% alerts keep their behavior.

### Glossary
- **Forecaster**: the new backend component that fits the model and computes the budget.
- **Daily usage series**: for one provider, the total tokens used on each local calendar day, built from timestamped session events.
- **Demand weight**: the predicted token usage for one local day, used only as a relative weight between days.
- **Tokens per percent**: the number of tokens that correspond to 1% of a provider's weekly window, learned from history.
- **Remaining capacity**: tokens per percent multiplied by the remaining weekly percent (100 minus `used_percent`).
- **Start-of-day capacity**: Remaining capacity plus the tokens the provider has already used today inside the current weekly window; it is the allowance the day began with, so it stays steady while the day passes.
- **Reset day**: the local day on which the weekly window resets (`resets_at`).
- **History window**: the most recent 30 local days that precede today.
- **Even split**: the current behavior, where every day from today to the reset day has the same weight.
- **Model state**: the per-provider fitted values (demand model, tokens per percent, days used, backtest error) stored once per day.
- **Forecast store**: the file in the per-user data folder that holds the model state.

### User stories
1. As a user near my weekly limit, I want today's suggested budget to reflect how much of the week I have left, so that I do not run out before the reset.
2. As a user whose usage differs by weekday, I want heavier days to receive a larger share than quiet days, so that the budget matches how I really work.
3. As a user early in a weekly window, I want a suggestion even when only a little of the week is used, so that the panel is not empty.
4. As a new user with only a few days of history, I want the panel to keep working with a clear note about its confidence, so that I am not shown nothing or a misleading number.

### Requirements

#### REQ-1: Build the daily usage series from history
THE Forecaster SHALL build a daily usage series for each enabled provider from the archived snapshots and the current snapshot, limited to the History window.

Acceptance criteria:
- AC-1.1 THE Forecaster SHALL assign each session event to a local calendar day using the event timestamp `at`, and SHALL sum `input`, `cached`, `write`, and `output` tokens, excluding `reasoning` because it is already part of `output` (matching `total()` in `backend/parsers/_helpers.py`).
- AC-1.2 THE Forecaster SHALL count each event at most once across all archived day files by using, for each session id, only the newest archived snapshot that contains that session, so that a session that appears in several consecutive daily snapshots does not inflate any day.
- AC-1.3 WHEN an event has no timestamp, THE Forecaster SHALL exclude it from the daily series and SHALL count it in a reported `skipped_events` number.
- AC-1.4 THE Forecaster SHALL exclude today's partial usage from the training series.
- AC-1.5 IF an archived snapshot file cannot be read, THEN THE Forecaster SHALL skip that file, SHALL record a warning, and SHALL continue with the remaining days.
- AC-1.6 THE Forecaster SHALL count every local day that has no events as zero tokens, from the provider's first recorded event inside the History window until yesterday, because session logs record all usage whether or not the app was open.

#### REQ-2: Predict relative demand for each remaining day
THE Forecaster SHALL predict a demand weight for every local day from today through the Reset day for each provider.

Acceptance criteria:
- AC-2.1 WHEN a provider's series has at least 18 days, THE Forecaster SHALL fit a deterministic regression model that uses the weekday and recent usage as inputs, and SHALL backtest it against a flat baseline on that provider's own days.
- AC-2.2 WHEN the backtest mean absolute error of the regression model is lower than that of the flat baseline, THE Forecaster SHALL use the regression weights and SHALL set `demand_method` to `weekday_regression`.
- AC-2.3 WHEN the regression model does not beat the flat baseline in the backtest, or the series has fewer than 18 days, THE Forecaster SHALL give every remaining day the same weight and SHALL set `demand_method` to `flat`.
- AC-2.4 THE Forecaster SHALL return only positive demand weights.
- AC-2.5 THE Forecaster SHALL report `days_used`, the backtest mean absolute error of the model, and the backtest mean absolute error of the baseline whenever a backtest was run, and SHALL report `backtest` as `null` otherwise.
- AC-2.6 THE Forecaster SHALL set `confidence` to `low` when `days_used` is below 7, `medium` from 7 to 17, and `normal` from 18.

#### REQ-3: Calibrate tokens per percent from history
THE Forecaster SHALL learn tokens per percent for each provider from the recorded weekly percent and the tokens used.

Acceptance criteria:
- AC-3.1 WHEN history holds at least 2 usable weekly percent samples for a provider within the History window, THE Forecaster SHALL estimate tokens per percent from the tokens used between pairs of samples and the change in weekly percent between them.
- AC-3.2 THE Forecaster SHALL NOT pair two samples that belong to different weekly windows, so that a weekly reset (a drop in percent, or a different `resets_at`) does not produce a negative or inflated ratio.
- AC-3.6 THE Forecaster SHALL draw weekly percent samples from the Claude desktop plan usage samples (`plan-usage-history.json`), from the `rate_limits` recorded with archived sessions, and from the `limits` captured in each archived daily snapshot.
- AC-3.7 THE Forecaster SHALL pair two samples only when the weekly percent changed by at least 2 points between them, so that whole-number rounding of the percent does not dominate the ratio.
- AC-3.3 IF a provider has fewer than 2 calibration pairs or fewer than 7 days of history, THEN THE Forecaster SHALL return no budget for that provider and SHALL set `excluded` to `insufficient_data`, so that the panel uses the previous browser even-split calculation.
- AC-3.4 THE Forecaster SHALL NOT estimate tokens per percent from the current weekly window alone; that case belongs to the previous browser calculation.
- AC-3.5 THE Forecaster SHALL report `calibration_pairs` and SHALL set `calibration` to `history` for every provider it budgets.

#### REQ-4: Compute the demand-weighted daily budget
THE Forecaster SHALL compute today's suggested budget for each provider from the weekly limit that is left and the demand weights.

Acceptance criteria:
- AC-4.1 WHEN a provider has a weekly window with `used_percent` and `resets_at` and a usable tokens per percent, THE Forecaster SHALL compute Remaining capacity as tokens per percent multiplied by the larger of zero and 100 minus `used_percent`.
- AC-4.2 THE Forecaster SHALL compute Start-of-day capacity as Remaining capacity plus the tokens the provider has used today inside the current weekly window.
- AC-4.3 THE Forecaster SHALL compute today's budget as Start-of-day capacity multiplied by today's demand weight divided by the sum of the demand weights from today through the Reset day, where each day's weight is scaled by the fraction of that day that lies inside the weekly window, so that the budget does not shrink as the day passes.
- AC-4.4 WHEN the weekly `used_percent` is 100 or more, THE Forecaster SHALL set Remaining capacity to zero, so that today's budget does not exceed the tokens already used today.
- AC-4.5 THE Forecaster SHALL compute the total suggested budget as the sum of the per-provider budgets.
- AC-4.6 WHERE the weekly reset time is marked as estimated (`resets_estimated`), THE Forecaster SHALL carry that flag into the result.
- AC-4.7 THE Forecaster SHALL NOT change any limit, pause state, or threshold stored by `Control` in `backend/services/limit_control.py`.

#### REQ-5: Fit once per day and apply to live limits on each request
THE Forecaster SHALL fit the model at most once per local day and SHALL apply the stored model state to the current limits on every request.

Acceptance criteria:
- AC-5.1 WHEN a forecast is requested on a local day and the Forecast store holds no model state dated today, THE Forecaster SHALL fit the model and SHALL write the model state to the Forecast store.
- AC-5.2 WHEN model state dated today exists, THE Forecaster SHALL NOT read any archived snapshot to answer the request.
- AC-5.3 THE Forecaster SHALL compute the budget from the stored model state and the live weekly `used_percent`, `resets_at`, and tokens used today on every request.
- AC-5.4 THE Forecaster SHALL write the Forecast store atomically, by writing a temporary file in the same folder and then replacing the target.
- AC-5.5 WHEN the app starts after days of being closed, THE Forecaster SHALL fit only today's model state and SHALL NOT back-fill missed days.
- AC-5.6 IF the Forecast store cannot be written, THEN THE Forecaster SHALL still return the computed budget and SHALL report a warning.

#### REQ-6: Expose the forecast and use it in the panel
THE system SHALL expose the forecast through a read-only endpoint, and THE panel SHALL use it as the suggested budget.

Acceptance criteria:
- AC-6.1 WHEN a client sends `GET /api/forecast`, THE system SHALL respond with HTTP 200 and a JSON body containing `date`, `generated_at`, `total`, and one entry per enabled provider with `daily`, `share`, `confidence`, `demand_method`, `shrinkage`, `backtest`, `calibration`, `calibration_pairs`, `days_used`, `excluded`, and `warnings`.
- AC-6.2 WHEN a client sends `GET /api/forecast?refresh=1`, THE system SHALL refit the model and return the new result.
- AC-6.3 WHEN the response holds a budget for a provider, THE panel SHALL use that budget in place of the browser even-split value for that provider, in the total, the per-provider split, the "Use suggested" button, and the explanatory note.
- AC-6.4 WHEN the response holds no budget for a provider but the browser calculation does, THE panel SHALL use the browser value for that provider and SHALL label it as an even split.
- AC-6.5 THE panel note SHALL state the confidence and the number of days used for the forecast.
- AC-6.6 IF the request fails or the archive is not configured, THEN THE panel SHALL show the browser even-split suggestion exactly as it does today.
- AC-6.7 THE system SHALL NOT include prompt text, session titles, or project names in the forecast response.
- AC-6.8 THE panel SHALL name, for each provider budgeted by the forecast, the algorithm used (even split, or weekday regression with its shrinkage), the number of calibration readings and days of history, and the backtest mean absolute error in tokens per day with its number of test days and the flat baseline error, or SHALL state that accuracy is not measured yet when no backtest ran.

### Non-functional requirements

#### NFR-1: Cross-platform behavior
THE Forecaster SHALL behave the same on macOS, Windows, and Linux.

Acceptance criteria:
- AC-1.1 THE Forecaster SHALL use only the Python standard library and SHALL NOT add a dependency to `pyproject.toml`.
- AC-1.2 THE Forecaster SHALL determine day boundaries in the local time zone, matching how `Archive.update` names files and how `BudgetPanel` calls `dayStart(dayKey(now))`.
- AC-1.3 THE Forecaster SHALL locate the Forecast store through `default_data()` in `backend/services/archive.py` and SHALL NOT hardcode a path separator.
- AC-1.4 BEFORE this feature is merged to `main`, THE check results SHALL be recorded from native runs on macOS, Windows, and Linux per the root `AGENTS.md`, and any platform not run SHALL be reported as an unverified gap.

#### NFR-2: Performance
THE Forecaster SHALL stay fast enough to run inside a normal request.

Acceptance criteria:
- AC-2.1 THE Forecaster SHALL fit the model from 30 daily snapshots of 5 MB each in under 3 seconds, measured by a test that records the time.
- AC-2.2 WHEN model state for today exists, THE Forecaster SHALL answer in under 50 milliseconds.
- AC-2.3 THE Forecaster SHALL read each archived snapshot file at most once per fit.

#### NFR-3: Privacy and local-only operation
THE Forecaster SHALL keep all data on the user's machine.

Acceptance criteria:
- AC-3.1 THE Forecaster SHALL NOT make any network request.
- AC-3.2 THE Forecast store SHALL contain only aggregate token counts, percentages, dates, and warnings.
- AC-3.3 THE Forecast store folder SHALL be created with owner-only permissions (`0o700`) where the platform supports it, as `Archive` does.

#### NFR-4: Honesty of reported numbers
THE Forecaster SHALL report only values computed from recorded data.

Acceptance criteria:
- AC-4.1 THE Forecaster SHALL NOT invent usage: every nonzero day in the series SHALL come from recorded events.
- AC-4.2 THE Forecaster SHALL NOT include days before a provider's first recorded event in that provider's series, so that a newly enabled provider is not padded with zeros.
- AC-4.3 THE Forecaster SHALL include `days_used`, `confidence`, `demand_method`, and `calibration` with every budget.

#### NFR-5: Test coverage
THE feature SHALL ship with automated tests in the existing layout.

Acceptance criteria:
- AC-5.1 THE backend tests under `tests/test_services/` SHALL cover each acceptance criterion in REQ-1 through REQ-5 with at least one pytest case on synthetic snapshots in a temporary data folder.
- AC-5.2 THE frontend tests in `frontend/src/components/insights/insights.test.tsx` SHALL cover AC-6.3 through AC-6.6.
- AC-5.3 THE tests SHALL run without network access.

### Decisions from review
- **Today's weight:** removed as an open question. The budget is the share of Start-of-day capacity, so no partial-day weight or floor is needed (AC-4.2, AC-4.3).
- **Calibration sources (verified on this machine's data):** Claude has 44 weekly percent samples over 22 days in `plan-usage-history.json` with no reset times; Codex has 106 distinct samples with `used_percent`, `resets_at`, and `window_minutes` in archived sessions; MiniMax has only one archived `limits` capture per day, so it is left to the previous system until it has enough history.
- **Day boundary:** local midnight, matching the existing panel.

### Open questions
- **Thresholds:** 18 days for the regression, 7 and 18 for confidence, and the 2-point pairing minimum are assumptions to tune in design after testing on real history.
- **Expected effect of the weekday weights:** on this machine's recorded usage, daily totals vary by roughly ten times with no obvious weekday pattern, so the backtest may often select the flat baseline. The calibration is then the main gain. This is a prediction to be measured, not a result.
