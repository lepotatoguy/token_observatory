from backend.services import claude_limits

NOW = 1_800_000_000


def test_zero_desktop_sample_without_resets_is_unreported():
    plan = dict(observed_at=NOW - 60, five_hour=0, seven_day=0)
    assert claude_limits.limits(plan, {}, NOW) is None


def test_nonzero_desktop_sample_is_kept():
    plan = dict(observed_at=NOW - 60, five_hour=12, seven_day=0)
    assert claude_limits.limits(plan, {}, NOW)['primary']['used_percent'] == 12


def test_day_old_live_and_statusline_answers_are_dropped():
    old = NOW - claude_limits.MAX_AGE - 1
    live = dict(primary=dict(used_percent=60), observed_at=old, source='live')
    capture = dict(captured_at=old, five_hour=dict(used_percentage=5), seven_day=dict(used_percentage=5))
    assert claude_limits.limits(None, {}, NOW, capture, live) is None


def plan_file(tmp_path, samples):
    import json
    path = tmp_path / 'plan-usage-history.json'
    path.write_text(json.dumps(dict(version=1, samples=samples)))
    return path


def test_plan_samples_are_sorted_in_seconds_and_hide_the_organization(tmp_path):
    path = plan_file(tmp_path, [
        dict(t=2000, org='secret', u=dict(fh=5, sd=9)),
        dict(t=1000, org='secret', u=dict(fh=1, sd=3)),
        dict(t='bad', u=dict(fh=1, sd=1)),
        dict(t=3000, u='bad'),
        'junk',
    ])
    rows = claude_limits.PlanUsage(path).samples()
    assert rows == [(1.0, 1, 3), (2.0, 5, 9)]
    assert 'secret' not in repr(rows)


def test_plan_samples_are_empty_for_missing_or_broken_files(tmp_path):
    assert claude_limits.PlanUsage(tmp_path / 'absent.json').samples() == []
    assert claude_limits.PlanUsage(None).samples() == []
    broken = tmp_path / 'broken.json'
    broken.write_text('{not json')
    assert claude_limits.PlanUsage(broken).samples() == []


def test_newest_plan_sample_still_reads_after_the_helper_change(tmp_path):
    path = plan_file(tmp_path, [dict(t=1000, u=dict(fh=1, sd=3)), dict(t=2000, u=dict(fh=7, sd=8))])
    assert claude_limits.PlanUsage(path).read() == dict(observed_at=2.0, five_hour=7, seven_day=8)
