# Verification

Feature: widget switch, manual update check, window warm-up. Date: 2026-11-06.

## Automated (macOS arm64, Python 3.13 venv, Node via `npm`)
- `.venv/bin/python -m pytest`: 508 passed, 1 skipped, 1 failed. The failure is `test_legacy_linux_restart_keeps_arguments` (no bundled Linux Python for aarch64) and it fails identically on the commit before these changes.
- `cd frontend && npx vitest run`: 77 passed (13 files). `npx tsc -b` clean. `npm run build` succeeds.
- Qt widget tests (`test_float_window.py`) ran only after PySide6-Essentials 6.12.0 was installed in `.venv` with the user's approval.

## Native macOS (this machine)
| Check | Result | Evidence |
|---|---|---|
| Collector on a temp port, `GET /api/widget` without Qt | `available:false` with reason | curl output in session |
| Enable widget via `POST /api/widget` | widget process starts, `running:true` within 9 s | `ps` showed `launcher.py --float --port 8791` |
| Dock and app switcher | not listed: `lsappinfo` type `BackgroundOnly` | `lsappinfo list` |
| Disable via `POST /api/widget` | process gone within 8 s | `pgrep` count 0 |
| Off then on again | widget restarts within 8 s (a bug here was found and fixed with a test) | `pgrep` count 1 |
| Collector killed | widget exits after about 15 s (3 missed polls) | `pgrep` count 0 at t+15 s |
| Manual update check route | returns status, disabled flag honored | curl output |
| Warm-up save, bad time rejected, next slot shown | works, 400 on `7:30` | curl output |
| Real Claude warm-up send | success, 5.2 s, no session file | direct `Sender` call |

## Not verified
- Windows and Linux: nothing was run natively. Cross-platform verification is INCOMPLETE. Per `AGENTS.md` this must pass on native runners (the release and cross-update workflows) before pushing to main. Specific items: widget start with no console window on Windows, widget start from the PyInstaller build and the `.deb` Qt libraries on Linux, and widget visibility on both.
- On macOS: the widget pill was not looked at on screen, the right-click Quit action was not clicked (its logic is unit tested), and the packaged `.app` was not rebuilt with Qt.
- Real Codex warm-up send (weekly limit at 99% on this account) and any MiniMax send (unavailable).
- The Settings dialog was tested in jsdom only, not in a real browser.
- Update install flow was not touched or run.
