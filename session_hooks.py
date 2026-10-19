"""Claude Code and Codex hooks: nudge a running conversation near its 5-hour limit or a full context.

The hook reads the hook input (https://code.claude.com/docs/en/hooks, https://learn.chatgpt.com/docs/hooks),
the conversation's transcript, and the newest 5-hour usage Token Observatory knows about, then returns
additionalContext asking the model to write a handoff summary or to keep its context small. Each nudge
fires once: the handoff once per 5-hour window per session, the context note once per threshold crossing.
A hook can't run /compact, so the context note asks the model to condense and suggest /compact.
Failures print nothing and exit 0, so a session is never blocked.
"""
import datetime as dt
import json
import os
from pathlib import Path
import sys
import time

import claude_context
import claude_limits
from claude_statusline import read_json, write_json

EVENTS = ('UserPromptSubmit', 'PostToolUse')
MARKER = '--hook'
TIMEOUT = 5
DEFAULT_LIMIT, DEFAULT_CONTEXT = 90, 60
TAIL_BYTES = 1 << 20
FIVE_HOURS = 5 * 3600
KEEP_SECONDS = 7 * 86400
NAMES = dict(claude='Claude', codex='Codex')


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def stamp(value):
    try:
        return dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp()
    except ValueError:
        return None


def thresholds(config):
    pick = lambda key, default: config.get(key) if number(config.get(key)) and 0 < config[key] <= 100 else default
    return pick('hook_limit_percent', DEFAULT_LIMIT), pick('hook_context_percent', DEFAULT_CONTEXT)


def newest_records(path):
    """Transcript records from the last megabyte, newest first."""
    with open(path, 'rb') as source:
        source.seek(0, os.SEEK_END)
        source.seek(max(0, source.tell() - TAIL_BYTES))
        lines = source.read().splitlines()
    for line in reversed(lines):
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record


