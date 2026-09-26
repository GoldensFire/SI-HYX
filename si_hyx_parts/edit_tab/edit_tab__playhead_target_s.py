# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _playhead_target_s. Public namespace: edit_tab."""
import edit_tab as _api


def _playhead_target_s(self):
    """Куда ЦЕЛИТСЯ плеер для текущего плейхеда, с.

        Это середина кадра, на котором стоит монтаж, — та же цель, что у шага
        (см. FrameGrid.center_of). Брать вместо неё player.position() нельзя:
        после перемотки плеер стоит где-то ВНУТРИ кадра (замерено — промах до
        3 кадров), а при удержании стрелки ещё и отстаёт от плейхеда на
        недоехавший seek. Кто считал прогрев от позиции плеера, тот утаскивал
        туда же и номер кадра, и метку — «шагнул вправо, а он пятится назад»."""
    if self._grid.valid and self._frame_idx is not None:
        return self._grid.center_of(self._frame_idx)
    try:
        return max(0.0, self.player.position() / 1000.0)
    except Exception:
        return 0.0

def _ui_pinned_ms(self):
    """Позиция (мс), на которой ОБЯЗАН стоять интерфейс, или None.

        Плеер иногда играет НЕ для пользователя: беззвучный разбег прогрева и
        транзиентный play() покадрового шага в overlay-режиме. В обоих случаях
        его позиция уезжает и возвращается — и раньше это ехало прямо на шкалу:
        бегунок «разгонялся» к отметке, а шаг стрелкой на один кадр сначала
        сдвигал плейхед, а потом тащил его назад к точке разбега. Резать с таким
        поведением невозможно.

        Поэтому пока плеер занят собой, часы интерфейса стоят на ЗАКАЗАННОЙ
        точке: метка времени, бегунок, жёлтая полоса на волне, «старт→плейхед»
        и полноэкранная панель показывают ровно тот кадр, который выбрал
        пользователь. Наружу прогрева не существует.

        То же самое и НА ПАУЗЕ: там истина — номер кадра, на котором стоит
        монтаж, а не позиция плеера. Позиция живёт по аудио-часам и после
        pause() отличается от показанного кадра на десятки миллисекунд, а
        точный кадр приезжает из предекодера только через сотни — раньше на
        этом зазоре жёлтая полоса после остановки сперва прыгала вперёд (по
        позиции плеера), а потом возвращалась назад (по приехавшему кадру)."""
    busy = (getattr(self, "_prerolling", False)
            or getattr(self, "_preroll_handoff", False)
            or getattr(self, "_scrubbing", False))
    if not busy:
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        if playing or not self._grid.valid or self._frame_idx is None:
            return None
        return int(round(self._grid.start_of(self._frame_idx) * 1000.0))
    # Истина у интерфейса одна — НАЧАЛО кадра, на котором стоит монтаж
    # (плееру мы отдаём середину кадра, чтобы он не промахнулся мимо него,
    # но метка обязана совпадать с картинкой). Раньше прогрев отдавал сюда
    # свою цель в миллисекундах, то есть СЕРЕДИНУ кадра, и метка времени
    # после каждого шага дёргалась на полкадра: 00:01:00.017 → .025 → .017.
    if self._grid.valid and self._frame_idx is not None:
        return int(round(self._grid.start_of(self._frame_idx) * 1000.0))
    if (getattr(self, "_prerolling", False)
            or getattr(self, "_preroll_handoff", False)):
        tgt = getattr(self, "_preroll_target_ms", None)
        if tgt is not None:
            return tgt
    ms = getattr(self, "_scrub_audio_ms", None)
    if ms is None:
        ms = getattr(self, "_scrub_target", None)
    return ms

def _ui_time_s(self):
    """Время монтажа для ЛЮБОГО показа на экране, с. Одна точка входа.

        Кто берёт время напрямую у плеера (player.position()), тот рано или
        поздно показывает не то: во время беззвучного разбега позиция уезжает
        на полсекунды назад, на паузе живёт по аудио-часам, а при удержании
        стрелки отстаёт на недоехавший seek. Именно так субтитры и мигали на
        каждый покадровый шаг — ASS-таймер рисовал libass по сырой позиции
        плеера и на время разбега выводил реплики из прошлого."""
    pinned = self._ui_pinned_ms()
    if pinned is not None:
        return max(0.0, pinned / 1000.0)
    return self._clock_pos_s()

