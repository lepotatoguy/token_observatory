#!/usr/bin/env python3
"""Package the standalone Linux executable as a .deb. Needs dpkg-deb (Debian or Ubuntu)."""
import argparse
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
NAME = 'token-observatory'
CONTROL = """Package: {name}
Version: {version}
Architecture: {arch}
Maintainer: Joyanta Mondal <mjoyanta.cs@gmail.com>
Section: devel
Priority: optional
Homepage: https://github.com/lepotatoguy/token_observatory
Description: Local token usage dashboard for Claude Code, Codex and local LLMs
 Reads the session logs Claude Code and Codex write on this machine, counts
 Ollama, LM Studio and llama.cpp requests through a loopback pass-through,
 and serves a loopback-only dashboard of token usage. No uploads or API keys.
"""
DESKTOP = """[Desktop Entry]
Type=Application
Name=Token Observatory
Comment=Local token usage dashboard for Claude Code, Codex and local LLMs
Exec=/usr/bin/{name}
Icon={name}
Terminal=false
Categories=Development;Utility;
"""


def build(binary, version, output):
    arch = subprocess.run(['dpkg', '--print-architecture'], check=True, capture_output=True, text=True).stdout.strip()
    with tempfile.TemporaryDirectory() as temporary:
        tree = Path(temporary) / NAME
        files = {
            f'usr/lib/{NAME}/{NAME}': Path(binary).read_bytes(),
            f'usr/share/applications/{NAME}.desktop': DESKTOP.format(name=NAME).encode(),
            f'usr/share/icons/hicolor/scalable/apps/{NAME}.svg': (ROOT / 'logo.svg').read_bytes(),
            f'usr/share/doc/{NAME}/copyright': (ROOT / 'LICENSE').read_bytes(),
            'DEBIAN/control': CONTROL.format(name=NAME, version=version, arch=arch).encode(),
        }
        for relative, content in files.items():
            path = tree / relative
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o755)
            path.write_bytes(content)
            path.chmod(0o644)
        (tree / f'usr/lib/{NAME}/{NAME}').chmod(0o755)
        (tree / 'usr/bin').mkdir(parents=True, mode=0o755)
        (tree / f'usr/bin/{NAME}').symlink_to(f'../lib/{NAME}/{NAME}')
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(['dpkg-deb', '--build', '--root-owner-group', str(tree), str(output)], check=True)
    print(f'Built: {output}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('binary', help='PyInstaller one-file executable')
    parser.add_argument('version')
    parser.add_argument('output')
    args = parser.parse_args()
    build(args.binary, args.version, args.output)
