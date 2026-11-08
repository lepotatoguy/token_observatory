import datetime as dt
import json

import pytest

from backend.services import warmup
from backend.services.warmup import Warmup


class Sender:
    def __init__(self, ok=True, reason=''):
        self.calls, self.result, self.boom = [], (ok, reason), None

    def __call__(self, provider, model):
        self.calls.append((provider, model))
        if self.boom:
            raise self.boom
        return self.result


def at(text):
    return dt.datetime.strptime(text, '%Y-%m-%d %H:%M:%S')


def make(tmp_path, sender=None, windows=None, enabled_at='2026-11-06 06:00:00'):
    sender = sender or Sender()
    windows = windows if windows is not None else {}
    service = Warmup(tmp_path, sender, lambda provider: windows.get(provider))
    return service, sender, windows


def enable(service, provider='claude', times=('07:30',), when='2026-11-06 06:00:00', model=None):
    return service.update(dict(provider=provider, enabled=True, times=list(times), model=model), now=at(when))


# Validation ---------------------------------------------------------------

@pytest.mark.parametrize('payload', [
    dict(provider='gemini', enabled=True, times=['07:30']),
    dict(provider='claude', enabled='yes', times=['07:30']),
    dict(provider='claude', enabled=True, times=['7:30']),
    dict(provider='claude', enabled=True, times=['24:00']),
    dict(provider='claude', enabled=True, times=['07:60']),
    dict(provider='claude', enabled=True, times=['07:30', '07:30']),
    dict(provider='claude', enabled=True, times=[f'0{i}:00' for i in range(9)]),
    dict(provider='claude', enabled=True, times=[]),
    dict(provider='claude', enabled=True, times='07:30'),
    dict(provider='claude', enabled=True, times=[730]),
    dict(provider='claude', enabled=True, times=['07:30'], model='bad model; rm'),
    dict(provider='claude', enabled=True, times=['07:30'], model='x' * 65),
    dict(provider='claude', enabled=True, times=['07:30'], model='--help'),
])
def test_invalid_updates_are_rejected_and_change_nothing(tmp_path, payload):
    service, _, _ = make(tmp_path)
    before = service.snapshot(at('2026-11-06 06:00:00'))
    with pytest.raises(ValueError):
        service.update(payload, now=at('2026-11-06 06:00:00'))
    assert service.snapshot(at('2026-11-06 06:00:00')) == before


def test_defaults_are_off_with_no_times(tmp_path):
    service, _, _ = make(tmp_path)
    snapshot = service.snapshot(at('2026-11-06 06:00:00'))
    assert snapshot['message'] == 'hello'
    assert set(snapshot['providers']) == {'claude', 'codex', 'minimax'}
    for row in snapshot['providers'].values():
        assert row['enabled'] is False and row['times'] == [] and row['next'] is None


def test_times_are_saved_sorted_and_survive_a_restart(tmp_path):
    service, _, _ = make(tmp_path)
    enable(service, times=('18:00', '07:30', '12:15'))
    again = Warmup(tmp_path, Sender(), lambda provider: None)
    assert again.snapshot(at('2026-11-06 06:00:00'))['providers']['claude']['times'] == ['07:30', '12:15', '18:00']


def test_disabling_without_times_is_allowed(tmp_path):
    service, _, _ = make(tmp_path)
    enable(service)
    service.update(dict(provider='claude', enabled=False, times=[]), now=at('2026-11-06 06:00:00'))
    assert service.snapshot(at('2026-11-06 06:00:00'))['providers']['claude']['enabled'] is False


# Scheduling ---------------------------------------------------------------

def test_nothing_is_sent_before_the_time(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service)
    assert service.tick(at('2026-11-06 07:29:59')) == []
    assert sender.calls == []


def test_a_due_slot_is_sent_once(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service)
    outcomes = service.tick(at('2026-11-06 07:30:10'))
    assert [(o.provider, o.slot, o.status) for o in outcomes] == [('claude', '2026-11-06 07:30', 'sent')]
    assert service.tick(at('2026-11-06 07:30:40')) == []
    assert service.tick(at('2026-11-06 09:00:00')) == []
    assert sender.calls == [('claude', None)]


def test_the_model_override_reaches_the_sender(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, model='haiku-test')
    service.tick(at('2026-11-06 07:30:10'))
    assert sender.calls == [('claude', 'haiku-test')]


