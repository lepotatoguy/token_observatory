import json
from pathlib import Path
import tempfile
import unittest

from archive import Archive
from server import Log, Store
from codex_usage import merge_threads


def meta(thread='root', parent=None):
    return dict(type='session_meta', payload=dict(id=thread, session_id=parent or thread,
                thread_source='subagent' if parent else 'user', parent_thread_id=parent,
                source={'subagent': {}} if parent else 'vscode'))


def record(response, thread='root', at='2026-10-17T12:00:00Z', count=100):
    return dict(type='token_usage_record', timestamp=at, payload=dict(response_id=response,
                thread_id=thread, usage=dict(input_tokens=count, cached_input_tokens=20,
                output_tokens=10, reasoning_output_tokens=4)))


def parsed(path, rows):
    log = Log(Path(path), 'codex')
    for row in rows:
        log.consume(row)
    return log.export({'root': 'One chat'})


class CodexUsageTests(unittest.TestCase):
    def test_segments_and_inherited_subagent_history_count_once(self):
        root1 = parsed('first', [meta(), record('one')])
        root2 = parsed('second', [meta(), record('one'), record('two', at='2026-10-17T12:10:00Z', count=200)])
        agent = parsed('child', [meta('child', 'root'), meta(), record('one'),
                               record('agent', 'child', count=50)])
        result = {s['session_id']: s for s in merge_threads([root1, root2, agent])}
        self.assertEqual(set(result), {'root', 'child'})
        self.assertEqual(result['root']['totals']['total'], 320)
        self.assertEqual(len(result['root']['events']), 2)
        self.assertEqual(result['root']['source_files'], ['first', 'second'])
        self.assertEqual(result['root']['latest_usage']['input'], 180)
        self.assertEqual(result['root']['context'], 210)
        self.assertEqual(result['child']['totals']['total'], 60)
        self.assertTrue(result['child']['subagent'])
        self.assertEqual(result['child']['conversation_id'], 'root')
        self.assertNotIn('_counters', result['root'])

    def test_legacy_counters_join_before_deriving_deltas(self):
        def counter(count, minute):
            return dict(type='event_msg', timestamp=f'2026-10-17T12:{minute}:00Z',
                        payload=dict(type='token_count', info=dict(total_token_usage=dict(input_tokens=count, output_tokens=10))))
        first = parsed('one', [meta(), counter(100, '00'), counter(200, '10')])
        second = parsed('two', [meta(), counter(200, '10'), counter(300, '20')])
        result = merge_threads([second, first])[0]
        self.assertEqual(result['totals']['total'], 310)
        self.assertEqual([e['input'] for e in result['events']], [100, 100, 100])

    def test_modern_records_replace_inherited_counter_baseline(self):
        rows = [meta(), dict(type='event_msg', timestamp='2026-10-17T12:00:00Z',
                payload=dict(type='token_count', info=dict(total_token_usage=dict(input_tokens=9000000)))), record('one')]
        result = merge_threads([parsed('one', rows)])[0]
        self.assertEqual(result['totals']['total'], 110)

    def test_unrelated_user_fork_keeps_its_own_identity(self):
        first = meta('fork')
        first['payload']['forked_from_id'] = 'root'
        result = merge_threads([parsed('one', [meta()]), parsed('two', [first])])
        self.assertEqual({s['conversation_id'] for s in result}, {'root', 'fork'})

    def test_incremental_store_has_stable_ids_and_latest_details(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            logs = root / 'codex/sessions'
            logs.mkdir(parents=True)
            path = logs / 'first.jsonl'
            path.write_text('\n'.join(map(json.dumps, [meta(), record('one')])) + '\n')
            store = Store(root / 'codex', root / 'claude')
            initial = store.read()['sessions'][0]
            with path.open('a') as stream:
                stream.write(json.dumps(record('two', at='2026-10-17T12:10:00Z', count=200)) + '\n')
            store.scanned = float('-inf')
            updated = store.read()['sessions'][0]
            self.assertEqual(initial['id'], updated['id'])
            self.assertEqual(updated['totals']['total'], 320)
            self.assertEqual(updated['latest_usage']['cached'], 20)

    def test_daily_archive_replaces_legacy_file_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            archive = Archive(Path(folder))
            archive.update(dict(at=1792252800, sessions=[dict(id='codex:file', source='first')]), 'old', force=True)
            new = merge_threads([parsed('first', [meta(), record('one')])])[0]
            archive.update(dict(at=1792252801, sessions=[new]), 'new', force=True)
            saved = archive.load(archive.dates()[0])
            self.assertEqual([s['id'] for s in saved['sessions']], ['codex:root'])


if __name__ == '__main__':
    unittest.main()
