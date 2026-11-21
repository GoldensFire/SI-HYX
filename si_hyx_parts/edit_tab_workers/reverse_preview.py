# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ReversePreviewWorker — фоновая сборка кэша reverse_preview/<hash>.mkv для
клипов проекта с реверсом. Public namespace: edit_tab_workers."""
import edit_tab_workers as _api


class ReversePreviewWorker(_api.QThread):
    """Собирает кэш реверс-превью для видеоклипов с reverse=True чанками по 4 с
    (N → 0) и склейкой -f concat -c copy. По готовности каждого клипа шлёт
    clipReady, чтобы живой плеер и деки сразу подхватили полноразрешённый файл."""

    progress = _api.pyqtSignal(str)
    clipReady = _api.pyqtSignal(str)
    failed = _api.pyqtSignal(str)
    done = _api.pyqtSignal()

    def __init__(self, clips, parent=None):
        super().__init__(parent)
        self._clips = list(clips or [])
        self._stopped = False

    def stop(self):
        self._stopped = True

    def run(self):
        total = len(self._clips)
        for i, c in enumerate(self._clips):
            if self._stopped:
                break
            if _api.montage_project.reverse_preview_lookup(c) is not None:
                continue
            prefix = (f"реверс-превью ({i + 1}/{total}): " if total > 1
                      else "реверс-превью: ")
            self.progress.emit(f"{prefix}0%")
            try:
                path = _api.montage_project.build_reverse_preview(
                    c, ffmpeg=_api.FFMPEG, ffprobe=_api.FFPROBE,
                    stop_check=lambda: self._stopped,
                    on_progress=lambda pct, p=prefix: self.progress.emit(f"{p}{pct}%"))
            except Exception as e:  # noqa: BLE001
                if not self._stopped:
                    self.failed.emit(str(e))
                continue
            if not self._stopped and path:
                self.clipReady.emit(path)
        self.done.emit()


ReversePreviewWorker.__module__ = _api.__name__
_api.ReversePreviewWorker = ReversePreviewWorker
