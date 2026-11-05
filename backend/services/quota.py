"""A compact quota view for the floating usage widget.

The dashboard snapshot carries every recorded session and event, which is far
more than a small overlay needs. This module reduces a snapshot to one row per
account: the model in use, the session window and the weekly window.
"""
from backend.services.providers import NAMES

SESSION_MINUTES = 300
WEEKLY_MINUTES = 10080
SLOTS = ('primary', 'secondary')


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def model_label(sessions, provider):
    """The model most recently used for an account, or None when none was recorded."""
    candidates = [s for s in sessions
                  if isinstance(s, dict) and s.get('provider') == provider and not s.get('subagent')
                  and s.get('model') and s.get('model') != 'Unreported']
    if not candidates:
        return None
    newest = max(candidates, key=lambda s: s.get('modified') or 0)
    return newest.get('model')


def window(limit, minutes):
    """One quota window as {used_percent, window_minutes, resets_at}, or None."""
    if not isinstance(limit, dict):
        return None
    return dict(used_percent=number(limit.get('used_percent')),
                window_minutes=number(limit.get('window_minutes')) or minutes,
                resets_at=number(limit.get('resets_at')))


def pick(limits, minutes, fallback):
    """The window for a duration, whichever slot it was stored in."""
    for slot in SLOTS:
        candidate = limits.get(slot)
        if isinstance(candidate, dict) and number(candidate.get('window_minutes')) == minutes:
            return window(candidate, minutes)
    candidate = limits.get(fallback)
    return window(candidate, minutes) if isinstance(candidate, dict) else None


def rows(snapshot):
    """One row per account with a recorded quota, in provider order."""
    limits = (snapshot or {}).get('limits') or {}
    sessions = (snapshot or {}).get('sessions') or []
    result = []
    for provider in NAMES:
        quota = limits.get(provider)
        if not isinstance(quota, dict):
            continue
        result.append(dict(provider=provider,
                           name=NAMES.get(provider, provider),
                           model=model_label(sessions, provider),
                           session=pick(quota, SESSION_MINUTES, 'primary'),
                           weekly=pick(quota, WEEKLY_MINUTES, 'secondary'),
                           observed_at=number(quota.get('observed_at')),
                           source=quota.get('source'),
                           plan=quota.get('plan_type')))
    return result


def payload(snapshot):
    """The float's data source: account rows, the last live check and any errors."""
    live = (snapshot or {}).get('live_limits') or {}
    errors = {p: e for p, e in (live.get('errors') or {}).items() if isinstance(e, str)}
    return dict(at=number((snapshot or {}).get('at')),
                checked_at=number(live.get('checked_at')),
                providers=rows(snapshot),
                errors=errors)
