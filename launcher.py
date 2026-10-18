#!/usr/bin/env python3
"""Start the Token Observatory collector once in the background, then open the dashboard.

Entry point for the standalone macOS, Linux and Windows builds. Also runs from a checkout.
"""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser

from archive import DEFAULT_DATA

VERSION = '1.0.1'  # Release tags must match; the PyInstaller spec reads it from here.
STARTUP_SECONDS = 60  # First launches can wait on OS malware scans; one-file builds also unpack first.
PID_FILE = DEFAULT_DATA / 'collector.pid'
LOG_FILE = DEFAULT_DATA / 'service.log'


def say(message, error=False):
    # Windowed builds have no console, so standard streams can be None.
    stream = sys.stderr if error else sys.stdout
    if stream:
        print(message, file=stream, flush=True)


# Loopback checks must never go through a configured HTTP proxy.
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def healthy(url):
    try:
        with LOCAL.open(url + '/api/health', timeout=1) as response:
            return b'"app":"token-observatory"' in response.read()
    except OSError:
        return False


def spawn(port):
    command = [sys.executable] if getattr(sys, 'frozen', False) else [sys.executable, str(Path(__file__).resolve())]
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                   # Without this, a one-file child reuses the parent's unpack folder, deleted when the parent exits.
                   env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1'))
    if sys.platform == 'win32':
        options['creationflags'] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        options['start_new_session'] = True
    subprocess.Popen(command + ['--serve', '--port', str(port)], **options)


def serve(port):
    DEFAULT_DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    log = LOG_FILE.open('a', buffering=1, encoding='utf-8')
    sys.stdout = sys.stderr = log
    PID_FILE.write_text(str(os.getpid()))

    def stop(*_):
        raise KeyboardInterrupt  # Lets server.main save history before exiting.
    signal.signal(signal.SIGTERM, stop)
    sys.argv = [sys.argv[0], '--port', str(port)]
    import server
    try:
        server.main()
    finally:
        if PID_FILE.exists() and PID_FILE.read_text() == str(os.getpid()):
            PID_FILE.unlink()


def stop_collector(url):
    try:
        pid = int(PID_FILE.read_text())
    except (OSError, ValueError):
        say('No collector started by this launcher is running.')
        return 0
    # Only signal the recorded process while the collector answers, so a reused PID is never hit.
    if healthy(url):
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError as error:
            say(f'Could not stop collector {pid}: {error}', error=True)
            return 1
        say('Collector stopped.')
    PID_FILE.unlink(missing_ok=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description='Token Observatory: local token telemetry for Claude Code and Codex.')
    parser.add_argument('--port', type=int, default=int(os.environ.get('TOKEN_OBSERVATORY_PORT', 8765)))
    parser.add_argument('--no-open', action='store_true', help='start the collector without opening a browser')
    parser.add_argument('--stop', action='store_true', help='stop the background collector')
    parser.add_argument('--serve', action='store_true', help=argparse.SUPPRESS)
    parser.add_argument('--version', action='version', version=f'Token Observatory {VERSION}')
    args = parser.parse_args()
    url = f'http://127.0.0.1:{args.port}'
    if args.serve:
        return serve(args.port)
    if args.stop:
        return stop_collector(url)
    if not healthy(url):
        spawn(args.port)
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
