"""Claude Code context capacity and cost from local settings, since transcripts omit them."""
import json
from pathlib import Path

ONE_MILLION = 1_000_000
# Claude Code sessions on this model run with a 1M window. Users override or extend this in config.json.
DEFAULT_WINDOWS = {'claude-opus-5-5': ONE_MILLION}


def load_windows(path):
    """Return (windows, warning) from {"claude_context_windows": {"<model id>": <tokens>}}."""
    windows = dict(DEFAULT_WINDOWS)
    path = Path(path)
    if not path.exists():
        return windows, None
    try:
        configured = json.loads(path.read_text()).get('claude_context_windows', {})
    except (OSError, ValueError, AttributeError) as error:
        return windows, f'Config {path} is unreadable: {error}'
    if not isinstance(configured, dict):
        return windows, f'Config {path}: claude_context_windows must map model IDs to token counts'
    invalid = sorted(k for k, v in configured.items() if isinstance(v, bool) or not isinstance(v, int) or v <= 0)
    windows.update((k, v) for k, v in configured.items() if k not in invalid)
    return windows, f'Config {path}: ignored invalid windows for {", ".join(invalid)}' if invalid else None


class LastSessions:
    """Last-session cost and models that Claude Code keeps per project in .claude.json."""

    def __init__(self, claude_home):
        home = Path(claude_home)
        # .claude.json sits inside CLAUDE_CONFIG_DIR when set, otherwise beside ~/.claude.
        self.candidates = (home / '.claude.json', home.parent / '.claude.json')
        self.mtime, self.sessions = None, {}

    def read(self):
        path = next((p for p in self.candidates if p.exists()), None)
        if path is None:
            return {}
        try:
            mtime = path.stat().st_mtime
            if mtime != self.mtime:
                projects = json.loads(path.read_text()).get('projects') or {}
                self.sessions = {p['lastSessionId']: dict(cost=p.get('lastCost'), models=list(p.get('lastModelUsage') or {}))
                                 for p in projects.values() if isinstance(p, dict) and p.get('lastSessionId')}
                self.mtime = mtime
        except (OSError, ValueError, AttributeError):
            pass
        return self.sessions


def apply(session, marked_1m, last_sessions, windows):
    """Fill Claude capacity and cost that the transcript lacks, labeling where each came from."""
    info = last_sessions.get(session['session_id']) or {}
    if session['reported_cost'] is None and isinstance(info.get('cost'), (int, float)):
        session.update(reported_cost=info['cost'], cost_source='session end')
    if session['capacity']:
        return
    marked_1m = marked_1m or any(f'{model}[1m]' in info.get('models', []) for model in session['models'])
    if marked_1m:
        session.update(capacity=ONE_MILLION, capacity_source='model ID [1m]')
    elif windows.get(session['model']):
        session.update(capacity=windows[session['model']], capacity_source='configured')
