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
