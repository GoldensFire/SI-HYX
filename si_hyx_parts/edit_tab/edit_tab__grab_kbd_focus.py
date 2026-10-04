# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _grab_kbd_focus. Public namespace: edit_tab."""
import edit_tab as _api


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
