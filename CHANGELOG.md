# Changelog

All notable changes to Token Observatory. Versions follow [Semantic Versioning](https://semver.org/).

## [1.2.0] - 2026-10-19

### Added

- **Refresh** button. It rescans the logs and asks Claude Code (`claude -p /usage`, no model request) and Codex (`codex app-server`) for current 5-hour and weekly usage. The dashboard also checks when it opens, and the collector every 5 minutes. A failed check says why and keeps the last good numbers.
- Today's budget meter is split into a Claude Code part and a Codex part, each sized by that tool's suggested daily share, with a line per tool showing tokens used, its share and the percentage.
- Optional conversation hooks for Claude Code and Codex (`--install-hooks`, removed with `--uninstall-hooks`). Near the 5-hour limit (90% by default) the running chat is asked to stop new work and write a handoff summary to `.claude/handoffs/` or `.codex/handoffs/`; at 60% context it is asked to condense and continue. Both thresholds are set in `config.json`.

### Changed

- Claude Code models documented as running with a 1M context window by default (Opus 4.7 and later, Sonnet 5 and later, Haiku 5.5) now show a context percentage without extra configuration.
- The Claude status line is now optional; live checks cover the desktop app's Code tab, which doesn't run status lines.

## [1.1.0] - 2026-10-19

### Added

- Click a day's bar in Token activity to view that day across the whole dashboard; a date chip clears it.
- Usage limits card for Claude Code and Codex: 5-hour and weekly quota, shown as used and left, with reset countdowns.
- Optional Claude Code status line (`--install-statusline`, removed with `--uninstall-statusline`) that records Claude's live 5-hour and weekly limits and shows them in your terminal. Without it, Claude limits come from the Claude desktop app's occasional usage samples.
- Daily token budget meter with a suggested daily amount, estimated from each weekly quota, this week's usage, and the days until reset.
- Breakdown by model or project, with share and cache reuse; click a name to filter.
- Trends: today vs your 7-day average, week over week, busiest recent day, and a weekday-by-hour heatmap.
- Context pressure banner, conversation badges, and optional desktop alerts for full context windows and the daily budget.
- Cache details in the inspector, including Claude's 5-minute vs 1-hour cache writes.

## [1.0.1] - 2026-10-18

### Changed

- With no conversation selected, the inspector now shows combined usage for every chat that matches the current filters and search. Click a chat for its details; click it again, or choose **All conversations**, to go back.
- **Tokens** and **Last activity** each sort in either direction. The list now opens sorted by newest activity.
- The README is now a short guide for regular users. Technical details (accounting rules, data files, security, building and releasing) moved to the new DEVELOPMENT.md.

## [1.0.0] - 2026-10-18

First release.

### Added

- Standalone apps with Python bundled: macOS (Apple silicon) `.zip`, Linux `.deb`, and Windows `.exe`, built and smoke-tested by GitHub Actions and published with SHA-256 checksums.
- A launcher that starts the collector in the background once, opens the dashboard, and stops it with `--stop`.
- One row per conversation: Claude Code and Codex subagent usage counts toward the chat that started it.
- Claude context card with the latest request's token breakdown, plus capacity from a recorded `[1m]` model ID or a per-model `config.json` setting (1M default for `claude-opus-5-5`).
- Per-chat token timelines, provider and time filters, search, CSV and JSON export, and daily saved history.
- Source install scripts for macOS and Linux, plus INSTALL.md, CONTRIBUTING.md, and the MIT license.

### Fixed

- Claude conversations stopped updating while their subagents did the work.
- Daily history used a fixed time zone; it now uses the computer's own. Linux and Windows store data in their standard folders.
- One-file Linux and Windows builds lost their files once the launcher exited.

[1.0.1]: https://github.com/lepotatoguy/token_observatory/compare/v1.0.0...v1.0.1
[1.0.0]: https://github.com/lepotatoguy/token_observatory/releases/tag/v1.0.0
