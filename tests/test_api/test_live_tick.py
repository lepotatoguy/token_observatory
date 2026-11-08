from unittest.mock import Mock

from backend import app as collector


def tick_with(app, widget_running, age):
    ext = app.extensions
    ext['store'].refresh_live = Mock()
    ext['store'].live = dict(checked_at=1000.0)
    ext['widget'].running = Mock(return_value=widget_running)
    ext['runtime'].live_tick(now=1000.0 + age)
    return ext['store'].refresh_live


def test_widget_running_refreshes_live_limits_at_the_widget_interval(app):
    assert tick_with(app, True, collector.LIVE_WIDGET_SECONDS - 1).call_count == 0
    refresh = tick_with(app, True, collector.LIVE_WIDGET_SECONDS)
    assert refresh.call_count == 1
    assert refresh.call_args.kwargs == dict(min_age=collector.LIVE_WIDGET_SECONDS)


def test_no_widget_keeps_the_slow_live_refresh(app):
    assert tick_with(app, False, collector.LIVE_WIDGET_SECONDS + 1).call_count == 0
    assert tick_with(app, False, collector.LIVE_IDLE_SECONDS).call_count == 1


def test_live_job_wakes_often_enough_for_the_widget_interval(app):
    assert collector.LIVE_TICK_SECONDS < collector.LIVE_WIDGET_SECONDS
    app.extensions['runtime'].config.LIVE_CHECKS = True
    ticks = [cb for cb, interval in app.extensions['runtime'].jobs() if interval == collector.LIVE_TICK_SECONDS]
    assert len(ticks) == 1
