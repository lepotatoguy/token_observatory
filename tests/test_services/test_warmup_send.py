import subprocess
import threading

import pytest

from backend.services import warmup_send
from backend.services.warmup_send import Sender


class Child:
    def __init__(self, code=0, out='', err='', hang=False):
        self.code, self.out, self.err, self.hang = code, out, err, hang
        self.killed = self.terminated = False
        self.returncode = None

    def communicate(self, timeout=None):
        if self.hang and not self.killed:
            raise subprocess.TimeoutExpired('cmd', timeout)
        self.returncode = -9 if self.killed else self.code
        return self.out, self.err

    def kill(self):
        self.killed = True

    def terminate(self):
        self.terminated = True
        self.killed = True

    def poll(self):
        return self.returncode


class Launcher:
    def __init__(self, child=None):
        self.child, self.calls = child or Child(), []

    def __call__(self, command, **options):
        self.calls.append((command, options))
        return self.child


def make(tmp_path, child=None, tools=None):
    launcher = Launcher(child)
    found = tools if tools is not None else {'claude': '/bin/claude', 'codex': '/bin/codex'}
    return Sender(tmp_path, popen=launcher, find=lambda name: found.get(name)), launcher


def test_claude_uses_haiku_low_effort_no_tools_no_session(tmp_path):
    sender, launcher = make(tmp_path)
    assert sender('claude', None) == (True, '')
    command, options = launcher.calls[0]
    assert command[:3] == ['/bin/claude', '-p', 'hello']
    assert command[command.index('--model') + 1] == 'haiku'
    assert command[command.index('--effort') + 1] == 'low'
    assert '--no-session-persistence' in command
    assert command[command.index('--tools') + 1] == ''
    assert command[command.index('--setting-sources') + 1] == ''
    assert '--strict-mcp-config' in command
    assert options['stdin'] == subprocess.DEVNULL
    assert options['cwd'] == str(tmp_path)
    assert options.get('shell') is None


def test_claude_model_override(tmp_path):
    sender, launcher = make(tmp_path)
    sender('claude', 'claude-haiku-9')
    command = launcher.calls[0][0]
    assert command[command.index('--model') + 1] == 'claude-haiku-9'


def test_codex_is_read_only_low_effort_and_skips_the_git_check(tmp_path):
    sender, launcher = make(tmp_path)
    assert sender('codex', None) == (True, '')
    command = launcher.calls[0][0]
    assert command[:2] == ['/bin/codex', 'exec']
    assert '--skip-git-repo-check' in command
    assert command[command.index('--sandbox') + 1] == 'read-only'
    assert 'model_reasoning_effort=low' in command
    assert '-m' not in command
    assert command[-1] == 'hello'


def test_codex_model_override(tmp_path):
    sender, launcher = make(tmp_path)
    sender('codex', 'gpt-test')
    command = launcher.calls[0][0]
    assert command[command.index('-m') + 1] == 'gpt-test'
    assert command[-1] == 'hello'


@pytest.mark.parametrize('model', ['--help', 'a b', 'x;y', '', 'm' * 65, '$(id)'])
def test_a_bad_model_is_refused_before_anything_runs(tmp_path, model):
    sender, launcher = make(tmp_path)
    ok, reason = sender('claude', model)
    assert ok is False and 'model' in reason
    assert launcher.calls == []


def test_a_missing_tool_is_a_failure(tmp_path):
    sender, launcher = make(tmp_path, tools={})
    assert sender('claude', None) == (False, 'claude is not installed')
    assert launcher.calls == []


def test_a_signed_out_tool_is_reported_as_such(tmp_path):
    sender, _ = make(tmp_path, Child(1, '', 'Please run /login to sign in'))
    assert sender('claude', None) == (False, 'claude is not signed in')


def test_other_failures_carry_a_short_reason(tmp_path):
    sender, _ = make(tmp_path, Child(2, '', 'line one\nsomething broke\n'))
    ok, reason = sender('codex', None)
    assert ok is False and reason == 'codex exited with code 2: something broke'


def test_the_reply_is_never_returned(tmp_path):
    sender, _ = make(tmp_path, Child(0, 'a long secret reply', ''))
    assert sender('claude', None) == (True, '')


def test_a_hang_is_killed_after_the_timeout(tmp_path):
    child = Child(hang=True)
    sender, launcher = make(tmp_path, child)
    ok, reason = sender('claude', None)
    assert (ok, reason) == (False, 'claude did not answer within 60 seconds')
    assert child.killed
    assert warmup_send.TIMEOUT == 60


def test_an_os_error_is_a_failure_not_a_crash(tmp_path):
    def broken(command, **options):
        raise OSError('exec format error')

    sender = Sender(tmp_path, popen=broken, find=lambda name: '/bin/x')
    ok, reason = sender('claude', None)
    assert ok is False and 'exec format error' in reason


def test_only_one_send_runs_at_a_time(tmp_path):
    started, release = threading.Event(), threading.Event()

    class Slow(Child):
        def communicate(self, timeout=None):
            started.set()
            release.wait(5)
            self.returncode = 0
            return '', ''

    sender, _ = make(tmp_path, Slow())
    other, _ = make(tmp_path)
    results = []
    thread = threading.Thread(target=lambda: results.append(sender('claude', None)))
    thread.start()
    assert started.wait(5)
    assert other('codex', None) == (False, 'another warm-up is still running')
    release.set()
    thread.join(5)
    assert results == [(True, '')]


def test_stop_terminates_a_running_child(tmp_path):
    started, release = threading.Event(), threading.Event()

    class Slow(Child):
        def communicate(self, timeout=None):
            started.set()
            release.wait(5)
            self.returncode = 0
            return '', ''

    child = Slow()
    sender, _ = make(tmp_path, child)
    thread = threading.Thread(target=lambda: sender('claude', None))
    thread.start()
    assert started.wait(5)
    sender.stop()
    assert child.terminated
    release.set()
    thread.join(5)


def test_unknown_provider_fails_cleanly(tmp_path):
    sender, launcher = make(tmp_path)
    assert sender('gemini', None)[0] is False
    assert launcher.calls == []


def test_minimax_is_unavailable_until_its_request_is_verified(tmp_path):
    sender, launcher = make(tmp_path)
    assert sender.unavailable('minimax')
    assert sender.unavailable('claude') is None and sender.unavailable('codex') is None
    ok, reason = sender('minimax', None)
    assert ok is False and 'unavailable' in reason
    assert launcher.calls == []
