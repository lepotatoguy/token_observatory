import datetime as dt

from backend.services import forecast_history as fh

TODAY = dt.date(2026, 11, 6)


def at(day, hour=12):
    """Local timestamp, because the forecast groups usage by local calendar day."""
    return dt.datetime.combine(day, dt.time(hour)).timestamp()


def ev(day, tokens=10, hour=12):
    return dict(at=at(day, hour), input=tokens, cached=0, write=0, output=0, reasoning=0)


def session(sid, events, provider='claude', **extra):
    return dict(id=sid, provider=provider, events=events, **extra)


def snap(*sessions, limits=None):
    return dict(at=at(TODAY), sessions=list(sessions), limits=limits or {})


class FakeArchive:
    def __init__(self, files, broken=()):
        self.files, self.broken, self.loaded = files, set(broken), []

    def dates(self):
        return sorted(self.files, reverse=True)

    def load(self, day):
        self.loaded.append(day)
        if day in self.broken:
            raise ValueError('Truncated compressed snapshot')
        return self.files[day]


def collect(current, archive=None, plan=(), providers=('claude', 'codex', 'minimax')):
    return fh.collect(current, archive, list(plan), TODAY, set(providers))


def day(n):
    return TODAY - dt.timedelta(days=n)


def test_events_are_summed_by_local_day_without_reasoning():
    event = dict(at=at(day(1)), input=1, cached=2, write=3, output=4, reasoning=9)
    history = collect(snap(session('a', [event])))
    assert history.series['claude'] == [10]
    assert history.first_day['claude'] == day(1)


def test_a_session_in_several_files_is_counted_once_from_its_newest_copy():
    old = snap(session('a', [ev(day(2), 5)]))
    live = snap(session('a', [ev(day(2), 5), ev(day(1), 7)]))
    archive = FakeArchive({day(1).isoformat(): old})
    history = collect(live, archive)
    assert history.series['claude'] == [5, 7]


def test_a_session_kept_only_in_an_old_file_still_counts():
    archive = FakeArchive({day(3).isoformat(): snap(session('gone', [ev(day(3), 4)]))})
    history = collect(snap(session('a', [ev(day(1), 1)])), archive)
    assert history.series['claude'] == [4, 0, 1]


def test_events_without_a_time_are_skipped_and_counted():
    history = collect(snap(session('a', [dict(at=None, input=99, cached=0, write=0, output=0), ev(day(1), 1)])))
    assert history.skipped_events == 1
    assert history.series['claude'] == [1]


def test_today_is_left_out_of_the_series_but_kept_in_the_event_index():
    history = collect(snap(session('a', [ev(day(1), 2), ev(TODAY, 8)])))
    assert history.series['claude'] == [2]
    assert [tokens for _, tokens in history.events['claude']] == [2, 8]


def test_only_the_last_thirty_days_are_used():
    history = collect(snap(session('a', [ev(day(40), 100), ev(day(29), 1), ev(day(1), 1)])))
    assert len(history.series['claude']) == 29
    assert history.series['claude'][0] == 1
    assert sum(history.series['claude']) == 2


def test_quiet_days_are_zero_between_the_first_event_and_yesterday_and_never_before():
    history = collect(snap(session('a', [ev(day(5), 3), ev(day(2), 4)])))
    assert history.series['claude'] == [3, 0, 0, 4, 0]
    assert history.first_day['claude'] == day(5)


def test_a_provider_without_events_has_no_series():
    history = collect(snap(session('a', [ev(day(1), 1)])))
    assert 'codex' not in history.series


def test_untracked_providers_are_ignored():
    history = collect(snap(session('a', [ev(day(1), 1)], provider='ollama')))
    assert history.series == {}


def test_an_unreadable_snapshot_is_skipped_with_a_warning():
    files = {day(2).isoformat(): snap(session('x', [ev(day(2), 9)])), day(3).isoformat(): snap(session('y', [ev(day(3), 6)]))}
    archive = FakeArchive(files, broken=[day(2).isoformat()])
    history = collect(snap(session('a', [ev(day(1), 1)])), archive)
    assert history.series['claude'] == [6, 0, 1]
    assert len(history.warnings) == 1 and day(2).isoformat() in history.warnings[0]


