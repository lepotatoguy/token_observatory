import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import tempfile
import threading
import unittest

import local_proxy
import providers


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class FakeServer(BaseHTTPRequestHandler):
    """Answers like Ollama (/api/chat, NDJSON) and like an OpenAI-compatible server (/v1/chat/completions)."""
    seen = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        FakeServer.seen.append((self.path, body, self.headers.get('Host')))
        if self.path == '/api/chat':
            lines = [dict(model='llama3.2', message=dict(content='hi'), done=False),
                     dict(model='llama3.2', done=True, prompt_eval_count=12, eval_count=5)]
            payload, kind = ''.join(json.dumps(line) + '\n' for line in lines).encode(), 'application/x-ndjson'
        elif body.get('stream'):
            chunks = [dict(model='qwen', choices=[dict(delta=dict(content='ok'))])]
            if body.get('stream_options', {}).get('include_usage'):
                chunks.append(dict(model='qwen', choices=[], usage=dict(prompt_tokens=30, completion_tokens=7)))
            payload, kind = (''.join(f'data: {json.dumps(c)}\n\n' for c in chunks) + 'data: [DONE]\n\n').encode(), 'text/event-stream'
        else:
            payload = json.dumps(dict(model='qwen', usage=dict(prompt_tokens=9, completion_tokens=3))).encode()
            kind = 'application/json'
        self.send_response(200)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        payload = b'{"models":[]}'
        self.send_response(200)
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *_):
        pass


