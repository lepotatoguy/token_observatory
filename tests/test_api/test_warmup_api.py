from unittest.mock import Mock


def test_defaults_are_off(client):
    body = client.get('/api/warmup').json
    assert body['message'] == 'hello'
    assert set(body['providers']) == {'claude', 'codex', 'minimax'}
    assert all(row['enabled'] is False and row['times'] == [] for row in body['providers'].values())
    assert body['providers']['minimax']['unavailable']


def test_saving_a_schedule_sorts_the_times_and_reports_the_next_slot(client):
    body = client.post('/api/warmup', json=dict(provider='claude', enabled=True, times=['18:00', '07:30'])).json
    row = body['providers']['claude']
    assert row['enabled'] is True and row['times'] == ['07:30', '18:00'] and row['next']
    assert client.get('/api/warmup').json['providers']['claude']['times'] == ['07:30', '18:00']


def test_bad_schedules_are_rejected_without_changing_anything(client):
    good = dict(provider='codex', enabled=True, times=['06:00'])
    assert client.post('/api/warmup', json=good).status_code == 200
    bad = [dict(provider='codex', enabled=True, times=['6:00']),
           dict(provider='codex', enabled=True, times=['06:00', '06:00']),
           dict(provider='codex', enabled=True, times=[f'0{i}:00' for i in range(9)]),
           dict(provider='codex', enabled=True, times=[]),
           dict(provider='gemini', enabled=True, times=['06:00']),
           dict(provider='codex', enabled='yes', times=['06:00']),
           dict(provider='codex', enabled=True),
           dict(provider='codex', enabled=True, times=['06:00'], model='--help'),
           dict(provider='codex', enabled=True, times=['06:00'], extra=1)]
    for payload in bad:
        assert client.post('/api/warmup', json=payload).status_code == 400, payload
    assert client.post('/api/warmup', json=[1]).status_code == 400
    assert client.get('/api/warmup').json['providers']['codex']['times'] == ['06:00']


def test_transport_limits_apply(client):
    assert client.post('/api/warmup', data='x').status_code == 415
    assert client.post('/api/warmup', json=dict(provider='claude', enabled=False, times=[], pad='x' * 2000)).status_code == 413


def test_the_scheduler_runs_from_the_collector_loop(app):
    app.extensions['warmup'].tick = Mock(return_value=[])
    (job,) = [callback for callback, interval in app.extensions['runtime'].jobs() if interval == 30]
    app.extensions['warmup'].tick.assert_not_called()
    job()
    app.extensions['warmup'].tick.assert_called_once_with()


def test_stopping_the_collector_terminates_a_running_send(app):
    app.extensions['warmup_sender'].stop = Mock()
    app.extensions['proxies'].stop = Mock()
    app.extensions['runtime'].stop()
    app.extensions['warmup_sender'].stop.assert_called_once()


def test_snapshot_reports_no_deferral_by_default(client):
    assert all(row['deferred'] is None for row in client.get('/api/warmup').json['providers'].values())
