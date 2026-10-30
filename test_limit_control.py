import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import limit_control
import session_hooks

NOW = 1793400000


def row(used=92, reset=NOW+60, key='plan:primary'):
    return dict(id=key, percent=used, reset=reset, minutes=300, observed=NOW)


class ControlTests(unittest.TestCase):
    def test_defaults_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            self.assertEqual(c.settings()['codex'], dict(mode='hard', threshold=90))
            for payload in [dict(codex=dict(mode='bad', threshold=90)), dict(codex=dict(mode='hard', threshold=True)),
                            dict(codex=dict(mode='warn', threshold=101)), dict(reset_notifications=1), dict(other={})]:
                with self.assertRaises(ValueError):
                    c.update(payload, NOW)
            c.update(dict(codex=dict(mode='warn', threshold=75), reset_notifications=False), NOW)
            other = limit_control.Control(folder)
            self.assertEqual(other.settings()['codex'], dict(mode='warn', threshold=75))
            self.assertFalse(other.settings()['reset_notifications'])
            self.assertEqual(len(other.snapshot(NOW)['events']), 1)
            other.update(dict(codex=dict(mode='warn', threshold=75), reset_notifications=False), NOW)
            self.assertEqual(len(other.snapshot(NOW)['events']), 1)

    def test_reset_tracked_across_restart_once_and_independent_limits(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            windows = dict(primary=row(), secondary=row(100, NOW+86400, 'plan:secondary'))
            c.observe({'codex':windows}, NOW, pauses={('codex', 'plan:primary'), ('codex','plan:secondary')})
            c.observe({'codex':windows}, NOW+1)
            other = limit_control.Control(folder)
            events = other.observe({}, NOW+61)['events']
            resets = [e for e in events if e['type']=='reset']
            self.assertEqual(len(resets), 1)
            self.assertEqual(resets[0]['limit'], 'plan:primary')
            self.assertEqual(len(other.observe({}, NOW+62)['events']), len(events))
            self.assertEqual(sum(e['type']=='pause' for e in events), 2)

    def test_warn_records_warning_without_pause(self):
        c = limit_control.Control()
        c.update(dict(codex=dict(mode='warn', threshold=70)), NOW)
        events = c.observe({'codex':dict(primary=row(75))}, NOW)['events']
        self.assertEqual(sum(e['type']=='threshold' for e in events), 1)
        self.assertFalse(any(e['type']=='pause' for e in events))
        events = c.observe({'codex':dict(primary=row(100))}, NOW+1)['events']
        self.assertEqual(sum(e['type']=='exhausted' for e in events), 1)
        self.assertFalse(any(e['type']=='pause' for e in events))

    def test_age_count_and_byte_caps(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            state = dict(events=[dict(at=NOW-limit_control.DAYS-1, type='old')] +
                         [dict(at=NOW, type='threshold', limit='x'*500) for _ in range(2000)])
            c.persist(state, NOW)
            events = c.snapshot(NOW)['events']
            self.assertTrue(events)
            self.assertLessEqual(len(events), limit_control.MAX_EVENTS)
            self.assertLessEqual((Path(folder)/'limit-events.json').stat().st_size, limit_control.MAX_BYTES)
            self.assertFalse(any(e['type']=='old' for e in events))
            c.observe({}, NOW+limit_control.DAYS+1)
            self.assertEqual(c.snapshot(NOW+limit_control.DAYS+1)['events'], [])
            self.assertNotIn('prompt', (Path(folder)/'limit-events.json').read_text())

    def test_hook_modes_threshold_changes_and_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            c.update(dict(codex=dict(mode='warn', threshold=70)), NOW)
            payload = dict(session_id='chat', cwd=folder, hook_event_name='PostToolUse')
            def hook(now=NOW):
                return session_hooks.run(io.StringIO(json.dumps(payload)), 'codex', folder, None, now)
            with patch('session_hooks.saved_limits', return_value={'plan:primary':row(75)}):
                warn = hook()
                self.assertIn('warning only', warn)
                self.assertNotIn('Pause substantive work', warn)
                self.assertEqual(hook(), '')
                c.update(dict(codex=dict(mode='hard', threshold=70)), NOW)
                self.assertIn('Pause substantive work', hook())
                self.assertEqual(hook(), '')
                reset = hook(NOW+61)
                self.assertIn('automatically resume', reset)
                self.assertNotIn('allowed on user request', reset)
                self.assertEqual(hook(NOW+62), '')

    def test_mode_switch_cancels_historical_pause(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            payload = dict(session_id='chat', hook_event_name='PostToolUse')
            def hook():
                return session_hooks.run(io.StringIO(json.dumps(payload)), 'codex', folder, None, NOW)
            with patch('session_hooks.saved_limits', return_value={'plan:primary':row(100)}):
                self.assertIn('Pause substantive work', hook())
                c.update(dict(codex=dict(mode='warn', threshold=90)), NOW)
                output = hook()
                self.assertIn('WARN mode supersedes ALL earlier', output)
                self.assertNotIn('Pause substantive work', output)

class ControlAPITests(unittest.TestCase):
    def test_shared_settings_endpoint_validation_and_origin(self):
        import threading
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer
        from server import Handler, Store
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            server.store = Store(root/'codex', root/'claude', root/'history', lmstudio_folder=root/'lmstudio')
            threading.Thread(target=server.serve_forever, daemon=True).start()
            base = f'http://127.0.0.1:{server.server_port}'
            def post(body, origin=None):
                headers = {'Content-Type':'application/json'}
                if origin:
                    headers['Origin'] = origin
                return json.load(urllib.request.urlopen(urllib.request.Request(base+'/api/limit-control',
                    data=json.dumps(body).encode(), headers=headers, method='POST')))
            try:
                result = post(dict(claude=dict(mode='warn', threshold=80)))
                self.assertEqual(result['settings']['claude'], dict(mode='warn', threshold=80))
                self.assertEqual(limit_control.Control(root).settings()['claude'], result['settings']['claude'])
                response = json.load(urllib.request.urlopen(base+'/api/limit-control'))
                self.assertEqual(response, result)
                for body in [dict(codex=dict(mode='hard', threshold=0)), dict(reset_notifications='yes')]:
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        post(body)
                    self.assertEqual(error.exception.code, 400)
                with self.assertRaises(urllib.error.HTTPError) as error:
                    post({}, 'https://evil.example')
                self.assertEqual(error.exception.code, 403)
                snapshot = server.store.read(force_save=True)
                self.assertIn('limit_control', snapshot)
                self.assertTrue(snapshot['archive']['dates'])
                saved = server.store.archive.load(snapshot['archive']['dates'][0])
                self.assertNotIn('limit_control', saved)
            finally:
                server.shutdown()
                server.server_close()
