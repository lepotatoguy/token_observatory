"""Upgrade a legacy macOS source app to the bundled Apple silicon app."""
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
import tempfile

IDENTIFIER = 'local.tokenobservatory.dashboard'


def upgrade_if_legacy(version):
    app = Path.home() / 'Applications/Token Observatory.app'
    legacy = app / 'Contents/Resources/dashboard/server.py'
    arch = platform.machine().lower()
    if sys.platform != 'darwin' or arch not in ('arm64', 'x86_64', 'amd64') or not legacy.is_file():
        return False
    with (app / 'Contents/Info.plist').open('rb') as f:
        if plistlib.load(f).get('CFBundleIdentifier') != IDENTIFIER:
            raise RuntimeError('Refusing to replace an unrelated application')
    suffix = 'arm64' if arch == 'arm64' else 'x64'
    archive = Path(__file__).with_name(f'legacy-macos-{suffix}.zip')
    with tempfile.TemporaryDirectory(prefix='.token-observatory-upgrade-', dir=app.parent) as temporary:
        temporary = Path(temporary)
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(temporary / 'new')], check=True)
        new = temporary / 'new/Token Observatory.app'
        with (new / 'Contents/Info.plist').open('rb') as f:
            info = plistlib.load(f)
            if info.get('CFBundleIdentifier') != IDENTIFIER or info.get('CFBundleShortVersionString') != version:
                raise RuntimeError('The bundled application has an unexpected identity or version')
        executable = new / 'Contents/MacOS/TokenObservatory'
        if not executable.is_file():
            raise RuntimeError('The bundled application executable is missing')
        shim = new / 'Contents/Resources/dashboard/server.py'
        shim.parent.mkdir(parents=True, exist_ok=True)
        shim.write_text("import os, sys\nfrom pathlib import Path\napp = Path(__file__).resolve().parents[3]\nexe = str(app / 'Contents/MacOS/TokenObservatory')\nos.execv(exe, [exe, '--serve', *sys.argv[1:]])\n", encoding='utf-8')
        previous = temporary / 'previous.app'
        os.rename(app, previous)
        try:
            os.rename(new, app)
        except OSError:
            os.rename(previous, app)
            raise
        shutil.rmtree(previous)
    return True