def test_a_restart_does_not_resend_a_finished_slot(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service)
    service.tick(at('2026-11-06 07:30:10'))
    again = Warmup(tmp_path, sender, lambda provider: None)
    again.tick(at('2026-11-06 07:31:00'))
    assert len(sender.calls) == 1


def test_a_late_start_inside_thirty_minutes_catches_up(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service)
    outcomes = service.tick(at('2026-11-06 07:59:59'))
    assert [o.status for o in outcomes] == ['sent']


def test_thirty_minutes_late_is_missed_and_never_sent(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service)
    outcomes = service.tick(at('2026-11-06 08:00:00'))
    assert [o.status for o in outcomes] == ['missed']
    assert sender.calls == []
    assert service.tick(at('2026-11-06 08:01:00')) == []


def test_slots_before_the_schedule_was_saved_are_ignored(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, when='2026-11-06 15:00:00')
    assert service.tick(at('2026-11-06 15:00:30')) == []
    assert sender.calls == []
    assert [o.slot for o in service.tick(at('2026-11-07 07:30:05'))] == ['2026-11-07 07:30']


def test_several_times_and_providers_are_independent(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, 'claude', ('07:30', '12:30'))
    enable(service, 'codex', ('07:30',))
    first = service.tick(at('2026-11-06 07:30:10'))
    assert sorted((o.provider, o.slot) for o in first) == [('claude', '2026-11-06 07:30'), ('codex', '2026-11-06 07:30')]
    second = service.tick(at('2026-11-06 12:30:10'))
    assert [(o.provider, o.slot) for o in second] == [('claude', '2026-11-06 12:30')]
    assert len(sender.calls) == 3


def test_a_disabled_provider_is_never_sent(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service)
    service.update(dict(provider='claude', enabled=False, times=['07:30']), now=at('2026-11-06 06:30:00'))
    assert service.tick(at('2026-11-06 07:30:10')) == []
    assert sender.calls == []


def test_a_failed_send_is_recorded_and_not_retried(tmp_path):
    service, sender, _ = make(tmp_path, Sender(False, 'claude is not installed'))
    enable(service)
    outcome = service.tick(at('2026-11-06 07:30:10'))[0]
    assert (outcome.status, outcome.reason) == ('failed', 'claude is not installed')
    assert service.tick(at('2026-11-06 07:30:50')) == []
    assert len(sender.calls) == 1


def test_a_crashing_sender_becomes_a_failure(tmp_path):
    sender = Sender()
    sender.boom = RuntimeError('boom')
    service, _, _ = make(tmp_path, sender)
    enable(service)
    outcome = service.tick(at('2026-11-06 07:30:10'))[0]
    assert outcome.status == 'failed' and 'boom' in outcome.reason


def test_midnight_rollover_catches_up_yesterdays_late_slot(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, times=('23:50',), when='2026-11-06 20:00:00')
    outcomes = service.tick(at('2026-11-07 00:10:00'))
    assert [(o.slot, o.status) for o in outcomes] == [('2026-11-06 23:50', 'sent')]
    assert service.tick(at('2026-11-07 00:11:00')) == []


# Active window ------------------------------------------------------------

def window(used, resets):
    return dict(used_percent=used, window_minutes=300, resets_at=resets)


def test_an_active_window_skips_the_send(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'claude': window(12.0, now.timestamp() + 3600)})
    enable(service)
    outcome = service.tick(now)[0]
    assert outcome.status == 'skipped_active'
    assert sender.calls == []
    assert service.tick(at('2026-11-06 07:31:00')) == []


def test_a_window_with_nothing_used_is_not_active(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'codex': window(0, now.timestamp() + 3600)})
    enable(service, 'codex')
    assert service.tick(now)[0].status == 'sent'


def test_an_expired_window_is_not_active(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'claude': window(80.0, now.timestamp() - 5)})
    enable(service)
    assert service.tick(now)[0].status == 'sent'


def test_an_unknown_window_still_sends(tmp_path):
    service, sender, _ = make(tmp_path, windows={})
    enable(service)
    assert service.tick(at('2026-11-06 07:30:10'))[0].status == 'sent'


def test_a_broken_window_lookup_still_sends(tmp_path):
    def broken(provider):
        raise RuntimeError('store down')

    sender = Sender()
    service = Warmup(tmp_path, sender, broken)
    enable(service)
    assert service.tick(at('2026-11-06 07:30:10'))[0].status == 'sent'


# Daylight saving (local wall-clock time, one outcome per date and time) -------

