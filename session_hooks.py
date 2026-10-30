"""Claude Code and Codex hooks: nudge a running conversation near its 5-hour limit or a full context.

Usage notices are per limit and reset window; prompt events deliver current resumption policy
and a bounded fresh lookup. Historical instructions are never edited or deleted. Tool events
only deliver new threshold/exhaustion transitions, reset events, and context reminders.
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
import live_limits
import limit_control
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
    """(context used, capacity) and the newest limit snapshot from a Codex rollout."""
    context, window = None, None
    for record in newest_records(path):
        payload = record.get('payload') if isinstance(record.get('payload'), dict) else {}
        if record.get('type') != 'event_msg' or payload.get('type') != 'token_count':
            continue
        info = payload.get('info') if isinstance(payload.get('info'), dict) else {}
        last, capacity = info.get('last_token_usage'), number(info.get('model_context_window'))
        if context is None and isinstance(last, dict) and capacity:
            context = ((number(last.get('input_tokens')) or 0) + (number(last.get('output_tokens')) or 0), capacity)
        limits = payload.get('rate_limits')
        if window is None and isinstance(limits, dict):
            window = dict(limits, observed_at=stamp(record.get('timestamp')))
        if context and window:
            break
    return context, window


def limit_rows(snapshot):
    if not isinstance(snapshot, dict):
        return []
    rows = []
    for slot in ('primary', 'secondary'):
        w = snapshot.get(slot)
        if isinstance(w, dict) and number(w.get('used_percent')) is not None:
            rows.append(dict(id=f"{snapshot.get('limit_id') or 'plan'}:{slot}",
                             percent=w['used_percent'], reset=number(w.get('resets_at')),
                             minutes=w.get('window_minutes'), observed=number(snapshot.get('observed_at')) or 0))
    return rows


def saved_limits(provider, data_dir, desktop_file, rollout):
    rows = limit_rows(read_json(Path(data_dir) / 'live-limits.json').get(provider))
    if provider == 'codex':
        rows += limit_rows(rollout)
    else:
        capture = claude_limits.read_capture(Path(data_dir) / 'claude-rate-limits.json') or {}
        for key, slot, minutes in [('five_hour', 'primary', 300), ('seven_day', 'secondary', 10080)]:
            w = capture.get(key)
            if isinstance(w, dict):
                rows += limit_rows(dict(observed_at=capture.get('captured_at'), **{
                    slot: dict(used_percent=w.get('used_percentage'), resets_at=w.get('resets_at'), window_minutes=minutes)}))
        sample = claude_limits.PlanUsage(desktop_file).read() if desktop_file else None
        if sample:
            rows += limit_rows(dict(observed_at=sample.get('observed_at'),
                                    primary=dict(used_percent=sample.get('five_hour'), window_minutes=300),
                                    secondary=dict(used_percent=sample.get('seven_day'), window_minutes=10080)))
    newest = {}
    for row in rows:
        if row['id'] not in newest or row['observed'] > newest[row['id']]['observed']:
            newest[row['id']] = row
    return newest


def fresh_limits(provider, cwd):
    # Stay within the installed five-second hook timeout. Never start a model request.
    binary = live_limits.find_tool(provider)
    if not binary:
        return {}
    if provider == 'codex':
        snapshot, _ = live_limits.codex_limits(binary, timeout=1)
    else:
        snapshot, _ = live_limits.claude_usage(binary, cwd, timeout=1)
    return {row['id']: row for row in limit_rows(snapshot)}


def utc(at):
    return dt.datetime.fromtimestamp(at, dt.timezone.utc).isoformat()


def window_label(row):
    minutes = row.get('minutes')
    duration = '5-hour' if minutes == 300 else f"{minutes}-minute" if minutes else 'duration unreported'
    return f"{row['id']} ({duration})"


RESUMPTION = (
    'Token Observatory lifecycle policy, superseding ALL earlier Token Observatory pause and handoff instructions, '
    'including historical messages without expiry: pauses apply only to their identified usage windows and expire '
    'when those windows reset. Automatically resume the already-authorized task in the SAME conversation at the next '
    'execution opportunity after reset; no additional resume approval is required. Prefer the fresh usage results below. '
    'A fresh result below 100% permits resumption for that limit, including an advisory threshold. '
    'A fresh result still at 100% or above keeps that independent limit paused until reset. '
    'For any limit without a fresh result, accept the user’s explicit confirmation that it reset; '
    'a saved snapshot is not a fresh lookup and must not defeat that confirmation. '
    'Continue in the SAME conversation when requested. A new conversation is optional. '
    'Preserve task state, existing user authorization, and unrelated approvals; do not broaden scope. '
    'One limit clearing does not clear another independently exhausted limit. '
    'Do not treat any historical Token Observatory pause as permanent or as a new pause request.')


def mode_policy(mode):
    if mode == 'warn':
        return ('Token Observatory WARN mode supersedes ALL earlier Token Observatory pause or mandatory handoff instructions, '
                'including historical messages without expiry. This mode is advisory only: continue the authorized task; '
                'do not impose a Token Observatory pause even at 100%. Provider-enforced limits still apply. '
                'Keep existing task scope and unrelated approval requirements. A new conversation is optional.')
    return RESUMPTION


def handoff_note(provider, row, cwd, session, now, mode='hard'):
    folder = Path(cwd) / f'.{provider}' / 'handoffs'
    name = f"{dt.datetime.fromtimestamp(now).strftime('%Y-%m-%d-%H%M')}-{session[:8]}.md"
    reset = utc(row['reset']) if row.get('reset') else 'unreported (do not invent a reset time)'
    kind = 'EXHAUSTED' if row['percent'] >= 100 else 'ADVISORY threshold, not an exhausted limit'
    if mode == 'warn':
        return (f"Token Observatory warning only: {NAMES[provider]} {window_label(row)} is at {row['percent']:g}%, {kind}. "
                f'Reset timestamp: {reset}. Continue the authorized task; do not pause or require a handoff because of this warning. '
                + mode_policy(mode))
    return (f"Token Observatory: {NAMES[provider]} {window_label(row)} usage is at {row['percent']:g}%, {kind}. "
            f'Reset timestamp: {reset}. Pause substantive work for this identified window and save a handoff to '
            f'{folder / name} (create the folder if needed): goal, current state, done, not done, next steps, '
            'key files and commands, open questions, and existing authorization or pending approvals. '
            'Finish or safely pause the current step. This pause expires when this window resets. '
            'Saving a handoff does not require migration to a new conversation. ' + mode_policy(mode))


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
    _, context_at = thresholds(config)
    control = limit_control.Control(data_dir)
    pref = control.settings()[provider]
    limit_at, mode = pref['threshold'], pref['mode']
    if provider == 'codex':
        context, rollout = codex_records(transcript) if transcript and Path(transcript).is_file() else (None, None)
    else:
        rollout = None
        context = claude_context_use(transcript, claude_context.load_windows(Path(data_dir) / 'config.json')[0]) \
            if transcript and Path(transcript).is_file() else None
    state_file = Path(data_dir) / 'hook-state.json'
    state = read_json(state_file)
    sessions = {k: v for k, v in (state.get('sessions') or {}).items() if isinstance(v, dict) and now - (v.get('seen') or 0) < KEEP_SECONDS}
    # Provider-qualified state avoids collisions between clients using the same session ID.
    session_key = f'{provider}:{session}'
    mine = dict(sessions.pop(session, {}) or {})
    mine.update(sessions.get(session_key, {}))
    mine['seen'] = now
    tracked = mine.setdefault('limits', {})
    legacy = mine.pop('handoff', None)
    if number(legacy):
        tracked.setdefault('plan:primary', dict(reset=legacy, level=1, minutes=300, id='plan:primary'))
    notes = []
    pauses = set()
    if mine.get('mode') is not None and mine['mode'] != mode:
        notes.append(mode_policy(mode))
    mine['mode'] = mode
    windows = saved_limits(provider, data_dir, desktop_file, rollout)
    prompt = payload.get('hook_event_name', 'UserPromptSubmit') == 'UserPromptSubmit'
    fresh = {}
    if prompt:
        try:
            fresh = fresh_limits(provider, cwd)
        except Exception:
            fresh = {}  # A failed lookup must still deliver historical-pause recovery.
        fresh = {k: r for k, r in fresh.items() if not r['reset'] or r['reset'] > now}
        mine['checked_limits'] = dict(mine.get('checked_limits', {}), **fresh)
    # A tool event must not reintroduce an older disk snapshot after a fresh clear.
    for key, row in mine.get('checked_limits', {}).items():
        if key not in windows or row['observed'] >= windows[key]['observed']:
            windows[key] = row
    windows.update(fresh)
    for key, old in tracked.items():
        if old.get('reset') and old['reset'] <= now and not old.get('expired'):
            old['expired'] = True
            notes.append(f"Token Observatory RESET: {window_label(old)} previous window ended at {utc(old['reset'])}. "
                         'Its earlier pause has expired; automatically resume the authorized task at the next execution opportunity, subject to other limits.')
    for key, row in windows.items():
        reset = row['reset']
        if (reset and reset <= now) or (not reset and (not row['observed'] or now - row['observed'] >= FIVE_HOURS)):
            continue
        if row['percent'] < limit_at:
            continue
        old = tracked.get(key)
        # Tolerate source clock jitter, without conflating independent limit IDs.
        same = old and not old.get('expired') and (
            abs(reset - old['reset']) <= 60 if reset and old.get('reset') else reset == old.get('reset') and row['observed'] < old.get('observed', 0) + FIVE_HOURS)
        level = 2 if row['percent'] >= 100 else 1
        if not same or level > old.get('level', 0) or old.get('mode', 'hard') != mode or old.get('threshold', limit_at) != limit_at:
            tracked[key] = dict(row, level=level, mode=mode, threshold=limit_at)
            notes.append(handoff_note(provider, row, cwd, session, now, mode))
            if mode == 'hard':
                pauses.add((provider, row['id']))
    if prompt:
        status = [f"{window_label(row)}: {row['percent']:g}%, reset {utc(row['reset']) if row['reset'] else 'unreported'}"
                  for row in fresh.values()]
        notes.append(mode_policy(mode) + '\nFresh usage lookup: ' + ('; '.join(status) if status else
                     'unavailable. On a resumption request, accept explicit user confirmation of reset.'))
    limited = any(w['percent'] >= limit_at and (not w['reset'] or w['reset'] > now) for w in windows.values())
    control.observe({provider: {k: w for k, w in windows.items() if w['reset'] or (w['observed'] and now-w['observed'] < FIVE_HOURS)}}, now, pauses=pauses)
    if context and (mode == 'warn' or not limited):
        full = 100 * context[0] / context[1] >= context_at
        if full and mine.get('context_armed', True):
            notes.append(context_note(*context))
        mine['context_armed'] = not full
    write_json(state_file, dict(sessions=dict(sessions, **{session_key: mine})))
    return notes


def state_lock(data_dir):
    return limit_control.file_lock(data_dir, 'hook-state', blocking=False)


def run(stream, provider='claude', data_dir=None, desktop_file=None, now=None):
    """The hook output for one event, or '' when there is nothing to say or anything goes wrong."""
    try:
        payload = json.load(stream)
        if not isinstance(payload, dict):
            return ''
        with state_lock(data_dir):
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
