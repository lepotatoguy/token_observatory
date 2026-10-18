#!/bin/sh
# Remove Token Observatory. Saved JSON history is kept unless --purge is given.
set -eu

platform="${TOKEN_OBSERVATORY_PLATFORM:-$(uname -s)}"
purge=false
[ "${1:-}" = "--purge" ] && purge=true

case "$platform" in
  Darwin)
    bundle="$HOME/Applications/Token Observatory.app"
    support="$HOME/Library/Application Support/Token Observatory"
    pkill -f "$bundle/Contents/Resources/dashboard/server.py" 2>/dev/null || true
    if [ -d "$bundle" ]; then
      id=$(/usr/bin/defaults read "$bundle/Contents/Info" CFBundleIdentifier 2>/dev/null || true)
      if [ "$id" != "local.tokenobservatory.dashboard" ]; then
        echo "Refusing to remove $bundle: unexpected bundle identifier '$id'." >&2
        exit 1
      fi
      /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$bundle" 2>/dev/null || true
      rm -rf "$bundle"
    fi
    ;;
  Linux|linux)
    data="${XDG_DATA_HOME:-$HOME/.local/share}"
    support="$data/token-observatory"
    pkill -f "$support/app/server.py" 2>/dev/null || true
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
