"""Verify single-instance startup, window close and relaunch from an extracted ZIP."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from zipfile import ZipFile


def find_window(child, title):
    user32 = ctypes.windll.user32
    callback = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    matches = []
    @callback
    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == child.pid:
            caption = ctypes.create_unicode_buffer(160)
            user32.GetWindowTextW(hwnd, caption, len(caption))
            if caption.value == title:
                matches.append(hwnd)
        return True
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and child.poll() is None:
        user32.EnumWindows(visit, 0)
        if matches:
            return matches[0]
        time.sleep(.05)
    raise RuntimeError(f'Window missing: {title}, exit={child.poll()}')


def main(archive):
    with tempfile.TemporaryDirectory() as tmp:
        with ZipFile(archive) as z:
            z.extractall(tmp)
        app = Path(tmp) / 'byerkn'
        data = app / 'data'
        data.mkdir()
        user = dict(close_to_tray=False, auto_check=False, start_engine=False, domains='fixture.example')
        config = data / 'settings.json'
        config.write_text(json.dumps(user))
        owned = []
        def start():
            proc = subprocess.Popen([app / 'runtime/pythonw.exe','-B','-m','byerkn'], cwd=app)
            owned.append(proc)
            return proc
        def close(proc, hwnd):
            ctypes.windll.user32.PostMessageW(wintypes.HWND(hwnd), 0x10, 0, 0)
            assert proc.wait(timeout=10) == 0
        try:
            first = start()
            window = find_window(first, 'byerkn')
            second = start()
            close(second, find_window(second, 'byerkn уже работает'))
            assert first.poll() is None
            close(first, window)
            third = start()
            close(third, find_window(third, 'byerkn'))
            assert not (data / 'byerkn.lock').exists()
            assert json.loads(config.read_text()) == user
        finally:
            for proc in owned:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=5)
    print('Packaged pythonw entry: initial launch, duplicate, close, relaunch and settings OK.')


if __name__ == '__main__':
    main(Path(sys.argv[1]))
