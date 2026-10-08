# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_WarmupWorker, InpaintWorker, BgRemoveWorker. Public namespace: photo_tab."""
import photo_tab as _api


class _WarmupWorker(_api.QThread):
    """Фоновый прогрев сессии ONNX (загрузка 200-МБ модели ~10 с), чтобы первый
    клик «Удалить» не ждал инициализацию."""
    done = _api.pyqtSignal(str)
    failed = _api.pyqtSignal(str)

    def __init__(self, inpainter):
        super().__init__()
        self._inp = inpainter

    def run(self):
        try:
            self.done.emit(self._inp.warmup())
        except Exception as e:        # pragma: no cover
            import traceback; traceback.print_exc()
            self.failed.emit(str(e))

_WarmupWorker.__module__ = _api.__name__
_api._WarmupWorker = _WarmupWorker


class InpaintWorker(_api.QThread):
    """Фоновый инференс LaMa — UI не виснет на время обработки."""
    done = _api.pyqtSignal(object)
    failed = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int)

    def __init__(self, inpainter, img_bgr, mask):
        super().__init__()
        self._inp = inpainter
        self._img = img_bgr
        self._mask = mask

    def run(self):
        try:
            res = self._inp.inpaint(
                self._img, self._mask,
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(res)
        except Exception as e:
            # Отмена пользователем (ModelCancelled) — не авария: сигнал шлём,
            # но консоль пугающим traceback'ом не засоряем.
            if not getattr(e, "cancelled", False):
                import traceback; traceback.print_exc()
            self.failed.emit(str(e))

InpaintWorker.__module__ = _api.__name__
_api.InpaintWorker = InpaintWorker


class BgRemoveWorker(_api.QThread):
    """Фоновое удаление фона (RMBG-2.0) — UI не виснет на инференсе/загрузке модели."""
    done = _api.pyqtSignal(object)
    failed = _api.pyqtSignal(str)
    progress = _api.pyqtSignal(int, int)

    def __init__(self, remover, img_bgr):
        super().__init__()
        self._rem = remover
        self._img = img_bgr

    def run(self):
        try:
            alpha = self._rem.remove(
                self._img,
                progress=lambda d, t: self.progress.emit(int(d), int(t)))
            self.done.emit(alpha)
        except Exception as e:
            # Отмена пользователем (ModelCancelled) — не авария: сигнал шлём,
            # но консоль пугающим traceback'ом не засоряем.
            if not getattr(e, "cancelled", False):
                import traceback; traceback.print_exc()
            self.failed.emit(str(e))

BgRemoveWorker.__module__ = _api.__name__
_api.BgRemoveWorker = BgRemoveWorker
