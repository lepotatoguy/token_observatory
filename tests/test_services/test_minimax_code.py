import hashlib
from backend.models.snapshot import UsageSnapshot
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.services import minimax_code
from backend.services import minimax
from backend.services import providers
from backend.services import session_hooks
from backend.services.store import Store
from backend.parsers._log import Log
from backend.parsers._helpers import timestamp, tokens, total


class MiniMaxCodeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        env = patch.dict(os.environ, MINIMAX_DATA_DIR=str(self.root), MINIMAX_API_KEY='')
        env.start()
        self.addCleanup(env.stop)
        self.path = minimax_code.database()
        self.path.parent.mkdir(parents=True)
        with sqlite3.connect(str(self.path)) as connection:
            connection.executescript('''
                CREATE TABLE local_runtime_sessions (
                    session_id TEXT PRIMARY KEY, title TEXT, workspace_dir TEXT,
                    parent_session_id TEXT, created_at_ms INTEGER, updated_at_ms INTEGER);
                CREATE TABLE local_runtime_token_usage (
                    id INTEGER PRIMARY KEY, session_id TEXT, model TEXT, ts INTEGER,
                    input_tokens INTEGER, output_tokens INTEGER, reasoning_tokens INTEGER,
                    cache_read_tokens INTEGER, cache_write_tokens INTEGER);
                INSERT INTO local_runtime_sessions VALUES ('root','Native chat','/project',NULL,1000,3000);
                INSERT INTO local_runtime_sessions VALUES ('child','Worker','/project','root',2000,3000);
                INSERT INTO local_runtime_sessions VALUES ('empty','No usage','/project',NULL,2000,3000);
                INSERT INTO local_runtime_token_usage VALUES (1,'root','MiniMax-test',2000,100,10,4,50,5);
                INSERT INTO local_runtime_token_usage VALUES (2,'root','MiniMax-test',3000,20,5,1,100,0);
                INSERT INTO local_runtime_token_usage VALUES (3,'child',NULL,3000,3,2,0,0,0);
            ''')

    def test_detection_without_plan_key(self):
        self.assertEqual(minimax_code.detect(), 'MiniMax Code local runtime found')
        detected = providers.detect(self.root/'claude', self.root/'codex',
                                    probe=lambda port: False, data_dir=self.root)
        self.assertEqual(detected['minimax'], 'MiniMax Code local runtime found')

    def test_counts_timestamps_parent_and_read_only(self):
        before = hashlib.sha256(self.path.read_bytes()).digest()
        sessions, sources, warnings = minimax_code.read()
        self.assertEqual(warnings, [])
        self.assertEqual(sources, [dict(provider='minimax', path=str(self.path), files=1)])
        rows = {session['session_id']: session for session in sessions}
        root = rows['root']
        self.assertEqual(root['totals'], dict(input=120,cached=150,write=5,output=15,reasoning=5,total=290))
        self.assertEqual([event['at'] for event in root['events']], [2,3])
        self.assertEqual(root['latest_usage']['cached'], 100)
        self.assertEqual(rows['child']['conversation_id'], 'root')
        self.assertTrue(rows['child']['subagent'])
        self.assertEqual(rows['child']['model'], 'Unreported')
        self.assertEqual(rows['empty']['usage_source'], 'unavailable')
        self.assertIsNone(root['capacity'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).digest(), before)
        self.assertEqual(minimax_code.read()[0], sessions)

    def test_collector_preserves_recorded_usage_without_duplicate_imports(self):
        settings = providers.Settings(None)
        settings.update(dict(enabled={p: p == 'minimax' for p in providers.ALL}))
        store = Store(self.root/'codex', self.root/'claude', settings=settings,
                      lmstudio_folder=self.root/'lmstudio')
        result = store.read()
        UsageSnapshot.model_validate(result)
        self.assertEqual(len(result['sessions']), 3)
        self.assertEqual(sum(row['totals']['total'] for row in result['sessions']), 295)
        self.assertTrue(all(row['provider'] == 'minimax' for row in result['sessions']))
        settings.update(dict(enabled=dict(minimax=False)))
        store.scanned = float('-inf')
        self.assertEqual(store.read()['sessions'], result['sessions'])

    def test_missing_and_incompatible_database_are_safe(self):
        self.assertEqual(minimax_code.read(self.root/'missing'), ([],[],[]))
        with sqlite3.connect(str(self.path)) as connection:
            connection.execute('DROP TABLE local_runtime_token_usage')
        sessions, sources, warnings = minimax_code.read()
        self.assertEqual(sessions, [])
        self.assertEqual(len(sources), 1)
        self.assertIn('MiniMax Code: cannot read local runtime', warnings[0])

    def test_local_tracking_does_not_request_remote_quota(self):
        settings = providers.Settings(None)
        settings.update(dict(enabled={p: p == 'minimax' for p in providers.ALL}))
        store = Store(self.root/'codex', self.root/'claude', settings=settings,
                      lmstudio_folder=self.root/'lmstudio',
                      live_check=lambda tools, cwd: dict(claude=None,codex=None,errors={},checked_at=1))
        store.live = dict(minimax=dict(primary=dict(used_percent=90)),
                          errors=dict(minimax='Add your Coding Plan key'))
        with patch.object(minimax, 'usage', side_effect=AssertionError('Remote quota request')) as remote:
            result = store.refresh_live()
            self.assertEqual(session_hooks.fresh_limits('minimax', str(self.root)), {})
            remote.assert_not_called()
        self.assertNotIn('minimax', result['limits'])
        self.assertNotIn('minimax', result['live_limits']['errors'])
        self.assertEqual(len(result['sessions']), 3)


if __name__ == '__main__':
    unittest.main()
