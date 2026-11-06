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
