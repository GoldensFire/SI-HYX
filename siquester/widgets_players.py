"""Audio / video player widgets built on QtMultimedia (QMediaPlayer)."""

from .qt import *
from .constants import *
from .util import *
from .media import *

class SeekSlider(QSlider):
    """QSlider that emits user_seek(value) on any mouse interaction."""
    user_seek    = pyqtSignal(int)
    user_release = pyqtSignal()   # emitted when mouse button is released

    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._pressing = False

    def _val_from_x(self, x: float) -> int:
        frac = max(0.0, min(1.0, x / max(1, self.width())))
        return int(frac * (self.maximum() - self.minimum())) + self.minimum()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressing = True
            val = self._val_from_x(e.position().x())
            self.setValue(val)
            self.user_seek.emit(val)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pressing:
            val = self._val_from_x(e.position().x())
            self.setValue(val)
            self.user_seek.emit(val)
        else:
            super().mouseMoveEvent(e)

    def wheelEvent(self, e):
        e.ignore()   # never let scroll wheel change seek position

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressing = False
            val = self._val_from_x(e.position().x())
            self.setValue(val)
            self.user_seek.emit(val)
            self.user_release.emit()
        else:
            super().mouseReleaseEvent(e)


SEEK_SLIDER_STYLE = """
    QSlider { min-height: 18px; }
    QSlider::groove:horizontal { background: #45475a; height: 4px; border-radius: 2px; }
    QSlider::sub-page:horizontal {
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #cba6f7,stop:1 #89b4fa);
        border-radius: 2px;
    }
    QSlider::handle:horizontal {
        background: #cdd6f4; border: 2px solid #89b4fa;
        width: 12px; height: 12px; margin: -5px 0; border-radius: 6px;
    }
    QSlider::handle:horizontal:hover { background: #89b4fa; }
"""


class WaveformWidget(QWidget):
    """Waveform bars that always reflect real amplitude — color animates during playback."""
    clicked_at = pyqtSignal(float)  # 0..1 fraction

    def __init__(self, bars: list, parent=None):
        super().__init__(parent)
        self._bars = bars or [0.3] * 50
        self._phase = 0.0
        self._playing = False
        self._progress = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(38)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_playing(self, playing: bool):
        self._playing = playing
        if playing: self._timer.start()
        else: self._timer.stop(); self.update()

    def set_bars(self, bars: list):
        """Safe to call only from the main thread via a signal."""
        self._bars = bars
        self.update()

    def set_progress(self, frac: float):
        self._progress = max(0.0, min(1.0, frac)); self.update()

    def _tick(self):
        self._phase += 0.18; self.update()

    def paintEvent(self, _):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        n = len(self._bars)
        if not n: p.end(); return
        gap = 2.0
        bar_w = max(2.0, (w - gap * (n - 1)) / n)
        off = (w - (bar_w * n + gap * (n - 1))) / 2
        inner_h = h - 8
        for i, amp in enumerate(self._bars):
            x = off + i * (bar_w + gap)
            played = (i / n) < self._progress
            # Bar height always reflects actual amplitude — no height animation
            bh = max(3.0, amp * inner_h + 2)
            y = (h - bh) / 2
            # Color: subtle pulse on unplayed bars during playback
            if played:
                color = QColor("#cba6f7")
            elif self._playing:
                # Gentle brightness pulse on unplayed bars to show activity
                pulse = math.sin(self._phase + i * 0.3) * 0.15 + 0.85
                base = int(0x30 * pulse); color = QColor(base, int(0x22 * pulse), int(0x50 * pulse))
            else:
                color = QColor("#313244")
            r = min(bar_w / 2, bh / 2, 2.5)
            path = QPainterPath()
            path.addRoundedRect(QRectF(x, y, bar_w, bh), r, r)
            p.fillPath(path, QBrush(color))
        p.end()

    def mousePressEvent(self, e):
        self.clicked_at.emit(max(0.0, min(1.0, e.position().x() / self.width())))
        super().mousePressEvent(e)


