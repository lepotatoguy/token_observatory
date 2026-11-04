from unittest.mock import Mock

import pytest

from backend.api import routes
from backend.launcher import healthy, main


def test_factory_starts_no_workers(app):
    assert app.extensions['runtime'].threads == []
    assert app.extensions['store'].snapshot is None


def test_usage_refresh_pricing_contract(client, app):
    app.extensions['store'].read = Mock(return_value={'sessions': [], 'total': 42})
    app.extensions['store'].refresh_live = Mock(return_value={'checked_at': 17})
    app.extensions['pricing'].snapshot = Mock(return_value={'prices': {}})
    assert client.get('/api/usage').json == {'sessions': [], 'total': 42}
    assert client.post('/api/refresh', json={}).json == {'checked_at': 17}
    assert client.get('/api/pricing').json == {'prices': {}}


def test_history_validation(client, app):
    archive = app.extensions['store'].archive
    archive.load = Mock(return_value={'day': '2026-11-03'})
    assert client.get('/api/history/2026-11-03').json['day'] == '2026-11-03'
    archive.load.side_effect = FileNotFoundError
    assert client.get('/api/history/2026-11-02').status_code == 404
    archive.load.side_effect = ValueError('Invalid day')
    assert client.get('/api/history/nope').status_code == 400
    assert client.get('/api/history/../../etc/passwd').status_code == 404


@pytest.mark.parametrize('route', ['/refresh', '/providers', '/limit-control', '/update/settings', '/update/install'])
def test_object_payload_required(client, route):
    assert client.post('/api' + route, json=[]).status_code == 400
    assert client.post('/api' + route, data='{', content_type='application/json').status_code == 400


def test_limit_validation_and_persistence(client):
    assert client.post('/api/limit-control', json={'codex': {'warn': 80, 'hard': 90}}).status_code == 200
    assert client.post('/api/limit-control', json={'codex': {'warn': 95, 'hard': 90}}).status_code == 400
    assert client.post('/api/limit-control', json={'unknown': True}).status_code == 400


def test_provider_validation_and_status(client, app, monkeypatch):
    monkeypatch.setattr(routes.providers, 'detect', lambda *a, **k: {'claude': True})
    monkeypatch.setattr(routes.local_proxy, 'reachable', lambda *a: False)
    app.extensions['proxies'].apply = Mock()
    assert client.post('/api/providers', json={'enabled': {'codex': 'yes'}}).status_code == 400
    response = client.post('/api/providers', json={'enabled': {'codex': False}})
    assert response.status_code == 200
    assert {'settings', 'enabled', 'detected', 'local', 'minimax'} <= response.json.keys()
    assert response.json['settings']['enabled']['codex'] is False
    app.extensions['proxies'].apply.assert_called_once()


def test_update_routes(client, app):
    updates = app.extensions['updates']
    updates.set_preferences = Mock(return_value={'notify': False})
    updates.start = Mock(return_value={'state': 'installing'})
    assert client.post('/api/update/settings', json={'notify': 'no'}).status_code == 400
    assert client.post('/api/update/settings', json={'notify': False}).json == {'notify': False}
    assert client.post('/api/update/install', json={}).json == {'state': 'installing'}


def test_spa_assets_and_api_404(client, app, tmp_path):
    folder = app.config['FRONTEND_DIST']
    # Config's Path can point at the shared build; do not mutate it.
    assert client.get('/api/missing').status_code == 404
    assert client.get('/api').status_code == 404
    assert client.get('/../../pyproject.toml').status_code == 404


def test_cli_flags_do_not_start_service(monkeypatch):
    from backend import launcher
    monkeypatch.setattr(launcher, 'serve', lambda port: port)
    assert main(['--serve', '--port', '9876']) == 9876
    monkeypatch.setattr(launcher, 'stop_collector', lambda url: 0)
    assert main(['--stop', '--no-open']) == 0


def test_runtime_start_stop(app, monkeypatch):
    import threading
    monkeypatch.setattr(routes, 'provider_status', lambda ext: {})
    ext = app.extensions
    ext['store'].read = Mock(return_value={})
    ext['pricing'].update = Mock()
    ext['proxies'].apply = Mock()
    ext['proxies'].stop = Mock()
    runtime = ext['runtime']
    runtime.start()
    threads = list(runtime.threads)
    assert len(threads) == 2
    runtime.start()
    assert runtime.threads == threads
    runtime.stop()
    assert not any(worker.is_alive() for worker in threads)
    assert runtime.threads == []
    ext['store'].read.assert_called_with(force_save=True)
    ext['proxies'].stop.assert_called_once()


