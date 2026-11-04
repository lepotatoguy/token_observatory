from unittest.mock import Mock, patch

from backend.services import providers
from backend.services.store import Store
from backend.models.snapshot import UsageSnapshot


def isolated_store(tmp_path, **kwargs):
    settings = providers.Settings(tmp_path / 'providers.json')
    settings.update({'enabled': {'codex': True, 'claude': True}})
    return Store(tmp_path / 'codex', tmp_path / 'claude', settings=settings,
                 lmstudio_folder=tmp_path / 'lmstudio', detect_providers=False, **kwargs)


def test_read_reuses_snapshot_and_retains_disabled_recordings(tmp_path):
    path = tmp_path / 'claude' / 'projects' / 'test' / 'chat.jsonl'
    path.parent.mkdir(parents=True)
    path.write_text('{"type":"assistant","timestamp":"2026-11-03T00:00:00Z",'
                    '"sessionId":"chat","message":{"id":"reply","model":"claude-opus-4-1",'
                    '"usage":{"input_tokens":10,"output_tokens":2}}}\n')
    store = isolated_store(tmp_path)
    store.settings.update({'enabled': {'codex': False, 'claude': False}})
    with patch('backend.services.store.minimax_code.read', return_value=([], [], [])):
        first = store.read()
        second = store.read()
    assert first is second
    assert first['sessions'][0]['totals']['total'] == 12
    assert first['providers']['enabled'] == []
    UsageSnapshot.model_validate(first)


def test_refresh_live_checks_enabled_tools_and_reuses_recent_check(tmp_path):
    check = Mock(return_value={'checked_at': 100, 'errors': {}, 'claude': None, 'codex': None})
    store = isolated_store(tmp_path, live_check=check, live_tools={'codex': 'synthetic-codex'})
    with patch('backend.services.store.minimax_code.read', return_value=([], [], [])), \
            patch('backend.services.store.time.time', return_value=100):
        store.refresh_live()
        store.refresh_live()
    check.assert_called_once()
    assert check.call_args.args[0] == {'codex': 'synthetic-codex'}
