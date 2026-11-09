# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_SubtitlePreview. Public namespace: edit_tab_widgets."""
import edit_tab_widgets as _api
from sip_notify import prime_disconnect_notify


class _SubtitlePreview(_api.QWidget):
    """Мини-плеер для SubtitleCreatorDialog: собственный QMediaPlayer +
    _PaintedVideoCanvas (независимо от плеера основной вкладки монтажа — второй
    набор player+canvas, как _build_video_output собирает первый), поверх кадра —
    свой прозрачный оверлей со стилизованным текстом текущей реплики."""

    positionChanged = _api.pyqtSignal(float)
    durationChanged = _api.pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = _api.QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(6)

        # ЦП-холст (не GPU): поверх него живёт обычный дочерний виджет-оверлей
        # со стилизованным текстом, и переезд диалога на Quick ничего не даёт.
        self.canvas = _api._PaintedVideoCanvas(self)
        self.canvas.setMinimumHeight(220)
        # По умолчанию QWidget без явного focusPolicy фокус не берёт — сюда
        # его отдаём осознанно, чтобы было куда деть начальный фокус диалога
        # (см. SubtitleCreatorDialog.__init__): без этого он проваливался в
        # QFontComboBox (первый в layout), а тот сам глотает пробел как ввод
        # текста раньше, чем до глобального шортката Space доходит очередь.
        self.canvas.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
        lay.addWidget(self.canvas, 1)
        self._overlay = _api._StyledSubtitleOverlay(self.canvas)

        transport = _api.QHBoxLayout(); transport.setSpacing(6)
        # Порядок кнопок — как в основном плеере Монтажа (pctrl_row): Стоп,
        # кадр назад, Play, кадр вперёд.
        self.btn_stop = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaStop)
        self.btn_step_back = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSeekBackward)
        self.btn_play = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaPlay, accent=True)
        self.btn_step_fwd = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSeekForward)
        # make_icon_btn — общий стиль для ТЕКСТОВЫХ кнопок (padding 7px/14px,
        # прозрачная рамка только у accent) — на маленьких квадратных иконках
        # без текста это давало заметно разный по факту размер контента у play
        # (без рамки) и step-кнопок (с рамкой в 1px с каждой стороны), плюс
        # немного отличающийся размер значка. Явно выравниваем все четыре.
        for b in (self.btn_stop, self.btn_step_back, self.btn_play, self.btn_step_fwd):
            b.setFixedSize(30, 26)
            b.setIconSize(_api.QSize(16, 16))
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 0px; border: 1px solid transparent; }")
        self.slider = _api.SeekSlider(_api.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.lbl_time = _api.QLabel("00:00.00 / 00:00.00")
        self.lbl_time.setStyleSheet(f"color: {_api.C['text2']}; font-size: 11px;")
        transport.addWidget(self.btn_stop)
        transport.addWidget(self.btn_step_back)
        transport.addWidget(self.btn_play)
        transport.addWidget(self.btn_step_fwd)
        transport.addWidget(self.slider, 1)
        transport.addWidget(self.lbl_time)
        lay.addLayout(transport)

        self.duration_s = 0.0
        self._active_cue_getter = None   # callable(pos_s) -> (text, style) | None
        # Диапазон показа/воспроизведения (абсолютное время исходника) — равен
        # обрезке, выделенной в Монтаже, а не всему видео (см. set_range).
        # Тайминги реплик остаются АБСОЛЮТНЫМИ (как и весь остальной таймлайн
        # монтажа) — так они совпадают и с превью, и со вшиванием (output-seek).
        self._range_start = 0.0
        self._range_end = None
        # Цель seek(), отложенная до тех пор, пока плеер реально не загрузит
        # медиа (см. seek()/_on_media_status) — до этого setPosition()
        # ненадёжен: durationChanged может прилететь ДО готовности пайплайна,
        # и любой seek к этому моменту backend молча роняет/переопределяет —
        # позиция откатывается на 0 при переходе Loading→Loaded→Buffered.
        self._pending_seek = None
        self._media_ready = False
        # Отдельный немой (без видео) плеер для короткого звукового блипа при
        # покадровом шаге (WASD/стрелки) — как _scrub_audio_blip в EditTab.
        # Через ОСНОВНОЙ self.player звук на паузе не идёт (setPosition на
        # паузе не проигрывает буфер), а короткий play()/pause() на painted-
        # холсте (_PaintedVideoCanvas) даёт мерцание/скачок кадра — отдельный плеер
        # (видео не подключено ни к какому sink'у) звучит без побочных эффектов.
        self._src_path = None
        self._blip_player = None
        self._blip_output = None
        self._blip_timer = None
        # Дорожка звука превью — та же, что выбрана в Монтаже, а не дефолтная
        # первая дорожка источника (см. set_audio_selection/_on_media_status).
        self._audio_track_index = None
        self._ext_audio_path = None
        self._ext_audio_player = None
        self._ext_audio_output = None

        self.player = _api.QMediaPlayer(self)
        self.audio_output = prime_disconnect_notify(_api.QAudioOutput(self))
        self.player.setAudioOutput(self.audio_output)
        self._audio_dev_watch = _api.install_audio_device_recovery(self.audio_output, self)
        self.player.setVideoSink(self.canvas.videoSink())
        # Субтитры — по каждому пришедшему кадру: на паузе кадр после seek
        # приезжает позже позиции, и реплика иначе считалась бы по старому.
        # Холст подписан на sink раньше — к этому слоту часы кадра уже новые.
        self._ass_provider = None
        self._ass_shown = None
        self.canvas.videoSink().videoFrameChanged.connect(self._on_canvas_frame)
        # Конец отрезка — как у Монтажа (set_play_bound): кадр за OUT не
        # показывается, плеер встаёт на последнем кадре отрезка.
        self.canvas.boundaryReached.connect(self._on_boundary)
        self.player.positionChanged.connect(self._on_position)
        self.player.durationChanged.connect(self._on_duration)
        self.player.mediaStatusChanged.connect(self._on_media_status)

        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_stop.clicked.connect(self.stop)
        fps_guess = 25
        self._step_s = 1.0 / fps_guess
        self.btn_step_back.clicked.connect(lambda: self.step_ms(-1000 // fps_guess))
        self.btn_step_fwd.clicked.connect(lambda: self.step_ms(1000 // fps_guess))
        self.slider.sliderMoved.connect(self._on_slider_seek)

    def set_active_cue_provider(self, fn):
        """fn(pos_s) -> (text, style_dict) | None — диалог передаёт свою логику
        поиска активной реплики (учитывает live-правки в списке реплик).
        Запасной путь, когда libass-рендера нет (set_ass_provider)."""
        self._active_cue_getter = fn

    def set_ass_provider(self, fn):
        """fn() -> AssRenderer|None — рендер того .ass, что сохранит окно.
        Есть рендер — субтитры рисует libass на холсте тем же путём, что в
        Монтаже (set_subtitle_image), по времени показанного кадра."""
        self._ass_provider = fn
        self._ass_shown = None
        if fn is None:
            self.canvas.clear_subtitle()
        self.refresh_subtitle()

    def refresh_subtitle(self):
        """Перерисовать субтитры на текущем кадре (реплики изменились)."""
        self._ass_shown = None
        rs, re_ = self._range_bounds()
        self._refresh_subtitle(max(rs, min(re_, self.position())))

    def _sub_time(self, pos_s):
        """Время для субтитров — начало показанного кадра, как у Монтажа
        (_sub_now_s) и у ffmpeg при вшивании. По позиции плеера реплика,
        кончающаяся внутри последнего кадра, в окне пропадала, а в Монтаже
        и в итоговом файле на этом кадре была."""
        pts = self.canvas.last_frame_pts()
        if pts is not None and abs(pts - pos_s) < 0.5:
            return pts
        return pos_s

    def _on_canvas_frame(self, _frame):
        # Пришёл кадр — метка, плейхед и субтитры встают на него.
        self._on_position(self.player.position())

    def _on_boundary(self):
        """Кадр за OUT пришёл раньше, чем позиция плеера дошла до конца
        (плеер отдаёт кадры с упреждением): пауза и снап на конец отрезка —
        как Монтаж (_on_play_boundary). Без снапа время, ползунок и плейхед
        таймлайна застревали за 0.05 с до конца, будто видео не доиграло.
        Позиция — на последний кадр отрезка (seek жмёт к OUT − 1 мс), и
        _on_position сам выставит метку на конец."""
        if self.player.playbackState() != _api.QMediaPlayer.PlaybackState.PlayingState:
            return   # чужой кадр на паузе — снап уже сделан
        self.player.pause()
        if self._ext_audio_player is not None:
            self._ext_audio_player.pause()
        self._sync_play_icon()
        _rs, re_ = self._range_bounds()
        self.seek(re_)

    def set_audio_selection(self, track_index=None, ext_path=None):
        """Звук превью — та же дорожка, что выбрана в Монтаже (cmb_audio), а
        не первая дефолтная дорожка source_path. track_index — относительный
        индекс встроенной дорожки (см. EditTab._audio_entries); ext_path —
        путь внешней озвучки (тогда звук самого видео глушится, играет
        отдельный синхронный плеер — как _ensure_ext_audio_player в EditTab).
        Вызывать ДО load() или сразу после — применяется в _on_media_status,
        когда пайплайн реально готов принимать setActiveAudioTrack/позицию."""
        self._audio_track_index = track_index
        self._ext_audio_path = ext_path

    def load(self, path):
        self._src_path = str(path)
        self._pending_seek = self._range_start
        self._media_ready = False
        try:
            self.player.setSource(_api.QUrl.fromLocalFile(str(path)))
        except Exception:
            pass
        # Подстраховка: на некоторых файлах/бэкендах (особенно с HW-декодом)
        # один seek+pause на первом «готовом» статусе иногда не успевает
        # протолкнуть кадр в VideoSink вовремя — кадр так и не появляется, пока
        # пользователь сам не потрогает плеер. Несколько раз повторяем
        # seek+pause в первые ~2с после загрузки, пока кадр не появится.
        self._frame_watchdog_tries = 0
        if not hasattr(self, '_frame_watchdog'):
            self._frame_watchdog = _api.QTimer(self)
            self._frame_watchdog.setInterval(150)
            self._frame_watchdog.timeout.connect(self._on_frame_watchdog)
        self._frame_watchdog.start()

    def _on_frame_watchdog(self):
        self._frame_watchdog_tries += 1
        if self.canvas._frame_img is not None:
            self._frame_watchdog.stop()
            return
        if self._frame_watchdog_tries > 14:
            self._frame_watchdog.stop()
            return
        if not self._media_ready:
            return
        try:
            cur = self.player.position()
            # setPosition на ТО ЖЕ САМОЕ значение бэкенд может тихо счесть
            # no-op'ом и не запросить новый кадр — небольшой чёт/нечет джиттер
            # гарантирует РЕАЛЬНОЕ изменение позиции перед возвратом на место.
            jitter = 1 if (self._frame_watchdog_tries % 2) else -1
            self.player.setPosition(max(0, cur + jitter))
            self.player.setPosition(cur)
            self.player.pause()
        except Exception:
            pass

    def set_range(self, start_s, end_s):
        """Ограничивает показ/скраб/воспроизведение диапазоном [start_s, end_s]
        (абсолютное время исходника) — тем самым, что выделен в Монтаже."""
        self._range_start = max(0.0, float(start_s))
        self._range_end = (max(self._range_start + 0.05, float(end_s))
                            if end_s is not None else None)
        # Чуть раньше OUT: кадр, начинающийся ровно на OUT, уже за отрезком
        # (округление pts в мкс не должно пропустить его на экран).
        self.canvas.set_play_bound(self._range_end - 0.0005
                                   if self._range_end is not None else None)
        self.seek(self._range_start)

    def _range_bounds(self):
        rs = self._range_start
        re_ = self._range_end if self._range_end is not None else self.duration_s
        return rs, max(rs + 0.05, re_)

    def _on_duration(self, dur_ms):
        self.duration_s = max(0.0, dur_ms / 1000.0)
        self.durationChanged.emit(self.duration_s)

    def _on_media_status(self, status):
        # durationChanged может прилететь РАНЬШЕ, чем пайплайн реально готов
        # принимать seek (иногда даже пока status ещё LoadingMedia) — надёжный
        # момент «можно сикать» — первый переход в Loaded/Buffering/Buffered.
        # Более ранние seek() (см. set_range/load) до сих пор только копились
        # в _pending_seek — применяем накопленную цель здесь.
        if self._media_ready:
            return
        ready_states = (_api.QMediaPlayer.MediaStatus.LoadedMedia,
                        _api.QMediaPlayer.MediaStatus.BufferingMedia,
                        _api.QMediaPlayer.MediaStatus.BufferedMedia)
        if status not in ready_states:
            return
        self._media_ready = True
        if self._audio_track_index is not None:
            try:
                self.player.setActiveAudioTrack(self._audio_track_index)
            except Exception:
                pass
        if self._pending_seek is not None:
            target = self._pending_seek
            self._pending_seek = None
            self.player.setPosition(int(max(0.0, target) * 1000))
        self.player.pause()
        self._sync_play_icon()
        if self._ext_audio_path:
            self._start_ext_audio_preview()

    def _start_ext_audio_preview(self):
        """Внешняя озвучка выбрана в Монтаже — глушим звук самого видео и
        играем отдельный синхронный плеер поверх него (как _ensure_ext_audio_
        player в EditTab), иначе превью звучало бы дорожкой из видеофайла."""
        try:
            self.audio_output.setMuted(True)
        except Exception:
            pass
        if self._ext_audio_player is None:
            self._ext_audio_player = _api.QMediaPlayer(self)
            self._ext_audio_output = prime_disconnect_notify(_api.QAudioOutput(self))
            self._ext_audio_player.setAudioOutput(self._ext_audio_output)
        try:
            self._ext_audio_output.setVolume(self.audio_output.volume())
            self._ext_audio_player.setSource(_api.QUrl.fromLocalFile(self._ext_audio_path))
            self._ext_audio_player.setPosition(self.player.position())
        except Exception:
            pass

    def _on_slider_seek(self, v):
        rs, re_ = self._range_bounds()
        self.seek(rs + (v / 1000.0) * (re_ - rs))

    def _on_position(self, pos_ms):
        pos_s = pos_ms / 1000.0
        rs, re_ = self._range_bounds()
        sub_s = self._sub_time(pos_s)
        if pos_s >= re_ - 0.02:
            if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause(); self._sync_play_icon()
            pos_s = re_
        else:
            # Метка и плейхед — на НАЧАЛЕ показанного кадра, как в Монтаже:
            # блоки реплик на таймлайне тоже стоят по кадрам, и плейхед внутри
            # блока = реплика на экране. В конце отрезка — снап на OUT.
            pos_s = max(rs, sub_s)
        span = max(0.001, re_ - rs)
        if not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int(max(0.0, min(1.0, (pos_s - rs) / span)) * 1000))
            self.slider.blockSignals(False)
        # Время внутри отрезка из Монтажа, а не от начала исходника: иначе у
        # трёхсекундного отрезка в конце файла счётчик показывал «/ 00:00:52».
        self.lbl_time.setText(f"{_api.s_to_clock(pos_s - rs)} / {_api.s_to_clock(span)}")
        self._refresh_subtitle(sub_s)
        self.positionChanged.emit(pos_s)

    def _refresh_subtitle(self, pos_s):
        r = self._ass_provider() if self._ass_provider is not None else None
        if r is not None:
            self._overlay.set_content("", None)
            self._render_ass(r, self._sub_time(pos_s))
            return
        if self._ass_shown is not None:
            self._ass_shown = None
            self.canvas.clear_subtitle()
        text, style = "", None
        if self._active_cue_getter is not None:
            found = self._active_cue_getter(pos_s)
            if found:
                text, style = found
        self._sync_overlay_geometry()
        self._overlay.set_content(text, style)

    def _render_ass(self, r, t_s):
        """Кадр libass на холст — как EditTab._update_subtitle: область кадра
        холста, картинка по ограничивающему прямоугольнику, без перерисовки,
        когда libass говорит, что ничего не изменилось."""
        try:
            w, h = self.canvas.subtitle_area_size()
        except Exception:
            return
        if w <= 0 or h <= 0:
            return
        try:
            r.set_frame_size(w, h)
            arr, ax, ay, changed = r.render(t_s * 1000.0)
        except Exception:
            arr, ax, ay, changed = None, 0, 0, True
        key = (id(r), w, h)
        if not changed and self._ass_shown == key:
            return
        self._ass_shown = key
        if arr is None:
            self.canvas.clear_subtitle()
            return
        ih, iw = int(arr.shape[0]), int(arr.shape[1])
        qimg = _api.QImage(arr.data, iw, ih, iw * 4,
                           _api.QImage.Format.Format_RGBA8888_Premultiplied).copy()
        self.canvas.set_subtitle_image(qimg, ax, ay)

    def _sync_overlay_geometry(self):
        # Оверлей — на весь холст; область кадра он берёт сам при отрисовке
        # (_StyledSubtitleOverlay._frame_rect), так текст не отстаёт от кадра.
        try:
            self._overlay.setGeometry(self.canvas.rect())
        except Exception:
            pass

    def seek(self, pos_s):
        # Превью не уходит за отрезок: реплика, начатая до него, перематывает
        # на его начало, а не на кадр, которого нет ни на таймлайне, ни в итоге.
        pos_s = max(self._range_start, float(pos_s))
        if self._range_end is not None:
            # На последний кадр отрезка, а не на OUT: кадр на OUT уже за
            # отрезком, холст его не покажет (set_play_bound).
            pos_s = min(pos_s, max(self._range_start, self._range_end - 0.001))
        # Пока пайплайн не готов (см. _on_media_status), setPosition() молча
        # роняется/переопределяется бэкендом — копим цель, применяем позже.
        if not self._media_ready:
            self._pending_seek = pos_s
            return
        try:
            self.player.setPosition(int(max(0.0, pos_s) * 1000))
        except Exception:
            pass
        if self._ext_audio_player is not None:
            try:
                self._ext_audio_player.setPosition(int(max(0.0, pos_s) * 1000))
            except Exception:
                pass

    def position(self):
        try:
            return self.player.position() / 1000.0
        except Exception:
            return 0.0

    def _sync_play_icon(self):
        playing = self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
        std = (_api.QStyle.StandardPixmap.SP_MediaPause if playing
               else _api.QStyle.StandardPixmap.SP_MediaPlay)
        self.btn_play.setIcon(_api.QApplication.style().standardIcon(std))

    def toggle_play(self):
        if self.player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
            if self._ext_audio_player is not None:
                self._ext_audio_player.pause()
        else:
            rs, re_ = self._range_bounds()
            if self.position() >= re_ - 0.02:
                self.seek(rs)
            self.player.play()
            if self._ext_audio_player is not None:
                self._ext_audio_player.setPosition(self.player.position())
                self._ext_audio_player.play()
        self._sync_play_icon()

    def step_ms(self, delta_ms):
        self.player.pause(); self._sync_play_icon()
        if self._ext_audio_player is not None:
            self._ext_audio_player.pause()
        rs, re_ = self._range_bounds()
        target = max(rs, min(re_, self.position() + delta_ms / 1000.0))
        self.seek(target)
        self._play_step_blip(target)

    def _ensure_blip_player(self):
        if self._blip_player is None:
            self._blip_player = _api.QMediaPlayer(self)
            self._blip_output = prime_disconnect_notify(_api.QAudioOutput(self))
            self._blip_player.setAudioOutput(self._blip_output)
        try:
            self._blip_output.setVolume(self.audio_output.volume())
        except Exception:
            pass
        cur = self._blip_player.source().toLocalFile()
        if self._src_path and cur != self._src_path:
            try:
                self._blip_player.setSource(_api.QUrl.fromLocalFile(self._src_path))
            except Exception:
                pass
        return self._blip_player

    def _play_step_blip(self, pos_s):
        """Короткий звуковой блип (~150мс) в новой позиции покадрового шага."""
        if not self._src_path:
            return
        player = self._ensure_blip_player()
        try:
            player.setPosition(int(max(0.0, pos_s) * 1000))
            player.play()
        except Exception:
            return
        if self._blip_timer is None:
            self._blip_timer = _api.QTimer(self)
            self._blip_timer.setSingleShot(True)
            self._blip_timer.timeout.connect(lambda: player.pause())
        self._blip_timer.start(150)

    def stop(self):
        self.player.stop()
        if self._ext_audio_player is not None:
            self._ext_audio_player.stop()
        # player.stop() сбрасывает позицию на АБСОЛЮТНЫЙ 0 (начало всего файла),
        # а не на начало выделенного диапазона — доводим до rs, как и положено
        # в ограниченном диапазоном превью.
        rs, _re = self._range_bounds()
        self.seek(rs)
        self._sync_play_icon()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._sync_overlay_geometry()

_SubtitlePreview.__module__ = _api.__name__
_api._SubtitlePreview = _SubtitlePreview
