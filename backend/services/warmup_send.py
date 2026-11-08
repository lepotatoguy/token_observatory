"""Send the warm-up message to a provider's cheapest model, through the provider's own tool and sign-in.

Nothing here reads credentials: Claude Code and Codex authenticate themselves. The reply is discarded;
only success or a short failure reason leaves this module.
"""
import re
import subprocess
import threading

from backend.services import live_limits, warmup

TIMEOUT = 60
GATE = threading.Lock()  # One send at a time across all providers.
CLAUDE_MODEL = 'haiku'
SIGNED_OUT = re.compile(r'log ?in|sign[- ]?in|not logged|unauthori[sz]ed|authenticat|api key', re.I)
# MiniMax has no verified request path or lowest-cost model id yet, so it reports itself as unavailable.
MINIMAX_UNAVAILABLE = 'MiniMax warm-up is unavailable: its request path and cheapest model are not verified yet.'


def short(text):
    lines = [line.strip() for line in (text or '').splitlines() if line.strip()]
    return lines[-1][:120] if lines else ''


class Sender:
    """Callable `(provider, model) -> (ok, reason)` that runs one send at a time."""

    def __init__(self, folder, popen=subprocess.Popen, find=live_limits.find_tool):
        self.folder, self.popen, self.find = folder, popen, find
        self.child = None

    def unavailable(self, provider):
        return MINIMAX_UNAVAILABLE if provider == 'minimax' else None

    def command(self, provider, binary, model):
        if provider == 'claude':
            return [binary, '-p', warmup.MESSAGE, '--model', model or CLAUDE_MODEL, '--effort', 'low',
                    '--no-session-persistence', '--strict-mcp-config', '--setting-sources', '', '--tools', '']
        command = [binary, 'exec', '--skip-git-repo-check', '--sandbox', 'read-only',
                   '-c', 'model_reasoning_effort=low']
        return command + (['-m', model] if model else []) + [warmup.MESSAGE]

    def __call__(self, provider, model):
        if model is not None and not (isinstance(model, str) and warmup.MODEL.match(model)):
            return False, 'the model id is not valid'
        if provider == 'minimax':
            return False, MINIMAX_UNAVAILABLE
        if provider not in ('claude', 'codex'):
            return False, f'unknown provider {provider}'
        if not GATE.acquire(blocking=False):
            return False, 'another warm-up is still running'
        try:
            binary = self.find(provider)
            if not binary:
                return False, f'{provider} is not installed'
            return self.run(provider, self.command(provider, binary, model), binary)
        finally:
            GATE.release()

    def run(self, provider, command, binary):
        try:
            child = self.popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               text=True, cwd=str(self.folder), env=live_limits.tool_env(binary))
        except OSError as error:
            return False, f'{provider} could not start: {error}'
        self.child = child
        try:
            try:
                out, err = child.communicate(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                child.kill()
                child.communicate()
                return False, f'{provider} did not answer within {TIMEOUT} seconds'
        finally:
            self.child = None
        if child.returncode == 0:
            return True, ''
        if SIGNED_OUT.search(f'{out}\n{err}'):
            return False, f'{provider} is not signed in'
        return False, f'{provider} exited with code {child.returncode}: {short(err) or short(out)}'

    def stop(self):
        """Terminate a send that is still running; called when the collector shuts down."""
        child = self.child
        if child is not None:
            child.terminate()
