import os
from pathlib import Path
import sys

# The same FreeType text renderer as helloytd; avoids variable-font weight bugs.
os.environ.setdefault('QT_QPA_PLATFORM', 'windows:fontengine=freetype')

from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox
from .core import Storage, setup_logging, LOG
from .ui import Window, load_font


def main():
    root = Path(__file__).resolve().parent.parent
    app = QApplication(sys.argv)
    app.setApplicationName('byerkn')
    app.setOrganizationName('byerkn')
    app.setQuitOnLastWindowClosed(False)
    load_font(root)
    data = root / 'data'
    try:
        data.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(data / 'byerkn.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(100):
            QMessageBox.information(None, 'byerkn уже работает', 'Откройте byerkn через значок в трее рядом с часами.')
            return 0
        setup_logging(data)
        storage = Storage(root)
        LOG.info('byerkn запущен')
        window = Window(storage)
        window.show()
        app.aboutToQuit.connect(window.engine.stop)
        code = app.exec()
        lock.unlock()
        return code
    except Exception as exc:
        LOG.exception('Ошибка запуска')
        QMessageBox.critical(None, 'byerkn не запустился', f'{exc}\n\nПоместите программу в папку с правом записи. Подробности: data/byerkn.log.')
        return 1


if __name__ == '__main__':
    sys.exit(main())
