"""Scheduled window warm-up: send "hello" to a provider's cheapest model at times the user chose.

The five-hour usage window of a paid plan starts with the first message, so a small message sent early
starts it, and so ends it, at a time the user picked. Everything here is opt-in and off by default.

A slot is one provider at one local wall-clock time on one date. Each slot gets exactly one outcome:
`sent`, `failed`, `skipped_active` (a window was already running) or `missed` (the collector was not
running within CATCH_UP of the time). When the window is used up at the scheduled time, the slot is
deferred instead: the message goes out RESET_DELAY seconds after the window's reset time. Sending itself lives in `warmup_send`.
"""
import dataclasses
import datetime as dt
import re
import shutil
import threading
from pathlib import Path

from backend.services.claude_statusline import read_json, write_json

MESSAGE = 'hello'
PROVIDERS = ('claude', 'codex', 'minimax')
MAX_TIMES = 8
CATCH_UP = dt.timedelta(minutes=30)
RESET_DELAY = 60  # Seconds after an exhausted window resets before the deferred message goes out.
EXHAUSTED = 100  # Percent of the window used at which nothing more can be sent.
KEEP_OUTCOMES = 200
SHOWN_OUTCOMES = 10
TIME = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')
# Must start with a letter or digit so a model id can never be read as a command line option.
MODEL = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:/-]{0,63}$')
STAMP = '%Y-%m-%d %H:%M:%S'


@dataclasses.dataclass(frozen=True)
class Outcome:
    provider: str
    slot: str
    at: float
    status: str
    reason: str = ''


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def active(window, now):
    """A window counts as running when it will reset later and some of it is already used."""
    if not isinstance(window, dict):
        return False
    resets, used = number(window.get('resets_at')), number(window.get('used_percent'))
    return resets is not None and resets > now.timestamp() and (used or 0) > 0


def exhausted(window, now):
    """A window whose quota is used up and which has not reset yet."""
    if not isinstance(window, dict):
        return False
    resets, used = number(window.get('resets_at')), number(window.get('used_percent'))
    return resets is not None and resets > now.timestamp() and (used or 0) >= EXHAUSTED


def clean(payload):
    """Validate one provider update. Raises ValueError for anything malformed."""
    if not isinstance(payload, dict):
        raise ValueError('Expected a JSON object')
    provider, enabled, times, model = (payload.get(k) for k in ('provider', 'enabled', 'times', 'model'))
    if provider not in PROVIDERS:
        raise ValueError(f'provider must be one of {", ".join(PROVIDERS)}')
    if not isinstance(enabled, bool):
        raise ValueError('enabled must be true or false')
    if not isinstance(times, list) or not all(isinstance(t, str) and TIME.match(t) for t in times):
        raise ValueError('times must be a list of HH:MM in 24-hour form')
    if len(set(times)) != len(times):
        raise ValueError('times must not repeat')
    if len(times) > MAX_TIMES:
        raise ValueError(f'at most {MAX_TIMES} times per provider')
    if enabled and not times:
        raise ValueError('add at least one time before turning warm-up on')
    if model is not None and not (isinstance(model, str) and MODEL.match(model)):
        raise ValueError('model must be a short model id')
    return provider, enabled, sorted(times), model


def at_time(date, text):
    return dt.datetime.combine(date, dt.time(int(text[:2]), int(text[3:])))


