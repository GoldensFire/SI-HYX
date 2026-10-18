# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProjectThumbWorker — миниатюры клипов проекта. Public namespace:
edit_tab_workers."""
import edit_tab_workers as _api


class ProjectThumbWorker(_api.QThread):
    """Первый кадр каждого клипа проекта маленькой картинкой — для таймлайна.

    Очередь заданий (не «последняя цель», как у превью перемотки): клипов
    обычно немного, и нужен кадр каждого. Одно задание — один ffmpeg на кадр
    с быстрым входным seek'ом."""

    ready = _api.pyqtSignal(str, object)     # ключ, QImage

    def __init__(self):
        super().__init__()
        self._jobs = []
        self._stop = False
        self._cond = _api.threading.Condition()

    def request(self, key, src, sec, height):
        with self._cond:
            if any(job[0] == key for job in self._jobs):
                return
            self._jobs.append((key, str(src), float(sec), int(height)))
            self._cond.notify()

    def stop(self):
        with self._cond:
            self._stop = True
            self._jobs = []
            self._cond.notify()

    def run(self):
        while True:
            with self._cond:
                while not self._jobs and not self._stop:
                    self._cond.wait()
                if self._stop:
                    return
                key, src, sec, height = self._jobs.pop(0)
            img = self._extract(src, sec, height)
            if img is not None and not img.isNull():
                self.ready.emit(key, img)

    @staticmethod
    def _extract(src, sec, height):
        try:
            r = _api.subprocess.run(
                [_api.FFMPEG, "-v", "error", "-ss", f"{max(0.0, sec):.3f}", "-i", src,
                 "-frames:v", "1", "-vf", f"scale=-2:{max(8, height)}",
                 "-f", "image2pipe", "-vcodec", "png", "-"],
                capture_output=True, timeout=20, creationflags=_api.CREATE_NO_WINDOW)
        except Exception:
            return None
        img = _api.QImage()
        if r.stdout and img.loadFromData(r.stdout, "PNG"):
            return img
        return None


ProjectThumbWorker.__module__ = _api.__name__
