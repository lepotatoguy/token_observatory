import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import update_install
import updater

REPO = updater.REPO


def release(version='1.3.0', **changes):
    base = f'https://github.com/{REPO}/releases/download/v{version}/'
    data = dict(tag_name=f'v{version}', name=f'Token Observatory v{version}', draft=False, prerelease=False,
                html_url=f'https://github.com/{REPO}/releases/tag/v{version}', published_at='2026-10-25T04:00:10Z',
                body="Intro\n\n## What's new\n\n### Added\n\n- Update prompt.\n\n## Downloads\n\n| table |",
                assets=[dict(name=name, browser_download_url=base + name, digest=None)
                        for name in ('SHA256SUMS.txt', f'TokenObservatory-{version}-macos-arm64.zip')])
    data.update(changes)
    return data


class VersionTests(unittest.TestCase):
    def test_parse_version_accepts_plain_releases_only(self):
        self.assertEqual(updater.parse_version('v1.2.10'), (1, 2, 10))
        self.assertEqual(updater.parse_version('1.2.3'), (1, 2, 3))
        for text in ('1.3.0-rc1', '1.3', 'latest', '', None, 3):
            self.assertIsNone(updater.parse_version(text))

    def test_is_newer_compares_numerically(self):
        self.assertTrue(updater.is_newer('1.2.10', '1.2.9'))
        self.assertTrue(updater.is_newer('v2.0.0', '1.9.9'))
        self.assertFalse(updater.is_newer('1.2.2', '1.2.2'))
        self.assertFalse(updater.is_newer('1.2.1', '1.2.2'))
        self.assertFalse(updater.is_newer('1.3.0-beta', '1.2.2'))


class ReleaseParsingTests(unittest.TestCase):
    def setUp(self):
        self.endpoints = updater.Endpoints({})

    def test_newer_release_is_parsed_with_its_notes_and_assets(self):
        found = updater.parse_release(release(), '1.2.2', self.endpoints)
        self.assertEqual(found['version'], '1.3.0')
        self.assertEqual(found['tag'], 'v1.3.0')
        self.assertEqual(found['notes'], '### Added\n\n- Update prompt.')
        self.assertEqual(found['url'], f'https://github.com/{REPO}/releases/tag/v1.3.0')
        self.assertEqual(sorted(found['assets']), ['SHA256SUMS.txt', 'TokenObservatory-1.3.0-macos-arm64.zip'])

    def test_drafts_prereleases_and_older_versions_are_ignored(self):
        for data in (release(draft=True), release(prerelease=True), release('1.2.2'), release('1.0.0'), release(tag_name='nightly'), [], None):
            self.assertIsNone(updater.parse_release(data, '1.2.2', self.endpoints))

    def test_foreign_asset_and_page_links_are_dropped(self):
        data = release()
        data['assets'].append(dict(name='TokenObservatory-1.3.0-windows-x64.exe', browser_download_url='https://evil.example/x.exe'))
        data['assets'].append(dict(name='other.zip', browser_download_url=f'https://github.com/someone/else/releases/download/v1.3.0/other.zip'))
        data['html_url'] = 'https://evil.example/notes'
        found = updater.parse_release(data, '1.2.2', self.endpoints)
        self.assertNotIn('TokenObservatory-1.3.0-windows-x64.exe', found['assets'])
        self.assertNotIn('other.zip', found['assets'])
        self.assertEqual(found['url'], f'https://github.com/{REPO}/releases/tag/v1.3.0')

    def test_test_server_override_is_loopback_only(self):
        local = updater.Endpoints({'TOKEN_OBSERVATORY_UPDATE_SERVER': 'http://127.0.0.1:9999'})
        self.assertEqual(local.api, f'http://127.0.0.1:9999/repos/{REPO}/releases/latest')
        self.assertTrue(local.allows('http://127.0.0.1:9999/file'))
        self.assertFalse(local.allows('https://github.com/x'))
        for value in ('http://evil.example:9999', 'file:///etc', 'http://127.0.0.1:9999/path'):
            self.assertEqual(updater.Endpoints({'TOKEN_OBSERVATORY_UPDATE_SERVER': value}).api, updater.API_URL)

    def test_redirects_stay_on_github_hosts(self):
        self.assertTrue(self.endpoints.allows('https://release-assets.githubusercontent.com/github-production-release-asset/1'))
        self.assertTrue(self.endpoints.allows('https://objects.githubusercontent.com/x'))
        self.assertFalse(self.endpoints.allows('http://objects.githubusercontent.com/x'))
        self.assertFalse(self.endpoints.allows('https://evil.example/x'))
        self.assertFalse(self.endpoints.allows('https://github.com.evil.example/x'))


class FakeClock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


class CheckAndPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.data = Path(self.folder.name)
        self.clock = FakeClock()
        self.calls = []
        self.answer = release()
        patcher = patch.dict(os.environ, {}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop('TOKEN_OBSERVATORY_UPDATE_CHECKS', None)
        os.environ.pop('TOKEN_OBSERVATORY_UPDATE_SERVER', None)

    def tearDown(self):
        self.folder.cleanup()

    def fetch(self, url):
        self.calls.append(url)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    def make(self, current='1.2.2'):
        return updater.Updates(self.data, current=current, fetch_json=self.fetch, clock=self.clock, kind='macos-app')

    def test_check_caches_the_latest_release_for_a_day(self):
        updates = self.make()
        updates.check()
        status = updates.status()
        self.assertEqual(status['latest']['version'], '1.3.0')
        self.assertTrue(status['prompt'])
        self.assertEqual(self.calls, [updater.API_URL])
        self.clock.now += 3600
        self.make().check()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.make().status()['latest']['version'], '1.3.0')
        self.clock.now += updater.CHECK_INTERVAL
        self.make().check()
        self.assertEqual(len(self.calls), 2)

    def test_no_prompt_when_latest_is_not_newer(self):
        self.answer = release('1.2.2')
        updates = self.make()
        updates.check()
        self.assertIsNone(updates.status()['latest'])
        self.assertFalse(updates.status()['prompt'])

    def test_cached_release_stops_prompting_after_upgrade(self):
        self.make().check()
        self.assertIsNone(self.make(current='1.3.0').status()['latest'])

    def test_failed_check_is_recorded_without_raising(self):
        self.answer = OSError('offline')
        updates = self.make()
        with patch('builtins.print') as printed:
            updates.check()
        self.assertIn('offline', updates.status()['error'])
        self.assertIsNone(updates.status()['latest'])
        self.assertTrue(printed.called)

    def test_environment_switch_disables_checks(self):
        os.environ['TOKEN_OBSERVATORY_UPDATE_CHECKS'] = '0'
        updates = self.make()
        updates.check()
        self.assertEqual(self.calls, [])
        self.assertFalse(updates.status()['checks'])

    def test_not_now_dismisses_only_that_version(self):
        updates = self.make()
        updates.check()
        updates.set_preferences(dict(dismiss='1.3.0'))
        self.assertFalse(self.make().status()['prompt'])
        self.assertEqual(self.make().status()['latest']['version'], '1.3.0')
        self.answer = release('1.4.0')
        self.clock.now += updater.CHECK_INTERVAL
        again = self.make()
        again.check()
        self.assertTrue(again.status()['prompt'])

    def test_turning_notifications_off_persists_and_stops_checks(self):
        updates = self.make()
        updates.check()
        updates.set_preferences(dict(notify=False))
        settings = json.loads((self.data / 'update-settings.json').read_text())
        self.assertEqual(settings['notify'], False)
        restarted = self.make()
        self.assertFalse(restarted.status()['notify'])
        self.assertFalse(restarted.status()['prompt'])
        self.clock.now += updater.CHECK_INTERVAL
        restarted.check()
        self.assertEqual(len(self.calls), 1)
        restarted.set_preferences(dict(notify=True), recheck=False)
        self.assertTrue(self.make().status()['notify'])
        self.assertTrue(self.make().status()['prompt'])

    def test_invalid_preferences_are_rejected(self):
        updates = self.make()
        for payload in (dict(notify='yes'), dict(dismiss='soon'), dict(other=1), [], dict()):
            with self.assertRaises(ValueError):
                updates.set_preferences(payload)
        self.assertFalse((self.data / 'update-settings.json').exists())

    def test_start_refuses_without_a_newer_release(self):
        self.answer = release('1.2.2')
        updates = self.make()
        updates.check()
        with self.assertRaises(ValueError):
            updates.start()


