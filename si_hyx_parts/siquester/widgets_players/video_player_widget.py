# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""VideoPlayerWidget. Public namespace: siquester.widgets_players."""
import siquester.widgets_players as _api


class VideoPlayerWidget(_api.QWidget):
    """Video preview on QtMultimedia (QMediaPlayer + QVideoWidget, ffmpeg backend).

    Replaces the former mpv-based widget — no native libmpv dependency. Keeps the
    public surface used by the question view: ``__init__(path, fname, dur_sec)``,
    a ``block_drag`` signal and a ``stop()`` method. UI is unchanged: a 16:9 video
    surface (click to play/pause), a seek row, and an info line whose size /
    bitrate / resolution / LUFS come from a background thread (+ player metadata).
    """
    block_drag = _api.pyqtSignal()          # emitted when an LMB drag starts on the widget

    def __init__(self, path: str, fname: str, dur_sec: float, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#181825;")
        self._path    = path
        self._fname   = fname
        self._dur     = dur_sec
        self._stopped = False
        self._res_w   = 0; self._res_h = 0; self._abr_kbps = 0
        self._drag_origin = None
        self._dragging = False
        self._at_end = False

        vl = _api.QVBoxLayout(self); vl.setContentsMargins(0, 0, 0, 4); vl.setSpacing(4)

        # ── Video surface inside aspect-ratio container ────────
        self._video = _api.QVideoWidget(self)
        self._video.setStyleSheet("background:#000;")
        try:
            self._video.setAspectRatioMode(_api.Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass
        self._video.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        # Клик по видео = play/pause, перетаскивание = block_drag (для drag плитки).
        # На Windows QVideoWidget может быть НАТИВНЫМ окном — события мыши приходят
        # ему, а не родителю и не «сквозь» него. Поэтому вешаем обработчики прямо на
        # окно видео (а не полагаемся на WA_TransparentForMouseEvents).
        self._video.mousePressEvent   = self._media_press
        self._video.mouseMoveEvent    = self._media_move
        self._video.mouseReleaseEvent = self._media_release
        self._aspect_wrap = _api._AspectWidget(self._video)
        self._aspect_wrap.setStyleSheet("background:#000; border-radius:6px;")
        vl.addWidget(self._aspect_wrap)

        # ── Player ─────────────────────────────────────────────
        self._player = _api.QMediaPlayer(self)
        self._aout = _api.QAudioOutput(self)
        self._player.setAudioOutput(self._aout)
        self._aout.setVolume(1.0)
        self._player.setVideoOutput(self._video)

        # ── Seek row ──────────────────────────────────────────
        seek_row = _api.QHBoxLayout(); seek_row.setSpacing(6)
        self._cur_lbl = _api.QLabel("0:00")
        self._cur_lbl.setStyleSheet("color:#a6adc8;font-size:10px;min-width:36px;")
        seek_row.addWidget(self._cur_lbl)

        self._slider = _api.SeekSlider()
        self._slider.setRange(0, 1000); self._slider.setValue(0)
        self._slider.setStyleSheet(_api.SEEK_SLIDER_STYLE)
        self._slider.user_seek.connect(self._on_user_seek)
        seek_row.addWidget(self._slider, stretch=1)

        self._dur_lbl = _api.QLabel(_api.fmt_dur(dur_sec) if dur_sec else "--:--")
        self._dur_lbl.setStyleSheet("color:#585b70;font-size:10px;min-width:36px;")
        seek_row.addWidget(self._dur_lbl)
        vl.addLayout(seek_row)

        # ── Info label — built statically, refined by background thread ─
        size_bytes = _api.os.path.getsize(path) if _api.os.path.exists(path) else 0
        if size_bytes >= 1_048_576:
            self._size_str = f"{size_bytes/1048576:.1f} МБ"
        elif size_bytes > 0:
            self._size_str = f"{size_bytes//1024} КБ"
        else:
            self._size_str = ""

        self._info_lbl = _api._lbl("", "color:#6c7086;font-size:10px;")
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
        self._info_lbl.setCursor(_api.Qt.CursorShape.IBeamCursor)
        self._info_lbl.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)

        # ── All disk reads (bitrate, resolution, LUFS) in one background thread ──
        self._lufs_str = ""
        def _do_static_info(p=path, sz=size_bytes):
            ext = p.rsplit('.', 1)[-1].lower() if '.' in p else ''
            if ext in ('mp4', 'm4v', 'mov', 'm4a', 'mp4a') and sz > 0:
                try:
                    read_sz = min(65536, sz)
                    with open(p, 'rb') as _f:
                        _head = _f.read(read_sz)
                    _abr = _api._m4a_audio_bitrate_kbps(_head)
                    if _abr is None and sz > read_sz:
                        with open(p, 'rb') as _f:
                            _f.seek(max(0, sz - 262144))
                            _tail = _f.read(262144)
                        _abr = _api._m4a_audio_bitrate_kbps(_tail)
                    if _abr:
                        self._abr_kbps = _abr
                except Exception:
                    pass
            _rw, _rh = _api._mp4_video_size(p)
            if _rw and _rh:
                self._res_w, self._res_h = _rw, _rh
            self._lufs_str = _api._measure_lufs(p)
            _api._get_ui_bridge().deliver_call(self._refresh_info_label)
        _api._threading.Thread(target=_do_static_info, daemon=True).start()

        def _video_ctx_menu(pos, lbl=self._info_lbl):
            menu = _api.QMenu(lbl)
            sel = lbl.selectedText()
            menu.addAction("Копировать имя файла").triggered.connect(
                lambda: _api.QApplication.clipboard().setText(lbl.text().replace("🎬  ", "").split("   ")[0].strip()))
            if sel:
                menu.addAction("Копировать выделенное").triggered.connect(
                    lambda: _api.QApplication.clipboard().setText(sel))
            menu.exec(lbl.mapToGlobal(pos))
        self._info_lbl.customContextMenuRequested.connect(_video_ctx_menu)
        self._refresh_info_label()
        vl.addWidget(self._info_lbl)

        # ── Signals ────────────────────────────────────────────
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.metaDataChanged.connect(self._on_metadata)
        self._player.setSource(_api.QUrl.fromLocalFile(path))
        # Декодируем первый кадр на паузе (как делал mpv с pause=True), не запуская
        # воспроизведение. singleShot — чтобы источник успел подхватиться плеером.
        _api.QTimer.singleShot(0, self._prime_first_frame)

    def _prime_first_frame(self):
        if self._stopped:
            return
        try:
            self._player.pause()
        except Exception:
            pass

    # ── Mouse: click toggles play, drag emits block_drag ───────
    # Общая логика — назначается и окну видео (см. __init__), и самому виджету.
    # Координаты события берутся относительно своего виджета, но для детекта drag
    # важна лишь дельта, поэтому система координат значения не имеет.
    def _media_press(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._drag_origin = e.position().toPoint()
            self._dragging = False

    def _media_move(self, e):
        if self._drag_origin and not self._dragging:
            if (e.position().toPoint() - self._drag_origin).manhattanLength() > 8:
                self._dragging = True
                self._drag_origin = None
                self.block_drag.emit()

    def _media_release(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            was_drag = self._dragging
            self._drag_origin = None; self._dragging = False
            if not was_drag:
                self._toggle_play()

    def mousePressEvent(self, e):
        self._media_press(e); super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        self._media_move(e); super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._media_release(e); super().mouseReleaseEvent(e)

    # ── Controls ───────────────────────────────────────────────
    def _toggle_play(self):
        if self._stopped:
            return
        if self._at_end:
            self._at_end = False
            self._slider.setValue(0)
            self._cur_lbl.setText("0:00")
            self._player.setPosition(0)
            self._player.play()
        elif self._player.playbackState() == _api.QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_user_seek(self, val: int):
        if self._stopped or self._dur <= 0:
            return
        pos = self._dur * val / 1000
        self._player.setPosition(int(pos * 1000))
        self._cur_lbl.setText(_api.fmt_dur(pos))
        self._at_end = False

    # ── Player signal slots (main thread) ──────────────────────
    def _on_position(self, ms: int):
        if self._stopped:
            return
        secs = ms / 1000.0
        self._cur_lbl.setText(_api.fmt_dur(secs))
        if not self._slider._pressing and self._dur > 0:
            self._slider.setValue(int(secs * 1000 / self._dur))

    def _on_duration(self, ms: int):
        if self._stopped:
            return
        if ms > 0:
            self._dur = ms / 1000.0
            self._dur_lbl.setText(_api.fmt_dur(self._dur))

    def _on_media_status(self, status):
        if self._stopped:
            return
        if status == _api.QMediaPlayer.MediaStatus.EndOfMedia:
            self._at_end = True
            self._slider.setValue(1000)
            if self._dur > 0:
                self._cur_lbl.setText(_api.fmt_dur(self._dur))

    def _on_metadata(self):
        """Resolution / audio bitrate from the player — covers non-mp4 formats the
        static parsers don't (webm/mkv)."""
        if self._stopped:
            return
        try:
            md = self._player.metaData()
            res = md.value(_api.QMediaMetaData.Key.Resolution)
            if res is not None:
                w = int(res.width()); h = int(res.height())
                if w > 0 and h > 0 and (w != self._res_w or h != self._res_h):
                    self._res_w, self._res_h = w, h
                    self._refresh_info_label()
            if self._abr_kbps <= 0:
                abr = md.value(_api.QMediaMetaData.Key.AudioBitRate)
                if abr:
                    kbps = int(abr) // 1000
                    if kbps > 0:
                        self._abr_kbps = kbps
                        self._refresh_info_label()
        except Exception:
            pass

    def _refresh_info_label(self):
        parts = []
        if self._size_str: parts.append(self._size_str)
        if self._abr_kbps > 0: parts.append(f"🔊 {self._abr_kbps} кбит/с")
        if getattr(self, '_lufs_str', ''): parts.append(self._lufs_str)
        if self._res_w > 0 and self._res_h > 0:
            parts.append(f"{self._res_w}×{self._res_h}")
        info = "  ·  ".join(parts)
        self._info_lbl.setText(f"🎬  {self._fname}" + (f"   {info}" if info else ""))

    def stop(self):
        self._stopped = True
        try:
            self._player.stop()
            self._player.setVideoOutput(None)
            self._player.setSource(_api.QUrl())
        except Exception:
            pass

VideoPlayerWidget.__module__ = _api.__name__
_api.VideoPlayerWidget = VideoPlayerWidget
