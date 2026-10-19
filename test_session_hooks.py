import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

import session_hooks

ROOT = Path(__file__).resolve().parent
NOW = 1792400000


def claude_line(tokens, model='claude-opus-5-5'):
    return json.dumps(dict(type='assistant', timestamp='2026-10-19T10:00:00Z', message=dict(
        id=f'r{tokens}', model=model, usage=dict(input_tokens=10, cache_read_input_tokens=tokens, cache_creation_input_tokens=0, output_tokens=5)))) + '\n'


class Fixture:
    def __init__(self, folder):
        self.root = Path(folder)
        self.data = self.root / 'data'
        self.data.mkdir()
        self.project = self.root / 'project'
        self.project.mkdir()
        self.transcript = self.root / 'chat.jsonl'
        self.transcript.write_text('')
        self.desktop = self.root / 'plan-usage-history.json'

    def capture(self, used, resets_at=NOW + 3600, captured_at=NOW - 60):
        (self.data / 'claude-rate-limits.json').write_text(json.dumps(dict(
            captured_at=captured_at, five_hour=dict(used_percentage=used, resets_at=resets_at))))

    def run(self, provider='claude', event='UserPromptSubmit', now=NOW, session='session-1', raw=None):
        payload = raw if raw is not None else json.dumps(dict(session_id=session, transcript_path=str(self.transcript), cwd=str(self.project),
                                                            hook_event_name=event))
        output = session_hooks.run(io.StringIO(payload), provider, self.data, self.desktop, now)
        return json.loads(output)['hookSpecificOutput'] if output else None