class ParsingTests(unittest.TestCase):
    def test_reads_ollama_openai_and_streamed_usage(self):
        ndjson = b'{"model":"m","done":false}\n{"model":"m","done":true,"prompt_eval_count":4,"eval_count":2}\n'
        self.assertEqual(local_proxy.read_usage(ndjson), ('m', 4, 2))
        self.assertEqual(local_proxy.read_usage(b'{"model":"q","usage":{"prompt_tokens":3,"completion_tokens":1}}'), ('q', 3, 1))
        sse = b'data: {"model":"q","choices":[]}\n\ndata: {"model":"q","usage":{"prompt_tokens":8,"completion_tokens":2}}\n\ndata: [DONE]\n'
        self.assertEqual(local_proxy.read_usage(sse), ('q', 8, 2))
        self.assertIsNone(local_proxy.read_usage(b'{"models":[]}'))
        self.assertIsNone(local_proxy.read_usage(b'not json'))

    def test_streamed_openai_requests_ask_for_usage_only_when_unset(self):
        added = json.loads(local_proxy.with_stream_usage('/v1/chat/completions', b'{"stream":true}'))
        self.assertEqual(added['stream_options'], dict(include_usage=True))
        kept = b'{"stream":true,"stream_options":{"include_usage":false}}'
        self.assertEqual(local_proxy.with_stream_usage('/v1/chat/completions', kept), kept)
        self.assertEqual(local_proxy.with_stream_usage('/api/chat', b'{"stream":true}'), b'{"stream":true}')
        self.assertEqual(local_proxy.with_stream_usage('/v1/chat/completions', b'{"stream":false}'), b'{"stream":false}')


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.upstream = ThreadingHTTPServer(('127.0.0.1', 0), FakeServer)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        self.log = Path(self.folder.name) / 'local-usage.jsonl'
        self.proxies = local_proxy.Proxies(local_proxy.Recorder(self.log))
        self.port = free_port()
        self.proxies.apply({'ollama': (self.port, self.upstream.server_port)})
        FakeServer.seen.clear()

    def tearDown(self):
        self.proxies.stop()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.folder.cleanup()

    def post(self, path, body):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('POST', path, body=json.dumps(body), headers={'Content-Type': 'application/json'})
        reply = connection.getresponse()
        data = reply.read()
        connection.close()
        return reply.status, data

    def rows(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def test_forwards_unchanged_and_records_counts_only(self):
        status, data = self.post('/api/chat', dict(model='llama3.2', messages=[dict(role='user', content='secret prompt')]))
        self.assertEqual(status, 200)
        self.assertIn(b'"eval_count": 5', data)
        self.assertEqual(FakeServer.seen[0][2], f'127.0.0.1:{self.upstream.server_port}')
        [row] = self.rows()
        self.assertEqual((row['tool'], row['model'], row['input'], row['output'], row['endpoint']), ('ollama', 'llama3.2', 12, 5, '/api/chat'))
        self.assertEqual(row['title'], 'secret prompt')  # Only a short title of the first message is kept.

    def test_rebound_host_names_are_refused(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('POST', '/api/chat', body='{}', headers={'Host': f'evil.example:{self.port}', 'Content-Type': 'application/json'})
        self.assertEqual(connection.getresponse().status, 403)
        connection.close()
        self.assertEqual(FakeServer.seen, [])

    def test_chats_are_named_by_their_first_message_and_grouped(self):
        first = [dict(role='system', content='be brief'), dict(role='user', content='Plan my  trip to Kyoto in spring with a budget of 2000 dollars please')]
        self.post('/api/chat', dict(model='llama3.2', messages=first))
        self.post('/api/chat', dict(model='llama3.2', messages=first + [dict(role='assistant', content='ok'), dict(role='user', content='more')]))
        self.post('/api/chat', dict(model='llama3.2', messages=[dict(role='user', content='Other chat')]))
        rows = self.rows()
        self.assertEqual(rows[0]['conversation'], rows[1]['conversation'])
        self.assertNotEqual(rows[0]['conversation'], rows[2]['conversation'])
        self.assertEqual(rows[0]['title'], 'Plan my trip to Kyoto in spring with a budget of 2000 dollar…')
        self.assertNotIn('more', self.log.read_text())
        chats = {s['title']: s for s in local_proxy.sessions(self.log, {'ollama'})}
        self.assertEqual(len(chats['Plan my trip to Kyoto in spring with a budget of 2000 dollar…']['events']), 2)
        self.assertIn('Other chat', chats)
        self.assertEqual(local_proxy.chat_identity(b'{"prompt":"Say hi.","model":"m"}')[1], 'Say hi.')
        self.assertEqual(local_proxy.chat_identity(b'{"messages":[{"role":"user","content":[{"type":"text","text":"Parts"}]}]}')[1], 'Parts')
        self.assertEqual(local_proxy.chat_identity(b'not json'), (None, None))

    def test_streamed_openai_reply_is_counted(self):
        status, data = self.post('/v1/chat/completions', dict(model='qwen', stream=True, messages=[]))
        self.assertEqual(status, 200)
        self.assertIn(b'[DONE]', data)
        self.assertEqual(self.rows()[0]['input'], 30)

    def test_gets_pass_through_without_recording(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        connection.request('GET', '/api/tags')
        self.assertEqual(connection.getresponse().read(), b'{"models":[]}')
        connection.close()
        self.assertEqual(self.rows(), [])

    def test_down_server_gives_502_and_busy_port_is_reported(self):
        self.proxies.apply({'ollama': (self.port, free_port())})
        self.assertEqual(self.post('/api/chat', {})[0], 502)
        with socket.socket() as taken:
            taken.bind(('127.0.0.1', 0))
            taken.listen()
            self.proxies.apply({'lmstudio': (taken.getsockname()[1], 1)})
            status = self.proxies.status()
        self.assertFalse(status['lmstudio']['listening'])
        self.assertIn('unavailable', status['lmstudio']['error'])
        self.assertFalse(status['ollama']['listening'])

    def test_sessions_group_by_tool_model_and_day(self):
        recorder = local_proxy.Recorder(self.log)
        recorder.add('ollama', 'llama3.2', 10, 2, '/api/chat', at=1792990000)
        recorder.add('ollama', 'llama3.2', 20, 4, '/api/chat', at=1792990100)
        recorder.add('lmstudio', 'qwen', 5, 1, '/v1/chat/completions', at=1792990200)
        self.log.write_text(self.log.read_text() + 'garbage\n')
        found = {s['provider']: s for s in local_proxy.sessions(self.log, {'ollama', 'lmstudio'})}
        self.assertEqual(found['ollama']['totals']['total'], 36)
        self.assertEqual(found['ollama']['context'], 24)
        self.assertEqual(len(found['ollama']['events']), 2)
        self.assertEqual([s['provider'] for s in local_proxy.sessions(self.log, {'lmstudio'})], ['lmstudio'])


class SettingsTests(unittest.TestCase):
    def test_defaults_keep_detected_cloud_tools_and_saves_choices(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'providers.json'
            settings = providers.Settings(path)
            self.assertFalse(settings.snapshot()['setup_done'])
            self.assertEqual(settings.enabled(), {'claude', 'codex'})
            settings.update(dict(enabled=dict(claude=False, codex=True, ollama=True), setup_done=True, ports=dict(ollama=dict(listen=12000))))
            again = providers.Settings(path)
            self.assertTrue(again.snapshot()['setup_done'])
            self.assertEqual(again.enabled(), {'codex', 'ollama'})
            self.assertEqual(again.ports('ollama'), (12000, 11434))

    def test_rejects_bad_input(self):
        settings = providers.Settings(None)
        for payload in (dict(enabled=dict(gemini=True)), dict(enabled=dict(claude='yes')), dict(ports=dict(ollama=dict(listen=0))),
                        dict(ports=dict(ollama=dict(listen=11434, target=11434))), dict(setup_done='true')):
            with self.assertRaises(ValueError):
                settings.update(payload)

    def test_detect_reports_reasons(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'claude/projects').mkdir(parents=True)
            found = providers.detect(Path(folder) / 'claude', Path(folder) / 'codex', probe=lambda port: port == 1234)
            self.assertEqual(found['claude'], 'Claude Code logs found')
            self.assertIsNone(found['codex'])
            self.assertIn('1234', found['lmstudio'])


if __name__ == '__main__':
    unittest.main()