def _preroll_at(self, t_s):
    """Беззвучный прогрев конвейера «с разбега» перед точкой t_s.

        Зачем вообще: QtMultimedia (ffmpeg-бэкенд) поднимает декодер и аудио-
        устройство только на play(), поэтому первое воспроизведение после
        перемотки начиналось с заметной паузы — на длинных GOP (аниме-BDRip,
        250+ кадров между ключевыми) картинка «думала» до пары секунд.

        Как это делалось раньше и почему это же и мешало: играли 45 мс под mute,
        потом ПАУЗА и setPosition НАЗАД, на исходную точку. Обратный seek — это
        ещё одна полная раскрутка GOP, и попадала она ровно в момент, когда
        пользователь жал «Воспроизвести»: плеер сперва доигрывал этот seek и
        только потом стартовал. Прогрев лечил симптом и создавал его же.

        Теперь прогрев идёт С РАЗБЕГА: встаём на _PREROLL_LEAD_MS РАНЬШЕ цели,
        играем под mute и тормозим, когда позиция САМА дошла до t_s. Обратной
        перемотки нет вовсе (а если проскочили больше кадра — правим, но это
        редкость), декодер уже раскрутил цепочку через нужную точку, и реальный
        старт продолжает воспроизведение, а не начинает его заново.

        И главное: снаружи прогрева НЕ ВИДНО. На холсте пришпилен точный кадр
        цели (см. _show_exact_frame), кадры разбега холст отбрасывает, а часы
        интерфейса заморожены на цели (см. _ui_pinned_ms) — бегунок, метка и
        жёлтая полоса стоят там, куда встал пользователь, и никуда не едут."""
    if self.duration <= 0.1 or not self.filepath:
        return
    if getattr(self, "_prerolling", False):
        # Разбег уже идёт. Если греем ровно эту точку — не мешаем ему. А вот
        # если пользователь тем временем перемотал в другое место, старый
        # разбег обязан быть отменён: он ждёт СВОЮ цель, а плеер уже стоит на
        # новой, и, дождавшись, утащил бы позицию обратно к прежней отметке.
        if abs((getattr(self, "_preroll_target_ms", None) or -10 ** 9)
               - int(max(0.0, t_s) * 1000)) <= self._PREROLL_GUARD_MS:
            return
        self._preroll_cancel()
    if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
        return
    if getattr(self, "_scrubbing", False):
        return          # идёт серия покадровых шагов — не мешаем ей плеером
    try:
        ms = int(max(0.0, t_s) * 1000)
        lead = max(0, ms - self._PREROLL_LEAD_MS)
        if ms - lead < self._PREROLL_MIN_LEAD_MS:
            # У самого начала файла разбегаться негде: плеер получил бы
            # play() и pause() в одном такте, а такую пару ffmpeg-бэкенд
            # теряет — плеер оставался ИГРАТЬ, пин снимался устаревшим
            # playbackStateChanged, и монтаж уезжал со стартового кадра сам
            # (проверено вживую: шаг у нулевого кадра «уплывал» вперёд).
            # Греть тут всё равно нечего: до начала файла меньше 120 мс.
            return
        # prev_muted держим на self — если пользователь нажмёт «Воспроизвести»
        # прямо в окне прогрева, toggle_play восстановит mute и отменит прогрев.
        # Возврат mute от ПРОШЛОГО разбега мог ещё не отработать (он отложен,
        # см. _restore_preroll_mute) — тогда «прежним» считаем то, что он
        # собирался вернуть, а не сегодняшний mute самого прогрева.
        if getattr(self, "_preroll_unmute_pending", False):
            self._preroll_unmute_gen = getattr(self, "_preroll_unmute_gen", 0) + 1
            self._preroll_unmute_pending = False
        else:
            self._preroll_prev_muted = self.audio_output.isMuted()
        self._prerolling = True
        self._preroll_handoff = False
        self._preroll_target_ms = ms
        self._preroll_gen = getattr(self, "_preroll_gen", 0) + 1
        gen = self._preroll_gen
        self.audio_output.setMuted(True)
        # Номер кадра прогрев НЕ трогает: на нём стоит монтаж, и вычислять
        # его заново из миллисекунд цели — способ потерять кадр на границе.
        if self._grid.valid and self._frame_idx is None:
            self._frame_idx = self._grid.index_at(ms / 1000.0)
        # Пин цели ДО старта разбега — экран остаётся на нужном кадре.
        self._show_exact_frame(self._frame_idx)
        if lead < ms:
            self.player.setPosition(lead)
        self.player.play()
        # Тормозим по СВОЕМУ таймеру (5 мс), а не по positionChanged (50 мс):
        # см. _PREROLL_POLL_MS.
        self._preroll_timer().start()
        # Страховка: если позиция почему-то не дойдёт до цели (короткий
        # клип, упёрлись в конец, seek не отработал) — заканчиваем сами.
        # Запас считаем от разбега: 500 мс разбега + ~300 мс раскрутки
        # конвейера + запас.
        _api.QTimer.singleShot(self._PREROLL_LEAD_MS + 1500,
                          lambda g=gen: self._preroll_finish(g, forced=True))
    except Exception:
        self._prerolling = False
        self._preroll_target_ms = None
        try:
            self.audio_output.setMuted(False)
        except Exception:
            pass