class Warmup:
    def __init__(self, folder, sender, window_for):
        """`sender(provider, model) -> (ok, reason)`; `window_for(provider)` gives its five-hour window or None."""
        self.folder = Path(folder)
        self.sender, self.window_for = sender, window_for
        self.lock = threading.RLock()
        self.config_file, self.state_file = self.folder / 'warmup.json', self.folder / 'warmup-state.json'
        self.providers = self.load_config()
        self.outcomes, self.deferred = self.load_state()

    # Files ----------------------------------------------------------------

    def load_config(self):
        saved = read_json(self.config_file).get('providers')
        saved = saved if isinstance(saved, dict) else {}
        result = {}
        for name in PROVIDERS:
            row = saved.get(name) if isinstance(saved.get(name), dict) else {}
            times = row.get('times')
            times = sorted(set(t for t in times if isinstance(t, str) and TIME.match(t))) if isinstance(times, list) else []
            model = row.get('model') if isinstance(row.get('model'), str) and MODEL.match(row['model']) else None
            since = row.get('since') if isinstance(row.get('since'), str) else None
            result[name] = dict(enabled=row.get('enabled') is True and bool(times), times=times[:MAX_TIMES],
                                model=model, since=since)
        return result

    def load_state(self):
        try:
            data = read_json(self.state_file) if self.state_file.exists() else {}
            if self.state_file.exists() and not data and self.state_file.read_text().strip():
                raise ValueError('unreadable')
        except (OSError, ValueError):
            try:
                shutil.copyfile(self.state_file, self.state_file.with_name(self.state_file.name + '.bad'))
            except OSError:
                pass
            data = {}
        rows = data.get('outcomes') if isinstance(data.get('outcomes'), list) else []
        found = []
        for row in rows:
            if isinstance(row, dict) and row.get('provider') in PROVIDERS and isinstance(row.get('slot'), str):
                found.append(Outcome(row['provider'], row['slot'], number(row.get('at')) or 0.0,
                                     str(row.get('status')), str(row.get('reason') or '')))
        waiting = {}
        rows = data.get('deferred') if isinstance(data.get('deferred'), list) else []
        for row in rows:
            if (isinstance(row, dict) and row.get('provider') in PROVIDERS and isinstance(row.get('slot'), str)
                    and number(row.get('send_at')) is not None):
                waiting[(row['provider'], row['slot'])] = float(row['send_at'])
        return found[-KEEP_OUTCOMES:], waiting

    def save_config(self):
        write_json(self.config_file, {'providers': self.providers})

    def save_state(self):
        deferred = [dict(provider=p, slot=slot, send_at=at) for (p, slot), at in sorted(self.deferred.items())]
        write_json(self.state_file, {'outcomes': [dataclasses.asdict(o) for o in self.outcomes], 'deferred': deferred})

    # Configuration --------------------------------------------------------

    def update(self, payload, now=None):
        provider, enabled, times, model = clean(payload)
        now = now or dt.datetime.now()
        with self.lock:
            old = self.providers[provider]
            changed = (old['enabled'], old['times']) != (enabled, times)
            since = now.strftime(STAMP) if (changed and enabled) or not old['since'] else old['since']
            self.providers[provider] = dict(enabled=enabled, times=times, model=model, since=since)
            if changed:
                self.deferred = {k: v for k, v in self.deferred.items() if k[0] != provider}
                self.save_state()
            self.save_config()
            return self.snapshot(now)

    def snapshot(self, now=None):
        now = now or dt.datetime.now()
        unavailable = getattr(self.sender, 'unavailable', lambda provider: None)
        with self.lock:
            rows = {}
            for name in PROVIDERS:
                config = self.providers[name]
                recent = [o for o in reversed(self.outcomes) if o.provider == name][:SHOWN_OUTCOMES]
                rows[name] = dict(enabled=config['enabled'], times=list(config['times']), model=config['model'],
                                  next=self.next_slot(config, now), unavailable=unavailable(name),
                                  deferred=self.waiting(name),
                                  last=[dict(slot=o.slot, at=o.at, status=o.status, reason=o.reason) for o in recent])
            return dict(message=MESSAGE, providers=rows)

    def waiting(self, provider):
        for (name, slot), send_at in sorted(self.deferred.items(), key=lambda item: item[1]):
            if name == provider:
                return dict(slot=slot, send_at=dt.datetime.fromtimestamp(send_at).strftime('%Y-%m-%d %H:%M'))
        return None

    def next_slot(self, config, now):
        if not config['enabled']:
            return None
        found = [at_time(now.date() + dt.timedelta(days=d), t) for d in (0, 1) for t in config['times']]
        later = [s for s in found if s > now]
        return min(later).strftime('%Y-%m-%d %H:%M') if later else None

    # Scheduling -----------------------------------------------------------

    def record(self, provider, slot, now, status, reason=''):
        outcome = Outcome(provider, slot, now.timestamp(), status, reason)
        with self.lock:
            self.outcomes = (self.outcomes + [outcome])[-KEEP_OUTCOMES:]
            self.deferred.pop((provider, slot), None)
            self.save_state()
        return outcome

    def due(self, now):
        """Slots with no outcome yet whose time has come, oldest first."""
        with self.lock:
            done = {(o.provider, o.slot) for o in self.outcomes} | set(self.deferred)
            found = []
            for name in PROVIDERS:
                config = self.providers[name]
                if not config['enabled']:
                    continue
                since = dt.datetime.strptime(config['since'], STAMP) if config['since'] else None
                for days in (1, 0):
                    date = now.date() - dt.timedelta(days=days)
                    for text in config['times']:
                        start = at_time(date, text)
                        slot = start.strftime('%Y-%m-%d %H:%M')
                        if start > now or (since and start < since) or (name, slot) in done:
                            continue
                        found.append((start, name, slot, config['model']))
            return sorted(found)

    def defer(self, provider, slot, send_at):
        with self.lock:
            self.deferred[(provider, slot)] = send_at
            self.save_state()

    def lookup(self, provider):
        try:
            return self.window_for(provider)
        except Exception:
            return None  # an unreadable window must not block the send

    def send(self, provider, slot, model, now, note=''):
        try:
            ok, reason = self.sender(provider, model)
        except Exception as error:
            ok, reason = False, f'{type(error).__name__}: {error}'
        return self.record(provider, slot, now, 'sent' if ok else 'failed', note if ok else str(reason)[:200])

    def run_deferred(self, now):
        """Send each deferred message one minute after its window reset, unless that moment has gone stale."""
        recorded = []
        with self.lock:
            waiting = sorted(self.deferred.items(), key=lambda item: item[1])
        for (provider, slot), send_at in waiting:
            config = self.providers[provider]
            if not config['enabled']:
                with self.lock:
                    self.deferred.pop((provider, slot), None)
                    self.save_state()
                continue
            if now.timestamp() < send_at:
                continue
            if now.timestamp() - send_at >= CATCH_UP.total_seconds():
                recorded.append(self.record(provider, slot, now, 'missed', 'Token Observatory was not running after the limit reset'))
                continue
            window = self.lookup(provider)
            if exhausted(window, now):
                self.defer(provider, slot, window['resets_at'] + RESET_DELAY)
            elif active(window, now):
                recorded.append(self.record(provider, slot, now, 'skipped_active'))
            else:
                recorded.append(self.send(provider, slot, config['model'], now, 'after the limit reset'))
        return recorded

    def tick(self, now=None):
        """Handle every due slot once. Returns the outcomes recorded by this call."""
        now = now or dt.datetime.now()
        recorded = self.run_deferred(now)
        for start, provider, slot, model in self.due(now):
            if now - start >= CATCH_UP:
                recorded.append(self.record(provider, slot, now, 'missed'))
                continue
            window = self.lookup(provider)
            if exhausted(window, now):
                self.defer(provider, slot, window['resets_at'] + RESET_DELAY)
            elif active(window, now):
                recorded.append(self.record(provider, slot, now, 'skipped_active'))
            else:
                recorded.append(self.send(provider, slot, model, now))
        return recorded
