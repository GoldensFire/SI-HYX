# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: on_player_duration_changed. Public namespace: edit_tab."""
import edit_tab as _api


# ── Playback ──────────────────────────────────────────────────────────
def on_player_duration_changed(self, dur_ms):
    if dur_ms <= 0:
        return
    # Усечённый прокси (первые N минут) короче оригинала — НЕ даём его
    # длительности перетереть настоящую, иначе таймлайн/обрезка схлопнутся
    # до длины прокси (а резать-то надо весь файл). Истинную длительность
    # держим из ffprobe (load_file).
    if getattr(self, 'is_proxy_active', False) and getattr(self, '_proxy_partial', False):
        return
    new_dur = dur_ms / 1000.0
    # Выделение покрывало весь клип? Тогда тянем OUT к настоящей длительности.
    was_full = (self.current_out <= 0.001) or abs(self.current_out - self.duration) < 0.05
    self.duration = new_dur
    self.lbl_duration.setText(_api.s_to_time(self.duration))
    self._update_total_time()
    # Синхронизируем current_out / waveform.out_s с новой длительностью (баг #4).
    self._refresh_frame_grid()   # у сетки кадров новый предел
    new_out = new_dur if was_full else min(self.current_out, new_dur)
    new_in  = min(self.current_in, max(0.0, new_out - 0.001))
    if abs(new_out - self.current_out) > 1e-4 or abs(new_in - self.current_in) > 1e-4:
        self.set_in_out(new_in, new_out, skip_undo=True)

def _update_seg_duration(self, pos_s=None):
    """Обновляет метку «старт→плейхед»: длительность от IN до жёлтой полосы
        воспроизведения. Зовётся отовсюду, где двигается плейхед или меняется IN."""
    lbl = getattr(self, "lbl_seg_dur", None)
    if lbl is None:
        return
    try:
        if pos_s is None:
            pos_s = self.player.position() / 1000.0
        lbl.setText(_api.s_to_time(max(0.0, pos_s - self.current_in)))
    except Exception:
        pass

def on_position_changed(self, pos_ms):
    self._preroll_watch(pos_ms)        # см. _preroll_at (прогрев с разбега)
    if not getattr(self, "_prerolling", False):
        # Во время разбега позиция пробегает мимо любых целей покадрового
        # seek'а — «подтверждать» ими чужой seek нельзя.
        self._confirm_frame_seek(pos_ms)   # см. step_frame/_dispatch_frame_seek
    # Интерфейс — по мастер-часам (кадр на экране), а не по «сырой» позиции
    # плеера: иначе метка и картинка живут каждая своей жизнью, что и было
    # видно как рассинхрон метки с видео. Для аудиофайлов _clock_pos_s сам
    # возвращает позицию плеера.
    pinned_ms = self._ui_pinned_ms()
    pos_s = (pinned_ms / 1000.0) if pinned_ms is not None else self._clock_pos_s()
    self._paint_playhead(pos_s)
    self._update_meter(pos_s)
    self._update_subtitle(pos_s)

def _update_meter(self, pos_s, force=False):
    """Кормит индикатор уровня значением аудиоволны на позиции плейхеда.
        При воспроизведении вызывается из sync_ui; `force=True` — при покадровой
        перемотке (скрабе), чтобы шкала «оживала» и на шаге, а не только на play.
        На паузе без force шкала плавно опадает сама."""
    meter = getattr(self, "audio_meter", None)
    if meter is None:
        return
    try:
        playing = (self.player.playbackState()
                   == _api.QMediaPlayer.PlaybackState.PlayingState)
        if not playing and not force:
            return
        # level_at_lr уже нормирован по пику и перцептивен (см. WaveformWidget),
        # поэтому шкала живая и отражает реальное присутствие звука. L и R —
        # честно раздельные каналы (для моно совпадут).
        lvl_l, lvl_r = self.waveform.level_at_lr(pos_s)
        try:
            vol = max(0.0, min(1.0, float(self.audio_output.volume())))
        except Exception:
            vol = 1.0
        k = 0.25 + 0.75 * vol
        meter.set_levels(min(1.0, lvl_l * k), min(1.0, lvl_r * k))
    except Exception:
        pass

