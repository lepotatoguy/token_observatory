"""Claude plan usage from local files, best source first.

- A live check with `claude -p /usage` (live_limits.py), saved by the collector to live-limits.json.
- Claude Code's status line input (documented at https://code.claude.com/docs/en/statusline), saved
  by `launcher.py --statusline` to claude-rate-limits.json: exact percentages and reset times.
- The Claude desktop app keeps recent usage samples in plan-usage-history.json: u.fh is the
  5-hour percentage and u.sd the 7-day percentage, with the sample time t in milliseconds.
- Claude Code adds quotaLimits (rateLimitType, resetsAt) to a reply when a request is rejected
  at a limit, which is the only place reset times appear.
"""
import json
import os
from pathlib import Path
import sys

FIVE_HOURS = 300
WEEK_MINUTES = 10080


def desktop_folder():
    """The Claude desktop app's data folder on this platform."""
    if sys.platform == 'darwin':
        return Path.home() / 'Library/Application Support/Claude'
    if sys.platform == 'win32':
        return Path(os.environ.get('APPDATA') or Path.home() / 'AppData/Roaming') / 'Claude'
    return Path(os.environ.get('XDG_CONFIG_HOME') or Path.home() / '.config') / 'Claude'


def percentage(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class PlanUsage:
    """Newest usage sample from plan-usage-history.json, re-read only when the file changes."""

    def __init__(self, path):
        self.path = Path(path) if path else None
        self.mtime, self.latest = None, None

    def read(self):
        try:
            mtime = self.path.stat().st_mtime if self.path else None
        except OSError:
            return None
        if mtime is None or mtime == self.mtime:
            return self.latest
        try:
            samples = json.loads(self.path.read_text()).get('samples') or []
        except (OSError, ValueError, AttributeError):
            return self.latest
        valid = [s for s in samples if isinstance(s, dict) and isinstance(s.get('t'), (int, float)) and isinstance(s.get('u'), dict)]
        newest = max(valid, key=lambda s: s['t'], default=None)
        # Only the percentages and time are kept; the organization ID is never read out.
        self.latest = dict(observed_at=newest['t'] / 1000, five_hour=percentage(newest['u'].get('fh')),
                           seven_day=percentage(newest['u'].get('sd'))) if newest else None
        self.mtime = mtime
        return self.latest


def read_capture(path):
    """Rate limits saved from Claude Code's status line, or None."""
    try:
        data = json.loads(Path(path).read_text()) if path else None
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and isinstance(data.get('captured_at'), (int, float)) else None


def captured_window(window, minutes):
    window = window if isinstance(window, dict) else {}
    return dict(used_percent=percentage(window.get('used_percentage')), window_minutes=minutes,
                resets_at=window.get('resets_at'), resets_estimated=False)


def limits(plan, resets, now, capture=None, live=None):
    """Combine the best available usage percentages and reset times, shaped like Codex limits."""
    found = [live] if isinstance(live, dict) and isinstance(live.get('observed_at'), (int, float)) else []
    if capture:
        found.append(dict(primary=captured_window(capture.get('five_hour'), FIVE_HOURS),
                          secondary=captured_window(capture.get('seven_day'), WEEK_MINUTES),
                          observed_at=capture['captured_at'], source='statusline'))
    newest = max(found, key=lambda f: f['observed_at'], default=None)
    if newest and newest['observed_at'] >= (plan or {}).get('observed_at', 0):
        return newest
    if not plan and not resets:
        return None
    plan = plan or {}
    # A logged reset only says when that window ends; once it passes, the next one is unknown.
    future = lambda at: at if at and at > now else None
    return dict(
        primary=dict(used_percent=plan.get('five_hour'), window_minutes=FIVE_HOURS, resets_at=future(resets.get('five_hour'))),
        secondary=dict(used_percent=plan.get('seven_day'), window_minutes=WEEK_MINUTES, resets_at=future(resets.get('seven_day'))),
        observed_at=plan.get('observed_at'), source='desktop')
