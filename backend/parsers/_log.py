import json
from pathlib import Path
from ._helpers import FIELDS, number, tokens, total, timestamp

class Log:
    def __init__(self, path, provider):
        self.path, self.provider = path, provider
        self.offset, self.identity, self.modified = 0, None, 0
        self.session_id = path.stem
        self.title = ''
        self.project = ''
        self.model = 'Unreported'
        self.models = set()
        self.last = None
        self.capacity = None
        self.rate_limits = None
        self.rate_limits_at = None
        self.quota_resets = {}
        self.messages = {}
        self.codex_events = []
        self.records = {}
        self.previous = {k: 0 for k in FIELDS}
        self.context = None
        self.compactions = 0
        self.errors = 0
        self.cost = None
        self.cost_usage = None
        self.subagent = 'subagents' in path.parts
        self.parent = None
        self.metadata_seen = False
        self.conversation_id = None
        self.latest_usage = None
        self.latest_usage_at = None
        self.marked_1m = False
        self.counter_snapshots = []
        self.compaction_marks = set()

    def refresh(self):
        stat = self.path.stat()
        identity = (stat.st_dev, stat.st_ino)
        if self.identity is not None and (identity != self.identity or stat.st_size < self.offset):
            self.__init__(self.path, self.provider)
        self.identity, self.modified = identity, stat.st_mtime
        with self.path.open('rb') as source:
            source.seek(self.offset)
            for line in source:
                if not line.endswith(b'\n'):
                    break
                self.offset += len(line)
                try:
                    data = json.loads(line)
                    if isinstance(data, dict):
                        self.consume(data)
                except (ValueError, TypeError, AttributeError):
                    self.errors += 1

    def consume(self, data):
        kind = data.get('type')
        stamp = timestamp(data.get('timestamp'))
        if stamp is not None:
            self.last = max(self.last or stamp, stamp)
        cwd = data.get('cwd')
        if cwd:
            self.project = Path(cwd).name
        if self.provider == 'codex':
            payload = data.get('payload') or {}
            if kind == 'session_meta' and not self.metadata_seen:
                self.metadata_seen = True
                self.session_id = payload.get('id', self.session_id)
                self.project = Path(payload.get('cwd') or '').name
                self.parent = payload.get('forked_from_id')
                source = payload.get('source', {})
                self.subagent = isinstance(source, dict) and 'subagent' in source
                self.subagent = self.subagent or payload.get('thread_source') == 'subagent'
                self.parent = payload.get('parent_thread_id') or self.parent
                self.conversation_id = (payload.get('session_id') or self.parent or self.session_id) if self.subagent else self.session_id
            elif kind == 'turn_context':
                self.model = payload.get('model') or self.model
                self.models.add(self.model)
            elif kind == 'compacted':
                self.compactions += 1
                self.compaction_marks.add(str(data.get('timestamp') or self.compactions))
            elif kind == 'event_msg' and payload.get('type') == 'token_count':
                owner = payload.get('thread_id')
                if (owner and owner != self.session_id) or (self.subagent and owner != self.session_id):
                    return
                if payload.get('rate_limits'):
                    self.rate_limits, self.rate_limits_at = payload['rate_limits'], stamp
                info = payload.get('info') or {}
                usage = info.get('total_token_usage')
                if usage is not None:
                    current = tokens(usage)
                    self.counter_snapshots.append(dict(at=stamp, model=self.model, **current))
                    reset = total(current) < total(self.previous)
                    delta = {k: max(0, current[k]-(0 if reset else self.previous[k])) for k in FIELDS}
                    if total(delta):
                        self.codex_events.append(dict(at=stamp, model=self.model, **delta))
                    self.previous = current
                last = info.get('last_token_usage')
                if last:
                    self.context = number(last.get('input_tokens')) + number(last.get('output_tokens'))
                    self.latest_usage = tokens(last)
                    self.latest_usage_at = stamp
                self.capacity = info.get('model_context_window') or self.capacity
            elif kind == 'token_usage_record':
                if payload.get('thread_id') and payload['thread_id'] != self.session_id:
                    return
                key = payload.get('response_id')
                if key and payload.get('usage'):
                    usage = tokens(payload['usage'])
                    old = self.records.get(key)
                    if old:
                        usage = {k: max(usage[k], old[k]) for k in FIELDS}
                    self.records[key] = dict(id=key, thread_id=self.session_id, at=stamp, model=self.model, **usage)
                    if self.latest_usage_at is None or (stamp is not None and stamp >= self.latest_usage_at):
                        self.latest_usage, self.latest_usage_at = usage, stamp
                        self.context = total(usage)
        else:
            quota = data.get('quotaLimits')
            if isinstance(quota, dict) and quota.get('rateLimitType') and isinstance(quota.get('resetsAt'), (int, float)):
                # Claude Code logs reset times only when a request is rejected at a limit.
                limit = quota['rateLimitType']
                self.quota_resets[limit] = max(self.quota_resets.get(limit, 0), quota['resetsAt'])
            if self.subagent and data.get('sessionId'):
                # Subagent transcripts record the parent chat's session ID.
                self.parent = data['sessionId']
            if kind == 'custom-title':
                self.title = str(data.get('customTitle') or '')[:180]
            elif kind == 'api-request':
                self.model = (data.get('params') or {}).get('model') or self.model
                self.models.add(self.model)
            elif kind == 'system' and data.get('subtype') == 'compact_boundary':
                self.compactions += 1
            elif kind == 'assistant':
                message = data.get('message') or {}
                usage = message.get('usage')
                key = message.get('id') or data.get('requestId') or data.get('uuid')
                if usage and key:
                    current = tokens(usage, True)
                    if not total(current):
                        return
                    # The 1-hour share of cache writes, when Claude Code records the split.
                    current['write_1h'] = number((usage.get('cache_creation') or {}).get('ephemeral_1h_input_tokens'))
                    self.model = message.get('model') or self.model
                    self.models.add(self.model)
                    # Claude Code marks 1M-context model selections with a [1m] suffix.
                    self.marked_1m = self.marked_1m or str(data.get('requestedModel') or '').endswith('[1m]')
                    previous = self.messages.get(key, {})
                    # Several content blocks can carry the same response usage.
                    current = {k: max(current[k], previous.get(k, 0)) for k in (*FIELDS, 'write_1h')}
                    self.messages[key] = dict(at=previous.get('at') or stamp, model=self.model, **current)
                    self.context = current['input'] + current['cached'] + current['write'] + current['output']
                    self.latest_usage, self.latest_usage_at = current, stamp
            elif kind == 'cost-state':
                if not data.get('hasUnknownModelCost') and isinstance(data.get('totalCostUSD'), (int, float)):
                    self.cost = data['totalCostUSD']
                self.cost_usage = data.get('modelUsage') or None

    def export(self, titles):
        events = list(self.records.values()) if self.records else self.codex_events
        if self.provider == 'claude':
            events = list(self.messages.values())
            if not events and self.cost_usage:
                for model, usage in self.cost_usage.items():
                    events.append(dict(at=None, model=model, **tokens({
                        'input_tokens': usage.get('inputTokens'),
                        'cache_read_input_tokens': usage.get('cacheReadInputTokens'),
                        'cache_creation_input_tokens': usage.get('cacheCreationInputTokens'),
                        'output_tokens': usage.get('outputTokens'),
                        'output_tokens_details': {'thinking_tokens': usage.get('thinkingTokens')},
                    }, True)))
        sums = {k: sum(e[k] for e in events) for k in FIELDS}
        result = dict(id=f'{self.provider}:{self.path}', session_id=self.session_id,
                    provider=self.provider, title=titles.get(self.session_id) or self.title or titles.get(self.parent) or self.project or self.path.stem,
                    project=self.project, model=self.model, models=sorted(self.models),
                    last=self.last, modified=self.modified, subagent=self.subagent, parent=self.parent,
                    totals=dict(**sums, total=total(sums)), events=events,
                    context=self.context, capacity=self.capacity, capacity_source='logged' if self.capacity else None,
                    compactions=self.compactions,
                    rate_limits=self.rate_limits, rate_limits_at=self.rate_limits_at, reported_cost=self.cost,
                    source=str(self.path), parse_errors=self.errors,
                    usage_source='cumulative token_count' if self.codex_events and not self.records else
                    ('response usage' if events and (self.records or self.messages) else 'cost-state' if events else 'unavailable'))
        if self.provider == 'codex':
            result.update(conversation_id=self.conversation_id or self.session_id,
                          latest_usage=self.latest_usage, latest_usage_at=self.latest_usage_at,
                          _counters=self.counter_snapshots, _compactions=sorted(self.compaction_marks))
        else:
            # Subagent usage belongs to the chat that delegated it.
            result.update(conversation_id=self.parent if self.subagent and self.parent else self.session_id,
                          latest_usage=self.latest_usage, latest_usage_at=self.latest_usage_at)
        return result
