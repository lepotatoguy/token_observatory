"""Build a source archive compatible with installed source updaters."""
import io
import re
import sys
import tarfile
from pathlib import Path


def build(source, archive, version, native):
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', version):
        raise ValueError('invalid release version')
    launcher = source / 'launcher.py'
    original = launcher.read_text(encoding='utf-8')
    marker = 'from backend.version import VERSION'
    if original.count(marker) != 1:
        raise ValueError('launcher version import is missing or ambiguous')
    contents = original.replace(marker, f"{marker}\nVERSION = '{version}'").encode()
    root = f'token_observatory-{version}'
    build_app = source / 'build_app.py'
    bootstrap = ("if __name__ == '__main__':\n"
                 "    import runpy, sys\n"
                 "    from pathlib import Path\n"
                 f"    if runpy.run_path(str(Path(__file__).with_name('legacy_macos_upgrade.py')))['upgrade_if_legacy']({version!r}):\n"
                 "        sys.exit(0)\n")
    build_contents = (bootstrap + build_app.read_text(encoding='utf-8')).encode()

    def include(info):
        if any(part.startswith('._') for part in Path(info.name).parts):
            return None
        if not (info.isfile() or info.isdir()):
            raise ValueError(f'unsupported archive entry: {info.name}')
        return info

    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(source, arcname=root, filter=lambda info: None if info.name in {f'{root}/launcher.py', f'{root}/build_app.py'} else include(info))
        info = tar.gettarinfo(str(launcher), arcname=f'{root}/launcher.py')
        info.size = len(contents)
        tar.addfile(info, io.BytesIO(contents))
        info = tar.gettarinfo(str(build_app), arcname=f'{root}/build_app.py')
        info.size = len(build_contents)
        tar.addfile(info, io.BytesIO(build_contents))
        tar.add(Path(__file__).with_name('legacy_macos_upgrade.py'), arcname=f'{root}/legacy_macos_upgrade.py')
        tar.add(native, arcname=f'{root}/legacy-macos-arm64.zip')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]))
