import datetime as dt
import json
from unittest.mock import Mock

NOW = dt.datetime.now().timestamp()


def snapshot(**extra):
    week = dict(used_percent=30.0, window_minutes=10080, resets_at=NOW + 3 * 86400)
    events = [dict(at=NOW - 3600, input=500, cached=0, write=0, output=0)]
    return dict(at=NOW, providers=dict(enabled=['claude']), limits=dict(claude=dict(secondary=week, observed_at=NOW)),
                sessions=[dict(id='claude:/private/project/chat.jsonl', provider='claude', title='Secret plan',
                               project='confidential-project', events=events)], **extra)


def test_the_endpoint_answers_with_a_budget_shape(client, app):
    app.extensions['store'].read = Mock(return_value=snapshot())
    response = client.get('/api/forecast')
    body = response.json
    assert response.status_code == 200
    assert {'date', 'generated_at', 'total', 'warnings', 'providers'} <= set(body)
    claude = body['providers']['claude']
    assert {'daily', 'share', 'confidence', 'demand_method', 'shrinkage', 'backtest', 'calibration', 'calibration_pairs',
            'days_used', 'excluded', 'warnings'} <= set(claude)
    assert claude['excluded'] == 'insufficient_data' and claude['daily'] is None


def test_refresh_refits_the_model(client, app):
    app.extensions['store'].read = Mock(return_value=snapshot())
    service = app.extensions['forecast']
    calls = []
    real = service.fit
    service.fit = lambda *args: calls.append(1) or real(*args)
    client.get('/api/forecast')
    client.get('/api/forecast?refresh=1')
    assert calls == [1]


def test_a_store_without_an_archive_still_answers(client, app):
    store = app.extensions['store']
    store.archive = None
    store.read = Mock(return_value=snapshot())
    assert client.get('/api/forecast').status_code == 200


def test_the_response_and_the_saved_file_hold_no_private_fields(client, app, tmp_path):
    app.extensions['store'].read = Mock(return_value=snapshot())
    text = json.dumps(client.get('/api/forecast').json)
    saved = (tmp_path / 'forecast.json').read_text()
    for private in ('Secret plan', 'confidential-project', '/private/project', 'chat.jsonl'):
        assert private not in text and private not in saved


def test_the_endpoint_is_read_only(client):
    assert client.post('/api/forecast', json={}).status_code == 405