def test_a_time_inside_the_spring_gap_is_missed_not_invented(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, times=('02:30',), when='2026-03-08 00:30:00')
    # The clock jumps from 01:59 to 03:00, so the first tick after the gap is 30 minutes past 02:30.
    assert [o.status for o in service.tick(at('2026-03-08 03:00:10'))] == ['missed']
    assert sender.calls == []


def test_a_time_just_after_the_gap_still_catches_up(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, times=('02:45',), when='2026-03-08 00:30:00')
    assert [o.status for o in service.tick(at('2026-03-08 03:00:10'))] == ['sent']


def test_a_repeated_hour_in_autumn_sends_once(tmp_path):
    service, sender, _ = make(tmp_path)
    enable(service, times=('01:30',), when='2026-11-01 00:30:00')
    assert [o.status for o in service.tick(at('2026-11-01 01:30:10'))] == ['sent']
    assert service.tick(at('2026-11-01 01:31:00')) == []  # the clock falls back and 01:30 happens again
    assert len(sender.calls) == 1


# State --------------------------------------------------------------------

def test_only_the_last_two_hundred_outcomes_are_kept(tmp_path):
    service, _, _ = make(tmp_path)
    enable(service, times=('00:00',), when='2020-01-01 00:00:00')
    day = at('2020-01-02 00:00:05')
    for _ in range(230):
        service.tick(day)
        day += dt.timedelta(days=1)
    kept = json.loads((tmp_path / 'warmup-state.json').read_text())['outcomes']
    assert len(kept) == 200
    assert kept[-1]['slot'] == (day - dt.timedelta(days=1)).strftime('%Y-%m-%d') + ' 00:00'


def test_a_corrupt_state_file_is_set_aside_not_fatal(tmp_path):
    (tmp_path / 'warmup-state.json').write_text('{nope')
    service, sender, _ = make(tmp_path)
    enable(service)
    assert service.tick(at('2026-11-06 07:30:10'))[0].status == 'sent'
    assert (tmp_path / 'warmup-state.json.bad').read_text() == '{nope'


def test_a_corrupt_config_file_means_everything_off(tmp_path):
    (tmp_path / 'warmup.json').write_text('[1]')
    service, sender, _ = make(tmp_path)
    assert service.tick(at('2026-11-06 07:30:10')) == []


# Snapshot -----------------------------------------------------------------

def test_next_slot_is_today_or_tomorrow(tmp_path):
    service, _, _ = make(tmp_path)
    enable(service, times=('07:30', '18:00'))
    row = lambda now: service.snapshot(at(now))['providers']['claude']['next']
    assert row('2026-11-06 06:00:00') == '2026-11-06 07:30'
    assert row('2026-11-06 07:30:00') == '2026-11-06 18:00'
    assert row('2026-11-06 19:00:00') == '2026-11-07 07:30'


def test_snapshot_lists_the_last_ten_outcomes_newest_first(tmp_path):
    service, _, _ = make(tmp_path)
    enable(service, times=('07:30',), when='2026-11-01 00:00:00')
    for day in range(2, 16):
        service.tick(at(f'2026-11-{day:02d} 07:30:05'))
    last = service.snapshot(at('2026-11-16 00:00:00'))['providers']['claude']['last']
    assert len(last) == 10
    assert last[0]['slot'] == '2026-11-15 07:30' and last[-1]['slot'] == '2026-11-06 07:30'
    assert set(last[0]) == {'slot', 'at', 'status', 'reason'}


def test_unavailable_senders_are_reported(tmp_path):
    class Unavailable(Sender):
        def unavailable(self, provider):
            return 'not set up' if provider == 'minimax' else None

    service, _, _ = make(tmp_path, Unavailable())
    providers = service.snapshot(at('2026-11-06 06:00:00'))['providers']
    assert providers['minimax']['unavailable'] == 'not set up'
    assert providers['claude']['unavailable'] is None


# Exhausted limit: wait for the reset, then send one minute later ----------------

def full(resets):
    return dict(used_percent=100.0, window_minutes=300, resets_at=resets)


