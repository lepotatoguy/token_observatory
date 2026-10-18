import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


def run(script, home, *args):
    env = dict(os.environ, HOME=str(home), XDG_DATA_HOME=str(home / 'data'),
               TOKEN_OBSERVATORY_PLATFORM='linux')
    return subprocess.run(['/bin/sh', str(ROOT / script), *args], env=env,
                          capture_output=True, text=True, check=True)


class LinuxInstallTest(unittest.TestCase):
    def test_install_copies_runtime_and_writes_launchers(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            run('install.sh', home)
            app = home / 'data/token-observatory/app'
            self.assertTrue((app / 'server.py').is_file())
            self.assertTrue((app / 'index.html').is_file())
            self.assertFalse(any(app.glob('test_*.py')))
            self.assertFalse((app / 'build_app.py').exists())
            launcher = home / '.local/bin/token-observatory'
            self.assertTrue(os.access(launcher, os.X_OK))
            desktop = (home / 'data/applications/token-observatory.desktop').read_text()
            self.assertIn(f'Exec={launcher}', desktop)

    def test_uninstall_keeps_history_unless_purged(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            run('install.sh', home)
            history = home / 'data/token-observatory/history'
            history.mkdir()
            run('uninstall.sh', home)
            self.assertFalse((home / '.local/bin/token-observatory').exists())
            self.assertFalse((home / 'data/token-observatory/app').exists())
            self.assertFalse((home / 'data/applications/token-observatory.desktop').exists())
            self.assertTrue(history.is_dir())
            run('uninstall.sh', home, '--purge')
            self.assertFalse((home / 'data/token-observatory').exists())


if __name__ == '__main__':
    unittest.main()
