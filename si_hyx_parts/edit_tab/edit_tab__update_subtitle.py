# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _update_subtitle. Public namespace: edit_tab."""
import edit_tab as _api


def _update_subtitle(self, pos_s):
    # Цель показа: сам холст (frame-режим) или окно-оверлей (overlay-режим).
    tgt = self.video_widget if self._subs_in_frame else self.sub_overlay
    if tgt is None or not hasattr(tgt, "set_subtitle_text"):
        return
    if self._sub_use_ass and self._ass is not None:
        try:
            w, h = tgt.subtitle_area_size()
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        try:
            self._ass.set_frame_size(w, h)
            arr, ax, ay, changed = self._ass.render(pos_s * 1000.0)
        except Exception:
            arr = None
            changed = True
        # libass говорит, изменилась ли картинка с прошлого рендера — если нет,
        # то, что уже на экране, всё ещё актуально: не гоняем QImage-копию и
        # перерисовку виджета впустую на каждый тик sync_ui (12.5 раз/сек).
        if not changed:
            return
        if arr is None:
            tgt.clear_subtitle()
        else:
            ih, iw = int(arr.shape[0]), int(arr.shape[1])
            qimg = _api.QImage(arr.data, iw, ih, iw * 4,
                          _api.QImage.Format.Format_RGBA8888_Premultiplied).copy()
            tgt.set_subtitle_image(qimg, ax, ay)
        return
    if self._sub_use_overlay:
        tgt.set_subtitle_text(self._subtitle_at(pos_s))

    # Субтитры выключены — ничего не рисуем (очистка уже сделана при смене
    # дорожки через _hide_sub_display), чтобы не дёргать перерисовку.

def _apply_active_tracks(self, *args):
    """tracksChanged: применяет выбор из комбобоксов, когда плеер обнаружил дорожки."""
    try:
        ai = self.cmb_audio.currentIndex()
        if ai is not None and ai >= 0:
            self.player.setActiveAudioTrack(ai)
    except Exception:
        pass
    try:
        si = self.cmb_subs.currentIndex()
        self.player.setActiveSubtitleTrack((si - 1) if si is not None else -1)
    except Exception:
        pass

# ── File loading ──────────────────────────────────────────────────────
def open_file(self):
    fname, _ = _api.QFileDialog.getOpenFileName(
        self, "Открыть медиа файл", "",
        "Медиа файлы (*.mp4 *.mkv *.mov *.avi *.mp3 *.aac *.wav *.flac "
        "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Все файлы (*)")
    if fname:
        self.load_file(fname)

