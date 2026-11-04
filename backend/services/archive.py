"""Atomic, private JSON snapshots, retaining the latest capture for each day."""
import datetime as dt
import gzip
import json
import os
from pathlib import Path
import sys
import tempfile
import time


def default_data():
    """Per-user data folder following each platform's convention."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Token Observatory'
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming') / 'Token Observatory'
    return Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share') / 'token-observatory'


DEFAULT_DATA = default_data()


class Archive:
    interval = 60

    def __init__(self, directory):
        self.directory = Path(directory)
        self.signature = None
        self.day = None
        self.saved_at = None
        self.saved_clock = float('-inf')
        self.error = None

    def dates(self):
        result = set()
        for path in list(self.directory.glob('*.json')) + list(self.directory.glob('*.json.gz')):
            day = path.name.removesuffix('.gz').removesuffix('.json')
            try:
                if not path.is_symlink() and dt.date.fromisoformat(day).isoformat() == day:
                    result.add(day)
            except ValueError:
                pass
        return sorted(result, reverse=True)

    def update(self, snapshot, signature, force=False):
        day = dt.datetime.fromtimestamp(snapshot['at']).date().isoformat()
        changed = signature != self.signature or day != self.day
        due = time.monotonic() - self.saved_clock >= self.interval
        if force or (changed and (due or day != self.day)):
            temporary = None
            try:
                self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
                body = dict(snapshot, schema_version=1)
                current_ids = {session.get('id') for session in snapshot['sessions']}
                current_sources = {source for session in snapshot['sessions']
                                   for source in session.get('source_files', [session.get('source')])}
                previous = []
                if any((self.directory / (day + suffix)).exists() for suffix in ('.json', '.json.gz')):
                    previous = self.load(day)['sessions']
                retained = [session for session in previous if session.get('id') and session['id'] not in current_ids
                            and session.get('source') not in current_sources]
                body['sessions'] = [dict(session, last_observed_at=snapshot['at']) for session in snapshot['sessions']] + retained
                descriptor, temporary = tempfile.mkstemp(prefix='.snapshot-', suffix='.tmp', dir=self.directory)
                with os.fdopen(descriptor, 'wb') as stream:
                    stream.write(gzip.compress(json.dumps(body, separators=(',', ':'), allow_nan=False).encode('utf-8'), mtime=0))
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.directory / (day + '.json.gz'))
                self.signature, self.day = signature, day
                self.saved_at, self.saved_clock = snapshot['at'], time.monotonic()
                self.error = None
            except (OSError, ValueError) as error:
                self.error = f'JSON auto-save failed: {getattr(error, "strerror", None) or str(error)}'
            finally:
                if temporary is not None:
                    try:
                        Path(temporary).unlink(missing_ok=True)
                    except OSError:
                        pass
        try:
            dates = self.dates()
        except OSError as error:
            dates = []
            self.error = f'Cannot list JSON history: {error.strerror or str(error)}'
        return dict(directory=str(self.directory), saved_at=self.saved_at,
                    interval_seconds=self.interval, dates=dates, error=self.error)

    def load(self, day):
        if dt.date.fromisoformat(day).isoformat() != day:
            raise ValueError('Invalid snapshot date')
        paths = [self.directory / (day + suffix) for suffix in ('.json', '.json.gz')]
        if any(path.is_symlink() for path in paths):
            raise ValueError('Snapshot cannot be a symlink')
        available = [path for path in paths if path.exists()]
        if not available:
            raise FileNotFoundError(day)
        path = max(available, key=lambda candidate: (candidate.stat().st_mtime_ns, candidate.suffix == '.gz'))
        opener = gzip.open if path.suffix == '.gz' else open
        try:
            with opener(path, 'rt', encoding='utf-8') as stream:
                snapshot = json.load(stream)
        except EOFError as error:
            raise ValueError('Truncated compressed snapshot') from error
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('sessions'), list) or not isinstance(snapshot.get('at'), (int, float)):
            raise ValueError('Invalid snapshot format')
        return snapshot
