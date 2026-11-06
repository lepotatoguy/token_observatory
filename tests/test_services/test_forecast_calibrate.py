import pytest

from backend.services import forecast_calibrate as fc
from backend.services.forecast_history import Sample

EVENTS = [(10, 100), (20, 100), (30, 100), (40, 100)]


def s(t, percent, resets_at=None):
    return Sample(float(t), percent, resets_at)


def test_a_pair_gives_tokens_per_percent():
    result = fc.tokens_per_percent([s(0, 10), s(15, 12)], EVENTS)
    assert result.value == 50 and result.pairs == 1


def test_pairs_chain_and_the_estimate_is_total_tokens_over_total_percent():
    result = fc.tokens_per_percent([s(0, 10), s(15, 12), s(35, 18)], EVENTS)
    assert result.pairs == 2
    assert result.value == pytest.approx((100 + 200) / (2 + 6))


def test_a_pair_waits_for_a_two_point_rise():
    result = fc.tokens_per_percent([s(0, 10), s(15, 11), s(25, 12)], EVENTS)
    assert result.pairs == 1 and result.value == 100


def test_a_percent_drop_starts_a_new_window_and_is_never_paired_across():
    result = fc.tokens_per_percent([s(0, 50), s(15, 52), s(16, 3), s(35, 5)], EVENTS)
    assert result.pairs == 2
    assert result.value == pytest.approx((100 + 200) / 4)


def test_different_reset_times_start_a_new_window():
    samples = [s(0, 10, 1000), s(15, 12, 1000), s(16, 12, 99999), s(35, 14, 99999)]
    result = fc.tokens_per_percent(samples, EVENTS)
    assert result.pairs == 2


def test_a_missing_reset_time_does_not_split_a_window():
    result = fc.tokens_per_percent([s(0, 10, 1000), s(15, 12, None), s(35, 14, 1000)], EVENTS)
    assert result.pairs == 2


def test_pairs_with_no_logged_tokens_are_dropped():
    result = fc.tokens_per_percent([s(0, 10), s(15, 12), s(41, 1), s(100, 3)], EVENTS)
    assert result.pairs == 1 and result.value == 50


def test_ratios_far_from_the_median_are_dropped():
    events = [(i * 10 + 5, 100) for i in range(40)]
    samples = [s(0, 0), s(10, 2), s(20, 4), s(30, 6), s(40, 8), s(50, 10), s(400, 12)]
    result = fc.tokens_per_percent(samples, events)
    assert result.pairs == 5 and result.value == 50


def test_without_a_usable_pair_there_is_no_estimate():
    assert fc.tokens_per_percent([], EVENTS) is None
    assert fc.tokens_per_percent([s(0, 10)], EVENTS) is None
    assert fc.tokens_per_percent([s(0, 10), s(15, 11)], EVENTS) is None
    assert fc.tokens_per_percent([s(0, 10), s(15, 12)], []) is None
