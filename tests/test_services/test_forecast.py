import datetime as dt
import json
import os
from types import SimpleNamespace

import pytest

from backend.services import forecast, forecast_history

NOW = dt.datetime(2026, 11, 5, 12, 0).timestamp()  # A Thursday at noon, local time.
DAY = 86400


def noon(days_ago):
    return (dt.datetime(2026, 11, 5, 12, 0) - dt.timedelta(days=days_ago)).timestamp()


def midnight(days_ago):
    return (dt.datetime(2026, 11, 5) - dt.timedelta(days=days_ago)).timestamp()


def make_snapshot(percent=30.0):
    events = [dict(at=noon(n), input=1000, cached=0, write=0, output=0) for n in range(1, 21)]
    week = dict(used_percent=percent, window_minutes=10080, resets_at=NOW + 3 * DAY)
    return dict(at=NOW, providers=dict(enabled=['claude']), limits=dict(claude=dict(secondary=week, observed_at=NOW)),
                sessions=[dict(id='s', provider='claude', events=events)])


# Two more percent points every midnight, with 1000 tokens logged each day: 500 tokens per percent.
# The live 30% agrees: six more logged days since the last reading add 12 points.
PLAN = [(midnight(n), 0, 10 + 2 * (10 - n)) for n in range(10, 5, -1)]


class FakeArchive:
    def __init__(self):
        self.loaded = []

    def dates(self):
        return []

    def load(self, day):
        self.loaded.append(day)
        raise FileNotFoundError(day)


class FakeStore:
    def __init__(self, snapshot=None):
        self.snapshot, self.archive = snapshot or make_snapshot(), FakeArchive()
        self.plan_usage = SimpleNamespace(samples=lambda: list(PLAN))

    def read(self):
        return self.snapshot


@pytest.fixture
def fits(monkeypatch):
    calls = []
    real = forecast_history.collect

    def counting(*args, **kwargs):
        calls.append(args[4:])
        return real(*args, **kwargs)

    monkeypatch.setattr(forecast_history, 'collect', counting)
    return calls


def test_the_first_request_of_a_day_fits_and_saves_the_model(tmp_path, fits):
    body = forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)
    saved = json.loads((tmp_path / 'forecast.json').read_text())
    assert len(fits) == 1
    assert (saved['schema_version'], saved['date']) == (1, '2026-11-05')
    claude = saved['providers']['claude']
    assert claude['tokens_per_percent'] == 500 and claude['days_used'] == 20 and claude['demand']['method'] == 'flat'
    assert body['providers']['claude']['calibration'] == 'history'
    assert body['providers']['claude']['daily'] == round(500 * 70 / 3.5)


def test_a_fresh_model_answers_without_reading_the_archive_again(tmp_path, fits):
    store = FakeStore()
    service = forecast.Forecaster(store, tmp_path)
    service.payload(now=NOW)
    loaded = len(store.archive.loaded)
    service.payload(now=NOW + 600)
    assert len(fits) == 1 and len(store.archive.loaded) == loaded


def test_a_restart_on_the_same_day_reuses_the_saved_model(tmp_path, fits):
    forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)
    forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW + 60)
    assert len(fits) == 1


def test_the_budget_follows_the_live_limit_without_a_refit(tmp_path, fits):
    store = FakeStore()
    service = forecast.Forecaster(store, tmp_path)
    before = service.payload(now=NOW)['providers']['claude']['daily']
    store.snapshot = make_snapshot(percent=60.0)
    after = service.payload(now=NOW + 60)['providers']['claude']['daily']
    assert len(fits) == 1 and after < before


def test_a_new_day_fits_once_and_missed_days_are_not_filled_in(tmp_path, fits):
    service = forecast.Forecaster(FakeStore(), tmp_path)
    service.payload(now=NOW)
    service.payload(now=NOW + 2 * DAY)
    service.payload(now=NOW + 2 * DAY + 100)
    assert len(fits) == 2
    assert json.loads((tmp_path / 'forecast.json').read_text())['date'] == '2026-11-07'


def test_a_refresh_refits_but_not_more_than_once_a_minute(tmp_path, fits):
    service = forecast.Forecaster(FakeStore(), tmp_path)
    service.payload(now=NOW)
    service.payload(refresh=True, now=NOW + 10)
    assert len(fits) == 1
    service.payload(refresh=True, now=NOW + 61)
    assert len(fits) == 2


@pytest.mark.parametrize('content', ['{not json', '[]', json.dumps(dict(schema_version=0, date='2026-11-05', providers={}, warnings=[])),
                                     json.dumps(dict(schema_version=1, date='2026-11-04', providers={}, warnings=[]))])
def test_a_corrupt_old_or_stale_file_is_refitted(tmp_path, fits, content):
    (tmp_path / 'forecast.json').write_text(content)
    forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)
    assert len(fits) == 1
    assert json.loads((tmp_path / 'forecast.json').read_text())['schema_version'] == 1


def test_the_file_is_replaced_atomically_and_no_temporary_file_is_left(tmp_path, monkeypatch):
    seen = []
    real = os.replace

    def replace(source, target):
        seen.append((os.path.dirname(source), str(target)))
        real(source, target)

    monkeypatch.setattr(os, 'replace', replace)
    forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)
    assert seen == [(str(tmp_path), str(tmp_path / 'forecast.json'))]
    assert [p.name for p in tmp_path.iterdir()] == ['forecast.json']


def test_a_failed_replace_leaves_no_partial_file_and_still_answers(tmp_path, monkeypatch):
    def boom(source, target):
        raise OSError(28, 'No space left on device')

    monkeypatch.setattr(os, 'replace', boom)
    body = forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)
    assert list(tmp_path.iterdir()) == []
    assert body['providers']['claude']['daily'] > 0
    assert any('cannot be saved' in w for w in body['warnings'])


def test_an_unwritable_folder_still_returns_the_budget_with_a_warning(tmp_path):
    blocker = tmp_path / 'file'
    blocker.write_text('x')
    body = forecast.Forecaster(FakeStore(), blocker / 'inside').payload(now=NOW)
    assert body['providers']['claude']['daily'] > 0
    assert any('cannot be saved' in w for w in body['warnings'])


def test_the_saved_model_holds_only_aggregates(tmp_path):
    forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)
    text = (tmp_path / 'forecast.json').read_text()
    assert str(tmp_path) not in text and '"sessions"' not in text and '"events"' not in text
    assert set(json.loads(text)) == {'schema_version', 'date', 'generated_at', 'skipped_events', 'warnings', 'providers'}


def test_no_network_is_used(tmp_path, monkeypatch):
    import socket

    def refuse(*args, **kwargs):
        raise AssertionError('network used')

    monkeypatch.setattr(socket, 'socket', refuse)
    monkeypatch.setattr(socket, 'create_connection', refuse)
    assert forecast.Forecaster(FakeStore(), tmp_path).payload(now=NOW)['providers']['claude']['daily'] > 0


def test_without_a_folder_nothing_is_saved_and_the_model_stays_in_memory(fits):
    service = forecast.Forecaster(FakeStore(), None)
    service.payload(now=NOW)
    service.payload(now=NOW + 5)
    assert len(fits) == 1
