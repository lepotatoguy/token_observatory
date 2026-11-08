# Contributing

Token Observatory has a Flask and Pydantic backend and a React 18 frontend written in TypeScript.

## Ground rules

- Keep telemetry local. Bind the dashboard and pass-through proxies to 127.0.0.1. Preserve Host, Origin, JSON body-size and response-header protections.
- Read source logs without changing them. Only explicit install/uninstall commands may modify Claude Code or Codex settings.
- Keep prompts, responses and credentials out of normalized history and exports. Local proxy titles retain only the first 60 characters of the first user message.
- Show missing measurements as unreported. Reasoning is included in output tokens and must not be counted twice. Preserve response deduplication and subagent grouping.
- MiniMax tracking reads local logs and its native read-only SQLite ledger. Do not add automatic remote quota calls or API-key controls. The one exception is the opt-in window warm-up, which sends a fixed "hello" through the provider's own tool at times the user schedules; it is off by default, never stores replies, and must not read Claude or Codex credentials.
- Preserve recorded history when a provider is disabled. Provider choices control live services.

## Development

Use Python 3.10 or later and Node.js 20 or later:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[test]'
cd frontend
npm ci
npm run dev
```

In a second terminal at the repository root, start the API on the port used by the Vite proxy:

```sh
.venv/bin/python launcher.py --serve --port 8766
```

Before submitting a change:

```sh
.venv/bin/python -m pytest
cd frontend
npm test -- --run
npm run build
```

Backend tests live in tests/ and use synthetic logs and temporary data folders. Frontend tests live beside their modules. Never commit personal telemetry or credentials. Keep tests isolated from real provider commands and personal history.

## Pull requests

Keep changes focused. Use conventional commit prefixes. Explain accounting changes with a small before/after example and update DEVELOPMENT.md and CHANGELOG.md when behavior changes. See DEVELOPMENT.md for packaging and deployment commands.
