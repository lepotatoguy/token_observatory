"""MiniMax account quota and attribution of locally recorded model usage."""
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.error
import urllib.request

from backend.services.archive import DEFAULT_DATA
from backend.services.claude_statusline import read_json

ENDPOINTS = {'global': 'https://www.minimax.io/v1/token_plan/remains',
             'cn': 'https://www.minimaxi.com/v1/token_plan/remains'}
LOGIN_ENDPOINTS = {'global': 'https://platform.minimax.io/v1/api/openplatform/coding_plan/remains',
                   'cn': 'https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains'}


def model_is_minimax(model):
    return 'minimax' in str(model).lower()


def using_minimax(payload, transcript=None, client='claude'):
    from urllib.parse import urlsplit
    host = urlsplit(os.environ.get('ANTHROPIC_BASE_URL', '')).hostname or ''
    if client == 'claude' and host in ('api.minimax.io', 'api.minimaxi.com'):
        return True
    if payload.get('model'):
        return model_is_minimax(payload['model'])
    if transcript and Path(transcript).is_file():
        # Reuse the bounded transcript reader without importing the hook module at startup.
        from backend.services.session_hooks import newest_records
        for record in newest_records(transcript):
            message = record.get('message') if record.get('type') == 'assistant' else None
            if isinstance(message, dict) and message.get('model'):
                return model_is_minimax(message['model'])
            if record.get('type') == 'turn_context':
                return model_is_minimax((record.get('payload') or {}).get('model'))
    return False


def credentials(folder=DEFAULT_DATA):
    saved = read_json(Path(folder) / 'minimax.json')
    key = os.environ.get('MINIMAX_API_KEY') or saved.get('api_key') or ''
    return key if isinstance(key, str) else '', saved.get('region') if saved.get('region') in ('global', 'cn') else 'global'


def native_credentials():
    """Read a matching production file login; MiniMax Code owns token renewal."""
    from backend.services.minimax_code import home
    found = []
    for region in ('en', 'cn'):
        folder = home() / 'auth' / 'prod' / region / 'mcode-public'
        state = read_json(folder / 'auth-state.json')
        if (state.get('schemaVersion') not in (1, 2) or state.get('status') != 'authenticated'
                or state.get('storeKind') != 'file' or state.get('region') != region
                or state.get('clientId') != 'mcode-public' or state.get('audience') != 'agent-backend'
                or state.get('buildEnv', 'prod') != 'prod'
                or type(state.get('generation')) is not int or state['generation'] < 0):
            continue
        saved = read_json(folder / 'auth.json')
        records = saved.get('records')
        if saved.get('schemaVersion') != 1 or not isinstance(records, dict):
            continue
        for row in records.values():
            if not isinstance(row, dict):
                continue
            token, expiry = row.get('accessToken'), row.get('expiresAtMs')
            if (row.get('schemaVersion') == 1 and row.get('clientId') == 'mcode-public'
                    and row.get('audience') == 'agent-backend'
                    and row.get('generation') == state.get('generation')
                    and numeric(expiry) and expiry > time.time() * 1000
                    and isinstance(token, str) and token and len(token) <= 8192
                    and not any(c.isspace() for c in token)):
                found.append((token, 'global' if region == 'en' else 'cn'))
    # Multiple accounts require an explicit key to avoid selecting the wrong account.
    return found[0] if len(found) == 1 else ('', 'global')


def status(folder=DEFAULT_DATA):
    key, region = credentials(folder)
    if not key:
        key, native_region = native_credentials()
        if key:
            region = native_region
    return dict(configured=bool(key), region=region)


def validate(change):
    if not isinstance(change, dict) or set(change) - {'api_key', 'region'}:
        raise ValueError('MiniMax settings need api_key and/or region')
    if 'region' in change and (not isinstance(change['region'], str) or change['region'] not in ENDPOINTS):
        raise ValueError('MiniMax region must be global or cn')
    key = change.get('api_key')
    if key is not None and (not isinstance(key, str) or len(key) > 8192 or any(c.isspace() for c in key)):
        raise ValueError('MiniMax API key must be a single token without whitespace')


