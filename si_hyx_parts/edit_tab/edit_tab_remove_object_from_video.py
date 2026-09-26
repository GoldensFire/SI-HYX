# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: remove_object_from_video. Public namespace: edit_tab."""
import edit_tab as _api


def remove_object_from_video(self):
    """Удаляет объект (водяной знак/эмодзи/логотип) со ВСЕГО видео: пользователь
        закрашивает объект кистью на текущем кадре, затем ТЕМ ЖЕ движком LaMa, что и
        в фоторедакторе, объект убирается с каждого кадра, и видео собирается
        обратно с исходными FPS/разрешением/ориентацией/аудио. Тяжёлая работа — в
        отдельном потоке (VideoInpaintWorker) с возможностью отмены.

        Поведение для одиночного изображения НЕ меняется: эта кнопка активна только
        при загруженном видео (см. _update_media_buttons)."""
    # Пока идёт обработка — кнопка работает как «Отмена».
    if getattr(self, "_vinp_running", False):
        self._cancel_video_inpaint()
        return

    src = self.actual_source_file or self.filepath
    if not src or not _api.os.path.exists(str(src)) or self.duration <= 0:
        return
    if getattr(self, "video_stream_index", None) is None:
        _api.msgbox_information(
            self, "Только для видео",
            "Удаление объекта доступно для видео. Для одиночного изображения "
            "используйте вкладку «Фото».")
        return
    src = str(src)

    # Доступность движка LaMa (numpy/opencv/модель).
    inp = self._ensure_inpainter()
    if inp is None or not inp.is_available():
        _api.msgbox_warning(
            self, "Удаление объекта недоступно",
            "Не найдены необходимые компоненты (numpy/opencv или файл модели "
            "LaMa). Удаление объекта с видео недоступно в этой сборке.")
        return

    # Кадр для рисования маски — из оригинала на текущей позиции, полный размер.
    frame = self._grab_source_frame_bgr(src)
    if frame is None:
        _api.msgbox_warning(
            self, "Ошибка",
            "Не удалось получить кадр видео для рисования маски.")
        return

    dlg = _api._VideoMaskDialog(frame, self)
    if dlg.exec() != _api.QDialog.DialogCode.Accepted:
        return
    mask = dlg.get_mask()
    if mask is None or int(mask.max()) == 0:
        return

    # Имя результата — в папке сохранения/рядом с исходником; контейнер
    # исходника, если он поддерживает H.264, иначе .mp4 (h264 в webm недопустим).
    base = _api.Path(src)
    out_dir = (_api.Path(self.export_dir)
               if (self.export_dir and _api.os.path.isdir(self.export_dir))
               else base.parent)
    suffix = base.suffix.lower()
    if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
        suffix = ".mp4"
    out_path = str(out_dir / f"{base.stem}_без_объекта{suffix}")
    if _api.os.path.exists(out_path):
        out_path = _api._unique_output(out_path)

    # Пункт «Нет» в списке дорожек — результат без звука.
    has_audio = (getattr(self, "audio_stream_index", None) is not None
                 and not bool(getattr(self, "audio_disabled", False)))
    venc = self._video_encoder_args(hardsub=False)

    # Запуск фоновой обработки + перевод кнопки в режим «Отмена».
    self._vinp_running = True
    self.btn_cut.setEnabled(False)
    self._set_remove_btn_cancel(True)
    self._report_progress(-1, "Удаление объекта…")
    self._set_cut_status("Удаление объекта… подготовка",
                         icon='fa5s.hourglass-half')
    self.log_label.setText("Удаление объекта с видео…")

    self._vinp_worker = _api.VideoInpaintWorker(
        inp, src, mask, self.fps, out_path, venc, has_audio)
    self._vinp_worker.progress.connect(self._on_vinp_progress)
    self._vinp_worker.done.connect(self._on_vinp_done)
    self._vinp_worker.failed.connect(self._on_vinp_failed)
    self._vinp_worker.start()