class _AspectWidget(QWidget):
    """Container that enforces a 16:9 aspect ratio via Qt's layout hint system.
    hasHeightForWidth() / heightForWidth() tell the layout engine to compute
    the height from the width in one pass — no setMinimumHeight feedback loops.
    """
    def __init__(self, child: QWidget, parent=None):
        super().__init__(parent)
        self.setSizePolicy(_Expand, _Pref)
        self._child = child
        child.setParent(self)
        child.move(0, 0)

    def hasHeightForWidth(self) -> bool: return True
    def heightForWidth(self, w: int) -> int: return max(1, w * 9 // 16)

    def sizeHint(self):
        w = self.width() or 400
        return QSize(w, self.heightForWidth(w))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Fill child exactly — no layout engine involved, no feedback
        self._child.setGeometry(0, 0, self.width(), self.height())


class VideoPlayerWidget(QWidget):
    """Video preview on QtMultimedia (QMediaPlayer + QVideoWidget, ffmpeg backend).

    Replaces the former mpv-based widget — no native libmpv dependency. Keeps the
    public surface used by the question view: ``__init__(path, fname, dur_sec)``,
    a ``block_drag`` signal and a ``stop()`` method. UI is unchanged: a 16:9 video
    surface (click to play/pause), a seek row, and an info line whose size /
    bitrate / resolution / LUFS come from a background thread (+ player metadata).
    """
    block_drag = pyqtSignal()          # emitted when an LMB drag starts on the widget

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

        vl = QVBoxLayout(self); vl.setContentsMargins(0, 0, 0, 4); vl.setSpacing(4)

        # ── Video surface inside aspect-ratio container ────────
        self._video = QVideoWidget(self)
        self._video.setStyleSheet("background:#000;")
        try:
            self._video.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        except Exception:
            pass
        self._video.setCursor(Qt.CursorShape.PointingHandCursor)
        # Клик по видео = play/pause, перетаскивание = block_drag (для drag плитки).
        # На Windows QVideoWidget может быть НАТИВНЫМ окном — события мыши приходят
        # ему, а не родителю и не «сквозь» него. Поэтому вешаем обработчики прямо на
        # окно видео (а не полагаемся на WA_TransparentForMouseEvents).
        self._video.mousePressEvent   = self._media_press
        self._video.mouseMoveEvent    = self._media_move
        self._video.mouseReleaseEvent = self._media_release
        self._aspect_wrap = _AspectWidget(self._video)
        self._aspect_wrap.setStyleSheet("background:#000; border-radius:6px;")
        vl.addWidget(self._aspect_wrap)

        # ── Player ─────────────────────────────────────────────
        self._player = QMediaPlayer(self)
        self._aout = QAudioOutput(self)
        self._player.setAudioOutput(self._aout)
        self._aout.setVolume(1.0)
        self._player.setVideoOutput(self._video)

        # ── Seek row ──────────────────────────────────────────
        seek_row = QHBoxLayout(); seek_row.setSpacing(6)
        self._cur_lbl = QLabel("0:00")
        self._cur_lbl.setStyleSheet("color:#a6adc8;font-size:10px;min-width:36px;")
        seek_row.addWidget(self._cur_lbl)

        self._slider = SeekSlider()
        self._slider.setRange(0, 1000); self._slider.setValue(0)
        self._slider.setStyleSheet(SEEK_SLIDER_STYLE)
        self._slider.user_seek.connect(self._on_user_seek)
        seek_row.addWidget(self._slider, stretch=1)

        self._dur_lbl = QLabel(fmt_dur(dur_sec) if dur_sec else "--:--")
        self._dur_lbl.setStyleSheet("color:#585b70;font-size:10px;min-width:36px;")
        seek_row.addWidget(self._dur_lbl)
        vl.addLayout(seek_row)

        # ── Info label — built statically, refined by background thread ─
        size_bytes = os.path.getsize(path) if os.path.exists(path) else 0
        if size_bytes >= 1_048_576:
            self._size_str = f"{size_bytes/1048576:.1f} МБ"
        elif size_bytes > 0:
            self._size_str = f"{size_bytes//1024} КБ"
        else:
            self._size_str = ""

        self._info_lbl = _lbl("", "color:#6c7086;font-size:10px;")
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._info_lbl.setCursor(Qt.CursorShape.IBeamCursor)
        self._info_lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)

        # ── All disk reads (bitrate, resolution, LUFS) in one background thread ──
        self._lufs_str = ""
        def _do_static_info(p=path, sz=size_bytes):
            ext = p.rsplit('.', 1)[-1].lower() if '.' in p else ''
            if ext in ('mp4', 'm4v', 'mov', 'm4a', 'mp4a') and sz > 0:
                try:
                    read_sz = min(65536, sz)
                    with open(p, 'rb') as _f:
                        _head = _f.read(read_sz)
                    _abr = _m4a_audio_bitrate_kbps(_head)
                    if _abr is None and sz > read_sz:
                        with open(p, 'rb') as _f:
                            _f.seek(max(0, sz - 262144))
                            _tail = _f.read(262144)
                        _abr = _m4a_audio_bitrate_kbps(_tail)
                    if _abr:
                        self._abr_kbps = _abr
                except Exception:
                    pass
            _rw, _rh = _mp4_video_size(p)
            if _rw and _rh:
                self._res_w, self._res_h = _rw, _rh
            self._lufs_str = _measure_lufs(p)
            _get_ui_bridge().deliver_call(self._refresh_info_label)
        _threading.Thread(target=_do_static_info, daemon=True).start()

        def _video_ctx_menu(pos, lbl=self._info_lbl):
            menu = QMenu(lbl)
            sel = lbl.selectedText()
            menu.addAction("Копировать имя файла").triggered.connect(
                lambda: QApplication.clipboard().setText(lbl.text().replace("🎬  ", "").split("   ")[0].strip()))
            if sel:
                menu.addAction("Копировать выделенное").triggered.connect(
                    lambda: QApplication.clipboard().setText(sel))
            menu.exec(lbl.mapToGlobal(pos))
        self._info_lbl.customContextMenuRequested.connect(_video_ctx_menu)
        self._refresh_info_label()
        vl.addWidget(self._info_lbl)

        # ── Signals ────────────────────────────────────────────
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.metaDataChanged.connect(self._on_metadata)
        self._player.setSource(QUrl.fromLocalFile(path))
        # Декодируем первый кадр на паузе (как делал mpv с pause=True), не запуская
        # воспроизведение. singleShot — чтобы источник успел подхватиться плеером.
        QTimer.singleShot(0, self._prime_first_frame)

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
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = e.position().toPoint()
            self._dragging = False

    def _media_move(self, e):
        if self._drag_origin and not self._dragging:
            if (e.position().toPoint() - self._drag_origin).manhattanLength() > 8:
                self._dragging = True
                self._drag_origin = None
                self.block_drag.emit()

    def _media_release(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
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
        elif self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_user_seek(self, val: int):
        if self._stopped or self._dur <= 0:
            return
        pos = self._dur * val / 1000
        self._player.setPosition(int(pos * 1000))
        self._cur_lbl.setText(fmt_dur(pos))
        self._at_end = False

    # ── Player signal slots (main thread) ──────────────────────
    def _on_position(self, ms: int):
        if self._stopped:
            return
        secs = ms / 1000.0
        self._cur_lbl.setText(fmt_dur(secs))
        if not self._slider._pressing and self._dur > 0:
            self._slider.setValue(int(secs * 1000 / self._dur))

    def _on_duration(self, ms: int):
        if self._stopped:
            return
        if ms > 0:
            self._dur = ms / 1000.0
            self._dur_lbl.setText(fmt_dur(self._dur))

    def _on_media_status(self, status):
        if self._stopped:
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._at_end = True
            self._slider.setValue(1000)
            if self._dur > 0:
                self._cur_lbl.setText(fmt_dur(self._dur))

    def _on_metadata(self):
        """Resolution / audio bitrate from the player — covers non-mp4 formats the
        static parsers don't (webm/mkv)."""
        if self._stopped:
            return
        try:
            md = self._player.metaData()
            res = md.value(QMediaMetaData.Key.Resolution)
            if res is not None:
                w = int(res.width()); h = int(res.height())
                if w > 0 and h > 0 and (w != self._res_w or h != self._res_h):
                    self._res_w, self._res_h = w, h
                    self._refresh_info_label()
            if self._abr_kbps <= 0:
                abr = md.value(QMediaMetaData.Key.AudioBitRate)
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
            self._player.setSource(QUrl())
        except Exception:
            pass


# Историческое имя класса (вкладка вопросов ссылается на него) — оставляем как
# алиас, чтобы не трогать call-site после порта с mpv на QtMultimedia.
MpvVideoPlayerWidget = VideoPlayerWidget


class CirclePlayButton(QWidget):
    """Painted circular button showing a proper play triangle or pause bars."""
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self._hovered = False
        self._pressed = False
        self.setFixedSize(44, 44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_playing(self, playing: bool):
        self._playing = playing
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 1.5

        # Circle fill
        if self._pressed:
            bg = QColor("#cba6f7")
        elif self._hovered:
            bg = QColor("#cba6f7")
        else:
            bg = QColor("#cba6f7")
        p.setBrush(QBrush(bg))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # Icon — white
        p.setBrush(QBrush(QColor("white")))
        p.setPen(Qt.PenStyle.NoPen)

        if self._playing:
            # Pause: two rounded rectangles
            bw, bh, gap = 4.0, 13.0, 5.0
            x1 = cx - gap / 2 - bw
            x2 = cx + gap / 2
            p.drawRoundedRect(QRectF(x1, cy - bh / 2, bw, bh), 2, 2)
            p.drawRoundedRect(QRectF(x2, cy - bh / 2, bw, bh), 2, 2)
        else:
            # Play: filled triangle, shifted slightly right for optical balance
            path = QPainterPath()
            ts = 13.0
            ox = 1.5
            path.moveTo(cx - ts * 0.38 + ox, cy - ts * 0.5)
            path.lineTo(cx + ts * 0.62 + ox, cy)
            path.lineTo(cx - ts * 0.38 + ox, cy + ts * 0.5)
            path.closeSubpath()
            p.fillPath(path, QBrush(QColor("white")))

        p.end()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = True; self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._pressed = False; self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self._hovered = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False; self._pressed = False; self.update(); super().leaveEvent(e)


class AudioPlayerWidget(QWidget):
    """Audio: circular play/pause + real-amplitude waveform (messenger style)."""
    block_drag = pyqtSignal()

    def __init__(self, path: str, fname: str, dur_sec: float, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#1e1e2e;border-radius:10px;")
        self._drag_origin = None; self._dragging = False

        self._player = QMediaPlayer(self)
        self._aout = QAudioOutput(self)
        self._player.setAudioOutput(self._aout)
        self._aout.setVolume(1.0)

        vl = QVBoxLayout(self); vl.setContentsMargins(10, 8, 10, 8); vl.setSpacing(4)

        # ── Main playback row: [●play] [time / dur] [waveform] ─
        row = QHBoxLayout(); row.setSpacing(10)

        self._play_btn = CirclePlayButton()
        self._play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self._play_btn, alignment=_AlignVC)

        right = QVBoxLayout(); right.setSpacing(2)

        # time / duration on one mini row
        time_row = QHBoxLayout(); time_row.setContentsMargins(0, 0, 0, 0); time_row.setSpacing(4)
        self._time_lbl = QLabel("0:00")
        self._time_lbl.setStyleSheet("color:#cdd6f4;font-size:10px;font-weight:700;background:transparent;")
        time_row.addWidget(self._time_lbl)
        total_str = fmt_dur(dur_sec) if dur_sec else "--:--"
        self._dur_lbl = QLabel(f"/ {total_str}")
        self._dur_lbl.setStyleSheet(_SS_LABEL_DIM)
        time_row.addWidget(self._dur_lbl)
        time_row.addStretch()
        right.addLayout(time_row)

        # waveform — start with flat placeholder, fill async
        self._wf = WaveformWidget([0.3] * 60)
        self._wf.clicked_at.connect(self._seek_frac)
        right.addWidget(self._wf)

        row.addLayout(right, stretch=1)
        vl.addLayout(row)

        # ── Info label (filename + bitrate + LUFS) — shown below the waveform row ──
        self._info_lbl = _lbl(f"🎵  {fname}", "color:#6c7086;font-size:10px;background:transparent;")
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._info_lbl.setCursor(Qt.CursorShape.IBeamCursor)
        self._info_lbl.setToolTip(f"Имя файла: {fname}  (выделите для копирования)")
        self._info_lbl.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        def _audio_ctx_menu(pos, lbl=self._info_lbl):
            menu = QMenu(lbl)
            sel = lbl.selectedText()
            menu.addAction("Копировать имя файла").triggered.connect(
                lambda: QApplication.clipboard().setText(
                    lbl.text().replace("🎵  ", "").split("   ")[0].strip()))
            if sel:
                menu.addAction("Копировать выделенное").triggered.connect(
                    lambda: QApplication.clipboard().setText(sel))
            menu.exec(lbl.mapToGlobal(pos))
        self._info_lbl.customContextMenuRequested.connect(_audio_ctx_menu)
        vl.addWidget(self._info_lbl)

        # ── Single background thread: waveform + media-info + LUFS ──
        # Previously two threads were spawned per widget. Merging them
        # halves thread-creation overhead and avoids two concurrent disk reads.
        def _do_audio_bg(p=path, wf=self._wf, lbl=self._info_lbl,
                         fname_=fname, dur=dur_sec):
            bars    = _extract_waveform_bars(p)
            info_str = _get_media_info(p, is_video=False, dur_sec=dur)
            lufs    = _measure_lufs(p)
            full    = info_str + (f"  ·  {lufs}" if lufs else "")
            disp    = f"🎵  {fname_}" + (f"   {full}" if full else "")
            bridge  = _get_ui_bridge()
            bridge.deliver_call(lambda b=bars, w=wf: w.set_bars(b))
            bridge.deliver_text(lbl, disp)
        _threading.Thread(target=_do_audio_bg, daemon=True,
                          name="audio-bg").start()

        # ── Signals ──────────────────────────────────────────
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.setSource(QUrl.fromLocalFile(path))

    def _toggle_play(self):
        st = self._player.playbackState()
        if st == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.setPosition(0)
            self._wf.set_progress(0.0)
            self._play_btn.set_playing(False)
            self._wf.set_playing(False)

    def _on_state(self, state):
        playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        self._play_btn.set_playing(playing)
        self._wf.set_playing(playing)

    def _seek_frac(self, frac):
        dur = self._player.duration()
        if dur > 0: self._player.setPosition(int(dur * frac))

    def _on_position(self, pos_ms):
        self._time_lbl.setText(fmt_dur(pos_ms / 1000))
        dur = self._player.duration()
        if dur > 0: self._wf.set_progress(pos_ms / dur)

    def _on_duration(self, dur_ms):
        if dur_ms > 0:
            self._dur_lbl.setText(f"/ {fmt_dur(dur_ms / 1000)}")

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = e.position().toPoint(); self._dragging = False
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag_origin and not self._dragging:
            if (e.position().toPoint() - self._drag_origin).manhattanLength() > 8:
                self._dragging = True; self._drag_origin = None
                self.block_drag.emit(); return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        self._drag_origin = None; self._dragging = False
        super().mouseReleaseEvent(e)

    def stop(self):
        self._player.stop()

__all__ = [
    'AudioPlayerWidget',
    'CirclePlayButton',
    'MpvVideoPlayerWidget',
    'SEEK_SLIDER_STYLE',
    'SeekSlider',
    'VideoPlayerWidget',
    'WaveformWidget',
    '_AspectWidget',
]
