import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pricing
import updater
from server import Handler, Log, Store, timestamp, tokens, total


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
        self.assertEqual(result['totals']['total'],120)
        self.assertEqual(len(result['events']),1)
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
            self.assertEqual(agent['conversation_id'],'parent-id')
            self.assertEqual(sessions['parent-id']['conversation_id'],'parent-id')

    def test_claude_context_card_uses_recorded_and_configured_values(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            project=root/'claude'/'projects'/'project'
            project.mkdir(parents=True)
            def reply(model, requested=None, cache=100):
                return json.dumps(dict(type='assistant', timestamp='2026-10-17T12:00:00Z', requestedModel=requested or model,
                    message=dict(id=model+str(cache), model=model, usage=dict(input_tokens=2, cache_read_input_tokens=cache,
                        cache_creation_input_tokens=5, output_tokens=7))))+'\n'
            (project/'configured.jsonl').write_text(reply('claude-opus-5-5')+reply('claude-opus-5-5', cache=300))
            (project/'marked.jsonl').write_text(reply('claude-sonnet-5-5', 'claude-sonnet-5-5[1m]'))
            (project/'ended.jsonl').write_text(reply('claude-haiku-5-5'))
            (project/'plain.jsonl').write_text(reply('claude-haiku-4-5-20251001'))
            (root/'claude'/'.claude.json').write_text(json.dumps(dict(projects={'/p': dict(
                lastSessionId='ended', lastCost=1.25, lastModelUsage={'claude-haiku-5-5[1m]': {}})})))
            sessions={s['session_id']:s for s in Store(root/'codex',root/'claude').read()['sessions']}
            configured=sessions['configured']
            self.assertEqual(configured['latest_usage']['cached'],300)
            self.assertEqual((configured['capacity'],configured['capacity_source']),(1000000,'configured'))
            self.assertEqual((sessions['marked']['capacity'],sessions['marked']['capacity_source']),(1000000,'model ID [1m]'))
            self.assertEqual(sessions['ended']['reported_cost'],1.25)
            self.assertEqual(sessions['ended']['capacity_source'],'model ID [1m]')
            self.assertIsNone(sessions['plain']['capacity'])
            self.assertIsNone(sessions['plain']['reported_cost'])

    def test_claude_window_config_overrides_and_rejects_invalid_values(self):
        from claude_context import DEFAULT_WINDOWS, load_windows
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'config.json'
            config.write_text(json.dumps(dict(claude_context_windows={'claude-haiku-5-5':200000,'bad':-1})))
            windows, warning = load_windows(config)
            self.assertEqual(windows['claude-haiku-5-5'],200000)
            self.assertNotIn('bad',windows)
            self.assertIn('bad',warning)
            self.assertEqual(load_windows(Path(folder)/'missing.json'),(DEFAULT_WINDOWS,None))
            self.assertEqual(DEFAULT_WINDOWS['claude-sonnet-5-5'],1000000)

    def test_latest_codex_quota_and_claude_hour_cache_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            sessions=root/'codex'/'sessions'
            sessions.mkdir(parents=True)
            def quota(stamp, used):
                return json.dumps(dict(type='event_msg', timestamp=stamp, payload=dict(type='token_count',
                    rate_limits=dict(primary=dict(used_percent=used, window_minutes=300, resets_at=1792365343)))))+'\n'
            (sessions/'old.jsonl').write_text(quota('2026-10-17T10:00:00Z', 5))
            (sessions/'new.jsonl').write_text(quota('2026-10-17T12:00:00Z', 21))
            project=root/'claude'/'projects'/'p'
            project.mkdir(parents=True)
            (project/'chat.jsonl').write_text(json.dumps(dict(type='assistant', timestamp='2026-10-17T12:00:00Z',
                message=dict(id='r', model='m', usage=dict(input_tokens=1, cache_creation_input_tokens=30, output_tokens=2,
                    cache_creation=dict(ephemeral_5m_input_tokens=10, ephemeral_1h_input_tokens=20)))))+'\n')
            snapshot=Store(root/'codex',root/'claude').read()
            limits=snapshot['limits']['codex']
            self.assertEqual(limits['primary']['used_percent'],21)
            self.assertEqual(limits['observed_at'],timestamp('2026-10-17T12:00:00Z'))
            chat=next(s for s in snapshot['sessions'] if s['provider']=='claude')
            self.assertEqual((chat['events'][0]['write'],chat['events'][0]['write_1h']),(30,20))

    def test_claude_limits_combine_desktop_usage_and_logged_resets(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            project=root/'claude'/'projects'/'p'
            project.mkdir(parents=True)
            now=time.time()
            week_reset=now-2*86400  # Logged at an earlier rejection; the window repeats weekly.
            lines=[dict(type='assistant', timestamp='2026-10-17T08:00:00Z', quotaLimits=dict(rateLimitType='seven_day', resetsAt=week_reset)),
                   dict(type='assistant', timestamp='2026-10-18T08:00:00Z', quotaLimits=dict(rateLimitType='five_hour', resetsAt=now+3600))]
            (project/'chat.jsonl').write_text(''.join(json.dumps(line)+'\n' for line in lines))
            plan=root/'plan-usage-history.json'
            plan.write_text(json.dumps(dict(version=2, samples=[dict(t=(now-7200)*1000, org='x', u=dict(fh=100, sd=14)),
                                                                dict(t=(now-60)*1000, org='x', u=dict(fh=3, sd=28))])))
            claude=Store(root/'codex',root/'claude',plan_usage=plan).read()['limits']['claude']
            self.assertEqual((claude['primary']['used_percent'],claude['secondary']['used_percent']),(3,28))
            self.assertAlmostEqual(claude['primary']['resets_at'],now+3600)
            self.assertIsNone(claude['secondary']['resets_at'])  # A passed weekly reset is not guessed forward.
            self.assertNotIn('org',json.dumps(claude))

    def test_claude_statusline_capture_beats_older_desktop_sample(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            now=time.time()
            capture=root/'claude-rate-limits.json'
            capture.write_text(json.dumps(dict(captured_at=now-30, five_hour=dict(used_percentage=79, resets_at=now+3600),
                                               seven_day=dict(used_percentage=55, resets_at=now+5*86400))))
            plan=root/'plan-usage-history.json'
            plan.write_text(json.dumps(dict(samples=[dict(t=(now-3600)*1000, u=dict(fh=0, sd=28))])))
            claude=Store(root/'codex',root/'claude',plan_usage=plan,claude_limits_file=capture).read()['limits']['claude']
            self.assertEqual((claude['primary']['used_percent'],claude['secondary']['used_percent']),(79,55))
            self.assertAlmostEqual(claude['secondary']['resets_at'],now+5*86400)
            self.assertFalse(claude['secondary']['resets_estimated'])
            self.assertEqual(claude['source'],'statusline')

    def test_newest_live_check_wins_for_both_providers(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            now=time.time()
            sessions=root/'codex'/'sessions'
            sessions.mkdir(parents=True)
            (sessions/'a.jsonl').write_text(json.dumps(dict(type='event_msg', timestamp='2026-10-17T12:00:00Z', payload=dict(type='token_count',
                rate_limits=dict(primary=dict(used_percent=5, window_minutes=300, resets_at=1792365343)))))+'\n')
            capture=root/'claude-rate-limits.json'
            capture.write_text(json.dumps(dict(captured_at=now-600, five_hour=dict(used_percentage=10, resets_at=now+3600))))
            live=root/'live-limits.json'
            live.write_text(json.dumps(dict(checked_at=now-5, errors={},
                claude=dict(primary=dict(used_percent=44, window_minutes=300, resets_at=now+3000), secondary=None, observed_at=now-5, source='live'),
                codex=dict(primary=dict(used_percent=97, window_minutes=300, resets_at=now+100), observed_at=now-5, source='live'))))
            limits=Store(root/'codex',root/'claude',claude_limits_file=capture,live_file=live).read()['limits']
            self.assertEqual((limits['claude']['primary']['used_percent'],limits['claude']['source']),(44,'live'))
            self.assertEqual((limits['codex']['primary']['used_percent'],limits['codex']['source']),(97,'live'))
            # An older live check loses to a newer status line capture.
            capture.write_text(json.dumps(dict(captured_at=now, five_hour=dict(used_percentage=12, resets_at=now+3600))))
            self.assertEqual(Store(root/'codex',root/'claude',claude_limits_file=capture,live_file=live).read()['limits']['claude']['source'],'statusline')

    def test_refresh_endpoint_checks_live_limits_and_saves_them(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            calls=[]
            def fake_check(tools, cwd, timeout=30):
                calls.append(tools)
                return dict(claude=dict(primary=dict(used_percent=33, window_minutes=300, resets_at=None), observed_at=time.time(), source='live'),
                            codex=None, errors=dict(codex='codex command not found'), checked_at=time.time())
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.store=Store(root/'codex',root/'claude',live_file=root/'live-limits.json',live_tools=dict(claude='c',codex=None),live_check=fake_check)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                body=json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/refresh',method='POST',data=b'')))
                self.assertEqual(body['limits']['claude']['primary']['used_percent'],33)
                self.assertEqual(body['live_limits']['errors'],dict(codex='codex command not found'))
                self.assertEqual(json.loads((root/'live-limits.json').read_text())['claude']['primary']['used_percent'],33)
                urllib.request.urlopen(urllib.request.Request(base+'/api/refresh',method='POST',data=b''))
                self.assertEqual(len(calls),1)  # A second click within seconds reuses the check.
                for headers in [{'Host':'evil.example'},{'Sec-Fetch-Site':'cross-site'},{'Origin':'http://evil.example'}]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(urllib.request.Request(base+'/api/refresh',method='POST',data=b'',headers=headers))
                    self.assertEqual(error.exception.code,403)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/usage',method='POST',data=b''))
                self.assertEqual(error.exception.code,404)
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_update_endpoints_are_protected_and_persist_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            started=[]
            latest=dict(tag_name='v9.0.0',draft=False,prerelease=False,body='',assets=[],
                        html_url='https://github.com/lepotatoguy/token_observatory/releases/tag/v9.0.0')
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.store=Store(root/'codex',root/'claude')
            server.updates=updater.Updates(root,current='1.2.2',fetch_json=lambda url:latest,kind='macos-app',runner=lambda *a:started.append(a))
            server.updates.check()
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            json_post=lambda route,body,headers={}:urllib.request.Request(base+route,method='POST',data=json.dumps(body).encode(),
                                                                          headers={'Content-Type':'application/json',**headers})
            try:
                status=json.load(urllib.request.urlopen(base+'/api/update'))
                self.assertEqual((status['current'],status['latest']['version'],status['prompt']),('1.2.2','9.0.0',True))
                status=json.load(urllib.request.urlopen(json_post('/api/update/settings',dict(dismiss='9.0.0'))))
                self.assertFalse(status['prompt'])
                self.assertEqual(json.loads((root/'update-settings.json').read_text())['dismissed'],'9.0.0')
                status=json.load(urllib.request.urlopen(json_post('/api/update/install',{})))
                self.assertEqual(status['progress']['state'],'starting')
                self.assertEqual(len(started),1)
                rejected=[(json_post('/api/update/install',{},h),403) for h in [{'Host':'evil.example'},{'Sec-Fetch-Site':'cross-site'},{'Origin':'http://evil.example'}]]
                rejected.append((urllib.request.Request(base+'/api/update/install',method='POST',data=b'{}',headers={'Content-Type':'text/plain'}),415))
                rejected.append((json_post('/api/update/settings',dict(notify='maybe')),400))
                rejected.append((urllib.request.Request(base+'/api/update/settings',method='POST',data=b'x'*5000,headers={'Content-Type':'application/json'}),413))
                for request, code in rejected:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request)
                    self.assertEqual(error.exception.code,code)
                self.assertEqual(len(started),1)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    urllib.request.urlopen(urllib.request.Request(base+'/api/update',headers={'Host':'evil.example'}))
                self.assertEqual(error.exception.code,403)
            finally:
                server.shutdown();server.server_close();thread.join()

    def test_http_limits_and_live_append(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            logs=root/'claude'/'projects'
            logs.mkdir(parents=True)
            path=logs/'session.jsonl'
            path.write_text('')
            server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
            server.store=Store(root/'codex',root/'claude',root/'saved')
            server.pricing=pricing.Pricing(root/'pricing.json',root/'config.json',lambda:'')
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            base=f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertEqual(urllib.request.urlopen(base).status,200)
                served=json.load(urllib.request.urlopen(base+'/api/pricing'))
                self.assertEqual(served['source'],'bundled')
                self.assertEqual(len(served['models']),len(pricing.load_bundled()))
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
