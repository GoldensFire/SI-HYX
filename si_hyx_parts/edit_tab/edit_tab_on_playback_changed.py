# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: on_playback_changed. Public namespace: edit_tab."""
import edit_tab as _api


def on_playback_changed(self, state):
    # Во время покадрового скраба play→pause транзиентны — не трогаем кнопку,
    # чтобы иконка/текст не дёргались (меняются только по явному действию).
    # То же во время беззвучного прогрева аудио (_preroll_at): кнопка/иконка
    # и внешняя озвучка не должны мигать на транзиентный play→pause.
    if self._scrubbing or getattr(self, "_prerolling", False):
        return
    playing = (state == _api.QMediaPlayer.PlaybackState.PlayingState)
    # Сигнал приходит с задержкой: «играю» могло прилететь уже ПОСЛЕ того,
    # как прогрев остановил плеер. Верим текущему состоянию, а не почтальону:
    # иначе устаревший сигнал снимал пин с холста и отпускал буфер кадров —
    # картинка уезжала с кадра, на котором стоял монтаж.
    try:
        if playing and (self.player.playbackState()
                        != _api.QMediaPlayer.PlaybackState.PlayingState):
            return
    except Exception:
        pass
    # Painted-режим: во время игры ресайзим кадр быстрым методом (экономим ЦП).
    vw = getattr(self, "video_widget", None)
    if isinstance(vw, _api.VideoCanvas):
        vw.set_playing(playing)
    # Покадровый слой: во время игры главные — кадры плеера (пин снят,
    # предекодер молчит); на паузе, наоборот, пришпиливаем к холсту точный
    # кадр остановки и греем соседей — тогда первый же шаг стрелкой
    # мгновенный и ровно тем кадром, что просили.
    if playing:
        # Исключение — «передача» разбега (см. toggle_play): пока доигрывается
        # немой остаток до отметки, пин точного кадра ОБЯЗАН держаться, иначе
        # на экране мелькнёт кусочек до отметки. Снимет его
        # _preroll_handoff_finish ровно на цели.
        if not getattr(self, "_preroll_handoff", False):
            self._release_frame_lock()
    elif self._grid.valid and self.video_stream_index is not None:
        # Сбрасываем ПЕРЕД вычислением: иначе _current_frame_index вернул бы
        # прежний номер (он на паузе доверяет _frame_idx), а нам нужен кадр,
        # на котором воспроизведение реально остановилось.
        self._frame_idx = None
        self._frame_idx = self._current_frame_index()
        self._show_exact_frame(self._frame_idx)
        # Плейхед — сразу на кадр остановки. Без этого интерфейс до первого
        # следующего события жил по позиции плеера (аудио-часы), и жёлтая
        # полоса после паузы успевала уехать вперёд, а потом вернуться назад,
        # когда из предекодера приезжал точный кадр.
        stop_s = self._grid.start_of(self._frame_idx)
        self._paint_playhead(stop_s)
        self._update_subtitle(stop_s)
    if playing:
        self.btn_play.setIcon(self.style().standardIcon(_api.QStyle.StandardPixmap.SP_MediaPause))
        self.sync_timer.start()
    else:
        self.btn_play.setIcon(self.style().standardIcon(_api.QStyle.StandardPixmap.SP_MediaPlay))
        self.sync_timer.stop()
    self._set_play_bound(playing)   # painted-режим: блокировка кадров за OUT
    # Внешняя озвучка следует за состоянием основного плеера.
    self._ext_audio_set_state(playing)
    fs = getattr(self, "_fs_window", None)
    if fs is not None:
        try:
            fs.update_play_icon(state == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            pass

def on_media_status_changed(self, status):
    # Дорожки известны только у загруженного медиа — поэтому режим «только
    # звук» доводим до плеера здесь же, а не в момент нажатия кнопки (иначе
    # у нового файла видео возвращалось само).
    if status in (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                  _api.QMediaPlayer.MediaStatus.BufferedMedia):
        if getattr(self, "_audio_only_mode", False):
            self._apply_audio_only_to_player()
    # После смены качества воспроизведения (swap источника) восстанавливаем
    # позицию и состояние, как только медиа загрузилось.
    if (status in (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                   _api.QMediaPlayer.MediaStatus.BufferedMedia)
            and getattr(self, '_pending_pb_seek', None) is not None):
        pos, was_playing = self._pending_pb_seek
        self._pending_pb_seek = None
        try:
            self.player.setPosition(int(max(0, pos)))
            if was_playing:
                self.player.play()
            else:
                self.player.pause()
        except Exception:
            pass
    # Подстраховка от чёрного кадра в конце: если воспроизведение всё же
    # дошло до EndOfMedia (таймер sync_ui не успел поставить паузу на кадр
    # раньше), возвращаемся на последний реальный кадр и держим паузу.
    try:
        if status == _api.QMediaPlayer.MediaStatus.EndOfMedia and self.duration > 0:
            frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
            last = max(self.current_in, self.duration - max(frame_s, 0.05))
            self.player.pause()
            self.player.setPosition(int(last * 1000))
            self.waveform.set_playhead(last)
            self.lbl_current_time.setText(_api.s_to_time(last))
    except Exception:
        pass

def toggle_mute(self):
    """Клик по значку динамика: выключает звук и включает обратно, возвращая
        ПРЕЖНИЙ уровень громкости.

        Через сам ползунок (а не audio_output.setMuted): его valueChanged уже
        разводит громкость по всем трём выходам — видео, внешняя озвучка и
        скраб-звук покадрового шага, — обновляет значок динамика и полноэкранную
        панель. Плюс setMuted тут занят: им глушится звук видео, когда выбрана
        внешняя озвучка (см. _set_external_audio), и mute «поверх» него оставил
        бы пользователя без способа вернуть звук."""
    sl = getattr(self, "vol_slider", None)
    if sl is None:
        return
    cur = int(sl.value())
    if cur > 0:
        self._vol_before_mute = cur
        sl.setValue(0)
    else:
        # Прежний уровень мог быть нулевым (ползунок утащили в 0 руками) —
        # тогда возвращаем разумную громкость, а не «включаем в тишину».
        prev = int(getattr(self, "_vol_before_mute", 0) or 0)
        sl.setValue(prev if prev > 0 else 100)

def _on_volume_changed(self, v):
    try:
        self.audio_output.setVolume(v / 100.0)
    except Exception:
        pass
    # Та же громкость — для внешней озвучки (отдельный аудиовыход).
    if self._ext_audio_output is not None:
        try:
            self._ext_audio_output.setVolume(v / 100.0)
        except Exception:
            pass
    # …и для скраб-звука покадровой перемотки.
    if getattr(self, "_scrub_sink_obj", None) is not None:
        try:
            self._scrub_sink_obj.setVolume(max(0.0, min(1.0, v / 100.0)))
        except Exception:
            pass
    try:
        self.vol_lbl.update_glyph(v)
    except Exception:
        pass
    # Полноэкранный ползунок громкости держим в курсе.
    fs = getattr(self, "_fs_window", None)
    if fs is not None:
        try:
            fs.sync_volume()
        except Exception:
            pass

def _update_media_buttons(self):
    """Кнопки «полноэкранный режим» и «сохранить кадр» активны только когда
        загружено видео (есть видеопоток и длительность)."""
    has_video = (getattr(self, "video_stream_index", None) is not None
                 and getattr(self, "duration", 0) > 0.1)
    is_image = bool(getattr(self, "is_still_image", False))
    # Для still-картинки доступны кадрирование/пикселизация/сохранение кадра
    # (полноэкранный режим — нет, он завязан на плеер).
    has_visual = has_video or is_image
    audio_only_mode = bool(getattr(self, "_audio_only_mode", False))
    _fsb = getattr(self, "btn_fullscreen", None)
    if _fsb is not None:
        # В режиме «только звук» смотреть в полный экран нечего.
        _fsb.setEnabled(has_video and not audio_only_mode)
    _aob = getattr(self, "btn_audio_only", None)
    if _aob is not None:
        _aob.setEnabled(has_video)
        if not has_video and _aob.isChecked():
            # Загрузили аудиофайл — режим сам себя выключает: у плеера и так
            # нет видео, а подсвеченная кнопка сбивала бы с толку.
            _aob.setChecked(False)
    for name in ("btn_save_frame", "btn_crop_frame", "btn_pixelize",
                 "btn_create_subs", "btn_image_overlay"):
        b = getattr(self, name, None)
        if b is not None:
            b.setEnabled(has_visual)
    # «Удалить объект» — только для видео (для одиночной картинки есть
    # фоторедактор) и только если не идёт уже обработка.
    b = getattr(self, "btn_remove_object", None)
    if b is not None and not getattr(self, "_vinp_running", False):
        b.setEnabled(has_video)
    # «Привязать к объекту» — тоже только для видео (нужно движение).
    b = getattr(self, "btn_track_object", None)
    if b is not None and not getattr(self, "_trk_running", False):
        b.setEnabled(has_video)
    # Нет визуала (ни видео, ни картинки) — выходим из режима кадрирования рамки.
    if not has_visual:
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.setChecked(False)
        # …и сбрасываем пикселизацию.
        if getattr(self, "_pixelize_active", False) or (
                getattr(self, "btn_pixelize", None) is not None
                and self.btn_pixelize.isChecked()):
            self._pixelize_active = False
            b = getattr(self, "btn_pixelize", None)
            if b is not None and b.isChecked():
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
            self._sync_pixelize_icon()
        self._clear_image_overlays()
    # «Удалить исходник» активна при любом загруженном файле (видео/аудио).
    try:
        src = getattr(self, "actual_source_file", None)
        b = getattr(self, "btn_delete_source", None)
        if b is not None:
            b.setEnabled(bool(src) and _api.os.path.exists(str(src)))
    except Exception:
        pass
    # Режимы обрезки, неприменимые к аудио, отключаем (см. ниже).
    self._update_mode_combo_for_media(has_video)
    # Иконка полноэкранного режима белая поверх accent-заливки; на сером
    # disabled-фоне белый значок «не выглядел» выключенным. Перекрашиваем его
    # в приглушённый цвет, когда видео нет, и обратно в белый, когда есть.
    try:
        if getattr(self, "btn_fullscreen", None) is not None \
                and getattr(self, "_fs_window", None) is None:
            self.btn_fullscreen.setIcon(_api._fullscreen_icon(
                expand=True, color="#ffffff" if has_video else _api.C['text3']))
    except Exception:
        pass

def _toggle_audio_only(self, on):
    """Кнопка «Только звук»: снимает/возвращает видеодорожку у плеера.

        Декодирование видео прекращается на уровне QMediaPlayer (активный
        видеотрек = -1), предекодер точных кадров глушится, на холсте вместо
        картинки — надпись. Звук, волна, покадровый шаг, прогрев конвейера и
        обрезка работают как обычно: резать по волне и на слух можно ровно так
        же, а экспорт идёт отдельным ffmpeg по исходнику и видео сохраняет."""
    on = bool(on)
    if on == getattr(self, "_audio_only_mode", False):
        return
    self._audio_only_mode = on
    # Разбег греет звук — но он играет плеером, а мы сейчас плееру меняем
    # набор дорожек. Гасим, чтобы не столкнулись.
    if getattr(self, "_prerolling", False):
        self._preroll_cancel()
    self._apply_audio_only_to_player()
    eng = getattr(self, "_frames", None)
    if eng is not None:
        eng.cancel()          # ffmpeg больше не декодирует кадры впустую
    self._update_audio_only_placeholder()
    if not on:
        # Вернули видео — сразу возвращаем и точный кадр под плейхедом.
        self._show_exact_frame(self._frame_idx)
    self._update_media_buttons()

def _apply_audio_only_to_player(self):
    """Переключает видеодорожку плеера под текущий режим.

        Смена активного трека у ffmpeg-бэкенда может сбросить позицию, поэтому
        запоминаем её и возвращаем: плейхед обязан остаться там же, где стоял
        (см. _ui_pinned_ms — позиция в Монтаже священна)."""
    player = getattr(self, "player", None)
    if player is None:
        return
    on = getattr(self, "_audio_only_mode", False)
    try:
        pos = player.position()
    except Exception:
        pos = None
    try:
        if on:
            cur = player.activeVideoTrack()
            if cur is not None and cur >= 0:
                self._audio_only_prev_track = cur
            player.setActiveVideoTrack(-1)
        else:
            prev = getattr(self, "_audio_only_prev_track", 0)
            player.setActiveVideoTrack(prev if (prev is not None and prev >= 0) else 0)
    except Exception as e:
        self.main.log(f"audio-only: не удалось переключить видеодорожку: {e}")
        return
    try:
        if pos is not None and player.position() != pos:
            player.setPosition(int(pos))
    except Exception:
        pass

def _update_audio_only_placeholder(self):
    """В области видео показываем поясняющий текст, когда у загруженного файла
        нет видеоряда (редактируется чистое аудио). При наличии видео или без файла
        — обычный режим (показ кадров)."""
    vw = getattr(self, "video_widget", None)
    if vw is None or not hasattr(vw, "set_audio_only_message"):
        return
    src = getattr(self, "actual_source_file", None)
    # Still-картинка показывается на холсте как кадр — это НЕ «аудио без видео».
    audio_only = (bool(src)
                  and not getattr(self, "is_still_image", False)
                  and getattr(self, "video_stream_index", None) is None
                  and getattr(self, "duration", 0) > 0.1)
    if audio_only:
        vw.set_audio_only_message("Вы редактируете аудиофайл — видеоряд отсутствует")
    elif getattr(self, "_audio_only_mode", False) and bool(src):
        # Видео у файла есть, но пользователь сам отключил его кнопкой —
        # прямо говорим об этом и как вернуть, иначе пустой холст читается
        # как поломка.
        vw.set_audio_only_message(
            "Только звук — видео отключено кнопкой 🎧 в панели плеера.\n"
            "Нажмите её ещё раз, чтобы вернуть картинку. "
            "На обрезку и экспорт это не влияет.")
    else:
        vw.set_audio_only_message("")
