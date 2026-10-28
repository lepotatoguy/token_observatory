"""Read recorded usage from LM Studio desktop chats without changing their files."""
import json
from pathlib import Path
import re

FIELDS = ('input', 'cached', 'write', 'output', 'reasoning')


def count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def step_time(identifier):
    # Saved step IDs contain their creation time in milliseconds followed by a random number.
    match = re.fullmatch(r'(\d{13})-\d+(?:\.\d+)?', identifier) if isinstance(identifier, str) else None
    return int(match[1]) / 1000 if match else None


def capacity(config):
    if not isinstance(config, dict) or not isinstance(config.get('fields'), list):
        return None
    for field in config['fields']:
        if isinstance(field, dict) and field.get('key') == 'llm.load.contextLength':
            return count(field.get('value')) or None
    return None


def parse_chat(path, data, modified):
    if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
        return None
    records, seen = [], set()
    for mi, message in enumerate(data['messages']):
        versions = message.get('versions') if isinstance(message, dict) else None
        if not isinstance(versions, list):
            continue
        for vi, version in enumerate(versions):
            if not isinstance(version, dict) or version.get('role') != 'assistant':
                continue
            steps = version.get('steps')
            if not isinstance(steps, list):
                continue
            thinking = 0
            for si, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                style = step.get('style')
                if isinstance(style, dict) and style.get('type') == 'thinking' and isinstance(step.get('content'), list):
                    thinking += sum(count(part.get('tokensCount')) or 0 for part in step['content']
                                    if isinstance(part, dict) and not part.get('fromDraftModel'))
                info = step.get('genInfo')
                stats = info.get('stats') if isinstance(info, dict) else None
                if not isinstance(stats, dict):
                    continue
                incoming, outgoing = count(stats.get('promptTokensCount')), count(stats.get('predictedTokensCount'))
                if incoming is None or outgoing is None:
                    continue
                identifier = step.get('stepIdentifier')
                key = identifier if isinstance(identifier, str) and identifier else f'{mi}:{vi}:{si}'
                if key not in seen:
                    seen.add(key)
                    model = info.get('identifier') or info.get('indexedModelIdentifier')
                    model = model if isinstance(model, str) and model else 'Unreported'
                    event = dict(id=key, at=step_time(identifier), model=model, cache_unreported=True, input=incoming, cached=0, write=0,
                                 output=outgoing, reasoning=thinking if thinking <= outgoing else 0)
                    records.append((event, capacity(info.get('loadModelConfig'))))
                thinking = 0
    events = [event for event, _ in records]
    latest, window = max(records, key=lambda pair: pair[0]['at'] or 0, default=(None, None))
    sums = {k: sum(e[k] for e in events) for k in FIELDS}
    times = [e['at'] for e in events if e['at'] is not None]
    for key in ('createdAt', 'assistantLastMessagedAt', 'userLastMessagedAt'):
        if count(data.get(key)) is not None:
            times.append(data[key] / 1000)
    model = latest['model'] if latest else 'Unreported'
    key = 'lmstudio:chat:' + path.stem
    title = data.get('name')
    return dict(id=key, session_id=key, conversation_id=key, provider='lmstudio',
                title=title[:180] if isinstance(title, str) and title else 'LM Studio chat',
                project=None, model=model, models=sorted({e['model'] for e in events}),
                last=max(times) if times else modified, modified=modified,
                subagent=False, parent=None, totals=dict(sums, total=sums['input'] + sums['output']), events=events,
                context=latest['input'] + latest['output'] if latest else None, capacity=window,
                capacity_source='logged' if window else None, compactions=0, rate_limits=None, rate_limits_at=None,
                reported_cost=None, source=str(path), source_files=[str(path)], parse_errors=0,
                usage_source='LM Studio chat file' if events else 'unavailable', cache_unreported=True,
                latest_usage={k: latest[k] for k in FIELDS} if latest else None,
                latest_usage_at=latest['at'] if latest else None)


class Chats:
    def __init__(self, folder=None):
        self.folder = Path(folder) if folder is not None else Path.home() / '.lmstudio/conversations'
        self.cache = {}
        self.files = 0
        self.warnings = []

    def read(self):
        self.warnings = []
        try:
            paths = sorted(self.folder.rglob('*.conversation.json')) if self.folder.is_dir() else []
        except OSError as error:
            self.warnings.append(f'LM Studio chat discovery: {error.strerror}')
            return []
        self.files = len(paths)
        self.cache = {p: cached for p, cached in self.cache.items() if p in paths}
        result = []
        for path in paths:
            previous = self.cache.get(path)
            try:
                stat = path.stat()
                signature = (stat.st_mtime_ns, stat.st_size)
                if previous and previous[0] == signature:
                    session = previous[1]
                else:
                    session = parse_chat(path, json.loads(path.read_text(encoding='utf-8')), stat.st_mtime)
                    self.cache[path] = (signature, session)
            except (OSError, ValueError, UnicodeError) as error:
                self.warnings.append(f'LM Studio: cannot read {path.name} ({type(error).__name__}); keeping its last good capture.')
                session = previous[1] if previous else None
            if session is not None:
                result.append(session)
        undated = sum(e['at'] is None for session in result for e in session['events'])
        if undated:
            self.warnings.append(f'LM Studio: {undated} responses lack recorded step timestamps; their usage appears only in All retained logs.')
        return result
