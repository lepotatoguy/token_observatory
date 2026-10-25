Standalone builds of Token Observatory, a local dashboard for Claude Code and Codex token usage. Python is bundled, so nothing else needs to be installed. Data stays on your machine.

## Downloads

| Platform | File |
|---|---|
| macOS (Apple silicon) | `TokenObservatory-<version>-macos-arm64.zip` |
| Linux (Debian, Ubuntu; x86-64) | `TokenObservatory-<version>-linux-amd64.deb` |
| Windows (x86-64) | `TokenObservatory-<version>-windows-x64.exe` |
| Source (used by source installs to update) | `TokenObservatory-<version>-source.tar.gz` |

`SHA256SUMS.txt` lists checksums for every file.

## Install

**macOS.** Unzip, move **Token Observatory.app** to Applications, and open it. The app isn't notarized, so macOS blocks the first launch. Either right-click the app and choose **Open**, or run:

```sh
xattr -dr com.apple.quarantine "/Applications/Token Observatory.app"
```

**Linux.**

```sh
sudo apt install ./TokenObservatory-<version>-linux-amd64.deb
token-observatory
```

It also appears in the desktop menu as **Token Observatory**.

**Windows.** Run the `.exe`. It isn't code-signed, so SmartScreen may warn: choose **More info**, then **Run anyway**.

## Use

Opening the app starts a background collector and opens <http://127.0.0.1:8765> in your browser. Opening it again reuses the running collector. To stop the collector:

- macOS: `"/Applications/Token Observatory.app/Contents/MacOS/TokenObservatory" --stop`
- Linux: `token-observatory --stop`
- Windows: `TokenObservatory-<version>-windows-x64.exe --stop`

The first launch can take up to a minute while the OS scans the new app. See [INSTALL.md](https://github.com/lepotatoguy/token_observatory/blob/main/INSTALL.md) for options, data folders and troubleshooting.
