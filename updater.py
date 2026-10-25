"""Check GitHub for a newer Token Observatory release and keep the update prompt settings.

The collector asks the public releases API at start and at most once a day (no sign-in, nothing sent
but the request). The answer is cached as update-check.json in the data folder; the dashboard's
"Notify me" checkbox and "Not now" choice are kept in update-settings.json. Downloads are accepted
only from this repository's release on github.com (redirects may go to GitHub's asset hosts) and must
match SHA256SUMS.txt from the same release. update_install.py replaces the app.
TOKEN_OBSERVATORY_UPDATE_CHECKS=0 turns checks off (the tests use it). TOKEN_OBSERVATORY_UPDATE_SERVER
points the checks at a loopback test server and is for testing only.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit

from claude_statusline import read_json, write_json
from launcher import VERSION

REPO = 'lepotatoguy/token_observatory'
API_URL = f'https://api.github.com/repos/{REPO}/releases/latest'
GITHUB_HOSTS = {'github.com', 'objects.githubusercontent.com', 'release-assets.githubusercontent.com', 'codeload.github.com'}
CHECK_INTERVAL = 24 * 3600
START_INTERVAL = 3600  # A restart checks again only when the last check is older than this.
TIMEOUT = 10
MAX_DOWNLOAD = 300_000_000
NOTES_LIMIT = 1500
SUMS = 'SHA256SUMS.txt'
VERSION_PATTERN = re.compile(r'v?(\d+)\.(\d+)\.(\d+)')


class UpdateError(Exception):
    pass


def parse_version(text):
    match = VERSION_PATTERN.fullmatch(text) if isinstance(text, str) else None
    return tuple(int(part) for part in match.groups()) if match else None


def is_newer(candidate, current):
    found, have = parse_version(candidate), parse_version(current)
    return bool(found and have and found > have)


class Endpoints:
    """Where to ask and what may be downloaded: GitHub, or a loopback server set for testing."""

    def __init__(self, environ=os.environ):
        self.local = None
        override = urlsplit(environ.get('TOKEN_OBSERVATORY_UPDATE_SERVER', ''))
        if override.scheme in ('http', 'https') and override.hostname in ('127.0.0.1', 'localhost') and override.path in ('', '/'):
            self.local = f'{override.scheme}://{override.netloc}'
        self.api = f'{self.local}/repos/{REPO}/releases/latest' if self.local else API_URL

    def release_prefix(self, tag):
        return f'{self.local or "https://github.com"}/{REPO}/releases/download/{tag}/'

    def allows(self, url):
        parts = urlsplit(url)
        if self.local:
            return f'{parts.scheme}://{parts.netloc}' == self.local
        return parts.scheme == 'https' and parts.hostname in GITHUB_HOSTS and parts.port is None

    def opener(self):
        allows = self.allows

        class Redirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, request, fp, code, message, headers, url):
                if not allows(url):
                    raise urllib.error.URLError(f'redirect to {urlsplit(url).hostname} refused')
                return super().redirect_request(request, fp, code, message, headers, url)
        handlers = [Redirect()] + ([urllib.request.ProxyHandler({})] if self.local else [])
        return urllib.request.build_opener(*handlers)


def request(url):
    return urllib.request.Request(url, headers={'User-Agent': f'token-observatory/{VERSION}', 'Accept': 'application/vnd.github+json',
                                                'X-GitHub-Api-Version': '2022-11-28'})


def fetch_json(url, endpoints=None):
    with (endpoints or Endpoints()).opener().open(request(url), timeout=TIMEOUT) as response:
        return json.loads(response.read(1_000_000).decode('utf-8'))


def release_notes(body):
    """The "What's new" section of the release notes, or their start."""
    text = body if isinstance(body, str) else ''
    match = re.search(r"^## What's new\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return (match.group(1) if match else text).strip()[:NOTES_LIMIT]


def parse_release(data, current, endpoints):
    """The release when it is a published, non-prerelease version newer than current; otherwise None."""
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = data.get('tag_name')
    if not is_newer(tag, current):
        return None
    prefix = endpoints.release_prefix(tag)
    assets = {}
    for asset in data.get('assets') or []:
        if isinstance(asset, dict) and isinstance(asset.get('name'), str) and asset.get('browser_download_url') == prefix + asset['name']:
            assets[asset['name']] = dict(url=asset['browser_download_url'], digest=asset.get('digest'))
    page = f'https://github.com/{REPO}/releases/tag/{tag}'
    url = data.get('html_url') if data.get('html_url') == page else page
    return dict(version='.'.join(map(str, parse_version(tag))), tag=tag, url=url, notes=release_notes(data.get('body')),
                published_at=data.get('published_at'), assets=assets)


def download(url, path, endpoints):
    """Stream url to path and return its SHA-256."""
    if not endpoints.allows(url):
        raise UpdateError(f'Refusing to download from {url}')
    digest, size = hashlib.sha256(), 0
    with endpoints.opener().open(request(url), timeout=60) as response, open(path, 'wb') as output:
        while chunk := response.read(1 << 20):
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise UpdateError(f'{path.name} is larger than expected')
            digest.update(chunk)
            output.write(chunk)
    return digest.hexdigest()


def parse_sums(text):
    sums = {}
    for line in text.splitlines():
        parts = line.strip().split(maxsplit=1)
        if len(parts) == 2 and re.fullmatch(r'[0-9a-f]{64}', parts[0].lower()):
            sums[parts[1].lstrip('*')] = parts[0].lower()
    return sums


def fetch_verified(release, name, folder, endpoints):
    """Download one release asset into folder and check it against SHA256SUMS.txt. A mismatch deletes it."""
    if name not in release['assets'] or SUMS not in release['assets']:
        raise UpdateError(f'{name} is not attached to release {release["tag"]}')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    sums_path, path = folder / SUMS, folder / name
    try:
        download(release['assets'][SUMS]['url'], sums_path, endpoints)
        expected = parse_sums(sums_path.read_text(encoding='utf-8', errors='replace')).get(name)
        if not expected:
            raise UpdateError(f'{name} is not listed in {SUMS}')
        actual = download(release['assets'][name]['url'], path, endpoints)
        digest = release['assets'][name].get('digest')
        if actual != expected or (isinstance(digest, str) and digest.startswith('sha256:') and digest[7:].lower() != actual):
            raise UpdateError(f'{name} failed the checksum check; the download was deleted')
        return path
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        sums_path.unlink(missing_ok=True)


def checks_enabled():
    return os.environ.get('TOKEN_OBSERVATORY_UPDATE_CHECKS') != '0'


def start_thread(target):
    threading.Thread(target=target, daemon=True).start()


class Updates:
    """Update check results, prompt settings and the progress of a running update."""

    def __init__(self, data_folder, current=VERSION, fetch_json=fetch_json, clock=time.time, kind=None, runner=start_thread,
                 installer=None, root=None, restart_command=None, before_restart=lambda: None, stop_server=lambda: None):
        self.folder = Path(data_folder)
        self.check_file, self.settings_file = self.folder / 'update-check.json', self.folder / 'update-settings.json'
        self.current, self.fetch, self.clock, self.runner = current, fetch_json, clock, runner
        self.kind, self.installer, self.root = kind, installer, root
        self.restart_command, self.before_restart, self.stop_server = restart_command or [], before_restart, stop_server
        self.endpoints = Endpoints()
        self.lock = threading.Lock()
        self.progress = dict(state='idle', message='')

    def settings(self):
        saved = read_json(self.settings_file)
        return dict(notify=saved.get('notify') is not False, dismissed=saved.get('dismissed'))

    def check(self, max_age=CHECK_INTERVAL):
        """Ask GitHub for the latest release unless checks are off or the cached answer is recent."""
        if not checks_enabled() or not self.settings()['notify']:
            return
        if self.clock() - (read_json(self.check_file).get('checked_at') or 0) < max_age:
            return
        try:
            answer, error = self.fetch(self.endpoints.api), None
            found = parse_release(answer, '0.0.0', self.endpoints)
        except (OSError, ValueError) as failure:
            found, error = None, f'Update check failed: {failure}'
            print(error, flush=True)
        with self.lock:
            write_json(self.check_file, dict(checked_at=self.clock(), latest=found, error=error))

    def latest(self):
        found = read_json(self.check_file).get('latest')
        return found if isinstance(found, dict) and is_newer(found.get('version'), self.current) else None

    def status(self):
        settings, cached, latest = self.settings(), read_json(self.check_file), self.latest()
        public = {k: latest[k] for k in ('version', 'url', 'notes', 'published_at')} if latest else None
        with self.lock:
            progress = dict(self.progress)
        return dict(current=self.current, install=self.kind, checks=checks_enabled(), notify=settings['notify'],
                    dismissed=settings['dismissed'], latest=public, checked_at=cached.get('checked_at'), error=cached.get('error'),
                    prompt=bool(public and settings['notify'] and settings['dismissed'] != public['version']), progress=progress)

    def set_preferences(self, payload, recheck=True):
        """Save {"notify": bool} and/or {"dismiss": "x.y.z"} from the dashboard."""
        if not isinstance(payload, dict) or not payload or set(payload) - {'notify', 'dismiss'}:
            raise ValueError('Expected "notify" and/or "dismiss"')
        if 'notify' in payload and not isinstance(payload['notify'], bool):
            raise ValueError('"notify" must be true or false')
        if 'dismiss' in payload and parse_version(payload['dismiss']) is None:
            raise ValueError('"dismiss" must be a version like 1.2.3')
        with self.lock:
            saved = read_json(self.settings_file)
            turned_on = payload.get('notify') is True and saved.get('notify') is False
            saved.update({k: v for k, v in (('notify', payload.get('notify')), ('dismissed', payload.get('dismiss'))) if v is not None})
            write_json(self.settings_file, saved)
        if turned_on and recheck:
            self.runner(lambda: self.check(max_age=0))
        return self.status()

    def start(self):
        """Begin installing the newer release in the background; the page polls status()."""
        latest = self.latest()
        if not latest:
            raise ValueError('No newer release to install')
        with self.lock:
            running = self.progress['state'] in ('starting', 'downloading', 'verifying', 'installing', 'restarting')
            if not running:
                self.progress = dict(state='starting', message=f'Starting update to {latest["version"]}', version=latest['version'])
        if not running:
            self.runner(lambda: self.run(latest))
        return self.status()

    def report(self, state, message):
        with self.lock:
            self.progress = dict(self.progress, state=state, message=message)

    def run(self, latest):
        import update_install
        installer = self.installer or update_install.install
        try:
            action, detail = installer(latest, self.kind, self.root, self.folder / 'updates', self.endpoints, self.restart_command, self.report)
        except (OSError, ValueError, UpdateError) as error:
            print(f'Update to {latest["version"]} failed: {error}', flush=True)
            self.report('failed', f'Update failed: {error}')
            return
        if action == 'manual':
            self.report('manual', detail)
            return
        self.report('restarting', f'Restarting Token Observatory {latest["version"]}')
        time.sleep(1.5)  # Lets the page see the restart message.
        if action == 'exit':
            self.stop_server()  # A helper script replaces the program once this process has exited.
            return
        self.before_restart()
        try:
            update_install.restart(detail)
        except OSError as error:
            update_install.undo()
            self.report('failed', f'Could not restart: {error}. Open Token Observatory again.')

    def finish(self):
        import update_install
        update_install.finish(self.folder, self.current)
