"""The display model behind the floating usage widget.

The widget is a small pill that shows each account's name and its session and
weekly quota. This module turns a quota payload into that display model and
holds the colours, so the layout can be tested without a display or a toolkit.
"""
SESSION = 'Session'
WEEKLY = 'Weekly'

# One accent per account, like the coding clients' own colours.
ACCENTS = {
    'claude': '#E8912D',
    'codex': '#3FB8AF',
    'minimax': '#9B7BF0',
}
DEFAULT_ACCENT = '#8E8E93'

BACKGROUND = '#1D1D20'
BORDER = '#3C3C42'
TRACK = '#3C3C42'
TEXT = '#F4F4F6'
MUTED = '#9C9CA6'


MAX_MISSES = 3


def follow(setting, misses):
    """Decide whether a managed widget should quit. Returns (quit_now, unreachable_polls).

    `setting` is the collector's /api/widget answer, or None when it could not be reached.
    """
    if setting is None:
        misses += 1
        return misses >= MAX_MISSES, misses
    return (isinstance(setting, dict) and setting.get('enabled') is False), 0


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def meter(limit, label):
    """One meter row: its label, how much of the window is used and when it resets."""
    if not isinstance(limit, dict):
        return None
    return dict(label=label,
                used_percent=number(limit.get('used_percent')),
                resets_at=number(limit.get('resets_at')),
                window_minutes=number(limit.get('window_minutes')))


def percent_text(used):
    """The percentage as the widget shows it, or a dash when it is unknown."""
    return f'{used:.0f}%' if isinstance(used, (int, float)) else '—'


def short_model(model, provider):
    """The model name without the provider prefix the logs add."""
    if isinstance(model, str) and provider and model.startswith(provider + '/'):
        return model[len(provider) + 1:]
    return model


def rows(payload):
    """Display rows for the widget: one per account, with its meters."""
    payload = payload or {}
    errors = payload.get('errors') or {}
    result = []
    for provider in payload.get('providers') or []:
        if not isinstance(provider, dict):
            continue
        key = provider.get('provider')
        meters = [m for m in (meter(provider.get('session'), SESSION),
                              meter(provider.get('weekly'), WEEKLY)) if m]
        result.append(dict(provider=key,
                           name=provider.get('name') or key or '',
                           model=short_model(provider.get('model'), key),
                           accent=ACCENTS.get(key, DEFAULT_ACCENT),
                           meters=meters,
                           observed_at=number(provider.get('observed_at')),
                           error=errors.get(key)))
    return result


def message(payload):
    """What the widget shows when there is nothing to report yet."""
    payload = payload or {}
    if payload.get('providers'):
        return None
    errors = payload.get('errors') or {}
    if errors:
        return '; '.join(f'{name}: {text}' for name, text in errors.items())
    if payload.get('checked_at'):
        return 'No account quota recorded yet.'
    return 'Waiting for the collector…'
