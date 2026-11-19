from __future__ import annotations

import datetime
import math
import time

from PySide6.QtCore import QEvent, QObject, QPointF, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import (QBrush, QColor, QDesktopServices, QEnterEvent, QFont, QFontDatabase, QIcon,
                           QImage, QInputDevice, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap)
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFrame, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QPlainTextEdit, QPushButton, QScrollArea, QStackedWidget,
    QStyle, QStyleOptionButton, QStylePainter, QSystemTrayIcon, QVBoxLayout, QWidget)

from . import __version__
from .core import (Engine, Storage, Updater, diagnostics,
                   latest_release, profile_description, profile_title, LOG)

# Surfaces, foregrounds and state colors shared by Qt styles and custom painting.
CANVAS = '#141415'
SURFACE = '#222223'
FIELD = '#303031'
EDGE = '#89898c'
SEPARATOR = '#38383a'
ACCENT = '#eeeeef'
ACCENT_HOVER = '#fdfdfd'
MUTED = '#b6b6ba'
TEXT = '#f4f4f5'
FOCUS = '#ffffff'
DISABLED = '#a2a2a7'
SUCCESS = '#e5e5e7'
WARNING = '#c2c2c7'
CONTROL_HEIGHT = 36
CONTROL_RADIUS = 8
PANEL_RADIUS = 14
PANEL_INSET = 20
PAGE_GAP = 12

STYLE = f'''
QWidget {{ font-size: 14px; color: {TEXT}; }}
QMainWindow, QWidget#outer, QFrame#sheet, QWidget#page {{ background: {CANVAS}; }}
QFrame#rail {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #2a2a2d, stop:0.29 {SURFACE}, stop:1 #202021); border-radius: {PANEL_RADIUS}px; }}
QFrame#panel {{ background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #262628, stop:1 {SURFACE}); border-radius: {PANEL_RADIUS}px; }}
QScrollArea, QScrollArea > QWidget > QWidget, QLabel {{ background: transparent; }}
QLabel#brand {{ font: italic 30px "Instrument Serif"; color: {TEXT}; }}
QLabel#title {{ font-size: 24px; font-weight: 600; }}
QLabel#display {{ font-size: 28px; font-weight: 600; }}
QLabel#sectionTitle, QLabel#statusTitle {{ font-size: 18px; font-weight: 600; }}
QLabel#small, QLabel#muted, QLabel#caps, QLabel#helpText {{ color: {MUTED}; font-size: 13px; }}
QPushButton, QComboBox {{ background: transparent; border: 0; padding: 0 14px; }}
QPushButton#primary {{ color: {ACCENT}; font-weight: 600; }}
QPushButton#nav {{ text-align: left; padding: 0 10px; color: #d3d3d6; }}
QPushButton#nav:checked {{ color: {ACCENT_HOVER}; font-weight: 600; }}
QPushButton:disabled, QPushButton#primary:disabled {{ color: {DISABLED}; }}
QPlainTextEdit {{ background: transparent; border: 0; selection-background-color: #525257; placeholder-text-color: {MUTED}; }}
QComboBox {{ padding-right: 36px; }}
QComboBox::drop-down {{ subcontrol-origin: border; subcontrol-position: top right; width: 34px; background: transparent; border: 0; }}
QComboBox::down-arrow {{ image: none; width: 0px; height: 0px; }}
QComboBox QAbstractItemView {{ background: #29292b; color: {TEXT}; border: 1px solid {EDGE}; border-radius: {CONTROL_RADIUS}px; padding: 5px; outline: 0; }}
QComboBox QAbstractItemView::item {{ padding: 3px 9px; min-height: 17px; border-radius: 4px; border-left: 2px solid transparent; }}
QComboBox QAbstractItemView::item:hover {{ background: #3a3a3d; }}
QComboBox QAbstractItemView::item:selected {{ background: #444447; color: #ffffff; border-left-color: {ACCENT}; }}
QToolTip {{ background: #2d2d30; color: {TEXT}; border: 1px solid #545457; padding: 5px; }}
QScrollBar:vertical {{ width: 8px; background: transparent; }}
QScrollBar::handle:vertical {{ background: #58585b; min-height: 24px; border-radius: 3px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}
'''


def label(text='', name=None, wrap=False):
    item = QLabel(text)
    if name:
        item.setObjectName(name)
    if name in ('title', 'display'):
        font = item.font()
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, -0.35)
        item.setFont(font)
    item.setWordWrap(wrap)
    item.setTextFormat(Qt.TextFormat.PlainText)
    return item


def pixel_bounds(painter, rect):
    transform = painter.deviceTransform()
    pixels = transform.mapRect(rect)
    # Keep the complete outline inside the widget's clip, even at fractional DPI.
    left, top = math.ceil(pixels.left() - 1e-6), math.ceil(pixels.top() - 1e-6)
    right, bottom = math.floor(pixels.right() + 1e-6), math.floor(pixels.bottom() + 1e-6)
    inverse, _ = transform.inverted()
    return inverse.mapRect(QRectF(left, top, right - left, bottom - top))


