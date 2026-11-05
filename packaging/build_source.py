"""Build a source archive compatible with installed source updaters."""
import io
import re
import sys
import tarfile
from pathlib import Path


def build(source, archive, version, native, intel, linux_x64, linux_arm):
    if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', version):
        raise ValueError('invalid release version')
    launcher = source / 'launcher.py'
    original = launcher.read_text(encoding='utf-8')
    marker = 'from backend.version import VERSION'
    if original.count(marker) != 1:
        raise ValueError('launcher version import is missing or ambiguous')
    contents = original.replace(marker, f"{marker}\nVERSION = '{version}'").encode()
    root = f'token_observatory-{version}'
    installer = source / 'install.sh'
    shell = installer.read_text(encoding='utf-8')
    old_python = 'python=$("$python" -c \'import os, sys; print(os.path.realpath(sys._base_executable))\')'
    new_python = 'python=$("$python" -c \'import os, sys; base = os.path.join(sys.base_prefix, "bin", "python%d.%d" % sys.version_info[:2]); print(os.path.realpath(base if os.path.isfile(base) else sys._base_executable))\')'
    if old_python in shell:
        shell = shell.replace(old_python, new_python, 1)
    elif new_python not in shell:
        raise ValueError('source installer has no expected Python selection')
    marker = 'set -eu\n'
    if shell.count(marker) != 1:
        raise ValueError('source installer does not have the expected entry point')
    linux_bootstrap = ("if [ \"${TOKEN_OBSERVATORY_LEGACY_RUNNING:-}\" != 1 ]; then\n"
                       "  if python3 \"$(dirname \"$0\")/legacy_linux_upgrade.py\" " + version + "; then exit 0; else result=$?; fi\n"
                       "  if [ \"$result\" -ne 3 ]; then exit \"$result\"; fi\nfi\n")
    install_contents = shell.replace(marker, marker + linux_bootstrap, 1).encode()
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
        tar.add(source, arcname=root, filter=lambda info: None if info.name in {f'{root}/launcher.py', f'{root}/build_app.py', f'{root}/install.sh'} else include(info))
        info = tar.gettarinfo(str(launcher), arcname=f'{root}/launcher.py')
        info.size = len(contents)
        tar.addfile(info, io.BytesIO(contents))
        info = tar.gettarinfo(str(build_app), arcname=f'{root}/build_app.py')
        info.size = len(build_contents)
        tar.addfile(info, io.BytesIO(build_contents))
        info = tar.gettarinfo(str(installer), arcname=f'{root}/install.sh')
        info.size = len(install_contents)
        tar.addfile(info, io.BytesIO(install_contents))
        tar.add(Path(__file__).with_name('legacy_macos_upgrade.py'), arcname=f'{root}/legacy_macos_upgrade.py')
        tar.add(Path(__file__).with_name('legacy_linux_upgrade.py'), arcname=f'{root}/legacy_linux_upgrade.py')
        tar.add(linux_x64, arcname=f'{root}/legacy-linux-python-x86_64.zip')
        tar.add(linux_arm, arcname=f'{root}/legacy-linux-python-aarch64.zip')
        tar.add(native, arcname=f'{root}/legacy-macos-arm64.zip')
        tar.add(intel, arcname=f'{root}/legacy-macos-x64.zip')


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5]), Path(sys.argv[6]), Path(sys.argv[7]))