def configure(change, folder=DEFAULT_DATA):
    validate(change)
    folder = Path(folder)
    data = read_json(folder / 'minimax.json')
    data.update(change)
    folder.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.minimax-', suffix='.tmp', dir=folder)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            json.dump(data, stream)
        os.replace(temporary, folder / 'minimax.json')
    finally:
        Path(temporary).unlink(missing_ok=True)


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_quota(data, now):
    """Use MiniMax's remaining percentages, falling back to remaining counts, never elapsed time."""
    if not isinstance(data, dict):
        return None
    base = data.get('base_resp', {})
    if not isinstance(base, dict) or base.get('status_code', 0) != 0:
        return None
    rows = data.get('model_remains')
    if not isinstance(rows, list):
        return None
    row = next((r for r in rows if isinstance(r, dict) and
                (r.get('model_name') == 'general' or model_is_minimax(r.get('model_name')))), None)
    if not row:
        return None
    result = {}
    for slot, prefix, start, end, default_minutes in (
            ('primary', 'current_interval', 'start_time', 'end_time', 300),
            ('secondary', 'current_weekly', 'weekly_start_time', 'weekly_end_time', 10080)):
        if row.get(prefix + '_status') == 3:
            continue  # Unlimited windows have no exhaustion percentage.
        remaining = row.get(prefix + '_remaining_percent')
        if not numeric(remaining):
            count, total = row.get(prefix + '_usage_count'), row.get(prefix + '_total_count')
            if not numeric(count) or not numeric(total) or total <= 0 or not 0 <= count <= total:
                continue
            remaining = 100 * count / total
        if not 0 <= remaining <= 100:
            continue
        if slot == 'secondary':
            boost = row.get('weekly_boost_permille', 1000)
            if not numeric(boost) or boost < 0:
                continue
            remaining = min(100, remaining * boost / 1000)
        reset = row.get(end)
        reset = reset / 1000 if numeric(reset) else None
        beginning = row.get(start)
        minutes = (row[end] - beginning) / 60000 if reset and numeric(beginning) and row[end] > beginning else default_minutes
        result[slot] = dict(used_percent=100-remaining, resets_at=reset, window_minutes=minutes)
    return dict(result, observed_at=now, source='live', limit_id='minimax') if result else None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # Never forward a plan key to a redirect target.


def usage(folder=DEFAULT_DATA, timeout=5):
    key, region = credentials(folder)
    endpoint = ENDPOINTS[region]
    if not key:
        key, region = native_credentials()
        endpoint = LOGIN_ENDPOINTS[region]
    if not key:
        return None, 'Sign in to MiniMax Code, or add a Coding Plan API key in Providers'
    request = urllib.request.Request(endpoint,
                                     headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    try:
        with urllib.request.build_opener(NoRedirect).open(request, timeout=timeout) as response:
            data = json.loads(response.read(1 << 20))
        result = parse_quota(data, time.time())
        return (result, None) if result else (None, 'MiniMax returned no supported Coding Plan quota')
    except urllib.error.HTTPError as error:
        return None, f'MiniMax quota check returned HTTP {error.code}; check your plan key and region'
    except (OSError, ValueError, TypeError, AttributeError):
        return None, 'MiniMax quota check failed; check your connection and plan key'


def split_session(session):
    """Keep mixed-model chats in separate provider totals without counting a response twice."""
    groups = {}
    for event in session['events']:
        provider = 'minimax' if model_is_minimax(event.get('model')) else session['provider']
        groups.setdefault(provider, []).append(event)
    if not groups:
        provider = 'minimax' if model_is_minimax(session['model']) else session['provider']
        groups[provider] = []
    result = []
    for provider, events in groups.items():
        row = dict(session, provider=provider, events=events)
        if provider != session['provider'] or len(groups) > 1:
            row['id'] = provider + ':' + session['id']
            row['models'] = sorted({e['model'] for e in events}) or session['models']
            row['model'] = events[-1]['model'] if events else session['model']
            row['totals'] = {k: sum(e.get(k, 0) or 0 for e in events) for k in session['totals']}
            row['totals']['total'] = sum(row['totals'].get(k, 0) for k in ('input', 'cached', 'write', 'output'))
            row['reported_cost'] = None
            if row['model'] != session['model']:
                row.update(context=None, capacity=None, capacity_source=None, latest_usage=None, latest_usage_at=None)
        if provider == 'minimax':
            row.update(rate_limits=None, rate_limits_at=None)
        result.append(row)
    return result
