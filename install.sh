#!/bin/sh
# Install Token Observatory for the current user. No root, no packages.
# macOS: builds ~/Applications/Token Observatory.app.
# Linux: copies the dashboard to $XDG_DATA_HOME/token-observatory/app, adds
# ~/.local/bin/token-observatory and a desktop menu entry.
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
platform="${TOKEN_OBSERVATORY_PLATFORM:-$(uname -s)}"

command -v python3 >/dev/null 2>&1 || { echo "Python 3.9 or later is required (python3 not found)." >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' ||
  { echo "Python 3.9 or later is required (found $(python3 --version 2>&1))." >&2; exit 1; }

case "$platform" in
  Darwin)
    python3 "$root/build_app.py"
    echo "Open Token Observatory from ~/Applications, or run: open \"$HOME/Applications/Token Observatory.app\""
    ;;
  Linux|linux)
    data="${XDG_DATA_HOME:-$HOME/.local/share}"
    app="$data/token-observatory/app"
    bin="$HOME/.local/bin"
    # Replace the previous copy so removed modules do not linger.
    rm -rf "$app"
    mkdir -p "$app" "$bin" "$data/applications"
    for file in "$root"/*.py; do
      case "${file##*/}" in test_*|build_app.py) continue ;; esac
      cp "$file" "$app/"
    done
    cp "$root/index.html" "$root/app.js" "$root/insights.js" "$root/updates.js" "$root/setup.js" "$root/theme.js" "$root/style.css" "$root/logo.svg" "$root/prices.json" "$app/"
    cp "$root/scripts/token-observatory" "$bin/token-observatory"
    chmod 755 "$bin/token-observatory"
    cat > "$data/applications/token-observatory.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Token Observatory
Comment=Local token usage dashboard for Claude Code and Codex
Exec=$bin/token-observatory
Icon=$app/logo.svg
Terminal=false
Categories=Development;Utility;
DESKTOP
    echo "Installed: $bin/token-observatory"
    case ":$PATH:" in *":$bin:"*) ;; *) echo "Add $bin to your PATH to run token-observatory by name." ;; esac
    ;;
  *)
    echo "Unsupported platform: $platform. Run 'python3 server.py' from this folder instead." >&2
    exit 1
    ;;
esac