def _set_remove_btn_cancel(self, cancel_mode):
    """Переключает кнопку «Удалить объект» между обычным видом и «Отмена» на
        время обработки видео."""
    b = getattr(self, "btn_remove_object", None)
    if b is None:
        return
    if cancel_mode:
        b.setIcon(_api.get_icon('fa5s.times'))
        b.setToolTip("Отменить удаление объекта")
        b.setEnabled(True)
    else:
        b.setIcon(_api.get_icon('fa5s.magic'))
        b.setToolTip(
            "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте "
            "его кистью на кадре — нейросеть LaMa уберёт его со всех кадров")

def _set_cut_btn_cancel(self, cancel_mode, cancel_handler=None):
    """Переключает btn_cut («Обрезать») между обычным видом и «Отмена» на
        время перекодировки/обрезки — тот же приём, что _set_remove_btn_cancel
        для «Удалить объект», но с сохранением исходных текста/иконки/стиля:
        у btn_cut они меняются по режиму («Обрезать» / «Создать видео» для
        картинки), и вернуть нужно РОВНО то, что было до переключения."""
    b = self.btn_cut
    try:
        b.clicked.disconnect()
    except Exception:
        pass
    if cancel_mode:
        self._cut_btn_saved = (b.text(), b.icon(), b.styleSheet())
        b.setText("Отмена")
        b.setIcon(_api.get_icon('fa5s.times', color='#1e1e2e'))
        b.setStyleSheet(f"""
                QPushButton {{
                    background: {_api.C['red']};
                    color: #1e1e2e;
                    border: none;
                    border-radius: 6px;
                    padding: 9px 24px;
                    font-weight: 700;
                    font-size: 13px;
                    letter-spacing: 0.3px;
                }}
                QPushButton:hover {{ background: {_api.C['red2']}; }}
                QPushButton:pressed {{ background: {_api.C['red2']}; }}
                QPushButton:disabled {{ background: {_api.C['surface3']}; color: {_api.C['text3']}; }}
            """)
        b.setEnabled(True)
        b.clicked.connect(cancel_handler or self._cancel_cut)
    else:
        saved = getattr(self, '_cut_btn_saved', None)
        if saved:
            b.setText(saved[0]); b.setIcon(saved[1]); b.setStyleSheet(saved[2])
        b.setEnabled(True)
        b.clicked.connect(self.start_cut)

def _cancel_cut(self):
    """Отменяет текущую обрезку/перекодировку/Smart Cut (self.ffmpeg_thread)."""
    th = getattr(self, "ffmpeg_thread", None)
    if th is not None and th.isRunning():
        self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
        self.btn_cut.setEnabled(False)
        th.stop()

def _cancel_cut_and_process(self, tab_media):
    """Отменяет «Обрезать и обработать» (worker вкладки «Обработка»)."""
    w = getattr(tab_media, 'worker', None)
    if w is not None and w.isRunning():
        self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
        self.btn_cut.setEnabled(False)
        w.stop()

