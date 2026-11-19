"""Prepare verified runtime dependencies and the recorded engine in a fresh tree."""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.request import urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from byerkn.core import atomic_json, safe_extract, validate_engine


def fetch(cache, url, digest):
    if cache.is_file():
        with cache.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() == digest:
                return
    from tempfile import NamedTemporaryFile
    with NamedTemporaryFile(dir=cache.parent, delete=False) as output:
        pending = Path(output.name)
    try:
        with urlopen(url, timeout=30) as response, pending.open('wb') as output:
            shutil.copyfileobj(response, output)
        with pending.open('rb') as source:
            if hashlib.file_digest(source, 'sha256').hexdigest() != digest:
                raise ValueError(f'Checksum mismatch: {cache.name}')
        pending.replace(cache)
    finally:
        pending.unlink(missing_ok=True)


def needed(name):
    parts = Path(name).parts
    if parts[0] != 'PySide6':
        return True  # shiboken and distribution metadata, including notices
    if len(parts) == 2:
        leaf = parts[-1]
        return (leaf.startswith(('QtCore.', 'QtGui.', 'QtWidgets.', 'QtSvg.')) or
                leaf in ('Qt6Core.dll','Qt6Gui.dll','Qt6Widgets.dll','Qt6Svg.dll') or
                (leaf.endswith('.dll') and not leaf.startswith('Qt')) or
                leaf in ('__init__.py','_config.py','_git_pyside_version.py','py.typed','PySide6_Essentials.json'))
    return (name.startswith('PySide6/support/') or name.startswith('PySide6/plugins/') and
            parts[-1] in ('qwindows.dll','qmodernwindowsstyle.dll','qico.dll','qsvgicon.dll','qsvg.dll',
                          'qgif.dll','qjpeg.dll','qwebp.dll') or
            parts[-1] in ('qt_ru.qm','qtbase_ru.qm'))


def prepare(work, qt_version):
    cache = ROOT / 'downloads'
    packages = work / 'runtime/Lib/site-packages'
    for name, pinned in (('PySide6-Essentials','c9a95102aa23c1f86516a30d5a9be37552d324eee7e567eb7508973f1218cb42'),
                         ('shiboken6','a1906cb8116869178c64b6bab52623bbc8b4ceed7b30bfc3c9aa0f6e67f6438e')):
        with urlopen(f'https://pypi.org/pypi/{name}/{qt_version}/json', timeout=30) as res:
            release = json.load(res)
        assets = [f for f in release['urls'] if f['filename'].endswith('abi3-win_amd64.whl')]
        if len(assets) != 1:
            raise ValueError(f'No unique Windows wheel: {name}')
        asset = assets[0]
        wheel = cache / Path(asset['filename']).name
        digest = asset['digests']['sha256']
        if qt_version == '6.12.0' and digest != pinned:
            raise ValueError(f'Unexpected wheel hash: {name}')
        fetch(wheel, asset['url'], digest)
        with ZipFile(wheel) as z:
            for member in z.namelist():
                if needed(member):
                    z.extract(member, packages)
    import PySide6.QtWidgets, shiboken6
    if PySide6.__version__ != qt_version or shiboken6.__version__ != qt_version:
        raise ValueError('Unexpected Qt version')
    release = json.loads((ROOT / 'upstream-release.json').read_text('utf-8-sig'))
    asset = next(f for f in release['assets'] if f['name'].endswith('.zip'))
    archive = cache / 'zapret.zip'
    digest = asset['digest'].removeprefix('sha256:')
    fetch(archive, asset['browser_download_url'], digest)
    unpacked = work / 'unpacked'
    safe_extract(archive, unpacked)
    (profile,) = unpacked.rglob('general.bat')
    validate_engine(profile.parent)
    profile.parent.rename(work / 'bundle')
    atomic_json(work / 'bundle/_byerkn.json', {'version':release['tag_name'], 'digest':asset['digest']})


if __name__ == '__main__':
    prepare(Path(sys.argv[1]), sys.argv[2])