class Release(BaseHTTPRequestHandler):
    files = {}

    def do_GET(self):
        body = self.files.get(self.path)
        if body is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Release)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.endpoints = updater.Endpoints({'TOKEN_OBSERVATORY_UPDATE_SERVER': self.origin})
        self.folder = tempfile.TemporaryDirectory()
        self.payload = b'new build'
        self.name = 'TokenObservatory-1.3.0-macos-arm64.zip'
        prefix = f'/{REPO}/releases/download/v1.3.0/'
        Release.files = {prefix + self.name: self.payload}
        self.sums = prefix + 'SHA256SUMS.txt'
        data = release()
        for asset in data['assets']:
            asset['browser_download_url'] = self.origin + prefix + asset['name']
        self.release = updater.parse_release(data, '1.2.2', self.endpoints)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.folder.cleanup()

    def test_matching_checksum_keeps_the_download(self):
        Release.files[self.sums] = f'{hashlib.sha256(self.payload).hexdigest()}  {self.name}\n'.encode()
        path = updater.fetch_verified(self.release, self.name, Path(self.folder.name), self.endpoints)
        self.assertEqual(path.read_bytes(), self.payload)

    def test_checksum_mismatch_aborts_and_removes_the_file(self):
        Release.files[self.sums] = f'{"0" * 64}  {self.name}\n'.encode()
        with self.assertRaisesRegex(updater.UpdateError, 'checksum'):
            updater.fetch_verified(self.release, self.name, Path(self.folder.name), self.endpoints)
        self.assertEqual(list(Path(self.folder.name).iterdir()), [])

    def test_missing_checksum_entry_aborts(self):
        Release.files[self.sums] = b'abc  other-file\n'
        with self.assertRaisesRegex(updater.UpdateError, 'SHA256SUMS'):
            updater.fetch_verified(self.release, self.name, Path(self.folder.name), self.endpoints)

    def test_github_digest_mismatch_aborts(self):
        Release.files[self.sums] = f'{hashlib.sha256(self.payload).hexdigest()}  {self.name}\n'.encode()
        self.release['assets'][self.name]['digest'] = 'sha256:' + '1' * 64
        with self.assertRaisesRegex(updater.UpdateError, 'checksum'):
            updater.fetch_verified(self.release, self.name, Path(self.folder.name), self.endpoints)

    def test_asset_missing_from_release_aborts(self):
        with self.assertRaisesRegex(updater.UpdateError, 'not attached'):
            updater.fetch_verified(self.release, 'TokenObservatory-1.3.0-windows-x64.exe', Path(self.folder.name), self.endpoints)


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def test_install_kind_per_platform_and_layout(self):
        data = self.root / 'data'
        self.assertEqual(update_install.kind(True, 'darwin', self.root, data), 'macos-app')
        self.assertEqual(update_install.kind(True, 'win32', self.root, data), 'windows-exe')
        self.assertEqual(update_install.kind(True, 'linux', self.root, data), 'linux-deb')
        app = Path.home() / 'Applications/Token Observatory.app/Contents/Resources/dashboard'
        self.assertEqual(update_install.kind(False, 'darwin', app, data), 'source-app')
        self.assertEqual(update_install.kind(False, 'linux', data / 'app', data), 'source-linux')
        (self.root / '.git').mkdir()
        self.assertEqual(update_install.kind(False, 'darwin', self.root, data), 'git')
        self.assertEqual(update_install.kind(False, 'linux', self.root / 'elsewhere', data), 'unknown')

    def test_safe_extract_rejects_paths_outside_the_folder(self):
        archive = self.root / 'bad.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            info = tarfile.TarInfo('../escape.txt')
            info.size = 1
            tar.addfile(info, io.BytesIO(b'x'))
        with self.assertRaises(updater.UpdateError):
            update_install.safe_extract(archive, self.root / 'out')
        self.assertFalse((self.root / 'escape.txt').exists())

    def test_safe_extract_rejects_links(self):
        archive = self.root / 'link.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            info = tarfile.TarInfo('token_observatory-1.3.0/link')
            info.type = tarfile.SYMTYPE
            info.linkname = '/etc/passwd'
            tar.addfile(info)
        with self.assertRaises(updater.UpdateError):
            update_install.safe_extract(archive, self.root / 'out')

    def test_source_archive_version_must_match(self):
        archive = self.root / 'src.tar.gz'
        with tarfile.open(archive, 'w:gz') as tar:
            body = b"VERSION = '1.2.0'\n"
            info = tarfile.TarInfo('token_observatory-1.3.0/launcher.py')
            info.size = len(body)
            tar.addfile(info, io.BytesIO(body))
        top = update_install.safe_extract(archive, self.root / 'out')
        with self.assertRaisesRegex(updater.UpdateError, '1.2.0'):
            update_install.check_source_version(top, '1.3.0')

    def test_linux_without_pkexec_gives_the_command(self):
        package = self.root / 'TokenObservatory-1.3.0-linux-amd64.deb'
        package.write_bytes(b'deb')
        with patch('update_install.shutil.which', return_value=None):
            action, detail = update_install.install_deb(package, ['token-observatory', '--serve'])
        self.assertEqual(action, 'manual')
        self.assertIn(f'sudo apt install "{package}"', detail)

    def test_linux_with_pkexec_installs_then_restarts(self):
        package = self.root / 'p.deb'
        package.write_bytes(b'deb')
        calls = []

        def run(command, **_):
            calls.append(command)
            return update_install.subprocess.CompletedProcess(command, 0, '', '')
        with patch('update_install.shutil.which', return_value='/usr/bin/pkexec'), patch('update_install.subprocess.run', side_effect=run):
            action, detail = update_install.install_deb(package, ['token-observatory', '--serve'])
        self.assertEqual(calls, [['/usr/bin/pkexec', 'dpkg', '-i', str(package)]])
        self.assertEqual((action, detail), ('restart', ['token-observatory', '--serve']))

    def test_git_checkout_is_left_alone(self):
        action, detail = update_install.install(dict(version='1.3.0'), 'git', self.root, self.root, None, [])
        self.assertEqual(action, 'manual')
        self.assertIn('git -C', detail)

    def test_windows_helper_waits_replaces_and_relaunches(self):
        script = update_install.windows_script(r'C:\Apps\to.exe', r'C:\Apps\to.exe.new', [11, 22], 8765)
        self.assertIn('PID eq 11', script)
        self.assertIn('PID eq 22', script)
        self.assertIn('move /y "C:\\Apps\\to.exe.new" "C:\\Apps\\to.exe"', script)
        self.assertIn('start "" "C:\\Apps\\to.exe" --no-open --port 8765', script)


if __name__ == '__main__':
    unittest.main()