def paint_control(painter, rect, radius, fill, edge=None):
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    rect = pixel_bounds(painter, rect)
    if edge:
        outline = QPainterPath()
        outline.addRoundedRect(rect, radius, radius)
        stroke = 1 / painter.deviceTransform().m11()
        rect.adjust(stroke, stroke, -stroke, -stroke)
        radius = max(0, radius - stroke)
        outline.addRoundedRect(rect, radius, radius)
        outline.setFillRule(Qt.FillRule.OddEvenFill)
        painter.fillPath(outline, QColor(edge))
    painter.setBrush(QColor(fill) if isinstance(fill, str) else QBrush(fill))
    painter.drawRoundedRect(rect, radius, radius)


class DampedValue(QObject):
    """A critically damped step response, retaining velocity when retargeted."""
    def __init__(self, widget, initial=0.0):
        super().__init__(widget)
        self.level = self.target = initial
        self.velocity = 0.0
        self.rate = 36
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.advance)

    def move_to(self, target, rate=36, *, animated=True):
        if not animated or not QApplication.isEffectEnabled(Qt.UIEffect.UI_General):
            self.timer.stop()
            self.level = self.target = target
            self.velocity = 0.0
            self.parent().update()
            return
        if target == self.target:
            return
        if self.timer.isActive():
            self.advance()
        self.target, self.rate = target, rate
        self.last_tick = time.monotonic()
        self.timer.start()

    def advance(self):
        now = time.monotonic()
        dt, self.last_tick = now - self.last_tick, now
        delta = self.level - self.target
        slope = self.velocity + self.rate * delta
        decay = math.exp(-self.rate * dt)
        self.level = self.target + (delta + slope * dt) * decay
        self.velocity = (self.velocity - self.rate * slope * dt) * decay
        if abs(self.level - self.target) < 0.003 and abs(self.velocity) < 0.15:
            self.level, self.velocity = self.target, 0.0
            self.timer.stop()
        self.parent().update()


class HoverLight(DampedValue):
    def __init__(self, widget):
        super().__init__(widget)
        widget.installEventFilter(self)

    def eventFilter(self, widget, event):
        if event.type() == QEvent.Type.Enter and isinstance(event, QEnterEvent):
            if event.device().type() == QInputDevice.DeviceType.Mouse and widget.isEnabled():
                self.move_to(1.0)
        elif event.type() == QEvent.Type.Leave:
            self.move_to(0.0, 30)
        elif event.type() in (QEvent.Type.Hide, QEvent.Type.EnabledChange):
            self.move_to(0.0, animated=False)
        return False

def glass_fill(rect, base, light, pressure=0.0):
    gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    color = QColor(base).lighter(round(100 + 9 * light)).darker(round(100 + 14 * pressure))
    gradient.setColorAt(0, color.lighter(105))
    gradient.setColorAt(1, color.darker(103))
    return gradient


class Divider(QWidget):
    def __init__(self):
        super().__init__()
        self.setFixedHeight(1)

    def paintEvent(self, event):
        painter = QPainter(self)
        # One physical pixel keeps consecutive separators equally bright.
        rect = QRectF(self.rect())
        rect.setHeight(1 / painter.deviceTransform().m11())
        painter.fillRect(rect, QColor(SEPARATOR))


def button(text, action, name=None):
    item = ControlButton(text)
    item.setCursor(Qt.CursorShape.PointingHandCursor)
    if name:
        item.setObjectName(name)
    item.clicked.connect(action)
    return item


