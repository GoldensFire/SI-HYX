# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: create_proxy_for_preview. Public namespace: edit_tab."""
import edit_tab as _api


def create_proxy_for_preview(self, vinfo, ainfo=None, scale=1.0, is_av1=False):
    if scale < 0.999 and is_av1:
        self.log_label.setText("Подготовка превью (AV1, пониженное качество)...")
    elif scale < 0.999:
        self.log_label.setText("Подготовка превью (пониженное качество)...")
    else:
        self.log_label.setText("Подготовка AV1...")
    self._report_progress(0, "Подготовка превью…")
    self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
    tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
    tf.close(); self.tmp_proxy_file = tf.name
    self.proxy_thread = _api.ProxyWorker(self.actual_source_file, self.tmp_proxy_file,
                                    scale=scale, duration=getattr(self, 'duration', 0.0),
                                    limit_sec=self._proxy_limit_sec())
    self._proxy_is_av1 = is_av1; self._proxy_scale = scale
    self._proxy_partial = self._proxy_limit_sec() > 0
    # Проценты создания прокси — в волну, рядом с «Ожидание метаданных…»
    # (так же, как «Извлечение аудио… N%» для H.264).
    self.proxy_thread.progress.connect(self.waveform.set_loading)
    self.proxy_thread.finished.connect(lambda s, m, o: self.on_proxy_ready(s, m, o, vinfo, ainfo))
    self.proxy_thread.start()

def on_proxy_ready(self, success, msg, output_path, vinfo, ainfo):
    self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
    self._report_progress(100); self.log_label.setText("Готово")
    # Файл очистили, пока строился прокси — не оживляем UI удалённым файлом.
    if self.actual_source_file is None:
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        return

    if success:
        self.is_proxy_active = True
        self.filepath = _api.Path(output_path)
        scale = getattr(self, '_proxy_scale', 1.0)
        is_av1 = getattr(self, '_proxy_is_av1', False)
        q_txt = {0.5: " 1/2", 0.25: " 1/4"}.get(scale, "")
        if is_av1 and q_txt:
            badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264,{q_txt.strip()})"
        elif is_av1:
            badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
        else:
            badge = f" ПРЕВЬЮ РЕЖИМ (качество{q_txt})"
        lim = self._proxy_limit_sec()
        if lim > 0:
            badge += f" · первые {int(round(lim / 60))} мин"
        self.lbl_proxy.setText(_api.icon_html('fa5s.bolt', 13, _api.C['yellow']) + badge)
        self.lbl_proxy.setVisible(True)
    elif msg != "Отменено":
        _api.msgbox_warning(self, "Ошибка прокси", f"Не удалось создать превью: {msg}")
    # «Аудио»/«Битрейт аудио» должны показывать РЕАЛЬНЫЙ кодек исходника (напр.
    # Opus), а не превью-прокси — прокси ВСЕГДА транскодирует звук в AAC (см.
    # ProxyWorker.run, -c:a aac) ради совместимости с QtMultimedia, поэтому
    # ainfo здесь — тот же объект, что пришёл из ffprobe исходника в load_file
    # (передан через create_proxy_for_preview), а не повторный probe self.filepath.
    self.finish_loading_file(vinfo, ainfo)

