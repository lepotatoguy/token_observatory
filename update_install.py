"""Replace the installed Token Observatory with a verified release download, then restart it.

- macos-app (release build): unzip with ditto next to the app, check its bundle ID and version, swap it in
  (the old app is kept until the new one is serving), clear quarantine, start the new collector.
- windows-exe: a running .exe can't replace itself, so a cmd helper waits for this process to exit,
  swaps the file and starts it again.
- linux-deb: needs root. Uses `pkexec dpkg -i` when pkexec exists; otherwise the verified package stays
  in the data folder and the page shows the command to run.
- source-app (build_app.py) and source-linux (install.sh): unpack the release's verified source archive
  and run its installer again.
- git checkouts and other copies are left alone; the page says what to run.
"""
import os
from pathlib import Path
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

from claude_statusline import read_json, write_json
from updater import UpdateError, fetch_verified

IDENTIFIER = 'local.tokenobservatory.dashboard'  # Same as build_app.py and the PyInstaller spec.
STAGING = '.token-observatory-update-'
STATE = 'update-state.json'
SUFFIX = {'macos-app': 'macos-arm64.zip', 'windows-exe': 'windows-x64.exe', 'linux-deb': 'linux-amd64.deb',
          'source-app': 'source.tar.gz', 'source-linux': 'source.tar.gz'}
SOURCE_APP = Path.home() / 'Applications/Token Observatory.app/Contents/Resources/dashboard'
INSTALLER_TIMEOUT = 600
undo_steps = []


def kind(frozen, system, root, data):
    """Which install this process runs from."""
    if frozen:
        return {'darwin': 'macos-app', 'win32': 'windows-exe'}.get(system, 'linux-deb' if system.startswith('linux') else 'unknown')
    root = Path(root).resolve()
    if (root / '.git').exists():
        return 'git'
    if system == 'darwin' and root == SOURCE_APP.resolve():
        return 'source-app'
    if system.startswith('linux') and root == (Path(data) / 'app').resolve():
        return 'source-linux'
    return 'unknown'


def install(release, install_kind, root, folder, endpoints, restart_command, report=lambda state, message: None):
    """Download, verify and install. Returns ('restart', command), ('exit', None) or ('manual', message)."""
    version = release['version']
    if install_kind == 'git':
        return 'manual', (f'This copy is a git checkout, so it is not changed automatically. Run: git -C "{root}" pull --ff-only, '
                          'then restart Token Observatory (and run ./install.sh again if you installed with it).')
    if install_kind not in SUFFIX or install_kind == 'linux-deb' and platform.machine() not in ('x86_64', 'AMD64', 'amd64'):
        return 'manual', f'This copy can\'t update itself. Download Token Observatory {version} from {release["url"]}'
    name = f'TokenObservatory-{version}-{SUFFIX[install_kind]}'
    report('downloading', f'Downloading and verifying {name}')
    path = fetch_verified(release, name, Path(folder), endpoints)
    report('installing', f'Checksum verified. Installing {version}')
    if install_kind == 'macos-app':
        return install_macos(path, version, restart_command, Path(folder))
    if install_kind == 'windows-exe':
        return install_windows(path, restart_command)
    if install_kind == 'linux-deb':
        return install_deb(path, restart_command)
    return install_source(path, version, install_kind, restart_command)


def install_macos(archive, version, command, folder):
    app = Path(sys.executable).resolve().parents[2]
    if app.suffix != '.app' or not os.access(app.parent, os.W_OK):
        return 'manual', f'Token Observatory can\'t write to {app.parent}. The verified download is {archive}; unzip it and replace {app}.'
    staging = Path(tempfile.mkdtemp(prefix=STAGING, dir=app.parent))
    previous = staging / 'previous.app'
    try:
        subprocess.run(['/usr/bin/ditto', '-x', '-k', str(archive), str(staging / 'new')], check=True, capture_output=True, timeout=INSTALLER_TIMEOUT)
        new = staging / 'new/Token Observatory.app'
        info = plistlib.loads((new / 'Contents/Info.plist').read_bytes())
        if info.get('CFBundleIdentifier') != IDENTIFIER or info.get('CFBundleShortVersionString') != version:
            raise UpdateError(f'the downloaded app is not Token Observatory {version}')
        subprocess.run(['/usr/bin/xattr', '-dr', 'com.apple.quarantine', str(new)], capture_output=True)
        os.rename(app, previous)
        try:
            os.rename(new, app)
        except OSError:
            os.rename(previous, app)
            raise
    except (OSError, ValueError, subprocess.SubprocessError, UpdateError) as error:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError(f'could not replace {app.name}: {error}') from error

    def swap_back():
        os.rename(app, staging / 'failed.app')
        os.rename(previous, app)
    undo_steps.append(swap_back)
    # The new collector deletes the old app once it is serving (see finish).
    write_json(folder / STATE, dict(version=version, cleanup=str(staging)))
    archive.unlink(missing_ok=True)
    return 'restart', command


