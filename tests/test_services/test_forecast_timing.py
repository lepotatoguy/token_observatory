import datetime as dt
import gzip
import json
from types import SimpleNamespace
import time

from backend.services import forecast
from backend.services.archive import Archive

NOW = dt.datetime(2026, 11, 5, 12, 0).timestamp()
ATTEMPTS = 3
COLD_FIT_LIMIT = 2.5  # Cold fit time as a multiple of the time spent reading the archive.
EVENTS_PER_FILE = 40_000  # About 5 MB of JSON per daily file.


def daily_file(template, day):
    stamp = dt.datetime.combine(day, dt.time(12)).timestamp()
    text = template.replace('"@AT@"', repr(stamp)).replace('@ID@', day.isoformat())
    return gzip.compress(text.encode(), compresslevel=1)


def timed_loads(monkeypatch):
    """Total seconds spent in Archive.load (gunzip + JSON decode), the part no fit can avoid."""
    spent, original = [0.0], Archive.load

    def load(self, name):
        started = time.perf_counter()
        try:
            return original(self, name)
        finally:
            spent[0] += time.perf_counter() - started
    monkeypatch.setattr(Archive, 'load', load)
    return spent


def test_a_cold_fit_over_thirty_five_megabyte_days_is_quick_and_a_warm_request_is_instant(tmp_path, monkeypatch):
    event = dict(at='@AT@', input=1200, cached=3400, write=560, output=780, reasoning=90, model='claude-sonnet-4', thread_id='@ID@')
    template = json.dumps(dict(at=NOW, limits={}, sessions=[dict(id='claude:@ID@', provider='claude', events=[event] * EVENTS_PER_FILE)]))
    assert len(template) > 4_500_000 * 1
    history = tmp_path / 'history'
    history.mkdir()
    today = dt.date(2026, 11, 5)
    for n in range(1, 31):
        day = today - dt.timedelta(days=n)
        (history / f'{day.isoformat()}.json.gz').write_bytes(daily_file(template, day))
    week = dict(used_percent=30.0, window_minutes=10080, resets_at=NOW + 3 * 86400)
    snapshot = dict(at=NOW, providers=dict(enabled=['claude']), limits=dict(claude=dict(secondary=week, observed_at=NOW)), sessions=[])
    store = SimpleNamespace(read=lambda: snapshot, archive=Archive(history), plan_usage=SimpleNamespace(samples=lambda: []))
    loads = timed_loads(monkeypatch)
    results = []
    for attempt in range(ATTEMPTS):  # A fresh folder each time keeps every fit cold; one noisy runner pass is forgiven.
        folder = tmp_path / f'forecast{attempt}'
        folder.mkdir()
        service = forecast.Forecaster(store, folder)
        loads[0] = 0.0
        started = time.perf_counter()
        service.payload(now=NOW)
        cold = time.perf_counter() - started
        results.append((cold, loads[0]))
        if cold < COLD_FIT_LIMIT * loads[0]:
            break
    started = time.perf_counter()
    body = service.payload(now=NOW + 5)
    warm = time.perf_counter() - started

    assert body['providers']['claude']['days_used'] == 30
    # Reading the archive sets a floor that depends on the machine, so bound the fit relative to it.
    # Native runners measured 1.8x to 3.0x between runs; a fit that regresses to 3.5x or more fails every attempt.
    ratios = ', '.join(f'{c:.2f}s = {c / r:.1f}x of {r:.2f}s reading' for c, r in results)
    assert cold < COLD_FIT_LIMIT * loads[0], f'cold fit over {COLD_FIT_LIMIT}x the archive read time in {len(results)} attempts: {ratios}'
    assert warm < 0.05, f'warm request took {warm:.3f}s'
