import datetime as dt
import gzip
import json
from types import SimpleNamespace
import time

from backend.services import forecast
from backend.services.archive import Archive

NOW = dt.datetime(2026, 11, 5, 12, 0).timestamp()
EVENTS_PER_FILE = 40_000  # About 5 MB of JSON per daily file.


def daily_file(template, day):
    stamp = dt.datetime.combine(day, dt.time(12)).timestamp()
    text = template.replace('"@AT@"', repr(stamp)).replace('@ID@', day.isoformat())
    return gzip.compress(text.encode(), compresslevel=1)


def test_a_cold_fit_over_thirty_five_megabyte_days_is_quick_and_a_warm_request_is_instant(tmp_path):
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
    service = forecast.Forecaster(store, tmp_path)

    started = time.perf_counter()
    service.payload(now=NOW)
    cold = time.perf_counter() - started
    started = time.perf_counter()
    body = service.payload(now=NOW + 5)
    warm = time.perf_counter() - started

    assert body['providers']['claude']['days_used'] == 30
    assert cold < 3, f'cold fit took {cold:.2f}s'
    assert warm < 0.05, f'warm request took {warm:.3f}s'
