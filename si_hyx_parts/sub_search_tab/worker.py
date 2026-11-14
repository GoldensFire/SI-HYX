# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Фоновый прогон «Поиска по сабам»: движок в своём потоке, события — сигналами
в поток интерфейса (QObject живёт в GUI-потоке, сигналы ставятся в очередь)."""
import sub_search_tab as _api


class SearchWorker(_api.QObject):
    status = _api.pyqtSignal(str)
    log = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int)
    hit = _api.pyqtSignal(object)
    finished = _api.pyqtSignal(dict)

    def __init__(self, req, excluded_ids=None, parent=None):
        super().__init__(parent)
        self.req = req
        self.excluded_ids = excluded_ids
        self.stop_event = _api.threading.Event()
        self.thread = None

    def start(self):
        self.thread = _api.threading.Thread(target=self._run, name="sub-search",
                                            daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def wait(self, timeout: float) -> bool:
        if self.thread is None:
            return True
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def _emit(self, event, data):
        try:
            self._send(event, data)
        except RuntimeError:  # вкладку уже закрыли — сигналам некуда идти
            self.stop_event.set()

    def _send(self, event, data):
        if event == "status":
            self.status.emit(str(data))
        elif event == "log":
            self.log.emit(str(data))
        elif event == "progress":
            self.progress.emit(int(data[0]), int(data[1]))
        elif event == "hit":
            self.hit.emit(data)
        elif event == "finished":
            self.finished.emit(dict(data))

    def _run(self):
        _api.engine.SearchEngine(self.req, self._emit, self.stop_event,
                                 self.excluded_ids).run()