def test_an_exhausted_window_defers_the_send_to_one_minute_after_its_reset(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, windows = make(tmp_path, windows={'claude': full(reset)})
    enable(service)
    assert service.tick(now) == []
    assert sender.calls == []
    row = service.snapshot(now)['providers']['claude']
    expected = dt.datetime.fromtimestamp(reset + 60).strftime('%Y-%m-%d %H:%M')
    assert row['deferred'] == dict(slot='2026-11-06 07:30', send_at=expected)
    assert row['last'] == []


def test_the_deferred_message_goes_out_one_minute_after_the_reset(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, windows = make(tmp_path, windows={'claude': full(reset)})
    enable(service)
    service.tick(now)
    assert service.tick(dt.datetime.fromtimestamp(reset + 59)) == []
    windows['claude'] = dict(used_percent=0, window_minutes=300, resets_at=reset + 18000)
    outcomes = service.tick(dt.datetime.fromtimestamp(reset + 60))
    assert [(o.slot, o.status, o.reason) for o in outcomes] == [('2026-11-06 07:30', 'sent', 'after the limit reset')]
    assert sender.calls == [('claude', None)]
    assert service.snapshot(now)['providers']['claude']['deferred'] is None
    assert service.tick(dt.datetime.fromtimestamp(reset + 120)) == []
    assert len(sender.calls) == 1


def test_a_deferral_survives_a_restart(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, windows = make(tmp_path, windows={'claude': full(reset)})
    enable(service)
    service.tick(now)
    again = Warmup(tmp_path, sender, lambda provider: None)
    assert [o.status for o in again.tick(dt.datetime.fromtimestamp(reset + 61))] == ['sent']
    assert len(sender.calls) == 1


def test_a_deferral_is_set_once_not_on_every_tick(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'claude': full(now.timestamp() + 3600)})
    enable(service)
    service.tick(now)
    service.tick(now + dt.timedelta(seconds=30))
    state = json.loads((tmp_path / 'warmup-state.json').read_text())
    assert len(state['deferred']) == 1


def test_a_window_that_is_still_full_after_the_reset_waits_for_the_next_one(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, windows = make(tmp_path, windows={'claude': full(reset)})
    enable(service)
    service.tick(now)
    windows['claude'] = full(reset + 600)
    assert service.tick(dt.datetime.fromtimestamp(reset + 60)) == []
    assert sender.calls == []
    expected = dt.datetime.fromtimestamp(reset + 660).strftime('%Y-%m-%d %H:%M')
    assert service.snapshot(now)['providers']['claude']['deferred']['send_at'] == expected


def test_a_window_someone_started_in_the_meantime_skips_the_send(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, windows = make(tmp_path, windows={'claude': full(reset)})
    enable(service)
    service.tick(now)
    windows['claude'] = dict(used_percent=3.0, window_minutes=300, resets_at=reset + 17000)
    assert [o.status for o in service.tick(dt.datetime.fromtimestamp(reset + 60))] == ['skipped_active']
    assert sender.calls == []


def test_a_deferral_more_than_thirty_minutes_late_is_missed(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, _ = make(tmp_path, windows={'claude': full(reset)})
    enable(service)
    service.tick(now)
    late = dt.datetime.fromtimestamp(reset + 60 + 30 * 60)
    assert [o.status for o in service.tick(late)] == ['missed']
    assert sender.calls == []


def test_a_window_below_one_hundred_percent_is_still_just_active(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'claude': dict(used_percent=99.9, window_minutes=300, resets_at=now.timestamp() + 3600)})
    enable(service)
    assert [o.status for o in service.tick(now)] == ['skipped_active']


def test_a_full_window_that_already_reset_sends_at_once(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'claude': full(now.timestamp() - 5)})
    enable(service)
    assert [o.status for o in service.tick(now)] == ['sent']


def test_changing_or_disabling_the_provider_drops_its_deferral(tmp_path):
    now = at('2026-11-06 07:30:10')
    reset = now.timestamp() + 3600
    service, sender, _ = make(tmp_path, windows={'claude': full(reset), 'codex': full(reset)})
    enable(service)
    enable(service, 'codex', ('07:30',))
    service.tick(now)
    service.update(dict(provider='claude', enabled=False, times=['07:30']), now=now)
    snapshot = service.snapshot(now)['providers']
    assert snapshot['claude']['deferred'] is None and snapshot['codex']['deferred'] is not None
    service.tick(dt.datetime.fromtimestamp(reset + 120))
    assert not any(provider == 'claude' for provider, _ in sender.calls)


def test_one_exhausted_provider_does_not_hold_up_another(tmp_path):
    now = at('2026-11-06 07:30:10')
    service, sender, _ = make(tmp_path, windows={'claude': full(now.timestamp() + 3600)})
    enable(service, 'claude')
    enable(service, 'codex')
    outcomes = service.tick(now)
    assert [(o.provider, o.status) for o in outcomes] == [('codex', 'sent')]
