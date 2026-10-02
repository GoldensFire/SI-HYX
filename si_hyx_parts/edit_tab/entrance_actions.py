# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Меню дополнительных действий и экспорт появления в монтаже."""
import edit_tab as _api
from .entrance_dialog import EntranceDialog
from .entrance_worker import EntranceWorker


def _build_more_actions(self):
    self.btn_more_actions = _api.make_icon_btn("")
    self.btn_more_actions.setIcon(_api.get_icon("fa5s.ellipsis-h"))
    self.btn_more_actions.setIconSize(_api.QSize(18, 18))
    self.btn_more_actions.setStyleSheet(self.btn_more_actions.styleSheet()
                                      + "\nQPushButton::menu-indicator { image: none; width: 0px; }")
    self._relax_width(self.btn_more_actions)
    self.btn_more_actions.setToolTip("Дополнительно: появление, удаление исходного файла")
    self.more_actions_menu = _api.QMenu(self.btn_more_actions)
    self.action_entrance = self.more_actions_menu.addAction(
        _api.get_icon("fa5s.magic"), "Появление")
    self.action_entrance.triggered.connect(self.create_entrance)
    self.more_actions_menu.addSeparator()
    self.action_delete_source = self.more_actions_menu.addAction(
        _api.get_icon("fa5s.trash-alt"), "Удалить исходный файл")
    self.action_delete_source.triggered.connect(self.delete_source_file)
    self.more_actions_menu.aboutToShow.connect(self._refresh_more_actions)
    self.btn_more_actions.setMenu(self.more_actions_menu)
    self._refresh_more_actions()


def _entrance_busy(self):
    if any(getattr(self, attr, False) for attr in
           ("_entrance_running", "_vinp_running", "_trk_running")):
        return True
    worker = getattr(self, "ffmpeg_thread", None)
    return worker is not None and worker.isRunning()


def _refresh_more_actions(self):
    source = getattr(self, "actual_source_file", None) or getattr(self, "filepath", None)
    has_file = bool(source) and _api.os.path.isfile(str(source))
    visual = (bool(getattr(self, "is_still_image", False))
              or (getattr(self, "video_stream_index", None) is not None
                  and getattr(self, "duration", 0) > 0.1))
    busy = self._entrance_busy()
    self.btn_more_actions.setEnabled(has_file and not busy)
    self.action_delete_source.setEnabled(has_file and not busy)
    self.action_entrance.setEnabled(has_file and visual and not busy)


def create_entrance(self):
    self._refresh_more_actions()
    if not self.action_entrance.isEnabled():
        return
    source = str(self.actual_source_file or self.filepath)
    is_image = bool(getattr(self, "is_still_image", False))
    dialog = EntranceDialog(self, source, is_image)
    try:
        if dialog.exec() != _api.QDialog.DialogCode.Accepted:
            return
        options = dialog.options()
    finally:
        dialog.entrance_preview.timer.stop()
        dialog.deleteLater()
    output = _api._unique_output(str(_api.Path(source).with_name(
        _api.Path(source).stem + " — появление.mp4")))
    self._entrance_worker = worker = EntranceWorker(source, output, is_image, options)
    worker.setParent(self)
    worker.done.connect(self._on_entrance_done)
    worker.failed.connect(self._on_entrance_failed)
    worker.finished.connect(worker.deleteLater)
    self._entrance_running = True
    self._set_cut_btn_cancel(True, self._cancel_entrance)
    self._update_media_buttons()
    self._report_progress(-1, "Создание видео появления…")
    self._set_cut_status("Создание видео появления…", icon="fa5s.hourglass-half")
    self.log_label.setText("Создание видео появления…")
    worker.start()


def _cancel_entrance(self):
    worker = getattr(self, "_entrance_worker", None)
    if worker is not None:
        self.btn_cut.setEnabled(False)
        self._set_cut_status("Отмена…", icon="fa5s.hourglass-half")
        worker.stop()


def _finish_entrance(self):
    self._entrance_running = False
    self._entrance_worker = None
    self._set_cut_btn_cancel(False)
    self._update_media_buttons()


def _on_entrance_done(self, output):
    self._finish_entrance()
    self._progress_result_path = output
    self.on_ffmpeg_finished(True, "Готово")


def _on_entrance_failed(self, message):
    self._finish_entrance()
    if message == "Отменено":
        self.on_ffmpeg_finished(False, message)
        return
    self.log_label.setText("Ошибка создания видео появления")
    self._report_progress(0, "Ошибка")
    self._clear_cut_status()
    _api.msgbox_critical(self, "Появление", f"Не удалось создать видео:\n{message}")
