# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""VideoCompareViewer. Public namespace: widgets."""
import widgets as _api


class VideoCompareViewer(_api.QDialog):
    """Полноэкранное сравнение исходного и перекодированного видео (рядом,
    слева исходник — справа результат). Пуск/пауза и перемотка синхронны для
    обоих плееров; звучит только один из них за раз (переключается кнопкой),
    чтобы дорожки не накладывались друг на друга. Колесо — синхронный зум,
    перетаскивание — синхронная панорама. Esc или кнопка выхода — закрыть."""
    def __init__(self, src_path, out_path, parent=None, use_filenames=False):
        super().__init__(parent)
        if not _api._HAS_MULTIMEDIA_CMP:
            raise RuntimeError("QtMultimedia недоступен — сравнение видео невозможно")
        # use_filenames: True только для кнопки «Сравнить любые 2 файла»
        # (тулбар) — подписи показывают имя файла вместо «Исходник»/«Результат».
        self._use_filenames = use_filenames
        self.setWindowTitle("Сравнение: исходник / результат")
        self.setStyleSheet("QDialog{background:#0e0e16;}")
        self.setAttribute(_api.Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._seeking = False
        self._audio_mode = 0  # 0=исходник, 1=результат, 2=без звука
        self._total_zoom = 1.0
        self._syncing_scroll = False
        self._src_paths = {'src': src_path, 'out': out_path}
        self._proxy_workers = []

        root = _api.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)

        # Верхняя полоса: кнопка выхода — ОБЫЧНЫЙ элемент раскладки (не плавающий
        # оверлей поверх видео), поэтому не перекрывается видео-виджетами.
        top = _api.QHBoxLayout()
        top.setContentsMargins(10, 6, 10, 6); top.setSpacing(0)
        # Кнопки «заменить исходник»/«заменить результат» — каждая трогает
        # только СВОЮ сторону, позволяя сравнить любые два видео с диска.
        self.btn_change_src = _api.QPushButton()
        self.btn_change_src.setIcon(_api.get_icon('fa5s.folder-open', '#ffffff'))
        self.btn_change_src.setIconSize(_api.QSize(18, 18))
        self.btn_change_src.setFixedSize(34, 34)
        self.btn_change_src.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        # Кнопки диалога НЕ держат клавиатурный фокус — иначе Qt отдаёт фокус
        # первому добавленному виджету (эта самая кнопка, ФАЙЛОВЫЙ пикер) сразу
        # при открытии, и Пробел вместо паузы/плей открывал «Проводник».
        self.btn_change_src.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_change_src.setToolTip("Заменить исходник (слева) файлом с диска")
        self.btn_change_src.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:17px;}"
            "QPushButton:hover{background:#89b4fa;border-color:#89b4fa;}")
        self.btn_change_src.clicked.connect(self._pick_source_video)
        top.addWidget(self.btn_change_src)
        top.addStretch(1)
        self.btn_change_out = _api.QPushButton()
        self.btn_change_out.setIcon(_api.get_icon('fa5s.folder-open', '#ffffff'))
        self.btn_change_out.setIconSize(_api.QSize(18, 18))
        self.btn_change_out.setFixedSize(34, 34)
        self.btn_change_out.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_change_out.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_change_out.setToolTip("Заменить результат (справа) файлом с диска")
        self.btn_change_out.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:17px;}"
            "QPushButton:hover{background:#89b4fa;border-color:#89b4fa;}")
        self.btn_change_out.clicked.connect(self._pick_source_out_video)
        top.addWidget(self.btn_change_out)
        top.addSpacing(8)
        self.btn_close = _api.QPushButton()
        self.btn_close.setIcon(_api.get_icon('fa5s.times', '#ffffff'))
        self.btn_close.setIconSize(_api.QSize(18, 18))
        self.btn_close.setFixedSize(34, 34)
        self.btn_close.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_close.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_close.setToolTip("Выход (Esc)")
        self.btn_close.setStyleSheet(
            "QPushButton{background:rgba(24,24,37,190);border:1px solid #45475a;"
            "border-radius:17px;}"
            "QPushButton:hover{background:#f38ba8;border-color:#f38ba8;}")
        self.btn_close.clicked.connect(self.close)
        top.addWidget(self.btn_close)
        top_w = _api.QWidget(); top_w.setLayout(top)
        top_w.setStyleSheet("background:#181825;")
        root.addWidget(top_w, 0)

        body = _api.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0); body.setSpacing(2)

        col_src, self.view_src, self.lbl_cap_src = self._make_col("Исходник", src_path)
        col_out, self.view_out, self.lbl_cap_out = self._make_col("Результат", out_path)
        self._views = [self.view_src, self.view_out]
        body.addLayout(col_src, 1)
        body.addLayout(col_out, 1)
        root.addLayout(body, 1)

        self.player_src = _api.QMediaPlayer(self)
        self.player_out = _api.QMediaPlayer(self)
        self.audio_src = _api.QAudioOutput(self)
        self.audio_out = _api.QAudioOutput(self)
        self.player_src.setVideoOutput(self.view_src.video_item)
        self.player_out.setVideoOutput(self.view_out.video_item)
        self.player_src.setAudioOutput(self.audio_src)
        self.player_out.setAudioOutput(self.audio_out)
        self._apply_audio_mode()

        self.view_src.video_item.nativeSizeChanged.connect(self.view_src.set_native_size)
        self.view_out.video_item.nativeSizeChanged.connect(self.view_out.set_native_size)
        self.player_src.durationChanged.connect(self._on_duration)
        self.player_src.positionChanged.connect(self._on_position)
        self.player_src.mediaStatusChanged.connect(self._on_media_status)
        self.player_src.playbackStateChanged.connect(self._on_playback_state)

        # Панель управления снизу.
        ctrl = _api.QHBoxLayout()
        ctrl.setContentsMargins(10, 6, 10, 6); ctrl.setSpacing(8)
        self.btn_play = _api.QPushButton(); self.btn_play.setIcon(_api.get_icon('fa5s.play', '#ffffff'))
        self.btn_play.setFixedSize(34, 34)
        self.btn_play.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_play.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_play.clicked.connect(self._toggle_play)
        self.slider = _api.QSlider(_api.Qt.Orientation.Horizontal)
        self.slider.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.slider.sliderPressed.connect(lambda: setattr(self, '_seeking', True))
        self.slider.sliderReleased.connect(self._on_slider_released)
        self.slider.sliderMoved.connect(self._on_slider_moved)
        self.lbl_time = _api.QLabel("00:00 / 00:00")
        self.lbl_time.setStyleSheet("color:#a6adc8;")
        self.btn_audio = _api.QPushButton("Звук: исходник")
        self.btn_audio.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_audio.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_audio.clicked.connect(self._cycle_audio)
        ctrl.addWidget(self.btn_play); ctrl.addWidget(self.slider, 1)
        ctrl.addWidget(self.lbl_time); ctrl.addWidget(self.btn_audio)
        ctrl_w = _api.QWidget(); ctrl_w.setLayout(ctrl)
        ctrl_w.setStyleSheet("background:#181825;")
        root.addWidget(ctrl_w, 0)

        # AV1 может рендериться чёрным экраном напрямую на iGPU без аппаратного
        # AV1-декодера — но у кого декодер ЕСТЬ (RTX 30+, RDNA2+, Intel 12-е
        # поколение/Arc и т.п.), AV1 играет напрямую без проблем, и гонять его
        # через прокси незачем — лишняя перекодировка тратит время и портит
        # качество превью. Поэтому не проксируем AV1 вслепую: сперва пробуем
        # играть напрямую и реальным приходом декодированного кадра проверяем,
        # что декодер действительно работает; не пришёл кадр за отведённое
        # время — тогда (и только тогда) подключаем H.264-прокси.
        # src_path/out_path могут быть None — «Сравнить любые 2 файла» позволяет
        # выбрать сначала только один файл, второй добавляется прямо в окне
        # (кнопкой-папкой) без пересоздания диалога.
        if src_path:
            self._start_video('src', src_path, self.player_src, self.view_src,
                              self.audio_src, self.lbl_cap_src, "Исходник")
        else:
            self.lbl_cap_src.setText("Нажмите на значок папки, чтобы выбрать файл")
        if out_path:
            self._start_video('out', out_path, self.player_out, self.view_out,
                              self.audio_out, self.lbl_cap_out, "Результат")
        else:
            self.lbl_cap_out.setText("Нажмите на значок папки, чтобы выбрать файл")

        # Все кнопки диалога — NoFocus (см. выше), так что фокус явно отдаём
        # самому диалогу: гарантирует, что Пробел сразу после открытия идёт в
        # keyPressEvent (пауза/плей), а не активирует случайно сфокусированный
        # виджет (было — открывался «Проводник» вместо воспроизведения).
        self.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
        self.setFocus(_api.Qt.FocusReason.OtherFocusReason)

    def _start_video(self, role, path, player, view, audio_out, lbl, title):
        if _api._probe_video_codec(path) != 'av1':
            lbl.setText(self._caption(title, path))
            player.setSource(_api.QUrl.fromLocalFile(path))
            player.pause()
            return
        lbl.setText(self._caption(title, path) + "   ·   проверка AV1-декодера…")
        sink = view.video_item.videoSink()
        probe = {'got_frame': False, 'target_vol': audio_out.volume()}
        audio_out.setVolume(0.0)  # без звука на время короткой пробной перемотки

        def _on_frame(frame):
            try:
                if frame.isValid():
                    probe['got_frame'] = True
            except Exception:
                pass
        sink.videoFrameChanged.connect(_on_frame)
        player.setSource(_api.QUrl.fromLocalFile(path))
        player.play()

        def _check():
            try:
                sink.videoFrameChanged.disconnect(_on_frame)
            except Exception:
                pass
            audio_out.setVolume(probe['target_vol'])
            if probe['got_frame']:
                # Аппаратный AV1-декодер реально выдал кадр — прямое воспроизведение
                # работает, прокси не нужен.
                player.pause()
                player.setPosition(0)
                lbl.setText(self._caption(title, path))
            else:
                # Кадр не пришёл — прямой путь не работает, подключаем прокси.
                player.pause()
                self._launch_proxy(role, path, player, lbl, title)
        _api.QTimer.singleShot(1500, _check)

    def _launch_proxy(self, role, path, player, lbl, title):
        lbl.setText(self._caption(title, path) + "   ·   готовим H.264-прокси (AV1 не играет напрямую)…")
        w = _api._CompareProxyWorker(role, path)  # без parent — переживает закрытие диалога
        w.ready.connect(lambda r, p: self._on_proxy_ready(r, p, player, lbl, title))
        w.finished.connect(lambda: _api._ACTIVE_COMPARE_PROXIES.discard(w))
        _api._ACTIVE_COMPARE_PROXIES.add(w)
        self._proxy_workers.append(w)
        w.start()

    def _on_proxy_ready(self, role, play_path, player, lbl, title):
        orig_path = self._src_paths.get(role, play_path)
        lbl.setText(self._caption(title, orig_path))
        player.setSource(_api.QUrl.fromLocalFile(play_path))
        player.pause()

    def _make_col(self, title, path):
        col = _api.QVBoxLayout(); col.setContentsMargins(0, 0, 0, 0); col.setSpacing(0)
        lbl = _api.QLabel(self._caption(title, path))
        lbl.setStyleSheet("color:#ffffff;background:rgba(0,0,0,160);padding:6px;font-weight:bold;")
        lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        # Длинное имя файла без переноса задирало minimumSizeHint колонки —
        # диалог оказывался шире экрана, и кнопки в верхней панели (закрытие,
        # замена файла) уезжали за его пределы. WordWrap + Ignored по горизонтали
        # заставляет подпись переноситься на новую строку, а не расширять окно.
        lbl.setWordWrap(True)
        lbl.setSizePolicy(_api.QSizePolicy.Policy.Ignored, _api.QSizePolicy.Policy.Preferred)
        view = _api._ZoomVideoView(owner=self)
        col.addWidget(lbl, 0)
        col.addWidget(view, 1)
        return col, view, lbl

    def _caption(self, title, path):
        if not path:
            return ""
        label = _api.os.path.basename(path) if self._use_filenames else title
        try:
            size_str = _api.human_size(_api.os.path.getsize(path))
        except Exception:
            size_str = ""
        ext = _api.os.path.splitext(path)[1].lstrip('.').upper() or "—"
        if self._use_filenames:
            return f"{label}   ·   {size_str}" if size_str else label
        return f"{label}   ·   {ext}" + (f"   ·   {size_str}" if size_str else "")

    def _broadcast_zoom(self, factor):
        new_total = max(1.0, min(8.0, self._total_zoom * factor))
        if new_total == self._total_zoom:
            return
        actual = new_total / self._total_zoom
        self._total_zoom = new_total
        for v in self._views:
            if new_total <= 1.0:
                v.reset_fit()
            else:
                v.apply_zoom_factor(actual)

    def _sync_scroll(self, axis, src_view, val):
        if self._syncing_scroll:
            return
        src_bar = src_view.horizontalScrollBar() if axis == 'h' else src_view.verticalScrollBar()
        rng = src_bar.maximum() - src_bar.minimum()
        frac = (val - src_bar.minimum()) / rng if rng else 0.0
        self._syncing_scroll = True
        try:
            for v in self._views:
                if v is src_view:
                    continue
                bar = v.horizontalScrollBar() if axis == 'h' else v.verticalScrollBar()
                r = bar.maximum() - bar.minimum()
                bar.setValue(int(bar.minimum() + frac * r))
        finally:
            self._syncing_scroll = False

    def _apply_audio_mode(self):
        labels = ["Звук: исходник", "Звук: результат", "Звук: выключен"]
        self.audio_src.setVolume(1.0 if self._audio_mode == 0 else 0.0)
        self.audio_out.setVolume(1.0 if self._audio_mode == 1 else 0.0)
        if hasattr(self, 'btn_audio'):
            self.btn_audio.setText(labels[self._audio_mode])

    def _cycle_audio(self):
        self._audio_mode = (self._audio_mode + 1) % 3
        self._apply_audio_mode()

    def _toggle_play(self):
        playing = self.player_src.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
        if playing:
            self.player_src.pause(); self.player_out.pause()
            # Снимаем возможную остаточную подстройку скорости (см. _resync_players).
            self._set_rate(self.player_src, 1.0); self._set_rate(self.player_out, 1.0)
        else:
            # Стартуем с общей позиции — иначе плееры разъезжаются уже на старте.
            self.player_out.setPosition(self.player_src.position())
            self.player_src.play(); self.player_out.play()

    def _on_playback_state(self, state):
        icon = 'fa5s.pause' if state == _api.QMediaPlayer.PlaybackState.PlayingState else 'fa5s.play'
        self.btn_play.setIcon(_api.get_icon(icon, '#ffffff'))

    def _on_duration(self, dur):
        self.slider.setRange(0, max(0, dur))
        self._update_time_label(self.player_src.position(), dur)

    def _on_position(self, pos):
        if not self._seeking:
            self.slider.setValue(pos)
        self._update_time_label(pos, self.player_src.duration())
        self._resync_players()

    @staticmethod
    def _set_rate(player, rate):
        """Меняет скорость плеера только когда она реально отличается — лишние
        setPlaybackRate дёргают backend и дают микро-рывки."""
        if abs(player.playbackRate() - rate) > 1e-3:
            player.setPlaybackRate(rate)

    def _resync_players(self):
        """Держит оба видео кадр-в-кадр без рассинхрона.

        Два независимых QMediaPlayer неизбежно расходятся (у каждого свой такт
        декодера — особенно на паре тяжёлых AV1-потоков). Старый код терпел до
        300 мс расхождения и лишь грубо «прыгал» позицией результата, из-за чего
        картинки уезжали друг от друга. Здесь — мягкая фазовая подстройка (PLL):
        звучащий плеер всегда идёт на скорости 1.0 (его звук не плывёт), а
        второй, немой, чуть ускоряется/замедляется, догоняя ведущего; только при
        большом разрыве (когда скоростью уже не догнать) делаем разовый seek."""
        ps, po = self.player_src, self.player_out
        Playing = _api.QMediaPlayer.PlaybackState.PlayingState
        if ps.playbackState() != Playing or po.playbackState() != Playing:
            self._set_rate(ps, 1.0); self._set_rate(po, 1.0)
            return
        # Ведущий — тот, чей звук слышно (его скорость не трогаем, иначе поплывёт
        # тон). В режиме «без звука» ведущий — исходник (по нему идёт таймлайн).
        master, slave = (po, ps) if self._audio_mode == 1 else (ps, po)
        self._set_rate(master, 1.0)
        drift = slave.position() - master.position()   # >0 ведомый убежал вперёд
        a = abs(drift)
        if a > 450:
            slave.setPosition(master.position())
            self._set_rate(slave, 1.0)
        elif a > 120:
            self._set_rate(slave, 0.90 if drift > 0 else 1.10)
        elif a > 30:
            self._set_rate(slave, 0.97 if drift > 0 else 1.03)
        else:
            self._set_rate(slave, 1.0)

    def _on_media_status(self, status):
        if status == _api.QMediaPlayer.MediaStatus.EndOfMedia:
            self.player_src.pause(); self.player_out.pause()
            self._set_rate(self.player_src, 1.0); self._set_rate(self.player_out, 1.0)
            self.player_src.setPosition(0); self.player_out.setPosition(0)

    def _on_slider_moved(self, val):
        self._update_time_label(val, self.player_src.duration())

    def _on_slider_released(self):
        val = self.slider.value()
        self.player_src.setPosition(val)
        self.player_out.setPosition(val)
        # После ручной перемотки сбрасываем подстройку скорости — иначе ведомый
        # остался бы «догонять» уже неактуальный сдвиг (см. _resync_players).
        self._set_rate(self.player_src, 1.0); self._set_rate(self.player_out, 1.0)
        self._seeking = False

    @staticmethod
    def _fmt_ms(ms):
        s = max(0, int(ms // 1000))
        m, s = divmod(s, 60)
        return f"{m:02d}:{s:02d}"

    def _update_time_label(self, pos, dur):
        self.lbl_time.setText(f"{self._fmt_ms(pos)} / {self._fmt_ms(dur)}")

    def keyPressEvent(self, e):
        if e.key() == _api.Qt.Key.Key_Escape:
            self.close()
        elif e.key() == _api.Qt.Key.Key_Space:
            self._toggle_play()
        else:
            super().keyPressEvent(e)

    _VIDEO_EXTS = _api.ALLOWED_MEDIA - _api.ALLOWED_AUDIO

    def _pick_source_video(self):
        exts = " ".join(f"*{e}" for e in sorted(self._VIDEO_EXTS))
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать видео для сравнения", "",
            f"Видео ({exts});;Все файлы (*)")
        if not path:
            return
        was_playing = self.player_src.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
        if was_playing:
            self.player_src.pause(); self.player_out.pause()
        self._cleanup_role_proxy('src')
        self._src_paths['src'] = path
        self.player_src.setSource(_api.QUrl())
        self._start_video('src', path, self.player_src, self.view_src,
                          self.audio_src, self.lbl_cap_src, "Исходник")

    def _pick_source_out_video(self):
        exts = " ".join(f"*{e}" for e in sorted(self._VIDEO_EXTS))
        path, _ = _api.QFileDialog.getOpenFileName(
            self, "Выбрать видео для сравнения", "",
            f"Видео ({exts});;Все файлы (*)")
        if not path:
            return
        was_playing = self.player_src.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState
        if was_playing:
            self.player_src.pause(); self.player_out.pause()
        self._cleanup_role_proxy('out')
        self._src_paths['out'] = path
        self.player_out.setSource(_api.QUrl())
        self._start_video('out', path, self.player_out, self.view_out,
                          self.audio_out, self.lbl_cap_out, "Результат")

    def _cleanup_role_proxy(self, role):
        """Удаляет временный H.264-прокси текущего видео роли role (если он был
        создан) перед тем, как подставить на его место другой файл. Вынесено из
        closeEvent, чтобы тем же способом чистить «хвост» и при смене исходника
        через _pick_source_video, а не только при закрытии диалога."""
        player = self.player_src if role == 'src' else self.player_out
        orig = self._src_paths.get(role)
        try:
            cur = player.source().toLocalFile()
            if cur and cur != orig and "sihyx_cmp_" in _api.os.path.basename(cur):
                player.setSource(_api.QUrl())
                _api.os.remove(cur)
        except Exception:
            pass

    def closeEvent(self, e):
        try:
            self.player_src.stop(); self.player_out.stop()
        except Exception:
            pass
        # Прокси-транскод (ffmpeg) внутри воркера нельзя прервать безопасно —
        # если диалог закрыт до готовности, просто отвязываем сигнал, чтобы
        # завершившийся позже поток не дёргал уже удалённые (WA_DeleteOnClose)
        # виджеты диалога.
        for w in self._proxy_workers:
            try:
                w.ready.disconnect()
            except Exception:
                pass
        # Временные H.264-прокси AV1-файлов больше не нужны.
        for role in self._src_paths:
            self._cleanup_role_proxy(role)
        super().closeEvent(e)

VideoCompareViewer.__module__ = _api.__name__
_api.VideoCompareViewer = VideoCompareViewer
