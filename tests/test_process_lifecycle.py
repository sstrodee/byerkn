"""Exercise the real Windows process/job lifecycle with a harmless Python child."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from byerkn.core import AppError, Engine, Storage


class ProcessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.engine = Engine(Storage(Path(__file__).resolve().parents[1], Path(tmp.name)))
        self.addCleanup(self.engine.stop)
        self.children = []
        for name, value in [('is_admin', True), ('external_engines', False)]:
            ctx = patch('byerkn.core.' + name, return_value=value)
            ctx.start()
            self.addCleanup(ctx.stop)

    def child_factory(self, code):
        popen = subprocess.Popen
        def start(_args, **kwargs):
            child = popen([sys.executable, '-c', code], **kwargs)
            self.children.append(child)
            return child
        return start

    def test_parallel_starts_and_stops_one_owned_child(self):
        with patch('byerkn.core.subprocess.Popen', self.child_factory('import time; time.sleep(15)')):
            with ThreadPoolExecutor(6) as workers:
                list(workers.map(lambda _: self.engine.start(), range(12)))
                self.assertTrue(self.engine.running)
                list(workers.map(lambda _: self.engine.stop(), range(12)))
        self.assertEqual(len(self.children), 1)
        self.assertIsNotNone(self.children[0].poll())
        self.assertIsNone(self.engine.job)
        self.assertIsNone(self.engine.output)

    def test_child_early_exit_and_job_failure_release_handles(self):
        with patch('byerkn.core.subprocess.Popen', self.child_factory('print("fixture exit")')):
            with self.assertRaisesRegex(AppError, 'fixture exit'):
                self.engine.start()
        with patch('byerkn.core.subprocess.Popen', self.child_factory('import time; time.sleep(15)')), patch(
                'byerkn.core.KillJob', side_effect=AppError('test job refused')):
            with self.assertRaisesRegex(AppError, 'test job refused'):
                self.engine.start()
        self.assertTrue(all(child.poll() is not None for child in self.children))
        self.assertIsNone(self.engine.output)
        self.assertFalse(self.engine.running)
