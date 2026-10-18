# Contributing

Thanks for helping. Token Observatory stays small on purpose: one Python process and three static files, with no dependencies.

## Ground rules

- **Standard library only.** No pip packages and no frontend build step. Python 3.9 is the floor (macOS Command Line Tools ship 3.9).
- **Read-only and local.** Never write to Claude Code or Codex files. The server listens on `127.0.0.1` only. Don't add network calls.
- **No estimates presented as measurements.** If a log doesn't record a value, show it as unreported. Don't infer it from character counts, model names or price lists.
- **Privacy.** Saved history and exports must exclude prompts, responses and credentials.

## Layout

| Path | Purpose |
|---|---|
| `server.py` | Log discovery, parsing, HTTP API (`/api/usage`, `/api/history/<day>`, `/api/health`) |
| `codex_usage.py` | Codex accounting helpers |
| `archive.py` | Daily JSON snapshots, written atomically with private permissions |
| `index.html`, `app.js`, `style.css`, `logo.svg` | Dashboard UI |
| `build_app.py`, `launch-app.sh` | macOS app bundle and its launcher |
| `scripts/token-observatory` | Portable launcher (Linux install, or run from a checkout) |
| `launcher.py` | Start-once launcher with `--stop`; entry point of the standalone builds |
| `packaging/` | PyInstaller spec, icons, `.deb` builder and release notes |
| `.github/workflows/release.yml` | Builds macOS, Linux and Windows releases |
| `install.sh`, `uninstall.sh` | Per-user install and removal |
| `test_*.py`, `test_app.js` | Tests |

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

## Releases

1. Bump `VERSION` in `launcher.py`.
2. Optionally run **Release** manually from the Actions tab to build and smoke-test all three platforms.
3. Tag and push: `git tag v1.2.3 && git push origin v1.2.3`. The workflow checks that the tag matches `VERSION`, builds on macOS, Ubuntu and Windows runners, and publishes the release with checksums.

To build locally: `pip install pyinstaller==6.11.1`, then `pyinstaller --noconfirm packaging/token_observatory.spec`. The `.deb` step (`python3 packaging/build_deb.py dist/token-observatory <version> out.deb`) needs `dpkg-deb`.

## Pull requests

- Keep changes focused. Use one pull request per fix or feature.
- Use conventional commit prefixes: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.
- If a change affects what a number means, describe it in the pull request and update the "Accounting and limits" section of `README.md`.