def _preroll_cancel(self):
    """Гасит разбег БЕЗ доводки позиции: цель устарела (пользователь перемотал
        в другое место или шагнул кадром), поэтому ни тормозить «на цели», ни
        возвращаться к ней не нужно — тот, кто отменил, сам поставит позицию."""
    if not getattr(self, "_prerolling", False):
        return
    self._prerolling = False
    self._preroll_target_ms = None
    # Новое поколение — чтобы хвосты старого (страховочный singleShot,
    # positionChanged) прошли мимо.
    self._preroll_gen = getattr(self, "_preroll_gen", 0) + 1
    try:
        self._preroll_timer().stop()
    except Exception:
        pass
    try:
        self.player.pause()
    except Exception:
        pass
    self._restore_preroll_mute()

def _restore_preroll_mute(self, delay_ms=None):
    """Возвращает звук после разбега — но НЕ в том же такте, что pause().

        Замерено щупом WASAPI (пик аудиосессии процесса, то есть ровно то, что
        уходит в колонки): после pause() устройство ещё ~130 мс доигрывает
        очередь, и mute у ffmpeg-бэкенда гасит её НЕ на входе, а на выходе
        сессии. Снятый в том же такте mute открывал этот хвост — и каждый
        покадровый шаг звучал ДВАЖДЫ: сначала блип скраба, а через ~0.2 с ещё
        и кусок прогрева (замер: пик 0.36 на +75…+200 мс после pause).

        Поэтому ждём, пока очередь доиграет вхолостую. Возврат В mute (внешняя
        озвучка) откладывать не нужно — он ничего не озвучивает."""
    if delay_ms is None:
        delay_ms = self._PREROLL_UNMUTE_MS
    prev = bool(getattr(self, "_preroll_prev_muted", False))
    self._preroll_unmute_gen = getattr(self, "_preroll_unmute_gen", 0) + 1
    if prev:
        self._preroll_unmute_pending = False
        try:
            self.audio_output.setMuted(True)
        except Exception:
            pass
        return
    self._preroll_unmute_pending = True
    gen = self._preroll_unmute_gen
    _api.QTimer.singleShot(int(delay_ms),
                           lambda g=gen: self._finish_preroll_unmute(g))

def _finish_preroll_unmute(self, gen=None):
    if gen is not None and gen != getattr(self, "_preroll_unmute_gen", 0):
        return
    if not getattr(self, "_preroll_unmute_pending", False):
        return
    self._preroll_unmute_pending = False
    try:
        self.audio_output.setMuted(False)
    except Exception:
        pass

def _flush_preroll_mute(self):
    """Немедленно приводит mute в пользовательское состояние: «Воспроизвести»
        нажато в окне отложенного возврата (см. _restore_preroll_mute), и ждать
        нельзя — иначе воспроизведение началось бы беззвучным."""
    self._preroll_unmute_gen = getattr(self, "_preroll_unmute_gen", 0) + 1
    if not getattr(self, "_preroll_unmute_pending", False):
        return
    self._preroll_unmute_pending = False
    try:
        self.audio_output.setMuted(bool(getattr(self, "_preroll_prev_muted", False)))
    except Exception:
        pass

def _preroll_timer(self):
    """Таймер-сторож разбега (создаётся один раз, см. _PREROLL_POLL_MS)."""
    t = getattr(self, "_preroll_watch_timer", None)
    if t is None:
        t = _api.QTimer(self)
        t.setInterval(self._PREROLL_POLL_MS)
        t.timeout.connect(self._preroll_tick)
        self._preroll_watch_timer = t
    return t

def _preroll_tick(self):
    """Позиция дошла до цели — тормозим разбег (или, если пользователь уже
        нажал «Воспроизвести», снимаем mute и отдаём ему воспроизведение)."""
    tgt = getattr(self, "_preroll_target_ms", None)
    handoff = getattr(self, "_preroll_handoff", False)
    if tgt is None or not (handoff or getattr(self, "_prerolling", False)):
        self._preroll_timer().stop()
        return
    try:
        pos = self.player.position()
        # Пока play() не отработал, тормозить нечего: pause() в одном такте
        # с play() ffmpeg-бэкенд теряет, и плеер уезжает играть дальше.
        if (self.player.playbackState()
                != _api.QMediaPlayer.PlaybackState.PlayingState):
            return
    except Exception:
        return
    if pos < tgt - self._PREROLL_GUARD_MS:
        return
    if handoff:
        self._preroll_handoff_finish()
    else:
        self._preroll_finish(getattr(self, "_preroll_gen", 0))

