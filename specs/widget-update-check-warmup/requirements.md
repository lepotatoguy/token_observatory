# Requirements

## Feature: Always-available floating widget, manual update check, and scheduled window warm-up

### Background
Three gaps were found in Token Observatory v1.6.1. First, the floating quota widget cannot be found by users: it starts only from the `--float` command line flag (`backend/launcher.py`), nothing in the dashboard or the installed apps launches it, and the macOS app installed by `build_app.py` ships without PySide6, so `--float` prints an install hint and exits. Released builds also strip Qt on purpose (`.github/workflows/release.yml`). Second, an update system exists (`backend/services/updater.py`, `UpdateDialog.tsx`) but it checks only every 24 hours and the Settings dialog has no way to ask for a check. Third, users on paid plans (Pro or better) of Claude, Codex and MiniMax get a rolling five-hour usage window that begins at the first message sent. A user who sends nothing until they start work loses the head start; a small scheduled message sent to the cheapest model starts the window earlier so it also resets earlier.

### Goals
- Users can switch the floating widget on and off from Settings, and it starts automatically while the collector runs and the setting is on.
- Every shipped build of Token Observatory (macOS, Windows, Linux) includes the widget runtime, so the widget works without extra install steps.
- Users can trigger an update check from Settings at any time and see the answer.
- Users can schedule one or more daily local times per provider (Claude, Codex, MiniMax) at which Token Observatory sends the message "hello" to that provider's lowest-cost model, so the five-hour window starts at a time the user chose.

### Out of scope
- Detecting the user's subscription plan. The warm-up is an opt-in and each provider is off by default.
- Changing the update installer or the update download and verification flow.
- Redesigning the widget's appearance or the quota data it shows.
- A warm-up that runs while the collector is not running (no OS-level scheduler, no launch agent, no cron entry).
- Warm-up for local tools (Ollama, LM Studio, llama.cpp).
- Weekly window management; only the five-hour primary window is considered.

### Glossary
- **Collector**: the long-running Token Observatory server process (`launcher.py --serve`) that owns the `Runtime` background jobs.
- **Widget**: the PySide6 floating quota pill (`backend/services/float_window.py`).
- **Widget service**: the new backend module that stores the widget on/off setting and starts the widget process.
- **Primary window**: the five-hour (300 minute) rate limit window reported by `backend/services/quota.py` and `backend/models/limits.py`.
- **Active window**: a primary window whose `resets_at` is in the future and whose `used_percent` is greater than zero.
- **Warm-up**: a scheduled message ("hello") sent to the lowest-cost model of a provider to start its primary window.
- **Warm-up service**: the new backend module that stores warm-up schedules, decides which sends are due, and sends them.
- **Slot**: one provider plus one configured local time on one local calendar date.

### User stories
1. As a user, I want a switch in Settings that shows or hides the floating widget, so that I can find and control it without a terminal.
2. As a user of the installed app, I want the widget to work out of the box, so that I never have to install Qt myself.
3. As a user, I want a "Check for updates" button in Settings, so that I can learn about a new release without waiting for the daily check.
4. As a Pro subscriber, I want Token Observatory to send "hello" to the cheapest model at times I choose, so that my five-hour window starts when I want it to.

### Requirements

#### REQ-1: Widget on/off setting and lifecycle
THE system SHALL persist a widget on/off setting and SHALL start and stop the widget process to match it.

Acceptance criteria:
- AC-1.1 THE system SHALL store the widget on/off setting in the data folder so that it survives collector and app restarts, and it SHALL default to off.
- AC-1.2 WHEN a client posts `{"enabled": true}` to `POST /api/widget`, THEN the system SHALL save the setting and SHALL start the widget process within 15 seconds.
- AC-1.3 WHEN a client posts `{"enabled": false}` to `POST /api/widget`, THEN the system SHALL save the setting and the widget process SHALL exit within 15 seconds.
- AC-1.4 WHILE the widget setting is on and the collector is running, IF no widget process has reported itself within 30 seconds, THEN the system SHALL start a widget process.
- AC-1.5 THE system SHALL NOT run more than one widget process at the same time.
- AC-1.6 WHEN the user chooses Quit from the widget context menu, THEN the widget SHALL set the widget setting to off before it exits.
- AC-1.7 IF the widget process exits with an error within 5 seconds of starting three times in a row, THEN the system SHALL stop restarting it and SHALL report the failure through `GET /api/widget`.

