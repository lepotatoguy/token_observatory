import pytest

from backend.services import forecast_calibrate as fc
from backend.services import forecast_weights as fw
from backend.services.forecast_history import Sample

TRUE = (3.0, 0.1, 1.5, 40.0)  # Percent per million tokens: input, cached, write, output.


def vector(i):
    """Deterministic token mixes (millions) that differ enough to tell the four types apart."""
    return (1 + (i * 7) % 5, 5 + (i * 3) % 11, 0.2 * (1 + i % 4), 0.5 + ((i * 5) % 7) * 0.3)


def made(count, weights=TRUE, noise=0.0):
    pairs = []
    for i in range(count):
        tokens = vector(i)
        rise = sum(w * t for w, t in zip(weights, tokens)) + noise * ((i * 37) % 5 - 2)
        pairs.append(fw.Pair(float(i), rise, tokens))
    return pairs


def s(t, percent, resets_at=None):
    return Sample(float(t), percent, resets_at)


# 1 million tokens of each type at times 10, 20, 30, 40, as (seconds, input, cached, write, output) rows.
TYPED = [(10, 1e6, 0, 0, 0), (20, 0, 2e6, 0, 0), (30, 0, 0, 3e6, 0), (40, 0, 0, 0, 4e6)]


def test_pairs_carry_millions_of_tokens_by_type_and_the_rise():
    pairs = fw.typed_pairs([s(0, 10), s(25, 14)], TYPED)
    assert len(pairs) == 1
    assert pairs[0].rise == 4 and pairs[0].tokens == (1.0, 2.0, 0.0, 0.0) and pairs[0].t_end == 25.0


def test_pairs_use_the_same_window_rule_and_drop_empty_and_outlier_pairs():
    assert len(fw.typed_pairs([s(0, 50), s(15, 52), s(16, 3), s(35, 5)], TYPED)) == 2   # A drop starts a new window.
    assert len(fw.typed_pairs([s(0, 10), s(5, 12)], TYPED)) == 0                          # No tokens between the readings.
    typed = [(i * 10 + 5, 1e6, 0, 0, 0) for i in range(40)]
    samples = [s(0, 0), s(10, 2), s(20, 4), s(30, 6), s(40, 8), s(50, 10), s(400, 12)]
    assert len(fw.typed_pairs(samples, typed)) == 5                                       # The 4x-median outlier is dropped.


def test_pairs_come_back_in_time_order():
    pairs = fw.typed_pairs([s(0, 10), s(15, 12), s(35, 18)], TYPED)
    assert [p.t_end for p in pairs] == sorted(p.t_end for p in pairs)


def test_the_single_ratio_matches_the_existing_calibration():
    samples = [s(0, 10), s(15, 12), s(35, 18)]
    events = [(at, sum(row)) for at, *row in TYPED]
    old = fc.tokens_per_percent(samples, events).value
    pairs = fw.typed_pairs(samples, TYPED)
    assert fw.single_tokens_per_percent(pairs) == pytest.approx(old)


def test_nnls_recovers_known_weights_exactly():
    weights = fw.fit_nnls(made(12))
    assert weights == pytest.approx(TRUE, rel=1e-4)  # The tiny ridge term shifts the result by about 1e-6.


def test_a_negative_true_weight_is_clipped_to_zero_and_all_weights_stay_non_negative():
    weights = fw.fit_nnls(made(30, weights=(2.0, -0.5, 1.0, 30.0)))
    assert weights[1] == 0 and min(weights) >= 0


def test_a_type_with_no_tokens_gets_zero_weight():
    pairs = [fw.Pair(p.t_end, 3.0 * p.tokens[0] + 20.0 * p.tokens[3], (p.tokens[0], p.tokens[1], 0.0, p.tokens[3])) for p in made(12)]
    assert fw.fit_nnls(pairs)[2] == 0


def test_the_fit_is_deterministic_and_empty_input_gives_none():
    pairs = made(15, noise=0.4)
    assert fw.fit_nnls(pairs) == fw.fit_nnls(list(pairs))
    assert fw.fit_nnls([]) is None


def test_leave_one_out_error_of_the_single_ratio_matches_a_hand_computation():
    pairs = [fw.Pair(float(i), rise, (1.0, 0.0, 0.0, 0.0)) for i, rise in enumerate((2, 4, 6))]
    errors = fw.loo_errors(pairs)
    assert errors.single == pytest.approx(2.0) and errors.by_type is None


def test_the_by_type_error_is_computed_only_with_twenty_pairs():
    assert fw.loo_errors(made(19)).by_type is None
    assert fw.loo_errors(made(20, noise=0.3)).by_type is not None


def test_distinct_type_costs_choose_the_by_type_fit():
    result = fw.choose(made(25))
    assert result.kind == 'by_type' and result.pairs == 25
    assert result.weights == pytest.approx(TRUE, rel=1e-4)
    assert result.loo_by_type <= 0.9 * result.loo_single


def test_fewer_than_twenty_pairs_keep_the_single_ratio():
    result = fw.choose(made(19))
    assert (result.kind, result.weights, result.loo_by_type) == ('single', None, None)


def test_types_that_cannot_be_told_apart_keep_the_single_ratio():
    pairs = []
    for i in range(25):
        scale = 1 + (i * 7) % 9
        tokens = (0.9 * scale, 0.05 * scale, 0.0, 0.05 * scale)
        pairs.append(fw.Pair(float(i), 3.0 * scale + 0.5 * ((i * 37) % 5 - 2), tokens))
    result = fw.choose(pairs)
    assert result.kind == 'single' and result.loo_by_type is not None and result.loo_by_type > 0.9 * result.loo_single


def test_a_provider_with_no_pairs_has_no_choice():
    assert fw.choose([]) is None


import datetime as dt

TODAY = dt.date(2026, 11, 6)


def row(days_ago, input=0.0, cached=0.0, write=0.0, output=0.0, hour=12):
    at = dt.datetime.combine(TODAY - dt.timedelta(days=days_ago), dt.time(hour)).timestamp()
    return (at, input, cached, write, output)


def test_the_recent_mix_covers_the_seven_local_days_before_today():
    typed = sorted([row(8, input=100), row(7, input=1, hour=0), row(3, cached=2), row(1, output=1), row(0, output=500)])
    assert fw.recent_mix(fw.Index(typed), TODAY) == pytest.approx((0.25, 0.5, 0.0, 0.25))


def test_the_recent_mix_is_none_without_tokens_in_the_window():
    assert fw.recent_mix(fw.Index([]), TODAY) is None
    assert fw.recent_mix(fw.Index([row(30, input=5), row(0, input=5)]), TODAY) is None


def test_the_pairs_mix_is_the_share_of_each_type_over_all_pairs():
    pairs = [fw.Pair(0.0, 1.0, (1.0, 1.0, 0.0, 0.0)), fw.Pair(1.0, 1.0, (0.0, 2.0, 0.0, 0.0))]
    assert fw.pairs_mix(pairs) == pytest.approx((0.25, 0.75, 0.0, 0.0))
    assert fw.pairs_mix([fw.Pair(0.0, 1.0, (0.0, 0.0, 0.0, 0.0))]) is None


def test_effective_tokens_per_percent_is_one_over_the_weighted_mix():
    assert fw.effective_tokens_per_percent(TRUE, (0.5, 0.5, 0.0, 0.0)) == pytest.approx(1e6 / 1.55)
    assert fw.effective_tokens_per_percent((0.0,) * 4, (0.25,) * 4) is None
    assert fw.effective_tokens_per_percent(TRUE, (0.0, 0.0, 0.0, 0.0)) is None
