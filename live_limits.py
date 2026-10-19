"""Ask Claude Code and Codex for current plan usage, through their documented local interfaces.

- Claude Code: `claude -p /usage` in stream-json mode attaches `usage_report` to its reply (Agent SDK
  reference, SDKUsageReport). It is a local command: no model request, no tokens, no saved session.
- Codex: `codex app-server` answers `account/rateLimits/read` (Codex App Server docs).
Both tools use their own sign-in; this module never reads credentials.
"""
import datetime as dt
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

FIVE_HOURS, WEEK_MINUTES = 300, 10080
CLAUDE_KINDS = {'session': ('primary', FIVE_HOURS), 'weekly_all': ('secondary', WEEK_MINUTES)}
CLAUDE_ARGS = ['-p', '/usage', '--output-format', 'stream-json', '--verbose', '--no-session-persistence',
               '--strict-mcp-config', '--setting-sources', '']
TIMEOUT = 30
# Apps started from Finder or launchd get a short PATH, so look in the usual install folders too.
FOLDERS = ('/opt/homebrew/bin', '/usr/local/bin', '~/.local/bin', '~/.claude/local', '~/.npm-global/bin')


def find_tool(name):
    found = shutil.which(name)
    if found:
        return found
    for folder in FOLDERS:
        path = Path(folder).expanduser() / name
        if path.is_file():
            return str(path)
    return None


def tool_env(binary):
    # Scripts such as `#!/usr/bin/env node` need the tool's own folder on PATH.
    return dict(os.environ, PATH=os.pathsep.join([str(Path(binary).parent), os.environ.get('PATH', '')]))


def epoch(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def parse_claude_usage(lines, now):
    """Plan windows from the usage_report in `claude -p /usage` stream-json output, or None."""
    for line in lines:
        try:
            message = json.loads(line)
        except ValueError:
            continue
        report = message.get('usage_report') if isinstance(message, dict) else None
        rows = ((report or {}).get('rate_limits') or {}).get('limits') if isinstance(report, dict) else None
        found = {}
        for row in rows if isinstance(rows, list) else []:
            if isinstance(row, dict) and row.get('kind') in CLAUDE_KINDS and isinstance(row.get('percent'), (int, float)):
                key, minutes = CLAUDE_KINDS[row['kind']]
                found[key] = dict(used_percent=row['percent'], window_minutes=minutes, resets_at=epoch(row.get('resets_at')))
        if found:
            return dict(found, observed_at=now, source='live')
    return None


def claude_usage(binary, cwd, timeout=TIMEOUT):
    if not binary:
        return None, 'claude command not found'
    try:
        done = subprocess.run([binary, *CLAUDE_ARGS], cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=timeout, env=tool_env(binary))
    except subprocess.TimeoutExpired:
        return None, f'claude /usage timed out after {timeout} s'
    except OSError as error:
        return None, f'claude /usage failed: {error.strerror}'
    result = parse_claude_usage(done.stdout.splitlines(), time.time())
    return (result, None) if result else (None, 'claude /usage returned no plan usage (it needs a claude.ai Pro or Max sign-in)')


def parse_codex_limits(result, now):
    """Codex rate limits from account/rateLimits/read, shaped like the rate_limits in Codex logs."""
    limits = (result or {}).get('rateLimits')
    if not isinstance(limits, dict):
        return None
    window = lambda w: dict(used_percent=w.get('usedPercent'), window_minutes=w.get('windowDurationMins'),
                            resets_at=w.get('resetsAt')) if isinstance(w, dict) else None
    shaped = dict(limit_id=limits.get('limitId'), primary=window(limits.get('primary')), secondary=window(limits.get('secondary')),
                  plan_type=limits.get('planType'), observed_at=now, source='live')
    return shaped if shaped['primary'] or shaped['secondary'] else None


def codex_limits(binary, timeout=TIMEOUT):
    if not binary:
        return None, 'codex command not found'
    try:
        process = subprocess.Popen([binary, 'app-server'], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, env=tool_env(binary))
    except OSError as error:
        return None, f'codex app-server failed: {error.strerror}'
    lines = queue.Queue()

    def pump():
        for line in process.stdout:
            lines.put(line)
        lines.put(None)
    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    deadline = time.monotonic() + timeout

    def send(message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()

    def reply(number):
        while True:
            line = lines.get(timeout=max(0.01, deadline - time.monotonic()))
            if line is None:
                raise EOFError
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if isinstance(message, dict) and message.get('id') == number:
                return message
    try:
        send(dict(method='initialize', id=0, params=dict(clientInfo=dict(name='token_observatory', title='Token Observatory', version='1'))))
        reply(0)
        send(dict(method='initialized', params={}))
        send(dict(method='account/rateLimits/read', id=1, params={}))
        answer = reply(1)
    except queue.Empty:
        return None, f'codex app-server timed out after {timeout} s'
    except (EOFError, OSError):
        return None, 'codex app-server closed before answering'
    finally:
        process.kill()
        process.wait()
        reader.join(1)
        for stream in (process.stdin, process.stdout):
            try:
                stream.close()
            except OSError:
                pass
    result = parse_codex_limits(answer.get('result'), time.time())
    return (result, None) if result else (None, f"codex app-server: {(answer.get('error') or {}).get('message') or 'no rate limits'}")


def check(tools, cwd, timeout=TIMEOUT):
    """Ask both tools at once. Returns {'claude', 'codex', 'errors', 'checked_at'}."""
    answers = {}
    jobs = dict(claude=lambda: claude_usage(tools.get('claude'), cwd, timeout), codex=lambda: codex_limits(tools.get('codex'), timeout))
    threads = [threading.Thread(target=lambda name=name, job=job: answers.__setitem__(name, job())) for name, job in jobs.items()]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    errors = {name: answers[name][1] for name in jobs if answers[name][1]}
    return dict(claude=answers['claude'][0], codex=answers['codex'][0], errors=errors, checked_at=time.time())
