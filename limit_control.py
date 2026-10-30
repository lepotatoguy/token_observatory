"""Shared limit preferences and bounded, metadata-only transition history."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import threading
import time

from claude_statusline import read_json, write_json

DAYS = 30 * 86400
MAX_EVENTS = 1000
MAX_BYTES = 256 * 1024
PROVIDERS = ('claude', 'codex')


@contextmanager
def file_lock(folder, name, blocking=True):
    path = Path(folder) / (name + '.lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        if os.name == 'nt':
            import msvcrt
            if not path.stat().st_size:
                stream.write(b'0')
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        try:
            yield
        finally:
            if os.name == 'nt':
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


class Control:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else None
        self.memory = {}
        self.lock = threading.RLock()

    def load(self, name):
        return read_json(self.folder / (name + '.json')) if self.folder else self.memory.get(name, {})

    def save(self, name, value):
        if self.folder:
            write_json(self.folder / (name + '.json'), value)
        else:
            self.memory[name] = value

    @contextmanager
    def transaction(self):
        with self.lock:
            if self.folder:
                with file_lock(self.folder, 'limit-control'):
                    yield
            else:
                yield

    def settings(self):
        data = self.load('limit-settings')
        legacy = self.load('config').get('hook_limit_percent', 90)
        default = legacy if numeric(legacy) and 1 <= legacy <= 100 else 90
        providers = {}
        for p in PROVIDERS:
            row = data.get(p, {})
            threshold = row.get('threshold', default)
            providers[p] = dict(mode=row.get('mode') if row.get('mode') in ('warn', 'hard') else 'hard',
                                threshold=threshold if numeric(threshold) and 1 <= threshold <= 100 else default)
        return dict(providers, reset_notifications=data.get('reset_notifications', True) is True)

    def update(self, payload, now=None):
        if set(payload) - {*PROVIDERS, 'reset_notifications'}:
            raise ValueError('Unknown limit setting')
        with self.transaction():
            data = self.settings()
            for p, row in payload.items():
                if p == 'reset_notifications':
                    if not isinstance(row, bool):
                        raise ValueError('reset_notifications must be true or false')
                    data[p] = row
                else:
                    if not isinstance(row, dict) or set(row) != {'mode', 'threshold'}:
                        raise ValueError('Each provider needs mode and threshold')
                    if row['mode'] not in ('warn', 'hard') or not numeric(row['threshold']) or not 1 <= row['threshold'] <= 100:
                        raise ValueError('Mode must be warn or hard; threshold must be from 1 to 100')
                    data[p] = row
            if data != self.settings():
                self.save('limit-settings', data)
                state = self.load('limit-events')
                self.append(state, dict(at=time.time() if now is None else now, type='settings'))
                self.persist(state, time.time() if now is None else now)
            return data

    def append(self, state, event):
        state.setdefault('events', []).append(event)

    def persist(self, state, now):
        state['events'] = [e for e in state.get('events', []) if now - DAYS <= e['at'] <= now][-MAX_EVENTS:]
        state['windows'] = {k: w for k, w in state.get('windows', {}).items() if w.get('seen', 0) >= now - DAYS}
        while len(json.dumps(state).encode()) > MAX_BYTES and state['events']:
            state['events'].pop(0)
        self.save('limit-events', state)

    def observe(self, limits, now=None, pauses=()):
        """Record transitions once globally, even when many chats/tabs observe them."""
        now = time.time() if now is None else now
        with self.transaction():
            settings = self.settings()
            before = self.load('limit-events')
            state = json.loads(json.dumps(before))
            windows = state.setdefault('windows', {})
            for key, old in list(windows.items()):
                if old.get('reset') and old['reset'] <= now and not old.get('expired'):
                    old['expired'] = True
                    self.append(state, dict(at=old['reset'], type='reset', provider=old['provider'],
                                            limit=old['limit'], minutes=old.get('minutes'), reset=old['reset']))
            for provider, rows in limits.items():
                if provider not in PROVIDERS:
                    continue
                for row in rows.values():
                    reset, used = row.get('reset'), row.get('percent')
                    if not numeric(used) or (reset and reset <= now):
                        continue
                    key = f"{provider}:{row['id'][:100]}"
                    old = windows.get(key)
                    same = old and not old.get('expired') and (
                        abs(reset-old['reset']) <= 60 if reset and old.get('reset') else reset == old.get('reset'))
                    current = old if same else dict(provider=provider, limit=row['id'][:100], minutes=row.get('minutes'),
                                                    reset=reset, level=0)
                    current['seen'] = now
                    pref = settings[provider]
                    if current.get('policy') != pref:
                        current['level'] = 0
                        current['pause_level'] = 0
                        current['policy'] = dict(pref)
                    level = 2 if used >= 100 else 1 if used >= pref['threshold'] else 0
                    if level > current['level']:
                        current['level'] = level
                        self.append(state, dict(at=now, type='exhausted' if level == 2 else 'threshold', provider=provider,
                                                limit=row['id'][:100], minutes=row.get('minutes'), reset=reset,
                                                used=used, mode=pref['mode'], threshold=pref['threshold']))
                    if (provider, row['id']) in pauses and level > current.get('pause_level', 0):
                        current['pause_level'] = level
                        self.append(state, dict(at=now, type='pause', provider=provider, limit=row['id'][:100], reset=reset))
                    windows[key] = current
            # Bound even a malformed stream of changing limit identifiers.
            state['windows'] = dict(sorted(windows.items(), key=lambda kv: kv[1]['seen'])[-64:])
            state['events'] = [e for e in state.get('events', []) if e['at'] >= now-DAYS][-MAX_EVENTS:]
            if state != before:
                self.persist(state, now)
            return self.snapshot(now)

    def snapshot(self, now=None):
        now = time.time() if now is None else now
        state = self.load('limit-events')
        events = [e for e in state.get('events', []) if e['at'] >= now-DAYS][-MAX_EVENTS:]
        return dict(settings=self.settings(), events=list(reversed(events)), retention_days=30,
                    max_events=MAX_EVENTS, max_bytes=MAX_BYTES)
