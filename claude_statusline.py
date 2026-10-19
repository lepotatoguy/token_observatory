"""Capture Claude Code's subscription rate limits through its status line.

Claude Code passes JSON to the status line command after each reply. For Pro and Max plans it
includes rate_limits.five_hour and rate_limits.seven_day, each with used_percentage (0 to 100) and
resets_at (Unix seconds). See https://code.claude.com/docs/en/statusline. This module saves those
windows for the dashboard and prints a short status line.
"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

WINDOWS = ('five_hour', 'seven_day')
MARKER = '--statusline'


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def read_json(path):
    try:
        data = json.loads(Path(path).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(prefix='.limits-', suffix='.tmp', dir=path.parent)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(data, stream)
    os.replace(temporary, path)


def windows_from(payload):
    limits = payload.get('rate_limits') if isinstance(payload.get('rate_limits'), dict) else {}
    found = {}
    for name in WINDOWS:
        window = limits.get(name)
        if isinstance(window, dict) and number(window.get('used_percentage')) is not None:
            found[name] = dict(used_percentage=window['used_percentage'], resets_at=number(window.get('resets_at')))
    return found


def capture(stream, limits_file, now=None):
    """Save the rate-limit windows from one status line update and return the text to show."""
    now = time.time() if now is None else now
    try:
        payload = json.load(stream)
    except ValueError:
        payload = {}
    payload = payload if isinstance(payload, dict) else {}
    found = windows_from(payload)
    if found:
        previous = read_json(limits_file)
        # Claude Code can omit a window; keep the saved one until its reset time passes.
        kept = {name: previous[name] for name in WINDOWS if name not in found and isinstance(previous.get(name), dict)
                and (previous[name].get('resets_at') or 0) > now}
        write_json(limits_file, dict(captured_at=now, **kept, **found))
    return status_text(payload, found)


def status_text(payload, found):
    parts = []
    model = (payload.get('model') or {}).get('display_name') if isinstance(payload.get('model'), dict) else None
    if model:
        parts.append(str(model))
    context = number((payload.get('context_window') or {}).get('used_percentage')) if isinstance(payload.get('context_window'), dict) else None
    if context is not None:
        parts.append(f'ctx {context:.0f}%')
    for name, label in (('five_hour', '5h'), ('seven_day', '7d')):
        if name in found:
            parts.append(f"{label} {found[name]['used_percentage']:.0f}%")
    return ' · '.join(parts) or 'Token Observatory'


def settings_path():
    return Path(os.environ.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'settings.json'


def command_line():
    """How Claude Code should run this launcher in status line mode."""
    if getattr(sys, 'frozen', False):
        return f'"{sys.executable}" {MARKER}'
    return f'"{sys.executable}" "{Path(__file__).resolve().parent / "launcher.py"}" {MARKER}'


def is_ours(status_line):
    return isinstance(status_line, dict) and MARKER in str(status_line.get('command', '')) and (
        'launcher.py' in status_line['command'] or 'oken' in status_line['command'])


def update_settings(install):
    """Add or remove the status line in Claude Code's settings. Returns (ok, message)."""
    path = settings_path()
    settings = read_json(path) if path.exists() else {}
    if path.exists() and not settings and path.read_text().strip():
        return False, f'{path} is not valid JSON; left unchanged.'
    current = settings.get('statusLine')
    if current and not is_ours(current):
        return False, f'{path} already has a status line ({current.get("command", current)!r}); left unchanged.'
    if install:
        settings['statusLine'] = dict(type='command', command=command_line())
    elif current:
        settings.pop('statusLine')
    else:
        return True, 'No Token Observatory status line to remove.'
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + '.bak'))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + '\n')
    return True, f'{"Added" if install else "Removed"} the Token Observatory status line in {path}.'
