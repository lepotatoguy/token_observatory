"""Fits the budget model once per local day and applies it to the live limits on each request."""
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import threading
import time

from backend.services import forecast_budget, forecast_calibrate, forecast_demand, forecast_history

SCHEMA = 1
REFIT_SECONDS = 60
FILE = 'forecast.json'


def valid(state, today):
    return (isinstance(state, dict) and state.get('schema_version') == SCHEMA and state.get('date') == today
            and isinstance(state.get('providers'), dict) and isinstance(state.get('warnings'), list))


class Forecaster:
    def __init__(self, store, folder):
        self.store = store
        self.path = Path(folder) / FILE if folder is not None else None
        self.lock = threading.Lock()
        self.state = None

    def load(self, today):
        try:
            state = json.loads(self.path.read_text(encoding='utf-8')) if self.path else None
        except (OSError, ValueError):
            return None
        return state if valid(state, today) else None

    def save(self, state):
        """Write atomically; a failure is reported as a warning and never raised."""
        if self.path is None:
            return
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            descriptor, temporary = tempfile.mkstemp(prefix='.forecast-', suffix='.tmp', dir=self.path.parent)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump(state, stream, separators=(',', ':'), allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except (OSError, ValueError) as error:
            state['warnings'].append(f'Forecast cannot be saved: {getattr(error, "strerror", None) or error}')
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink(missing_ok=True)
                except OSError:
                    pass

    def fit(self, snapshot, now):
        today = dt.datetime.fromtimestamp(now).date()
        enabled = [p for p in forecast_budget.PROVIDERS if p in ((snapshot.get('providers') or {}).get('enabled') or [])]
        history = forecast_history.collect(snapshot, self.store.archive, self.store.plan_usage.samples(), today, set(enabled))
        providers = {}
        for provider in enabled:
            demand = forecast_demand.fit_demand(history.series.get(provider, []), today - dt.timedelta(days=1))
            calibration = forecast_calibrate.tokens_per_percent(history.samples.get(provider, []), history.events.get(provider, []))
            test = demand.backtest
            providers[provider] = dict(
                days_used=demand.days_used, confidence=demand.confidence,
                tokens_per_percent=calibration.value if calibration else None,
                calibration_pairs=calibration.pairs if calibration else 0,
                demand=dict(method=demand.method, weekday_weights=list(demand.weekday_weights), shrinkage=demand.shrinkage,
                            backtest=dict(model_mae=test.model_mae, baseline_mae=test.baseline_mae, days=test.days) if test else None))
        state = dict(schema_version=SCHEMA, date=today.isoformat(), generated_at=now, skipped_events=history.skipped_events,
                     warnings=list(history.warnings), providers=providers)
        self.save(state)
        return state

    def payload(self, refresh=False, now=None):
        now = time.time() if now is None else now
        today = dt.datetime.fromtimestamp(now).date().isoformat()
        with self.lock:
            snapshot = self.store.read()
            if not valid(self.state, today):
                self.state = self.load(today)
            stale = self.state is not None and refresh and now - self.state['generated_at'] >= REFIT_SECONDS
            if self.state is None or stale:
                self.state = self.fit(snapshot, now)
            return forecast_budget.budget(self.state, snapshot, now)