def claude_context_use(path, windows):
    usage, model, marked_1m = None, None, False
    for record in newest_records(path):
        marked_1m = marked_1m or str(record.get('requestedModel') or '').endswith('[1m]')
        message = record.get('message') if record.get('type') == 'assistant' else None
        if usage is None and isinstance(message, dict) and isinstance(message.get('usage'), dict):
            u = message['usage']
            used = sum(number(u.get(k)) or 0 for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens'))
            if used:
                usage, model = used, message.get('model')
    capacity = claude_context.ONE_MILLION if marked_1m else windows.get(model)
    return (usage, capacity) if usage and capacity else None


def codex_records(path):
    """(context used, capacity) and the newest 5-hour window from a Codex rollout."""
    context, window = None, None
    for record in newest_records(path):
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        if record.get('type') != 'event_msg' or payload.get('type') != 'token_count':
            continue
        info = payload.get('info') if isinstance(payload.get('info'), dict) else {}
        last, capacity = info.get('last_token_usage'), number(info.get('model_context_window'))
        if context is None and isinstance(last, dict) and capacity:
            context = ((number(last.get('input_tokens')) or 0) + (number(last.get('output_tokens')) or 0), capacity)
        primary = (payload.get('rate_limits') or {}).get('primary') if isinstance(payload.get('rate_limits'), dict) else None
        if window is None and isinstance(primary, dict) and primary.get('window_minutes') == 300:
            window = (primary.get('used_percent'), primary.get('resets_at'), stamp(record.get('timestamp')))
        if context and window:
            break
    return context, window


def five_hour(candidates, now):
    """Newest (percent, resets_at) whose window hasn't reset; samples without a reset time count for 5 hours."""
    current = [(p, r, at) for p, r, at in candidates if number(p) is not None and (r > now if number(r) else at and now - at < FIVE_HOURS)]
    return max(current, key=lambda c: c[2] or 0, default=None)


def claude_windows(data_dir, desktop_file, now):
    found = []
    capture = claude_limits.read_capture(Path(data_dir) / 'claude-rate-limits.json') or {}
    if isinstance(capture.get('five_hour'), dict):
        found.append((capture['five_hour'].get('used_percentage'), capture['five_hour'].get('resets_at'), capture['captured_at']))
    live = read_json(Path(data_dir) / 'live-limits.json').get('claude')
    if isinstance(live, dict) and isinstance(live.get('primary'), dict):
        found.append((live['primary'].get('used_percent'), live['primary'].get('resets_at'), live.get('observed_at')))
    sample = claude_limits.PlanUsage(desktop_file).read() if desktop_file else None
    if sample:
        found.append((sample.get('five_hour'), None, sample.get('observed_at')))
    return found


def handoff_note(provider, percent, resets_at, cwd, session, now):
    folder = Path(cwd) / f'.{provider}' / 'handoffs'
    name = f"{dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d-%H%M')}-{session[:8]}.md"
    reset = f', resetting in about {round((resets_at - now) / 60)} minutes' if number(resets_at) else ''
    return (f'Token Observatory: your {NAMES[provider]} 5-hour usage limit is at {percent:.0f}%{reset}. '
            f'Finish or safely pause the current step and do not start new work. Then write a handoff summary to '
            f'{folder / name} (create the folder if needed) with: the goal, the current state, what is done, what is not done, '
            'next steps in order, key files and commands, and open questions or risks. Tell the user where it is saved, '
            'so the work can continue in a new conversation after the limit resets.')


def context_note(used, capacity):
    return (f'Token Observatory: this conversation\'s context is {100 * used / capacity:.0f}% full '
            f'({used:,} of {capacity:,} tokens). Compress and keep going: summarize what you still need from earlier work '
            'in a few lines, keep replies and tool output short, avoid re-reading large files, then continue the task. '
            'A hook cannot compact the conversation; if it keeps growing, suggest the user run /compact.')


def decide(payload, provider, data_dir, desktop_file, now):
    session, cwd, transcript = str(payload.get('session_id') or ''), payload.get('cwd') or os.getcwd(), payload.get('transcript_path')
    if not session:
        return []
    config = read_json(Path(data_dir) / 'config.json')
    limit_at, context_at = thresholds(config)
    if provider == 'codex':
        context, window = codex_records(transcript) if transcript and Path(transcript).is_file() else (None, None)
        live = read_json(Path(data_dir) / 'live-limits.json').get('codex')
        windows = [window] if window else []
        if isinstance(live, dict) and isinstance(live.get('primary'), dict):
            windows.append((live['primary'].get('used_percent'), live['primary'].get('resets_at'), live.get('observed_at')))
    else:
        windows = claude_windows(data_dir, desktop_file, now)
        context = claude_context_use(transcript, claude_context.load_windows(Path(data_dir) / 'config.json')[0]) \
            if transcript and Path(transcript).is_file() else None
    state_file = Path(data_dir) / 'hook-state.json'
    state = read_json(state_file)
    sessions = {k: v for k, v in (state.get('sessions') or {}).items() if isinstance(v, dict) and now - (v.get('seen') or 0) < KEEP_SECONDS}
    mine = dict(sessions.get(session) or {}, seen=now)
    notes = []
    window = five_hour(windows, now)
    if window and window[0] >= limit_at:
        # Sources report a window's reset a few seconds apart; the next window resets at least 5 hours later.
        key = window[1] if number(window[1]) else (window[2] or now) + FIVE_HOURS
        if not number(mine.get('handoff')) or key >= mine['handoff'] + FIVE_HOURS - 3600:
            mine['handoff'] = key
            notes.append(handoff_note(provider, window[0], window[1], cwd, session, now))
    if context:
        full = 100 * context[0] / context[1] >= context_at
        if full and mine.get('context_armed', True):
            notes.append(context_note(*context))
        mine['context_armed'] = not full
    write_json(state_file, dict(sessions=dict(sessions, **{session: mine})))
    return notes


def run(stream, provider='claude', data_dir=None, desktop_file=None, now=None):
    """The hook output for one event, or '' when there is nothing to say or anything goes wrong."""
    try:
        payload = json.load(stream)
        if not isinstance(payload, dict):
            return ''
        notes = decide(payload, provider, data_dir, desktop_file, time.time() if now is None else now)
    except Exception:  # A hook must never break the session.
        return ''
    if not notes:
        return ''
    return json.dumps(dict(hookSpecificOutput=dict(hookEventName=payload.get('hook_event_name') or 'UserPromptSubmit',
                                                   additionalContext='\n\n'.join(notes))))


# Installing: merge into Claude Code's settings.json and Codex's hooks.json, keeping every other hook.
def command_line(provider):
    if getattr(sys, 'frozen', False):
        base = f'"{sys.executable}" {MARKER}'
    else:
        base = f'"{sys.executable}" "{Path(__file__).resolve().parent / "launcher.py"}" {MARKER}'
    return base + (' codex' if provider == 'codex' else '')


def is_ours(handler):
    command = str(handler.get('command', '')) if isinstance(handler, dict) else ''
    return f'{MARKER}' in command.split() and ('launcher.py' in command or 'oken' in command)


def merged(config, install, provider):
    hooks = dict(config.get('hooks') or {})
    for event in EVENTS:
        groups = []
        for group in hooks.get(event) or []:
            handlers = group.get('hooks') if isinstance(group, dict) else None
            if isinstance(handlers, list) and any(is_ours(h) for h in handlers):
                kept = [h for h in handlers if not is_ours(h)]
                if kept:
                    groups.append(dict(group, hooks=kept))
            else:
                groups.append(group)
        if install:
            groups.append(dict(hooks=[dict(type='command', command=command_line(provider), timeout=TIMEOUT)]))
        if groups:
            hooks[event] = groups
        else:
            hooks.pop(event, None)
    result = dict(config, hooks=hooks)
    return result if hooks else {k: v for k, v in result.items() if k != 'hooks'}


def update_file(path, install, provider):
    path = Path(path)
    text = path.read_text() if path.exists() else ''
    config = read_json(path) if text.strip() else {}
    if text.strip() and not config:
        return False, f'{path} is not valid JSON; left unchanged.'
    updated = merged(config, install, provider)
    if updated == config:
        return True, f'{path}: already {"installed" if install else "removed"}.'
    if path.exists():
        path.with_name(path.name + '.bak').write_text(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(updated, indent=2) + '\n')
    return True, f'{"Added" if install else "Removed"} Token Observatory hooks in {path}.'


def update_hooks(install, env=None):
    """Install or remove the hooks for Claude Code and, when Codex is set up, for Codex. Returns [(ok, message)]."""
    env = os.environ if env is None else env
    claude = Path(env.get('CLAUDE_CONFIG_DIR') or Path.home() / '.claude') / 'settings.json'
    codex = Path(env.get('CODEX_HOME') or Path.home() / '.codex')
    results = [update_file(claude, install, 'claude')]
    if codex.is_dir():
        ok, message = update_file(codex / 'hooks.json', install, 'codex')
        results.append((ok, message + (' Codex runs new hooks only after you trust them: run /hooks in Codex.' if ok and install else '')))
    return results
