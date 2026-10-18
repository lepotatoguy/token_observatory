# Changelog

All notable changes to Token Observatory. Versions follow [Semantic Versioning](https://semver.org/).

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
