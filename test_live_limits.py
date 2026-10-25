import json
from pathlib import Path
import stat
import tempfile
import unittest

import live_limits

USAGE_REPORT = dict(session=dict(total_cost_usd=0), rate_limits=dict(limits=[
    dict(kind='session', group='session', percent=32, resets_at='2026-10-19T19:59:59.970846+00:00', severity='normal', is_active=False),
    dict(kind='weekly_all', group='weekly', percent=63, resets_at='2026-10-24T23:59:59+00:00', severity='normal', is_active=True),
    dict(kind='weekly_scoped', group='weekly', percent=10, resets_at=None, severity='normal', is_active=False)]))
CODEX_RESULT = dict(rateLimits=dict(limitId='codex', primary=dict(usedPercent=99, windowDurationMins=300, resetsAt=1792440264),
                                    secondary=dict(usedPercent=38, windowDurationMins=10080, resetsAt=1792886569), planType='plus'),
                    accountId='secret-account')


def fake_tool(folder, name, body):
    path = Path(folder) / name
    path.write_text('#!/bin/sh\n' + body)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


class ParseTests(unittest.TestCase):
    def test_claude_usage_report_maps_session_and_weekly_rows(self):
        lines = [json.dumps(dict(type='system', subtype='init')),
                 json.dumps(dict(type='assistant', usage_report=USAGE_REPORT)), 'not json']
        result = live_limits.parse_claude_usage(lines, now=1792400000)
        self.assertEqual(result['source'], 'live')
        self.assertEqual(result['observed_at'], 1792400000)
        self.assertEqual((result['primary']['used_percent'], result['primary']['window_minutes']), (32, 300))
        self.assertAlmostEqual(result['primary']['resets_at'], 1792439999.970846, places=3)
        self.assertEqual((result['secondary']['used_percent'], result['secondary']['window_minutes']), (63, 10080))

    def test_claude_usage_without_report_is_none(self):
        self.assertIsNone(live_limits.parse_claude_usage([json.dumps(dict(type='assistant', message={}))], now=1))
        self.assertIsNone(live_limits.parse_claude_usage([json.dumps(dict(type='assistant', usage_report=dict(rate_limits=None)))], now=1))

    def test_codex_result_matches_log_shape_without_account_id(self):
        result = live_limits.parse_codex_limits(CODEX_RESULT, now=5)
        self.assertEqual(result['primary'], dict(used_percent=99, window_minutes=300, resets_at=1792440264))
        self.assertEqual(result['secondary']['used_percent'], 38)
        self.assertEqual((result['plan_type'], result['observed_at'], result['source']), ('plus', 5, 'live'))
        self.assertNotIn('secret-account', json.dumps(result))
        self.assertIsNone(live_limits.parse_codex_limits({}, now=5))


class ProcessTests(unittest.TestCase):
    def test_claude_usage_runs_print_mode_without_persistence(self):
        with tempfile.TemporaryDirectory() as folder:
            args = Path(folder) / 'args'
            tool = fake_tool(folder, 'claude', f'echo "$@" > "{args}"\necho \'{json.dumps(dict(type="assistant", usage_report=USAGE_REPORT))}\'\n')
            result, error = live_limits.claude_usage(tool, folder)
            self.assertIsNone(error)
            self.assertEqual(result['primary']['used_percent'], 32)
            self.assertIn('--no-session-persistence', args.read_text())
            self.assertIn('/usage', args.read_text())

    def test_signed_out_claude_says_how_to_sign_in(self):
        with tempfile.TemporaryDirectory() as folder:
            script = 'if [ "$1" = auth ]; then echo \'{"loggedIn": false, "authMethod": "none"}\'; else echo \'{"type": "result", "result": "Total cost: $0.0000"}\'; fi\n'
            result, error = live_limits.claude_usage(fake_tool(folder, 'claude', script), folder)
            self.assertIsNone(result)
            self.assertIn('signed out', error)
            self.assertIn('claude /login', error)

    def test_signed_in_without_report_keeps_plan_message(self):
        with tempfile.TemporaryDirectory() as folder:
            script = 'if [ "$1" = auth ]; then echo \'{"loggedIn": true}\'; else echo \'{"type": "result"}\'; fi\n'
            error = live_limits.claude_usage(fake_tool(folder, 'claude', script), folder)[1]
            self.assertIn('Pro or Max', error)

    def test_codex_app_server_handshake_and_read(self):
        with tempfile.TemporaryDirectory() as folder:
            seen = Path(folder) / 'seen'
            reply = json.dumps(dict(id=1, result=CODEX_RESULT))
            tool = fake_tool(folder, 'codex', f'read a; echo \'{{"id":0,"result":{{}}}}\'; read b; read c; echo "$a $b $c" > "{seen}"\n'
                                              f'echo \'{{"method":"other/notice","params":{{}}}}\'\necho \'{reply}\'\nsleep 5\n')
            result, error = live_limits.codex_limits(tool, timeout=3)
            self.assertIsNone(error)
            self.assertEqual(result['primary']['used_percent'], 99)
            sent = seen.read_text()
            self.assertIn('"initialize"', sent)
            self.assertIn('"initialized"', sent)
            self.assertIn('account/rateLimits/read', sent)

    def test_failures_are_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(live_limits.claude_usage(None, folder), (None, 'claude command not found'))
            broken = fake_tool(folder, 'codex', 'exit 3\n')
            result, error = live_limits.codex_limits(broken, timeout=2)
            self.assertIsNone(result)
            self.assertTrue(error)
            slow = fake_tool(folder, 'claude', 'sleep 5\n')
            self.assertIsNone(live_limits.claude_usage(slow, folder, timeout=0.5)[0])

    def test_check_combines_both_providers(self):
        with tempfile.TemporaryDirectory() as folder:
            claude = fake_tool(folder, 'claude', f'echo \'{json.dumps(dict(type="assistant", usage_report=USAGE_REPORT))}\'\n')
            result = live_limits.check(dict(claude=claude, codex=None), folder)
            self.assertEqual(result['claude']['primary']['used_percent'], 32)
            self.assertIsNone(result['codex'])
            self.assertEqual(result['errors'], dict(codex='codex command not found'))
            self.assertIsInstance(result['checked_at'], float)


if __name__ == '__main__':
    unittest.main()
