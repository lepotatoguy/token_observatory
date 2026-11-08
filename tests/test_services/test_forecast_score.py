import datetime as dt

import pytest

from backend.services import forecast_score as fs
from backend.services import forecast_weights as fw
from backend.services.forecast_history import Sample

TRUE = (3.0, 0.1, 1.5, 40.0)
TODAY = dt.date(2026, 11, 6)


def single_pairs(rises):
    return [fw.Pair(float(i), rise, (1.0, 0.0, 0.0, 0.0)) for i, rise in enumerate(rises)]


def typed_pairs(count):
    pairs = []
    for i in range(count):
        tokens = (1 + (i * 7) % 5, 5 + (i * 3) % 11, 0.2 * (1 + i % 4), 0.5 + ((i * 5) % 7) * 0.3)
        pairs.append(fw.Pair(float(i), sum(w * t for w, t in zip(TRUE, tokens)), tokens))
    return pairs


def test_the_rolling_error_matches_a_hand_computation():
    result = fs.rolling_errors(single_pairs([2, 2, 2, 2, 2, 2, 8]), 'single')
    assert (result.mae_points, result.single_mae_points, result.readings) == (3.0, 3.0, 2)


def test_the_rolling_error_needs_six_pairs():
    assert fs.rolling_errors(single_pairs([2] * 5), 'single') is None
    assert fs.rolling_errors(single_pairs([2] * 6), 'single').readings == 1


def test_each_step_uses_only_earlier_pairs():
    pairs = typed_pairs(26)
    full = fs.rolling_steps(pairs, 'by_type')
    assert fs.rolling_steps(pairs[:22], 'by_type') == full[:len(full) - 4]


def test_the_by_type_fit_is_used_only_after_twenty_earlier_pairs(monkeypatch):
    calls = []
    real = fw.fit_nnls
    monkeypatch.setattr(fw, 'fit_nnls', lambda pairs: calls.append(len(pairs)) or real(pairs))
    result = fs.rolling_errors(typed_pairs(25), 'by_type')
    assert calls == [20, 21, 22, 23, 24] and result.readings == 20
    assert result.mae_points < result.single_mae_points


def test_the_single_kind_never_fits_by_type(monkeypatch):
    monkeypatch.setattr(fw, 'fit_nnls', lambda pairs: pytest.fail('by-type fit used'))
    result = fs.rolling_errors(typed_pairs(25), 'single')
    assert result.mae_points == result.single_mae_points


def mid(day):
    return dt.datetime.combine(day, dt.time()).timestamp()


def at(day, hour):
    return dt.datetime.combine(day, dt.time(hour)).timestamp()


RESET = mid(dt.date(2026, 11, 7))          # The weekly window runs 31 October to 6 November.
K = 0.5e6                                  # Tokens per percent: 2 points per million tokens.
CALIBRATION = [fw.Pair(mid(dt.date(2026, 10, 20 + i)), 2.0, (1.0, 0.0, 0.0, 0.0)) for i in range(6)]
FLAT = [1.0] * 7
USED = {dt.date(2026, 11, 1): 2e6, dt.date(2026, 11, 2): 4e6, dt.date(2026, 11, 3): 20e6,
        dt.date(2026, 11, 4): 3e6, dt.date(2026, 11, 5): 3e6}


def week(used=USED, evening=20, resets_at=RESET, skip=()):
    """Typed rows, one noon event per day, and an evening reading each day that matches the 2 points per million."""
    rows, samples, spent = [], [], 0.0
    for day in sorted(used):
        samples_day = day - dt.timedelta(days=1)
        if samples_day not in skip:
            samples.append(Sample(at(samples_day, evening), spent / K, resets_at))
        rows.append((at(day, 12), used[day], 0.0, 0.0, 0.0))
        spent += used[day]
    return fw.Index(rows), samples


def check(used=USED, **kwargs):
    index, samples = week(used, **kwargs)
    return fs.day_check(samples, index, CALIBRATION, 'single', FLAT, TODAY)


def test_days_within_the_budget_as_it_stood_at_the_start_of_each_day_are_counted():
    result = check()
    assert (result.within, result.scored) == (4, 5)  # Only 3 November (20M against an 11M budget) is over.


def test_a_reading_older_than_twelve_hours_leaves_the_day_unscored():
    near, samples = week(evening=13)                # 11 hours before midnight: near enough.
    assert fs.day_check(samples, near, CALIBRATION, 'single', FLAT, TODAY).scored == 5
    far, samples = week(evening=11)                 # 13 hours before midnight: too old.
    assert fs.day_check(samples, far, CALIBRATION, 'single', FLAT, TODAY) is None


def test_a_reading_of_another_window_leaves_the_day_unscored():
    index, samples = week()
    other = samples[:4] + [Sample(samples[4].t, samples[4].percent, RESET + 7 * 86400)]
    assert fs.day_check(other, index, CALIBRATION, 'single', FLAT, TODAY) is None  # Four scoreable days.


def test_fewer_than_five_scoreable_days_gives_none():
    index, samples = week()
    assert fs.day_check(samples[:4], index, CALIBRATION, 'single', FLAT, TODAY) is None
    assert fs.day_check([], index, CALIBRATION, 'single', FLAT, TODAY) is None


def test_a_reading_without_a_reset_time_cannot_score_a_day():
    index, samples = week()
    bare = [Sample(s.t, s.percent, None) for s in samples]
    assert fs.day_check(bare, index, CALIBRATION, 'single', FLAT, TODAY) is None


def test_days_before_any_calibration_exists_are_not_scored():
    index, samples = week()
    assert fs.day_check(samples, index, [], 'single', FLAT, TODAY) is None


def test_fitting_and_scoring_one_hundred_pairs_stays_under_half_a_second():
    import time
    pairs = typed_pairs(100)
    started = time.perf_counter()
    choice = fw.choose(pairs)
    fs.rolling_errors(pairs, choice.kind)
    elapsed = time.perf_counter() - started
    assert choice.kind == 'by_type'
    assert elapsed < 0.5, f'took {elapsed:.2f}s'
