# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _on_track_path_ready. Public namespace: edit_tab."""
import edit_tab as _api


def _on_track_path_ready(self, boxes):
    """Путь объекта посчитан — показываем накладку прямо в плеере. Ничего
        никуда не записано: в файл накладка попадёт обычным экспортом, то есть
        кнопкой «Обрезать» (см. start_cut)."""
    self._finish_track_overlay()
    spec = getattr(self, "_trk_spec", None)
    if not spec or not boxes:
        return
    spec["boxes"] = boxes
    canvas = self.video_widget
    if not isinstance(canvas, _api.VideoCanvas):
        # Классический QVideoWidget не умеет рисовать поверх кадра — там
        # предпросмотра нет, сразу рендерим (как раньше).
        self._render_track_overlay()
        return

    from photo_tab import np_bgra_to_qimage
    qimg = np_bgra_to_qimage(spec["overlay_bgra"])
    canvas.set_track_preview({
        "overlay": qimg, "boxes": boxes,
        "src_w": spec["src_w"], "src_h": spec["src_h"], "fps": spec["fps"],
        "start_s": spec["start_s"], "end_s": spec["end_s"],
        "anchor": spec["anchor"], "off": (spec["off_x"], spec["off_y"]),
        "scale_with_box": spec["scale_with_box"],
    })
    canvas.set_track_time(max(0.0, self._ui_time_s()))
    self._connect_track_preview_signals(canvas)
    self._set_cut_status("Накладка привязана — сохранит её «Обрезать»",
                         icon='fa5s.crosshairs')
    self.log_label.setText(
        "Смотрите, как накладка едет за объектом. «Обрезать» сохранит видео "
        "с накладкой, кнопка привязки — уберёт её.")

def _connect_track_preview_signals(self, canvas):
    """Подключает сигналы предпросмотра ровно один раз на КАЖДЫЙ холст (при
        смене способа показа видео в настройках виджет пересоздаётся)."""
    if getattr(self, "_trk_signals_canvas", None) is canvas:
        return
    canvas.trackCancelled.connect(self._clear_track_preview)
    self._trk_signals_canvas = canvas

def has_track_preview(self):
    """Есть ли посчитанная накладка, ждущая экспорта («Обрезать»)."""
    spec = getattr(self, "_trk_spec", None)
    return bool(spec and spec.get("boxes"))

def _clear_track_preview(self):
    """Убирает накладку из плеера (Esc, повторное нажатие кнопки привязки,
        новый файл)."""
    canvas = getattr(self, "video_widget", None)
    if isinstance(canvas, _api.VideoCanvas) and canvas.has_track_preview():
        canvas.set_track_preview(None)
        self._set_cut_status("")
        self.log_label.setText("Готово")
    self._trk_spec = None

