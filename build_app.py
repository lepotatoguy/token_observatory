"""Install one macOS launcher and keep only its ZIP in the build directory."""
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
IDENTIFIER = 'local.tokenobservatory.dashboard'
DESTINATION = Path.home() / 'Applications/Token Observatory.app'
LSREGISTER = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'


def check_owned(path):
    if path.exists():
        with (path / 'Contents/Info.plist').open('rb') as source:
            if plistlib.load(source).get('CFBundleIdentifier') != IDENTIFIER:
                raise RuntimeError(f'Refusing to overwrite another application: {path}')


def main():
    legacy = ROOT / 'dist/Token Observatory.app'
    check_owned(legacy)
    check_owned(DESTINATION)
    with tempfile.TemporaryDirectory(prefix='token-observatory-') as temporary:
        temporary = Path(temporary)
        application = temporary / 'Token Observatory.app'
        contents = application / 'Contents'
        resources = contents / 'Resources/dashboard'
        executable = contents / 'MacOS/TokenObservatory'
        resources.mkdir(parents=True)
        executable.parent.mkdir(parents=True)
        for name in ['server.py', 'archive.py', 'codex_usage.py', 'index.html', 'app.js', 'style.css', 'logo.svg']:
            shutil.copy2(ROOT / name, resources / name)
        shutil.copy2(ROOT / 'launch-app.sh', executable)
        executable.chmod(0o755)
        master = temporary / 'logo.png'
        subprocess.run(['/usr/bin/sips', '-s', 'format', 'png', str(ROOT / 'logo.svg'), '--out', str(master)], check=True, capture_output=True)
        iconset = temporary / 'AppIcon.iconset'
        iconset.mkdir()
        for size in [16, 32, 128, 256, 512]:
            for scale in [1, 2]:
                pixels = str(size * scale)
                suffix = '@2x' if scale == 2 else ''
                output = iconset / f'icon_{size}x{size}{suffix}.png'
                subprocess.run(['/usr/bin/sips', '-z', pixels, pixels, str(master), '--out', str(output)], check=True, capture_output=True)
        icon = contents / 'Resources/AppIcon.icns'
        subprocess.run(['/usr/bin/iconutil', '-c', 'icns', str(iconset), '-o', str(icon)], check=True, capture_output=True)
        info = dict(CFBundleIdentifier=IDENTIFIER, CFBundleName='Token Observatory',
                    CFBundleDisplayName='Token Observatory', CFBundleExecutable='TokenObservatory',
                    CFBundlePackageType='APPL', CFBundleInfoDictionaryVersion='6.0',
                    CFBundleShortVersionString='1.2', CFBundleVersion='3',
                    CFBundleIconFile='AppIcon.icns', LSUIElement=True)
        with (contents / 'Info.plist').open('wb') as output:
            plistlib.dump(info, output)
        package = ROOT / 'dist/Token Observatory.zip'
        package.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(package, 'w', zipfile.ZIP_DEFLATED) as archive:
            for path in application.rglob('*'):
                if path.is_file():
                    archive.write(path, path.relative_to(temporary))
        DESTINATION.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(application, DESTINATION, dirs_exist_ok=True)
        # Unpacked build copies also appear in the macOS app catalog.
        if legacy.exists():
            subprocess.run([LSREGISTER, '-u', str(legacy)], check=True, capture_output=True)
            shutil.rmtree(legacy)
        os.utime(DESTINATION, None)
        subprocess.run([LSREGISTER, '-f', str(DESTINATION)], check=True, capture_output=True)
    assert (DESTINATION / 'Contents/MacOS/TokenObservatory').stat().st_mode & 0o111
    assert (DESTINATION / 'Contents/Resources/AppIcon.icns').read_bytes().startswith(b'icns')
    assert not legacy.exists()
    print(f'Built: {package}\nInstalled: {DESTINATION}')


if __name__ == '__main__':
    main()