def _preroll_watch(self, pos_ms):
    """Резервный сторож разбега по positionChanged: сигнал приходит раз в
        ~50 мс, поэтому обычно первым срабатывает _preroll_tick (5 мс). Оставлен
        на случай, если таймер не успел (загруженный интерфейс)."""
    if not (getattr(self, "_prerolling", False)
            or getattr(self, "_preroll_handoff", False)):
        return
    tgt = getattr(self, "_preroll_target_ms", None)
    if tgt is None:
        return
    if pos_ms >= tgt - self._PREROLL_GUARD_MS:
        if getattr(self, "_preroll_handoff", False):
            self._preroll_handoff_finish()
        else:
            self._preroll_finish(getattr(self, "_preroll_gen", 0))

def _preroll_handoff_finish(self):
    """Разбег доигран до цели, а «Воспроизвести» уже нажато: просто снимаем
        mute и отпускаем покадровый слой. Ни паузы, ни перемотки — конвейер как
        играл, так и играет, поэтому звук появляется ровно на цели и мгновенно."""
    if not getattr(self, "_preroll_handoff", False):
        return
    self._preroll_handoff = False
    self._preroll_target_ms = None
    try:
        self._preroll_timer().stop()
    except Exception:
        pass
    try:
        self.audio_output.setMuted(self._preroll_prev_muted)
    except Exception:
        pass
    # Воспроизведение успели остановить (Пробел ещё раз, СТОП, граница OUT) —
    # тогда мы просто возвращаем mute: пин точного кадра там уже поставлен
    # паузой, и снимать его нельзя.
    try:
        if self.player.playbackState() != _api.QMediaPlayer.PlaybackState.PlayingState:
            return
    except Exception:
        return
    self._release_frame_lock()

def _preroll_finish(self, gen=None, forced=False):
    if not getattr(self, "_prerolling", False):
        return
    if gen is not None and gen != getattr(self, "_preroll_gen", 0):
        return          # это хвост от ПРЕДЫДУЩЕГО прогрева
    self._prerolling = False
    try:
        self._preroll_timer().stop()
    except Exception:
        pass
    tgt = getattr(self, "_preroll_target_ms", None)
    self._preroll_target_ms = None
    try:
        self.player.pause()
        if tgt is not None:
            # Возвращаемся назад ТОЛЬКО при ГРУБОМ промахе: лишний seek — это
            # та самая раскрутка конвейера, ради избавления от которой прогрев
            # и переделан (см. докстроку _preroll_at). Порог не «кадр», как
            # было: с кадровым порогом перемотка срабатывала практически
            # всегда (часы плеера меняются шагами по ~40–60 мс), и каждое
            # воспроизведение после перемотки начиналось с ~0.35 с тишины.
            tol = max(self._PREROLL_SNAP_MS,
                      int(1000.0 / self.fps) if (self.fps and self.fps > 0) else 40)
            if abs(self.player.position() - tgt) > tol:
                self.player.setPosition(tgt)
            t_s = tgt / 1000.0
            if self._grid.valid:
                if self._frame_idx is None:
                    self._frame_idx = self._grid.index_at(t_s)
                # Метка и волна показывают НАЧАЛО кадра — ровно то, что
                # на экране; цель прогрева (середина кадра) сюда не идёт.
                t_s = self._grid.start_of(self._frame_idx)
                self._show_exact_frame(self._frame_idx)
            self.waveform.set_playhead(t_s)
            self.lbl_current_time.setText(_api.s_to_time(t_s))
    except Exception:
        pass
    # Восстанавливаем прежнее состояние mute (могло быть включено внешней
    # озвучкой — тогда звук видео должен остаться немым). Отложенно: сразу
    # после pause() устройство ещё доигрывает очередь — см. _restore_preroll_mute.
    self._restore_preroll_mute()

def _release_frame_lock(self):
    """Отпускает покадровый слой перед воспроизведением: снимает пин с холста
        и отменяет фоновое декодирование кадров."""
    self._frame_idx = None
    vw = getattr(self, "video_widget", None)
    if isinstance(vw, _api.VideoCanvas):
        vw.clear_frame_pin()
    eng = getattr(self, "_frames", None)
    if eng is not None:
        eng.cancel()
