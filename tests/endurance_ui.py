"""Bounded event-loop soak on temporary settings, with a real queued worker."""
import json
import os
import sys
from pathlib import Path
import tempfile
import time
os.environ['QT_QPA_PLATFORM'] = 'windows:fontengine=freetype'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from byerkn.core import Storage
from byerkn.ui import Window, load_font
from tests.stress_storage import process_metrics

ROOT = Path(__file__).resolve().parents[1]


def main(seconds=90):
    app = QApplication([])
    load_font(ROOT)
    with tempfile.TemporaryDirectory() as tmp:
        w = Window(Storage(ROOT, Path(tmp)), testing=True)
        w.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
        w.show()
        start = time.perf_counter()
        cpu = time.process_time()
        samples, latencies, done = [], [], []
        iterations = 0
        while time.perf_counter() - start < seconds:
            t = time.perf_counter()
            w.nav[iterations % 5].click()
            assert w.pages.currentIndex() == iterations % 5
            if iterations % 10 == 0:
                w.checkboxes['game_filter'].toggle()
                w.save_settings()
                assert w.s.settings['game_filter'] == w.checkboxes['game_filter'].isChecked()
                w.run_task(lambda: 1, done.append, action=w.check_btn)
            while w.busy:
                app.processEvents()
                if time.perf_counter() - t > 5:
                    raise TimeoutError('Worker failed to return')
            app.processEvents()
            latencies.append((time.perf_counter() - t) * 1000)
            if iterations % 200 == 0:
                samples.append(process_metrics())
            iterations += 1
            time.sleep(.008)
        assert len(done) == (iterations + 9) // 10
        w.timer.stop()
        w.update_timer.stop()
        w.quitting = True
        w.close()
        latencies.sort()
        print(json.dumps(dict(seconds=round(time.perf_counter()-start, 2), iterations=iterations,
              worker_completions=len(done), errors=0, cpu_s=round(time.process_time()-cpu, 2),
              ms={str(p):round(latencies[int((len(latencies)-1)*p/100)], 3) for p in (50,95,99)},
              samples=samples, end=process_metrics()), indent=2))


if __name__ == '__main__':
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 90)
