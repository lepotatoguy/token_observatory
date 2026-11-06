"""Daily token history and weekly percent samples for the budget forecast.

Reads the live snapshot and the archived daily snapshots once. A session that
appears in several daily files is taken only from the newest one, because later
captures hold every earlier event of the same session.
"""
from dataclasses import dataclass
import datetime as dt
import math

from backend.parsers._helpers import FIELDS, number
from backend.services import quota

WINDOW_DAYS = 30
COUNTED = tuple(field for field in FIELDS if field != 'reasoning')  # Reasoning is already part of output.


@dataclass(frozen=True)
class Sample:
    """One reading of a weekly quota window."""
    t: float
    percent: float
    resets_at: float | None = None


@dataclass(frozen=True)
class History:
    events: dict      # provider -> sorted [(seconds, tokens)] inside the history window, today included
    series: dict      # provider -> daily totals, oldest first, ending yesterday
    first_day: dict   # provider -> date of the first recorded event inside the window
    samples: dict     # provider -> [Sample] sorted by time
    skipped_events: int
    warnings: list


def is_time(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def day_of(seconds):
    try:
        return dt.datetime.fromtimestamp(seconds).date()
    except (OverflowError, OSError, ValueError):
        return None


def weekly(limits):
    return quota.pick(limits, quota.WEEKLY_MINUTES, 'secondary') if isinstance(limits, dict) else None


def collect(snapshot, archive, plan_samples, today, providers, days=WINDOW_DAYS):
    """History for the given providers over the `days` local days before `today`."""
    first = today - dt.timedelta(days=days)
    start = dt.datetime.combine(first, dt.time()).timestamp()
    seen, warnings, marks = set(), [], set()
    rows = {provider: [] for provider in providers}
    samples = {}
    skipped = 0

    def add_sample(provider, t, window):
        if provider not in providers or not window or not is_time(t) or window['used_percent'] is None:
            return
        key = (provider, round(t), window['used_percent'])
        if key not in marks:
            marks.add(key)
            samples.setdefault(provider, []).append(Sample(float(t), window['used_percent'], window['resets_at']))

    def read(snap):
        nonlocal skipped
        for session in snap.get('sessions') or []:
            sid = session.get('id')
            if sid is not None:
                if sid in seen:
                    continue
                seen.add(sid)
            provider = session.get('provider')
            if provider not in providers:
                continue
            add_sample(provider, session.get('rate_limits_at'), weekly(session.get('rate_limits')))
            for event in session.get('events') or []:
                at = event.get('at')
                if not is_time(at):
                    skipped += 1
                elif at >= start:
                    rows[provider].append((at, sum(number(event.get(field)) for field in COUNTED)))
        for provider, limits in (snap.get('limits') or {}).items():
            if isinstance(limits, dict):
                add_sample(provider, limits.get('observed_at'), weekly(limits))

    read(snapshot)
    if archive is not None:
        try:
            names = archive.dates()
        except OSError as error:
            warnings.append(f'Cannot list JSON history: {error.strerror or error}')
            names = []
        for name in names:
            try:
                if dt.date.fromisoformat(name) < first:
                    continue
                read(archive.load(name))
            except (OSError, ValueError) as error:
                warnings.append(f'Skipped {name}: {getattr(error, "strerror", None) or error}')
    for t, _five, seven in plan_samples:
        add_sample('claude', t, dict(used_percent=seven, resets_at=None))

    events, series, first_day = {}, {}, {}
    for provider, found in rows.items():
        if not found:
            continue
        found.sort()
        events[provider] = found
        totals = {}
        for at, tokens in found:
            day = day_of(at)
            if day is not None and day < today:
                totals[day] = totals.get(day, 0) + tokens
        if totals:
            begin = min(totals)
            series[provider] = [totals.get(begin + dt.timedelta(days=i), 0) for i in range((today - begin).days)]
            first_day[provider] = begin
    ordered = {provider: sorted(found, key=lambda sample: sample.t) for provider, found in samples.items()}
    return History(events, series, first_day, ordered, skipped, warnings)
