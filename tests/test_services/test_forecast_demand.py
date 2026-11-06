import datetime as dt

import pytest

from backend.services import forecast_demand as fd

LAST = dt.date(2026, 11, 5)  # A Thursday.


def weekday_of(index, length):
    return (LAST - dt.timedelta(days=length - 1 - index)).weekday()


def patterned(length, weekday=100, weekend=10):
    return [weekend if weekday_of(i, length) >= 5 else weekday for i in range(length)]


def test_short_history_is_flat_and_has_no_backtest():
    demand = fd.fit_demand(patterned(17), LAST)
    assert demand.method == 'flat'
    assert demand.weekday_weights == (1.0,) * 7
    assert demand.backtest is None


def test_empty_history_is_flat_with_low_confidence():
    demand = fd.fit_demand([], LAST)
    assert (demand.method, demand.confidence, demand.days_used) == ('flat', 'low', 0)


def test_a_real_weekday_pattern_beats_the_baseline_and_is_used():
    demand = fd.fit_demand(patterned(35), LAST)
    assert demand.method == 'weekday_regression'
    assert demand.backtest.model_mae < demand.backtest.baseline_mae
    assert demand.weekday_weights[5] < demand.weekday_weights[0]


def test_a_constant_series_stays_flat():
    demand = fd.fit_demand([100] * 30, LAST)
    assert demand.method == 'flat'
    assert demand.backtest.model_mae == demand.backtest.baseline_mae


@pytest.mark.parametrize('series', [
    [10, 90, 50, 70, 30] * 7,
    [(i * 37) % 101 for i in range(30)],
    patterned(21),
    [5] * 18,
])
def test_the_regression_is_used_only_when_it_wins_the_backtest(series):
    demand = fd.fit_demand(series, LAST)
    wins = demand.backtest.model_mae < demand.backtest.baseline_mae
    assert (demand.method == 'weekday_regression') == wins
    if not wins:
        assert demand.weekday_weights == (1.0,) * 7


def test_weights_are_always_positive_even_for_a_weekday_with_no_use():
    length = 35
    series = [0 if weekday_of(i, length) == 6 else 100 for i in range(length)]
    demand = fd.fit_demand(series, LAST)
    assert demand.method == 'weekday_regression'
    assert min(demand.weekday_weights) >= fd.FLOOR > 0


def test_the_reported_baseline_error_is_computed_from_the_backtest():
    series = [10] * 14 + [20] * 4
    demand = fd.fit_demand(series, LAST)
    assert demand.backtest.days == 4
    assert demand.backtest.baseline_mae == pytest.approx((10 + 9.285714 + 8.571429 + 7.857143) / 4, rel=1e-5)


@pytest.mark.parametrize('length, level', [(0, 'low'), (6, 'low'), (7, 'medium'), (17, 'medium'), (18, 'normal'), (30, 'normal')])
def test_confidence_follows_the_days_used(length, level):
    demand = fd.fit_demand([50] * length, LAST)
    assert demand.confidence == level and demand.days_used == length


def test_the_fit_is_deterministic():
    series = patterned(30)
    assert fd.fit_demand(series, LAST) == fd.fit_demand(list(series), LAST)
