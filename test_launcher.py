import json
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
            env = dict(os.environ, HOME=folder, XDG_DATA_HOME=str(Path(folder)/'data'), APPDATA=folder, TOKEN_OBSERVATORY_PRICE_UPDATES='0')
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

    def test_statusline_saves_claude_rate_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, HOME=folder, XDG_DATA_HOME=str(Path(folder)/'data'), APPDATA=folder, TOKEN_OBSERVATORY_PRICE_UPDATES='0')
            payload = json.dumps(dict(model=dict(display_name='Opus'), context_window=dict(used_percentage=12.4),
                rate_limits=dict(five_hour=dict(used_percentage=79, resets_at=4102444800), seven_day=dict(used_percentage=55.2, resets_at=4102444800))))
            shown = subprocess.run([sys.executable, str(ROOT/'launcher.py'), '--statusline'], input=payload, env=env,
                                   capture_output=True, text=True, timeout=30)
            self.assertEqual(shown.returncode, 0, shown.stderr)
            self.assertIn('5h 79%', shown.stdout)
            saved = json.loads(next(Path(folder).rglob('claude-rate-limits.json')).read_text())
            self.assertEqual((saved['five_hour']['used_percentage'], saved['seven_day']['used_percentage']), (79, 55.2))
            # A later status line without rate limits keeps the saved windows.
            subprocess.run([sys.executable, str(ROOT/'launcher.py'), '--statusline'], input='{}', env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(json.loads(next(Path(folder).rglob('claude-rate-limits.json')).read_text())['five_hour']['used_percentage'], 79)

    def test_install_statusline_adds_command_and_respects_existing(self):
        with tempfile.TemporaryDirectory() as folder:
            claude = Path(folder)/'claude'
            claude.mkdir()
            (claude/'settings.json').write_text(json.dumps(dict(theme='dark')))
            env = dict(os.environ, HOME=folder, CLAUDE_CONFIG_DIR=str(claude))
            run = lambda *a: subprocess.run([sys.executable, str(ROOT/'launcher.py'), *a], env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(run('--install-statusline').returncode, 0)
            settings = json.loads((claude/'settings.json').read_text())
            self.assertEqual(settings['theme'], 'dark')
            self.assertIn('--statusline', settings['statusLine']['command'])
            self.assertEqual(run('--uninstall-statusline').returncode, 0)
            self.assertNotIn('statusLine', json.loads((claude/'settings.json').read_text()))
            (claude/'settings.json').write_text(json.dumps(dict(statusLine=dict(type='command', command='my-line'))))
            self.assertNotEqual(run('--install-statusline').returncode, 0)
            self.assertEqual(json.loads((claude/'settings.json').read_text())['statusLine']['command'], 'my-line')

    def test_healthy_is_false_when_nothing_listens(self):
        self.assertFalse(healthy(f'http://127.0.0.1:{free_port()}'))


if __name__ == '__main__':
    unittest.main()