def _render_track_overlay(self, trim_in=None, trim_out=None):
    """Экспорт видео с накладкой по УЖЕ посчитанной траектории (отслеживать
        заново нечего, этап только кодирующий). trim_in/trim_out — выделенный в
        Монтаже отрезок: «Обрезать» с активной накладкой и режет, и вшивает."""
    spec = getattr(self, "_trk_spec", None)
    if not spec or getattr(self, "_trk_running", False):
        return
    src = spec["src"]
    if not _api.os.path.exists(src):
        return
    base = _api.Path(src)
    out_dir = (_api.Path(self.export_dir)
               if (self.export_dir and _api.os.path.isdir(self.export_dir))
               else base.parent)
    suffix = base.suffix.lower()
    if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
        suffix = ".mp4"
    out_path = str(out_dir / f"{base.stem}_привязка{suffix}")
    if _api.os.path.exists(out_path):
        out_path = _api._unique_output(out_path)

    # Пункт «Нет» в списке дорожек — результат без звука.
    has_audio = (getattr(self, "audio_stream_index", None) is not None
                 and not bool(getattr(self, "audio_disabled", False)))
    # hardsub-профиль: у текста и краёв картинки резкие границы, на «fast»/
    # высоком CRF они мылятся — берём тот же профиль, что при вшивании субтитров.
    venc = self._video_encoder_args(hardsub=True)
    # Экспорт накладки идёт своим путём (кадры собираются в python), поэтому
    # фильтры обычной обрезки к нему не применяются — честно предупреждаем,
    # а не делаем вид, что кадрирование/пикселизация учтены.
    if (self._video_crop_filter() is not None
            or getattr(self, "_pixelize_active", False)):
        _api.msgbox_information(
            self, "Только накладка",
            "Сейчас в файл уйдёт видео с привязанной накладкой — "
            "кадрирование и пикселизация в этот экспорт не попадут. "
            "Сначала сохраните их обычной обрезкой, а привязку сделайте "
            "уже по готовому файлу.")

    self._trk_running = True
    self._set_track_export_busy(True)
    self._report_progress(-1, "Привязка к объекту…")
    self._set_cut_status("Привязка к объекту… подготовка",
                         icon='fa5s.hourglass-half')
    self.log_label.setText("Наложение на кадры…")

    self._trk_worker = _api.TrackOverlayWorker(
        src, out_path, venc, has_audio, spec["fps"],
        (spec["src_w"], spec["src_h"]), float(self.duration),
        spec["box"], spec["start_s"], spec["end_s"], spec["overlay_bgra"],
        anchor=spec["anchor"], off_x=spec["off_x"], off_y=spec["off_y"],
        scale_with_box=spec["scale_with_box"], smooth=spec["smooth"],
        boxes=spec.get("boxes"), trim_in=trim_in, trim_out=trim_out,
        static_overlays=self._static_overlays_bgra(spec["src_w"],
                                                   spec["src_h"]))
    self._trk_worker.progress.connect(self._on_trk_progress)
    self._trk_worker.done.connect(self._on_trk_done)
    self._trk_worker.failed.connect(self._on_trk_failed)
    self._trk_worker.start()

