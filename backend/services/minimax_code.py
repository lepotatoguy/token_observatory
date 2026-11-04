"""Read MiniMax Code's local runtime ledger without modifying its database."""
import math
import os
from pathlib import Path
import shutil
import sqlite3


FIELDS = ('input', 'cached', 'write', 'output', 'reasoning')


def home():
    override = os.environ.get('MINIMAX_DATA_DIR') or os.environ.get('MAVIS_DATA_DIR')
    return Path(override).expanduser() if override else Path.home() / '.minimax'


def database(folder=None):
    return (Path(folder) if folder is not None else home()) / 'v2/sqlite/runtime-state.sqlite'


def detect():
    if database().is_file():
        return 'MiniMax Code local runtime found'
    if shutil.which('mcode'):
        return '`mcode` command installed'
    return None


def count(value):
    return int(value) if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else 0


def read(folder=None):
    path = database(folder)
    if not path.is_file():
        return [], [], []
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=0.2)
        connection.row_factory = sqlite3.Row
        connection.execute('BEGIN')
        metadata = {row['session_id']: dict(row) for row in connection.execute(
            'SELECT session_id, title, workspace_dir, parent_session_id, created_at_ms, updated_at_ms '
            'FROM local_runtime_sessions')}
        events = {}
        for row in connection.execute(
                'SELECT id, session_id, model, ts, input_tokens, output_tokens, reasoning_tokens, '
                'cache_read_tokens, cache_write_tokens FROM local_runtime_token_usage ORDER BY ts, id'):
            if row['input_tokens'] is None or row['output_tokens'] is None:
                continue
            # Ledger input is fresh input; cache reads and writes are separate counts.
            event = dict(at=row['ts'] / 1000 if row['ts'] is not None else None,
                         model=row['model'] or 'Unreported', input=count(row['input_tokens']),
                         cached=count(row['cache_read_tokens']), write=count(row['cache_write_tokens']),
                         output=count(row['output_tokens']), reasoning=count(row['reasoning_tokens']))
            if row['cache_read_tokens'] is None or row['cache_write_tokens'] is None:
                event['cache_unreported'] = True
            events.setdefault(row['session_id'], []).append(event)
        sessions = []
        for session_id in metadata.keys() | events.keys():
            info = metadata.get(session_id, {})
            records = events.get(session_id, [])
            latest = records[-1] if records else None
            sums = {field: sum(event[field] for event in records) for field in FIELDS}
            times = [event['at'] for event in records if event['at'] is not None]
            for field in ('created_at_ms', 'updated_at_ms'):
                if info.get(field) is not None:
                    times.append(info[field] / 1000)
            parent = info.get('parent_session_id')
            sessions.append(dict(
                id=f'minimax-code:{session_id}', session_id=session_id, provider='minimax',
                conversation_id=parent or session_id, parent=parent, subagent=bool(parent),
                title=info.get('title') or 'MiniMax Code conversation', project=info.get('workspace_dir'),
                model=latest['model'] if latest else 'Unreported',
                models=sorted({event['model'] for event in records}), events=records,
                totals=dict(sums, total=sum(sums[field] for field in FIELDS if field != 'reasoning')),
                last=max(times) if times else None, modified=max(times) if times else 0,
                context=None, capacity=None, capacity_source=None, compactions=0,
                rate_limits=None, rate_limits_at=None, reported_cost=None, parse_errors=0,
                source=str(path), usage_source='MiniMax Code token ledger' if records else 'unavailable',
                cache_unreported=any(event.get('cache_unreported') for event in records),
                latest_usage={field: latest[field] for field in FIELDS} if latest else None,
                latest_usage_at=latest['at'] if latest else None))
        return sessions, [dict(provider='minimax', path=str(path), files=1)], []
    except (OSError, sqlite3.Error, ValueError, TypeError, OverflowError) as error:
        return [], [dict(provider='minimax', path=str(path), files=1)], [
            f'MiniMax Code: cannot read local runtime ({type(error).__name__})']
    finally:
        if connection is not None:
            connection.close()
