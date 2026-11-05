import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend.services import update_install


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('current_installer', [False, True])
def test_source_release_supports_legacy_automatic_update(tmp_path, current_installer):
    source = tmp_path / 'source-release'
    source.mkdir()
    (source / 'launcher.py').write_text('from backend.version import VERSION\n')
    (source / 'build_app.py').write_text('')
    installer = (ROOT / 'install.sh').read_text() if current_installer else "#!/bin/sh\nset -eu\npython=$(\"$python\" -c 'import os, sys; print(os.path.realpath(sys._base_executable))')\n"
    (source / 'install.sh').write_text(installer)
    (source / '._metadata').write_text('macOS metadata')
    native = tmp_path / 'native.zip'
    with zipfile.ZipFile(native, 'w') as bundle:
        bundle.writestr('fixture', 'native app')
    archive = tmp_path / 'source.tar.gz'
    subprocess.run([sys.executable, str(ROOT / 'packaging/build_source.py'),
                    str(source), str(archive), '1.5.0', str(native), str(native), str(native), str(native)], check=True)

    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        assert {Path(m.name).parts[0] for m in members} == {'token_observatory-1.5.0'}
        assert not any(part.startswith('._') for m in members for part in Path(m.name).parts)
        launcher = tar.extractfile('token_observatory-1.5.0/launcher.py').read().decode()
        assert re.search(r"^VERSION = '1\.5\.0'", launcher, re.M)
        assert tar.extractfile('token_observatory-1.5.0/legacy-macos-arm64.zip').read() == native.read_bytes()
        assert tar.extractfile('token_observatory-1.5.0/legacy-macos-x64.zip').read() == native.read_bytes()
        assert b'upgrade_if_legacy' in tar.extractfile('token_observatory-1.5.0/build_app.py').read()
        assert b'legacy_linux_upgrade.py' in tar.extractfile('token_observatory-1.5.0/install.sh').read()

    with patch.object(update_install.subprocess, 'run') as installer:
        assert update_install.install_source(archive, '1.5.0', 'source-app', ['restart']) == ('restart', ['restart'])
        assert Path(installer.call_args.args[0][-1]).name == 'build_app.py'
    assert not archive.exists()