def _effective_out_s(self):
    """Граница авто-паузы воспроизведения. Если OUT у самого конца клипа —
        останавливаемся на кадр раньше: иначе плеер доходит до EndOfMedia и
        QtMultimedia гасит поверхность в чёрный кадр (баг #9)."""
    frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
    guard = max(frame_s, 0.05)
    at_end = self.current_out >= (self.duration - 0.02)
    return (self.duration - guard) if at_end else self.current_out

def _set_play_bound(self, active):
    """Вкл/выкл блокировку кадров за OUT в painted-режиме (анти-overshoot)."""
    vw = self.video_widget
    if not isinstance(vw, _api.VideoCanvas):
        return
    if active and self.duration > 0:
        frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
        # граница = effective_out + полкадра: кадр НА границе ещё показываем,
        # а следующий (за ней) — блокируем и встаём на паузу.
        vw.set_play_bound(self._effective_out_s() + frame_s * 0.5)
    else:
        vw.set_play_bound(None)

def _on_play_boundary(self):
    """Пришёл кадр за OUT (по PTS) — мгновенная пауза и снап на границу ДО
        показа кадра. Убирает проскок-и-отскок правой границы."""
    try:
        if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        out_s = self._effective_out_s()
        # Кадр остановки задаём явно: иначе пауза «пришпилила» бы последний
        # ПОКАЗАННЫЙ кадр, и метка отскочила бы от границы на кадр назад.
        if self._grid.valid:
            self._frame_idx = self._grid.index_at(out_s)
        self.player.setPosition(int(out_s * 1000))
        self.lbl_current_time.setText(_api.s_to_time(out_s))
        self.waveform.set_playhead(out_s)
        self._ext_audio_seek(int(out_s * 1000))
    except Exception:
        pass

def sync_ui(self):
    if self.duration <= 0.1:
        return
    # Часы плеера (по сути аудио-часы) — ими проверяем границу OUT: она
    # обязана срабатывать по звуку, даже если видеокадры отстают.
    pos_s = self.player.position() / 1000.0
    # А интерфейс (метка времени, полоса, плейхед на волне, субтитры) ведём
    # по МАСТЕР-ЧАСАМ — времени кадра, который сейчас на экране. Пока плеер
    # занят служебным делом (разбег, транзиентный play скраба), часы стоят
    # на отметке пользователя — см. _ui_pinned_ms.
    pinned_ms = self._ui_pinned_ms()
    disp_s = (pinned_ms / 1000.0) if pinned_ms is not None else self._clock_pos_s()
    # Авто-пауза в конце воспроизводимого участка (резерв к покадровому
    # блоку VideoCanvas: ловит границу в overlay-режиме и как страховка).
    effective_out = self._effective_out_s()
    if effective_out > self.current_in and pos_s >= effective_out:
        self.player.pause()
        if self._grid.valid:
            self._frame_idx = self._grid.index_at(effective_out)
        self.player.setPosition(int(effective_out * 1000))
        self.lbl_current_time.setText(_api.s_to_time(effective_out))
        self.waveform.set_playhead(effective_out)
        self._update_seg_duration(effective_out)
        return
    self._paint_playhead(disp_s)
    self._update_meter(disp_s)
    self._update_subtitle(disp_s)
    # Рассинхрон внешней озвучки. Порог опущен с 220 до 130 мс: 220 мс — это
    # уже отчётливо слышимое «эхо» относительно картинки (заметно от ~40 мс),
    # а ниже сотни ставить нельзя — каждая правка это setPosition, то есть
    # микро-заминка в звуке. Сверяемся с ЧАСАМИ ПЛЕЕРА (звук к звуку), а не с
    # часами кадра: рассинхрон двух звуковых дорожек между собой слышен, а
    # отставание рендера видео к нему отношения не имеет.
    if self._ext_audio_active and self._ext_audio_player is not None:
        try:
            if (self._ext_audio_player.playbackState()
                    == _api.QMediaPlayer.PlaybackState.PlayingState):
                drift = self._ext_audio_player.position() - self.player.position()
                if abs(drift) > 130:
                    self._ext_audio_player.setPosition(self.player.position())
        except Exception:
            pass

