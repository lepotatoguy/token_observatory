"""The floating widget runtime ships in every build instead of being an optional extra."""
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def test_pyside_is_a_core_dependency():
    project = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
    assert any(dep.startswith('PySide6-Essentials') for dep in project['dependencies'])
    # The old extra stays so existing `pip install '.[float]'` commands keep working.
    assert 'float' in project['optional-dependencies']


def test_release_build_keeps_qt():
    workflow = (ROOT / '.github/workflows/release.yml').read_text()
    assert 'pip uninstall' not in workflow
    assert 'PySide6' in workflow


def test_pyinstaller_spec_always_bundles_qt():
    spec = (ROOT / 'packaging/token_observatory.spec').read_text()
    assert 'except ImportError' not in spec
    assert 'backend.services.float_window' in spec


def test_deb_declares_qt_system_libraries():
    deb = (ROOT / 'packaging/build_deb.py').read_text()
    assert 'Depends:' in deb
    for library in ('libegl1', 'libopengl0', 'libxkbcommon-x11-0'):
        assert library in deb


def test_installers_no_longer_gate_the_widget():
    assert 'WITH_FLOAT' not in (ROOT / 'install.sh').read_text()
    assert 'float' not in (ROOT / 'build_app.py').read_text().split('def main')[0].lower().split('def prepare_runtime')[1]
