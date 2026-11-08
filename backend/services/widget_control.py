"""Owns the floating widget's on/off setting and keeps one widget process running while it is on.

The widget is a separate process because Qt needs the main thread and a crash must not take down the
collector. The server never kills it by PID: the widget polls `/api/widget` and quits itself when the
setting turns off, which avoids stale PID files and PID reuse.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from backend.services import float_panel

GRACE_SECONDS = 30       # a widget that has not polled for this long counts as not running
EARLY_SECONDS = 5        # an exit sooner than this after starting counts as a crash
MAX_FAILURES = 3
MANAGED = 'TOKEN_OBSERVATORY_WIDGET_MANAGED'  # tells a widget that the setting controls its lifetime
ALREADY_RUNNING = 75     # exit code of a widget that found another instance holding the lock
UNAVAILABLE = 'The widget runtime (PySide6) could not be loaded. Reinstall Token Observatory.'


def command(port):
    """Same entry point the collector uses for itself, in float mode."""
    launcher = [] if getattr(sys, 'frozen', False) else [str(Path(__file__).resolve().parents[1] / 'launcher.py')]
    return [sys.executable, *launcher, '--float', '--port', str(port)]


def detach_options(log):
    options = dict(stdin=subprocess.DEVNULL, stdout=log, stderr=log, close_fds=True,
                   # A one-file build would otherwise reuse the parent's unpack folder, deleted when it exits.
                   env=dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1', **{MANAGED: '1'}))
    if sys.platform == 'win32':
        options['creationflags'] = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                    | subprocess.CREATE_NO_WINDOW)
    else:
        options['start_new_session'] = True
    return options


class Widget:
    def __init__(self, folder, command, spawn=subprocess.Popen, clock=time.monotonic,
                 available=float_panel.available):
        self.folder, self.command = Path(folder), list(command)
        self.spawn, self.clock, self.available = spawn, clock, available
        self.lock = threading.RLock()
        self.process = self.started = self.last_seen = None
        self.failures, self.error = 0, None
        self.enabled = self.load()

    @property
    def path(self):
        return self.folder / 'widget.json'

    def load(self):
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError):
            return False
        return isinstance(data, dict) and data.get('enabled') is True

    def save(self):
        self.folder.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(dir=self.folder, prefix='.widget-', suffix='.tmp')
        try:
            with os.fdopen(handle, 'w') as out:
                json.dump({'enabled': self.enabled}, out)
            os.replace(name, self.path)
        except BaseException:
            try:
                os.unlink(name)
            except OSError:
                pass
            raise

    def touch(self):
        """Called whenever a widget process polls the collector."""
        self.last_seen = self.clock()

    def running(self):
        return self.last_seen is not None and self.clock() - self.last_seen < GRACE_SECONDS

    def status(self):
        with self.lock:
            available = bool(self.available())
            running = self.running()
            starting = bool(self.enabled and available and not running and not self.error
                            and self.process is not None and self.process.poll() is None)
            return dict(enabled=self.enabled, available=available, reason=None if available else UNAVAILABLE,
                        running=running, starting=starting, error=self.error)

    def set_enabled(self, value):
        if not isinstance(value, bool):
            raise ValueError('enabled must be true or false')
        with self.lock:
            self.enabled = value
            self.save()
            self.failures, self.error = 0, None
            if value:
                self.ensure()
            return self.status()

    def ensure(self):
        """Start the widget when it is on and not running. Safe to call every few seconds."""
        with self.lock:
            if not self.enabled or self.error or not self.available():
                return
            if self.process is not None:
                code = self.process.poll()
                if code is None:
                    return
                early = self.clock() - self.started < EARLY_SECONDS
                self.process = None
                self.last_seen = None  # we saw it exit, so its last poll no longer means it is running
                if code not in (0, ALREADY_RUNNING) and early:
                    self.failures += 1
                    if self.failures >= MAX_FAILURES:
                        self.error = f'The widget keeps exiting at start (code {code}). See widget.log.'
                        return
                elif code in (0, ALREADY_RUNNING) or not early:
                    self.failures = 0
            if self.running():
                return
            self.folder.mkdir(parents=True, exist_ok=True)
            try:
                with (self.folder / 'widget.log').open('ab') as log:
                    self.process = self.spawn(self.command, **detach_options(log))
            except OSError as error:
                self.error = f'The widget could not be started: {error}'
                return
            self.started = self.clock()
