import os
os.environ.setdefault('QT_QPA_PLATFORM', 'windows:fontengine=freetype')
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from byerkn.core import Storage
from byerkn.ui import Window, load_font

ROOT = Path(__file__).resolve().parents[1]


class InteractionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        load_font(ROOT)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = Window(Storage(ROOT, Path(tmp.name)), testing=True)
        self.w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        self.w.show()
        self.app.processEvents()

    def tearDown(self):
        self.w.timer.stop()
        self.w.update_timer.stop()
        self.w.pool.waitForDone(5000)
        self.w.quitting = True
        self.w.close()
        self.w.deleteLater()
        self.app.processEvents()

    def test_unsaved_profile_restores_visible_selection(self):
        w = self.w
        original = w.profile.currentData()
        with patch.object(w.s, 'save', side_effect=PermissionError('locked')):
            w.profile.setCurrentIndex(1)
        self.assertEqual(w.profile.currentData(), original)
        self.assertEqual(w.s.settings['profile'], original)
        self.assertTrue(w.notice.isVisible())

    def test_crash_during_check_drops_stale_measurements(self):
        w = self.w
        with patch.object(type(w.engine), 'running', new_callable=unittest.mock.PropertyMock, return_value=True):
            w.engine.started_at = 100
            w.tick()
            with patch.object(w.pool, 'start'):
                w.run_diagnostics()
        w.engine.started_at = None
        w.tick()
        w.task_done([{'name': n, 'ok': True, 'detail':'test'} for n in w.health])
        self.assertEqual(w.last_check.text(), 'Ещё не проверяли')
        self.assertTrue(w.notice.isVisible())

    def test_one_worker_for_double_action_and_retry(self):
        w = self.w
        barrier = threading.Event()
        calls = []
        def delayed():
            calls.append(1)
            if not barrier.wait(3):
                raise TimeoutError('fixture timeout')
            return 7
        def drain():
            deadline = time.monotonic() + 4
            while w.busy and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(.002)
            self.assertFalse(w.busy)
        values = []
        for _ in range(20):
            w.run_task(delayed, values.append, action=w.check_btn)
        self.assertTrue(w.busy)
        self.assertFalse(w.check_btn.isEnabled())
        barrier.set()
        drain()
        self.assertEqual((calls, values), ([1], [7]))
        def offline():
            raise TimeoutError('test offline')
        with self.assertLogs('byerkn', level='ERROR'):
            w.run_task(offline, values.append, action=w.check_btn)
            drain()
        self.assertTrue(w.check_btn.isEnabled())
        self.assertIn('test offline', w.notice.text())
        w.run_task(lambda: 8, values.append, action=w.check_btn)
        drain()
        self.assertEqual(values, [7, 8])

    def test_large_domain_save_returns_to_event_loop(self):
        w = self.w
        text = '\n'.join(f'host{i}.example' for i in range(10000))
        w.domain_edit.setPlainText(text)
        w.save_btn.click()
        self.assertTrue(w.busy)
        deadline = time.monotonic() + 6
        while w.busy and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(.002)
        self.assertFalse(w.busy)
        self.assertEqual(w.s.settings['domains'], text)
        self.assertFalse(w.save_btn.isEnabled())
