from pathlib import Path
import tempfile
import unittest
from zipfile import ZipFile
from unittest.mock import patch
from tools.package_portable import publish


class PackagingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dist = Path(tmp.name)
        self.stage = self.dist / '_build-test/byerkn'
        self.stage.mkdir(parents=True)
        (self.stage / 'sample').write_bytes(b'candidate')
        self.out = self.dist / 'byerkn'
        self.out.mkdir()
        (self.out / 'sample').write_bytes(b'previous')

    def test_default_rebuild_preserves_data_and_excludes_it_from_zip(self):
        data = self.out / 'data'
        data.mkdir()
        (data / 'sentinel').write_bytes(b'private')
        publish(self.stage)
        self.assertEqual((data / 'sentinel').read_bytes(), b'private')
        self.assertEqual((self.out / 'sample').read_bytes(), b'previous')
        with ZipFile(self.dist / 'byerkn-portable.zip') as z:
            self.assertEqual(z.namelist(), ['byerkn/sample'])
            self.assertEqual(z.read('byerkn/sample'), b'candidate')

    def test_locked_archive_restores_previous_directory(self):
        with patch('tools.package_portable.os.replace', side_effect=PermissionError), self.assertRaises(PermissionError):
            publish(self.stage)
        self.assertEqual((self.out / 'sample').read_bytes(), b'previous')
        self.assertEqual((self.stage / 'sample').read_bytes(), b'candidate')
