import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from backend.services import limit_control
from backend.services import session_hooks

NOW = 1793400000


def row(used=92, reset=NOW+60, key='plan:primary'):
    return dict(id=key, percent=used, reset=reset, minutes=300, observed=NOW)


class ControlTests(unittest.TestCase):
    def setUp(self):
        # Synthetic windows must never be replaced by a real local account lookup.
        fresh = patch('backend.services.session_hooks.fresh_limits', return_value={})
        fresh.start()
        self.addCleanup(fresh.stop)

    def test_five_hour_limit_and_weekly_reserve_are_independent(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            c.update({'codex': dict(warn=None, hard=95, weekly_reserve=3)}, NOW)
            windows = {'five': row(94), 'week': dict(row(95, NOW+86400, 'plan:secondary'), minutes=10080)}
            payload = dict(session_id='reserve', hook_event_name='PreToolUse')
            def hook(now=NOW):
                with patch('backend.services.session_hooks.saved_limits', return_value=windows):
                    return json.loads(session_hooks.run(io.StringIO(json.dumps(payload)), 'codex', folder, None, now) or '{}')
            self.assertNotIn('hookSpecificOutput', hook())
            windows['week']['percent'] = 97
            self.assertEqual(hook()['hookSpecificOutput']['permissionDecision'], 'deny')
            windows['week']['percent'] = 95
            windows['five']['percent'] = 95
            self.assertEqual(hook()['hookSpecificOutput']['permissionDecision'], 'deny')
            windows['week']['percent'] = 98
            windows['five']['reset'] = NOW-1
            self.assertEqual(hook()['hookSpecificOutput']['permissionDecision'], 'deny')
            windows['week']['reset'] = NOW-1
            self.assertNotIn('permissionDecision', hook().get('hookSpecificOutput', {}))
            self.assertIsNone(limit_control.hard_threshold(c.settings()['codex'], 60))
            for reserve in (-1, 101, True, float('nan')):
                with self.assertRaises(ValueError):
                    c.update({'codex': dict(warn=None, hard=95, weekly_reserve=reserve)}, NOW)

    def test_defaults_validation_and_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            self.assertEqual(c.settings()['codex'], dict(warn=None, hard=90, weekly_reserve=3))
            for payload in [dict(codex=dict(mode='bad', threshold=90)), dict(codex=dict(mode='hard', threshold=True)),
                            dict(codex=dict(mode='warn', threshold=101)), dict(reset_notifications=1), dict(other={})]:
                with self.assertRaises(ValueError):
                    c.update(payload, NOW)
            c.update(dict(codex=dict(mode='warn', threshold=75), reset_notifications=False), NOW)
            other = limit_control.Control(folder)
            self.assertEqual(other.settings()['codex'], dict(warn=75, hard=None, weekly_reserve=None))
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
            with patch('backend.services.session_hooks.saved_limits', return_value={'plan:primary':row(75)}):
                warn = hook()
                self.assertIn('warning only', warn)
                self.assertNotIn('Pause substantive work', warn)
                self.assertEqual(hook(), '')
                c.update(dict(codex=dict(mode='hard', threshold=70)), NOW)
                self.assertIn('Pause substantive work', hook())
                self.assertIs(json.loads(hook())['continue'], False)
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
            with patch('backend.services.session_hooks.saved_limits', return_value={'plan:primary':row(100)}):
                self.assertIn('Pause substantive work', hook())
                c.update(dict(codex=dict(mode='warn', threshold=90)), NOW)
                output = hook()
                self.assertIn('WARN mode supersedes ALL earlier', output)
                self.assertNotIn('Pause substantive work', output)

    def test_independent_warning_and_hard_thresholds(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            c.update(dict(codex=dict(warn=80, hard=98)), NOW)
            payload = dict(session_id='chat', hook_event_name='PostToolUse')
            def hook(used):
                with patch('backend.services.session_hooks.saved_limits', return_value={'plan:primary':row(used)}):
                    return session_hooks.run(io.StringIO(json.dumps(payload)), 'codex', folder, None, NOW)
            self.assertEqual(hook(79), '')
            warning = hook(80)
            self.assertIn('warning only', warning)
            self.assertNotIn('Pause substantive work', warning)
            self.assertNotIn('WARN mode supersedes', warning)
            self.assertEqual(hook(90), '')
            self.assertIn('Pause substantive work', hook(98))
            self.assertIs(json.loads(hook(99))['continue'], False)
            self.assertIn('EXHAUSTED', hook(100))
            self.assertIs(json.loads(hook(100))['continue'], False)
            events = c.snapshot(NOW)['events']
            self.assertEqual(sum(e['type']=='pause' for e in events), 2)
            c.update(dict(codex=dict(warn=None, hard=None, weekly_reserve=None)), NOW)
            off = hook(100)
            self.assertIn('usage warnings and hard pauses are disabled', off)
            self.assertNotIn('Pause substantive work', off)
            self.assertEqual(hook(100), '')

    def test_new_schema_validation_and_legacy_file_migration(self):
        with tempfile.TemporaryDirectory() as folder:
            c = limit_control.Control(folder)
            c.save('limit-settings', dict(codex=dict(mode='hard', threshold=98), claude=dict(mode='warn', threshold=70)))
            self.assertEqual(c.settings()['codex'], dict(warn=None, hard=98, weekly_reserve=3))
            self.assertEqual(c.settings()['claude'], dict(warn=70, hard=None, weekly_reserve=None))
            for pref in [dict(warn=99, hard=80), dict(warn=False, hard=None), dict(warn=None), dict(warn=80, hard=101)]:
                with self.assertRaises(ValueError):
                    c.update(dict(codex=pref), NOW)
            c.update(dict(codex=dict(warn=None, hard=None, weekly_reserve=None)), NOW)
            self.assertEqual(limit_control.Control(folder).settings()['codex'], dict(warn=None, hard=None, weekly_reserve=None))
            self.assertEqual(limit_control.stage(c.settings()['codex'],100),0)
