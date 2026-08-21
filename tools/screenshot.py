#!/usr/bin/env python3
"""
Take thumb.png headlessly: QT_QPA_PLATFORM=offscreen python tools/screenshot.py <folder with sample videos>
Runs a real rename over the folder, waits for the finished signal, then grabs the window.
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import main as app_main  # noqa: E402

app = QApplication(sys.argv)
app.setStyle("Fusion")
win = app_main.MainWindow()
win.resize(1180, 760)
win.show()
folder = sys.argv[1]


def grab():
    win.grab().save("thumb.png")
    print("thumb.png saved")
    app.quit()


def start():
    win.start()
    win.worker.finished_all.connect(lambda *a: QTimer.singleShot(600, grab))


win.add_paths([folder])
win.prober.finished.connect(lambda: QTimer.singleShot(300, start))
QTimer.singleShot(60000, grab)
app.exec()
