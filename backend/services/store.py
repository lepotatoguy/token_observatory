import json
from pathlib import Path
import threading
import time
from backend.parsers._log import Log
from backend.parsers.claude import ClaudeLog
from backend.parsers.codex import CodexLog
from backend.parsers._codex_usage import merge_threads
from backend.parsers import local_proxy
from backend.parsers import lmstudio as lmstudio_chats
from backend.services.archive import Archive
from backend.services import claude_context, claude_limits, claude_statusline, live_limits, limit_control, minimax, minimax_code, session_hooks
from backend.services import providers

LIVE_REUSE_SECONDS = 10

def latest_limits(sessions):
    """Newest account quota snapshot per provider; only Codex records one locally."""
    quotas = [s for s in sessions if s.get('rate_limits') and s.get('rate_limits_at')]
    newest = max(quotas, key=lambda s: s['rate_limits_at'], default=None)
    return {'codex': dict(newest['rate_limits'], observed_at=newest['rate_limits_at'])} if newest else {}


class Store:
    def __init__(self, codex, claude, data_dir=None, windows=None, config_warning=None, plan_usage=None, claude_limits_file=None,
                 live_file=None, live_tools=None, live_check=live_limits.check, settings=None, local_log=None, lmstudio_folder=None,
                 detect_providers=True):
        self.codex, self.claude = codex, claude
        self.settings = settings or providers.Settings(None)
        self.limit_control = limit_control.Control(Path(data_dir).parent if data_dir is not None else None)
        self.local_log = local_log
        self.local_parser = local_proxy.LocalProxyParser(local_log) if local_log else None
        self.lmstudio = lmstudio_chats.Chats(lmstudio_folder)
        self.detected = providers.detect(claude, codex, data_dir=self.limit_control.folder) if detect_providers else set()
        self.windows = claude_context.DEFAULT_WINDOWS if windows is None else windows
        self.config_warning = config_warning
        self.last_sessions = claude_context.LastSessions(claude)
        self.plan_usage = claude_limits.PlanUsage(plan_usage)
        self.claude_limits_file = claude_limits_file
        self.live_file, self.live_tools, self.live_check = live_file, live_tools, live_check
        self.live = claude_statusline.read_json(live_file) if live_file else {}
        self.live.pop('minimax', None)
        self.live.get('errors', {}).pop('minimax', None)
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
                count = 0
                if provider in enabled and not root.exists():
                    warnings.append(f'{provider}: log directory not found')
                try:
                    paths = list(root.rglob('*.jsonl')) if root.exists() else []
                    for path in paths:
                        try:
                            parser = ClaudeLog if provider == 'claude' else CodexLog
                            entry = self.logs.setdefault(str(path), parser(path, provider))
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
            sessions = merge_threads(sessions)
            # Provider switches control live services, not access to recorded usage.
            sessions = [part for session in sessions for part in minimax.split_session(session)]
            native, native_sources, native_warnings = minimax_code.read()
            sessions.extend(native)
            sources.extend(native_sources)
            warnings.extend(native_warnings)
            signature = tuple((s['id'], s['modified'], s['title']) for s in sessions)
            local_sessions = []
            if self.local_log:
                local_sessions += self.local_parser.read(local_proxy.TOOLS)
                sources.append(dict(provider='local', path=str(self.local_log), files=1 if Path(self.local_log).exists() else 0))
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
                self.live.get('errors', {}).pop('minimax', None)
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
