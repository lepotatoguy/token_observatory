"""Shared limit preferences and bounded, metadata-only transition history."""
from contextlib import contextmanager
import json
import math
import os
from pathlib import Path
import threading
import time

from backend.services.claude_statusline import read_json, write_json

DAYS = 30 * 86400
MAX_EVENTS = 1000
MAX_BYTES = 256 * 1024
PROVIDERS = ('claude', 'codex', 'minimax')


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


def preferences(row, default=90):
    """Keep the existing five-hour threshold and reserve 3% of the week in hard mode."""
    row = row if isinstance(row, dict) else {}
    if 'warn' in row or 'hard' in row:
        pref = {k: row.get(k) if numeric(row.get(k)) and 1 <= row[k] <= 100 else None for k in ('warn', 'hard')}
    else:
        threshold = row.get('threshold', default)
        threshold = threshold if numeric(threshold) and 1 <= threshold <= 100 else default
        pref = dict(warn=threshold if row.get('mode') == 'warn' else None,
                    hard=None if row.get('mode') == 'warn' else threshold)
    reserve = row.get('weekly_reserve', 3 if pref['hard'] is not None else None)
    return dict(pref, weekly_reserve=reserve if numeric(reserve) and 0 <= reserve <= 100 else None)


def hard_threshold(pref, minutes=300):
    if minutes == 10080:
        reserve = pref.get('weekly_reserve')
        return 100-reserve if reserve is not None else None
    return pref['hard'] if minutes == 300 else None


def stage(pref, used, minutes=300):
    hard = hard_threshold(pref, minutes)
    if pref['warn'] is None and hard is None:
        return 0
    if used >= 100:
        return 3
    if hard is not None and used >= hard:
        return 2
    return 1 if pref['warn'] is not None and used >= pref['warn'] else 0


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
            providers[p] = preferences(row, default)
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
                    if not isinstance(row, dict):
                        raise ValueError('Each provider needs warn and hard percentages, or null to disable')
                    if set(row) == {'mode', 'threshold'}:
                        if row['mode'] not in ('warn', 'hard') or not numeric(row['threshold']) or not 1 <= row['threshold'] <= 100:
                            raise ValueError('Invalid legacy mode or threshold')
                        row = preferences(row)
                    if set(row) not in ({'warn', 'hard'}, {'warn', 'hard', 'weekly_reserve'}) or any(v is not None and (not numeric(v) or not 1 <= v <= 100) for k, v in row.items() if k != 'weekly_reserve'):
                        raise ValueError('Warn and hard must each be null or a percentage from 1 to 100')
                    reserve = row.get('weekly_reserve')
                    if reserve is not None and (not numeric(reserve) or not 0 <= reserve <= 100):
                        raise ValueError('Weekly reserve must be null or a remaining percentage from 0 to 100')
                    if row['warn'] is not None and row['hard'] is not None and row['warn'] > row['hard']:
                        raise ValueError('Warning threshold must not exceed hard limit')
                    data[p] = preferences(row)
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
                    hard = hard_threshold(pref, row.get('minutes'))
                    level = stage(pref, used, row.get('minutes'))
                    mode = 'hard' if level >= 2 and hard is not None else 'warn'
                    if level > current['level']:
                        current['level'] = level
                        self.append(state, dict(at=now, type='exhausted' if level == 3 else 'threshold', provider=provider,
                                                limit=row['id'][:100], minutes=row.get('minutes'), reset=reset,
                                                used=used, mode=mode, threshold=hard if mode == 'hard' else pref['warn']))
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
