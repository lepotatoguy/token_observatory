import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from launcher import healthy

ROOT = Path(__file__).resolve().parent


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class LauncherTests(unittest.TestCase):
    def test_start_reuse_and_stop(self):
        with tempfile.TemporaryDirectory() as folder:
            port = free_port()
            url = f'http://127.0.0.1:{port}'
            env = dict(os.environ, HOME=folder, XDG_DATA_HOME=str(Path(folder)/'data'), APPDATA=folder)
            env.pop('CLAUDE_CONFIG_DIR', None)
            env.pop('CODEX_HOME', None)

            def launch(*args):
                return subprocess.run([sys.executable, str(ROOT/'launcher.py'), '--port', str(port), *args],
                                      env=env, capture_output=True, text=True, timeout=90)

            def log():
                found = list(Path(folder).rglob('service.log'))
                return found[0].read_text() if found else 'no service.log'
            try:
                started = launch('--no-open')
                self.assertEqual(started.returncode, 0, started.stderr + log())
                self.assertTrue(healthy(url))
                pid = next(Path(folder).rglob('collector.pid')).read_text()
                self.assertEqual(launch('--no-open').returncode, 0)
                self.assertEqual(next(Path(folder).rglob('collector.pid')).read_text(), pid)
                self.assertEqual(launch('--stop').returncode, 0)
                deadline = time.monotonic() + 10
                while healthy(url) and time.monotonic() < deadline:
                    time.sleep(0.1)
                self.assertFalse(healthy(url))
            finally:
                launch('--stop')

    def test_healthy_is_false_when_nothing_listens(self):
        self.assertFalse(healthy(f'http://127.0.0.1:{free_port()}'))


if __name__ == '__main__':
    unittest.main()
