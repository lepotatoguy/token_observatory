from backend.services import quota


def snapshot(**overrides):
    """A snapshot with one account's quota and one recorded session."""
    base = dict(
        at=1759620000.0,
        sessions=[dict(provider='codex', model='gpt-6.1-sol', modified=10, subagent=False),
                  dict(provider='codex', model='gpt-6.1-terra', modified=5, subagent=False),
                  dict(provider='codex', model='Unreported', modified=20, subagent=False)],
        limits={'codex': dict(primary=dict(used_percent=15.0, window_minutes=300, resets_at=1759623600.0),
                              secondary=dict(used_percent=65.0, window_minutes=10080, resets_at=1760200000.0),
                              observed_at=1759619000.0, source='live', plan_type='plus')},
        live_limits=dict(checked_at=1759619000.0, errors={}))
    base.update(overrides)
    return base


def test_rows_pick_session_and_weekly_windows():
    rows = quota.rows(snapshot())
    assert len(rows) == 1
    row = rows[0]
    assert row['provider'] == 'codex'
    assert row['name'] == 'Codex'
    assert row['session'] == dict(used_percent=15.0, window_minutes=300, resets_at=1759623600.0)
    assert row['weekly'] == dict(used_percent=65.0, window_minutes=10080, resets_at=1760200000.0)
    assert row['plan'] == 'plus'


def test_model_label_uses_the_newest_recorded_session():
    assert quota.model_label(snapshot()['sessions'], 'codex') == 'gpt-6.1-sol'


def test_model_label_ignores_unreported_and_subagents():
    sessions = [dict(provider='claude', model='Unreported', modified=9),
                dict(provider='claude', model='claude-opus-5-5', modified=1, subagent=True)]
    assert quota.model_label(sessions, 'claude') is None


def test_model_label_without_sessions():
    assert quota.model_label([], 'codex') is None
    assert quota.model_label([dict(provider='codex')], 'codex') is None


def test_pick_falls_back_to_the_slot_when_the_duration_is_unknown():
    limits = dict(primary=dict(used_percent=40.0), secondary=dict(used_percent=80.0))
    assert quota.pick(limits, 300, 'primary')['used_percent'] == 40.0
    assert quota.pick(limits, 10080, 'secondary')['used_percent'] == 80.0


def test_pick_matches_a_window_stored_in_the_other_slot():
    limits = dict(primary=dict(used_percent=10.0, window_minutes=10080),
                  secondary=dict(used_percent=20.0, window_minutes=300))
    assert quota.pick(limits, 300, 'primary')['used_percent'] == 20.0
    assert quota.pick(limits, 10080, 'secondary')['used_percent'] == 10.0


def test_rows_skip_accounts_without_a_recorded_quota():
    assert quota.rows(snapshot(limits={})) == []


def test_payload_carries_errors_and_the_last_check():
    payload = quota.payload(snapshot(live_limits=dict(checked_at=1759619000.0,
                                                      errors={'claude': 'signed out'})))
    assert payload['checked_at'] == 1759619000.0
    assert payload['at'] == 1759620000.0
    assert payload['errors'] == {'claude': 'signed out'}
    assert payload['providers'][0]['provider'] == 'codex'


def test_payload_of_an_empty_snapshot():
    payload = quota.payload({})
    assert payload == dict(at=None, checked_at=None, providers=[], errors={})
