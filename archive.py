"""Atomic, private JSON snapshots, retaining the latest capture for each day."""
import datetime as dt
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
        result = []
        for path in self.directory.glob('*.json'):
            try:
                if not path.is_symlink() and dt.date.fromisoformat(path.stem).isoformat() == path.stem:
                    result.append(path.stem)
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
                if (self.directory / (day + '.json')).exists():
                    previous = self.load(day)['sessions']
                retained = [session for session in previous if session.get('id') and session['id'] not in current_ids
                            and session.get('source') not in current_sources]
                body['sessions'] = [dict(session, last_observed_at=snapshot['at']) for session in snapshot['sessions']] + retained
                descriptor, temporary = tempfile.mkstemp(prefix='.snapshot-', suffix='.tmp', dir=self.directory)
                with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                    json.dump(body, stream, separators=(',', ':'), allow_nan=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self.directory / (day + '.json'))
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
        path = self.directory / (day + '.json')
        if path.is_symlink():
            raise ValueError('Snapshot cannot be a symlink')
        with path.open(encoding='utf-8') as stream:
            snapshot = json.load(stream)
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get('sessions'), list) or not isinstance(snapshot.get('at'), (int, float)):
            raise ValueError('Invalid snapshot format')
        return snapshot