@pytest.mark.skipif(sys.platform == 'win32', reason='the restart bridge uses a POSIX executable')
@pytest.mark.parametrize('machine', ['arm64', 'x86_64'])
def test_legacy_bridge_preserves_restart_arguments(tmp_path, monkeypatch, machine):
    import importlib.util
    import plistlib
    import shutil
    import shlex

    spec = importlib.util.spec_from_file_location('legacy_upgrade', ROOT / 'packaging/legacy_macos_upgrade.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    home = tmp_path / 'home'
    app = home / 'Applications/Token Observatory.app'
    legacy = app / 'Contents/Resources/dashboard/server.py'
    legacy.parent.mkdir(parents=True)
    legacy.write_text('old server')
    (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': bridge.IDENTIFIER}))
    fixture = tmp_path / 'fixture/Token Observatory.app'
    executable = fixture / 'Contents/MacOS/TokenObservatory'
    executable.parent.mkdir(parents=True)
    output = tmp_path / 'arguments'
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > ' + shlex.quote(str(output)) + '\n')
    executable.chmod(0o755)
    (fixture / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': bridge.IDENTIFIER, 'CFBundleShortVersionString': '1.5.0'}))
    monkeypatch.setattr(bridge.Path, 'home', lambda: home)
    monkeypatch.setattr(bridge.sys, 'platform', 'darwin')
    monkeypatch.setattr(bridge.platform, 'machine', lambda: machine)
    run = subprocess.run
    def run_bridge(command, **kwargs):
        if command[0] == '/usr/bin/ditto':
            shutil.copytree(fixture, Path(command[-1]) / fixture.name)
        else:
            assert command[:4] == ['/usr/bin/codesign', '--force', '--sign', '-']
    monkeypatch.setattr(bridge.subprocess, 'run', run_bridge)
    assert bridge.upgrade_if_legacy('1.5.0')
    shim = app / 'Contents/Resources/dashboard/server.py'
    run([sys.executable, str(shim), '--port', '8876', '--data-dir', str(home / 'data')], check=True)
    assert output.read_text().splitlines() == ['--serve', '--port', '8876', '--data-dir', str(home / 'data')]


@pytest.mark.parametrize(('machine', 'suffix'), [('arm64', 'macos-arm64.zip'), ('x86_64', 'macos-x64.zip')])
def test_macos_updater_downloads_matching_architecture(tmp_path, monkeypatch, machine, suffix):
    monkeypatch.setattr(update_install.platform, 'machine', lambda: machine)
    with patch.object(update_install, 'fetch_verified', return_value=tmp_path / 'archive') as fetch, \
         patch.object(update_install, 'install_macos', return_value=('restart', [])):
        update_install.install({'version': '1.5.0'}, 'macos-app', tmp_path, tmp_path, None, [])
    assert fetch.call_args.args[1] == f'TokenObservatory-1.5.0-{suffix}'


@pytest.mark.skipif(sys.platform == 'win32', reason='the legacy Linux installer uses POSIX executables')
def test_legacy_linux_restart_keeps_arguments(tmp_path, monkeypatch):
    import importlib.util
    import shlex

    spec = importlib.util.spec_from_file_location('linux_upgrade', ROOT / 'packaging/legacy_linux_upgrade.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    home = tmp_path / 'home'
    app = home / 'share/token-observatory/app'
    app.mkdir(parents=True)
    (app / 'server.py').write_text('old server')
    monkeypatch.setenv('XDG_DATA_HOME', str(home / 'share'))
    monkeypatch.delenv('TOKEN_OBSERVATORY_LEGACY_RUNNING', raising=False)
    monkeypatch.setattr(bridge.sys, 'platform', 'linux')
    output = tmp_path / 'args'
    run = subprocess.run

    def install(command, env, check):
        assert env['TOKEN_OBSERVATORY_LEGACY_RUNNING'] == '1'
        python = app / '.venv/bin/python'
        python.parent.mkdir(parents=True)
        python.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > ' + shlex.quote(str(output)) + '\n')
        python.chmod(0o755)
        (app / 'launcher.py').write_text('')

    monkeypatch.setattr(bridge.subprocess, 'run', install)
    assert bridge.upgrade_if_legacy(tmp_path, '1.5.0')
    run([sys.executable, str(app / 'server.py'), '--port', '8876'], check=True)
    assert output.read_text().splitlines() == [str(app / 'launcher.py'), '--serve', '--port', '8876']
    assert not bridge.upgrade_if_legacy(tmp_path, '1.5.0')


def test_legacy_linux_rejects_unsafe_runtime_without_replacing_app(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location('linux_upgrade_safe', ROOT / 'packaging/legacy_linux_upgrade.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    app = tmp_path / 'data/token-observatory/app'
    app.mkdir(parents=True)
    old = app / 'server.py'
    old.write_text('original')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path / 'data'))
    monkeypatch.delenv('TOKEN_OBSERVATORY_LEGACY_RUNNING', raising=False)
    monkeypatch.setattr(bridge.platform, 'machine', lambda: 'x86_64')
    with zipfile.ZipFile(tmp_path / 'legacy-linux-python-x86_64.zip', 'w') as archive:
        archive.writestr('../outside', 'unsafe')
    with patch.object(bridge.sys, 'platform', 'linux'), patch.object(bridge.sys, 'version_info', (3, 9)):
        with pytest.raises(RuntimeError, match='Unsafe entry'):
            bridge.upgrade_if_legacy(tmp_path, '1.5.0')
    assert old.read_text() == 'original'
    assert not (tmp_path / 'data/token-observatory/outside').exists()


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX runtime permissions require POSIX')
@pytest.mark.parametrize('version', [(3, 9), (3, 10), (3, 11)])
def test_legacy_linux_uses_supported_bundled_runtime(tmp_path, monkeypatch, version):
    import importlib.util
    import stat

    spec = importlib.util.spec_from_file_location('linux_upgrade_python39', ROOT / 'packaging/legacy_linux_upgrade.py')
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    data = tmp_path / 'data'
    app = data / 'token-observatory/app'
    app.mkdir(parents=True)
    (app / 'server.py').write_text('legacy server')
    monkeypatch.setenv('XDG_DATA_HOME', str(data))
    monkeypatch.delenv('TOKEN_OBSERVATORY_LEGACY_RUNNING', raising=False)
    monkeypatch.setattr(bridge.platform, 'machine', lambda: 'x86_64')
    info = zipfile.ZipInfo('bin/python3')
    info.external_attr = (stat.S_IFREG | 0o755) << 16
    with zipfile.ZipFile(tmp_path / 'legacy-linux-python-x86_64.zip', 'w') as archive:
        archive.writestr(info, b'python fixture')
    calls = []
    def install(command, env, check):
        calls.append(env['TOKEN_OBSERVATORY_PYTHON'])
    monkeypatch.setattr(bridge.subprocess, 'run', install)
    with patch.object(bridge.sys, 'platform', 'linux'), patch.object(bridge.sys, 'version_info', version):
        assert bridge.upgrade_if_legacy(tmp_path, '1.5.0')
    runtime = data / 'token-observatory/legacy-python-1.5.0-x86_64/bin/python3'
    assert calls == [str(runtime)]
    assert runtime.read_bytes() == b'python fixture'
    assert runtime.stat().st_mode & 0o111


def test_windows_update_helper_keeps_unicode_paths_in_environment(tmp_path, monkeypatch):
    target = tmp_path / 'München' / 'TokenObservatory.exe'
    target.parent.mkdir()
    target.write_bytes(b'old')
    download = tmp_path / 'download.exe'
    download.write_bytes(b'new')
    monkeypatch.setattr(update_install.sys, 'executable', str(target))
    with patch.object(update_install.subprocess, 'Popen') as process:
        assert update_install.install_windows(download, ['--port', '8765']) == ('exit', None)
    env = process.call_args.kwargs['env']
    assert env['TOKEN_OBSERVATORY_UPDATE_TARGET'] == str(target)
    assert env['TOKEN_OBSERVATORY_UPDATE_NEW'] == str(target) + '.new'
    script = Path(process.call_args.args[0][-1]).read_text(encoding='ascii')
    assert str(target) not in script
    assert '%TOKEN_OBSERVATORY_UPDATE_TARGET%' in script


@pytest.mark.skipif(sys.platform != 'win32', reason='requires the Windows command interpreter')
def test_windows_helper_replaces_unicode_path(tmp_path):
    import os
    import time

    folder = tmp_path / 'München & 100%'
    folder.mkdir()
    target = folder / 'app.cmd'
    replacement = folder / 'app.cmd.new'
    marker = tmp_path / 'started.txt'
    target.write_text('@echo off\r\nexit /b 1\r\n', encoding='ascii')
    replacement.write_text('@echo off\r\necho started > "%TOKEN_OBSERVATORY_TEST_MARKER%"\r\n', encoding='ascii')
    helper = tmp_path / 'helper.cmd'
    helper.write_text(update_install.windows_script([], 8765), encoding='ascii')
    env = dict(os.environ, TOKEN_OBSERVATORY_UPDATE_TARGET=str(target),
               TOKEN_OBSERVATORY_UPDATE_NEW=str(replacement), TOKEN_OBSERVATORY_TEST_MARKER=str(marker))
    completed = subprocess.run(['cmd.exe', '/d', '/v:off', '/c', str(helper)], env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert marker.exists(), (completed.returncode, list(folder.iterdir()))
    assert marker.read_text().strip() == 'started'
    assert target.read_text(encoding='ascii').startswith('@echo off\necho started')
