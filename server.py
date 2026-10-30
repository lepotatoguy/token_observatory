#!/usr/bin/env python3
"""Read local agent telemetry and serve a loopback-only dashboard. No dependencies."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit
from archive import Archive, DEFAULT_DATA
from codex_usage import merge_threads
import claude_context
import claude_limits
import claude_statusline
import live_limits
import limit_control
import session_hooks
import local_proxy
import lmstudio_chats
import pricing
import providers
import update_install
import updater

LIVE_REUSE_SECONDS = 10  # Clicks within this many seconds share one live check.
LIVE_INTERVAL = 300  # The collector also checks live limits this often, in seconds.

# Standalone builds unpack the dashboard assets into PyInstaller's bundle folder.
HERE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
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


def latest_limits(sessions):
    """Newest account quota snapshot per provider; only Codex records one locally."""
    quotas = [s for s in sessions if s.get('rate_limits') and s.get('rate_limits_at')]
    newest = max(quotas, key=lambda s: s['rate_limits_at'], default=None)
    return {'codex': dict(newest['rate_limits'], observed_at=newest['rate_limits_at'])} if newest else {}


class Store:
    def __init__(self, codex, claude, data_dir=None, windows=None, config_warning=None, plan_usage=None, claude_limits_file=None,
                 live_file=None, live_tools=None, live_check=live_limits.check, settings=None, local_log=None, lmstudio_folder=None):
        self.codex, self.claude = codex, claude
        self.settings = settings or providers.Settings(None)
        self.limit_control = limit_control.Control(Path(data_dir).parent if data_dir is not None else None)
        self.local_log = local_log
        self.lmstudio = lmstudio_chats.Chats(lmstudio_folder)
        self.detected = providers.detect(claude, codex)
        self.windows = claude_context.DEFAULT_WINDOWS if windows is None else windows
        self.config_warning = config_warning
        self.last_sessions = claude_context.LastSessions(claude)
        self.plan_usage = claude_limits.PlanUsage(plan_usage)
        self.claude_limits_file = claude_limits_file
        self.live_file, self.live_tools, self.live_check = live_file, live_tools, live_check
        self.live = claude_statusline.read_json(live_file) if live_file else {}
        self.live_lock = threading.Lock()
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
            enabled = self.settings.enabled(self.detected)
            for provider, root in [('codex', self.codex/'sessions'), ('claude', self.claude/'projects')]:
                if provider not in enabled:
                    continue
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
            last_sessions = self.last_sessions.read()
            for log, session in zip(logs, sessions):
                if log.provider == 'claude':
                    claude_context.apply(session, log.marked_1m, last_sessions, self.windows)
            if self.config_warning:
                warnings.append(self.config_warning)
            signature = tuple((s['id'], s['modified'], s['title']) for s in sessions)
            sessions = merge_threads(sessions)
            local_sessions = []
            if self.local_log and enabled & set(local_proxy.TOOLS):
                local_sessions += local_proxy.sessions(self.local_log, enabled)
                sources.append(dict(provider='local', path=str(self.local_log), files=1 if Path(self.local_log).exists() else 0))
            if 'lmstudio' in enabled:
                local_sessions += self.lmstudio.read()
                warnings.extend(self.lmstudio.warnings)
                sources.append(dict(provider='lmstudio', path=str(self.lmstudio.folder), files=self.lmstudio.files))
            sessions += local_sessions
            signature += tuple((s['id'], s['modified'], s['title'], s['totals']['total'], len(s['events'])) for s in local_sessions)
            limits = {p: v for p, v in self.limits(logs, sessions).items() if p in enabled}
            self.snapshot = dict(at=time.time(), sessions=sessions, sources=sources, warnings=warnings,
                                 limits=limits, accounting_version=2,
                                 providers=dict(enabled=sorted(enabled), setup_done=self.settings.snapshot()['setup_done']),
                                 live_limits=dict(checked_at=self.live.get('checked_at'),
                                                  errors={p: e for p, e in (self.live.get('errors') or {}).items() if p in enabled}))
            if self.archive:
                self.snapshot['archive'] = self.archive.update(self.snapshot, signature, force=force_save)
                if self.snapshot['archive']['error']:
                    warnings.append(self.snapshot['archive']['error'])
            self.snapshot['limit_control'] = self.limit_control.observe({p: {r['id']: r for r in session_hooks.limit_rows(q)} for p, q in limits.items()})
            self.scanned = time.monotonic()
            return self.snapshot

    def refresh_live(self):
        """Ask Claude Code and Codex for current limits, then rescan. Failed checks keep the last good answer."""
        with self.live_lock:
            if time.time() - (self.live.get('checked_at') or 0) >= LIVE_REUSE_SECONDS:
                enabled = self.settings.enabled(self.detected)
                tools = self.live_tools or dict(claude=live_limits.find_tool('claude'), codex=live_limits.find_tool('codex'))
                tools = {name: path for name, path in tools.items() if name in enabled}
                folder = Path(self.live_file).parent if self.live_file else Path.home()
                found = self.live_check(tools, str(folder if folder.is_dir() else Path.home()))
                self.live = dict(found, **{p: found[p] or self.live.get(p) for p in ('claude', 'codex')})
                if self.live_file:
                    claude_statusline.write_json(self.live_file, self.live)
        self.scanned = float('-inf')
        return self.read()

    def limits(self, logs, sessions):
        result = latest_limits(sessions)
        codex = self.live.get('codex')
        if codex and codex.get('observed_at', 0) >= result.get('codex', {}).get('observed_at', 0):
            result['codex'] = codex
        resets = {}
        for log in logs:
            for limit, at in log.quota_resets.items():
                resets[limit] = max(resets.get(limit, 0), at)
        claude = claude_limits.limits(self.plan_usage.read(), resets, time.time(), claude_limits.read_capture(self.claude_limits_file), self.live.get('claude'))
        return dict(result, claude=claude) if claude else result


class Handler(BaseHTTPRequestHandler):
    def allowed(self):
        hosts = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        origin = self.headers.get('Origin')
        if self.headers.get('Host', '') not in hosts or self.headers.get('Sec-Fetch-Site') == 'cross-site' or (
                origin and urlsplit(origin).netloc not in hosts):
            self.send_error(403)
            return False
        return True

    def json_body(self):
        """The request's JSON object, or None after replying with an error."""
        if self.headers.get_content_type() != 'application/json':
            self.send_error(415)
            return None
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            length = -1
        if length < 0:
            self.send_error(400, 'Bad Content-Length')
            return None
        if length > 1024:
            self.rfile.read(min(length, 65536))  # Read what was sent so the error reply arrives intact.
            self.send_error(413)
            return None
        try:
            payload = json.loads(self.rfile.read(length) or b'{}')
        except ValueError:
            payload = None
        if not isinstance(payload, dict):
            self.send_error(400, 'Expected a JSON object')
            return None
        return payload

    def do_POST(self):
        if not self.allowed():
            return
        route = urlsplit(self.path).path
        updates = getattr(self.server, 'updates', None)
        if route == '/api/refresh':
            body = self.server.store.refresh_live()
        elif route == '/api/limit-control':
            payload = self.json_body()
            if payload is None:
                return
            try:
                self.server.store.limit_control.update(payload)
            except ValueError as error:
                self.send_error(400, str(error))
                return
            self.server.store.scanned = float('-inf')
            body = self.server.store.limit_control.snapshot()
        elif route == '/api/providers':
            payload = self.json_body()
            if payload is None:
                return
            try:
                self.server.store.settings.update(payload)
            except ValueError as error:
                self.send_error(400, str(error))
                return
            apply_proxies(self.server)
            self.server.store.scanned = float('-inf')
            body = provider_status(self.server)
        elif route in ('/api/update/settings', '/api/update/install') and updates:
            # A JSON content type also makes browsers ask first for any cross-site attempt, which is never answered.
            payload = self.json_body()
            if payload is None:
                return
            try:
                body = updates.set_preferences(payload) if route.endswith('settings') else updates.start()
            except ValueError as error:
                self.send_error(400, str(error))
                return
        else:
            self.send_error(404)
            return
        self.reply(json.dumps(body, separators=(',', ':'), allow_nan=False).encode(), 'application/json')

    def do_GET(self):
        if not self.allowed():
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
        elif route == '/api/pricing':
            body = json.dumps(self.server.pricing.snapshot(), separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route == '/api/update' and getattr(self.server, 'updates', None):
            body = json.dumps(self.server.updates.status(), separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route == '/api/providers':
            body = json.dumps(provider_status(self.server), separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route == '/api/limit-control':
            body = json.dumps(self.server.store.limit_control.snapshot(), separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route == '/api/usage':
            body = json.dumps(self.server.store.read(), separators=(',', ':'), allow_nan=False).encode()
            content_type = 'application/json'
        elif route in ('/', '/index.html', '/app.js', '/insights.js', '/updates.js', '/setup.js', '/theme.js', '/style.css', '/logo.svg'):
            path = HERE / ('index.html' if route == '/' else route[1:])
            body = path.read_bytes()
            content_type = {'.html': 'text/html; charset=utf-8', '.css': 'text/css',
                            '.js': 'text/javascript', '.svg': 'image/svg+xml'}[path.suffix]
        else:
            self.send_error(404)
            return
        self.reply(body, content_type)

    def reply(self, body, content_type):
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


def apply_proxies(server):
    store = server.store
    enabled = store.settings.enabled(store.detected)
    server.proxies.apply({tool: store.settings.ports(tool) for tool in local_proxy.TOOLS if tool in enabled})


def provider_status(server):
    """Everything the setup and provider settings need: choices, what was detected, and proxy health."""
    store = server.store
    store.detected = providers.detect(store.claude, store.codex)
    proxies = server.proxies.status()
    local = {}
    for tool in local_proxy.TOOLS:
        listen, target = store.settings.ports(tool)
        local[tool] = dict(proxies[tool], listen=listen, target=target, server_up=local_proxy.reachable(target))
        if tool == 'lmstudio':
            local[tool]['chat_files'] = store.lmstudio.files
    return dict(settings=store.settings.snapshot(), enabled=sorted(store.settings.enabled(store.detected)),
                detected=store.detected, names=providers.NAMES, cloud=list(providers.CLOUD), local=local)


def main(restart_command=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--codex-home', type=Path, default=Path(os.environ.get('CODEX_HOME', str(Path.home()/'.codex'))))
    parser.add_argument('--claude-home', type=Path, default=Path(os.environ.get('CLAUDE_CONFIG_DIR', str(Path.home()/'.claude'))))
    parser.add_argument('--data-dir', type=Path, default=DEFAULT_DATA / 'history')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    windows, config_warning = claude_context.load_windows(args.data_dir.parent / 'config.json')
    server.store = Store(args.codex_home, args.claude_home, args.data_dir, windows, config_warning,
                         claude_limits.desktop_folder() / 'plan-usage-history.json',
                         args.data_dir.parent / 'claude-rate-limits.json', args.data_dir.parent / 'live-limits.json',
                         settings=providers.Settings(args.data_dir.parent / 'providers.json'),
                         local_log=args.data_dir.parent / 'local-usage.jsonl')
    server.proxies = local_proxy.Proxies(local_proxy.Recorder(args.data_dir.parent / 'local-usage.jsonl'))
    apply_proxies(server)
    server.pricing = pricing.Pricing(args.data_dir.parent / 'pricing.json', args.data_dir.parent / 'config.json')
    stop = threading.Event()
    # Restarting after an update runs this process's command again; launcher.py passes its own.
    restart_command = restart_command or [sys.executable, str(Path(sys.argv[0]).resolve()), *sys.argv[1:]]
    data_folder = args.data_dir.parent
    server.updates = updater.Updates(
        data_folder, kind=update_install.kind(getattr(sys, 'frozen', False), sys.platform, Path(__file__).resolve().parent, DEFAULT_DATA),
        root=Path(__file__).resolve().parent, restart_command=restart_command,
        before_restart=lambda: server.store.read(force_save=True),
        stop_server=lambda: threading.Thread(target=server.shutdown, daemon=True).start())

    def collect():
        while not stop.is_set():
            server.store.read()
            stop.wait(2)

    def check_live():
        # TOKEN_OBSERVATORY_LIVE_CHECKS=0 turns off the background checks (the tests use it); Refresh still asks.
        while not stop.is_set() and os.environ.get('TOKEN_OBSERVATORY_LIVE_CHECKS') != '0':
            server.store.refresh_live()
            stop.wait(LIVE_INTERVAL)

    def check_updates():
        server.updates.finish()
        server.updates.check(max_age=updater.START_INTERVAL)
        while not stop.wait(3600):
            server.updates.check()

    def update_prices():
        while not stop.is_set():
            server.pricing.update(cancelled=stop.is_set)
            stop.wait(3600)

    collector = threading.Thread(target=collect, daemon=True)
    collector.start()
    threading.Thread(target=check_live, daemon=True).start()
    threading.Thread(target=update_prices, daemon=True).start()
    threading.Thread(target=check_updates, daemon=True).start()
    print(f'Token Observatory: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        server.proxies.stop()
        collector.join()
        server.store.read(force_save=True)
        server.server_close()


if __name__ == '__main__':
    main()