class WorkerSignals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Worker(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.signals = WorkerSignals()

    def run(self):
        try:
            self.signals.done.emit(self.fn())
        except Exception as exc:
            LOG.exception('Операция не выполнена')
            self.signals.failed.emit(str(exc))


class ControlButton(QPushButton):
    def __init__(self, text):
        super().__init__(text)
        self.setMinimumHeight(CONTROL_HEIGHT)
        self.light = HoverLight(self)
        self.pressure = DampedValue(self)
        self.show_focus = False
        self.pressed.connect(self.press_surface)
        self.released.connect(lambda: self.pressure.move_to(0.0, 33))

    def press_surface(self):
        if QApplication.mouseButtons() & Qt.MouseButton.LeftButton:
            self.pressure.move_to(1.0, 58)

    def focusInEvent(self, event):
        self.show_focus = event.reason() != Qt.FocusReason.MouseFocusReason
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        self.show_focus = False
        super().mousePressEvent(event)

    def keyPressEvent(self, event):
        self.show_focus = True
        super().keyPressEvent(event)
        self.update()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.pressure.move_to(0.0, animated=False)

    def paintEvent(self, event):
        painter = QStylePainter(self)
        variant = self.objectName()
        edge = None
        if variant == 'nav':
            opacity = round(11 * self.light.level * (1 - 0.55 * self.pressure.level))
            fill = '#323234' if self.isChecked() else QColor(255, 255, 255, opacity)
        elif not self.isEnabled():
            fill, edge = '#262628', '#3a3a3d'
        elif variant == 'primary':
            fill, edge = '#49494d', '#a0a0a4'
        else:
            fill = FIELD
            edge = EDGE
        if self.hasFocus() and self.show_focus:
            edge = FOCUS
        rect = QRectF(self.rect())
        if self.isEnabled() and (variant != 'nav' or self.isChecked()):
            fill = glass_fill(rect, fill, self.light.level, self.pressure.level)
        paint_control(painter, rect, CONTROL_RADIUS, fill, edge)
        if variant == 'nav' and self.isChecked():
            paint_control(painter, QRectF(4, 10, 2, self.height() - 20), 1, ACCENT)

        option = QStyleOptionButton()
        self.initStyleOption(option)
        if variant == 'nav':
            option.rect.adjust(10, 0, -10, 0)
        painter.drawControl(QStyle.ControlElement.CE_PushButtonLabel, option)


class ProfileComboBox(QComboBox):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(CONTROL_HEIGHT)
        self.setMaxVisibleItems(8)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.light = HoverLight(self)

    def paintEvent(self, event):
        painter = QPainter(self)
        enabled = self.isEnabled()
        rect = QRectF(self.rect())
        fill = glass_fill(rect, FIELD, self.light.level) if enabled else '#262628'
        edge = FOCUS if self.hasFocus() or self.view().isVisible() else EDGE if enabled else '#3a3a3d'
        paint_control(painter, rect, CONTROL_RADIUS, fill, edge)
        text_area = self.rect().adjusted(14, 0, -36, 0)
        painter.setPen(QColor(TEXT if enabled else DISABLED))
        name = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, text_area.width())
        painter.drawText(text_area, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)

        color = QColor(TEXT if enabled else DISABLED)
        painter.setPen(QPen(color, 1.5, Qt.PenStyle.SolidLine,
                            Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        x, y = self.width() - 18, self.height() / 2
        chevron = QPainterPath(QPointF(x - 4, y - 2))
        chevron.lineTo(x, y + 2)
        chevron.lineTo(x + 4, y - 2)
        painter.drawPath(chevron)


class TextField(QFrame):
    def __init__(self, editor):
        super().__init__()
        self.editor = editor
        editor.installEventFilter(self)
        box = QVBoxLayout(self)
        box.setContentsMargins(9, 8, 9, 8)
        box.addWidget(editor)

    def eventFilter(self, watched, event):
        if event.type() in (QEvent.Type.FocusIn, QEvent.Type.FocusOut):
            self.update()
        return super().eventFilter(watched, event)

    def paintEvent(self, event):
        painter = QPainter(self)
        edge = FOCUS if self.editor.hasFocus() else EDGE
        paint_control(painter, QRectF(self.rect()), CONTROL_RADIUS, SURFACE, edge)


class ToggleSwitch(QCheckBox):
    """Use native checkbox interaction with a single painted switch track."""
    def __init__(self, title='', checked=False):
        super().__init__()
        self.setChecked(checked)
        self.setAccessibleName(title)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(48, 32)
        self.motion = DampedValue(self, float(checked))
        self.pointer_activation = False
        self.toggled.connect(self.animate_thumb)

    def animate_thumb(self, checked):
        self.motion.move_to(float(checked), 35, animated=self.pointer_activation)

    def mouseReleaseEvent(self, event):
        self.pointer_activation = (event.pointingDevice().type() == QInputDevice.DeviceType.Mouse
                                   and event.source() == Qt.MouseEventSource.MouseEventNotSynthesized)
        try:
            super().mouseReleaseEvent(event)
        finally:
            self.pointer_activation = False

    def hitButton(self, pos):
        """Treat the whole painted track as the control's click target."""
        return self.rect().contains(pos)

    def paintEvent(self, event):
        enabled = self.isEnabled()
        position = self.motion.level
        tone = round(49 + (48 if enabled else 18) * position)
        edge = FOCUS if self.hasFocus() else EDGE if enabled else '#525256'

        # Sample the small curves at 4x physical resolution. Keep the thumb's
        # fractional position throughout its travel, including on fractional DPI.
        dpr = self.devicePixelRatioF()
        pixels = QSize(math.ceil(self.width() * dpr), math.ceil(self.height() * dpr))
        layer = QImage(pixels * 4, QImage.Format.Format_ARGB32_Premultiplied)
        layer.fill(Qt.GlobalColor.transparent)
        with QPainter(layer) as shape:
            shape.scale(4 * dpr, 4 * dpr)
            shape.setRenderHint(QPainter.RenderHint.Antialiasing)
            shape.setPen(Qt.PenStyle.NoPen)
            track = QRectF(3, 5, 42, 22)
            shape.setBrush(QColor(edge))
            shape.drawRoundedRect(track, 11, 11)
            stroke = 1 / dpr
            shape.setBrush(QColor(tone, tone, tone + 3))
            shape.drawRoundedRect(track.adjusted(stroke, stroke, -stroke, -stroke),
                                  11 - stroke, 11 - stroke)
            shape.setBrush(QColor(ACCENT if enabled else '#929297'))
            shape.drawEllipse(QRectF(6 + 20 * position, 8, 16, 16))
        frame = layer.scaled(pixels, Qt.AspectRatioMode.IgnoreAspectRatio,
                             Qt.TransformationMode.SmoothTransformation)
        frame.setDevicePixelRatio(dpr)
        with QPainter(self) as painter:
            painter.drawImage(QPointF(0, 0), frame)


class HealthTile(QFrame):
    def __init__(self, name):
        super().__init__()
        self.setFixedHeight(40)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(label(name))
        row.addStretch()
        self.value = label('', 'small')
        row.addWidget(self.value)
        self.reset()

    def reset(self):
        self.value.setText('—')
        self.value.setStyleSheet('')
        self.setToolTip('Ожидает проверки')

    def result(self, data):
        self.value.setText('Доступен' if data['ok'] else 'Доступ не подтверждён')
        self.value.setStyleSheet('color: ' + (SUCCESS if data['ok'] else WARNING))
        self.setToolTip(data['detail'])


class Window(QMainWindow):
    def __init__(self, storage: Storage, *, testing=False):
        super().__init__()
        self.s = storage
        self.engine = Engine(storage)
        self.updater = Updater(storage)
        self.testing = testing
        self.busy = False
        self.settings_edited = False
        self.pending_action = None
        self.connection_target = False
        self.diagnostic_context = None
        self.worker = None
        self.complete = None
        self.release = None
        self.was_running = False
        self.quitting = False
        self.tray_notified = False
        self.pool = QThreadPool(self)
        self.setWindowTitle('byerkn')
        app_icon = QIcon(str(storage.root / 'assets/icon.ico'))
        self.setWindowIcon(app_icon)
        self.resize(872, 556)
        self.setMinimumSize(780, 550)
        self.setStyleSheet(STYLE)
        outer = QWidget()
        outer.setObjectName('outer')
        self.setCentralWidget(outer)
        out = QHBoxLayout(outer)
        out.setContentsMargins(16, 16, PANEL_INSET, 16)
        out.setSpacing(20)
        rail = QFrame()
        rail.setObjectName('rail')
        rail.setFixedWidth(184)
        out.addWidget(rail)
        side = QVBoxLayout(rail)
        side.setContentsMargins(12, PANEL_INSET, 12, 16)
        side.setSpacing(4)
        brand = label('byerkn', 'brand')
        brand.setContentsMargins(10, 3, 6, 3)
        side.addWidget(brand)
        brand.ensurePolished()
        brand.setFixedHeight(max(40, brand.sizeHint().height()))
        side.addSpacing(16)
        self.nav = []
        for i, name in enumerate(('Подключение', 'Настройки', 'Обновления', 'Журнал', 'Справка')):
            if i == 4:
                side.addStretch()
            b = button(name, lambda checked=False, index=i: self.navigate(index), 'nav')
            glyph = ('\ue839', '\ue713', '\ue895', '\ue8a5', '\ue897')[i]
            pix = QPixmap(36, 36)
            pix.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pix)
            font = QFont('Segoe MDL2 Assets')
            font.setPixelSize(28)
            painter.setFont(font)
            painter.setPen(QColor('#c5c5c8'))
            painter.drawText(pix.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
            painter.end()
            b.setIcon(QIcon(pix))
            b.setIconSize(QSize(18, 18))
            b.setCheckable(True)
            self.nav.append(b)
            side.addWidget(b)
        self.footer_version = label('', 'small')
        side.addWidget(self.footer_version)
        self.sheet = QFrame()
        self.sheet.setObjectName('sheet')
        out.addWidget(self.sheet, 1)
        lay = QVBoxLayout(self.sheet)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(16)
        self.page_title = label('', 'title')
        lay.addWidget(self.page_title)
        self.notice = label('', wrap=True)
        self.notice.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.notice.hide()
        lay.addWidget(self.notice)
        self.pages = QStackedWidget()
        lay.addWidget(self.pages, 1)
        self.build_home()
        self.build_settings()
        self.build_updates()
        self.build_log()
        self.build_help()
        for toggle in self.checkboxes.values():
            toggle.toggled.connect(self.refresh_save_action)
        self.domain_edit.textChanged.connect(self.refresh_save_action)
        self.exclude_edit.textChanged.connect(self.refresh_save_action)
        self.tray = QSystemTrayIcon(app_icon, self)
        # The tray menu uses the platform style, independently of the window.
        self.tray_menu = menu = QMenu()
        menu.addAction('Открыть byerkn', self.reveal)
        self.tray_toggle = menu.addAction('Включить обход', self.toggle_engine)
        menu.addSeparator()
        menu.addAction('Выключить и выйти', self.quit_app)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        if not testing:
            self.tray.show()
        self.refresh_profiles()
        self.refresh_versions()
        self.navigate(0)
        self.tick()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.periodic_update)
        self.update_timer.start(6 * 60 * 60 * 1000)
        if not testing:
            QTimer.singleShot(800, self.startup)

    def page(self):
        page = QWidget()
        page.setObjectName('page')
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(PAGE_GAP)
        self.pages.addWidget(page)
        return page, layout

    def scroll_content(self, page):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        page.addWidget(scroll, 1)
        content = QWidget()
        content.setObjectName('page')
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 0, 2)
        layout.setSpacing(PAGE_GAP)
        scroll.verticalScrollBar().rangeChanged.connect(
            lambda minimum, maximum: layout.setContentsMargins(0, 0, 8 if maximum > minimum else 0, 2))
        scroll.setWidget(content)
        return layout

    def build_home(self):
        _, page = self.page()
        lay = self.scroll_content(page)

        panel = QFrame()
        panel.setObjectName('panel')
        box = QVBoxLayout(panel)
        box.setContentsMargins(PANEL_INSET, 16, PANEL_INSET, 16)
        box.setSpacing(12)
        top = QHBoxLayout()
        self.state_title = label('', 'display')
        top.addWidget(self.state_title, 1)
        self.power = button('Включить', self.toggle_engine, 'primary')
        self.power.setMinimumWidth(120)
        top.addWidget(self.power)
        box.addLayout(top)
        box.addWidget(Divider())
        row = QHBoxLayout()
        row.addWidget(label('Профиль', 'muted'))
        row.addStretch()
        self.profile = ProfileComboBox()
        self.profile.setAccessibleName('Профиль подключения')
        self.profile.currentIndexChanged.connect(self.profile_changed)
        row.addWidget(self.profile)
        box.addLayout(row)
        lay.addWidget(panel)

        services = QFrame()
        services.setObjectName('panel')
        rows = QVBoxLayout(services)
        rows.setContentsMargins(PANEL_INSET, 16, PANEL_INSET, 8)
        rows.setSpacing(0)
        checks = QHBoxLayout()
        checks.addWidget(label('Доступность сайтов', 'sectionTitle'), 1)
        self.check_btn = button('Проверить', self.run_diagnostics)
        self.check_btn.setMinimumWidth(120)
        checks.addWidget(self.check_btn)
        rows.addLayout(checks)
        self.last_check = label('', 'small', True)
        rows.addWidget(self.last_check)
        rows.addSpacing(8)
        self.health = {}
        for name in ('YouTube', 'Discord', 'Google', 'GitHub'):
            rows.addWidget(Divider())
            tile = HealthTile(name)
            rows.addWidget(tile)
            self.health[name] = tile
        lay.addWidget(services)
        self.help_action = button('Что попробовать дальше?', lambda: self.navigate(4))
        lay.addWidget(self.help_action, 0, Qt.AlignmentFlag.AlignLeft)
        lay.addStretch()
        self.reset_checks()

    def build_help(self):
        _, page = self.page()
        lay = self.scroll_content(page)
        answers = (
            ('С чего начать?', 'Выберите «Основной» и нажмите «Включить». Проверка сайтов начнётся автоматически.'),
            ('Сайт или видео не открывается', 'Выключите обход и проверьте соединение. Если интернет работает, попробуйте другой профиль.'),
            ('Как закрыть программу?', 'Крестик по умолчанию сворачивает окно в трей. Для выхода выберите «Выключить и выйти» в меню значка.'),
            ('Как вернуть предыдущую версию?', 'Выключите обход и нажмите «Откатить» в разделе «Обновления». Кнопка доступна после первого обновления.'))
        card = QFrame()
        card.setObjectName('panel')
        card.setMaximumWidth(608)
        body = QVBoxLayout(card)
        body.setContentsMargins(PANEL_INSET, 16, PANEL_INSET, 16)
        body.setSpacing(8)
        column = QHBoxLayout()
        column.addWidget(card, 1)
        column.addStretch()
        lay.addLayout(column)
        for index, (question, answer) in enumerate(answers):
            if index:
                body.addWidget(Divider())
            body.addWidget(label(question, 'sectionTitle'))
            paragraph = label(answer, 'helpText', True)
            paragraph.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
            body.addWidget(paragraph)
            paragraph.ensurePolished()
            # Allow two or more lines even when Qt estimates the card at its wider size.
            paragraph.setMinimumHeight(paragraph.heightForWidth(476))
        lay.addStretch()

    def build_settings(self):
        _, lay = self.page()
        form = self.scroll_content(lay)
        self.checkboxes = {}
        items = [
            ('game_filter', 'Игровой режим', 'Расширяет обработку TCP и UDP на порты 1024–65535. Включайте, если нужны игры или другие приложения. Может влиять на их соединение.'),
            ('ip_filter', 'Список IP-адресов', 'Обрабатывает также адреса из списка zapret. Выключите, если с обходом перестал открываться ресурс, который работал без него.'),
            ('start_engine', 'Включать обход при открытии byerkn', 'После запуска приложения автоматически включает выбранный профиль. Само приложение не добавляется в автозагрузку Windows.'),
            ('close_to_tray', 'Оставлять в трее при закрытии', 'Крестик скрывает окно, обход продолжает работать. Чтобы остановить его и выйти, используйте меню значка в трее.'),
            ('auto_check', 'Проверять обновления автоматически', 'Проверка официальных релизов GitHub при запуске и каждые 6 часов. Настройки и ваши домены сохраняются.'),
            ('auto_install', 'Автоматически устанавливать новые файлы', 'Установка только при выключенном обходе. Активное соединение не прерывается. Предыдущая версия остаётся для отката.')]
        for key, title, detail in (items[2:] + items[:2]):
            if key in ('start_engine', 'auto_check', 'game_filter'):
                section = QFrame()
                section.setObjectName('panel')
                group = QVBoxLayout(section)
                group.setContentsMargins(PANEL_INSET, 12, PANEL_INSET, 6)
                group.setSpacing(4)
                group.addWidget(label({'start_engine': 'Приложение', 'auto_check': 'Обновления', 'game_filter': 'Сеть'}[key], 'sectionTitle'))
                form.addWidget(section)
            else:
                group.addWidget(Divider())
            row = QHBoxLayout()
            name = label(title, wrap=True)
            name.setToolTip(detail)
            row.addWidget(name, 1)
            cb = ToggleSwitch(title, self.s.settings[key])
            cb.setToolTip(detail)
            self.checkboxes[key] = cb
            row.addWidget(cb)
            group.addLayout(row)
        domains = QWidget()
        columns = QHBoxLayout(domains)
        columns.setContentsMargins(0, 8, 0, 0)
        columns.setSpacing(12)
        domains.hide()
        self.domain_disclosure = disclosure = ControlButton('Настроить списки сайтов')
        disclosure.setCheckable(True)
        disclosure.toggled.connect(domains.setVisible)
        disclosure.toggled.connect(lambda opened: disclosure.setText('Свернуть списки сайтов' if opened else 'Настроить списки сайтов'))
        form.addWidget(disclosure, 0, Qt.AlignmentFlag.AlignLeft)
        self.domain_edit = QPlainTextEdit(self.s.settings['domains'])
        self.exclude_edit = QPlainTextEdit(self.s.settings['exclusions'])
        for title, edit, placeholder in [('Применять к сайтам', self.domain_edit, 'example.org'), ('Исключения', self.exclude_edit, 'example.com')]:
            col = QVBoxLayout()
            col.setSpacing(6)
            col.setAlignment(Qt.AlignmentFlag.AlignTop)
            col.addWidget(label(title, 'caps'))
            edit.setPlaceholderText(placeholder)
            edit.setAccessibleName(title)
            field = TextField(edit)
            field.setFixedHeight(120)
            col.addWidget(field)
            columns.addLayout(col)
        form.addWidget(domains)
        form.addStretch(1)
        bar = QHBoxLayout()
        self.save_hint = label('Для изменения настроек выключите обход.', 'small', True)
        bar.addWidget(self.save_hint, 1)
        self.save_btn = button('Сохранить', self.save_settings, 'primary')
        bar.addWidget(self.save_btn, 0, Qt.AlignmentFlag.AlignRight)
        lay.addLayout(bar)

    def build_updates(self):
        _, lay = self.page()
        panel = QFrame()
        panel.setObjectName('panel')
        body = QVBoxLayout(panel)
        body.setContentsMargins(PANEL_INSET, 16, PANEL_INSET, 16)
        body.setSpacing(PAGE_GAP)
        body.addWidget(label('Версия zapret', 'sectionTitle'))
        versions = QHBoxLayout()
        self.installed_label = label('', 'statusTitle')
        self.remote_label = label('Ещё не проверяли', 'statusTitle')
        for title, value in (('Установлена', self.installed_label), ('Последний релиз', self.remote_label)):
            column = QVBoxLayout()
            column.setSpacing(4)
            column.addWidget(label(title, 'small'))
            column.addWidget(value)
            versions.addLayout(column, 1)
        body.addLayout(versions)
        body.addWidget(Divider())
        actions = QHBoxLayout()
        self.update_check = button('Проверить обновления', self.check_updates)
        self.install_btn = button('Установить', self.install_update, 'primary')
        self.rollback_btn = button('Откатить', self.rollback)
        actions.addWidget(self.update_check)
        actions.addStretch()
        actions.addWidget(self.install_btn)
        actions.addWidget(self.rollback_btn)
        body.addLayout(actions)
        self.update_info = label('', 'small', True)
        body.addWidget(self.update_info)
        lay.addWidget(panel)
        self.release_heading = label('Изменения в релизе', 'caps')
        lay.addWidget(self.release_heading)
        self.release_notes = QPlainTextEdit()
        self.release_notes.setReadOnly(True)
        self.release_notes.setAccessibleName('Описание релиза')
        self.release_field = TextField(self.release_notes)
        lay.addWidget(self.release_field, 1)
        lay.addStretch()

    def build_log(self):
        _, lay = self.page()
        controls = QHBoxLayout()
        controls.addWidget(button('Обновить', self.refresh_log))
        controls.addWidget(button('Открыть папку', lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.s.data)))))
        controls.addStretch()
        lay.addLayout(controls)
        self.log_edit = QPlainTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setPlaceholderText('Здесь появятся события запуска, проверок и обновлений.')
        self.log_edit.setAccessibleName('Журнал byerkn и zapret')
        self.log_edit.setStyleSheet('font-family: Consolas; font-size: 12px;')
        lay.addWidget(TextField(self.log_edit), 1)

    def navigate(self, index):
        self.page_title.setText(self.nav[index].text())
        self.pages.setCurrentIndex(index)
        for i, btn in enumerate(self.nav):
            btn.setChecked(i == index)
        if index == 3:
            self.refresh_log()

    def say(self, message, error=False):
        short = message.split('\n')[0]
        self.notice.setText(short[:320] + ('… Подробности в журнале.' if len(short) > 320 else ''))
        self.notice.setVisible(bool(message))
        self.notice.setStyleSheet('background: #353538; color: #f4f4f5; padding: 9px 12px; border-radius: 7px;' if error else 'background: #29292b; color: #dedee1; padding: 9px 12px; border-radius: 7px;')
        self.notice.setToolTip(message)

    def run_task(self, fn, done, *, action):
        if self.busy:
            return
        self.busy = True
        self.pending_action = action
        self.complete = done
        self.say('')
        self.worker = Worker(fn)
        self.worker.signals.done.connect(self.task_done)
        self.worker.signals.failed.connect(self.task_failed)
        self.tick()
        self.pool.start(self.worker)

    def task_done(self, value):
        callback = self.complete
        self.complete = None
        self.busy = False
        self.pending_action = None
        self.worker = None
        self.say('')
        if callback:
            callback(value)
        self.tick()

    def task_failed(self, message):
        was_checking = self.pending_action is self.check_btn
        self.busy = False
        self.pending_action = None
        self.complete = None
        self.worker = None
        self.say(message, error=True)
        if was_checking:
            self.reset_checks()
        self.tick()

    def tick(self):
        running = self.engine.running
        if self.was_running and not running and not self.busy:
            self.say('zapret неожиданно завершился. Откройте журнал, чтобы посмотреть причину.', error=True)
            LOG.warning('Процесс zapret неожиданно завершился')
        self.was_running = running
        if self.pending_action is self.power:
            self.state_title.setText('Включаем обход…' if self.connection_target else 'Выключаем обход…')
        else:
            self.state_title.setText('Обход включён' if running else 'Обход выключен')
        self.power.setText('Выключить' if running else 'Включить')
        self.power.setEnabled(not self.busy)
        self.profile.setEnabled(not running and not self.busy)
        self.profile.setToolTip('Выключите обход, чтобы сменить профиль.' if running
                                else profile_description(self.profile.currentData() or 'general.bat'))
        self.check_btn.setEnabled(not self.busy)
        self.update_check.setEnabled(not self.busy)
        available = bool(self.release and self.release['version'] != self.s.version)
        self.install_btn.setEnabled(available and not running and not self.busy)
        self.rollback_btn.setEnabled(self.s.previous.exists() and not running and not self.busy)
        self.refresh_release_state(running)
        self.save_btn.setEnabled(self.settings_edited and not running and not self.busy)
        self.save_btn.setText('Сохраняем…' if self.pending_action is self.save_btn else 'Сохранить')
        for cb in self.checkboxes.values():
            cb.setEnabled(not running and not self.busy)
        self.domain_edit.setReadOnly(running or self.busy)
        self.exclude_edit.setReadOnly(running or self.busy)
        self.save_hint.setVisible(running)
        status = ''
        if running:
            elapsed = int(time.monotonic() - (self.engine.started_at or time.monotonic()))
            status = f'Работает  {elapsed // 3600:02}:{elapsed // 60 % 60:02}:{elapsed % 60:02}'
        elif self.busy:
            status = 'Выполняется операция…'
        self.tray.setToolTip(f'byerkn · {status}' if status else 'byerkn')
        self.tray_toggle.setText('Выключить обход' if running else 'Включить обход')
        self.tray_toggle.setEnabled(not self.busy)

    def refresh_save_action(self):
        self.settings_edited = (any(cb.isChecked() != self.s.settings[key] for key, cb in self.checkboxes.items())
                   or self.domain_edit.toPlainText() != self.s.settings['domains']
                   or self.exclude_edit.toPlainText() != self.s.settings['exclusions'])
        self.save_btn.setEnabled(self.settings_edited and not self.engine.running and not self.busy)

    def refresh_profiles(self):
        self.profile.blockSignals(True)
        self.profile.clear()
        for p in self.s.profiles():
            self.profile.addItem(profile_title(p.name), p.name)
        index = self.profile.findData(self.s.settings['profile'])
        if index < 0 and self.profile.count():
            self.s.save({'profile': self.profile.itemData(0)})
            index = 0
            self.say('Сохранённый профиль не найден. Выбран основной; проверьте соединение после запуска.', True)
        self.profile.setCurrentIndex(index)
        self.profile.blockSignals(False)
        self.profile.setToolTip(profile_description(self.profile.currentData() or 'general.bat'))

    def profile_changed(self):
        name = self.profile.currentData()
        if name:
            try:
                self.s.save({'profile': name})
                self.profile.setToolTip(profile_description(name))
                self.reset_checks()
                LOG.info('Выбран профиль %s', name)
            except Exception as exc:
                self.profile.blockSignals(True)
                try:
                    self.profile.setCurrentIndex(self.profile.findData(self.s.settings['profile']))
                finally:
                    self.profile.blockSignals(False)
                self.say(str(exc), True)

    def reset_checks(self):
        for tile in self.health.values():
            tile.reset()
        self.help_action.hide()
        self.last_check.setText('Ещё не проверяли')

    def toggle_engine(self):
        if self.busy:
            self.reveal()
            return
        running = self.engine.running
        self.connection_target = not running
        self.was_running = False
        self.reset_checks()
        self.run_task(self.engine.stop if running else self.engine.start, self.engine_changed, action=self.power)

    def engine_changed(self, _):
        self.was_running = self.engine.running
        if self.engine.running:
            self.run_diagnostics()
        elif self.s.settings['auto_install'] and self.release and self.release['version'] != self.s.version:
            QTimer.singleShot(100, self.install_update)

    def run_diagnostics(self):
        if self.busy:
            return
        self.diagnostic_context = (self.engine.running, self.engine.started_at)
        self.reset_checks()
        self.last_check.setText('Проверяем доступность…')
        self.run_task(diagnostics, self.diagnostics_done, action=self.check_btn)

    def diagnostics_done(self, results):
        if self.diagnostic_context != (self.engine.running, self.engine.started_at):
            self.reset_checks()
            self.say('Во время проверки состояние обхода изменилось. Проверьте соединение ещё раз.', True)
            return
        for data in results:
            self.health[data['name']].result(data)
            LOG.info('Проверка %s: %s', data['name'], data['detail'])
        self.last_check.setText('Проверено в ' + datetime.datetime.now().strftime('%H:%M') + (' · с обходом' if self.engine.running else ' · без обхода'))
        if any(not d['ok'] for d in results):
            self.help_action.show()
        else:
            self.help_action.hide()

    def save_settings(self):
        if self.busy or self.engine.running:
            return
        changes = {key: cb.isChecked() for key, cb in self.checkboxes.items()}
        changes['domains'] = self.domain_edit.toPlainText()
        changes['exclusions'] = self.exclude_edit.toPlainText()
        if len(changes['domains']) + len(changes['exclusions']) > 64 * 1024:
            self.run_task(lambda: self.s.save(changes), self.settings_saved, action=self.save_btn)
            return
        try:
            self.s.save(changes)
        except Exception as exc:
            self.say(str(exc), True)
            return
        self.settings_saved()

    def settings_saved(self, _=None):
        for editor, key in ((self.domain_edit, 'domains'), (self.exclude_edit, 'exclusions')):
            if editor.toPlainText() != self.s.settings[key]:
                editor.setPlainText(self.s.settings[key])
        LOG.info('Настройки сохранены')
        self.refresh_save_action()
        self.say('Настройки сохранены. Они применятся при следующем включении.')
        self.reset_checks()

    def refresh_versions(self):
        self.footer_version.setText(f'   Версия {__version__}')
        self.installed_label.setText(self.s.version)

    def refresh_release_state(self, running):
        message = ''
        if self.pending_action is self.update_check:
            message = 'Проверяем релизы на GitHub…'
        elif self.pending_action is self.install_btn:
            message = 'Скачиваем и проверяем архив…'
        elif self.pending_action is self.rollback_btn:
            message = 'Возвращаем предыдущую версию…'
        elif self.release:
            if self.release['version'] == self.s.version:
                message = 'Установлена актуальная версия.'
            elif running:
                message = 'Выключите обход, чтобы установить обновление.'
            else:
                message = 'Доступно обновление.'
        self.update_info.setText(message)
        self.update_info.setVisible(bool(message))
        has_notes = bool(self.release and self.release['notes'].strip())
        self.release_heading.setVisible(has_notes)
        self.release_field.setVisible(has_notes)

    def check_updates(self):
        self.run_task(latest_release, self.update_checked, action=self.update_check)

    def update_checked(self, release):
        self.release = release
        self.remote_label.setText(release['version'])
        self.release_notes.setPlainText(release['notes'])
        if release['version'] != self.s.version and self.s.settings['auto_install'] and not self.engine.running:
            QTimer.singleShot(100, self.install_update)

    def install_update(self):
        if self.engine.running or self.busy or not self.release or self.release['version'] == self.s.version:
            return
        self.run_task(lambda: self.updater.install(self.release), self.updated, action=self.install_btn)

    def updated(self, version):
        self.refresh_profiles()
        self.refresh_versions()
        self.say(f'Готово. Установлен zapret {version}; ваши настройки сохранены.')
        self.reset_checks()

    def rollback(self):
        if not self.engine.running:
            self.run_task(self.updater.rollback, self.updated, action=self.rollback_btn)

    def periodic_update(self):
        if self.s.settings['auto_check'] and not self.busy:
            self.check_updates()

    def startup(self):
        if self.s.settings['start_engine']:
            self.toggle_engine()
            QTimer.singleShot(15000, self.periodic_update)
        else:
            self.periodic_update()

    def refresh_log(self):
        sections = []
        for name in ('byerkn.log', 'engine.log'):
            path = self.s.data / name
            try:
                with path.open('rb') as f:
                    f.seek(0, 2)
                    f.seek(max(0, f.tell() - 50000))
                    text = f.read(50000).decode('utf-8', errors='replace')
            except FileNotFoundError:
                continue
            except OSError as exc:
                text = f'Не удалось прочитать журнал: {exc}'
            sections.append(name + '\n\n' + (text or 'Пока нет записей.'))
        self.log_edit.setPlainText('\n\n'.join(sections))
        self.log_edit.verticalScrollBar().setValue(self.log_edit.verticalScrollBar().maximum())

    def open_upstream(self):
        QDesktopServices.openUrl(QUrl('https://github.com/Flowseal/zapret-discord-youtube'))

    def tray_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            self.reveal()

    def reveal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, event):
        if self.quitting:
            event.accept()
            return
        if self.s.settings['close_to_tray'] and QSystemTrayIcon.isSystemTrayAvailable() and not self.testing:
            self.hide()
            event.ignore()
            if not self.tray_notified:
                self.tray.showMessage('byerkn остаётся в трее', 'Открыть окно или полностью выйти можно через значок byerkn.', QSystemTrayIcon.MessageIcon.Information, 3500)
                self.tray_notified = True
        else:
            event.ignore()
            self.quit_app()

    def quit_app(self):
        if self.busy:
            self.reveal()
            self.say('Дождитесь завершения текущей операции, затем выйдите через меню в трее.')
            return
        self.quitting = True
        self.timer.stop()
        self.update_timer.stop()
        self.engine.stop()
        self.tray.hide()
        self.close()
        QApplication.instance().quit()


def load_font(root):
    QFontDatabase.addApplicationFont(str(root / 'assets/fonts/InstrumentSerif-Italic.ttf'))
    font_id = QFontDatabase.addApplicationFont(str(root / 'assets/fonts/GolosText-VF.ttf'))
    families = QFontDatabase.applicationFontFamilies(font_id)
    app = QApplication.instance()
    font = QFont(families[0] if families else 'Segoe UI', 10)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    app.setFont(font)
