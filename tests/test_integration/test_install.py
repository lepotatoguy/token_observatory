import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from backend.version import VERSION

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX source installer")

ROOT = Path(__file__).resolve().parents[2]


def test_source_installer_uses_versioned_base_python(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    shutil.copy2(ROOT / 'install.sh', source / 'install.sh')
    (source / 'build_app.py').write_text('')
    base = tmp_path / 'base'
    versioned = base / 'bin' / f'python{sys.version_info.major}.{sys.version_info.minor}'
    versioned.parent.mkdir(parents=True)
    marker = tmp_path / 'selected'
    versioned.write_text(f'#!{sys.executable}\nfrom pathlib import Path\nPath({str(marker)!r}).write_text("selected")\n')
    versioned.chmod(0o755)
    wrapper = tmp_path / 'venv-python'
    wrapper.write_text(
        f'#!{sys.executable}\nimport os, sys\n'
        f'if len(sys.argv) > 2 and sys.argv[1] == "-c" and "_base_executable" in sys.argv[2]:\n'
        f'    sys.base_prefix = {str(base)!r}\n'
        f'    sys._base_executable = {str(tmp_path / "unusable-python")!r}\n'
        f'    exec(sys.argv[2])\n'
        f'else:\n'
        f'    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])\n'
    )
    wrapper.chmod(0o755)
    env = dict(os.environ, TOKEN_OBSERVATORY_PLATFORM='Darwin', TOKEN_OBSERVATORY_PYTHON=str(wrapper))
    result = subprocess.run(['/bin/sh', str(source / 'install.sh')], env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == 'selected'


def fake_installer_python(path, stable=None):
    path.write_text(f'''#!{sys.executable}
import os, pathlib, sys
if len(sys.argv) > 2 and sys.argv[1] == '-c' and '_base_executable' in sys.argv[2]:
    print({str(stable or path)!r})
elif sys.argv[1:3] == ['-m', 'venv']:
    root = pathlib.Path(sys.argv[-1])
    (root / 'bin').mkdir(parents=True)
    python = root / 'bin/python'
    python.write_text('#!/bin/sh\\nif [ "$2" = "pip" ]; then exit "${{FAKE_INSTALL_FAIL:-0}}"; fi\\nexec "{sys.executable}" "$@"\\n')
    python.chmod(0o755)
else:
    os.execv({sys.executable!r}, [{sys.executable!r}, *sys.argv[1:]])
''')
    path.chmod(0o755)


@pytest.mark.parametrize('checkout', [False, True])
def test_linux_install_package_and_private_runtime(tmp_path, checkout):
    source, home = tmp_path / 'source', tmp_path / 'home'
    source.mkdir()
    home.mkdir()
    for name in ('install.sh', 'launcher.py', 'pyproject.toml', 'logo.svg'):
        shutil.copy2(ROOT / name, source / name)
    shutil.copytree(ROOT / 'backend', source / 'backend')
    shutil.copytree(ROOT / 'scripts', source / 'scripts')
    static = source / 'frontend/dist'
    static.mkdir(parents=True)
    (static / 'index.html').write_text('<h1>test</h1>')
    expected_html = '<h1>test</h1>'
    if checkout:
        (source / '.git').write_text('gitdir: /unused/worktree')
        expected_html = '<h1>changed source</h1>'
        (source / 'frontend/source.txt').write_text(expected_html)
    tools = tmp_path / 'tools'
    tools.mkdir()
    npm = tools / 'npm'
    npm.write_text(f'''#!{sys.executable}
from pathlib import Path
import sys
with Path('npm-calls').open('a') as log:
    log.write(' '.join(sys.argv[1:]) + '\\n')
if sys.argv[1:] == ['run', 'build']:
    Path('dist/index.html').write_text(Path('source.txt').read_text())
''')
    npm.chmod(0o755)
    interpreter = tmp_path / 'python'
    fake_installer_python(interpreter)
    env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / 'data'),
               TOKEN_OBSERVATORY_PLATFORM='Linux', TOKEN_OBSERVATORY_PYTHON=str(interpreter),
               PATH=str(tools) + os.pathsep + os.environ['PATH'])
    result = subprocess.run(['/bin/sh', str(source / 'install.sh')], env=env,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    app = home / 'data/token-observatory/app'
    assert (app / 'backend/app.py').exists()
    assert (app / 'backend/data/prices.json').exists()
    assert (app / 'backend/static/index.html').read_text() == expected_html
    if checkout:
        assert (source / 'frontend/npm-calls').read_text().splitlines() == ['ci', 'run build']
    else:
        assert not (source / 'frontend/npm-calls').exists()
    assert not (app / 'server.py').exists()
    assert not (app / 'backend/__pycache__').exists()
    assert not (app / 'build_app.py').exists()
    launcher = home / '.local/bin/token-observatory'
    assert os.access(launcher, os.X_OK)
    version = subprocess.run([str(launcher), '--version'], env=env, capture_output=True, text=True)
    assert version.returncode == 0, version.stderr
    assert f'Token Observatory {VERSION}' in version.stdout
    assert f'Exec={launcher}' in (home / 'data/applications/token-observatory.desktop').read_text()
    selected = app / '.venv/bin/python'
    fake_installer_python(selected, stable=interpreter)
    current_env = dict(env, TOKEN_OBSERVATORY_PYTHON=str(selected))
    reinstall = subprocess.run(['/bin/sh', str(source / 'install.sh')], env=current_env,
                               capture_output=True, text=True)
    assert reinstall.returncode == 0, reinstall.stderr
    marker = app / 'working-install'
    marker.write_text('preserve')
    fake_installer_python(selected, stable=interpreter)
    before = selected.read_bytes()
    failed = subprocess.run(['/bin/sh', str(source / 'install.sh')],
                            env=dict(current_env, FAKE_INSTALL_FAIL='1'), capture_output=True, text=True)
    assert failed.returncode != 0
    assert marker.read_text() == 'preserve'
    assert selected.read_bytes() == before
    assert not list(app.parent.glob('.install-*'))


def test_source_launcher_requires_private_runtime(tmp_path):
    script = tmp_path / 'bin/token-observatory'
    script.parent.mkdir()
    shutil.copy2(ROOT / 'scripts/token-observatory', script)
    result = subprocess.run(['/bin/sh', str(script)], env=dict(os.environ, HOME=str(tmp_path)),
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert 'private Python runtime missing' in result.stderr