def _cancel_video_inpaint(self):
    """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
    w = getattr(self, "_vinp_worker", None)
    if w is not None and w.isRunning():
        self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
        if getattr(self, "btn_remove_object", None) is not None:
            self.btn_remove_object.setEnabled(False)
        w.cancel()

def _on_vinp_progress(self, pct, text):
    self._report_progress(pct, text)
    self._set_cut_status(text, icon='fa5s.magic' if pct >= 0
                         else 'fa5s.hourglass-half')

def _finish_video_inpaint(self):
    """Общая уборка состояния UI после завершения/отмены/ошибки обработки."""
    self._vinp_running = False
    self._vinp_worker = None
    self._set_remove_btn_cancel(False)
    self.btn_cut.setEnabled(True)
    self._update_media_buttons()

def _on_vinp_done(self, final_path):
    self._finish_video_inpaint()
    try:
        if self.main is not None and hasattr(self.main, "log"):
            self.main.log(f"Объект удалён с видео: {final_path}")
    except Exception:
        pass
    # Переиспользуем стандартное завершение «Монтажа» (статус «Готово»,
    # обновление верхней ленты файлов и т.п.).
    self._progress_result_path = final_path
    self.on_ffmpeg_finished(True, "Готово")

def _on_vinp_failed(self, message):
    self._finish_video_inpaint()
    self.on_ffmpeg_finished(False, message)

# ── Привязка текста/картинки к движущемуся объекту ───────────────────────
def track_object_overlay(self):
    """Привязывает текст или картинку к ДВИЖУЩЕМУСЯ объекту: пользователь
        обводит объект рамкой на текущем кадре, трекер DyHiT (нейросеть, ONNX;
        без модели — запасной CSRT из OpenCV) находит его на каждом следующем
        кадре, и накладка едет вместе с ним. Результат — новый файл; исходник не
        трогаем. Вся тяжёлая работа в TrackOverlayWorker, с отменой.

        Доступно только для видео: у одиночной картинки нечему двигаться."""
    # Пока идёт обработка — кнопка работает как «Отмена».
    if getattr(self, "_trk_running", False):
        self._cancel_track_overlay()
        return
    # Накладка уже висит в плеере — второе нажатие её снимает (отдельной
    # кнопки «Отмена» на холсте нет, экспортом занимается «Обрезать»).
    if self.has_track_preview():
        self._clear_track_preview()
        return
    self._clear_track_preview()

    src = self.actual_source_file or self.filepath
    if not src or not _api.os.path.exists(str(src)) or self.duration <= 0:
        return
    if getattr(self, "video_stream_index", None) is None:
        _api.msgbox_information(
            self, "Только для видео",
            "Привязка к объекту работает с видео: нужно движение, за которым "
            "можно следить.")
        return
    src = str(src)

    try:
        import dyhit_tracker
    except Exception as e:
        _api.msgbox_warning(
            self, "Отслеживание недоступно",
            f"Не удалось загрузить движок отслеживания (нужны numpy/opencv):\n{e}")
        return
    if not (dyhit_tracker.dyhit_available()
            or dyhit_tracker.opencv_tracker_available()):
        _api.msgbox_warning(
            self, "Отслеживание недоступно",
            "Не найден ни один трекер. Для нейросетевого варианта положите "
            "файл модели DyHiT/HiT (.onnx) в папку models — ожидается "
            f"{dyhit_tracker.expected_model_path()} — либо установите "
            "opencv-python с трекерами (CSRT).")
        return

    # Кадр для выбора области — из оригинала на текущей позиции, полный размер
    # (тот же способ, что у маски удаления объекта, поэтому рамка попадает в
    # кадры воркера попиксельно).
    frame = self._grab_source_frame_bgr(src)
    if frame is None:
        _api.msgbox_warning(self, "Ошибка",
                       "Не удалось получить кадр видео для выбора объекта.")
        return

    fps = float(self.fps) if getattr(self, "fps", None) else 25.0
    pos = max(0.0, self._ui_time_s())
    start_s = max(0.0, pos - 0.5 / fps)
    zone_end = float(self.current_out) if getattr(self, "current_out", 0) else 0.0

    dlg = _api._TrackAttachDialog(frame, self, start_s=start_s,
                             end_s=float(self.duration), zone_end_s=zone_end)
    if dlg.exec() != _api.QDialog.DialogCode.Accepted:
        return
    spec = dlg.values()
    if not spec.get("box") or spec.get("overlay_bgra") is None:
        return

    h, w = frame.shape[:2]
    self._trk_spec = dict(spec)
    self._trk_spec.update({"src": src, "fps": fps, "src_w": w, "src_h": h})

    # Шаг 1 — только путь объекта, без кодирования: он считается в разы
    # быстрее полного рендера, и по нему сразу показываем предпросмотр.
    self._trk_running = True
    self._set_track_export_busy(True)
    self._report_progress(-1, "Привязка к объекту…")
    self._set_cut_status("Привязка к объекту… подготовка",
                         icon='fa5s.hourglass-half')
    self.log_label.setText("Отслеживание объекта на видео…")

    self._trk_worker = _api.TrackPathWorker(
        src, fps, (w, h), spec["box"], spec["start_s"], spec["end_s"],
        smooth=spec["smooth"])
    self._trk_worker.progress.connect(self._on_trk_progress)
    self._trk_worker.done.connect(self._on_track_path_ready)
    self._trk_worker.failed.connect(self._on_trk_failed)
    self._trk_worker.start()
