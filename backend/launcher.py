#!/usr/bin/env python3
"""Start the Token Observatory collector once in the background, then open the dashboard.

Entry point for the standalone macOS, Linux and Windows builds. Also runs from a checkout.
"""
import argparse

# Support direct execution as well as python -m backend.launcher.
if __package__ in (None, ""):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit
import webbrowser

from backend.services.archive import DEFAULT_DATA
from backend.services import claude_limits
from backend.services import claude_statusline
from backend.services import session_hooks

from backend.version import VERSION
STARTUP_SECONDS = 60  # First launches can wait on OS malware scans; one-file builds also unpack first.
DATA_FOLDER = Path(os.environ.get('TOKEN_OBSERVATORY_DATA_DIR', str(DEFAULT_DATA / 'history'))).expanduser().parent
PID_FILE = DATA_FOLDER / 'collector.pid'
LOG_FILE = DATA_FOLDER / 'service.log'
CLAUDE_LIMITS_FILE = DATA_FOLDER / 'claude-rate-limits.json'


def say(message, error=False):
    # Windowed builds have no console, so standard streams can be None.
    stream = sys.stderr if error else sys.stdout
    if stream:
        print(message, file=stream, flush=True)


# Loopback checks must never go through a configured HTTP proxy.
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def health_identity(url):
    try:
        with LOCAL.open(url + '/api/health', timeout=1) as response:
            import json
            body = json.load(response)
            if body.get('app') == 'token-observatory' and body.get('version') == 2:
                return dict(body, pid=getattr(response, 'headers', {}).get('X-Token-Observatory-Pid'))
    except (OSError, ValueError, AttributeError):
        return None
    return None


def healthy(url):
    return health_identity(url) is not None


def pid_path(port, folder=None):
    base = Path(folder) / 'collector.pid' if folder is not None else PID_FILE
    return base if port == 8765 else base.with_name(f'collector-{port}.pid')


def spawn(port, extra_args=None):
    command = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve())]
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                   # Without this, a one-file child reuses the parent's unpack folder, deleted when the parent exits.
                   env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
    if sys.platform == 'win32':
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    subprocess.Popen(command + ['--serve', '--port', str(port)] + (extra_args or []), **options)


def serve(port, config=None):
    from backend.app import create_app
    from backend.config import Config
    from werkzeug.serving import make_server
    config = config or Config(PORT=port)
    if getattr(config, 'CLAUDE_PLAN_FILE', None) is None:
        config.CLAUDE_PLAN_FILE = claude_limits.desktop_folder() / 'plan-usage-history.json'
    if getattr(config, 'LMSTUDIO_FOLDER', None) is None:
        config.LMSTUDIO_FOLDER = Path.home() / '.lmstudio/conversations'
    folder = Path(config.DATA_DIR).parent
    folder.mkdir(parents=True, exist_ok=True)
    pid_file, log_file = pid_path(port, folder), folder / 'service.log'
    old_stdout, old_stderr = sys.stdout, sys.stderr
    server = runtime = old_handler = None
    pid_written = False
    try:
        with log_file.open('a', buffering=1, encoding='utf-8') as log:
            sys.stdout = sys.stderr = log
            try:
                app = create_app(config)
                server = make_server('127.0.0.1', port, app, threaded=True)
                pid_file.write_text(str(os.getpid()))
                pid_written = True
                runtime = app.extensions['runtime']
                import threading
                shutdown = lambda: threading.Thread(target=server.shutdown, daemon=True).start()
                old_handler = signal.signal(signal.SIGTERM, lambda *_: shutdown())
                command = [sys.executable] + ([] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve())])
                runtime.start(restart_command=command + ['--serve', '--port', str(port),
                              '--data-dir', str(config.DATA_DIR), '--codex-home', str(config.CODEX_HOME),
                              '--claude-home', str(config.CLAUDE_HOME)], shutdown=shutdown)
                say(f'Token Observatory: http://127.0.0.1:{port}')
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                try:
                    if runtime:
                        runtime.stop()
                finally:
                    if server:
                        server.server_close()
                    if old_handler is not None:
                        signal.signal(signal.SIGTERM, old_handler)
                    if pid_written and pid_file.exists() and pid_file.read_text() == str(os.getpid()):
                        pid_file.unlink()
                    sys.stdout, sys.stderr = old_stdout, old_stderr
    finally:
        sys.stdout, sys.stderr = old_stdout, old_stderr
    return 0


