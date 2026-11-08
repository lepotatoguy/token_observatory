"""Daily token history and weekly percent samples for the budget forecast.

Reads the live snapshot and the archived daily snapshots once. A session that
appears in several daily files is taken only from the newest one, because later
captures hold every earlier event of the same session.
"""
from dataclasses import dataclass
import bisect
import datetime as dt
import math
from operator import itemgetter

from backend.parsers._helpers import FIELDS, number
from backend.services import quota

WINDOW_DAYS = 30
COUNTED = tuple(field for field in FIELDS if field != 'reasoning')  # Reasoning is already part of output.
assert COUNTED == ('input', 'cached', 'write', 'output')  # collect() reads these four fields inline.
INF = math.inf
fields = itemgetter('at', *COUNTED)


@dataclass(frozen=True)
class Sample:
    """One reading of a weekly quota window."""
    t: float
    percent: float
    resets_at: float | None = None


@dataclass(frozen=True)
class History:
    events: dict      # provider -> sorted [(seconds, tokens)] inside the history window, today included
    typed: dict       # provider -> sorted [(seconds, input, cached, write, output)], the same events split by token type
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
    typed_rows = {provider: [] for provider in providers}
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
            typed_into = typed_rows[provider]
            for event in session.get('events') or []:
                try:
                    at, a, b, c, d = fields(event)
                except KeyError:  # A missing field reads as absent, like event.get.
                    at, a, b, c, d = (event.get(name) for name in ('at', *COUNTED))
                kind = at.__class__
                if not ((kind is float and -INF < at < INF) or kind is int or is_time(at)):
                    skipped += 1
                elif at >= start:
                    if a.__class__ is int and b.__class__ is int and c.__class__ is int and d.__class__ is int \
                            and a >= 0 and b >= 0 and c >= 0 and d >= 0:
                        typed_into.append((at, a, b, c, d))
                    else:  # Missing, negative, fractional or boolean counts take the careful path.
                        values = [number(v) for v in (a, b, c, d)]
                        typed_into.append((at, *values))
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

    events, typed, series, first_day = {}, {}, {}, {}
    for provider, found in typed_rows.items():
        if not found:
            continue
        found.sort()
        typed[provider] = found
        events[provider] = [(row[0], row[1] + row[2] + row[3] + row[4]) for row in found]
        totals = {}
        low, count = 0, len(found)
        while low < count:  # One local-day bucket at a time, so day_of runs per day, not per event.
            day = day_of(found[low][0])
            if day is None:
                low += 1
                continue
            end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time()).timestamp()
            high = bisect.bisect_left(found, (end,), low)
            if high <= low:  # A clock jump put the boundary at or before this event: take it alone.
                high = low + 1
            if day < today:
                totals[day] = totals.get(day, 0) + sum(row[1] + row[2] + row[3] + row[4] for row in found[low:high])
            low = high
        if totals:
            begin = min(totals)
            series[provider] = [totals.get(begin + dt.timedelta(days=i), 0) for i in range((today - begin).days)]
            first_day[provider] = begin
    ordered = {provider: sorted(found, key=lambda sample: sample.t) for provider, found in samples.items()}
    return History(events, typed, series, first_day, ordered, skipped, warnings)
