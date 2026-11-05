"""Package a relocatable Python runtime without archive links."""
from pathlib import Path
import sys
import zipfile


def build(source, output):
    source = source.resolve()
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(source.rglob('*')):
            if path.is_file():
                if source not in path.resolve().parents:
                    raise ValueError(f'runtime link escapes its root: {path}')
                archive.write(path, path.relative_to(source))


if __name__ == '__main__':
    build(Path(sys.argv[1]), Path(sys.argv[2]))