def test_spa_serves_built_assets(tmp_path):
    from backend.app import create_app
    from backend.config import Config
    folder = tmp_path / 'dist'
    folder.mkdir()
    (folder / 'index.html').write_text('<h1>Dashboard</h1>')
    (folder / 'app.js').write_text('console.log(1)')
    app = create_app(Config(DATA_DIR=tmp_path / 'history', CODEX_HOME=tmp_path / 'codex',
                            CLAUDE_HOME=tmp_path / 'claude', FRONTEND_DIST=folder,
                            LIVE_CHECKS=False, UPDATE_CHECKS=False))
    app.config['SERVER_NAME'] = f"127.0.0.1:{app.config['PORT']}"
    client = app.test_client()
    assert client.get('/').data == b'<h1>Dashboard</h1>'
    assert client.get('/dashboard/settings').status_code == 200
    assert client.get('/app.js').data == b'console.log(1)'
    assert client.get('/missing.js').status_code == 404
    assert client.get('/api/missing').status_code == 404


def test_health_accepts_flask_json_spacing(monkeypatch):
    from backend import launcher
    from io import BytesIO
    class Response(BytesIO):
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()
    monkeypatch.setattr(launcher.LOCAL, 'open', lambda *a, **k: Response(b'{"app": "token-observatory", "version": 2}'))
    assert healthy('http://127.0.0.1:8766')


def test_launcher_serve_lifecycle(monkeypatch, tmp_path):
    from backend import launcher
    from backend.config import Config
    from backend import app as app_module
    import werkzeug.serving
    config = Config(PORT=9123, DATA_DIR=tmp_path / 'history', CODEX_HOME=tmp_path / 'codex',
                    CLAUDE_HOME=tmp_path / 'claude', CLAUDE_PLAN_FILE=tmp_path / 'plan.json',
                    LIVE_CHECKS=False, UPDATE_CHECKS=False)
    runtime, server = Mock(), Mock()
    fake_app = Mock(extensions={'runtime': runtime})
    monkeypatch.setattr(app_module, 'create_app', lambda config: fake_app)
    factory = Mock(return_value=server)
    monkeypatch.setattr(werkzeug.serving, 'make_server', factory)
    assert launcher.serve(9123, config) == 0
    factory.assert_called_once_with('127.0.0.1', 9123, fake_app, threaded=True)
    runtime.start.assert_called_once()
    runtime.stop.assert_called_once()
    server.server_close.assert_called_once()
    assert not (tmp_path / 'collector.pid').exists()
    assert (tmp_path / 'service.log').exists()


def test_factory_does_not_probe_providers(tmp_path, monkeypatch):
    from backend.app import create_app
    from backend.config import Config
    probe = Mock(side_effect=AssertionError('Provider probe during setup'))
    monkeypatch.setattr(routes.providers, 'detect', probe)
    create_app(Config(DATA_DIR=tmp_path / 'history', CODEX_HOME=tmp_path / 'codex',
                      CLAUDE_HOME=tmp_path / 'claude', LIVE_CHECKS=False, UPDATE_CHECKS=False))
    probe.assert_not_called()


def test_cli_forwards_source_paths(monkeypatch, tmp_path):
    from backend import launcher
    serve = Mock(return_value=0)
    monkeypatch.setattr(launcher, 'serve', serve)
    monkeypatch.setattr(launcher, 'PID_FILE', tmp_path / 'unused.pid')
    monkeypatch.setattr(launcher, 'LOG_FILE', tmp_path / 'unused.log')
    assert main(['--serve', '--port', '9876', '--data-dir', str(tmp_path / 'history'),
                 '--codex-home', str(tmp_path / 'codex'), '--claude-home', str(tmp_path / 'claude')]) == 0
    port, config = serve.call_args.args
    assert port == 9876
    assert config.DATA_DIR == tmp_path / 'history'
    assert config.CODEX_HOME == tmp_path / 'codex'
    assert config.CLAUDE_HOME == tmp_path / 'claude'


def test_cli_spawn_is_detached_and_preserves_paths(monkeypatch, tmp_path):
    from backend import launcher
    popen = Mock()
    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)
    launcher.spawn(9876, ['--data-dir', str(tmp_path / 'history')])
    args, kwargs = popen.call_args
    assert args[0][-5:] == ['--serve', '--port', '9876', '--data-dir', str(tmp_path / 'history')]
    assert kwargs['stdin'] == launcher.subprocess.DEVNULL
    assert kwargs.get('start_new_session') or kwargs.get('creationflags')


