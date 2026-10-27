#!/usr/bin/env python3
"""Serve the dashboard with made-up demo data, for the README screenshots.

    python3 docs/screenshots/demo.py [--port 8799]

Writes synthetic Claude Code and Codex logs, local LLM usage, provider settings and usage limits into a
temporary folder, then runs server.py on them. Live limit checks return the demo limits instead of asking
Claude Code or Codex, and price and update downloads are off. Nothing reads or changes your real logs.
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import random
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

CLAUDE_CHATS = [('Refactor billing service', 'billing-api', 'claude-opus-5-5'), ('Fix flaky checkout tests', 'web-shop', 'claude-sonnet-5-5'),
                ('Write onboarding docs', 'docs-site', 'claude-sonnet-5-5'), ('Migrate auth to OAuth', 'billing-api', 'claude-opus-5-5'),
                ('Profile slow search query', 'search', 'claude-haiku-5-5')]
CODEX_CHATS = [('Add dark mode to settings', 'web-shop', 'gpt-6.1-sol'), ('Speed up CI pipeline', 'infra', 'gpt-6.1-sol'),
               ('Clean up feature flags', 'web-shop', 'gpt-6.1')]
LOCAL_CHATS = [('ollama', 'llama3.2', 'Summarize this design doc in five bullet points'),
               ('ollama', 'qwen2.5-coder', 'Explain this regex and suggest a simpler one'),
               ('lmstudio', 'mistral-small', 'Draft release notes from these commit messages'),
               ('llamacpp', 'gemma-3-12b', 'Translate the error messages into Spanish')]


def stamp(at):
    return dt.datetime.fromtimestamp(at, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def busy_times(now, days, count, rng):
    """Request times weighted toward working hours over the last few days."""
    times = []
    while len(times) < count:
        at = now - rng.random() * days * 86400
        hour = dt.datetime.fromtimestamp(at).hour
        if rng.random() < (0.9 if 9 <= hour <= 19 else 0.15):
            times.append(at)
    return sorted(times)


def write_claude(home, now, rng):
    for n, (title, project, model) in enumerate(CLAUDE_CHATS):
        folder = home / 'projects' / f'-Users-demo-{project}'
        folder.mkdir(parents=True, exist_ok=True)
        session = f'demo-claude-{n}'
        lines = [dict(type='custom-title', customTitle=title, sessionId=session)]
        context = 20000
        for i, at in enumerate(busy_times(now, 3 if n else 1, rng.randint(18, 40), rng)):
            context = min(context + rng.randint(4000, 14000), 180000)
            usage = dict(input_tokens=rng.randint(200, 3000), cache_read_input_tokens=context,
                         cache_creation_input_tokens=rng.randint(1000, 9000), output_tokens=rng.randint(300, 2500))
            lines.append(dict(type='assistant', sessionId=session, timestamp=stamp(at), cwd=f'/Users/demo/{project}',
                              message=dict(id=f'{session}-{i}', model=model, usage=usage)))
        (folder / f'{session}.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in lines))


def write_codex(home, now, rng):
    folder = home / 'sessions' / '2026' / '10' / '26'
    folder.mkdir(parents=True, exist_ok=True)
    index = []
    for n, (title, project, model) in enumerate(CODEX_CHATS):
        session = f'demo-codex-{n}'
        index.append(dict(id=session, thread_name=title))
        lines = [dict(type='session_meta', timestamp=stamp(now - 4 * 86400), payload=dict(id=session, cwd=f'/Users/demo/{project}')),
                 dict(type='turn_context', payload=dict(model=model))]
        context = 15000
        for i, at in enumerate(busy_times(now, 3, rng.randint(15, 35), rng)):
            context = min(context + rng.randint(3000, 12000), 250000)
            usage = dict(input_tokens=context, cached_input_tokens=int(context * 0.85), output_tokens=rng.randint(200, 2000),
                         reasoning_output_tokens=rng.randint(50, 600))
            lines.append(dict(type='token_usage_record', timestamp=stamp(at), payload=dict(response_id=f'{session}-{i}', usage=usage)))
        (folder / f'rollout-{session}.jsonl').write_text(''.join(json.dumps(line) + '\n' for line in lines))
    (home / 'session_index.jsonl').write_text(''.join(json.dumps(row) + '\n' for row in index))


def write_local(data, now, rng):
    import local_proxy
    recorder = local_proxy.Recorder(data / 'local-usage.jsonl')
    for tool, model, first in LOCAL_CHATS:
        conversation, title = local_proxy.chat_identity(json.dumps(dict(model=model, messages=[dict(role='user', content=first)])).encode())
        for at in busy_times(now, 2, rng.randint(4, 10), rng):
            recorder.add(tool, model, rng.randint(400, 6000), rng.randint(150, 1200), '/api/chat', at=at,
                         conversation=conversation, title=title)


def demo_limits(now):
    hour = 3600
    return dict(
        claude=dict(primary=dict(used_percent=46, window_minutes=300, resets_at=now + 2.4 * hour),
                    secondary=dict(used_percent=38, window_minutes=10080, resets_at=now + 3.6 * 86400), observed_at=now, source='live'),
        codex=dict(primary=dict(used_percent=22, window_minutes=300, resets_at=now + 3.1 * hour),
                   secondary=dict(used_percent=31, window_minutes=10080, resets_at=now + 4.2 * 86400), observed_at=now, source='live',
                   plan_type='plus'))


def fake_check(tools, cwd, timeout=30):
    return dict(**demo_limits(time.time()), errors={}, checked_at=time.time())


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--port', type=int, default=8799)
    args = parser.parse_args()
    rng, now = random.Random(7), time.time()
    folder = Path(tempfile.mkdtemp(prefix='token-observatory-demo-'))
    claude, codex, data = folder / 'claude', folder / 'codex', folder / 'data'
    data.mkdir(parents=True)
    write_claude(claude, now, rng)
    write_codex(codex, now, rng)
    write_local(data, now, rng)
    (data / 'providers.json').write_text(json.dumps(dict(setup_done=True, enabled={p: True for p in ('claude', 'codex', 'ollama', 'lmstudio', 'llamacpp')})))
    os.environ.update(TOKEN_OBSERVATORY_PRICE_UPDATES='0', TOKEN_OBSERVATORY_UPDATE_CHECKS='0', HOME=str(folder))
    import server
    # The Store's live check is a default argument, so swap it there.
    defaults = server.Store.__init__.__defaults__
    server.Store.__init__.__defaults__ = tuple(fake_check if callable(d) else d for d in defaults)
    # Show the local LLM pass-throughs as running without opening their ports, which a real install may be using.
    server.apply_proxies = lambda _server: None
    server.local_proxy.reachable = lambda port, timeout=0.3: True
    server.providers.detect.__defaults__ = (server.local_proxy.reachable,)
    server.local_proxy.Proxies.status = lambda self: {t: dict(listening=True, error=None, port=i['listen']) for t, i in server.local_proxy.TOOLS.items()}
    print(f'Demo data in {folder}', flush=True)
    sys.argv = [sys.argv[0], '--port', str(args.port), '--claude-home', str(claude), '--codex-home', str(codex), '--data-dir', str(data / 'history')]
    server.main()


if __name__ == '__main__':
    main()
