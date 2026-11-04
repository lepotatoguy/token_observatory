#!/bin/sh
# Remove Token Observatory. Saved JSON history is kept unless --purge is given.
set -eu

platform="${TOKEN_OBSERVATORY_PLATFORM:-$(uname -s)}"
purge=false
[ "${1:-}" = "--purge" ] && purge=true

stop_source() {
  for pid_file in "$3"/collector*.pid; do
    [ -f "$pid_file" ] || continue
    filename=${pid_file##*/}
    case "$filename" in
      collector.pid) port=8765 ;;
      collector-*.pid) port=${filename#collector-}; port=${port%.pid} ;;
      *) continue ;;
    esac
    case "$port" in ''|*[!0-9]*) continue ;; esac
    "$1" "$2" --stop --port "$port" --data-dir "$3/history"
  done
}

case "$platform" in
  Darwin)
    bundle="$HOME/Applications/Token Observatory.app"
    support="$HOME/Library/Application Support/Token Observatory"
    if [ -d "$bundle" ]; then
      id=$(/usr/bin/defaults read "$bundle/Contents/Info" CFBundleIdentifier 2>/dev/null || true)
      if [ "$id" != "local.tokenobservatory.dashboard" ]; then
        echo "Refusing to remove $bundle: unexpected bundle identifier '$id'." >&2
        exit 1
      fi
      resources="$bundle/Contents/Resources/dashboard"
      if [ -x "$resources/.venv/bin/python" ]; then
        stop_source "$resources/.venv/bin/python" "$resources/launcher.py" "$support"
      elif [ -f "$resources/server.py" ]; then
        pkill -f "$resources/server.py" 2>/dev/null || true
      else
        "$bundle/Contents/MacOS/TokenObservatory" --stop
      fi
      /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$bundle" 2>/dev/null || true
      rm -rf "$bundle"
    fi
    ;;
  Linux|linux)
    data="${XDG_DATA_HOME:-$HOME/.local/share}"
    support="$data/token-observatory"
    if [ -x "$support/app/.venv/bin/python" ]; then
      stop_source "$support/app/.venv/bin/python" "$support/app/launcher.py" "$support"
    else
      pkill -f "$support/app/server.py" 2>/dev/null || true
    fi
    rm -rf "$support/app"
    rm -f "$HOME/.local/bin/token-observatory" "$data/applications/token-observatory.desktop"
    ;;
  *)
    echo "Unsupported platform: $platform." >&2
    exit 1
    ;;
esac

if $purge; then
  rm -rf "$support"
  echo "Removed Token Observatory and its saved history."
else
  echo "Removed Token Observatory. Saved history kept in: $support"
fi
