from backend.services import float_model

MISSING = object()


def payload(**overrides):
    base = dict(at=1759620000.0, checked_at=1759619000.0, providers=[], errors={})
    base.update(overrides)
    return base


def provider(name='Codex', key='codex', model='gpt-6.1-sol', session=MISSING, weekly=MISSING):
    default_session = dict(used_percent=90.0, window_minutes=300)
    default_weekly = dict(used_percent=42.0, window_minutes=10080)
    return dict(provider=key, name=name, model=model,
                session=default_session if session is MISSING else session,
                weekly=default_weekly if weekly is MISSING else weekly)


def test_rows_carry_the_name_model_and_accent():
    rows = float_model.rows(payload(providers=[provider()]))
    assert len(rows) == 1
    row = rows[0]
    assert row['name'] == 'Codex'
    assert row['model'] == 'gpt-6.1-sol'
    assert row['accent'] == float_model.ACCENTS['codex']


def test_each_account_has_its_own_accent():
    rows = float_model.rows(payload(providers=[provider(), provider(key='claude', name='Claude Code', model='Auto')]))
    assert [row['accent'] for row in rows] == [float_model.ACCENTS['codex'], float_model.ACCENTS['claude']]


def test_an_unknown_account_falls_back_to_the_default_accent():
    rows = float_model.rows(payload(providers=[provider(key='other', name='Other')]))
    assert rows[0]['accent'] == float_model.DEFAULT_ACCENT


def test_meters_are_labelled_session_and_weekly():
    rows = float_model.rows(payload(providers=[provider()]))
    assert [meter['label'] for meter in rows[0]['meters']] == [float_model.SESSION, float_model.WEEKLY]
    assert rows[0]['meters'][0]['used_percent'] == 90.0
    assert rows[0]['meters'][1]['used_percent'] == 42.0


def test_a_missing_window_is_left_out():
    rows = float_model.rows(payload(providers=[provider(weekly=None)]))
    assert [meter['label'] for meter in rows[0]['meters']] == [float_model.SESSION]


def test_the_provider_prefix_is_dropped_from_the_model():
    rows = float_model.rows(payload(providers=[provider(key='minimax', name='MiniMax',
                                                        model='minimax/MiniMax-M3.1-Flash')]))
    assert rows[0]['model'] == 'MiniMax-M3.1-Flash'


def test_a_model_without_a_prefix_is_kept():
    rows = float_model.rows(payload(providers=[provider(model='gpt-6.1-sol')]))
    assert rows[0]['model'] == 'gpt-6.1-sol'


def test_percent_text():
    assert float_model.percent_text(90.0) == '90%'
    assert float_model.percent_text(42.4) == '42%'
    assert float_model.percent_text(None) == '—'


def test_message_when_the_collector_is_silent():
    assert float_model.message(payload(checked_at=None)) == 'Waiting for the collector…'


def test_message_when_no_quota_was_recorded():
    assert float_model.message(payload(checked_at=1759619000.0)) == 'No account quota recorded yet.'


def test_message_reports_a_failed_check():
    text = float_model.message(payload(errors={'claude': 'signed out'}))
    assert 'claude' in text and 'signed out' in text


def test_message_is_empty_when_there_is_something_to_show():
    assert float_model.message(payload(providers=[provider()])) is None
