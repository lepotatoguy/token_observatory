"""The floating usage widget: a small always-on-top pill on macOS, Windows and Linux.

Qt draws the same widget on every desktop, so one implementation covers all three
operating systems. This module needs PySide6, so the launcher only imports it
when the widget is started and the packaged app stays small without it.
"""
import json
import os
import sys
import threading
import urllib.request
import webbrowser
from pathlib import Path

from PySide6.QtCore import QLockFile, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication, QMenu, QWidget

from backend.services import float_model

POLL_SECONDS = 5
ALREADY_RUNNING = 75  # exit code when another widget holds the lock; the collector does not count it as a crash
PADDING_X = 12
PADDING_Y = 9
ACCENT_WIDTH = 3
ACCENT_HEIGHT = 15
ACCENT_GAP = 7
NAME_GAP = 14
METER_GAP = 12
METER_GAP_Y = 6
BAR_HEIGHT = 4
PROVIDER_GAP = 18
METER_SLOTS = 2
NAME_SIZE = 12
METER_SIZE = 10
RADIUS = 18


def alpha(hex_color, value):
    """A colour from the palette with an alpha channel."""
    color = QColor(hex_color)
    color.setAlpha(value)
    return color


class FloatWindow(QWidget):
    """A frameless pill that shows each account's name and its quota meters."""

    updated = Signal(object)
    checked = Signal(object)

    def __init__(self, url, position_file=None, managed=False):
        super().__init__()
        self.url = url
        # A managed widget was started by the collector, so the dashboard setting decides how long it lives.
        self.managed = managed
        base = url.rsplit('/api/', 1)[0]
        self.quota_url = f'{url}?client=widget' if managed else url
        self.setting_url = f'{base}/api/widget'
        self.misses = 0
        self.closing = False
        self.position_file = Path(position_file) if position_file else None
        self.payload = {}
        self.rows = []
        self.message = float_model.message({})
        self._drag = None
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                            | Qt.WindowType.Tool | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.font_name = self._font(NAME_SIZE, QFont.Weight.DemiBold)
        self.font_meter = self._font(METER_SIZE)
        self.font_meter_strong = self._font(METER_SIZE, QFont.Weight.DemiBold)
        self.font_message = self._font(METER_SIZE + 1)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(POLL_SECONDS * 1000)
        self.updated.connect(self.apply)
        self.checked.connect(self.follow)
        self.restored = self.restore()

    def _font(self, size, weight=None):
        font = QFont()
        font.setPixelSize(size)
        if weight is not None:
            font.setWeight(weight)
        return font

    # Data -----------------------------------------------------------------

    def poll(self):
        """Ask the collector for the current quota without blocking the interface."""
        threading.Thread(target=self._fetch, daemon=True).start()

    def _fetch(self):
        try:
            with urllib.request.urlopen(self.quota_url, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
        except Exception as error:
            data = {'error': str(error)}
        self.updated.emit(data)
        if self.managed:
            try:
                with urllib.request.urlopen(self.setting_url, timeout=5) as response:
                    setting = json.loads(response.read().decode('utf-8'))
            except Exception:
                setting = None
            self.checked.emit(setting)

    def follow(self, setting):
        """Quit when the dashboard turns the widget off or the collector is gone."""
        if not self.managed:
            return
        quit_now, self.misses = float_model.follow(setting, self.misses)
        if quit_now:
            self.shutdown()

    def shutdown(self):
        self.closing = True
        self.close()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def quit(self):
        """The menu's Quit: a managed widget also turns the dashboard setting off so it stays closed."""
        if self.managed:
            post_setting(self.setting_url, False)
        self.shutdown()

    def apply(self, payload):
        """Show a new quota reading."""
        self.payload = payload or {}
        self.rows = float_model.rows(self.payload)
        self.message = float_model.message(self.payload) or ''
        self.setToolTip(self._tooltip())
        self.resize(self.size())
        self.update()

    def _tooltip(self):
        """A hover summary: every account's quota and any error."""
        lines = []
        for row in self.rows:
            used = ', '.join(f"{meter['label']} {float_model.percent_text(meter['used_percent'])}"
                             for meter in row['meters'])
            lines.append(f"{row['name']}: {used}")
            if row.get('error'):
                lines.append(f"{row['name']}: {row['error']}")
        if not lines:
            lines.append(self.message or 'Token Observatory')
        return '\n'.join(lines)

    # Layout ---------------------------------------------------------------

    def _widths(self):
        name_metrics, meter_metrics = QFontMetrics(self.font_name), QFontMetrics(self.font_meter)
        name_width = meter_width = 0
        for row in self.rows:
            name_width = max(name_width, name_metrics.horizontalAdvance(row['name']))
            for meter in row['meters']:
                meter_width = max(meter_width, meter_metrics.horizontalAdvance(meter['label']) + 18
                                  + meter_metrics.horizontalAdvance('100%'))
        return name_width, meter_width

    def _columns(self):
        """Where each account's parts sit: its accent, its name and its meters."""
        name_width, meter_width = self._widths()
        x = PADDING_X
        columns = []
        for row in self.rows:
            name_x = x + ACCENT_WIDTH + ACCENT_GAP
            meters_x = name_x + name_width + NAME_GAP
            width = (meters_x - x) + meter_width * METER_SLOTS + METER_GAP * (METER_SLOTS - 1)
            columns.append(dict(x=x, name_x=name_x, meters_x=meters_x, width=width))
            x += width + PROVIDER_GAP
        return columns

    def _heights(self):
        """The height of the name block and of the meters."""
        name_metrics, meter_metrics = QFontMetrics(self.font_name), QFontMetrics(self.font_meter)
        name_height = name_metrics.height()
        meter_height = (meter_metrics.height() + BAR_HEIGHT) * METER_SLOTS + METER_GAP_Y * (METER_SLOTS - 1)
        return name_height, meter_height

    def size(self):
        """The pill's size for the current rows."""
        if not self.rows:
            message = QFontMetrics(self.font_message)
            return QSize(max(220, message.horizontalAdvance(self.message) + PADDING_X * 2), 36)
        columns = self._columns()
        name_height, meter_height = self._heights()
        width = PADDING_X + sum(column['width'] for column in columns) + PROVIDER_GAP * (len(columns) - 1) + PADDING_X
        height = max(name_height, meter_height) + PADDING_Y * 2
        return QSize(int(width), int(height))

    def sizeHint(self):
        return self.size()

    def minimumSizeHint(self):
        return self.sizeHint()

    # Painting -------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        frame = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        panel = QPainterPath()
        panel.addRoundedRect(frame, RADIUS, RADIUS)
        painter.fillPath(panel, alpha(float_model.BACKGROUND, 236))
        painter.setPen(QPen(alpha(float_model.BORDER, 190), 1))
        painter.drawPath(panel)
        if not self.rows:
            self._paint_message(painter)
            return
        name_metrics, meter_metrics = QFontMetrics(self.font_name), QFontMetrics(self.font_meter)
        name_height, meter_height = self._heights()
        content_height = max(name_height, meter_height)
        top = (self.height() - content_height) / 2
        name_width, meter_width = self._widths()
        for index, (row, column) in enumerate(zip(self.rows, self._columns())):
            if index:
                self._paint_divider(painter, column['x'] - PROVIDER_GAP / 2, top, content_height)
            accent = QColor(row['accent'])
            bar = QRectF(column['x'], top + (content_height - ACCENT_HEIGHT) / 2, ACCENT_WIDTH, ACCENT_HEIGHT)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(accent)
            painter.drawRoundedRect(bar, ACCENT_WIDTH / 2, ACCENT_WIDTH / 2)
            name_x = column['name_x']
            name_top = top + (content_height - name_metrics.height()) / 2
            self._paint_text(painter, self.font_name, QRectF(name_x, name_top, name_width, name_metrics.height()),
                             row['name'], float_model.TEXT)
            for slot, meter in enumerate(row['meters']):
                x = column['meters_x'] + slot * (meter_width + METER_GAP)
                self._paint_text(painter, self.font_meter, QRectF(x, top, meter_width, meter_metrics.height()),
                                 meter['label'], float_model.MUTED)
                self._paint_text(painter, self.font_meter_strong, QRectF(x, top, meter_width, meter_metrics.height()),
                                 float_model.percent_text(meter['used_percent']), float_model.TEXT,
                                 Qt.AlignmentFlag.AlignRight)
                bar_y = top + meter_metrics.height() + 3
                self._paint_bar(painter, QRectF(x, bar_y, meter_width, BAR_HEIGHT), meter['used_percent'], accent)

    def _paint_text(self, painter, font, rect, text, color, alignment=Qt.AlignmentFlag.AlignLeft):
        painter.setFont(font)
        painter.setPen(QPen(QColor(color)))
        painter.drawText(rect, int(alignment | Qt.AlignmentFlag.AlignVCenter), text)

    def _paint_bar(self, painter, rect, used, accent):
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(alpha(float_model.TRACK, 210))
        painter.drawRoundedRect(rect, BAR_HEIGHT / 2, BAR_HEIGHT / 2)
        if not isinstance(used, (int, float)):
            return
        filled = QRectF(rect)
        filled.setWidth(rect.width() * min(100.0, max(0.0, used)) / 100.0)
        if filled.width() <= 0:
            return
        painter.setBrush(accent)
        painter.drawRoundedRect(filled, BAR_HEIGHT / 2, BAR_HEIGHT / 2)

    def _paint_divider(self, painter, x, top, height):
        painter.setPen(QPen(alpha(float_model.BORDER, 120), 1))
        painter.drawLine(int(x), int(top + 2), int(x), int(top + height - 2))

    def _paint_message(self, painter):
        painter.setFont(self.font_message)
        painter.setPen(QPen(QColor(float_model.MUTED)))
        painter.drawText(QRectF(PADDING_X, 0, self.width() - PADDING_X * 2, self.height()),
                         int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), self.message)

    # Interaction ----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.save()

    def mouseDoubleClickEvent(self, event):
        self.open_dashboard()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction('Open dashboard', self.open_dashboard)
        menu.addAction('Refresh now', self.poll)
        menu.addAction('Quit', self.quit)
        menu.exec(event.globalPos())

    def open_dashboard(self):
        base = self.url.rsplit('/api/', 1)[0]
        webbrowser.open(base)

    # Position -------------------------------------------------------------

    def restore(self):
        """Put the pill back where it was left, when that place still exists."""
        if not self.position_file or not self.position_file.exists():
            return False
        try:
            saved = json.loads(self.position_file.read_text())
            x, y = int(saved['x']), int(saved['y'])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if not self._on_screen(x, y):
            return False
        self.move(x, y)
        return True

    def save(self):
        """Remember where the pill sits."""
        if not self.position_file:
            return
        point = self.frameGeometry().topLeft()
        try:
            self.position_file.parent.mkdir(parents=True, exist_ok=True)
            self.position_file.write_text(json.dumps({'x': point.x(), 'y': point.y()}))
        except OSError:
            pass

    def _on_screen(self, x, y):
        for screen in QApplication.screens():
            area = screen.availableGeometry()
            if area.contains(x + 40, y + 20):
                return True
        return False

    def closeEvent(self, event):
        self.save()
        super().closeEvent(event)


