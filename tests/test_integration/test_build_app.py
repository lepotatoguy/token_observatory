from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import zipfile
import pytest
from unittest.mock import Mock

import build_app


def source_fixture(root):
    for name in build_app.APP_FILES + ['launch-app.sh']:
        target = root / name
        shutil.copy2(build_app.ROOT / name, target)
    (root / 'backend/data').mkdir(parents=True)
    (root / 'backend/__init__.py').write_text('')
    (root / 'backend/data/prices.json').write_text('{}')
    (root / 'backend/__pycache__').mkdir()
    (root / 'backend/__pycache__/cache.pyc').write_bytes(b'cache')
    (root / 'frontend/dist').mkdir(parents=True)
    (root / 'frontend/dist/index.html').write_text('<h1>dashboard</h1>')
    return root


@pytest.mark.skipif(sys.platform == "win32", reason="macOS source app uses POSIX runtime paths and symlinks")
def test_prepare_runtime_copies_package_assets_and_installs_private_deps(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    source_fixture(root)
    target = tmp_path / 'app'
    target.mkdir()
    calls = Mock()
    base = tmp_path / 'base/python3'
    base.parent.mkdir()
    base.write_text('synthetic interpreter')
    alias = tmp_path / 'python-alias'
    alias.symlink_to(base)
    monkeypatch.setattr(build_app.sys, '_base_executable', str(alias))
    monkeypatch.setattr(build_app, 'ROOT', root)
    monkeypatch.setattr(build_app.subprocess, 'run', calls)
    build_app.prepare_runtime(target)
    assert (target / 'backend/data/prices.json').exists()
    assert (target / 'backend/static/index.html').exists()
    assert not (target / 'backend/__pycache__').exists()
    assert calls.call_args_list[0].args[0] == [str(base), '-m', 'venv', '--copies', str(target / '.venv')]
    assert calls.call_args_list[1].args[0] == [str(target / '.venv/bin/python'), '-m', 'pip', 'install', str(target)]


@pytest.mark.parametrize('worktree', [False, True])
def test_checkout_rebuilds_existing_dist(tmp_path, monkeypatch, worktree):
    root = tmp_path / 'source'
    root.mkdir()
    source_fixture(root)
    if worktree:
        (root / '.git').write_text('gitdir: /unused/worktree')
    else:
        (root / '.git').mkdir()
    (root / 'frontend/source.txt').write_text('<h1>changed source</h1>')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command == ['npm', 'run', 'build']:
            (root / 'frontend/dist/index.html').write_text((root / 'frontend/source.txt').read_text())
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(build_app, 'ROOT', root)
    monkeypatch.setattr(build_app.subprocess, 'run', run)
    target = tmp_path / 'app'
    target.mkdir()
    build_app.prepare_runtime(target)
    assert calls[:2] == [['npm', 'ci'], ['npm', 'run', 'build']]
    assert (target / 'backend/static/index.html').read_text() == '<h1>changed source</h1>'


@pytest.mark.skipif(sys.platform == "win32", reason="macOS app executable permissions require POSIX")
def test_build_repeatedly_uses_only_temp_destination(tmp_path, monkeypatch):
    root = tmp_path / 'source'
    root.mkdir()
    source_fixture(root)
    destination = tmp_path / 'Applications/Token Observatory.app'
    monkeypatch.setattr(build_app, 'ROOT', root)
    monkeypatch.setattr(build_app, 'DESTINATION', destination)
    def fake_run(command, **kwargs):
        if command[0].endswith('iconutil'):
            Path(command[-1]).write_bytes(b'icnsfake')
        return subprocess.CompletedProcess(command, 0)
    monkeypatch.setattr(build_app.subprocess, 'run', fake_run)
    build_app.main()
    stale = destination / 'Contents/Resources/dashboard/server.py'
    stale.write_text('old')
    build_app.main()
    assert not stale.exists()
    assert (destination / 'Contents/MacOS/TokenObservatory').stat().st_mode & 0o111
    with (destination / 'Contents/Info.plist').open('rb') as file:
        assert plistlib.load(file)['CFBundleVersion'] == build_app.VERSION
    with zipfile.ZipFile(root / 'dist/Token Observatory.zip') as archive:
        assert archive.testzip() is None
        assert 'Token Observatory.app/Contents/Resources/dashboard/backend/static/index.html' in archive.namelist()
    assert list(tmp_path.rglob('*.app')) == [destination]
