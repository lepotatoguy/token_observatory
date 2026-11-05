# Token Observatory

See token usage for Claude Code, Codex, MiniMax and local LLMs (Ollama, LM Studio, llama.cpp) in a dashboard on your computer. It reads existing local logs and counts local API requests on a pass-through port. Chat content stays local. MiniMax token tracking uses local records. Account quota checks reuse an unexpired MiniMax Code file login or a Coding Plan API key configured in Providers. MiniMax Code owns login renewal; keychain logins and ambiguous multiple accounts require a Coding Plan key. Optional network requests fetch published prices and software updates.

The source uses a Flask and Pydantic backend in `backend/` and a React 18, TypeScript and Vite frontend in `frontend/`. Source development needs Python 3.10 or later and Node.js 20 or later. Packaged standalone releases bundle their runtime. See [development setup](DEVELOPMENT.md).

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
- **Providers** (left sidebar) turns tracking on or off for Claude Code, Codex, Ollama, LM Studio and llama.cpp. The first time you open the dashboard it asks which tools you use, with the ones it found already ticked.
- **Local LLMs:** chats made inside LM Studio are read automatically from its saved chat files. For API requests from other apps, point them at the counting port: Ollama `http://127.0.0.1:11435`, LM Studio `http://127.0.0.1:1235/v1`, or llama.cpp `http://127.0.0.1:8081/v1`. See [Local LLMs](INSTALL.md#local-llms).
- Filter by provider and time range, or search by name or model.
- **Export CSV** and **Export JSON** save what you're looking at.
- A saved copy is kept for each day. Pick a date next to the time range to look back.
- Click any day's bar in **Token activity** to see just that day. Click the date chip to go back.
- **Usage limits** shows how much of your enabled Claude and Codex 5-hour and weekly quota you've used and when each resets. Under each limit, a forecast says when you'll reach it at your recent pace (the last hour for the 5-hour limit, the last day for the weekly one), or how full it will be when it resets. When a limit you had used at least halfway resets, the card says so, and with **Alerts** on you also get a desktop notification. **Refresh** (top right) checks enabled providers for the current numbers, and the collector also checks every 5 minutes. Opening or reloading the dashboard checks too.
- **Floating widget** shows the same numbers for every enabled account in a small always-on-top pill on macOS, Windows and Linux: the model in use, the 5-hour session meter and the weekly meter, side by side. Drag it anywhere, double-click to open the dashboard, right-click for a menu. Start it with `launcher.py --float`; it needs the optional `float` extra (`pip install 'token-observatory[float]'`).
- **Today's budget** compares today's tokens with a suggested daily amount that keeps you within your weekly limits. The meter has a part for each enabled provider, sized by its suggested share, with a line per provider underneath. You can also set your own target.
- **Estimated cost** (top row) prices your tokens at published API list prices, per model. Anthropic's prices are downloaded about once a day; OpenAI and MiniMax use verified snapshots in `prices.json`. Local-provider usage counts as $0. Unreported prices count as $0* so totals stay numeric; the asterisk marks the fallback, and affected models appear in the card's tooltip. Known components still contribute when another component lacks a price.
- **Breakdown** splits usage by model or project. Each row has a meter split into input and output; click a name to see fresh input, cache read, cache write, output and cost, and click **Other** to list the models or projects grouped there. **Trends** compares today with your recent average and shows when you use tokens most.
- Turn on **Alerts** (top right) for a desktop notification when a chat's context is almost full, you pass a usage threshold or budget, or a usage limit resets.
- **Theme** (top right) switches between Auto (follows your system), Light and Dark.

- Optional **conversation hooks** (see [INSTALL.md](INSTALL.md#conversation-hooks)): near a reported usage limit, supported Claude Code or Codex hook events stop for that window, when their quota is reported; same-chat resumption is supported after reset; when its context passes 60%, it is asked to condense and continue.
- **Settings** groups providers, data sources, limit controls, appearance, notifications and dashboard defaults. Each provider has a warning percentage, a **5-hour hard limit (% used)**, and a **Weekly reserve (% remaining)**. A 3% weekly reserve stops work at 97% weekly usage. Either hard condition stops supported hook events; resetting one window does not clear the other. Warnings appear on the page and, with Alerts on, as desktop notifications. Event history retains metadata only, capped at 30 days, 1,000 events and 256 KiB.

- **Updates.** When a new version is out, the dashboard asks whether to update. **Update now** downloads it, checks it, installs it and reloads the page; **Not now** skips that version. Untick **Notify me about future updates** to stop asking; the link at the bottom right turns it back on. See [INSTALL.md](INSTALL.md#updates).

Numbers update after each reply finishes, not while it's being written.

Token Observatory keeps collecting in the background after you close the browser. Open the app again to bring the dashboard back. To stop it:

| Mac | Windows | Linux |
|---|---|---|
| `"/Applications/Token Observatory.app/Contents/MacOS/TokenObservatory" --stop` | `TokenObservatory-<version>-windows-x64.exe --stop` | `token-observatory --stop` |

## Screenshots

Screenshots use synthetic demo data (`python3 docs/screenshots/demo.py` serves it).

**Overview:** totals, provider and time filters for Claude Code, Codex, Ollama, LM Studio and llama.cpp, estimated cost, usage limits and today's budget.

![Dashboard overview with demo token totals, provider filters including local LLMs, estimated cost, usage limits and daily budget](docs/screenshots/overview.jpg)

**Usage limits and budget:** 5-hour and weekly limits for Claude Code and Codex with reset times and a forecast at your recent pace, today's budget split by tool, and token activity by day.

![Usage limits with forecasts, today's budget split by provider, and the daily token activity chart](docs/screenshots/limits-budget.jpg)

**Breakdown and trends:** usage by model or project with cache reuse, today against your 7-day average, and when in the week you use tokens.

![Breakdown by model with cache share, trends, weekday-by-hour heatmap, and the conversation list](docs/screenshots/breakdown-trends.jpg)

**Conversation details:** context usage, a timeline, and the input, cache, output and reasoning breakdown.

![Selected Claude Code conversation showing context capacity, token activity and detailed usage breakdown](docs/screenshots/conversation-details.jpg)

**Local LLMs:** Ollama, LM Studio and llama.cpp chats, each named by its first message.

![Ollama conversations filtered, with a selected chat showing its latest request and token breakdown](docs/screenshots/local-llm.jpg)

**Providers:** turn each tool on or off and see how to connect local servers, with live status. The same dialog opens on first run with the tools it found already ticked.

![Providers dialog listing Claude Code, Codex, Ollama, LM Studio and llama.cpp with connection steps and status](docs/screenshots/providers.jpg)

**Floating widget:** every enabled account's model, 5-hour session meter and weekly meter, in one always-on-top pill.

![Floating widget showing Claude Code and Codex session and weekly usage meters](docs/screenshots/float.jpg)

## Good to know

- Only chats saved on this computer appear. Chats on claude.ai or chatgpt.com don't.
- Claude Code doesn't record the size of its context window. Token Observatory assumes 1M tokens for the models Claude Code documents as 1M by default (Opus 4.7 and later, Sonnet 5 and later, Haiku 5.5); you can set other models yourself (see [INSTALL.md](INSTALL.md#claude-context-window)).
- Cost is an estimate at standard API list prices, not a bill: subscription plans, discounts, service-tier premiums and batch pricing aren't modelled. OpenAI rates use the published 272K input threshold. OpenAI cache-write retention is unavailable in these logs, so those write components use $0*. Local $0 excludes hardware and electricity costs. You can override prices in `config.json`.
- Values a tool doesn't record are shown as "Unreported", never guessed.

## More

- [INSTALL.md](INSTALL.md): installing from source, settings, updating, uninstalling, troubleshooting
- [DEVELOPMENT.md](DEVELOPMENT.md): how the numbers are calculated, data files, building and releasing
- [CONTRIBUTING.md](CONTRIBUTING.md): how to help
- [CHANGELOG.md](CHANGELOG.md): what changed in each version
- [LICENSE](LICENSE): MIT
