import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from byerkn.core import (AppError, DEFAULTS, Engine, KillJob, Storage, Updater, atomic_json,
                         normalize_domains, profile_args, safe_extract, validate_engine)

ROOT = Path(__file__).resolve().parents[1]


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='byerkn-tests-', dir=ROOT)
        self.s = Storage(ROOT, Path(self.temp.name) / 'data')

    def tearDown(self):
        self.temp.cleanup()

    def test_all_upstream_profiles_translate_without_shell(self):
        profiles = self.s.profiles()
        self.assertGreater(len(profiles), 10)
        for p in profiles:
            for enabled in (False, True):
                with self.subTest(profile=p.name, game=enabled):
                    args = profile_args(p, self.s.current, self.s.users, {**DEFAULTS, 'game_filter': enabled})
                    self.assertTrue(all(x.startswith('--') for x in args))
                    self.assertFalse(any('%' in x or '"' in x for x in args))
                    self.assertIn('--wf-udp=443,19294-19344,50000-50100,' + ('1024-65535' if enabled else '12'), args)
                    self.assertTrue(any(str(self.s.users / 'list-general-user.txt') in x for x in args))

    def test_profile_unknown_variable_rejected(self):
        path = self.s.current / 'bad.bat'
        path.write_text('start "zapret" /min "%BIN%winws.exe" --hostlist="%EVIL%file"')
        with self.assertRaises(AppError):
            profile_args(path, self.s.current, self.s.users, DEFAULTS)

    def test_profile_does_not_execute_trailing_batch_lines(self):
        path = self.s.current / 'bad.bat'
        path.write_text('start "zapret" /min "%BIN%winws.exe" --debug=1\ncalc.exe\n')
        self.assertEqual(profile_args(path, self.s.current, self.s.users, DEFAULTS), ['--debug=1'])

    def test_profile_path_escape_rejected(self):
        path = self.s.current / 'bad.bat'
        path.write_text('start "zapret" /min "%BIN%winws.exe" --hostlist="C:\\Windows\\win.ini"')
        with self.assertRaises(AppError):
            profile_args(path, self.s.current, self.s.users, DEFAULTS)

    def test_settings_survive_update_and_rollback(self):
        self.s.save({'domains': 'Example.org\nпример.рф\nExample.org', 'game_filter': True})
        before = self.s.config.read_bytes()
        incoming = Path(self.temp.name) / 'incoming'
        shutil.copytree(self.s.current, incoming)
        atomic_json(incoming / '_byerkn.json', {'version': 'test-next'})
        updater = Updater(self.s)
        updater.commit(incoming)
        self.assertEqual(self.s.version, 'test-next')
        self.assertEqual(self.s.config.read_bytes(), before)
        self.assertEqual(updater.rollback(), '1.10.4')
        self.assertEqual(self.s.config.read_bytes(), before)
        self.assertIn('example.org', (self.s.users / 'list-general-user.txt').read_text())

    def test_failed_swap_restores_current_and_previous(self):
        incoming = Path(self.temp.name) / 'incoming'
        shutil.copytree(self.s.current, incoming)
        updater = Updater(self.s)
        updater.commit(incoming)
        import os
        original = os.replace
        missing = Path(self.temp.name) / 'not-there'
        with self.assertRaises(FileNotFoundError):
            updater.commit(missing)
        self.assertTrue(self.s.current.is_dir())
        self.assertTrue(self.s.previous.is_dir())
        validate_engine(self.s.current)

    def test_recover_interrupted_install(self):
        self.s.current.rename(self.s.previous)
        recovered = Storage(ROOT, self.s.data)
        self.assertEqual(recovered.version, '1.10.4')

    def test_corrupt_settings_preserved(self):
        self.s.config.write_text('{bad')
        recovered = Storage(ROOT, self.s.data)
        self.assertTrue(self.s.config.with_suffix('.invalid.json').exists())
        self.assertEqual(recovered.settings['profile'], 'general.bat')

    def test_domain_validation(self):
        self.assertEqual(normalize_domains('EXAMPLE.org\nexample.org\n# comment'), 'example.org')
        for host in ('https://example.org', 'site.com/path', 'hello world.com', 'a..com', '1.2.3.4', '-bad.com'):
            with self.subTest(host=host), self.assertRaises(AppError):
                normalize_domains(host)

    def test_ip_filter_disabled_uses_empty_match_list(self):
        args = profile_args(self.s.current / 'general.bat', self.s.current, self.s.users, {**DEFAULTS, 'ip_filter': False})
        self.assertFalse(any('ipset-all.txt' in x for x in args))
        self.assertTrue(any('ipset-disabled.txt' in x for x in args))

    def test_archive_traversal_rejected(self):
        for name in ('../outside.txt', '/absolute.txt', 'C:/evil', 'a/../../evil', 'a\\..\\..\\evil', 'con.txt', 'bad. /evil'):
            archive = Path(self.temp.name) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr(name, b'bad')
            with self.subTest(name=name), self.assertRaises(AppError):
                safe_extract(archive, Path(self.temp.name) / 'out')

    def test_wrong_hash_leaves_engine_intact(self):
        archive = (ROOT / 'downloads/zapret.zip').read_bytes()
        with patch('byerkn.core.urllib.request.urlopen', return_value=io.BytesIO(archive)):
            with self.assertRaises(AppError):
                Updater(self.s).install(dict(url='https://github.com/test', size=len(archive), digest='sha256:' + '0'*64, version='bad'))
        self.assertEqual(self.s.version, '1.10.4')
        self.assertFalse(self.s.previous.exists())

    def test_complete_verified_install(self):
        archive = (ROOT / 'downloads/zapret.zip').read_bytes()
        release = json.loads((ROOT / 'upstream-release.json').read_text('utf-8-sig'))
        asset = next(x for x in release['assets'] if x['name'].endswith('.zip'))
        with patch('byerkn.core.urllib.request.urlopen', return_value=io.BytesIO(archive)):
            result = Updater(self.s).install(dict(url=asset['browser_download_url'], size=asset['size'], digest=asset['digest'], version=release['tag_name']))
        self.assertEqual(result, '1.10.4')
        self.assertTrue(self.s.previous.exists())

    def test_engine_never_stops_external_process(self):
        engine = Engine(self.s)
        with patch('byerkn.core.is_admin', return_value=True), patch('byerkn.core.external_engines', return_value=True), patch('byerkn.core.subprocess.Popen') as popen:
            with self.assertRaises(AppError):
                engine.start()
            popen.assert_not_called()
        engine.stop()

    def test_job_closes_only_owned_child(self):
        import subprocess
        import sys
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        other = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            job = KillJob(child)
            job.close()
            child.wait(timeout=5)
            self.assertIsNone(other.poll())
        finally:
            for p in (child, other):
                if p.poll() is None:
                    p.terminate()
                p.wait(timeout=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