def clear_file(self):
    """Убирает текущий файл и возвращает редактор в исходное «пустое»
        состояние (как при запуске без файла): останавливает плеер и фоновые
        воркеры, чистит временный proxy, сбрасывает инфо/волну/тайминги."""
    # Снимок для отмены «Очистить» через Ctrl+Z: файл + текущая обрезка.
    if self.filepath:
        self._cleared_snapshot = {
            'path': str(self.filepath),
            'in': self.current_in,
            'out': self.current_out,
        }
    # Останавливаем воспроизведение.
    try:
        self.player.stop()
    except Exception:
        pass
    # Воркер волны + его временный wav.
    if self.audio_worker and self.audio_worker.isRunning():
        self.audio_worker.stop(); self.audio_worker.wait()
    if self.audio_worker:
        try:
            if self.audio_worker.tmp_wav and _api.os.path.exists(self.audio_worker.tmp_wav):
                _api.os.remove(self.audio_worker.tmp_wav)
        except Exception:
            pass
        self.audio_worker = None
    # Воркер быстрого предпросмотра волны выделения (см. _start_waveform).
    if self._audio_partial_worker and self._audio_partial_worker.isRunning():
        self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
    if self._audio_partial_worker:
        try:
            if self._audio_partial_worker.tmp_wav and _api.os.path.exists(self._audio_partial_worker.tmp_wav):
                _api.os.remove(self._audio_partial_worker.tmp_wav)
        except Exception:
            pass
        self._audio_partial_worker = None
    # Proxy-воркер + его временный файл.
    if self.proxy_thread and self.proxy_thread.isRunning():
        self.proxy_thread.stop(); self.proxy_thread.wait()
    self.proxy_thread = None
    if self.tmp_proxy_file and _api.os.path.exists(self.tmp_proxy_file):
        try:
            _api.os.remove(self.tmp_proxy_file)
        except Exception:
            pass
    self.tmp_proxy_file = None
    self.is_proxy_active = False
    # Выгружаем источник из плеера.
    try:
        self.player.setSource(_api.QUrl())
    except Exception:
        pass
    # Очищаем последний кадр на холсте (frame-режим).
    if isinstance(self.video_widget, _api.VideoCanvas):
        self.video_widget.clear_frame()
    # …и отпускаем покадровый слой: буфер кадров прошлого файла больше не
    # нужен, а его ffmpeg нельзя оставлять работать по удалённому источнику.
    self._grid = _api.FrameGrid(0.0, 0.0)
    self._frame_idx = None
    if getattr(self, '_frames', None) is not None:
        self._frames.set_source(None)
    self._frames_src = None

    # Сбрасываем субтитры.
    self._stop_sub_extractor()
    self._stop_ass()
    self._sub_cues = []
    self._sub_use_overlay = False
    self._hide_sub_display()

    # Сбрасываем состояние.
    self.filepath = None
    self.actual_source_file = None
    self.duration = 0.0
    self.current_in = 0.0
    self.current_out = 0.0
    self.fps = None
    self.video_aspect = None
    self.video_stream_index = None
    self.audio_stream_index = None
    # Сбрасываем режим картинки и возвращаем подпись кнопки экспорта.
    if getattr(self, "is_still_image", False):
        try:
            self.btn_cut.setText("Обрезать")
            self.btn_cut.setIcon(_api.get_icon('fa5s.cut', color='#1e1e2e'))
        except Exception:
            pass
    self.is_still_image = False
    self.still_image_path = None
    # Снимаем пикселизацию вместе с очисткой файла.
    self._pixelize_active = False
    _pb = getattr(self, "btn_pixelize", None)
    if _pb is not None and _pb.isChecked():
        _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
    self._sync_pixelize_icon()
    # Наложенные картинки — тоже строго «на файл»: следующий клип начинается
    # без чужих слоёв (иначе экспорт молча вшил бы логотип с прошлого видео).
    self._clear_image_overlays()
    self.selected_audio_abs_index = None
    self._clear_external_audio()
    self._set_audio_disabled(False)
    self._audio_streams = []
    self._sub_streams = []
    self._audio_ext = []
    self._sub_ext = []
    self.selected_audio_ext_path = None
    self.selected_sub_ext_path = None
    self.undo_stack.clear(); self.redo_stack.clear()

    # Инфо-карточка → прочерки.
    for lbl in (self.lbl_duration, self.lbl_fps, self.lbl_vstream,
                self.lbl_astream, self.lbl_abitrate):
        lbl.setText("—")

    # Подпись файла → исходный «пустой» вид (пунктирная рамка).
    self.lbl_file.setText("Нет файла")
    self.lbl_file.setToolTip("")
    self.lbl_file.setStyleSheet(f"""
            color: {_api.C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {_api.C['surface2']};
            border: 1px dashed {_api.C['border2']};
            border-radius: 6px;
        """)

    # Плашка proxy / строка лога.
    self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
    try:
        self.log_label.setText(""); self.log_label.setVisible(False)
    except Exception:
        pass

    # Дорожки (с пустыми списками → «— нет —» / «Выкл»).
    self._populate_track_combos()
    self._update_media_buttons()
    self._update_audio_only_placeholder()

    # Поля IN/OUT + кадры + позиция плеера.
    self.in_time_edit.setText(_api.s_to_time(0.0))
    self.out_time_edit.setText(_api.s_to_time(0.0))
    self._set_frame_spins(0.0, 0.0)
    lbl_cur = getattr(self, "lbl_current_time", None)
    if lbl_cur is not None:
        lbl_cur.setText(_api.s_to_time(0.0))
    try:
        self.slider.blockSignals(True); self.slider.setValue(0); self.slider.blockSignals(False)
    except Exception:
        pass

    # Волна → пустое состояние с подсказкой «Перетащите видео…».
    self.waveform.set_data([], 0.0)
    self._update_total_time()
    self.update_selection_label()

def accept_dropped_paths(self, paths):
    """Бросок файла на заголовок вкладки «Монтаж» (см. main.eventFilter):
        грузим первый существующий файл в редактор, как обычный drop в окно."""
    for p in (paths or []):
        if p and _api.os.path.exists(p):
            self.load_file(p)
            break
