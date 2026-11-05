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


def test_source_release_supports_legacy_automatic_update(tmp_path):
    source = tmp_path / 'source-release'
    source.mkdir()
    (source / 'launcher.py').write_text('from backend.version import VERSION\n')
    (source / 'build_app.py').write_text('')
    (source / 'install.sh').write_text('#!/bin/sh\nset -eu\n')
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
    monkeypatch.setattr(bridge.subprocess, 'run', lambda command, check: shutil.copytree(fixture, Path(command[-1]) / fixture.name))
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