#### REQ-2: Widget runtime ships in every build
THE system SHALL include the widget runtime in the macOS app, the Windows build, the Linux package and source installs.

Acceptance criteria:
- AC-2.1 THE system SHALL declare PySide6 as a required dependency so that a normal install provides it.
- AC-2.2 THE release build for each operating system SHALL bundle the Qt runtime that the widget needs.
- AC-2.3 THE Linux package SHALL declare the system libraries that the bundled Qt platform plugin needs.
- AC-2.4 IF the widget runtime cannot be imported at launch, THEN `GET /api/widget` SHALL report `available: false` with a reason, and the Settings toggle SHALL be disabled and show that reason.

#### REQ-3: Widget settings control in the dashboard
THE Settings dialog SHALL show a widget section that reflects and changes the widget state.

Acceptance criteria:
- AC-3.1 THE Settings dialog SHALL show a "Floating widget" toggle bound to `GET /api/widget` and `POST /api/widget`.
- AC-3.2 WHEN the toggle changes, THEN the dialog SHALL show the saved state returned by the server, not the requested state.
- AC-3.3 IF `POST /api/widget` fails, THEN the dialog SHALL revert the toggle and SHALL show the error message.
- AC-3.4 WHILE the widget setting is on and the widget is not running, THE dialog SHALL show "Starting" or the reported failure.

#### REQ-4: Manual update check
WHEN the user presses "Check for updates" in Settings, THEN the system SHALL check for a new release immediately and report the result.

Acceptance criteria:
- AC-4.1 WHEN a client posts to `POST /api/update/check`, THEN the system SHALL query the release feed regardless of the 24-hour interval and SHALL return the updated update status.
- AC-4.2 WHEN a newer release exists, THEN the Settings dialog SHALL show its version and an action that opens the existing update dialog.
- AC-4.3 WHEN no newer release exists, THEN the Settings dialog SHALL show "You are on the latest version" with the installed version.
- AC-4.4 IF the release feed cannot be reached, THEN the Settings dialog SHALL show that the check failed and SHALL keep any previously known update status.
- AC-4.5 IF update checks are disabled by `TOKEN_OBSERVATORY_UPDATE_CHECKS=0`, THEN the system SHALL return a disabled status and the dialog SHALL say that update checks are disabled.
- AC-4.6 IF two manual checks arrive less than 5 seconds apart, THEN the system SHALL answer the second one with the result of the first and SHALL NOT make a second network request.

#### REQ-5: Warm-up configuration
THE system SHALL let the user configure, per provider, whether warm-up is on and at which daily local times it runs.

Acceptance criteria:
- AC-5.1 THE system SHALL store the warm-up configuration for Claude, Codex and MiniMax in the data folder, and each provider SHALL default to off with no times.
- AC-5.2 WHEN a client posts a provider configuration to `POST /api/warmup`, THEN the system SHALL accept between 1 and 8 distinct times per provider in 24-hour `HH:MM` form and SHALL save them sorted.
- AC-5.3 IF a posted time is malformed or duplicated, or more than 8 times are posted, THEN the system SHALL reject the whole request with HTTP 400 and SHALL NOT change the saved configuration.
- AC-5.4 IF a client enables a provider with zero times, THEN the system SHALL reject the request with HTTP 400.
- AC-5.5 THE Settings dialog SHALL show, per provider, a toggle, the list of times with add and remove controls, and the text of the message that will be sent.
- AC-5.6 THE Settings dialog SHALL state that warm-up uses a small amount of the user's quota and is intended for paid plans.

