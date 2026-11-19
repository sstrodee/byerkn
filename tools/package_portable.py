"""Verify and publish a newly staged portable build on the same volume."""
import os
import msvcrt
from pathlib import Path
import re
import sys
from zipfile import ZIP_DEFLATED, ZipFile


def publish(stage, archive_name='byerkn-portable.zip'):
    work = stage.parent
    dist = work.parent
    if stage.name != 'byerkn' or not work.name.startswith('_build-'):
        raise ValueError('Unexpected build path')
    if not re.fullmatch(r'byerkn-(?:portable|\d+\.\d+\.\d+-windows-x64)\.zip', archive_name):
        raise ValueError('Unexpected portable archive name')
    with (dist / '.byerkn-build.lock').open('a+b') as lock:
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        publish_locked(stage, work, dist, archive_name)


def publish_locked(stage, work, dist, archive_name):
    out = dist / 'byerkn'
    archive = dist / archive_name
    packed = work / archive.name
    if (stage / 'data').exists():
        raise ValueError('Personal data in release staging')
    files = [p for p in stage.rglob('*') if p.is_file()]
    with ZipFile(packed, 'w', ZIP_DEFLATED) as z:
        for p in files:
            z.write(p, p.relative_to(work).as_posix())
    with ZipFile(packed) as z:
        for p in files:
            if z.read(p.relative_to(work).as_posix()) != p.read_bytes():
                raise OSError(f'Archive verification failed: {p.name}')
    # A working installation can have a live lock or an open engine. Never
    # delete/move its settings to make room for a build. The ZIP is independent.
    if (out / 'data').exists():
        os.replace(packed, archive)
        print(f'Existing installation preserved. Verified update: {archive}')
        return
    backup = work / 'previous-build'
    if out.exists():
        out.rename(backup)
        if (backup / 'data').exists():
            backup.rename(out)
            os.replace(packed, archive)
            return
    try:
        stage.rename(out)
        try:
            os.replace(packed, archive)
        except OSError:
            out.rename(stage)
            raise
    except OSError:
        if backup.exists():
            backup.rename(out)
        raise
    print(f'Verified {len(files)} files: {out} and {archive}')


if __name__ == '__main__':
    publish(Path(sys.argv[1]).resolve(), *sys.argv[2:])