class HookTests(unittest.TestCase):
    def test_context_reminder_fires_once_per_crossing(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            f.transcript.write_text(claude_line(400_000))
            self.assertIsNone(f.run())
            f.transcript.write_text(claude_line(400_000) + claude_line(620_000))
            out = f.run(event='PostToolUse')
            self.assertEqual(out['hookEventName'], 'PostToolUse')
            self.assertIn('62% full', out['additionalContext'])
            self.assertIn('/compact', out['additionalContext'])
            self.assertIsNone(f.run())
            f.transcript.write_text(claude_line(100_000))  # After compaction the reminder re-arms.
            self.assertIsNone(f.run())
            f.transcript.write_text(claude_line(700_000))
            self.assertIn('70% full', f.run()['additionalContext'])
            self.assertIn('70% full', f.run(session='session-2')['additionalContext'])

    def test_unknown_capacity_never_guesses(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            f.transcript.write_text(claude_line(900_000, model='mystery-model'))
            self.assertIsNone(f.run())

    def test_handoff_fires_once_per_five_hour_window(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            f.capture(89)
            self.assertIsNone(f.run())
            f.capture(92)
            text = f.run()['additionalContext']
            self.assertIn('92%', text)
            self.assertIn(str(f.project / '.claude' / 'handoffs'), text)
            self.assertIn('next steps', text)
            self.assertIsNone(f.run())
            f.capture(93, resets_at=NOW + 3600 - 1)  # Another source, same window.
            self.assertIsNone(f.run())
            f.capture(91, resets_at=NOW + 5 * 3600 + 600)
            self.assertIn('91%', f.run()['additionalContext'])

    def test_stale_limits_are_ignored_and_newest_source_wins(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            f.capture(99, resets_at=NOW - 10)  # That window already reset.
            self.assertIsNone(f.run())
            f.desktop.write_text(json.dumps(dict(samples=[dict(t=(NOW - 6 * 3600) * 1000, u=dict(fh=100, sd=5))])))
            self.assertIsNone(f.run())
            (f.data / 'live-limits.json').write_text(json.dumps(dict(claude=dict(
                primary=dict(used_percent=95, window_minutes=300, resets_at=NOW + 900), observed_at=NOW - 5))))
            self.assertIn('95%', f.run()['additionalContext'])

    def test_thresholds_come_from_config(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            (f.data / 'config.json').write_text(json.dumps(dict(hook_limit_percent=50, hook_context_percent=30)))
            f.capture(55)
            f.transcript.write_text(claude_line(310_000))
            text = f.run()['additionalContext']
            self.assertIn('55%', text)
            self.assertIn('31% full', text)

    def test_codex_reads_its_rollout(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            f.transcript.write_text(json.dumps(dict(type='event_msg', payload=dict(type='token_count', info=dict(
                last_token_usage=dict(input_tokens=170_000, output_tokens=2_000), model_context_window=258_400),
                rate_limits=dict(primary=dict(used_percent=96.0, window_minutes=300, resets_at=NOW + 600))))) + '\n')
            text = f.run(provider='codex')['additionalContext']
            self.assertIn('Codex 5-hour usage limit is at 96%', text)
            self.assertIn(str(f.project / '.codex' / 'handoffs'), text)
            self.assertIn('67% full', text)
            # A newer live check beats the rollout's older snapshot.
            f.transcript.write_text(f.transcript.read_text().replace('{"type": "event_msg"', '{"type": "event_msg", "timestamp": "2026-10-19T00:00:00Z"'))
            (f.data / 'live-limits.json').write_text(json.dumps(dict(codex=dict(
                primary=dict(used_percent=97, window_minutes=300, resets_at=NOW + 5 * 3600 + 900), observed_at=NOW - 5))))
            self.assertIn('at 97%', f.run(provider='codex', session='session-2')['additionalContext'])

    def test_bad_input_prints_nothing(self):
        with tempfile.TemporaryDirectory() as folder:
            f = Fixture(folder)
            for raw in ['', 'not json', '[]', json.dumps(dict(session_id='x', transcript_path='/missing/file.jsonl'))]:
                self.assertIsNone(f.run(raw=raw))

    def test_launcher_hook_mode_exits_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ, HOME=folder, XDG_DATA_HOME=str(Path(folder) / 'data'), APPDATA=folder)
            for payload in ['garbage', json.dumps(dict(session_id='s', transcript_path=str(Path(folder) / 'none.jsonl')))]:
                done = subprocess.run([sys.executable, str(ROOT / 'launcher.py'), '--hook'], input=payload, env=env,
                                      capture_output=True, text=True, timeout=30)
                self.assertEqual((done.returncode, done.stdout, done.stderr), (0, '', ''))


class InstallTests(unittest.TestCase):
    def test_install_merges_keeps_existing_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            claude, codex = Path(folder) / 'claude', Path(folder) / 'codex'
            claude.mkdir()
            codex.mkdir()
            mine = dict(matcher='Bash', hooks=[dict(type='command', command='my-check')])
            (claude / 'settings.json').write_text(json.dumps(dict(theme='dark', hooks=dict(PostToolUse=[mine], Stop=[mine]))))
            (codex / 'hooks.json').write_text(json.dumps(dict(hooks=dict(PreToolUse=[mine]))))
            env = dict(CLAUDE_CONFIG_DIR=str(claude), CODEX_HOME=str(codex))
            for _ in range(2):
                results = session_hooks.update_hooks(True, env)
                self.assertTrue(all(ok for ok, _ in results), results)
            settings = json.loads((claude / 'settings.json').read_text())
            self.assertEqual(settings['theme'], 'dark')
            self.assertEqual(settings['hooks']['Stop'], [mine])
            self.assertEqual(settings['hooks']['PostToolUse'][0], mine)
            self.assertEqual(len(settings['hooks']['PostToolUse']), 2)
            self.assertEqual(len(settings['hooks']['UserPromptSubmit']), 1)
            ours = settings['hooks']['UserPromptSubmit'][0]['hooks'][0]
            self.assertIn('--hook', ours['command'])
            self.assertEqual(ours['timeout'], 5)
            self.assertTrue((claude / 'settings.json.bak').exists())
            codex_hooks = json.loads((codex / 'hooks.json').read_text())['hooks']
            self.assertEqual(codex_hooks['PreToolUse'], [mine])
            self.assertTrue(codex_hooks['UserPromptSubmit'][0]['hooks'][0]['command'].endswith('--hook codex'))
            session_hooks.update_hooks(False, env)
            self.assertEqual(json.loads((claude / 'settings.json').read_text()), dict(theme='dark', hooks=dict(PostToolUse=[mine], Stop=[mine])))
            self.assertEqual(json.loads((codex / 'hooks.json').read_text()), dict(hooks=dict(PreToolUse=[mine])))

    def test_invalid_settings_are_left_alone_and_missing_codex_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            claude = Path(folder) / 'claude'
            claude.mkdir()
            (claude / 'settings.json').write_text('{broken')
            results = session_hooks.update_hooks(True, dict(CLAUDE_CONFIG_DIR=str(claude), CODEX_HOME=str(Path(folder) / 'none')))
            self.assertFalse(results[0][0])
            self.assertEqual((claude / 'settings.json').read_text(), '{broken')
            self.assertFalse((Path(folder) / 'none').exists())


if __name__ == '__main__':
    unittest.main()
