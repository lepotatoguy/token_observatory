# Contributing

Thanks for helping. Token Observatory stays small on purpose: one Python process and three static files, with no dependencies.

## Ground rules

- **Standard library only.** No pip packages and no frontend build step. Python 3.9 is the floor (macOS Command Line Tools ship 3.9).
- **Read-only and local.** Never write to Claude Code or Codex files. The server listens on `127.0.0.1` only. Don't add network calls.
- **No estimates presented as measurements.** If a log doesn't record a value, show it as unreported. Don't infer it from character counts, model names or price lists.
- **Privacy.** Saved history and exports must exclude prompts, responses and credentials.

## Layout

See [DEVELOPMENT.md](DEVELOPMENT.md#repository-layout) for the repository layout, how the numbers are calculated, and how to build and release.

## Development

Run the server from the checkout and reload the browser after editing:

```sh
python3 server.py --port 8766
```

Run the tests before opening a pull request:

```sh
python3 -m unittest
node test_app.js
```

`node test_app.js` needs Node.js 18 or later. It's used only for tests; the app itself never needs Node.

When you change parsing, add a test with a small synthetic log line next to the existing ones in `test_server.py` or `test_codex_usage.py`. Never commit real session logs: they contain prompts and file paths. `.gitignore` already excludes `*.jsonl` and `*.json`.

## Pull requests

- Keep changes focused. Use one pull request per fix or feature.
- Use conventional commit prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- If a change affects what a number means, describe it in the pull request and update the "Accounting" section of `DEVELOPMENT.md` and add a line to `CHANGELOG.md`.
