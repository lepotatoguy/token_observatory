# Token Observatory

See how many tokens your Claude Code and Codex chats use, live, in a dashboard on your own computer. It reads the logs those tools already save. Nothing is uploaded and no API key is needed.

## Download

Get the latest version from [Releases](https://github.com/lepotatoguy/token_observatory/releases/latest).

| Your computer | Download |
|---|---|
| Mac with Apple silicon (M1 or later) | `TokenObservatory-<version>-macos-arm64.zip` |
| Windows | `TokenObservatory-<version>-windows-x64.exe` |
| Ubuntu or Debian Linux | `TokenObservatory-<version>-linux-amd64.deb` |

## Install and open

**Mac.** Unzip the file and drag **Token Observatory** into Applications. The first time, right-click it and choose **Open** (macOS warns because the app isn't from the App Store).

**Windows.** Double-click the `.exe`. If Windows shows "Windows protected your PC", choose **More info**, then **Run anyway**.

**Linux.** Install it, then open **Token Observatory** from your app menu or run `token-observatory`:

```sh
sudo apt install ./TokenObservatory-<version>-linux-amd64.deb
```

The dashboard opens in your browser at <http://127.0.0.1:8765>. The first launch can take up to a minute.

## Using it

- **Conversations** lists your chats. Click one to see its details; click it again to go back to the combined view.
- **Tokens** and **Last activity** sort the list. Click again to reverse.
- Filter by provider (Claude Code or Codex) and time range, or search by name or model.
- **Export CSV** and **Export JSON** save what you're looking at.
- A saved copy is kept for each day. Pick a date next to the time range to look back.
- Click any day's bar in **Token activity** to see just that day. Click the date chip to go back.
- **Usage limits** shows how much of your Claude and Codex 5-hour and weekly quota you've used and when each resets. For live Claude numbers, add the Token Observatory status line to Claude Code once (see [INSTALL.md](INSTALL.md#live-claude-usage-limits)); otherwise they come from the Claude desktop app's last check.
- **Today's budget** compares today's tokens with a suggested daily amount that keeps you within your weekly limits. You can also set your own target.
- **Breakdown** splits usage by model or project; **Trends** compares today with your recent average and shows when you use tokens most.
- Turn on **Alerts** (top right) for a desktop notification when a chat's context is almost full or you pass your budget.

Numbers update after each reply finishes, not while it's being written.

Token Observatory keeps collecting in the background after you close the browser. Open the app again to bring the dashboard back. To stop it:

| Mac | Windows | Linux |
|---|---|---|
| `"/Applications/Token Observatory.app/Contents/MacOS/TokenObservatory" --stop` | `TokenObservatory-<version>-windows-x64.exe --stop` | `token-observatory --stop` |

## Screenshots

Screenshots use synthetic demo data.

**Overview:** combined usage, provider and time filters, and token activity.

![Dashboard overview with demo token totals, time filters, activity chart, and conversation list](docs/screenshots/overview.jpg)

**Conversation details:** context usage, a timeline, and the input, cache, output, and reasoning breakdown.

![Selected conversation showing context capacity, token activity, and detailed usage breakdown](docs/screenshots/conversation-details.jpg)

## Good to know

- Only chats saved on this computer appear. Chats on claude.ai or chatgpt.com don't.
- Claude Code doesn't record the size of its context window. Token Observatory assumes 1M tokens for Opus 5.5; you can set other models yourself (see [INSTALL.md](INSTALL.md#claude-context-window)).
- Values a tool doesn't record are shown as "Unreported", never guessed.

## More

- [INSTALL.md](INSTALL.md): installing from source, settings, updating, uninstalling, troubleshooting
- [DEVELOPMENT.md](DEVELOPMENT.md): how the numbers are calculated, data files, building and releasing
- [CONTRIBUTING.md](CONTRIBUTING.md): how to help
- [CHANGELOG.md](CHANGELOG.md): what changed in each version
- [LICENSE](LICENSE): MIT
