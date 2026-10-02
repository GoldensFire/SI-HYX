# -*- coding: utf-8 -*-
"""Directory enumeration in a worker; only completed results reach Qt."""
import heapq
import os

from PyQt6.QtCore import QObject, QRunnable, QThreadPool, pyqtSignal


def scan_recent(folder, mode, allowed, excluded, limit=30):
    def entries():
        try:
            with os.scandir(folder) as directory:
                for entry in directory:
                    extension = os.path.splitext(entry.name)[1].lower()
                    if (extension in excluded if mode == "all"
                            else extension not in allowed):
                        continue
                    try:
                        if entry.is_file():
                            yield entry.stat().st_mtime, entry.path
                    except OSError:
                        continue
        except OSError:
            return

    if not folder:
        return []
    return [path for _, path in heapq.nlargest(limit, entries())]


class ScanSignals(QObject):
    finished = pyqtSignal(object, object)


class ScanTask(QRunnable):
    def __init__(self, request):
        super().__init__()
        self.request = request
        self.signals = ScanSignals()

    def run(self):
        try:
            paths = scan_recent(*self.request)
        except Exception:
            paths = []
        self.signals.finished.emit(self.request, paths)


class DirectoryScanner(QObject):
    ready = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.task = None
        self.requested = None

    def request(self, folder, mode, allowed, excluded):
        self.requested = (folder, mode, frozenset(allowed), frozenset(excluded))
        if self.task is None:
            self._start()

    def _start(self):
        self.task = ScanTask(self.requested)
        self.task.signals.finished.connect(self._finished)
        QThreadPool.globalInstance().start(self.task)

    def _finished(self, request, paths):
        self.task = None
        if request == self.requested:
            self.ready.emit(paths)
        else:
            # A folder change during scanning must not display the old folder.
            self._start()
