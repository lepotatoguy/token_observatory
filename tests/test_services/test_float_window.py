import os

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from backend.services import float_model  # noqa: E402
from backend.services import float_window  # noqa: E402


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def payload():
    return dict(at=1759620000.0, checked_at=1759619000.0, errors={}, providers=[
        dict(provider='claude', name='Claude Code', model='claude-opus-5-5',
             session=dict(used_percent=90.0, window_minutes=300), weekly=dict(used_percent=42.0, window_minutes=10080)),
        dict(provider='codex', name='Codex', model='gpt-6.1-sol',
             session=dict(used_percent=100.0, window_minutes=300), weekly=dict(used_percent=92.0, window_minutes=10080))])


def render(window):
    image = QImage(window.size(), QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    window.render(image)
    return image


def test_the_pill_is_frameless_and_stays_on_top(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    flags = window.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint
    assert flags & Qt.WindowType.WindowStaysOnTopHint


def test_the_pill_sizes_itself_for_the_accounts(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    window.apply(payload())
    assert window.width() > 200
    assert window.height() > 30
    assert len(window.rows) == 2


def test_the_pill_draws_each_account_accent(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    window.apply(payload())
    image = render(window)
    drawn = {image.pixelColor(x, y).getRgb()
             for x in range(image.width()) for y in range(image.height())}
    for key in ('claude', 'codex'):
        assert QColor(float_model.ACCENTS[key]).getRgb() in drawn


def test_the_pill_draws_a_used_bar_in_the_accent_colour(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    window.apply(payload())
    image = render(window)
    codex = QColor(float_model.ACCENTS['codex']).getRgb()
    filled = sum(1 for x in range(image.width()) for y in range(image.height())
                 if image.pixelColor(x, y).getRgb() == codex)
    # A full session bar and a nearly full weekly bar.
    assert filled > 50


def test_the_pill_shows_a_message_without_accounts(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    window.apply(dict(at=None, checked_at=None, providers=[], errors={}))
    assert window.rows == []
    assert window.message == 'Waiting for the collector…'
    assert window.width() > 100


def test_the_pill_reports_a_failed_check(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    window.apply(dict(errors={'claude': 'signed out'}))
    assert 'signed out' in window.message


def test_the_position_is_remembered(app, tmp_path):
    path = tmp_path / 'float.json'
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota', position_file=path)
    window.move(120, 80)
    window.save()
    other = float_window.FloatWindow('http://127.0.0.1:1/api/quota', position_file=path)
    assert other.pos().x() == 120
    assert other.pos().y() == 80


def test_a_broken_position_file_is_ignored(app, tmp_path):
    path = tmp_path / 'float.json'
    path.write_text('not json')
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota', position_file=path)
    assert window.restored is False


@pytest.mark.parametrize('platform', ['darwin', 'win32', 'linux'])
def test_run_keeps_widget_in_background_before_creating_application(monkeypatch, platform):
    monkeypatch.setattr(float_window.sys, 'platform', platform)
    monkeypatch.setenv('QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM', '')
    observed = []

    class ApplicationCreated(Exception):
        pass

    class Application:
        instance = staticmethod(lambda: None)

        def __init__(self, args):
            observed.append(os.environ.get('QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM'))
            raise ApplicationCreated

    monkeypatch.setattr(float_window, 'QApplication', Application)
    with pytest.raises(ApplicationCreated):
        float_window.run('http://127.0.0.1:1/api/quota')
    assert observed == ['1' if platform == 'darwin' else '']


def test_widget_stays_visible_without_becoming_a_foreground_app(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    try:
        assert window.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    finally:
        window.close()


def test_second_instance_cannot_take_the_lock(app, tmp_path):
    first = float_window.acquire_lock(tmp_path)
    assert first is not None
    assert float_window.acquire_lock(tmp_path) is None
    first.unlock()
    again = float_window.acquire_lock(tmp_path)
    assert again is not None
    again.unlock()


def test_polls_identify_the_widget_and_check_the_setting(app):
    window = float_window.FloatWindow('http://127.0.0.1:9/api/quota', managed=True)
    assert window.quota_url == 'http://127.0.0.1:9/api/quota?client=widget'
    assert window.setting_url == 'http://127.0.0.1:9/api/widget'


def test_unmanaged_widget_ignores_the_setting(app):
    window = float_window.FloatWindow('http://127.0.0.1:9/api/quota')
    window.follow({'enabled': False})
    assert window.isVisible() is False and window.misses == 0
    assert window.closing is False


def test_managed_widget_closes_when_the_setting_turns_off(app):
    window = float_window.FloatWindow('http://127.0.0.1:9/api/quota', managed=True)
    window.follow({'enabled': False})
    assert window.closing is True


def test_managed_widget_closes_after_three_unreachable_polls(app):
    window = float_window.FloatWindow('http://127.0.0.1:9/api/quota', managed=True)
    for _ in range(2):
        window.follow(None)
    assert window.closing is False
    window.follow(None)
    assert window.closing is True


def test_quit_from_the_menu_turns_the_setting_off_when_managed(app, monkeypatch):
    sent = []
    monkeypatch.setattr(float_window, 'post_setting', lambda url, enabled: sent.append((url, enabled)))
    managed = float_window.FloatWindow('http://127.0.0.1:9/api/quota', managed=True)
    managed.quit()
    assert sent == [('http://127.0.0.1:9/api/widget', False)]
    unmanaged = float_window.FloatWindow('http://127.0.0.1:9/api/quota')
    unmanaged.quit()
    assert len(sent) == 1


def test_the_model_name_is_not_shown(app):
    window = float_window.FloatWindow('http://127.0.0.1:1/api/quota')
    window.apply(payload())
    assert 'claude-opus-5-5' not in window.toolTip() and 'gpt-6.1-sol' not in window.toolTip()
    short = window.width()
    long_names = payload()
    for provider in long_names['providers']:
        provider['model'] = 'a-very-long-model-name-that-would-widen-the-pill-' * 3
    window.apply(long_names)
    assert window.width() == short