def stop_collector(url):
    pid_file = pid_path(urlsplit(url).port or 8765)
    try:
        pid = int(pid_file.read_text())
    except (OSError, ValueError):
        say('No collector started by this launcher is running.')
        return 0
    identity = health_identity(url)
    if identity is not None and identity['pid'] != str(pid):
        say('Refusing to stop: the PID file does not match the responding collector.', error=True)
        return 1
    if identity is not None:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as error:
            say(f'Could not stop collector {pid}: {error}', error=True)
            return 1
        say('Collector stopped.')
    pid_file.unlink(missing_ok=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description='Token Observatory: local token telemetry for Claude Code, Codex and local LLMs.')
    parser.add_argument('--port', type=int, default=int(os.environ.get('TOKEN_OBSERVATORY_PORT', 8765)))
    parser.add_argument('--no-open', action='store_true', help='start the collector without opening a browser')
    parser.add_argument('--stop', action='store_true', help='stop the background collector')
    parser.add_argument('--statusline', action='store_true', help='status line mode for Claude Code: save its rate limits')
    parser.add_argument('--install-statusline', action='store_true', help="add the status line to Claude Code's settings")
    parser.add_argument('--uninstall-statusline', action='store_true', help="remove it from Claude Code's settings")
    parser.add_argument('--hook', nargs='?', const='claude', choices=('claude', 'codex', 'minimax'),
                        help='hook mode for Claude Code or Codex: 5-hour limit and context reminders')
    parser.add_argument('--install-hooks', action='store_true', help='add the hooks to Claude Code (and Codex, when set up)')
    parser.add_argument('--uninstall-hooks', action='store_true', help='remove them')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--version', action='version', version=f'Token Observatory {VERSION}')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--codex-home', type=Path)
    parser.add_argument('--claude-home', type=Path)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    extra_args = []
    for name in ('data_dir', 'codex_home', 'claude_home'):
        value = getattr(args, name)
        if value is not None:
            extra_args.extend(['--' + name.replace('_', '-'), str(value)])
    if args.data_dir is not None:
        global PID_FILE, LOG_FILE, DATA_FOLDER, CLAUDE_LIMITS_FILE
        DATA_FOLDER = args.data_dir.parent
        PID_FILE = DATA_FOLDER / 'collector.pid'
        LOG_FILE = DATA_FOLDER / 'service.log'
        CLAUDE_LIMITS_FILE = DATA_FOLDER / 'claude-rate-limits.json'
    url = f'http://127.0.0.1:{args.port}'
    if args.serve:
        if extra_args:
            from backend.config import Config
            values = {name.upper(): getattr(args, name) for name in ('data_dir', 'codex_home', 'claude_home')
                      if getattr(args, name) is not None}
            return serve(args.port, Config(PORT=args.port, **values))
        return serve(args.port)
    if args.statusline:
        say(claude_statusline.capture(sys.stdin, CLAUDE_LIMITS_FILE))
        return 0
    if args.hook:
        output = session_hooks.run(sys.stdin, args.hook, DATA_FOLDER, claude_limits.desktop_folder() / 'plan-usage-history.json')
        if output:
            say(output)
        return 0
    if args.install_hooks or args.uninstall_hooks:
        results = session_hooks.update_hooks(install=args.install_hooks)
        for ok, message in results:
            say(message, error=not ok)
        return 0 if all(ok for ok, _ in results) else 1
    if args.install_statusline or args.uninstall_statusline:
        ok, message = claude_statusline.update_settings(install=args.install_statusline)
        say(message, error=not ok)
        return 0 if ok else 1
    if args.stop:
        return stop_collector(url)
    if not healthy(url):
        spawn(args.port, extra_args) if extra_args else spawn(args.port)
        deadline = time.monotonic() + STARTUP_SECONDS
        while not healthy(url):
            if time.monotonic() > deadline:
                say(f'Collector did not start. See {LOG_FILE}', error=True)
                return 1
            time.sleep(0.2)
    say(f'Token Observatory: {url}')
    if not args.no_open:
        webbrowser.open(url)
    return 0


if __name__ == '__main__':
    sys.exit(main())