def test_each_archive_file_is_loaded_at_most_once_and_old_files_are_not_read():
    files = {day(n).isoformat(): snap(session(f's{n}', [ev(day(n), 1)])) for n in (1, 2, 45)}
    archive = FakeArchive(files)
    collect(snap(), archive)
    assert sorted(archive.loaded) == sorted([day(1).isoformat(), day(2).isoformat()])


def test_a_missing_archive_still_uses_the_live_snapshot():
    assert collect(snap(session('a', [ev(day(1), 1)])), None).series['claude'] == [1]


def weekly(percent, resets_at=None):
    return dict(window_minutes=10080, used_percent=percent, resets_at=resets_at)


def test_weekly_percent_samples_come_from_sessions_limits_and_the_desktop_file():
    codex = session('c', [], provider='codex', rate_limits=dict(secondary=weekly(40, 5000)), rate_limits_at=1000.0)
    limits = dict(codex=dict(secondary=weekly(55, 5000), observed_at=2000.0),
                  claude=dict(primary=dict(window_minutes=300, used_percent=9), secondary=weekly(12, 7000), observed_at=3000.0))
    history = collect(snap(codex, limits=limits), plan=[(500.0, 4, 8), (600.0, 5, None)])
    assert history.samples['codex'] == [fh.Sample(1000.0, 40, 5000), fh.Sample(2000.0, 55, 5000)]
    assert history.samples['claude'] == [fh.Sample(500.0, 8, None), fh.Sample(3000.0, 12, 7000)]


def test_duplicate_samples_are_dropped():
    codex = session('c', [], provider='codex', rate_limits=dict(secondary=weekly(40, 5000)), rate_limits_at=1000.2)
    limits = dict(codex=dict(secondary=weekly(40, 5000), observed_at=1000.4))
    history = collect(snap(codex, limits=limits))
    assert len(history.samples['codex']) == 1


def test_malformed_limits_are_ignored():
    limits = dict(codex='bad', claude=dict(secondary='bad', observed_at=1.0), minimax=dict(secondary=weekly(None), observed_at=1.0))
    history = collect(snap(limits=limits))
    assert history.samples == {}


def test_typed_rows_split_each_event_into_four_types_and_sum_to_the_total():
    event = dict(at=at(day(1)), input=1, cached=2, write=3, output=4, reasoning=9)
    history = collect(snap(session('a', [event])))
    assert history.typed['claude'] == [(event['at'], 1, 2, 3, 4)]
    assert [tokens for _, tokens in history.events['claude']] == [sum(row[1:]) for row in history.typed['claude']]


def test_typed_rows_follow_the_same_dedup_and_skip_events_without_a_time():
    old = snap(session('a', [dict(ev(day(2), 5), cached=7)]))
    live = snap(session('a', [dict(ev(day(2), 5), cached=7), ev(day(1), 3)]),
                session('b', [dict(at=None, input=99, cached=0, write=0, output=0)]))
    history = collect(live, FakeArchive({day(1).isoformat(): old}))
    assert [row[1:] for row in history.typed['claude']] == [(5, 7, 0, 0), (3, 0, 0, 0)]
    assert history.skipped_events == 1


def test_a_provider_without_events_has_no_typed_rows():
    assert 'codex' not in collect(snap(session('a', [ev(day(1), 1)]))).typed


def test_a_clean_session_and_the_careful_path_give_the_same_rows():
    clean = [dict(ev(day(n), 5 * n), cached=n, write=2 * n, output=3 * n) for n in range(1, 6)]
    odd = dict(at=at(day(1)), input=True, cached=1.9, write=-4, output=None)  # Forces the per-event path.
    fast = collect(snap(session('a', clean)))
    slow = collect(snap(session('a', clean + [odd])))
    expected = [row for row in slow.typed['claude'] if row != (odd['at'], 1, 1, 0, 0)]
    assert fast.typed['claude'] == expected
    assert (odd['at'], 1, 1, 0, 0) in slow.typed['claude']  # bool -> 1, 1.9 -> 1, negative -> 0, None -> 0


def test_events_outside_the_window_or_not_finite_are_never_taken_by_the_bulk_path():
    old = ev(day(40), 7)
    nan = dict(ev(day(1), 3), at=float('nan'))
    history = collect(snap(session('a', [ev(day(1), 4), old, nan])))
    assert [row[1] for row in history.typed['claude']] == [4]
    assert history.skipped_events == 1
