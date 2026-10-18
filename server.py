#!/usr/bin/env python3
"""Read local agent telemetry and serve a loopback-only dashboard. No dependencies."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from archive import Archive, DEFAULT_DATA
from codex_usage import merge_threads

HERE = Path(__file__).resolve().parent
FIELDS = ('input', 'cached', 'write', 'output', 'reasoning')


def number(value):
    return max(0, int(value)) if isinstance(value, (int, float)) else 0


def tokens(usage, claude=False):
    cached = number(usage.get('cache_read_input_tokens' if claude else 'cached_input_tokens'))
    write = number(usage.get('cache_creation_input_tokens' if claude else 'cache_write_input_tokens'))
    raw_input = number(usage.get('input_tokens'))
    return dict(input=raw_input if claude else max(0, raw_input-cached-write),
                cached=cached, write=write, output=number(usage.get('output_tokens')),
                reasoning=number((usage.get('output_tokens_details') or {}).get('thinking_tokens'))
                if claude else number(usage.get('reasoning_output_tokens')))


def total(usage):
    # Reasoning is already included in output tokens.
    return sum(usage.get(k, 0) for k in FIELDS if k != 'reasoning')


def timestamp(value):
    try:
        return dt.datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
    except (ValueError, TypeError, AttributeError):
        return None


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
                self.rate_limits = payload.get('rate_limits') or self.rate_limits
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
                    self.model = message.get('model') or self.model
                    self.models.add(self.model)
                    previous = self.messages.get(key, {})
                    # Several content blocks can carry the same response usage.
                    current = {k: max(current[k], previous.get(k, 0)) for k in FIELDS}
                    self.messages[key] = dict(at=previous.get('at') or stamp, model=self.model, **current)
                    self.context = current['input'] + current['cached'] + current['write'] + current['output']
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
                    context=self.context, capacity=self.capacity, compactions=self.compactions,
                    rate_limits=self.rate_limits, reported_cost=self.cost,
                    source=str(self.path), parse_errors=self.errors,
                    usage_source='cumulative token_count' if self.codex_events and not self.records else
                    ('response usage' if events and (self.records or self.messages) else 'cost-state' if events else 'unavailable'))
        if self.provider == 'codex':
            result.update(conversation_id=self.conversation_id or self.session_id,
                          latest_usage=self.latest_usage, latest_usage_at=self.latest_usage_at,
                          _counters=self.counter_snapshots, _compactions=sorted(self.compaction_marks))
        return result


class Store:
    def __init__(self, codex, claude, data_dir=None):
        self.codex, self.claude = codex, claude
        self.logs = {}
        self.lock = threading.Lock()
        self.snapshot = None
        self.scanned = 0
        self.archive = Archive(data_dir) if data_dir is not None else None

    def read(self, force_save=False):
        with self.lock:
            if not force_save and self.snapshot and time.monotonic()-self.scanned < 1.5:
                return self.snapshot
            logs, warnings, sources = [], [], []
            titles = {}
            index = self.codex / 'session_index.jsonl'
            if index.exists():
                try:
                    for line in index.open():
                        try:
                            row = json.loads(line)
                            if row.get('thread_name'):
                                titles[row.get('id')] = row['thread_name']
                        except ValueError:
                            pass
                except OSError as error:
                    warnings.append(f'Session titles: {error.strerror}')
            for provider, root in [('codex', self.codex/'sessions'), ('claude', self.claude/'projects')]:
                count = 0
                if not root.exists():
                    warnings.append(f'{provider}: log directory not found')
                try:
                    paths = list(root.rglob('*.jsonl')) if root.exists() else []
                    for path in paths:
                        try:
                            entry = self.logs.setdefault(str(path), Log(path, provider))
                            entry.refresh()
                            logs.append(entry)
                            count += 1
                        except OSError as error:
                            warnings.append(f'{provider}: cannot read {path.name}: {error.strerror}')
                except OSError as error:
                    warnings.append(f'{provider}: discovery failed: {error.strerror}')
                sources.append(dict(provider=provider, path=str(root), files=count))
            # Read every log before export so subagents can show their parent chat's title.
            titles.update((log.session_id, log.title) for log in logs if log.provider == 'claude' and log.title and not log.subagent)
            sessions = [log.export(titles) for log in logs]
            signature = tuple((s['id'], s['modified'], s['title']) for s in sessions)
            sessions = merge_threads(sessions)
            self.snapshot = dict(at=time.time(), sessions=sessions, sources=sources, warnings=warnings, accounting_version=2)
            if self.archive:
                self.snapshot['archive'] = self.archive.update(self.snapshot, signature, force=force_save)
                if self.snapshot['archive']['error']:
                    warnings.append(self.snapshot['archive']['error'])
            self.scanned = time.monotonic()
            return self.snapshot


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        host = self.headers.get('Host', '')
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if host not in allowed or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.send_error(403)
            return
        route = urlsplit(self.path).path
        if route == '/api/health':
            body = b'{"app":"token-observatory","version":2}'
            content_type = 'application/json'
        elif route.startswith('/api/history/') and self.server.store.archive:
            try:
                snapshot = self.server.store.archive.load(route[len('/api/history/'):])
            except FileNotFoundError:
                self.send_error(404, 'Saved snapshot not found')
                return
            except (OSError, ValueError):
                self.send_error(400, 'Saved snapshot is unreadable')
                return
            body = json.dumps(snapshot, separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route == '/api/usage':
            body = json.dumps(self.server.store.read(), separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route in ('/', '/index.html', '/app.js', '/style.css', '/logo.svg'):
            path = HERE / ('index.html' if route == '/' else route[1:])
            body = path.read_bytes()
            content_type = {'.html': 'text/html; charset=utf-8', '.css': 'text/css',
                            '.js': 'text/javascript', '.svg': 'image/svg+xml'}[path.suffix]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_):
        pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))))
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home()/'.claude'))))
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA / 'history')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.store = Store(args.codex_home, args.claude_home, args.data_dir)
    stop = threading.Event()

    def collect():
        while not stop.is_set():
            server.store.read()
            stop.wait(2)

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()
    print(f'Token Observatory: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        collector.join()
        server.store.read(force_save=True)
        server.server_close()


if __name__ == '__main__':
    main()