def _on_pb_quality_changed(self, _idx=None):
    """Смена «качества воспроизведения» на лету: пересобираем прокси (или
        возвращаемся к оригиналу), сохраняя позицию и состояние плеера. На экспорт
        не влияет — он всегда из self.actual_source_file."""
    src = self.actual_source_file
    if not src or not _api.os.path.exists(str(src)):
        return
    if getattr(self, 'video_stream_index', None) is None:
        return  # без видеодорожки качество воспроизведения не применимо
    # Если прокси уже строится — отменяем, начнём заново с новым качеством.
    if self.proxy_thread and self.proxy_thread.isRunning():
        self.proxy_thread.stop(); self.proxy_thread.wait()
    try: pos = int(self.player.position())
    except Exception: pos = 0
    try:
        was_playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
    except Exception:
        was_playing = False
    self._pb_restore = (pos, was_playing)

    is_av1 = bool(getattr(self, '_source_is_av1', False))
    scale = self._proxy_scale_for(is_av1)
    need_proxy = is_av1 or scale < 0.999

    # Освобождаем плеер от старого прокси-файла (иначе Windows его не отдаст),
    # затем удаляем временный файл.
    try: self.player.stop()
    except Exception: pass
    try: self.player.setSource(_api.QUrl())
    except Exception: pass
    old_proxy = self.tmp_proxy_file
    self.tmp_proxy_file = None
    self.is_proxy_active = False
    if old_proxy and _api.os.path.exists(old_proxy):
        try: _api.os.remove(old_proxy)
        except Exception: pass

    if need_proxy:
        self.log_label.setText("Смена качества предпросмотра…")
        self._report_progress(0, "Качество предпросмотра…")
        self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
        tf = _api.tempfile.NamedTemporaryFile(delete=False, suffix=".mp4"); tf.close()
        self.tmp_proxy_file = tf.name
        self._proxy_is_av1 = is_av1; self._proxy_scale = scale
        self.proxy_thread = _api.ProxyWorker(src, self.tmp_proxy_file, scale=scale,
                                        duration=getattr(self, 'duration', 0.0),
                                        limit_sec=self._proxy_limit_sec())
        self._proxy_partial = self._proxy_limit_sec() > 0
        # Здесь волна уже заполнена — set_loading её стёр бы; показываем
        # прогресс создания прокси в строке лога И в общем прогрессбаре окна.
        self.proxy_thread.progress.connect(self._on_pb_proxy_progress)
        self.proxy_thread.finished.connect(self._on_pb_proxy_ready)
        self.proxy_thread.start()
    else:
        # Полное качество и не-AV1 → играем оригинал.
        self._proxy_partial = False
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        self._swap_player_source(src)

def _on_pb_proxy_progress(self, text):
    """Прогресс пересборки прокси при смене версии качества: пишем и в строку
        лога, и в общий прогрессбар окна (вытаскиваем проценты из «…N%»)."""
    self.log_label.setText(text)
    pct = None
    if '%' in text:
        try:
            pct = int(text.rsplit('%', 1)[0].split()[-1])
        except Exception:
            pct = None
    self._report_progress(pct if pct is not None else -1,
                          text or "Создание превью…")

def _on_pb_proxy_ready(self, success, msg, output_path):
    self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
    self._report_progress(100); self.log_label.setText("Готово")
    # Источник могли очистить, пока строился прокси (его finished-слот в этом
    # случае приходит уже после очистки) — показывать/переключать нечего.
    if self.actual_source_file is None:
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        return
    if success and output_path and _api.os.path.exists(output_path):
        self.is_proxy_active = True
        scale = getattr(self, '_proxy_scale', 1.0)
        is_av1 = getattr(self, '_proxy_is_av1', False)
        q_txt = {0.5: "1/2", 0.25: "1/4"}.get(scale, "")
        if is_av1 and q_txt:
            badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264, {q_txt})"
        elif is_av1:
            badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
        else:
            badge = f" ПРЕВЬЮ РЕЖИМ (качество {q_txt})"
        lim = self._proxy_limit_sec()
        if lim > 0:
            badge += f" · первые {int(round(lim / 60))} мин"
        self.lbl_proxy.setText(_api.icon_html('fa5s.bolt', 13, _api.C['yellow']) + badge)
        self.lbl_proxy.setVisible(True)
        self._swap_player_source(output_path)
    else:
        if msg != "Отменено":
            _api.msgbox_warning(self, "Ошибка прокси",
                                f"Не удалось создать превью: {msg}")
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        self._swap_player_source(self.actual_source_file)

def _swap_player_source(self, path):
    """Переключает источник плеера, сохраняя позицию/состояние из _pb_restore
        (применяются после загрузки медиа в on_media_status_changed)."""
    if path is None:
        return  # файл очистили — переключать нечего
    self.filepath = _api.Path(path)
    self._pending_pb_seek = getattr(self, '_pb_restore', None)
    self._set_player_file(path)
    # Точные кадры обязаны браться из ТОГО ЖЕ файла, что играет плеер:
    # иначе после смены качества превью стоп-кадр остался бы от прежнего
    # источника (другое разрешение — заметный «скачок» резкости на паузе).
    self._frames_set_source()

def _set_player_file(self, path):
    """Грузит файл в плеер через девайс с FILE_SHARE_DELETE — тогда исходник
        можно удалить из Проводника прямо во время монтажа (плеер его не держит
        намертво). Если девайс открыть не удалось — обычная загрузка по URL."""
    path = str(path)
    old = getattr(self, '_play_device', None)
    dev = _api.ShareDeleteIODevice(path)
    opened = False
    try:
        opened = dev.open()
    except Exception:
        opened = False
    try:
        if opened:
            self._play_device = dev
            self.player.setSourceDevice(dev, _api.QUrl.fromLocalFile(path))
        else:
            self._play_device = None
            self.player.setSource(_api.QUrl.fromLocalFile(path))
    except Exception:
        self._play_device = None
        try:
            self.player.setSource(_api.QUrl.fromLocalFile(path))
        except Exception:
            pass
    # Старый девайс закрываем чуть позже — плеер уже переключился на новый.
    if old is not None and old is not dev:
        _api.QTimer.singleShot(0, lambda d=old: self._close_play_device(d))

