import re
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from backend.services import update_install


ROOT = Path(__file__).resolve().parents[2]


def test_source_release_supports_legacy_automatic_update(tmp_path):
    source = tmp_path / 'source-release'
    source.mkdir()
    (source / 'launcher.py').write_text('from backend.version import VERSION\n')
    (source / 'build_app.py').write_text('')
    (source / '._metadata').write_text('macOS metadata')
    native = tmp_path / 'native.zip'
    with zipfile.ZipFile(native, 'w') as bundle:
        bundle.writestr('fixture', 'native app')
    archive = tmp_path / 'source.tar.gz'
    subprocess.run([sys.executable, str(ROOT / 'packaging/build_source.py'),
                    str(source), str(archive), '1.5.0', str(native)], check=True)

    with tarfile.open(archive, 'r:gz') as tar:
        members = tar.getmembers()
        assert {Path(m.name).parts[0] for m in members} == {'token_observatory-1.5.0'}
        assert not any(part.startswith('._') for m in members for part in Path(m.name).parts)
        launcher = tar.extractfile('token_observatory-1.5.0/launcher.py').read().decode()
        assert re.search(r"^VERSION = '1\.5\.0'", launcher, re.M)
        assert tar.extractfile('token_observatory-1.5.0/legacy-macos-arm64.zip').read() == native.read_bytes()
        assert b'upgrade_if_legacy' in tar.extractfile('token_observatory-1.5.0/build_app.py').read()

    with patch.object(update_install.subprocess, 'run') as installer:
        assert update_install.install_source(archive, '1.5.0', 'source-app', ['restart']) == ('restart', ['restart'])
        assert Path(installer.call_args.args[0][-1]).name == 'build_app.py'
    assert not archive.exists()


def test_legacy_bridge_preserves_restart_arguments(tmp_path, monkeypatch):
    import importlib.util
    import plistlib
    import shutil

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
    executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > ' + str(output) + '\n')
    executable.chmod(0o755)
    (fixture / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': bridge.IDENTIFIER, 'CFBundleShortVersionString': '1.5.0'}))
    monkeypatch.setattr(bridge.Path, 'home', lambda: home)
    monkeypatch.setattr(bridge.sys, 'platform', 'darwin')
    monkeypatch.setattr(bridge.platform, 'machine', lambda: 'arm64')
    run = subprocess.run
    monkeypatch.setattr(bridge.subprocess, 'run', lambda command, check: shutil.copytree(fixture, Path(command[-1]) / fixture.name))
    assert bridge.upgrade_if_legacy('1.5.0')
    shim = app / 'Contents/Resources/dashboard/server.py'
    run([sys.executable, str(shim), '--port', '8876', '--data-dir', str(home / 'data')], check=True)
    assert output.read_text().splitlines() == ['--serve', '--port', '8876', '--data-dir', str(home / 'data')]
