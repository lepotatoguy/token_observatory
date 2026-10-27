# PyInstaller spec for the standalone builds: a macOS .app, and one-file Linux and Windows executables.
# Run from the repository root: pyinstaller --noconfirm packaging/token_observatory.spec
import re
import sys
from pathlib import Path

root = Path(SPECPATH).parent
version = re.search(r"^VERSION = '([^']+)'", (root / 'launcher.py').read_text(), re.M).group(1)
assets = [(str(root / name), '.') for name in ('index.html', 'app.js', 'insights.js', 'updates.js', 'setup.js', 'theme.js', 'style.css', 'logo.svg', 'prices.json')]
icon = {'darwin': 'logo.icns', 'win32': 'logo.ico'}.get(sys.platform)
icon = str(root / 'packaging' / icon) if icon else None

a = Analysis([str(root / 'launcher.py')], pathex=[str(root)], datas=assets, hiddenimports=['server'])
pyz = PYZ(a.pure)

if sys.platform == 'darwin':
    exe = EXE(pyz, a.scripts, exclude_binaries=True, name='TokenObservatory', console=False, icon=icon)
    collected = COLLECT(exe, a.binaries, a.datas, name='TokenObservatory')
    app = BUNDLE(collected, name='Token Observatory.app', icon=icon,
                 bundle_identifier='local.tokenobservatory.dashboard', version=version,
                 # No Dock icon: the app starts the background collector, opens the browser and quits.
                 info_plist={'LSUIElement': True, 'CFBundleShortVersionString': version, 'CFBundleVersion': version})
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name='token-observatory',
              console=sys.platform != 'win32', icon=icon)