def _cancel_track_overlay(self):
    """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
    w = getattr(self, "_trk_worker", None)
    if w is not None and w.isRunning():
        self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
        if getattr(self, "btn_track_object", None) is not None:
            self.btn_track_object.setEnabled(False)
        w.cancel()

def _on_trk_progress(self, pct, text):
    self._report_progress(pct, text)
    self._set_cut_status(text, icon='fa5s.crosshairs' if pct >= 0
                         else 'fa5s.hourglass-half')

def _set_track_export_busy(self, busy):
    """На время отслеживания/рендера «Обрезать» превращается в «Отмена» (как
        при обычном экспорте), а кнопка привязки выключается."""
    b = getattr(self, "btn_track_object", None)
    if b is not None:
        b.setEnabled(not busy)
    self._set_cut_btn_cancel(busy, self._cancel_track_overlay)

def _finish_track_overlay(self):
    self._trk_running = False
    self._trk_worker = None
    self._set_track_export_busy(False)
    self._update_media_buttons()

def _on_trk_done(self, final_path):
    self._finish_track_overlay()
    # Файл готов — накладка-предпросмотр больше не нужна.
    self._clear_track_preview()
    try:
        if self.main is not None and hasattr(self.main, "log"):
            self.main.log(f"Накладка привязана к объекту: {final_path}")
    except Exception:
        pass
    self._progress_result_path = final_path
    self.on_ffmpeg_finished(True, "Готово")

def _on_trk_failed(self, message):
    self._finish_track_overlay()
    self.on_ffmpeg_finished(False, message)

# ── Удаление исходного файла ─────────────────────────────────────────────
def delete_source_file(self):
    """Удаляет загруженный исходный файл с диска (с подтверждением). Перед
        удалением освобождает файл (останавливает плеер и снимает источник),
        иначе Windows не даст удалить открытый файл."""
    src = self.actual_source_file or self.filepath
    if not src or not _api.os.path.exists(str(src)):
        return
    src = str(src)
    name = _api.os.path.basename(src)
    reply = _api.msgbox_question(
        self, "Удалить исходный файл?",
        "Файл будет удалён с диска без возможности восстановления:\n\n"
        f"{name}\n\nПродолжить?",
        _api.QMessageBox.StandardButton.Yes | _api.QMessageBox.StandardButton.No,
        _api.QMessageBox.StandardButton.No)
    if reply != _api.QMessageBox.StandardButton.Yes:
        return
    # Останавливаем фоновую сборку прокси (если идёт): иначе её ffmpeg будет
    # держать temp-файл, а finished-слот выстрелит уже после очистки. Сам слот
    # дополнительно защищён проверкой actual_source_file is None.
    try:
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
    except Exception: pass
    self.proxy_thread = None
    # Освобождаем файл: останавливаем воспроизведение и снимаем источник.
    try: self.player.stop()
    except Exception: pass
    try: self.player.setSource(_api.QUrl())
    except Exception: pass
    try:
        if getattr(self, "seek_preview", None) is not None:
            self.seek_preview.set_source(None)
    except Exception: pass
    try: _api.QApplication.processEvents()
    except Exception: pass
    try:
        _api.os.remove(src)
    except Exception as e:
        _api.msgbox_critical(self, "Ошибка", f"Не удалось удалить файл:\n{e}")
        return
    # Сбрасываем состояние редактора (файл больше не загружен).
    self.actual_source_file = None
    self.filepath = None
    self.duration = 0.0
    try:
        if hasattr(self.video_widget, "clear_frame"):
            self.video_widget.clear_frame()
    except Exception: pass
    try: self.waveform.set_data([], 0.0)
    except Exception: pass
    try: self._update_media_buttons()
    except Exception: pass
    try:
        if self.main is not None and hasattr(self.main, "log"):
            self.main.log(f"🗑 Исходный файл удалён: {name}")
    except Exception: pass

# ── Полноэкранный режим ─────────────────────────────────────────────────
def toggle_fullscreen(self):
    if getattr(self, "_fs_window", None) is not None:
        self.exit_fullscreen()
    else:
        self.enter_fullscreen()

def enter_fullscreen(self):
    if getattr(self, "_fs_window", None) is not None:
        return
    if self.duration <= 0.1:   # нет загруженного видео
        return
    try:
        fs = _api.FullscreenVideo(self)
        # fs — самостоятельное окно без родителя (иначе showFullScreen на
        # дочернем виджете ведёт себя иначе), поэтому Qt может открыть его
        # fullscreen'ом на ПЕРВИЧНОМ мониторе, даже если само приложение
        # (и мышь пользователя) сейчас на другом. Явно ставим тот же экран,
        # где сейчас окно приложения — заодно фиксирует QScreen ДО первого
        # show(), от чего зависит и корректный клэмп tooltip'ов панели
        # управления (см. FullscreenVideo._relayout).
        try:
            src_screen = self.window().windowHandle().screen()
        except Exception:
            src_screen = None
        if src_screen is not None:
            fs.winId()   # форсирует создание нативного хэндла ДО setScreen
            wh = fs.windowHandle()
            if wh is not None:
                wh.setScreen(src_screen)
        # Снимаем фиксированные размеры с видео и переносим его в окно.
        self.video_widget.setMinimumSize(0, 0)
        self.video_widget.setMaximumSize(16777215, 16777215)
        fs.attach_video(self.video_widget)
        self._fs_window = fs
        self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=False))
        self.btn_fullscreen.setToolTip("Свернуть (Esc / двойной клик по видео)")
        fs.showFullScreen()
        # Без этого клавиши (F/Esc/Space/стрелки) не доходили до окна: после
        # showFullScreen() фокус клавиатуры мог оставаться на виджете, у
        # которого он был ДО входа в полноэкранный режим (например, на
        # волне/поле ссылки в основном окне) — F там ничего не делал.
        fs.activateWindow()
        fs.setFocus(_api.Qt.FocusReason.OtherFocusReason)
        fs.sync_from_player()
        fs.sync_volume()
        fs.update_play_icon(
            self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState)
        # Холст переехал в другое окно, а с ним и его сцена Qt Quick:
        # графический контекст пересоздан, и показанный кадр в нём не
        # переживает переезд. На паузе кадров от плеера больше не будет —
        # ставим точный кадр заново (на воспроизведении метод сам ничего не
        # делает: там следующий кадр приедет через ~16 мс).
        _api.QTimer.singleShot(0, self._restore_canvas_frame)
        try:
            self._update_subtitle(self._ui_time_s())
            _api.QTimer.singleShot(0, self._position_overlay)
        except Exception:
            pass
    except Exception as e:
        self.main.log(f"enter_fullscreen error: {e}")
        self._fs_window = None
