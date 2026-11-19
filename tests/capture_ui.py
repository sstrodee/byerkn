"""Render real Qt screens using isolated data; never starts WinDivert or makes network requests."""
import os
os.environ['QT_QPA_PLATFORM'] = 'windows:fontengine=freetype'
from pathlib import Path
import tempfile
from unittest.mock import patch
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea
from PySide6.QtCore import QEvent, QPoint, QPointF, QSize, Qt
from PySide6.QtGui import QColor, QEnterEvent, QFontInfo, QImage, QKeyEvent, QMouseEvent, QPainter
from byerkn.core import Storage
from byerkn.ui import EDGE, FOCUS, Window, load_font

SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('BYERKN_TEST_ROOT') or SOURCE).resolve()
if os.environ.get('BYERKN_TEST_ROOT'):
    import byerkn.ui
    assert Path(byerkn.ui.__file__).resolve().is_relative_to(ROOT)
app = QApplication([])
load_font(ROOT)
out = SOURCE / '.impeccable/review' / os.environ.get('BYERKN_CAPTURE_SET', '')
out.mkdir(parents=True, exist_ok=True)


def assert_outline(control, color):
    rendered = control.grab().toImage()
    width, height = rendered.width(), rendered.height()
    horizontal = [rendered.pixelColor(x, height // 2).name() for x in range(width)]
    vertical = [rendered.pixelColor(width // 2, y).name() for y in range(height)]
    for row in (horizontal, vertical):
        midpoint = len(row) // 2
        assert row[:midpoint].count(color) == row[midpoint:].count(color) == 1, (
            control, color, control.devicePixelRatioF())


with tempfile.TemporaryDirectory(prefix='byerkn-ui-', dir=ROOT) as tmp:
    s = Storage(ROOT, Path(tmp) / 'data')
    w = Window(s, testing=True)
    w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    w.show()
    app.processEvents()
    wordmark = w.findChild(QLabel, 'brand')
    brand = QFontInfo(wordmark.font())
    assert brand.family() == 'Instrument Serif' and brand.italic()
    ink = wordmark.grab().toImage()
    rows = [y for y in range(ink.height()) if any(ink.pixelColor(x, y).red() > 170
            for x in range(ink.width()))]
    assert rows and min(rows) >= 2 and ink.height() - max(rows) >= 3
    wordmark.grab().save(str(out / 'wordmark.png'))
    sizes = w.windowIcon().availableSizes()
    assert all(QSize(side, side) in sizes for side in (16, 20, 24, 32, 48, 256))
    preview = QImage(184, 54, QImage.Format.Format_RGB32)
    preview.fill(QColor('#242426'))
    painter = QPainter(preview)
    for x, side in ((12, 16), (42, 20), (76, 24), (112, 32), (144, 36)):
        painter.drawPixmap(x, (54 - side) // 2, w.windowIcon().pixmap(QSize(side, side), 1.0))
    painter.end()
    preview.save(str(out / 'icon-sizes.png'))
    effects = Qt.UIEffect.UI_General
    had_effects = app.isEffectEnabled(effects)
    glow = w.power.light
    try:
        app.setEffectEnabled(effects, True)
        point = QPointF(5, 5)
        QApplication.sendEvent(w.power, QEnterEvent(point, point, point))
        with patch('byerkn.ui.time.monotonic', return_value=glow.last_tick + 0.045) as clock:
            glow.advance()
            mid, velocity = glow.level, glow.velocity
            assert 0 < mid < 1 and velocity > 0
            QApplication.sendEvent(w.power, QEvent(QEvent.Type.Leave))
            assert glow.level == mid and glow.velocity == velocity
            clock.return_value += 0.4
            glow.advance()
        assert glow.level == 0
        app.setEffectEnabled(effects, False)
        QApplication.sendEvent(w.power, QEnterEvent(point, point, point))
        assert glow.level == 1
        w.grab().save(str(out / 'hover.png'))
        QApplication.sendEvent(w.power, QEvent(QEvent.Type.Leave))
        assert glow.level == 0
    finally:
        app.setEffectEnabled(effects, had_effects)
    QApplication.setActiveWindow(w)
    nav = w.nav[1]
    nav.setFocus(Qt.FocusReason.TabFocusReason)
    def mouse_event(kind, buttons):
        pos = QPointF(nav.rect().center())
        return QMouseEvent(kind, pos, QPointF(nav.mapToGlobal(pos.toPoint())), Qt.MouseButton.LeftButton,
                           buttons, Qt.KeyboardModifier.NoModifier)

    for pressed in (False, True):
        if pressed:
            QApplication.sendEvent(nav, mouse_event(QEvent.Type.MouseButtonPress, Qt.MouseButton.LeftButton))
        frame = nav.grab().toImage()
        assert frame.pixelColor(frame.width() - 12, frame.height() // 2).red() < 100
    QApplication.sendEvent(nav, mouse_event(QEvent.Type.MouseButtonRelease, Qt.MouseButton.NoButton))
    assert w.pages.currentIndex() == 1
    menu = w.tray.contextMenu()
    assert menu.parentWidget() is None and menu.actions()[1] is w.tray_toggle
    menu.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    menu.popup(QPoint(10, 10))
    menu.setActiveAction(menu.actions()[-1])
    app.processEvents()
    menu.grab().save(str(out / 'tray-menu.png'))
    QApplication.sendEvent(menu, QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier))
    assert not menu.isVisible()
    # The custom switch must be clickable across its entire painted track.
    probe = w.checkboxes['game_filter']
    for x in (1, probe.width() // 2, probe.width() - 2):
        assert probe.hitButton(QPoint(x, probe.height() // 2)), f'toggle hit target missed x={x}'
    # A subpixel step must move the thumb without shrinking its diameter.
    dpr = probe.devicePixelRatioF()
    centers = []
    initial = probe.motion.level
    for position in (0.302, 0.316):
        probe.motion.level = position
        frame = probe.grab().toImage()
        tone = round(49 + 48 * position)
        weights = [max(0, frame.pixelColor(x, frame.height() // 2).red() - tone) / (238 - tone)
                   for x in range(round(8 * dpr), round(36 * dpr))]
        assert abs(sum(weights) - 16 * dpr) < 0.25
        centers.append(sum(i * a for i, a in enumerate(weights)) / sum(weights))
    assert abs(centers[1] - centers[0] - 0.28 * dpr) < 0.12
    probe.motion.level = initial
    probe.update()
    for index, name in enumerate(('home', 'settings', 'updates', 'log', 'help')):
        w.navigate(index)
        app.processEvents()
        w.grab().save(str(out / f'{name}.png'))
    for paragraph in w.pages.currentWidget().findChildren(QLabel, 'helpText'):
        assert paragraph.height() >= paragraph.heightForWidth(paragraph.width())
    w.resize(w.minimumSize())
    w.navigate(0)
    app.processEvents()
    assert_outline(w.profile, EDGE)
    assert_outline(w.check_btn, EDGE)
    w.grab().save(str(out / 'compact.png'))
    with patch.object(w.pool, 'start'):
        w.run_diagnostics()
        app.processEvents()
        assert not w.check_btn.isEnabled() and not w.notice.isVisible()
        assert w.last_check.text() == 'Проверяем доступность…'
        w.grab().save(str(out / 'checking.png'))
        w.task_done([{'name': name, 'ok': name != 'Discord', 'detail': 'Тест HTTPS'} for name in w.health])
    assert w.health['Discord'].value.text() == 'Доступ не подтверждён'
    assert w.help_action.isVisible()
    w.help_action.click()
    assert w.pages.currentIndex() == 4
    w.navigate(0)
    assert 'без обхода' in w.last_check.text()
    w.grab().save(str(out / 'diagnostics.png'))
    w.reset_checks()
    w.say('')
    with patch.object(w.pool, 'start'):
        w.toggle_engine()
        app.processEvents()
        assert w.state_title.text() == 'Включаем обход…'
        w.grab().save(str(out / 'starting.png'))
        w.task_failed('Тестовая ошибка запуска.')
        w.say('')
        w.navigate(2)
        assert not w.release_field.isVisible()
        w.check_updates()
        assert 'GitHub' in w.update_info.text() and not w.notice.isVisible()
        w.task_done({'version': s.version, 'notes': ''})
        app.processEvents()
        assert not w.release_field.isVisible() and not w.install_btn.isEnabled()
        assert w.update_info.text() == 'Установлена актуальная версия.'
        w.grab().save(str(out / 'updates-checked.png'))
    w.navigate(1)
    old_value = probe.isChecked()
    for key_event in (QKeyEvent.Type.KeyPress, QKeyEvent.Type.KeyRelease):
        QApplication.sendEvent(probe, QKeyEvent(key_event, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
    assert probe.isChecked() != old_value and w.save_btn.isEnabled()
    probe.setChecked(old_value)
    assert not w.save_btn.isEnabled()
    w.domain_disclosure.click()
    app.processEvents()
    settings_scroll = w.pages.currentWidget().findChild(QScrollArea)
    if settings_scroll:
        settings_scroll.verticalScrollBar().setValue(settings_scroll.verticalScrollBar().maximum())
        app.processEvents()
        w.grab().save(str(out / 'settings-lower.png'))
        assert_outline(w.domain_edit.parentWidget(), EDGE)
        settings_scroll.verticalScrollBar().setValue(0)
    w.domain_edit.setPlainText('https://bad.com')
    w.save_settings()
    app.processEvents()
    assert w.notice.isVisible() and 'без https://' in w.notice.text()
    w.grab().save(str(out / 'validation.png'))
    w.domain_edit.setPlainText('example.org')
    w.save_settings()
    assert s.settings['domains'] == 'example.org'
    w.navigate(0)
    w.profile.setCurrentIndex(1)
    assert s.settings['profile'] == w.profile.currentData()
    QApplication.setActiveWindow(w)
    w.profile.setFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    assert w.profile.hasFocus()
    w.profile.grab().save(str(out / 'profile-focus.png'))
    popup = w.profile.view().window()
    popup.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
    QApplication.sendEvent(w.profile, QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_F4, Qt.KeyboardModifier.NoModifier))
    app.processEvents()
    assert w.profile.view().isVisible()
    assert w.profile.view().currentIndex().row() == w.profile.currentIndex()
    popup.grab().save(str(out / 'profile-list.png'))
    w.profile.hidePopup()
    w.say('Тестовая ошибка соединения. Данные текущего подключения не изменены.', True)
    app.processEvents()
    w.grab().save(str(out / 'notice.png'))
    w.nav[1].setFocus()
    app.processEvents()
    w.grab().save(str(out / 'keyboard-focus.png'))
    for control in (w.power, w.profile, w.check_btn):
        control.setFocus(Qt.FocusReason.TabFocusReason)
        app.processEvents()
        assert control.hasFocus()
        assert_outline(control, FOCUS)
    w.timer.stop()
    w.update_timer.stop()
    w.quitting = True
    w.close()
print(f'Qt UI interactions and screenshots at {w.devicePixelRatioF():.2f}x: OK')