def post_setting(url, enabled):
    """Tell the collector whether the widget is wanted. Failures are ignored: the widget is closing anyway."""
    request = urllib.request.Request(url, data=json.dumps({'enabled': enabled}).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
    try:
        urllib.request.urlopen(request, timeout=3).close()
    except Exception:
        pass


def acquire_lock(folder):
    """Hold the single-instance lock, or return None when another widget already has it."""
    lock = QLockFile(str(Path(folder) / 'float.lock'))
    lock.setStaleLockTime(0)  # a lock from a dead process is still reclaimed; a live one is never stolen
    return lock if lock.tryLock(0) else None


def run(url, position_file=None):
    """Show the widget until it is closed. Returns an exit code."""
    lock = None
    if position_file:
        Path(position_file).parent.mkdir(parents=True, exist_ok=True)
        lock = acquire_lock(Path(position_file).parent)
        if lock is None:
            return ALREADY_RUNNING
    # Plain executables must stay out of the macOS Dock and app switcher.
    if sys.platform == 'darwin':
        os.environ['QT_MAC_DISABLE_FOREGROUND_APPLICATION_TRANSFORM'] = '1'
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName('Token Observatory')
    from backend.services.widget_control import MANAGED
    window = FloatWindow(url, position_file=position_file, managed=os.environ.get(MANAGED) == '1')
    if not window.restored:
        screen = app.primaryScreen()
        area = screen.availableGeometry() if screen else None
        if area is not None:
            window.move(area.right() - window.width() - 24, area.top() + 10)
    window.show()
    window.poll()
    code = app.exec()
    if lock is not None:
        lock.unlock()
    return code
