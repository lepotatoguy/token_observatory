import json
from pathlib import Path
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from server import Handler, Log, Store, tokens, total


class AccountingTests(unittest.TestCase):
    def test_cached_input_and_reasoning_are_not_added_twice(self):
        usage = tokens(dict(input_tokens=100, cached_input_tokens=70,
                            cache_write_input_tokens=10, output_tokens=20,
                            reasoning_output_tokens=8))
        self.assertEqual(usage['input'], 20)
        self.assertEqual(total(usage), 120)

    def test_claude_duplicate_content_blocks_use_largest_usage(self):
        log = Log(Path('session.jsonl'), 'claude')
        def consume(output):
            log.consume(dict(type='assistant', timestamp='2026-10-17T12:00:00Z',
                             message=dict(id='same-response', model='test',
                                          usage=dict(input_tokens=3, cache_read_input_tokens=10,
                                                     cache_creation_input_tokens=5, output_tokens=output))))
        consume(7)
        consume(12)
        consume(7)
        result = log.export({})
        self.assertEqual(result['totals']['total'], 30)
        self.assertEqual(len(result['events']), 1)
        self.assertEqual(result['context'], 30)

    def test_null_details_and_zero_usage_error_messages(self):
        log=Log(Path('session.jsonl'),'claude')
        for key, model, count in [('one','real-model',3),('two','<synthetic>',0)]:
            log.consume(dict(type='assistant',message=dict(id=key,model=model,
                usage=dict(input_tokens=count,output_tokens=count,output_tokens_details=None))))
        result=log.export({})
        self.assertEqual(result['totals']['total'],6)
        self.assertEqual(result['context'],6)
        self.assertEqual(result['model'],'real-model')

    def test_codex_duplicate_counts_and_fallback_never_overlap(self):
        log = Log(Path('session.jsonl'), 'codex')
        log.consume(dict(type='token_usage_record', payload=dict(response_id='one', usage=dict(input_tokens=100, output_tokens=20))))
        self.assertEqual(log.export({})['totals']['total'], 120)
        for input_count, output_count in [(100,20),(100,20),(200,30)]:
            log.consume(dict(type='event_msg', payload=dict(type='token_count', info=dict(
                total_token_usage=dict(input_tokens=input_count,cached_input_tokens=50,output_tokens=output_count),
                last_token_usage=dict(input_tokens=80,output_tokens=10),model_context_window=1000))))
        result=log.export({})
        self.assertEqual(result['totals']['total'],230)
        self.assertEqual(len(result['events']),2)
        self.assertEqual(result['context'],90)
        self.assertEqual(result['capacity'],1000)

    def test_partial_lines_append_and_truncate(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'test.jsonl'
            row=json.dumps(dict(type='assistant',message=dict(id='one',usage=dict(input_tokens=5,output_tokens=5))))
            path.write_text(row[:20])
            log=Log(path,'claude');log.refresh()
            self.assertEqual(log.offset,0)
            with path.open('a') as stream:stream.write(row[20:]+'\n')
            log.refresh();self.assertEqual(log.export({})['totals']['total'],10)
            log.refresh();self.assertEqual(log.export({})['totals']['total'],10)
            path.write_text('{}\n');log.refresh()
            self.assertEqual(log.export({})['totals']['total'],0)

    def test_cost_state_is_undated_fallback_and_missing_roots_are_visible(self):
        log=Log(Path('session.jsonl'),'claude')
        log.consume(dict(type='cost-state',modelUsage={'test':dict(inputTokens=2,outputTokens=4,cacheReadInputTokens=10)}))
        result=log.export({})
        self.assertEqual(result['totals']['total'],16)
        self.assertIsNone(result['events'][0]['at'])
        with tempfile.TemporaryDirectory() as folder:
            result=Store(Path(folder)/'codex',Path(folder)/'claude').read()
            self.assertEqual(len(result['warnings']),2)

    def test_claude_subagent_links_to_parent_chat(self):
        # Desktop Code tab sessions delegate work to subagents, whose usage lands
        # in <session>/subagents/agent-*.jsonl rather than the chat transcript.
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            project=root/'claude'/'projects'/'project'
            child=project/'parent-id'/'subagents'/'agent-x.jsonl'
            child.parent.mkdir(parents=True)
            (project/'parent-id.jsonl').write_text(json.dumps(dict(type='custom-title',customTitle='My chat'))+'\n')
            child.write_text(json.dumps(dict(type='assistant',sessionId='parent-id',cwd='/tmp/project',
                message=dict(id='a',usage=dict(input_tokens=4,output_tokens=1))))+'\n')
            sessions={s['session_id']:s for s in Store(root/'codex',root/'claude').read()['sessions']}
            agent=sessions['agent-x']
            self.assertTrue(agent['subagent'])
            self.assertEqual(agent['parent'],'parent-id')
            self.assertEqual(agent['title'],'My chat')
            self.assertEqual(agent['totals']['total'],5)
            self.assertIsNone(sessions['parent-id']['parent'])

    def test_http_limits_and_live_append(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            logs=root/'claude'/'projects'
            logs.mkdir(parents=True)
            path=logs/'session.jsonl'
            path.write_text('')
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.store=Store(root/'codex',root/'claude',root/'saved')
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertEqual(urllib.request.urlopen(base).status,200)
                with urllib.request.urlopen(base+'/logo.svg') as response:
                    self.assertEqual(response.headers.get_content_type(),'image/svg+xml')
                    self.assertIn(b'<svg',response.read())
                first=json.load(urllib.request.urlopen(base+'/api/usage'))
                self.assertEqual(first['sessions'][0]['totals']['total'],0)
                path.write_text(json.dumps(dict(type='assistant',message=dict(id='new',usage=dict(input_tokens=7,output_tokens=2))))+'\n')
                server.store.scanned=float('-inf')
                second=json.load(urllib.request.urlopen(base+'/api/usage'))
                self.assertEqual(second['sessions'][0]['totals']['total'],9)
                saved=server.store.read(force_save=True)
                day=saved['archive']['dates'][0]
                history=json.load(urllib.request.urlopen(base+'/api/history/'+day))
                self.assertEqual(history['sessions'][0]['totals']['total'],9)
                self.assertEqual(json.load(urllib.request.urlopen(base+'/api/health'))['app'],'token-observatory')
                for route, headers, code in [('/server.py',{},404),('/api/usage',{'Host':'evil.example'},403),('/api/usage',{'Sec-Fetch-Site':'cross-site'},403)]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(base+route,headers=headers))
                    self.assertEqual(error.exception.code,code)
            finally:
                server.shutdown();server.server_close();thread.join()


if __name__=='__main__':
    unittest.main()
