import io
import gzip
import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import MagicMock, patch

from backend.services import minimax
from backend.services import providers
from backend.services import session_hooks
from backend.services.store import Store
from backend.parsers._log import Log
from backend.parsers._helpers import timestamp, tokens, total
from backend.parsers import local_proxy

NOW = 1793400000


def quota(**changes):
    row = dict(model_name='general', current_interval_remaining_percent=5,
               current_weekly_remaining_percent=3, start_time=NOW*1000,
               end_time=(NOW+18000)*1000, weekly_start_time=NOW*1000,
               weekly_end_time=(NOW+604800)*1000)
    row.update(changes)
    return dict(base_resp=dict(status_code=0), model_remains=[row])


class MiniMaxTests(unittest.TestCase):
    def setUp(self):
        reader = patch('backend.services.store.lmstudio_chats.Chats.read', return_value=[])
        reader.start()
        self.addCleanup(reader.stop)
        native_home = tempfile.TemporaryDirectory()
        self.addCleanup(native_home.cleanup)
        env = patch.dict(os.environ, {'MINIMAX_API_KEY': '', 'ANTHROPIC_BASE_URL': '',
                                      'MINIMAX_DATA_DIR': native_home.name})
        env.start()
        self.addCleanup(env.stop)

    def native_login(self, region='en', **changes):
        from backend.services import minimax_code
        folder = minimax_code.home() / 'auth' / 'prod' / region / 'mcode-public'
        folder.mkdir(parents=True, exist_ok=True)
        state = dict(schemaVersion=2, status='authenticated', storeKind='file',
                     clientId='mcode-public', audience='agent-backend', region=region, generation=2)
        row = dict(schemaVersion=1, clientId='mcode-public', audience='agent-backend',
                   generation=2, accessToken='synthetic-native-token', expiresAtMs=(NOW+3600)*1000)
        row.update(changes)
        (folder/'auth-state.json').write_text(json.dumps(state))
        (folder/'auth.json').write_text(json.dumps(dict(schemaVersion=1, records={'test': row})))
        return folder

    def test_native_login_quota_is_read_only_and_uses_login_endpoint(self):
        folder = self.native_login()
        before = {p.name: p.read_bytes() for p in folder.iterdir()}
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(quota()).encode()
        with patch.object(minimax.time, 'time', return_value=NOW), patch.object(
                minimax.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(minimax.status(folder.parent.parent.parent.parent), dict(configured=True, region='global'))
            result, error = minimax.usage(folder.parent.parent.parent.parent)
        self.assertIsNone(error)
        self.assertEqual(result['primary']['used_percent'], 95)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, 'https://platform.minimax.io/v1/api/openplatform/coding_plan/remains')
        self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-native-token')
        self.assertEqual(before, {p.name: p.read_bytes() for p in folder.iterdir()})

    def test_expired_or_mismatched_native_login_is_not_sent(self):
        for change in [dict(expiresAtMs=(NOW-1)*1000), dict(audience='other'), dict(generation=1),
                       dict(accessToken='bad\ntoken')]:
            self.native_login(**change)
            with patch.object(minimax.time, 'time', return_value=NOW), patch.object(
                    minimax.urllib.request, 'build_opener') as opener:
                result, error = minimax.usage(Path(os.environ['MINIMAX_DATA_DIR']))
            self.assertIsNone(result)
            self.assertTrue(error)
            opener.assert_not_called()

    def test_native_login_refuses_ambiguous_accounts_and_unsupported_state(self):
        folder = self.native_login()
        self.native_login('cn')
        with patch.object(minimax.time, 'time', return_value=NOW):
            self.assertEqual(minimax.native_credentials(), ('', 'global'))
            (folder/'auth-state.json').write_text(json.dumps(dict(schemaVersion=99)))
            self.assertEqual(minimax.native_credentials(), ('synthetic-native-token', 'cn'))

    def test_refresh_includes_minimax_and_preserves_last_good_quota(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            settings = providers.Settings(None)
            settings.update(dict(enabled={p: p == 'minimax' for p in providers.ALL}))
            live_file = root/'live-limits.json'
            store = Store(root/'codex', root/'claude', data_dir=root/'history', settings=settings,
                          live_file=live_file, live_check=lambda tools, cwd: dict(claude=None, codex=None, errors={}, checked_at=minimax.time.time()),
                          lmstudio_folder=root/'lmstudio')
            q = minimax.parse_quota(quota(), NOW)
            with patch.object(minimax, 'usage', return_value=(q, None)) as remote:
                result = store.refresh_live()
                self.assertEqual(result['limits']['minimax'], q)
                store.refresh_live()
                remote.assert_called_once()
            restored = Store(root/'codex', root/'claude', data_dir=root/'history', settings=settings,
                             live_file=live_file, lmstudio_folder=root/'lmstudio')
            self.assertEqual(restored.read()['limits']['minimax'], q)
            store.live['checked_at'] = 0
            with patch.object(minimax, 'usage', return_value=(None, 'Quota check failed')):
                result = store.refresh_live()
            self.assertEqual(result['limits']['minimax'], q)
            self.assertEqual(result['live_limits']['errors']['minimax'], 'Quota check failed')
            settings.update(dict(enabled=dict(minimax=False)))
            store.live['checked_at'] = 0
            with patch.object(minimax, 'usage') as remote:
                result = store.refresh_live()
            remote.assert_not_called()
            self.assertNotIn('minimax', result['limits'])

    def test_remaining_quota_and_independent_resets(self):
        result = minimax.parse_quota(quota(), NOW)
        self.assertEqual(result['primary']['used_percent'], 95)
        self.assertEqual(result['secondary']['used_percent'], 97)
        self.assertEqual(result['primary']['window_minutes'], 300)
        self.assertEqual(result['secondary']['window_minutes'], 10080)
        self.assertEqual(result['secondary']['resets_at'], NOW+604800)
        count = quota(current_interval_remaining_percent=None, current_interval_total_count=100,
                      current_interval_usage_count=20)
        self.assertEqual(minimax.parse_quota(count, NOW)['primary']['used_percent'], 80)
        self.assertEqual(minimax.parse_quota(quota(weekly_boost_permille=2000), NOW)['secondary']['used_percent'], 94)

    def test_invalid_or_unlimited_is_unreported(self):
        for value in (None, [], {'base_resp': []}, {'model_remains': 'bad'}, quota(model_name='video')):
            self.assertIsNone(minimax.parse_quota(value, NOW))
        result = minimax.parse_quota(quota(current_interval_status=3), NOW)
        self.assertNotIn('primary', result)
        result = minimax.parse_quota(quota(current_interval_remaining_percent=float('nan')), NOW)
        self.assertNotIn('primary', result)

    def test_private_key_status_validation_and_removal(self):
        with tempfile.TemporaryDirectory() as folder:
            minimax.configure(dict(api_key='synthetic-test-key', region='cn'), folder)
            self.assertEqual(minimax.status(folder), dict(configured=True, region='cn'))
            path = Path(folder)/'minimax.json'
            if os.name != 'nt':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            minimax.configure(dict(region='global'), folder)
            self.assertEqual(minimax.credentials(folder)[0], 'synthetic-test-key')
            self.assertNotIn('synthetic-test-key', json.dumps(minimax.status(folder)))
            for change in ({'region': []}, {'api_key': 123}, {'api_key': 'a\nb'}, {'other': 1}):
                with self.assertRaises(ValueError):
                    minimax.configure(change, folder)
            minimax.configure(dict(api_key=None), folder)
            self.assertFalse(minimax.status(folder)['configured'])

    def test_quota_request_and_errors_never_reveal_key(self):
        with tempfile.TemporaryDirectory() as folder:
            minimax.configure(dict(api_key='synthetic-test-key'), folder)
            opener = MagicMock()
            opener.open.return_value.__enter__.return_value.read.return_value = json.dumps(quota()).encode()
            with patch('backend.services.minimax.urllib.request.build_opener', return_value=opener):
                result, error = minimax.usage(folder)
                self.assertIsNone(error)
                self.assertEqual(result['primary']['used_percent'], 95)
                request = opener.open.call_args.args[0]
                self.assertEqual(request.full_url, minimax.ENDPOINTS['global'])
                self.assertEqual(request.get_header('Authorization'), 'Bearer synthetic-test-key')
                opener.open.side_effect = urllib.error.HTTPError(request.full_url, 401, 'synthetic-test-key', {}, None)
                self.assertNotIn('synthetic-test-key', minimax.usage(folder)[1])
            self.assertIsNone(minimax.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://example.com'))

    def test_model_switch_and_client_scoped_detection(self):
        with tempfile.TemporaryDirectory() as folder:
            transcript = Path(folder)/'chat.jsonl'
            transcript.write_text(json.dumps(dict(type='assistant', message=dict(model='MiniMax-M2.7')))+'\n')
            self.assertTrue(minimax.using_minimax({}, transcript))
            self.assertFalse(minimax.using_minimax(dict(model='claude-test'), transcript))
            with patch.dict(os.environ, ANTHROPIC_BASE_URL='https://api.minimax.io/anthropic'):
                self.assertTrue(minimax.using_minimax({}, None, 'claude'))
                self.assertFalse(minimax.using_minimax(dict(model='gpt-test'), None, 'codex'))

    def test_mixed_logs_totals_history_and_provider_toggle(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            logs = root/'claude'/'projects'
            logs.mkdir(parents=True)
            events = [dict(type='assistant', timestamp='2026-11-03T12:00:00Z',
                           message=dict(id=str(i), model=model, usage=dict(input_tokens=count, output_tokens=2)))
                      for i, (model, count) in enumerate([('claude-test', 3), ('MiniMax-M2.7', 7)])]
            (logs/'chat.jsonl').write_text('\n'.join(map(json.dumps, events))+'\n')
            settings = providers.Settings(root/'providers.json')
            settings.update(dict(enabled=dict(claude=True, codex=False, minimax=True)))
            minimax.configure(dict(api_key='synthetic-test-key'), root)
            store = Store(root/'codex', root/'claude', data_dir=root/'history', settings=settings,
                          lmstudio_folder=root/'lmstudio')
            result = store.read()
            self.assertEqual({s['provider']: s['totals']['total'] for s in result['sessions']}, dict(claude=5, minimax=9))
            self.assertNotIn('synthetic-test-key', json.dumps(result))
            archived = gzip.decompress(next((root/'history').glob('*.json.gz')).read_bytes()).decode()
            self.assertNotIn('synthetic-test-key', archived)
            settings.update(dict(enabled=dict(claude=False, minimax=False)))
            store.scanned = float('-inf')
            self.assertEqual(store.read()['sessions'], result['sessions'])
            archived = store.archive.load(result['archive']['dates'][0])['sessions']
            self.assertEqual({s['provider']: s['totals']['total'] for s in archived}, dict(claude=5, minimax=9))

    def test_minimax_hook_uses_its_own_quota_and_policy(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'limit-settings.json').write_text(json.dumps(dict(minimax=dict(warn=None, hard=95, weekly_reserve=3))))
            snapshot = minimax.parse_quota(quota(current_interval_remaining_percent=80), NOW)
            Path(folder, 'live-limits.json').write_text(json.dumps(dict(minimax=snapshot)))
            payload = dict(session_id='mm', model='MiniMax-M2.7', hook_event_name='PreToolUse')
            with patch('backend.services.session_hooks.fresh_limits', return_value={}):
                result = json.loads(session_hooks.run(io.StringIO(json.dumps(payload)), 'claude', folder, None, NOW))
            self.assertEqual(result['hookSpecificOutput']['permissionDecision'], 'deny')
            self.assertIn('MiniMax', result['systemMessage'])
            self.assertIn('weekly remaining quota falls to 3% or less (weekly usage 97% or more)', result['hookSpecificOutput']['additionalContext'])



if __name__ == '__main__':
    unittest.main()