def test_cli_hook_modes_and_installers(monkeypatch):
    from backend import launcher
    run = Mock(return_value='reminder')
    monkeypatch.setattr(launcher.session_hooks, 'run', run)
    monkeypatch.setattr(launcher.session_hooks, 'update_hooks', Mock(return_value=[(True, 'saved')]))
    monkeypatch.setattr(launcher.claude_statusline, 'update_settings', Mock(return_value=(True, 'saved')))
    monkeypatch.setattr(launcher.claude_statusline, 'capture', Mock(return_value='status'))
    assert main(['--hook', 'minimax']) == 0
    assert run.call_args.args[1] == 'minimax'
    assert main(['--install-hooks']) == 0
    assert main(['--uninstall-hooks']) == 0
    assert main(['--install-statusline']) == 0
    assert main(['--uninstall-statusline']) == 0
    assert main(['--statusline']) == 0


def test_bind_failure_preserves_existing_pid(monkeypatch, tmp_path):
    from backend import launcher
    from backend import app as app_module
    from backend.config import Config
    import werkzeug.serving
    config = Config(PORT=9123, DATA_DIR=tmp_path / 'history', CODEX_HOME=tmp_path / 'codex',
                    CLAUDE_HOME=tmp_path / 'claude', CLAUDE_PLAN_FILE=tmp_path / 'plan.json',
                    LIVE_CHECKS=False, UPDATE_CHECKS=False)
    pid = launcher.pid_path(9123, tmp_path)
    pid.write_text(str(launcher.os.getpid()))
    monkeypatch.setattr(app_module, 'create_app', lambda config: Mock())
    monkeypatch.setattr(werkzeug.serving, 'make_server', Mock(side_effect=OSError('address in use')))
    with pytest.raises(OSError, match='address in use'):
        launcher.serve(9123, config)
    assert pid.read_text() == str(launcher.os.getpid())


def test_two_ports_stop_only_their_own_pid(monkeypatch, tmp_path):
    from backend import launcher
    monkeypatch.setattr(launcher, 'PID_FILE', tmp_path / 'collector.pid')
    first, second = launcher.pid_path(8765), launcher.pid_path(8766)
    assert first == tmp_path / 'collector.pid'
    assert second == tmp_path / 'collector-8766.pid'
    first.write_text('101')
    second.write_text('202')
    kill = Mock()
    monkeypatch.setattr(launcher.os, 'kill', kill)
    monkeypatch.setattr(launcher, 'health_identity', lambda url: {'pid': '202' if url.endswith(':8766') else '101'})
    assert launcher.stop_collector('http://127.0.0.1:8766') == 0
    kill.assert_called_once_with(202, launcher.signal.SIGTERM)
    assert first.read_text() == '101'
    assert not second.exists()
    assert launcher.stop_collector('http://127.0.0.1:8765') == 0
    assert kill.call_args.args[0] == 101


def test_stop_refuses_mismatched_pid_file(monkeypatch, tmp_path):
    from backend import launcher
    from io import BytesIO
    class Response(BytesIO):
        headers = {'X-Token-Observatory-Pid': '202'}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.close()
    monkeypatch.setattr(launcher, 'PID_FILE', tmp_path / 'collector.pid')
    launcher.pid_path(8766).write_text('101')
    monkeypatch.setattr(launcher.LOCAL, 'open', lambda *a, **k: Response(b'{"app":"token-observatory","version":2}'))
    kill = Mock()
    monkeypatch.setattr(launcher.os, 'kill', kill)
    assert launcher.stop_collector('http://127.0.0.1:8766') == 1
    kill.assert_not_called()
    assert launcher.pid_path(8766).read_text() == '101'


@pytest.mark.parametrize('value', [b'{"app":"token-observatory"}',
                                  b'{"app":"token-observatory","version":1}',
                                  b'{"app":"other","version":2}', b'[]', b'invalid'])
def test_health_rejects_wrong_contract(monkeypatch, value):
    from backend import launcher
    from io import BytesIO
    monkeypatch.setattr(launcher.LOCAL, 'open', lambda *a, **k: BytesIO(value))
    assert not launcher.healthy('http://127.0.0.1:8766')
