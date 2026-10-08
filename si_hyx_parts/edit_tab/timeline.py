# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: волна, отметки и undo, покадровый шаг, предпрокрутка и звук скраба."""
import edit_tab as _api


class EditTabTimelineMixin:
    """Монтаж: волна, отметки и undo, покадровый шаг, предпрокрутка и звук скраба."""

    def _grab_kbd_focus(self):
        """Возвращает фокус на вкладку или активное полноэкранное окно плеера."""
        try:
            target = getattr(self, "_fs_window", None)
            if target is None:
                target = self
            elif target.bar.isActiveWindow():
                target = target.bar
            target.setFocus(_api.Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def start_waveform_loading(self):
        a_idx = self.audio_stream_index if not self.is_proxy_active else None
        self._start_waveform(self.filepath, a_idx)

    @staticmethod
    def _file_cache_stamp(path):
        """(mtime, size) файла — ключ инвалидации кэша по факту его изменения
        на диске (не просто по пути, который может указывать на подменённый файл)."""
        try:
            st = _api.os.stat(path)
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def _start_waveform(self, filepath, audio_index, prioritize_selection=False):
        """Запускает (или перезапускает) построение аудиоволны для конкретного
        файла и индекса дорожки. Используется и при загрузке файла, и при смене
        озвучки — тогда волна перестраивается под новую дорожку.
        prioritize_selection=True (смена аудиодорожки) — сперва запускает
        быстрый проход ТОЛЬКО по текущему выделению IN/OUT (обычно секунды),
        чтобы сразу показать/дать проверить нужный кусок, не дожидаясь полного
        прохода по всему файлу; полный проход всё равно идёт следом и
        подменяет собой предпросмотр, когда досчитается."""
        if not filepath:
            return
        self._waveform_gen = getattr(self, "_waveform_gen", 0) + 1
        gen = self._waveform_gen
        stamp = self._file_cache_stamp(filepath)
        cache_key = (str(filepath), audio_index, stamp) if stamp else None
        cached = self._waveform_cache.get(cache_key) if cache_key else None
        # Снимаем предыдущие воркеры (полный + быстрый предпросмотр выделения),
        # чтобы устаревшая волна старой дорожки не прилетела последней.
        if self.audio_worker and self.audio_worker.isRunning():
            try:
                self.audio_worker.stop(); self.audio_worker.wait()
            except Exception:
                pass
        if self._audio_partial_worker and self._audio_partial_worker.isRunning():
            try:
                self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
            except Exception:
                pass
        if cached is not None:
            self._waveform_cache_key = None
            self.on_waveform_ready(gen, *cached)
            return
        self.waveform.set_loading("Загрузка волны...")
        self._waveform_cache_key = cache_key
        seg_in, seg_out = self.current_in, self.current_out
        if (prioritize_selection and self.duration > 0
                and 0 <= seg_in < seg_out <= self.duration
                and (seg_out - seg_in) < self.duration - 0.5):
            seg_worker = _api.AudioSegmentWaveformLoader(str(filepath), audio_index,
                                                     seg_in, seg_out, self.duration)
            seg_worker.finished.connect(
                lambda samples, s_in, s_out, l, r, g=gen:
                    self.on_waveform_partial_ready(g, samples, s_in, s_out, l, r))
            self._audio_partial_worker = seg_worker
            seg_worker.start()
        self.audio_worker = _api.AudioWaveformLoader(str(filepath), audio_index,
                                                self.duration)
        self.audio_worker.finished.connect(
            lambda samples, dur, l, r, g=gen: self.on_waveform_ready(g, samples, dur, l, r))
        self.audio_worker.progress.connect(self._on_waveform_progress)
        self.audio_worker.start()

    def _on_waveform_progress(self, text):
        # Если волна уже частично заполнена (быстрый предпросмотр выделения —
        # см. prioritize_selection), set_loading() её бы стёр; тогда прогресс
        # полного прохода пишем в строку лога вместо полосы волны.
        if self.waveform.samples:
            self.log_label.setText(text)
        else:
            self.waveform.set_loading(text)

    def on_waveform_partial_ready(self, gen, samples, seg_in, seg_out, left=None, right=None):
        if gen != getattr(self, "_waveform_gen", gen):
            return
        if not samples or self.duration <= 0:
            return
        self.waveform.set_partial_data(samples, seg_in, seg_out, self.duration, left, right)

    def on_waveform_ready(self, gen, samples, duration, left=None, right=None):
        if gen != getattr(self, "_waveform_gen", gen):
            return
        cache_key = getattr(self, "_waveform_cache_key", None)
        if cache_key is not None:
            self._waveform_cache_key = None
            self._waveform_cache[cache_key] = (samples, duration, left, right)
            if len(self._waveform_cache) > 8:
                self._waveform_cache.pop(next(iter(self._waveform_cache)))
        use_duration = self.duration if (self.duration and self.duration > 0) else duration
        if duration > 0 and use_duration < (duration - 0.05):
            use_duration = duration
        # Длительность из контейнера могла не определиться (format.duration пуст) —
        # тогда current_out осталась ~0.001, зона воспроизведения вырождена: плеер
        # сразу упирается в OUT (видео «не играется»), а в начале таймлайна слипаются
        # маркеры IN/OUT. Берём длительность из аудиоволны и раскрываем зону на всё.
        if use_duration > 0 and (self.duration <= 0 or self.current_out <= 0.002
                                 or (self.current_out - self.current_in) < 0.003):
            self.duration = use_duration
            self.lbl_duration.setText(_api.s_to_time(self.duration))
            self.current_in = 0.0
            self.current_out = use_duration
        self._update_total_time()
        self.waveform.set_data(samples, use_duration, left, right)
        # Восстанавливаем выделение пользователя после загрузки волны
        # (waveform.set_in_out пошлёт selectionChanged → синхронизация полей/кадров).
        self.waveform.set_in_out(self.current_in, self.current_out)
        self.update_pan_slider_values()
        # Восстановление обрезки после отмены «Очистить» (Ctrl+Z) — применяем
        # ПОСЛЕ того, как длительность/волна устаканились (иначе перезатёрлась бы).
        pend = getattr(self, "_pending_restore_in_out", None)
        if pend is not None:
            self._pending_restore_in_out = None
            self.set_in_out(pend[0], pend[1], skip_undo=True)

    # ── Undo / Redo ───────────────────────────────────────────────────────
    def push_undo(self):
        state = (self.current_in, self.current_out)
        if self.undo_stack:
            li, lo = self.undo_stack[-1]
            if abs(li - state[0]) < 0.001 and abs(lo - state[1]) < 0.001:
                return
        self.undo_stack.append(state)   # deque auto-trims at maxlen=50
        self.redo_stack.clear()

    def undo(self):
        # Отмена «Очистить»: восстанавливаем выгруженный файл и его обрезку
        # (свой undo-стек был очищен вместе с файлом).
        snap = getattr(self, "_cleared_snapshot", None)
        if snap and not self.filepath:
            self._cleared_snapshot = None
            if _api.os.path.exists(snap['path']):
                self.load_file(snap['path'])
                self._pending_restore_in_out = (snap['in'], snap['out'])
            return
        # Пропускаем «пустые» снимки, равные текущему состоянию: они появлялись,
        # когда действие не меняло in/out (напр. «Обрезать старт/конец» по кнопке,
        # когда плейхед уже стоит на границе) — push_undo всё равно клал снимок, и
        # из-за этого первый Ctrl+Z «не срабатывал» (отменял в то же состояние,
        # визуально ничего не происходило). Откатываемся до ПЕРВОГО отличающегося.
        cur = (self.current_in, self.current_out)
        while self.undo_stack:
            prev = self.undo_stack.pop()
            if abs(prev[0] - cur[0]) > 1e-4 or abs(prev[1] - cur[1]) > 1e-4:
                self.redo_stack.append(cur)
                self.set_in_out(prev[0], prev[1], skip_undo=True)
                return

            # prev == cur — это пустой снимок, отбрасываем и ищем дальше.

    def redo(self):
        cur = (self.current_in, self.current_out)
        while self.redo_stack:
            nxt = self.redo_stack.pop()
            if abs(nxt[0] - cur[0]) > 1e-4 or abs(nxt[1] - cur[1]) > 1e-4:
                self.undo_stack.append(cur)
                self.set_in_out(nxt[0], nxt[1], skip_undo=True)
                return

    # ── In / Out ──────────────────────────────────────────────────────────
    def _set_frame_spins(self, in_s, out_s):
        """Обновляет спинбоксы кадров, не вызывая valueChanged (защита от рекурсии)."""
        self.in_frame_spin.blockSignals(True)
        self.out_frame_spin.blockSignals(True)
        if self.fps and self.fps > 0:
            self.in_frame_spin.setValue(int(round(in_s * self.fps)))
            self.out_frame_spin.setValue(int(round(out_s * self.fps)))
        else:
            self.in_frame_spin.setValue(0); self.out_frame_spin.setValue(0)
        self.in_frame_spin.blockSignals(False)
        self.out_frame_spin.blockSignals(False)

    def set_in_out(self, in_s, out_s, skip_undo=False, keep_view=True):
        self.current_in  = max(0.0, min(in_s,  self.duration))
        self.current_out = max(0.0, min(out_s, self.duration))
        if self.current_out <= self.current_in:
            self.current_out = min(self.duration, self.current_in + 0.001)
        self.in_time_edit.setText(_api.s_to_time(self.current_in))
        self.out_time_edit.setText(_api.s_to_time(self.current_out))
        self._set_frame_spins(self.current_in, self.current_out)
        # keep_view=True по умолчанию: обрезка не перематывает окно таймлайна.
        self.waveform.set_in_out(self.current_in, self.current_out, keep_view=keep_view)
        self.update_selection_label(); self.update_pan_slider_values()
        self._update_seg_duration()

    def set_in_point(self):
        self.push_undo()
        try:
            t = _api.time_to_s(self.in_time_edit.text())
        except Exception:
            t = self._ui_time_s()
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - 0.04)
        self.set_in_out(new_in, self.current_out)

    def set_out_point(self):
        self.push_undo()
        try:
            t = _api.time_to_s(self.out_time_edit.text())
        except Exception:
            t = self._ui_time_s()
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + 0.04)
        self.set_in_out(self.current_in, new_out)

    def on_in_frame_changed(self, frame):
        if not (self.fps and self.fps > 0) or self.duration <= 0:
            return
        self.push_undo()
        t = frame / self.fps
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - (1.0 / self.fps))
        self.set_in_out(new_in, self.current_out)

    def on_out_frame_changed(self, frame):
        if not (self.fps and self.fps > 0) or self.duration <= 0:
            return
        self.push_undo()
        t = frame / self.fps
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + (1.0 / self.fps))
        self.set_in_out(self.current_in, new_out)

    def on_wave_seek(self, t):     self.seek_to(t)

    def on_wave_playseek(self, t): self.seek_to(t)

    def on_wave_selection_changed(self, new_in, new_out):
        self.current_in = new_in; self.current_out = new_out
        self.in_time_edit.setText(_api.s_to_time(new_in))
        self.out_time_edit.setText(_api.s_to_time(new_out))
        self._set_frame_spins(new_in, new_out)
        self.update_selection_label()
        # Двигаем красную/зелёную полоску ВО ВРЕМЯ воспроизведения → обновляем
        # границу авто-паузы painted-режима. Иначе VideoCanvas держит СТАРЫЙ OUT
        # и стопит/телепортит плеер на прежнем месте зелёной полоски (баг).
        try:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self._set_play_bound(True)
        except Exception:
            pass

    def update_selection_label(self):
        # Показываем только итоговую длительность будущего ролика (без таймкодов
        # начала/конца — они и так есть в полях IN/OUT).
        dur = max(0.0, self.current_out - self.current_in)
        self.lbl_selection.setText(
            f"{_api.icon_html('fa5s.stopwatch', 13, _api.C['text'])}  Итог: {_api.s_to_time(dur)}")

    def _resize_montage_side_btns(self, col_h):
        """Кнопки боковой панели монтажа — квадратные, в две колонки по 4 (место
        под 8 штук); сторона квадрата = высота колонки на ровно 4 ряда."""
        btns = getattr(self, "_montage_side_btns", None)
        if not btns or col_h <= 0:
            return
        rows = self._MSIDE_COUNT // 2
        avail = max(0, int(col_h) - self._MSIDE_GAP * (rows - 1))
        bh = max(24, min(40, avail // rows))
        isz = max(14, min(22, bh - 12))
        for b in btns:
            b.setFixedSize(bh, bh)
            b.setIconSize(_api.QSize(isz, isz))

    @staticmethod
    def _relax_width(wdg):
        """Снимает минимальную «требуемую» ширину виджета (горизонтальная политика
        Ignored): он не распирает правую панель по длине своего текста, а тянется
        по доступному месту (текст при нехватке укорачивается). НЕ применять к
        меткам в строках инфо-карточек (там есть stretch — схлопнутся в 0)."""
        sp = wdg.sizePolicy()
        sp.setHorizontalPolicy(_api.QSizePolicy.Policy.Ignored)
        wdg.setSizePolicy(sp)

    def _update_total_time(self):
        """Обновляет общее время в плеере (00:00 / ОБЩЕЕ под видео)."""
        lbl = getattr(self, "lbl_total_time", None)
        if lbl is not None:
            lbl.setText(_api.s_to_time(self.duration if self.duration and self.duration > 0 else 0.0))

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

    # ── Покадровый движок: кадры, часы, буфер ────────────────────────────────
    def _frames_engine(self):
        """Ленивая инициализация предекодера кадров (поток создаётся при первом
        файле с видео, а не при запуске приложения)."""
        eng = getattr(self, "_frames", None)
        if eng is None:
            eng = _api.FramePrefetcher(self)
            eng.ready.connect(self._on_exact_frame)
            eng.start()
            self._frames = eng
        return eng

    def _frames_set_source(self):
        """Переводит предекодер на ТОТ ЖЕ файл, что играет плеер (оригинал или
        превью-прокси): стоп-кадр обязан выглядеть ровно так же, как
        воспроизведение, иначе на паузе картинка «дёргалась» бы в резкость."""
        src = str(self.filepath) if self.filepath else None
        has_video = (self.video_stream_index is not None
                     and not getattr(self, "is_still_image", False))
        if not has_video or not src:
            eng = getattr(self, "_frames", None)
            if eng is not None:
                eng.set_source(None)
            self._frames_src = None
            return
        eng = self._frames_engine()
        eng.set_source(src, self.fps or 0.0)
        self._frames_src = src

    def _refresh_frame_grid(self):
        """Пересобирает сетку кадров (fps/длительность могли измениться)."""
        self._grid = _api.FrameGrid(self.fps or 0.0, self.duration or 0.0)

    def _current_frame_index(self):
        """Номер кадра, на котором СЕЙЧАС стоит монтаж.

        На паузе истина — _frame_idx (его ведут seek/шаг/остановка): позиция
        плеера после seek'а может отличаться от запрошенной на доли кадра, и
        считать шаг от неё значило бы копить ту же ошибку, что и раньше.
        Во время воспроизведения истина — pts ПОКАЗАННОГО кадра (часы кадра),
        и только если их нет (аудиофайл, overlay-режим) — позиция плеера."""
        grid = self._grid
        if not grid.valid:
            return 0
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        if not playing and self._frame_idx is not None:
            return grid.clamp(self._frame_idx)
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            pts = vw.last_frame_pts()
            if pts is not None:
                return grid.index_of_pts(pts)
        try:
            return grid.index_at(self.player.position() / 1000.0)
        except Exception:
            return 0

    def _clock_pos_s(self):
        """Время монтажа для ИНТЕРФЕЙСА — то, что реально видно на экране.

        Мастер-часы: во время игры это pts последнего показанного кадра (Qt
        рендерит кадры по аудио-часам, так что метка идёт за звуком, но при этом
        гарантированно совпадает с картинкой); на паузе — начало кадра, который
        пришпилен к холсту. Раньше метка жила по player.position(), который
        опрашивался таймером раз в 80 мс и к картинке отношения не имел — отсюда
        и ощущение, что видео, звук и метка разъезжаются."""
        try:
            pos_s = self.player.position() / 1000.0
        except Exception:
            pos_s = 0.0
        vw = getattr(self, "video_widget", None)
        if (not isinstance(vw, _api.VideoCanvas) or self.video_stream_index is None
                # «Только звук»: кадров нет вовсе, часы кадра застыли бы на
                # последнем показанном — ведём время по плееру, как для аудио.
                or getattr(self, "_audio_only_mode", False)):
            return pos_s
        pts = vw.last_frame_pts()
        if pts is None:
            return pos_s
        age = vw.frame_clock_age()
        try:
            playing = (self.player.playbackState()
                       == _api.QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        if playing:
            # Часы кадра «живые» — берём их. Если кадры перестали приходить
            # (декодер захлебнулся/нет видео) — возвращаемся к часам плеера,
            # иначе метка замерла бы вместе с картинкой.
            if age is not None and age < 0.35:
                return pts
            return pos_s
        # На паузе показанный кадр и есть текущее время — но только если он
        # действительно наш (пин с картинкой, часы в его диапазоне), а не
        # случайный кадр после смены источника: заявленный, но не приехавший пин
        # раньше отдавал pts ПРОШЛОГО кадра, и метка «замерзала» на нём.
        pinned = vw.pinned_frame_pts()
        if pinned is not None:
            return pinned
        # Точный кадр ещё едет из предекодера (после остановки буфер пуст, и это
        # сотни миллисекунд). Позиция плеера сюда не годится: она живёт по
        # аудио-часам и расходится с показанным кадром — на этом расхождении
        # жёлтая полоса после паузы прыгала вперёд, а затем возвращалась назад,
        # когда кадр доезжал. На паузе истина — номер кадра, на котором стоит
        # монтаж (его ведут шаг, перемотка и сама остановка).
        grid = getattr(self, "_grid", None)
        idx = getattr(self, "_frame_idx", None)
        if grid is not None and grid.valid and idx is not None:
            return grid.start_of(idx)
        return pos_s

    def _show_exact_frame(self, idx=None, direction=1):
        """Ставит на холст ТОЧНЫЙ кадр idx и заказывает соседние в буфер.

        Кадр из буфера рисуется мгновенно (0 мс, без ожидания плеера), чего от
        QMediaPlayer добиться нельзя в принципе; если кадра ещё нет — «пин»
        просто объявляет, какой кадр сейчас правильный, и холст перестаёт
        показывать чужие кадры, как только точный доедет."""
        grid = self._grid
        vw = getattr(self, "video_widget", None)
        if (not grid.valid or not isinstance(vw, _api.VideoCanvas)
                or self.video_stream_index is None
                or getattr(self, "is_still_image", False)
                # «Только звук»: картинки нет — гонять ffmpeg за кадрами незачем
                # (ровно от этой работы пользователь и уходит, включая режим).
                or getattr(self, "_audio_only_mode", False)):
            return
        # Во время НАСТОЯЩЕГО воспроизведения пин не ставим ни при каких
        # обстоятельствах (например, стрелка нажата на ходу): иначе холст начал
        # бы отбрасывать кадры плеера как чужие и картинка бы встала. Прогрев
        # («с разбега») — исключение: там играем мы сами и как раз прячем разбег.
        try:
            if (self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
                    and not getattr(self, "_prerolling", False)):
                return
        except Exception:
            pass
        idx = self._current_frame_index() if idx is None else grid.clamp(idx)
        span = grid.pts_span_us(idx)
        vw.arm_frame_pin(span)
        eng = self._frames_engine()
        if self._frames_src != (str(self.filepath) if self.filepath else None):
            self._frames_set_source()
        img = eng.frame(idx)
        if img is not None:
            vw.set_exact_frame(img, span, int(grid.start_of(idx) * 1_000_000))
        # Буфер вокруг плейхеда: шагаем вперёд — греем кадры впереди, назад —
        # позади. Сам кадр idx всегда декодируется первым (см. FramePrefetcher).
        if direction >= 0:
            eng.request(idx, ahead=14, behind=3)
        else:
            eng.request(idx, ahead=2, behind=14)

    def _paint_playhead(self, t_s):
        """Рисует положение плейхеда: метка времени, полоса, жёлтая линия на
        волне, «старт→плейхед» и полноэкранная панель. Одно место на все
        источники времени (кадр, позиция плеера, точный кадр из буфера)."""
        self.lbl_current_time.setText(_api.s_to_time(t_s))
        if self.duration and self.duration > 0 and not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int((t_s / self.duration) * 1000))
            self.slider.blockSignals(False)
        self.waveform.set_playhead(t_s)
        self._update_seg_duration(t_s)
        self._fs_sync_position()

    def _on_exact_frame(self, idx, img):
        """Точный кадр доехал из предекодера — показываем, если монтаж всё ещё
        стоит на нём (иначе это устаревший результат прошлого шага)."""
        try:
            # Прогрев — не воспроизведение: там играем мы сами, под mute, и кадр
            # цели на холсте нужен именно наш (иначе, пока идёт разбег, экран
            # остался бы на старом кадре — а пользователь его уже перемотал).
            if (self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
                    and not getattr(self, "_prerolling", False)):
                return
        except Exception:
            return
        if self._frame_idx is None or int(idx) != int(self._frame_idx):
            return
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, _api.VideoCanvas) or not self._grid.valid:
            return
        vw.set_exact_frame(img, self._grid.pts_span_us(idx),
                           int(self._grid.start_of(idx) * 1_000_000))
        # Кадр сменился — метка/полоса/волна обязаны показать ЕГО время.
        self._paint_playhead(self._grid.start_of(idx))

    def step_frame(self, step):
        if not self.duration:
            return
        grid = self._grid
        if not grid.valid:
            # fps неизвестен (битые метаданные) — старое поведение по времени.
            ms = (self._scrub_target if (getattr(self, "_scrubbing", False)
                                         and self._scrub_target is not None)
                  else self.player.position())
            new_ms = max(0, min(int(self.duration * 1000), ms + int(step * 40)))
            self._scrub_target = new_ms
            self._scrub_audio_ms = new_ms
            self._dispatch_frame_seek(new_ms)
            return
        # Шаг считаем в КАДРАХ от текущего кадра — не в миллисекундах от позиции
        # плеера. Так серия шагов (удержание ←/→) детерминирована и не копит
        # ошибку округления, а «туда-обратно» возвращает ровно тот же кадр.
        idx = grid.clamp(self._current_frame_index() + int(step))
        self._frame_idx = idx
        # Плееру отдаём СЕРЕДИНУ кадра: она дальше полукадра от границ, поэтому
        # округление до миллисекунд не может перекинуть его на соседний кадр.
        new_ms = grid.ms_of(idx)
        self._scrub_target = new_ms
        # А звук скраба начинается с НАЧАЛА кадра — там же, где картинка.
        self._scrub_audio_ms = int(round(grid.start_of(idx) * 1000.0))
        # Кадр на холст — сразу из буфера (не ждём плеер).
        self._show_exact_frame(idx, direction=step)
        # Реальный player.setPosition() диспетчеризуем через _dispatch_frame_seek:
        # держать ←/→ = автоповтор ОС шлёт events быстрее, чем плеер успевает
        # довести seek до кадра, и они раньше просто копились в очереди — отсюда
        # «догоняющий» скачок на несколько секунд ПОСЛЕ отпускания клавиши.
        # Теперь в полёте не больше одного seek'а: новая цель ЗАМЕНЯЕТ предыдущую
        # отложенную, и в итоге всегда доезжаем ровно до последней зажатой цели.
        self._dispatch_frame_seek(new_ms)

    def _dispatch_frame_seek(self, new_ms):
        """Доводит позицию ПЛЕЕРА до выбранного кадра.

        Во время серии шагов (удержание ←/→) плееру достаётся не каждый шаг, а
        не чаще _SCRUB_SEEK_MS. Картинку на экране даёт предекодер, звук —
        скраббер; плееру позиция нужна только чтобы было откуда продолжить
        воспроизведение. А каждый его setPosition на тяжёлом источнике (HEVC
        1080p, длинный GOP) — это полная раскрутка GOP в декодере, причём
        параллельно с предекодером, который в это же время декодирует ТЕ ЖЕ
        кадры: два декодера дрались за процессор, и удержание стрелки лагало.
        Накопленную позицию досылает _flush_frame_seek, когда серия кончилась."""
        if getattr(self, "_scrubbing", False):
            now = _api.time.monotonic()
            if (now - getattr(self, "_frame_seek_last_at", 0.0)) * 1000.0 < self._SCRUB_SEEK_MS:
                self._frame_seek_deferred_ms = new_ms
                return
            self._frame_seek_last_at = now
        self._send_frame_seek(new_ms)

    def _flush_frame_seek(self):
        """Досылает плееру позицию, накопленную серией шагов (конец серии, нажатие
        «Воспроизвести»). Без неё плеер продолжил бы с кадра, на котором
        троттлинг остановил его в последний раз."""
        ms = getattr(self, "_frame_seek_deferred_ms", None)
        if ms is None:
            return
        self._frame_seek_last_at = _api.time.monotonic()
        self._send_frame_seek(ms)

    def _send_frame_seek(self, new_ms):
        self._frame_seek_deferred_ms = None
        if getattr(self, "_frame_seek_busy", False):
            self._frame_seek_pending = new_ms   # копим только САМУЮ СВЕЖУЮ цель
            return
        self._frame_seek_busy = True
        self._frame_seek_target_ms = new_ms
        self._frame_seek_gen = getattr(self, "_frame_seek_gen", 0) + 1
        gen = self._frame_seek_gen
        self.player.setPosition(new_ms)
        self._ext_audio_seek(new_ms)
        # Запасной выход — ТОЛЬКО если on_position_changed сам не подтвердит
        # доезд до цели (см. _confirm_frame_seek). Окно щедрое (не 100-200мс):
        # на тяжёлом HEVC без ближайшего кейфрейма один seek может декодировать
        # секунду и дольше, а слишком короткий запасной таймер сам стал бы
        # источником бага — «отпускал» бы busy раньше, чем предыдущий seek
        # реально доехал, и держащаяся стрелка перебивала бы декодирование
        # снова и снова, так и не давая ни одному кадру долистать до конца
        # (ровно то поведение — «зажал на 10с, показали 1 кадр» — которое
        # чиним). gen — чтобы устаревший запасной таймер не «отпустил» уже
        # ДРУГОЙ, более поздний seek.
        _api.QTimer.singleShot(2500, lambda: self._release_frame_seek(gen))

    def _confirm_frame_seek(self, pos_ms):
        """Вызывается из on_position_changed на каждое реальное изменение позиции:
        как только плеер довёл её до запрошенной цели — освобождаем «в полёте»
        сразу, не дожидаясь запасного таймера (и шлём накопившуюся свежую цель,
        если пользователь всё ещё держит стрелку)."""
        if not getattr(self, "_frame_seek_busy", False):
            return
        target = getattr(self, "_frame_seek_target_ms", None)
        if target is None:
            return
        tol_ms = max(20, int(1000.0 / self.fps)) if (self.fps and self.fps > 0) else 40
        if abs(pos_ms - target) <= tol_ms:
            self._release_frame_seek(self._frame_seek_gen)

    def _release_frame_seek(self, gen=None):
        if gen is not None and gen != getattr(self, "_frame_seek_gen", None):
            return   # устаревший вызов — «в полёте» уже другая, более поздняя цель
        self._frame_seek_busy = False
        self._frame_seek_target_ms = None
        pending = getattr(self, "_frame_seek_pending", None)
        if pending is not None:
            self._frame_seek_pending = None
            self._dispatch_frame_seek(pending)

    def step_frame_scrub(self, step):
        # Идёт беззвучный прогрев — гасим его ДО шага: иначе плеер играет (пусть
        # и под mute), а мы тут же дёргаем ему позицию, и они мешают друг другу.
        # Именно cancel, а не finish: доводить позицию до УСТАРЕВШЕЙ цели незачем,
        # шаг сейчас поставит свою — лишний seek только съел бы кадр времени.
        # Прогрев вернётся, когда серия шагов утихнет (см. _end_scrub_painted).
        if getattr(self, "_prerolling", False):
            self._preroll_cancel()
        playing = (self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState)
        painted = isinstance(self.video_widget, _api.VideoCanvas)
        # Серия шагов: при удержании ←/→ считаем от _scrub_target (детерминизм),
        # а на ПЕРВОМ шаге серии — от живой позиции плеера.
        if not playing and not getattr(self, "_scrubbing", False):
            self._scrub_target = None
            # Начало серии: первый шаг обязан дойти до плеера сразу (см.
            # _dispatch_frame_seek — дальше он троттлится).
            self._frame_seek_last_at = 0.0
        if not playing:
            self._scrubbing = True
            if painted:
                # Пока идёт перемотка, ЦП-копия кадров плеера не нужна: на экране
                # всё равно точный кадр предекодера, а toImage() каждого кадра
                # 1080p занимает главный поток на 8–9 мс (см. VideoCanvas.
                # _want_cpu_copy) — при удержании стрелки это и был видимый лаг.
                self.video_widget.set_scrub_active(True)
        self.step_frame(step)
        if playing:
            return
        # Скраб-звук (как в Filmora): короткий звуковой блип в новой позиции.
        # В painted-режиме видео уже доставлено setPosition'ом — звук добавляем,
        # не трогая кадр (см. _scrub_audio_blip).
        self._scrub_audio_blip(painted)
        # Оживляем индикатор уровня и на покадровом шаге (на паузе он иначе молчит,
        # из-за чего казалось, что звука нет).
        tgt_ms = getattr(self, "_scrub_audio_ms", None)
        if tgt_ms is None:
            tgt_ms = (self._scrub_target if self._scrub_target is not None
                      else self.player.position())
        self._update_meter((tgt_ms or 0) / 1000.0, force=True)
        if painted:
            # painted-режим (VideoCanvas + QVideoSink): пауза + setPosition сама
            # доставляет новый кадр в сink — короткий play() НЕ нужен (именно он
            # давал мерцание/скачок назад-вперёд). Флаг скраба снимаем таймером,
            # перезапускаемым на каждом шаге (серия удержания не рвётся).
            if not hasattr(self, "_scrub_reset_timer"):
                self._scrub_reset_timer = _api.QTimer(self)
                self._scrub_reset_timer.setSingleShot(True)
                self._scrub_reset_timer.timeout.connect(self._end_scrub_painted)
            self._scrub_reset_timer.start(160)
            return
        # overlay-режим (QVideoWidget): нативная поверхность без play() кадр не
        # перерисовывает — прежний приём с коротким play() и возвратом на цель.
        self._scrubbing = True
        self.player.play()
        _api.QTimer.singleShot(60, self._end_scrub)

    def _end_scrub_painted(self):
        self._scrubbing = False
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, _api.VideoCanvas):
            vw.set_scrub_active(False)
        # Плееру — итоговая позиция серии (во время неё он получал её не чаще
        # _SCRUB_SEEK_MS, см. _dispatch_frame_seek). Обязательно ДО прогрева:
        # прогрев считает разбег от этой же точки.
        self._flush_frame_seek()
        # Серия покадровых шагов закончилась — прогреваем конвейер там, где
        # встали. Обычный сценарий монтажа «долистал кадрами → Пробел» после
        # этого стартует без заминки (см. _preroll_at). Ни звука (mute), ни
        # движения на шкале (часы заморожены на цели) прогрев не даёт.
        try:
            if (self.player.playbackState()
                    != _api.QMediaPlayer.PlaybackState.PlayingState):
                self._preroll_at(self._playhead_target_s())
        except Exception:
            pass

    def _scrub_audio_engine(self):
        """Лениво поднимает фоновый декодер PCM вокруг плейхеда."""
        eng = getattr(self, "_audio_scrub", None)
        if eng is None:
            eng = _api.AudioScrubber(self)
            eng.ready.connect(self._on_scrub_audio_window)
            eng.start()
            self._audio_scrub = eng
        return eng

    def _scrub_audio_source(self):
        """(файл, поток) для скраб-звука: внешняя озвучка, если выбрана, иначе
        ОРИГИНАЛ (не прокси: у прокси звук пережат в AAC, а дорожка может быть
        и не одна). Поток — абсолютный индекс выбранной дорожки, чтобы звук шага
        совпадал с тем, что играет плеер."""
        if getattr(self, "audio_disabled", False):
            return (None, "a:0")          # пункт «Нет»: шаг кадра без звука
        ext = getattr(self, "selected_audio_ext_path", None)
        if ext:
            return (str(ext), "a:0")
        src = getattr(self, "actual_source_file", None)
        if not src:
            return (None, "a:0")
        idx = getattr(self, "selected_audio_abs_index", None)
        return (str(src), str(int(idx)) if idx is not None else "a:0")

    def _sync_scrub_audio_source(self):
        """Держит источник скраб-звука в согласии с выбранной дорожкой."""
        src, stream = self._scrub_audio_source()
        if not src:
            return None
        eng = self._scrub_audio_engine()
        if eng.source() != (src, stream):
            fmt = self._scrub_sink_format()
            if fmt is not None:
                eng.configure(fmt.sampleRate(), fmt.channelCount(),
                              4 if fmt.sampleFormat() == _api.QAudioFormat.SampleFormat.Float else 2)
            eng.set_source(src, stream)
        return eng

    def _scrub_sink_format(self):
        """Формат вывода для скраб-звука (создаётся один раз под устройство)."""
        fmt = getattr(self, "_scrub_fmt", None)
        if fmt is not None:
            return fmt
        if _api.QAudioFormat is None or _api.QMediaDevices is None:
            return None
        try:
            dev = _api.QMediaDevices.defaultAudioOutput()
            if dev is None or dev.isNull():
                return None
            fmt = _api.QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(_api.QAudioFormat.SampleFormat.Int16)
            if not dev.isFormatSupported(fmt):
                # Устройство не тянет 48 кГц/16 бит — берём его собственный
                # формат и просим ffmpeg отдавать PCM ровно в нём.
                fmt = dev.preferredFormat()
            self._scrub_fmt = fmt
            return fmt
        except Exception:
            return None

    def _scrub_sink(self):
        """QAudioSink для блипов (push-режим). Открывается один раз и живёт:
        pause/play у QMediaPlayer заново открывали бы аудиоустройство, а это на
        Windows заметная задержка — здесь же запись в устройство слышна через
        1–9 мс (замерено)."""
        sink = getattr(self, "_scrub_sink_obj", None)
        if sink is not None:
            return sink
        if _api.QAudioSink is None:
            return None
        fmt = self._scrub_sink_format()
        if fmt is None:
            return None
        try:
            dev = _api.QMediaDevices.defaultAudioOutput()
            sink = _api.QAudioSink(dev, fmt, self)
            # Буфер с запасом на пару срезов: сама задержка звука от него не
            # зависит (устройство играет то, что в очереди, а очередь мы держим
            # короткой — см. _play_scrub_slice), зато длинный срез влезает
            # целиком и не режется.
            bytes_per_s = fmt.sampleRate() * fmt.channelCount() * fmt.bytesPerSample()
            sink.setBufferSize(max(4096, int(bytes_per_s * 0.25)))
            sink.setVolume(self._scrub_volume())
            self._scrub_sink_obj = sink
            # start() стоит ~45 мс (поднимается сеанс WASAPI) — поэтому делаем
            # его РОВНО ОДИН РАЗ, при первом обращении, а дальше только пишем в
            # устройство (запись — 0 мс). Именно поэтому здесь нет ни stop(), ни
            # reset() на каждый шаг: они убивают QIODevice, и следующий шаг
            # платил бы за start() те же 45 мс задержки перед звуком.
            self._scrub_sink_io = sink.start()
            return sink
        except Exception:
            self._scrub_sink_obj = None
            self._scrub_sink_io = None
            return None

    def _scrub_volume(self):
        try:
            return max(0.0, min(1.0, self.vol_slider.value() / 100.0))
        except Exception:
            return 1.0

    def _scrub_blip_seconds(self):
        """Длина блипа: ровно кадр, но в разумных пределах слышимости."""
        fps = float(self.fps or 0.0)
        one = (1.0 / fps) if fps > 0 else self._SCRUB_BLIP_MIN_S
        return max(self._SCRUB_BLIP_MIN_S, min(self._SCRUB_BLIP_MAX_S, one))

    def _scrub_audio_time_s(self):
        """Время, с которого обязан звучать шаг, — НАЧАЛО показанного кадра
        (плееру мы отдаём середину кадра, но слышно должно быть то же, что
        видно). Берём его из НОМЕРА кадра, а не из округлённых миллисекунд."""
        if self._grid.valid and self._frame_idx is not None:
            return self._grid.start_of(self._frame_idx)
        ms = getattr(self, "_scrub_audio_ms", None)
        if ms is None:
            ms = getattr(self, "_scrub_target", None)
        if ms is None:
            try:
                ms = self.player.position()
            except Exception:
                return None
        return max(0.0, ms / 1000.0)

    def _scrub_audio_blip(self, painted=True):
        """Короткий звук нового кадра: точный PCM-срез с pts кадра в устройство.

        В overlay-режиме (QVideoWidget) кадр доставляется коротким play()
        основного плеера, который несёт и звук, — там мы молчим. Исключение —
        выбранная внешняя озвучка: звук видео тогда заглушён, и слышно только
        то, что сыграем здесь."""
        if not getattr(self, "_scrub_audio_enabled", True):
            return
        if not painted and not getattr(self, "_ext_audio_active", False):
            return
        t_s = self._scrub_audio_time_s()
        if t_s is None:
            return
        eng = self._sync_scrub_audio_source()
        if eng is None:
            return
        eng.request(t_s)                    # окно вокруг плейхеда — заранее
        data = eng.slice_at(t_s, self._scrub_blip_seconds())
        if data:
            self._play_scrub_slice(data)
            self._scrub_wait = None
            return
        # Окна ещё нет (первый шаг после загрузки/перемотки) — доиграем, как
        # только фоновый декодер его принесёт (см. _on_scrub_audio_window).
        # Раньше в этом месте звука просто не было — жалоба «при AV1 звук на
        # шаге появляется не всегда».
        self._scrub_wait = (t_s, _api.time.monotonic())

    def _on_scrub_audio_window(self):
        """Окно PCM доехало: если шаг был только что и с тех пор никуда не
        ушли — играем его звук с опозданием, а не молчим."""
        pending = getattr(self, "_scrub_wait", None)
        self._scrub_wait = None
        if not pending or not getattr(self, "_scrub_audio_enabled", True):
            return
        t_s, at = pending
        if _api.time.monotonic() - at > 0.4:
            return                          # поздно, звук был бы «из прошлого»
        cur = self._scrub_audio_time_s()
        if cur is None or abs(cur - t_s) > 0.001:
            return                          # плейхед уже ушёл — играть нечего
        eng = getattr(self, "_audio_scrub", None)
        data = eng.slice_at(t_s, self._scrub_blip_seconds()) if eng else None
        if data:
            self._play_scrub_slice(data)

    def _play_scrub_slice(self, data):
        """Пишет срез в аудиоустройство, НЕ давая очереди расти.

        Очередь длиннее одного среза — это и есть «звук уехал вперёд»: при
        удержании клавиши шаги идут чаще, чем звук успевает проигрываться, и
        хвост копится, а следующий шаг слышится уже с опозданием. Поэтому
        пишем ровно столько, сколько успело проиграться: одиночный шаг звучит
        целиком, а удержание даёт непрерывную перемотку по звуку, отстающую от
        картинки не больше чем на срез."""
        sink = self._scrub_sink()
        io = getattr(self, "_scrub_sink_io", None)
        if sink is None or io is None:
            return
        try:
            sink.setVolume(self._scrub_volume())
            free = int(sink.bytesFree())
            pending = max(0, int(sink.bufferSize()) - free)
            budget = min(free, len(data) - pending)
            if budget <= 0:
                return              # предыдущий срез ещё звучит — не наслаиваем
            io.write(data[:budget])
        except Exception:
            # Устройство могло пропасть (наушники выдернули) — пересоберём.
            self._release_scrub_sink()

    def _release_scrub_sink(self):
        sink = getattr(self, "_scrub_sink_obj", None)
        self._scrub_sink_obj = None
        self._scrub_sink_io = None
        self._scrub_fmt = None
        if sink is not None:
            try:
                sink.stop()
            except Exception:
                pass
            try:
                sink.deleteLater()
            except Exception:
                pass

    def _end_scrub(self):
        self.player.pause()
        # play() ушёл вперёд на ~2 кадра — возвращаем плеер РОВНО на целевой кадр,
        # иначе шаг назад визуально «отскакивал» вперёд (баг).
        tgt = getattr(self, "_scrub_target", None)
        if tgt is not None:
            self.player.setPosition(int(tgt))
            self._ext_audio_seek(int(tgt))
        # Сбрасываем флаг после того, как событие паузы будет обработано.
        _api.QTimer.singleShot(40, lambda: setattr(self, "_scrubbing", False))

    # ── Обрезка до точки воспроизведения (плейхеда) ─────────────────────────
    def trim_start_to_playhead(self):
        """Ставит точку IN на текущую позицию воспроизведения (обрезает старт)."""
        if self.duration <= 0:
            return
        self.push_undo()
        # Берём время ПОКАЗАННОГО кадра, а не «сырую» позицию плеера: они могут
        # отличаться на доли кадра, а рез обязан совпадать с тем, что видно.
        t = self._clock_pos_s()
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - 0.04)
        self.set_in_out(new_in, self.current_out)
        # Возвращаем фокус в текущий режим плеера для последующих сочетаний.
        self._grab_kbd_focus()

    def trim_end_to_playhead(self):
        """Ставит точку OUT на текущую позицию воспроизведения (обрезает конец)."""
        if self.duration <= 0:
            return
        self.push_undo()
        t = self._clock_pos_s()
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + 0.04)
        self.set_in_out(self.current_in, new_out)
        self._grab_kbd_focus()

    def _trim_ctx_menu(self, pos=None):
        """Контекстное меню аудио-визуализации (ПКМ): обрезка старт/конец до
        плейхеда. Сочетания показываются справа как подсказка (через \\t), но НЕ
        регистрируются повторно — настоящие хоткеи висят на QShortcut."""
        if self.duration <= 0:
            return
        menu = _api.QMenu(self)
        a_start = menu.addAction(
            f"Обрезать старт до точки воспроизведения\t{self.trim_start_seq}")
        a_start.triggered.connect(self.trim_start_to_playhead)
        a_end = menu.addAction(
            f"Обрезать конец до точки воспроизведения\t{self.trim_end_seq}")
        a_end.triggered.connect(self.trim_end_to_playhead)
        menu.exec(_api.QCursor.pos())

    # ── Pan slider ────────────────────────────────────────────────────────
    def on_wave_view_changed(self, view_offset, visible_duration):
        self.update_pan_slider_values()
        self.update_wave_scroll()

    # ── Horizontal scrollbar over the waveform ─────────────────────────────
    def on_wave_scroll(self, value):
        """Пользователь двигает горизонтальную прокрутку → смещаем окно обзора волны."""
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            return
        self.waveform.set_view_offset(value / 1000.0)

    def update_wave_scroll(self):
        """Синхронизирует горизонтальную прокрутку с масштабом/положением волны.
        Прячется, когда прокручивать нечего (волна целиком помещается)."""
        sb = getattr(self, "wave_scroll", None)
        if sb is None:
            return
        duration = self.waveform.duration or self.duration or 0.0
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        if duration <= 0 or pan_range <= 1e-6:
            sb.setVisible(False)
            return
        sb.setVisible(True)
        sb.blockSignals(True)
        sb.setMinimum(0)
        sb.setMaximum(int(pan_range * 1000))
        sb.setPageStep(max(1, int(visible * 1000)))
        sb.setSingleStep(max(1, int(visible * 100)))
        sb.setValue(int(self.waveform.view_offset * 1000))
        sb.blockSignals(False)

    def update_pan_slider_values(self):
        pan_row = getattr(self, 'pan_row_w', None)
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            self.pan_slider.setEnabled(False)
            if pan_row is not None:
                pan_row.setVisible(False)
            return
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        if pan_range <= 0.0:
            self.pan_slider.setEnabled(False); self.pan_slider.setValue(0)
            if pan_row is not None:
                pan_row.setVisible(False)
            return
        self.pan_slider.setEnabled(True)
        if pan_row is not None:
            pan_row.setVisible(True)
        val = int((self.waveform.view_offset / pan_range) * 1000) if pan_range > 0 else 0
        self.pan_slider.blockSignals(True)
        self.pan_slider.setValue(max(0, min(1000, val)))
        self.pan_slider.blockSignals(False)

    def on_pan_moved(self, value):
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            return
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        offset = (value / 1000.0) * pan_range if pan_range > 0 else 0.0
        self.waveform.set_view_offset(offset)
