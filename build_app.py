"""Build a relocatable macOS launcher and install it in the user's Applications folder."""
from pathlib import Path
import plistlib
import shutil

ROOT = Path(__file__).resolve().parent
IDENTIFIER = 'local.tokenobservatory.dashboard'
APP = ROOT / 'dist/Token Observatory.app'


def check_owned(path):
    if path.exists():
        with (path / 'Contents/Info.plist').open('rb') as source:
            if plistlib.load(source).get('CFBundleIdentifier') != IDENTIFIER:
                raise RuntimeError(f'Refusing to overwrite another application: {path}')


def main():
    check_owned(APP)
    contents = APP / 'Contents'
    resources = contents / 'Resources/dashboard'
    executable = contents / 'MacOS/TokenObservatory'
    resources.mkdir(parents=True, exist_ok=True)
    executable.parent.mkdir(parents=True, exist_ok=True)
    for name in ['server.py', 'archive.py', 'index.html', 'app.js', 'style.css']:
        shutil.copy2(ROOT / name, resources / name)
    shutil.copy2(ROOT / 'launch-app.sh', executable)
    executable.chmod(0o755)
    info = dict(CFBundleIdentifier=IDENTIFIER, CFBundleName='Token Observatory',
                CFBundleDisplayName='Token Observatory', CFBundleExecutable='TokenObservatory',
                CFBundlePackageType='APPL', CFBundleInfoDictionaryVersion='6.0',
                CFBundleShortVersionString='1.1', CFBundleVersion='2', LSUIElement=True)
    with (contents / 'Info.plist').open('wb') as output:
        plistlib.dump(info, output)
    destination = Path.home() / 'Applications/Token Observatory.app'
    check_owned(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(APP, destination, dirs_exist_ok=True)
    assert (destination / 'Contents/MacOS/TokenObservatory').stat().st_mode & 0o111
    assert (destination / 'Contents/Resources/dashboard/archive.py').exists()
    print(f'Built: {APP}\nInstalled: {destination}')


if __name__ == '__main__':
    main()
