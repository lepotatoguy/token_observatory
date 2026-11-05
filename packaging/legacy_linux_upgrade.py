"""Keep legacy Linux source updates and their restart path compatible."""
import os
from pathlib import Path, PurePosixPath
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

MARKER = '# Token Observatory legacy restart bridge\n'


def upgrade_if_legacy(root, version):
    if sys.platform != 'linux' or os.environ.get('TOKEN_OBSERVATORY_LEGACY_RUNNING') == '1':
        return False
    data = Path(os.environ.get('XDG_DATA_HOME', str(Path.home() / '.local/share'))) / 'token-observatory'
    app = data / 'app'
    old = app / 'server.py'
    if not old.is_file() or old.read_text(encoding='utf-8').startswith(MARKER):
        return False
    python = sys.executable
    if sys.version_info < (3, 12):
        arch = platform.machine().lower()
        arch = {'amd64': 'x86_64', 'arm64': 'aarch64'}.get(arch, arch)
        archive = root / ('legacy-linux-python-' + arch + '.zip')
        if not archive.is_file():
            raise RuntimeError('No bundled Python runtime for Linux architecture ' + arch)
        runtime = data / ('legacy-python-' + version + '-' + arch)
        if not (runtime / 'bin/python3').is_file():
            data.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='.runtime-', dir=data) as temp:
                stage = Path(temp) / 'runtime'
                stage.mkdir()
                with zipfile.ZipFile(archive) as zipped:
                    for item in zipped.infolist():
                        path = PurePosixPath(item.filename)
                        if path.is_absolute() or '..' in path.parts or not path.parts:
                            raise RuntimeError('Unsafe entry in bundled Python runtime')
                        if stat.S_ISLNK(item.external_attr >> 16):
                            raise RuntimeError('Unexpected link in bundled Python runtime')
                        zipped.extract(item, stage)
                        if not item.is_dir():
                            (stage / item.filename).chmod((item.external_attr >> 16) & 0o777)
                if not (stage / 'bin/python3').is_file():
                    raise RuntimeError('Bundled Python runtime is incomplete')
                if runtime.exists():
                    raise RuntimeError('Existing Python runtime is incomplete')
                os.rename(stage, runtime)
        python = str(runtime / 'bin/python3')
    env = dict(os.environ, TOKEN_OBSERVATORY_LEGACY_RUNNING='1', TOKEN_OBSERVATORY_PYTHON=python)
    subprocess.run(['/bin/sh', str(root / 'install.sh')], env=env, check=True)
    shim = app / 'server.py'
    shim.write_text(MARKER + "import os, sys\nfrom pathlib import Path\nroot = Path(__file__).resolve().parent\npython = str(root / '.venv/bin/python')\nlauncher = str(root / 'launcher.py')\nos.execv(python, [python, launcher, '--serve', *sys.argv[1:]])\n", encoding='utf-8')
    return True


if __name__ == '__main__':
    sys.exit(0 if upgrade_if_legacy(Path(__file__).resolve().parent, sys.argv[1]) else 3)
