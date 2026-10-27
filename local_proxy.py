"""Count tokens for local LLM servers (Ollama, LM Studio, llama.cpp) with a recording pass-through proxy.

None of these servers keeps per-request token counts on disk, so Token Observatory listens on its own
loopback port, forwards each request unchanged to the real server, and reads the token counts from the
reply: Ollama's native `prompt_eval_count` / `eval_count`, or the OpenAI-compatible `usage` object.
Replies are never stored. Each answered request appends the time, model, token counts and, for chats, the
first 60 characters of the chat's first message (its title) to a JSON Lines file in the data folder.
"""
import datetime as dt
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import socket
import threading
import time

# Each tool's usual server port, and the port Token Observatory listens on in front of it.
TOOLS = {
    'ollama': dict(name='Ollama', target=11434, listen=11435),
    'lmstudio': dict(name='LM Studio', target=1234, listen=1235),
    'llamacpp': dict(name='llama.cpp', target=8080, listen=8081),
}
HOP_HEADERS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization', 'te', 'trailers',
               'transfer-encoding', 'upgrade', 'content-length', 'host'}
KEEP_BYTES = 16 * 1024 * 1024  # Larger replies keep only their tail, where streamed usage arrives.
TAIL_BYTES = 256 * 1024
TIMEOUT = 600  # Local models can take minutes to answer.
TITLE_CHARS = 60