def windows_script(target, new, pids, port):
    lines = ['@echo off', 'rem Token Observatory update: wait for the old program to exit, swap in the new one, start it.',
             'setlocal', 'set tries=0', ':wait', 'set /a tries+=1', 'if %tries% gtr 120 goto replace']
    lines += [f'tasklist /fi "PID eq {pid}" /nh 2>nul | find " {pid} " >nul && goto pause' for pid in pids]
    lines += ['goto replace', ':pause', 'ping -n 2 127.0.0.1 >nul', 'goto wait',
              ':replace', f'move /y "{target}" "{target}.old" >nul 2>&1 || goto retry',
              f'move /y "{new}" "{target}" >nul 2>&1 || move /y "{target}.old" "{target}" >nul 2>&1',
              f'del /f /q "{target}.old" >nul 2>&1', 'goto start',
              ':retry', 'set /a tries+=1', 'if %tries% gtr 180 goto start', 'ping -n 2 127.0.0.1 >nul', 'goto replace',
              ':start', f'start "" "{target}" --no-open --port {port}', 'del /f /q "%~f0" >nul 2>&1']
    return '\r\n'.join(lines) + '\r\n'


def install_windows(download, command):
    target = Path(sys.executable).resolve()
    if not os.access(target.parent, os.W_OK):
        return 'manual', f'Token Observatory can\'t write to {target.parent}. The verified download is {download}; replace {target} with it.'
    new = target.with_name(target.name + '.new')
    shutil.move(str(download), str(new))
    port = command[command.index('--port') + 1] if '--port' in command else '8765'
    script = Path(tempfile.gettempdir()) / f'token-observatory-update-{os.getpid()}.cmd'
    script.write_text(windows_script(target, new, [os.getpid(), os.getppid()], port), encoding='ascii', errors='replace')
    flags = getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0) | getattr(subprocess, 'CREATE_NO_WINDOW', 0)
    subprocess.Popen(['cmd.exe', '/d', '/c', str(script)], creationflags=flags, close_fds=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
    return 'exit', None


def install_deb(package, command):
    manual = ('manual', f'The verified package is saved. Install it with: sudo apt install "{package}" and then open Token Observatory again.')
    pkexec = shutil.which('pkexec')
    if not pkexec:
        return manual
    try:
        done = subprocess.run([pkexec, 'dpkg', '-i', str(package)], capture_output=True, text=True, timeout=INSTALLER_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return manual
    if done.returncode != 0:
        return manual
    package.unlink(missing_ok=True)
    return 'restart', command


def safe_extract(archive, destination):
    """Unpack a source archive of plain files and folders under one top folder; anything else is refused."""
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        for member in members:
            parts = Path(member.name).parts
            if member.name.startswith(('/', '\\')) or '..' in parts or not (member.isfile() or member.isdir()):
                raise UpdateError(f'unsafe entry in the source archive: {member.name}')
        tops = {Path(m.name).parts[0] for m in members if Path(m.name).parts}
        if len(tops) != 1:
            raise UpdateError('unexpected source archive layout')
        options = dict(filter='data') if hasattr(tarfile, 'data_filter') else {}
        tar.extractall(destination, members=members, **options)
    return destination / tops.pop()


def check_source_version(top, version):
    found = re.search(r"^VERSION = '([^']+)'", (top / 'launcher.py').read_text(encoding='utf-8'), re.M)
    if not found or found.group(1) != version:
        raise UpdateError(f'the source archive is version {found.group(1) if found else "unknown"}, expected {version}')


def install_source(archive, version, install_kind, command):
    with tempfile.TemporaryDirectory(prefix='token-observatory-source-') as temporary:
        top = safe_extract(archive, Path(temporary))
        check_source_version(top, version)
        if install_kind == 'source-app':
            installer, env = [sys.executable, '-I', str(top / 'build_app.py')], dict(os.environ)
        else:
            installer, env = ['/bin/sh', str(top / 'install.sh')], dict(os.environ, TOKEN_OBSERVATORY_PLATFORM='Linux')
        try:
            subprocess.run(installer, cwd=top, env=env, check=True, capture_output=True, text=True, timeout=INSTALLER_TIMEOUT)
        except subprocess.CalledProcessError as error:
            raise UpdateError(f'the installer failed: {(error.stderr or error.stdout or "").strip()[-300:]}') from error
        except (OSError, subprocess.SubprocessError) as error:
            raise UpdateError(f'the installer did not run: {error}') from error
    archive.unlink(missing_ok=True)
    return 'restart', command


def restart(command):
    """Replace this process with the new collector (same PID, so launchers and PID files still match)."""
    for stream in (sys.stdout, sys.stderr):
        if stream:
            stream.flush()
    os.execve(command[0], command, dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))


def undo():
    while undo_steps:
        try:
            undo_steps.pop()()
        except OSError as error:
            print(f'Could not restore the previous app: {error}', flush=True)


def finish(data_folder, current):
    """Called once the collector serves: delete the app kept from before a successful update."""
    state_file = Path(data_folder) / 'updates' / STATE
    state = read_json(state_file)
    if not state or state.get('version') != current:
        return
    cleanup = Path(state.get('cleanup') or '')
    if cleanup.name.startswith(STAGING):
        shutil.rmtree(cleanup, ignore_errors=True)
    state_file.unlink(missing_ok=True)
