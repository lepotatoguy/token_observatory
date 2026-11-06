"""Flask factory for the staged backend migration."""

from flask import Flask, abort, request, send_from_directory
from pathlib import Path
import logging
import sys
import threading

from backend.api.routes import blueprint as dashboard, apply_proxies
from backend.parsers import local_proxy
from backend.services import claude_context, forecast, pricing, providers, updater, update_install
from backend.services.store import Store

from backend.api.health import blueprint as health
from backend.config import Config
from backend.middleware.security import SecurityMiddleware


def create_app(config: Config | None = None) -> Flask:
    config = config if config is not None else Config()
    app = Flask(__name__, static_folder=None)
    app.config.from_object(config)
    app.config["MAX_CONTENT_LENGTH"] = 1024
    app.wsgi_app = SecurityMiddleware(app.wsgi_app, config.PORT)
    folder = Path(config.DATA_DIR).parent
    windows, warning = claude_context.load_windows(folder / 'config.json')
    app.extensions['store'] = Store(
        config.CODEX_HOME, config.CLAUDE_HOME, config.DATA_DIR, windows, warning,
        getattr(config, 'CLAUDE_PLAN_FILE', None) or folder / 'plan-usage-history.json',
        folder / 'claude-rate-limits.json', folder / 'live-limits.json',
        settings=providers.Settings(folder / 'providers.json'), local_log=folder / 'local-usage.jsonl',
        lmstudio_folder=getattr(config, 'LMSTUDIO_FOLDER', None) or folder / 'lmstudio/conversations', detect_providers=False)
    app.extensions['forecast'] = forecast.Forecaster(app.extensions['store'], folder)
    app.extensions['proxies'] = local_proxy.Proxies(local_proxy.Recorder(folder / 'local-usage.jsonl'))
    app.extensions['pricing'] = pricing.Pricing(folder / 'pricing.json', folder / 'config.json')
    root = Path(__file__).resolve().parents[1]
    app.extensions['updates'] = updater.Updates(
        folder, kind=update_install.kind(getattr(sys, 'frozen', False), sys.platform, root, folder),
        root=root, before_restart=lambda: app.extensions['store'].read(force_save=True),
        stop_server=lambda: app.extensions.get('shutdown', lambda: None)())
    app.extensions['runtime'] = Runtime(app, config)
    app.register_blueprint(dashboard, url_prefix='/api')
    app.register_blueprint(health, url_prefix="/api")

    @app.before_request
    def validate_mutation():
        if request.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            if request.content_length is not None and request.content_length > 1024:
                abort(413)
            if request.mimetype != "application/json":
                abort(415)
            # One extra byte distinguishes a full legal body from a truncated stream.
            request.max_content_length = 1025
            if len(request.get_data()) > 1024:
                abort(413)
            request.max_content_length = 1024

    @app.get('/')
    @app.get('/<path:asset>')
    def frontend(asset='index.html'):
        if asset == 'api' or asset.startswith('api/'):
            abort(404)
        folder = Path(getattr(config, 'FRONTEND_DIST', Path(__file__).resolve().parents[1] / 'frontend/dist'))
        if '..' in Path(asset).parts or Path(asset).is_absolute():
            abort(404)
        if (folder / asset).is_file():
            return send_from_directory(folder, asset)
        if Path(asset).suffix:
            abort(404)
        return send_from_directory(folder, 'index.html')

    return app


class Runtime:
    """Explicitly owned workers; creating a Flask test client starts none."""
    def __init__(self, app, config):
        self.app, self.config = app, config
        self.stop_event = threading.Event()
        self.threads = []

    def _loop(self, callback, interval):
        while not self.stop_event.is_set():
            try:
                callback()
            except Exception:
                logging.exception('Collector background task failed')
            if self.stop_event.wait(interval):
                break

    def start(self, restart_command=None, shutdown=None):
        if self.threads:
            return
        self.stop_event.clear()
        ext = self.app.extensions
        ext['shutdown'] = shutdown or (lambda: None)
        ext['updates'].restart_command = restart_command or []
        from backend.api.routes import provider_status
        provider_status(ext)
        apply_proxies(ext)
        jobs = [(ext['store'].read, 2),
                (lambda: ext['pricing'].update(cancelled=self.stop_event.is_set), 3600)]
        if self.config.LIVE_CHECKS:
            jobs.append((ext['store'].refresh_live, 300))
        if self.config.UPDATE_CHECKS:
            ext['updates'].finish()
            jobs.append((ext['updates'].check, 3600))
        for callback, interval in jobs:
            worker = threading.Thread(target=self._loop, args=(callback, interval), daemon=True)
            self.threads.append(worker)
            worker.start()

    def stop(self):
        self.stop_event.set()
        self.app.extensions['proxies'].stop()
        for worker in self.threads:
            worker.join(timeout=35)
        self.threads = [worker for worker in self.threads if worker.is_alive()]
        self.app.extensions['store'].read(force_save=True)