#### REQ-6: Warm-up scheduling
THE system SHALL decide once per slot whether to send, skip or catch up.

Acceptance criteria:
- AC-6.1 WHILE the collector is running and a provider is on, WHEN the local clock reaches a configured time, THEN the system SHALL attempt that slot within 60 seconds.
- AC-6.2 WHEN the collector starts or the computer wakes and a slot's time passed less than 30 minutes ago with no recorded outcome, THEN the system SHALL attempt that slot.
- AC-6.3 IF a slot's time passed 30 minutes or more ago with no recorded outcome, THEN the system SHALL record it as `missed` and SHALL NOT send.
- AC-6.4 IF the provider has an active primary window when a slot is attempted, THEN the system SHALL record the slot as `skipped_active` and SHALL NOT send.
- AC-6.5 THE system SHALL record exactly one outcome per slot and SHALL NOT retry a slot after any outcome, including failure.
- AC-6.6 IF the provider's primary window state is unknown at attempt time, THEN the system SHALL send.
- AC-6.7 THE system SHALL NOT run two sends for the same provider concurrently.

#### REQ-7: Warm-up message to the lowest-cost model
WHEN a slot is sent, THEN the system SHALL send the message "hello" to the provider's lowest-cost model without persisting a session.

Acceptance criteria:
- AC-7.1 WHEN the provider is Claude, THEN the system SHALL run the Claude Code command in non-interactive print mode with model `haiku`, effort `low`, no session persistence and no tools.
- AC-7.2 WHEN the provider is Codex, THEN the system SHALL run `codex exec` with the cheapest configured model at low reasoning effort, read-only sandbox, and the git repository check skipped.
- AC-7.3 WHEN the provider is MiniMax, THEN the system SHALL send one request with the stored MiniMax key to the provider's lowest-cost coding model.
- AC-7.4 THE system SHALL bound each send to 60 seconds and SHALL record `failed` with a short reason on timeout, non-zero exit, missing command, missing credentials or HTTP error.
- AC-7.5 THE system SHALL NOT store the provider's reply text, only the outcome, the time and a failure reason.
- AC-7.6 IF a provider is not signed in or its tool is not installed, THEN the system SHALL record `failed` with that reason and SHALL NOT prompt for credentials.

#### REQ-8: Warm-up status visibility
THE system SHALL show the most recent outcome of each provider's slots.

Acceptance criteria:
- AC-8.1 WHEN a client requests `GET /api/warmup`, THEN the system SHALL return each provider's configuration, its next scheduled slot in local time, and its last 10 outcomes with time, slot and status.
- AC-8.2 THE Settings dialog SHALL show each provider's next slot and last outcome.
- AC-8.3 THE system SHALL keep at most 200 outcome records and SHALL drop the oldest first.

#### REQ-9: Wait for an exhausted limit to reset
WHEN a slot is due and the provider's five-hour window is used up, THEN the system SHALL send the message one minute after that window's reset time instead of failing now.

Acceptance criteria:
- AC-9.1 WHEN a slot is attempted and the primary window has `used_percent` of 100 or more and a `resets_at` in the future, THEN the system SHALL record the slot as deferred with a send time of `resets_at` plus 60 seconds and SHALL NOT send yet.
- AC-9.2 WHEN the local clock reaches a deferred send time and no window is active, THEN the system SHALL send the message and SHALL record `sent` with the reason "after the limit reset".
- AC-9.3 IF the window is still used up when a deferred send time arrives, THEN the system SHALL defer again to the new reset time plus 60 seconds.
- AC-9.4 IF a window with some usage but not used up exists when a deferred send time arrives, THEN the system SHALL record `skipped_active` and SHALL NOT send.
- AC-9.5 IF a deferred send time passed 30 minutes or more ago with no outcome, THEN the system SHALL record `missed` and SHALL NOT send.
- AC-9.6 THE system SHALL keep deferred sends across a restart and SHALL drop them when the provider is turned off or its schedule changes.
- AC-9.7 THE system SHALL read fresh limits before deciding, and `GET /api/warmup` SHALL show each provider's deferred slot and send time.