def on_slider_moved(self, value):
    if self.duration > 0:
        self.seek_to((value / 1000.0) * self.duration)

def seek_to(self, t_s):
    try:
        ms = int(max(0.0, min(t_s, max(0.0, self.duration))) * 1000)
        # Идёт беззвучный разбег — гасим его ПЕРВЫМ делом. Иначе плеер
        # продолжил бы играть уже от новой отметки и уехал бы с неё.
        if getattr(self, "_prerolling", False):
            self._preroll_cancel()
        # Отложенная цель покадровой серии устарела — позицию ставим здесь.
        self._frame_seek_deferred_ms = None
        if isinstance(self.video_widget, _api.VideoCanvas):
            self.video_widget.set_scrub_active(True)
            self._scrub_idle_timer.start()   # перезапуск — «перемотка ещё идёт»
        # Целевой кадр запоминаем сразу: от него пойдёт покадровый шаг.
        # Пин ПЕРЕВОДИМ на новый кадр тут же — без этого холст продолжал бы
        # считать «своим» кадр, где перемотка началась, и отбрасывал бы все
        # кадры плеера: картинка стояла бы всю протяжку. Точные кадры при
        # этом не заказываем (ffmpeg на каждый пиксель протяжки не нужен) —
        # но если нужный кадр уже лежит в буфере, показываем его мгновенно.
        if self._grid.valid:
            self._frame_idx = self._grid.index_at(ms / 1000.0)
            vw = getattr(self, "video_widget", None)
            if isinstance(vw, _api.VideoCanvas):
                span = self._grid.pts_span_us(self._frame_idx)
                vw.arm_frame_pin(span)
                eng = getattr(self, "_frames", None)
                img = eng.frame(self._frame_idx) if eng is not None else None
                if img is not None:
                    vw.set_exact_frame(
                        img, span,
                        int(self._grid.start_of(self._frame_idx) * 1_000_000))
        self.player.setPosition(ms)
        self.waveform.set_playhead(t_s)
        self._ext_audio_seek(ms)
    except Exception as e:
        self.main.log(f"seek_to error: {e}")

def _on_scrub_idle(self):
    """Перемотка утихла (seek_to не вызывался _scrub_idle_timer.interval() мс) —
        возвращаем сглаженную отрисовку кадра в VideoCanvas."""
    if isinstance(self.video_widget, _api.VideoCanvas):
        self.video_widget.set_scrub_active(False)
    prerolling = getattr(self, "_prerolling", False)
    playing = (self.player.playbackState()
               == _api.QMediaPlayer.PlaybackState.PlayingState)
    if not playing or prerolling:
        # Перемотка кончилась — ставим на холст ТОЧНЫЙ кадр этой позиции и
        # набиваем буфер соседями, чтобы первый же шаг стрелкой был мгновенным.
        # Во время прогрева («с разбега») плеер формально играет, но кадр всё
        # равно наш: пин прячет пробегающие кадры разбега.
        self._show_exact_frame(self._frame_idx)
    if not playing:
        # Окно PCM для скраб-звука — в новой точке (первый шаг после клика
        # по шкале обязан звучать сразу, см. AudioScrubber).
        self._prime_scrub_audio()
        # Греем аудио-конвейер в новой точке, пока стоим на паузе: иначе
        # первое «Воспроизвести» после перемотки начиналось с ~0.35 с тишины
        # и докрутить обрезку по слуху было нельзя (см. _preroll_at).
        self._preroll_at(self._playhead_target_s())

