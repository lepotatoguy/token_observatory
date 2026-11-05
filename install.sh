#!/bin/sh
# Install the package and its private dependencies for the current user.
set -eu
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
python="${TOKEN_OBSERVATORY_PYTHON:-python3}"
command -v "$python" >/dev/null 2>&1 || { echo 'Python 3.10 or later is required.' >&2; exit 1; }
"$python" -c 'import sys; sys.exit(sys.version_info < (3, 10))' || { echo 'Python 3.10 or later is required. Set TOKEN_OBSERVATORY_PYTHON to a suitable interpreter.' >&2; exit 1; }
python=$("$python" -c 'import os, sys; print(os.path.realpath(sys._base_executable))')
# The floating widget needs Qt; it is optional so the dashboard stays small.
float=''
if [ "${TOKEN_OBSERVATORY_WITH_FLOAT:-0}" = "1" ]; then float=1; fi
case "${TOKEN_OBSERVATORY_PLATFORM:-$(uname -s)}" in
  Darwin)
    if [ -n "$float" ]; then
      "$python" "$root/build_app.py" --with-float
    else
      "$python" "$root/build_app.py"
    fi
    ;;
  Linux|linux)
    data="${XDG_DATA_HOME:-$HOME/.local/share}"
    app="$data/token-observatory/app"
    bin="$HOME/.local/bin"
    static="$root/frontend/dist"
    if [ ! -f "$static/index.html" ]; then static="$root/backend/static"; fi
    if [ -e "$root/.git" ] || [ ! -f "$static/index.html" ]; then
      (cd "$root/frontend" && npm ci && npm run build)
      static="$root/frontend/dist"
    fi
    mkdir -p "$data/token-observatory" "$bin" "$data/applications"
    stage=$(mktemp -d "$data/token-observatory/.install-XXXXXX")
    trap 'rm -rf "$stage"' EXIT HUP INT TERM
    "$python" - "$root/backend" "$stage/backend" <<'PY'
from pathlib import Path
import shutil
import sys
shutil.copytree(sys.argv[1], sys.argv[2],
                ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'static'))
PY
    cp -R "$static" "$stage/backend/static"
    cp "$root/launcher.py" "$root/pyproject.toml" "$root/logo.svg" "$stage/"
    "$python" -m venv --copies "$stage/.venv"
    "$stage/.venv/bin/python" -m pip install "$stage"
    if [ -n "$float" ]; then
      "$stage/.venv/bin/python" -m pip install "$stage[float]"
    fi
    "$python" - "$stage" <<'PY'
from pathlib import Path
import shutil
import sys
root = Path(sys.argv[1])
for generated in [root / 'build', *root.glob('*.egg-info')]:
    if generated.is_dir():
        shutil.rmtree(generated)
PY
    previous="$app.previous.$$"
    if [ -d "$app" ]; then mv "$app" "$previous"; fi
    if ! mv "$stage" "$app"; then
      if [ -d "$previous" ]; then mv "$previous" "$app"; fi
      exit 1
    fi
    if [ -d "$previous" ]; then rm -rf "$previous"; fi
    trap - EXIT HUP INT TERM
    cp "$root/scripts/token-observatory" "$bin/token-observatory"
    chmod +x "$bin/token-observatory"
    cat > "$data/applications/token-observatory.desktop" <<DESKTOP
[Desktop Entry]
Type=Application
Name=Token Observatory
Exec=$bin/token-observatory
Icon=$app/logo.svg
Terminal=false
Categories=Development;Utility;
DESKTOP
    echo "Installed: $bin/token-observatory"
    ;;
  *) echo 'Unsupported platform.' >&2; exit 1 ;;
esac
