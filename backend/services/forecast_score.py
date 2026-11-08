"""Held-out scores for the calibration and for the budget itself.

The rolling error replays reading pairs in time order, predicting each rise from earlier
pairs only. The day check counts past days whose tokens stayed within the budget the
formula would have given at the start of that day.
"""
from bisect import bisect_right
from dataclasses import dataclass
import datetime as dt

from backend.services import forecast_budget, forecast_weights as fw, quota

MIN_ROLLING = 6        # The replay starts at the sixth pair.
MIN_SCORED_DAYS = 5
READING_GAP = 12 * 3600
DAYS = 30
WEEK = quota.WEEKLY_MINUTES * 60


@dataclass(frozen=True)
class Rolling:
    mae_points: float
    single_mae_points: float
    readings: int


@dataclass(frozen=True)
class Check:
    within: int
    scored: int


def rolling_steps(pairs, kind):
    """(chosen error, single-ratio error) in percentage points for each pair from the sixth on."""
    steps = []
    for i in range(MIN_ROLLING - 1, len(pairs)):
        earlier, target = pairs[:i], pairs[i]
        single = sum(target.tokens) * fw.single_percent_per_million(earlier)
        predicted = single
        if kind == 'by_type' and i >= fw.MIN_TYPED_PAIRS:
            predicted = fw.predict(fw.fit_nnls(earlier), target)
        steps.append((abs(predicted - target.rise), abs(single - target.rise)))
    return steps


def rolling_errors(pairs, kind):
    """Mean held-out error of the chosen calibration and of the single ratio, or None below six pairs."""
    steps = rolling_steps(pairs, kind)
    if not steps:
        return None
    return Rolling(sum(a for a, _ in steps) / len(steps), sum(b for _, b in steps) / len(steps), len(steps))


def tokens_per_percent_as_of(pairs, kind, index, day):
    """The calibration a user would have had at the start of `day`, from pairs that ended before it."""
    start = dt.datetime.combine(day, dt.time()).timestamp()
    past = [p for p in pairs if p.t_end <= start]
    if not past:
        return None
    if kind == 'by_type' and len(past) >= fw.MIN_TYPED_PAIRS:
        weights = fw.fit_nnls(past)
        effective = fw.effective_tokens_per_percent(weights, fw.recent_mix(index, day) or fw.pairs_mix(past)) if weights else None
        if effective:
            return effective
    return fw.single_tokens_per_percent(past)


def day_check(samples, index, pairs, kind, weekday_weights, today):
    """How many scoreable past days stayed within that day's budget, or None below five scoreable days."""
    readings = sorted((s for s in samples if s.resets_at is not None), key=lambda s: s.t)
    times = [s.t for s in readings]
    scored = within = 0
    for back in range(1, DAYS + 1):
        day = today - dt.timedelta(days=back)
        start = forecast_budget.midnight(day)
        end = forecast_budget.midnight(day + dt.timedelta(days=1))
        found = bisect_right(times, start) - 1
        reading = readings[found] if found >= 0 else None
        if (reading is None or start - reading.t > READING_GAP or reading.resets_at <= start
                or reading.resets_at - WEEK > start):
            continue
        k = tokens_per_percent_as_of(pairs, kind, index, day)
        if not k:
            continue
        gap = sum(index.between(reading.t, start - 1e-6))  # Tokens logged after the reading and before the day began.
        capacity = k * max(0.0, 100 - reading.percent) + gap
        weights = forecast_budget.day_weights(weekday_weights, day, max(reading.resets_at - WEEK, start), reading.resets_at)
        used = sum(index.between(start, end, 'left'))
        scored += 1
        within += used <= capacity * weights[0] / sum(weights)
    return Check(within, scored) if scored >= MIN_SCORED_DAYS else None