def toggle_play(self):
    self._scrubbing = False   # явное play/pause не должно гаситься скрабом
    # Возврат звука после разбега отложен на четверть секунды (хвост очереди
    # аудиоустройства, см. _restore_preroll_mute) — но ждать его нельзя:
    # воспроизведение, начатое в этом окне, было бы немым.
    self._flush_preroll_mute()
    # …и позиция: серия покадровых шагов могла закончиться этим самым нажатием,
    # а её итоговую точку плеер ещё не получил (см. _dispatch_frame_seek).
    self._flush_frame_seek()
    # Пользователь нажал Play в окне беззвучного прогрева: отменяем прогрев,
    # возвращаем mute и продолжаем уже как обычный запуск (плеер уже играет
    # под mute — достаточно снять mute, не дёргая позицию).
    if getattr(self, "_prerolling", False):
        self._prerolling = False
        tgt = getattr(self, "_preroll_target_ms", None)
        # Прогрев идёт «с разбега», то есть плеер сейчас может быть ЕЩЁ НЕ
        # доехавшим до отметки пользователя. Продолжить прямо отсюда значило
        # бы начать воспроизведение раньше плейхеда. Но и перематывать на
        # цель нельзя: перемотка кладёт аудио-конвейер, и звук появится
        # только через ~0.35 с (ровно тот баг, ради которого прогрев и
        # существует). Поэтому пока остаток разбега короткий — ДОИГРЫВАЕМ
        # его под mute и снимаем mute на цели (_preroll_handoff): и картинка
        # (пин точного кадра держится), и звук стартуют ровно на отметке.
        behind = 0
        try:
            behind = (int(tgt) - self.player.position()) if tgt is not None else 0
        except Exception:
            behind = 0
        if tgt is not None and 0 < behind <= self._PREROLL_HANDOFF_MS:
            self._preroll_handoff = True
            self._preroll_timer().start()
            # Страховка: разбег мог упереться в конец файла и не доехать.
            _api.QTimer.singleShot(self._PREROLL_HANDOFF_MS + 300,
                              self._preroll_handoff_finish)
            self.on_playback_changed(self.player.playbackState())
            return
        self._preroll_target_ms = None
        try:
            self._preroll_timer().stop()
        except Exception:
            pass
        try:
            self.audio_output.setMuted(self._preroll_prev_muted)
            # Остаток разбега длиннее порога — ждать дольше, чем стоит
            # перемотка; доводим позицию.
            if tgt is not None and behind > self._PREROLL_HANDOFF_MS:
                self.player.setPosition(int(tgt))
        except Exception:
            pass
        self._release_frame_lock()
        self.on_playback_changed(self.player.playbackState())
        return
    if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
        self.player.pause()
    else:
        pos_s = self.player.position() / 1000.0
        if abs(pos_s - self.current_out) < 0.15 and self.current_out > (self.current_in + 0.5):
            self.seek_to(self.current_in)
        # Пин снимаем ДО play(): иначе первые кадры воспроизведения (у них
        # уже другой pts) холст отбросил бы как «чужие», и картинка стояла бы
        # лишние доли секунды. Предекодер тоже глушим — во время игры
        # процессор нужен декодеру плеера, а не буферу стоп-кадров.
        self._release_frame_lock()
        self.player.play()

def stop_playback(self):
    self.player.pause(); self.seek_to(self.current_in)
    # «Камера» идёт за плейхедом: если зум стоит не на начале зоны, докручиваем
    # окно обзора так, чтобы точка, куда прыгнула жёлтая полоска, была видна.
    try:
        self.waveform.ensure_view_contains(self.current_in, self.current_in)
        self.waveform.update()
    except Exception:
        pass
    # Точный кадр точки IN — на холст СРАЗУ (до прогрева): иначе кадры
    # «разбега» успели бы мелькнуть на экране.
    self._show_exact_frame(self._frame_idx)
    # Прогреваем конвейер в точке IN — следующее «Воспроизвести» стартует
    # без задержки (см. _preroll_at). Цель берём у КАДРА (seek_to уже
    # поставил на него _frame_idx), иначе прогрев целился бы мимо сетки.
    self._preroll_at(self._playhead_target_s())