def number(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else 0


def json_objects(body):
    """Every JSON object in a reply: a plain JSON body, NDJSON lines, or `data:` lines of a server-sent stream."""
    text = body.decode('utf-8', 'replace')
    try:
        whole = json.loads(text)
        return [whole] if isinstance(whole, dict) else []
    except ValueError:
        pass
    found = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('data:'):
            line = line[5:].strip()
        if not line.startswith('{'):
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            found.append(item)
    return found


def read_usage(body):
    """(model, input, output) from a reply, or None when it carries no token counts."""
    model, usage = None, None
    for item in json_objects(body):
        model = item.get('model') or model
        if isinstance(item.get('usage'), dict) and ('prompt_tokens' in item['usage'] or 'completion_tokens' in item['usage']):
            usage = (number(item['usage'].get('prompt_tokens')), number(item['usage'].get('completion_tokens')))
        elif 'prompt_eval_count' in item or 'eval_count' in item:
            usage = (number(item.get('prompt_eval_count')), number(item.get('eval_count')))
    return (model or 'unknown model', *usage) if usage else None


def chat_identity(body):
    """(conversation id, title) from a request. Chat apps resend the whole conversation each turn, so its first user
    message identifies the chat; the title keeps only its first TITLE_CHARS characters, like a chat app's chat list."""
    try:
        request = json.loads(body) if body else None
    except ValueError:
        return None, None
    if not isinstance(request, dict):
        return None, None
    first = None
    messages = request.get('messages')
    if isinstance(messages, list):
        first = next((m.get('content') for m in messages if isinstance(m, dict) and m.get('role') == 'user'), None)
        if isinstance(first, list):  # OpenAI-style content parts.
            first = ' '.join(part.get('text', '') for part in first if isinstance(part, dict))
    elif isinstance(request.get('prompt'), str):
        first = request['prompt']
    if not isinstance(first, str) or not first.strip():
        return None, None
    text = ' '.join(first.split())
    key = hashlib.sha256(f'{request.get("model")}\n{text}'.encode()).hexdigest()[:16]
    return key, text[:TITLE_CHARS] + ('…' if len(text) > TITLE_CHARS else '')


def with_stream_usage(path, body):
    """Ask OpenAI-compatible servers to include usage in streamed replies, unless the client already chose."""
    if not path.split('?')[0].endswith(('/chat/completions', '/completions')) or not body:
        return body
    try:
        request = json.loads(body)
    except ValueError:
        return body
    if not isinstance(request, dict) or request.get('stream') is not True or 'stream_options' in request:
        return body
    return json.dumps(dict(request, stream_options=dict(include_usage=True))).encode()


class Recorder:
    """Appends one JSON line per answered request: counts and a short chat title, never full prompts or replies."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def add(self, tool, model, input_tokens, output_tokens, endpoint, at=None, conversation=None, title=None):
        row = dict(at=time.time() if at is None else at, tool=tool, model=model, input=input_tokens,
                   output=output_tokens, endpoint=endpoint)
        if conversation:
            row.update(conversation=conversation, title=title)
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(row) + '\n')


def handler_for(tool, listen, target, recorder):
    # Only loopback Host names: a website that rebinds its own name to 127.0.0.1 is refused, as the servers do.
    hosts = {f'127.0.0.1:{listen}', f'localhost:{listen}', f'[::1]:{listen}'}

    class Proxy(BaseHTTPRequestHandler):
        # HTTP/1.0 lets a streamed reply end by closing, so no length is needed up front.
        protocol_version = 'HTTP/1.0'

        def forward(self):
            if (self.headers.get('Host') or '').lower() not in hosts:
                self.send_error(403, 'Unexpected Host header')
                return
            length = int(self.headers.get('Content-Length') or 0)
            body = self.rfile.read(length) if length > 0 else b''
            conversation, title = chat_identity(body) if self.command == 'POST' else (None, None)
            body = with_stream_usage(self.path, body) if self.command == 'POST' else body
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
            headers['Host'] = f'127.0.0.1:{target}'
            if body:
                headers['Content-Length'] = str(len(body))
            upstream = http.client.HTTPConnection('127.0.0.1', target, timeout=TIMEOUT)
            try:
                upstream.request(self.command, self.path, body=body or None, headers=headers)
                reply = upstream.getresponse()
            except OSError:
                upstream.close()
                self.send_error(502, f'{TOOLS[tool]["name"]} is not answering on port {target}')
                return
            self.send_response(reply.status, reply.reason)
            for key, value in reply.getheaders():
                if key.lower() not in HOP_HEADERS:
                    self.send_header(key, value)
            self.send_header('Connection', 'close')
            self.end_headers()
            kept, size = bytearray(), 0
            try:
                while True:
                    chunk = reply.read1(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
                    size += len(chunk)
                    kept += chunk
                    if size > KEEP_BYTES:
                        del kept[:-TAIL_BYTES]
            except OSError:
                pass  # The client went away; whatever arrived so far is still counted.
            finally:
                upstream.close()
            if self.command == 'POST' and 200 <= reply.status < 300:
                found = read_usage(bytes(kept))
                if found:
                    recorder.add(tool, found[0], found[1], found[2], self.path.split('?')[0], conversation=conversation, title=title)

        do_GET = do_POST = do_PUT = do_DELETE = do_HEAD = do_OPTIONS = do_PATCH = forward

        def log_message(self, *_):
            pass

    return Proxy


def reachable(port, timeout=0.3):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=timeout):
            return True
    except OSError:
        return False


class Proxies:
    """Starts and stops one proxy per enabled local tool."""

    def __init__(self, recorder):
        self.recorder = recorder
        self.running = {}
        self.errors = {}
        self.lock = threading.Lock()

    def apply(self, wanted):
        """wanted: {tool: (listen, target)} for every enabled local tool."""
        with self.lock:
            for tool in list(self.running):
                server, ports = self.running[tool]
                if wanted.get(tool) != ports:
                    server.shutdown()
                    server.server_close()
                    del self.running[tool]
            for tool, (listen, target) in wanted.items():
                if tool in self.running:
                    continue
                try:
                    server = ThreadingHTTPServer(('127.0.0.1', listen), handler_for(tool, listen, target, self.recorder))
                except OSError as error:
                    self.errors[tool] = f'Port {listen} is unavailable: {error.strerror}'
                    continue
                server.daemon_threads = True
                threading.Thread(target=server.serve_forever, daemon=True).start()
                self.running[tool] = (server, (listen, target))
                self.errors.pop(tool, None)
            for tool in list(self.errors):
                if tool not in wanted:
                    del self.errors[tool]

    def status(self):
        with self.lock:
            return {tool: dict(listening=tool in self.running, error=self.errors.get(tool),
                               port=self.running[tool][1][0] if tool in self.running else None)
                    for tool in TOOLS}

    def stop(self):
        self.apply({})


def sessions(path, enabled):
    """Recorded local requests as dashboard sessions: one per chat (by its first message), or per tool, model and
    day for requests that carry no chat messages."""
    groups = {}
    try:
        lines = Path(path).read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get('tool') not in enabled or not isinstance(row.get('at'), (int, float)):
            continue
        day = dt.datetime.fromtimestamp(row['at']).strftime('%Y-%m-%d')
        model = str(row.get('model') or 'unknown model')
        chat = row.get('conversation') if isinstance(row.get('conversation'), str) else None
        groups.setdefault((row['tool'], model, chat or day), []).append(row)
    result = []
    for (tool, model, chat_or_day), rows in groups.items():
        events = [dict(at=r['at'], model=model, input=number(r.get('input')), cached=0, write=0,
                       output=number(r.get('output')), reasoning=0) for r in rows]
        sums = {k: sum(e[k] for e in events) for k in ('input', 'cached', 'write', 'output', 'reasoning')}
        latest = max(events, key=lambda e: e['at'])
        key = f'{tool}:{model}:{chat_or_day}'
        title = next((r['title'] for r in reversed(rows) if isinstance(r.get('title'), str) and r['title']), None)
        result.append(dict(
            id=f'{tool}:{key}', session_id=key, conversation_id=key, provider=tool,
            title=title or f'{model} · {chat_or_day}', project=None, model=model, models=[model], last=latest['at'], modified=latest['at'],
            subagent=False, parent=None, totals=dict(**sums, total=sums['input'] + sums['output']), events=events,
            context=latest['input'] + latest['output'], capacity=None, capacity_source=None, compactions=0,
            rate_limits=None, rate_limits_at=None, reported_cost=None, source=str(path), parse_errors=0,
            usage_source='local proxy', latest_usage=None, latest_usage_at=latest['at']))
    return result