### Non-functional requirements

#### NFR-1: Security and privacy
THE system SHALL keep the new endpoints local and SHALL NOT widen credential handling.

Acceptance criteria:
- AC-1.1 THE new `POST` endpoints SHALL pass through the existing JSON content-type, 1024-byte body limit and Host/Origin checks.
- AC-1.2 THE system SHALL NOT read the Claude or Codex credential files; those tools SHALL authenticate with their own sign-in.
- AC-1.3 THE system SHALL use the MiniMax key only through `backend/services/minimax.py` `credentials()` and SHALL NOT log it or return it from any endpoint.
- AC-1.4 THE system SHALL NOT write the warm-up message or reply into the usage history or logs beyond the outcome record.
- AC-1.5 THE warm-up SHALL be opt-in, and `CONTRIBUTING.md` SHALL document that exception to the no-automatic-remote-calls rule.

#### NFR-2: Cross-platform behavior
THE system SHALL behave the same on macOS, Windows and Linux.

Acceptance criteria:
- AC-2.1 THE widget process SHALL start detached with no console window on Windows and no Dock icon on macOS.
- AC-2.2 THE widget process SHALL NOT appear in the Dock, taskbar entry list or app switcher beyond what the existing widget behavior allows on each operating system.
- AC-2.3 THE system SHALL be verified by running the affected behavior natively on each operating system, with results recorded in `verification.md`.

#### NFR-3: Resource use and reliability
THE system SHALL keep background work small and bounded.

Acceptance criteria:
- AC-3.1 THE warm-up scheduler tick SHALL finish in under 50 ms when no slot is due.
- AC-3.2 THE system SHALL run no more than one warm-up send process at a time across all providers.
- AC-3.3 IF the collector stops during a send, THEN the system SHALL terminate the child process.
- AC-3.4 THE system SHALL write the widget and warm-up settings and state files atomically.

#### NFR-4: Accessibility
THE new Settings controls SHALL meet WCAG 2.1 AA for the controls added.

Acceptance criteria:
- AC-4.1 THE system SHALL give every toggle, time input and button a visible label and keyboard focus.
- AC-4.2 THE system SHALL announce check and save results to assistive technology with a polite live region.

#### NFR-5: No regression
THE system SHALL keep existing behavior unchanged.

Acceptance criteria:
- AC-5.1 THE `GET /api/quota`, `GET /api/update`, `POST /api/update/settings` and `POST /api/update/install` contracts SHALL stay backward compatible.
- AC-5.2 THE `--float` command line flag SHALL keep working for source users.
- AC-5.3 THE existing automated tests SHALL keep passing.

### Open questions
- Codex cheapest model: `codex-cli 0.160.0` offers no flag that names the cheapest model. Assumption: the default is the model the user already uses at `model_reasoning_effort=low`, and the user can type a model id per provider. Confirm which model id to default to.
- MiniMax send path: the repo shows MiniMax Anthropic-compatible hosts (`api.minimax.io`, `api.minimaxi.com`) but not the request path or the lowest-cost model id. `[UNVERIFIED]` Verify against MiniMax documentation before T8. If it cannot be verified, MiniMax warm-up ships disabled with an "unavailable" reason.
- Active window test: assumed that a Claude or Codex window reports a future `resets_at` and `used_percent > 0` only after the first message. `[ASSUMPTION]` Verify with live `/usage` output before T6.
- Claude `--effort low` was seen in `claude --help` (v2.1.319), and `--model`, `--tools` and `--no-session-persistence` also exist. Verified locally on 2026-11-06 on macOS only.
