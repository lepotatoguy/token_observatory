from unittest.mock import Mock


def fake(app):
    widget = app.extensions['widget']
    widget.spawn = Mock(return_value=Mock(poll=Mock(return_value=None)))
    widget.available = lambda: True
    return widget


def test_widget_defaults_to_off(client, app):
    fake(app)
    body = client.get('/api/widget').json
    assert body['enabled'] is False and body['available'] is True and body['running'] is False


def test_enable_saves_and_starts(client, app):
    widget = fake(app)
    body = client.post('/api/widget', json={'enabled': True}).json
    assert body['enabled'] is True and body['starting'] is True
    assert widget.spawn.call_count == 1
    assert client.post('/api/widget', json={'enabled': False}).json['enabled'] is False


def test_rejects_bad_payloads(client, app):
    fake(app)
    assert client.post('/api/widget', json={'enabled': 'yes'}).status_code == 400
    assert client.post('/api/widget', json={}).status_code == 400
    assert client.post('/api/widget', json={'enabled': True, 'x': 1}).status_code == 400
    assert client.post('/api/widget', json=[True]).status_code == 400
    assert client.post('/api/widget', data='enabled=1').status_code == 415
    assert client.post('/api/widget', json={'enabled': True, 'pad': 'x' * 2000}).status_code == 413
    assert client.get('/api/widget').json['enabled'] is False


def test_widget_poll_marks_it_running(client, app):
    fake(app)
    app.extensions['store'].quota = Mock(return_value={})
    client.get('/api/quota')
    assert client.get('/api/widget').json['running'] is False
    client.get('/api/quota?client=widget')
    assert client.get('/api/widget').json['running'] is True


def test_reports_unavailable_runtime(client, app):
    app.extensions['widget'].available = lambda: False
    body = client.post('/api/widget', json={'enabled': True}).json
    assert body['available'] is False and body['reason']
