# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: exit_fullscreen. Public namespace: edit_tab."""
import edit_tab as _api


def exit_fullscreen(self):
    fs = getattr(self, "_fs_window", None)
    if fs is None:
        return
    self._fs_window = None
    try:
        # Возвращаем видео обратно в контейнер вкладки.
        self.vc_layout.insertWidget(0, self.video_widget, 0, _api.Qt.AlignmentFlag.AlignCenter)
        self.video_widget.show()
    except Exception:
        pass
    # Оверлей субтитров мог стать дочерним к окну fs — вернём его главному
    # окну ДО удаления fs, иначе Qt удалит оверлей вместе с fs.
    try:
        if self.sub_overlay is not None:
            self._reparent_overlay(self.window())
    except Exception:
        pass
    try:
        fs.close(); fs.deleteLater()
    except Exception:
        pass
    try:
        self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=True))
        self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
        self._adjust_video_height()
        _api.QTimer.singleShot(0, self._position_overlay)
        # Обратный переезд — та же история, что и при входе (см. там).
        _api.QTimer.singleShot(0, self._restore_canvas_frame)
    except Exception:
        pass

def _restore_canvas_frame(self):
    """Возвращает кадр на холст после переезда в другое окно.

        Нужен только на паузе: сцена холста теряет показанный кадр вместе с
        графическим контекстом, а новых кадров плеер на паузе не шлёт. Точный
        кадр берётся из того же предекодера, что и при покадровом шаге, так что
        на экране оказывается ровно тот кадр, на котором стояли."""
    try:
        if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
            return
    except Exception:
        return
    try:
        self._show_exact_frame(self._frame_idx)
    except Exception:
        pass

def _fs_sync_position(self):
    """Обновляет полосу/тайминги в полноэкранном окне (вызывается из sync_ui
        и on_position_changed, когда оно открыто)."""
    fs = getattr(self, "_fs_window", None)
    if fs is not None:
        try:
            fs.sync_from_player()
        except Exception:
            pass

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
