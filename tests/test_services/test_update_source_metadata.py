import pytest
import sys
from unittest.mock import patch

from backend.services.update_install import UpdateError, check_source_version
from backend.services import update_install


def test_rewrite_source_archive_uses_packaged_version_with_root_shim(tmp_path):
    (tmp_path / 'backend').mkdir()
    (tmp_path / 'backend' / 'version.py').write_text('VERSION = "1.4.0"\n')
    (tmp_path / 'launcher.py').write_text('from backend.launcher import main\n')
    check_source_version(tmp_path, '1.4.0')
    with pytest.raises(UpdateError, match='expected 2.0.0'):
        check_source_version(tmp_path, '2.0.0')


def test_source_linux_installer_receives_current_python(tmp_path):
    top = tmp_path / 'source'
    top.mkdir()
    (top / 'launcher.py').write_text("VERSION = '1.4.0'\n")
    archive = tmp_path / 'source.tar.gz'
    archive.write_bytes(b'synthetic archive')
    with patch.object(update_install, 'safe_extract', return_value=top), \
            patch.object(update_install.subprocess, 'run') as run:
        assert update_install.install_source(archive, '1.4.0', 'source-linux', ['restart']) == ('restart', ['restart'])
    assert run.call_args.args[0] == ['/bin/sh', str(top / 'install.sh')]
    assert run.call_args.kwargs['env']['TOKEN_OBSERVATORY_PYTHON'] == sys.executable
    assert run.call_args.kwargs['env']['TOKEN_OBSERVATORY_PLATFORM'] == 'Linux'
    assert not archive.exists()
