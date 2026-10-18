"""Join Codex log segments by thread and count each response once."""
FIELDS = ('input', 'cached', 'write', 'output', 'reasoning')


def total(usage):
    return sum(usage.get(k, 0) for k in FIELDS if k != 'reasoning')


def merge_threads(sessions):
    result = [s for s in sessions if s['provider'] != 'codex']
    threads = {}
    for session in sessions:
        if session['provider'] == 'codex':
            threads.setdefault(session['session_id'], []).append(session)
    for thread_id, segments in threads.items():
        latest = max(segments, key=lambda s: (s['last'] or 0, s['modified']))
        merged = dict(latest)
        records = {}
        for segment in segments:
            if segment['usage_source'] != 'response usage':
                continue
            for event in segment['events']:
                key = event['id']
                previous = records.get(key)
                if previous:
                    dates = [at for at in [previous['at'], event['at']] if at is not None]
                    records[key] = dict(event, at=min(dates) if dates else None,
                                        **{k: max(event[k], previous[k]) for k in FIELDS})
                else:
                    records[key] = event
        first_record = min((e['at'] for e in records.values() if e['at'] is not None), default=None)
        counters = {}
        for segment in segments:
            if segment['usage_source'] == 'response usage':
                continue
            for event in segment['_counters']:
                # Modern response records supersede their overlapping counters.
                if records and (first_record is None or event['at'] is None or event['at'] >= first_record):
                    continue
                key = (event['at'], *(event[k] for k in FIELDS))
                counters[key] = event
        previous = dict.fromkeys(FIELDS, 0)
        events = []
        for event in sorted(counters.values(), key=lambda e: e['at'] or 0):
            reset = total(event) < total(previous)
            delta = {k: max(0, event[k] - (0 if reset else previous[k])) for k in FIELDS}
            if total(delta):
                events.append(dict(at=event['at'], model=event['model'], **delta))
            previous = event
        events.extend(records.values())
        events.sort(key=lambda e: e['at'] or 0)
        sums = {k: sum(e[k] for e in events) for k in FIELDS}
        context = max(segments, key=lambda s: s['latest_usage_at'] or 0)
        merged.update(id='codex:' + thread_id, events=events,
                      totals=dict(sums, total=total(sums)),
                      models=sorted({model for s in segments for model in s['models']}),
                      source_files=sorted({s['source'] for s in segments}),
                      modified=max(s['modified'] for s in segments),
                      parse_errors=sum(s['parse_errors'] for s in segments),
                      compactions=len({mark for s in segments for mark in s['_compactions']}),
                      context=context['context'], capacity=context['capacity'],
                      latest_usage=context['latest_usage'], latest_usage_at=context['latest_usage_at'],
                      accounting_version=2,
                      usage_source='response usage' if records else 'cumulative token_count' if events else 'unavailable')
        merged.pop('_counters', None)
        merged.pop('_compactions', None)
        result.append(merged)
    by_id = {s['session_id']: s for s in result if s['provider'] == 'codex'}
    for session in by_id.values():
        owner = session
        seen = set()
        while owner['subagent'] and owner.get('parent') in by_id and owner['session_id'] not in seen:
            seen.add(owner['session_id'])
            owner = by_id[owner['parent']]
        session['conversation_id'] = owner.get('conversation_id') or owner['session_id']
    return sorted(result, key=lambda s: s['last'] or s['modified'], reverse=True)
