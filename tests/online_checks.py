"""Read-only network smoke test; writes a reproducible local QA report."""
import json
from pathlib import Path
import sys
import tempfile
from byerkn.core import latest_release, diagnostics, external_engines, is_admin, Storage, Updater

root = Path(__file__).resolve().parents[1]
release = latest_release()
report = {'release': release['version'], 'digest': release['digest'],
          'diagnostics': diagnostics(), 'external_engine': external_engines(), 'admin': is_admin()}
if '--install-in-temp' in sys.argv[1:]:
    with tempfile.TemporaryDirectory() as tmp:
        storage = Storage(root, Path(tmp) / 'data')
        storage.save({'domains': 'fixture.example'})
        before = storage.config.read_bytes()
        initial = storage.version
        updater = Updater(storage)
        report['installed'] = updater.install(release)
        assert report['installed'] == release['version'] and storage.previous.is_dir()
        report['rolled_back'] = updater.rollback()
        assert report['rolled_back'] == initial and storage.config.read_bytes() == before
(root / 'tests/online-results.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=2))
