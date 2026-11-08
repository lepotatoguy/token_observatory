import copy
import datetime as dt
import os
import time

import pytest

from backend.services import forecast_budget as fb

NOW = dt.datetime(2026, 11, 5, 12, 0).timestamp()  # A Thursday at noon, local time.


def local(year, month, day, hour=0):
    return dt.datetime(year, month, day, hour).timestamp()


def flat_state(k=1000.0, weights=(1.0,) * 7, provider='claude', **extra):
    entry = dict(days_used=22, confidence='normal', tokens_per_percent=k, calibration_pairs=5,
                 demand=dict(method='flat', weekday_weights=list(weights), shrinkage=0.0, backtest=None), **extra)
    return dict(generated_at=1.0, warnings=[], providers={provider: entry} if entry else {})


def snapshot(percent=40.0, resets_at=local(2026, 11, 8, 12), now=NOW, events=(), provider='claude', estimated=False, **limits):
    week = dict(used_percent=percent, window_minutes=10080, resets_at=resets_at)
    if estimated:
        week['resets_estimated'] = True
    return dict(at=now, providers=dict(enabled=[provider]),
                limits={provider: dict(primary=dict(used_percent=5, window_minutes=300, resets_at=resets_at), secondary=week, observed_at=now)},
                sessions=[dict(provider=provider, events=[dict(at=at, input=tokens, cached=0, write=0, output=0) for at, tokens in events])],
                **limits)


def entry(state, snap, now=NOW, provider='claude'):
    return fb.budget(state, snap, now)['providers'][provider]


def test_flat_weights_give_the_calibrated_even_split_over_the_days_left():
    result = entry(flat_state(), snapshot())
    assert result['remaining_capacity'] == 60000
    assert result['share'] == pytest.approx(1 / 3.5)
    assert result['daily'] == round(60000 / 3.5)
    assert (result['calibration'], result['demand_method'], result['excluded']) == ('history', 'flat', None)


def test_a_heavier_weekday_takes_a_larger_share():
    weights = (1, 1, 1, 2, 1, 1, 1)  # Thursday counts double.
    result = entry(flat_state(weights=weights), snapshot())
    assert result['share'] == pytest.approx(2 / 4.5)
    assert result['daily'] == round(60000 * 2 / 4.5)


def test_spending_today_leaves_the_budget_unchanged_and_so_does_the_time_of_day():
    before = entry(flat_state(), snapshot(percent=40))
    spent = entry(flat_state(), snapshot(percent=45, events=[(NOW - 60, 5000)]))
    later = entry(flat_state(), snapshot(percent=40, now=local(2026, 11, 5, 21)), now=local(2026, 11, 5, 21))
    assert spent['used_today'] == 5000 and spent['start_of_day_capacity'] == 60000
    assert before['daily'] == spent['daily'] == later['daily']


def test_a_spent_week_cannot_budget_more_than_was_used_today():
    result = entry(flat_state(), snapshot(percent=100, events=[(NOW - 60, 4000)]))
    assert result['remaining_capacity'] == 0
    assert result['daily'] <= 4000
    assert entry(flat_state(), snapshot(percent=130))['daily'] == 0


def test_a_window_that_began_today_counts_only_the_part_of_today_inside_it():
    started = local(2026, 11, 5, 8)
    result = entry(flat_state(), snapshot(percent=0, resets_at=started + 7 * 86400))
    assert result['share'] == pytest.approx((2 / 3) / 7)


@pytest.mark.skipif(not hasattr(time, 'tzset'), reason='the time zone cannot be switched on this platform')
@pytest.mark.parametrize('zone, now, resets', [
    ('America/New_York', (2026, 3, 7, 12), (2026, 3, 9, 0)),   # The 8th has 23 hours.
    ('America/New_York', (2026, 10, 31, 12), (2026, 11, 2, 0)),  # The 1st has 25 hours.
])
def test_a_short_or_long_daylight_saving_day_counts_as_a_whole_day(monkeypatch, zone, now, resets):
    monkeypatch.setenv('TZ', zone)
    time.tzset()
    try:
        when = local(*now)
        result = entry(flat_state(), snapshot(percent=0, resets_at=local(*resets), now=when), now=when)
        assert result['share'] == pytest.approx(1 / 2)
    finally:
        monkeypatch.undo()
        time.tzset()