def _close_play_device(self, dev):
    try:
        dev.close()
    except Exception:
        pass

def finish_loading_file(self, vinfo, ainfo):
    if vinfo:
        r = vinfo.get('r_frame_rate') or vinfo.get('avg_frame_rate') or "0/1"
        try:
            num, den = r.split('/')
            fps = float(num) / float(den) if float(den) != 0 else 0.0
            self.fps = fps if fps > 0 else None
        except Exception:
            self.fps = None
        w = vinfo.get('width', '?'); h = vinfo.get('height', '?')
        codec = vinfo.get('codec_name', '?').upper()
        self.lbl_vstream.setText(f"{codec} {w}×{h}")
        try:
            wv = int(vinfo.get('width') or 0); hv = int(vinfo.get('height') or 0)
            self.video_aspect = (wv / hv) if (wv > 0 and hv > 0) else None
        except Exception:
            self.video_aspect = None
    else:
        self.video_stream_index = None; self.fps = None
        self.video_aspect = None
        self.lbl_vstream.setText("—")

    if ainfo:
        self.audio_stream_index = ainfo.get('index')
        codec_a = ainfo.get('codec_name', '?').upper()
        self.lbl_astream.setText(f"{codec_a} {_api._fmt_channels(ainfo)}")
        self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
    else:
        self.audio_stream_index = None
        self.lbl_astream.setText("—")
        self.lbl_abitrate.setText("—")

    self._populate_track_combos()
    self._update_media_buttons()
    self._update_audio_only_placeholder()
    self.lbl_fps.setText(_api.format_fps(self.fps))
    # Покадровый слой перенастраиваем на новый клип: сетка кадров (fps +
    # длительность) и источник точных кадров — ТОТ ЖЕ файл, что уйдёт в
    # плеер (оригинал или превью-прокси, см. _frames_set_source).
    self._refresh_frame_grid()
    self._frame_idx = 0
    self._frames_set_source()

    self.undo_stack.clear(); self.redo_stack.clear()
    self.current_in = 0.0; self.current_out = max(0.001, self.duration)
    self.set_in_out(0.0, self.current_out, skip_undo=True)

    # Новый файл — сбрасываем зум/панораму превью (если активен холст-режим)
    # и снимаем предпросмотр привязки: он посчитан по ПРОШЛОМУ видео.
    if isinstance(self.video_widget, _api.VideoCanvas):
        self.video_widget.reset_view()
        self._clear_track_preview()

    self._set_player_file(self.filepath)
    self.player.setPosition(0); self.player.pause()

    self.start_waveform_loading()
    _api.QTimer.singleShot(50, self._adjust_video_aspect_once)
    self.update_selection_label(); self.update_pan_slider_values()
    # После загрузки файла (в т.ч. через drag&drop) забираем фокус клавиатуры
    # на вкладку, чтобы Пробел/I/O/←→ работали сразу — без клика по видео.
    # singleShot(0): после того, как плеер/видеовиджет отработают своё событие.
    _api.QTimer.singleShot(0, self._grab_kbd_focus)
    # Прогреваем отдельный плеер скраб-звука заранее (источник — оригинал).
    # Без прогрева ПЕРВЫЕ покадровые шаги часто шли без звука: плеер ещё
    # догружал медиа (а у AV1+Opus оригинала открытие/перемотка не мгновенны)
    # — отсюда баг «при av1 прокси звук при шаге по кадру появляется не всегда».
    _api.QTimer.singleShot(0, self._prime_scrub_audio)

def _prime_scrub_audio(self):
    """Заранее декодирует окно PCM вокруг текущей точки, чтобы ПЕРВЫЙ же
        покадровый шаг звучал сразу (окно готовится ~80 мс — на первом шаге это
        было бы слышно как «звук появляется не всегда»). Только подготовка —
        ничего не играем (тишина при загрузке файла)."""
    if not getattr(self, "_scrub_audio_enabled", True):
        return
    try:
        eng = self._sync_scrub_audio_source()
        if eng is not None:
            eng.request(max(0.0, self.player.position() / 1000.0))
        self._scrub_sink()          # поднять устройство заранее (~45 мс)
    except Exception:
        pass
