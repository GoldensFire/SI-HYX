# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""InpaintTab: _remove_bg. Public namespace: photo_tab."""
import photo_tab as _api


def _remove_bg(self):
    self._touch()
    if not self.canvas.has_image():
        return
    if not _api._HAS_RMBG or self._remover is None:
        _api.msgbox_warning(
            self, "Удаление фона недоступно",
            "Нужна модель models/model_uint8.onnx и пакет onnxruntime.\n\n"
            "Установка onnxruntime:  pip install onnxruntime")
        return
    if (self._worker is not None and self._worker.isRunning()) or \
       (self._bg_worker is not None and self._bg_worker.isRunning()):
        return
    self._cancelling = False        # новый запуск — снимаем возможный флаг отмены
    # Вжигаем плавающий слой и мазки кисти, снимок «до» — для Ctrl+Z.
    self.canvas.commit_pending()
    # Незавершённое кадрирование применяем перед удалением фона (иначе рамка
    # кадрирования пропадала, а фон убирался с полного изображения).
    if self.canvas.has_crop():
        self.canvas.apply_crop()
    self.canvas._push_history()
    self.canvas.bake_paint()
    img = self.canvas.img_bgr
    self._set_status(_api.status_html(
        'fa5s.spinner',
        "Удаляю фон нейросетью… (первый запуск дольше — грузится модель ~360 МБ)",
        '#89b4fa'))
    self.setCursor(_api.Qt.CursorShape.WaitCursor)
    self._show_proc_chip(None, label="Удаляю фон…", icon='fa5s.cut')
    self._bg_worker = _api.BgRemoveWorker(self._remover, img)
    self._bg_worker.done.connect(self._on_bg_done)
    self._bg_worker.failed.connect(self._on_bg_failed)
    self._bg_worker.start()
    self._refresh_enabled()

def _on_bg_done(self, alpha):
    # Отменено во время инференса — фон уже не убираем (UI в «Отменено»).
    if getattr(self, "_cancelling", False):
        self._cancelling = False
        self._bg_worker = None
        self._hide_proc_chip()
        self.unsetCursor()
        self._refresh_enabled()
        return
    # Историю уже сохранили перед запуском — применяем без повторного пуша.
    self.canvas.apply_cutout(alpha)
    self._finish_proc()
    self._hide_proc_chip()
    self.unsetCursor()
    try:
        self._device = self._remover.device_label
        self.lbl_device.setText(f"Устройство: {self._device}")
    except Exception:
        pass
    self._set_status(_api.status_html('fa5s.check-circle',
                     "Готово! Фон удалён — сохраняйте в PNG.", '#a6e3a1'))
    self._bg_worker = None
    self._refresh_enabled()
    try: _api.play_done_sound()
    except Exception: pass

def _on_bg_failed(self, err):
    self._hide_proc_chip()
    self.unsetCursor()
    self._bg_worker = None
    self._refresh_enabled()
    if getattr(self, "_cancelling", False):
        self._cancelling = False
        self._set_status(_api.status_html('fa5s.ban', "Отменено пользователем.", '#f9e2af'))
        return
    self._set_status(_api.status_html('fa5s.times-circle', f"Ошибка: {err}", '#f38ba8'))
    _api.msgbox_warning(self, "Ошибка удаления фона", str(err))
