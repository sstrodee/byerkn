import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from byerkn.core import AppError, Storage, Updater, atomic_json, latest_release, probe_endpoint, profile_args

ROOT = Path(__file__).resolve().parents[1]


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / 'data'
        self.s = Storage(ROOT, self.data)

    def restart(self):
        return Storage(ROOT, self.data)

    def test_wrong_shape_metadata(self):
        for value in (None, [], 4, {'version': None}, {'version': ''}):
            with self.subTest(value=value):
                atomic_json(self.s.current / '_byerkn.json', value)
                self.assertIsInstance(self.s.version, str)
                self.assertTrue(self.s.version)

    def test_wrong_shape_config_preserved(self):
        atomic_json(self.s.config, [])
        self.restart()
        self.assertEqual(json.loads(self.s.config.with_suffix('.invalid.json').read_text()), [])

    def test_save_failure_does_not_commit_partial_settings(self):
        self.s.save({'domains': 'original.example', 'exclusions': 'old.example'})
        original = os.replace
        def deny(source, target):
            if Path(target).name == 'list-exclude-user.txt':
                raise PermissionError('test: list is locked')
            original(source, target)
        with patch('byerkn.core.os.replace', side_effect=deny), self.assertRaises(PermissionError):
            self.s.save({'domains': 'new.example', 'exclusions': 'new.example'})
        self.assertEqual(self.s.settings['domains'], 'original.example')
        self.assertEqual(json.loads(self.s.config.read_text())['domains'], 'original.example')
        self.assertEqual((self.s.users / 'list-general-user.txt').read_text().strip(), 'original.example')
        self.assertEqual(self.restart().settings, self.s.settings)

    def test_recover_each_rollback_boundary(self):
        import shutil
        shutil.copytree(self.s.current, self.s.previous)
        atomic_json(self.s.previous / '_byerkn.json', {'version': 'backup'})
        swap = self.data / 'rollback-swap'
        version = self.s.version
        self.s.current.rename(swap)
        self.restart()
        self.assertEqual(self.s.version, version)
        self.assertTrue(self.s.previous.is_dir())
        self.s.current.rename(swap)
        self.s.previous.rename(self.s.current)
        self.restart()
        self.assertEqual(self.s.version, 'backup')
        self.assertEqual(Updater(self.s).rollback(), version)

    def test_recover_retired_backup(self):
        import shutil
        retired = self.data / 'retired-engine'
        shutil.copytree(self.s.current, retired)
        self.s.current.rename(self.s.previous)
        self.restart()
        self.assertTrue(self.s.previous.is_dir())
        self.assertFalse(retired.exists())

    def test_locked_final_rollback_rename_restores_both_versions(self):
        import shutil
        shutil.copytree(self.s.current, self.s.previous)
        atomic_json(self.s.previous / '_byerkn.json', {'version':'backup'})
        version = self.s.version
        replace = os.replace
        def fail(source, dest):
            if Path(source).name == 'rollback-swap' and dest == self.s.previous:
                raise PermissionError('test: locked')
            replace(source, dest)
        with patch('os.replace', side_effect=fail), self.assertRaises(PermissionError):
            Updater(self.s).rollback()
        self.assertEqual(self.s.version, version)
        self.assertTrue(self.s.previous.is_dir())
        self.assertFalse((self.data / 'rollback-swap').exists())

    def test_portable_path_with_symbols(self):
        self.s = Storage(ROOT, self.data.parent / 'Тест & 100%')
        args = profile_args(self.s.current / 'general.bat', self.s.current, self.s.users, self.s.settings)
        self.assertTrue(any(str(self.s.users) in arg for arg in args))

    def test_release_shape_and_timeouts(self):
        for response in ([], None, {'assets':[{}]}, {'assets':None}):
            with self.subTest(response=response), patch('urllib.request.urlopen',
                    return_value=io.BytesIO(json.dumps(response).encode())), self.assertRaises(AppError):
                latest_release()
        with patch('urllib.request.urlopen', side_effect=urllib.error.URLError('offline')), self.assertRaises(AppError):
            latest_release()

    def test_read_interruption_preserves_current(self):
        version = self.s.version
        with patch('urllib.request.urlopen', side_effect=TimeoutError('offline')), self.assertRaises(OSError):
            Updater(self.s).install({'url':'https://github.com/Flowseal/zapret-discord-youtube/releases/download/test/test.zip'})
        self.assertEqual(self.s.version, version)
        self.assertEqual(list(self.data.glob('update-*')), [])

    def test_slow_update_hits_overall_deadline(self):
        with patch('urllib.request.urlopen', return_value=io.BytesIO(b'partial')), patch(
                'byerkn.core.time.monotonic', side_effect=[0, 0, 600]), self.assertRaisesRegex(AppError, 'время'):
            Updater(self.s).install({'url':'https://github.com/test','size':1,'digest':'test'})
        self.assertFalse(self.s.previous.exists())

    def test_diagnostic_rejects_unrelated_success_page(self):
        from unittest.mock import MagicMock
        opener = MagicMock()
        response = opener.open.return_value.__enter__.return_value
        response.status = 200
        response.geturl.return_value = 'https://other.example/welcome'
        response.read.return_value = b'<html>Welcome</html>'
        with patch('urllib.request.build_opener', return_value=opener):
            self.assertFalse(probe_endpoint(('Google', 'https://www.google.com/generate_204'))['ok'])

    def test_flush_failure_preserves_committed_config(self):
        self.s.save({'domains':'persist.example'})
        before = self.s.config.read_bytes()
        with patch('os.fsync', side_effect=OSError(28, 'test disk full')), self.assertRaises(OSError):
            self.s.save({'domains':'changed.example'})
        self.assertEqual(self.s.config.read_bytes(), before)
        self.assertEqual(self.restart().settings['domains'], 'persist.example')