def test_a_provider_without_a_weekly_window_is_excluded():
    snap = snapshot()
    snap['limits']['claude'].pop('secondary')
    assert entry(flat_state(), snap)['excluded'] == 'no_weekly_quota'
    assert entry(flat_state(), snapshot(resets_at=NOW - 10))['excluded'] == 'no_weekly_quota'
    assert entry(flat_state(), snapshot(percent=None))['excluded'] == 'no_weekly_quota'
    assert entry(flat_state(), snapshot(resets_at=None))['excluded'] == 'no_weekly_quota'


@pytest.mark.parametrize('extra', [dict(tokens_per_percent=None), dict(days_used=6), dict(calibration_pairs=1)])
def test_too_little_data_leaves_the_provider_to_the_previous_system(extra):
    state = flat_state()
    state['providers']['claude'].update(extra)
    result = entry(state, snapshot())
    assert result['excluded'] == 'insufficient_data' and result['daily'] is None


def test_the_smallest_sufficient_history_is_budgeted():
    state = flat_state()
    state['providers']['claude'].update(days_used=7, calibration_pairs=2)
    assert entry(state, snapshot())['excluded'] is None


def test_a_provider_missing_from_the_stored_state_is_left_to_the_previous_system():
    state = dict(generated_at=1.0, warnings=[], providers={})
    assert entry(state, snapshot())['excluded'] == 'insufficient_data'


def test_the_algorithm_and_its_accuracy_are_reported():
    state = flat_state()
    state['providers']['claude']['demand'].update(method='weekday_regression', shrinkage=0.5,
                                                  backtest=dict(model_mae=10.0, baseline_mae=12.0, days=8))
    result = entry(state, snapshot())
    assert result['demand_method'] == 'weekday_regression' and result['shrinkage'] == 0.5
    assert result['backtest'] == dict(model_mae=10.0, baseline_mae=12.0, days=8)
    assert result['calibration_pairs'] == 5 and result['calibration'] == 'history'


def test_an_estimated_reset_is_carried_through():
    assert entry(flat_state(), snapshot(estimated=True))['estimated'] is True
    assert entry(flat_state(), snapshot())['estimated'] is False


def test_only_enabled_providers_are_budgeted_and_the_total_adds_them_up():
    snap = snapshot()
    snap['limits']['codex'] = copy.deepcopy(snap['limits']['claude'])
    snap['providers']['enabled'] = ['claude', 'codex']
    snap['sessions'].append(dict(provider='codex', events=[]))
    state = flat_state()
    state['providers']['codex'] = copy.deepcopy(state['providers']['claude'])
    body = fb.budget(state, snap, NOW)
    assert set(body['providers']) == {'claude', 'codex'}
    assert body['total'] == sum(p['daily'] for p in body['providers'].values())
    snap['providers']['enabled'] = ['codex']
    assert set(fb.budget(state, snap, NOW)['providers']) == {'codex'}


def test_the_inputs_are_never_changed():
    state, snap = flat_state(), snapshot(events=[(NOW - 60, 100)])
    before = copy.deepcopy((state, snap))
    fb.budget(state, snap, NOW)
    assert (state, snap) == before


def test_the_body_carries_the_date_and_the_fit_time():
    body = fb.budget(flat_state(), snapshot(), NOW)
    assert body['date'] == '2026-11-05' and body['generated_at'] == 1.0


def test_the_calibration_method_and_scores_pass_through_unchanged():
    state = flat_state()
    state['providers']['claude'].update(
        calibration_model=dict(kind='by_type', weights=[1, 2, 3, 4], mix=None, readings=33, loo_single=2.0, loo_by_type=1.0),
        rolling=dict(mae_points=1.5, single_mae_points=2.0, readings=14), budget_check=dict(within=9, scored=12))
    result = entry(state, snapshot())
    assert (result['calibration_kind'], result['calibration_readings']) == ('by_type', 33)
    assert result['rolling'] == dict(mae_points=1.5, single_mae_points=2.0, readings=14)
    assert result['budget_check'] == dict(within=9, scored=12)


def test_a_state_without_the_new_keys_gives_null_scores():
    result = entry(flat_state(), snapshot())
    assert (result['calibration_kind'], result['rolling'], result['budget_check']) == (None, None, None)
    assert result['calibration_readings'] == 5
