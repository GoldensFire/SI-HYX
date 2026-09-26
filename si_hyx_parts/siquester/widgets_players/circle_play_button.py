# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""CirclePlayButton. Public namespace: siquester.widgets_players."""
import siquester.widgets_players as _api


class CirclePlayButton(_api.QWidget):
    """Painted circular button showing a proper play triangle or pause bars."""
    clicked = _api.pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._playing = False
        self._hovered = False
        self._pressed = False
        self.setFixedSize(44, 44)
        self.setCursor(_api.Qt.CursorShape.PointingHandCursor)

    def set_playing(self, playing: bool):
        self._playing = playing
        self.update()

    def paintEvent(self, _):
        p = _api.QPainter(self)
        p.setRenderHint(_api.QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - 1.5

        # Circle fill
        if self._pressed:
            bg = _api.QColor("#cba6f7")
        elif self._hovered:
            bg = _api.QColor("#cba6f7")
        else:
            bg = _api.QColor("#cba6f7")
        p.setBrush(_api.QBrush(bg))
        p.setPen(_api.Qt.PenStyle.NoPen)
        p.drawEllipse(_api.QRectF(cx - r, cy - r, r * 2, r * 2))

        # Icon — white
        p.setBrush(_api.QBrush(_api.QColor("white")))
        p.setPen(_api.Qt.PenStyle.NoPen)

        if self._playing:
            # Pause: two rounded rectangles
            bw, bh, gap = 4.0, 13.0, 5.0
            x1 = cx - gap / 2 - bw
            x2 = cx + gap / 2
            p.drawRoundedRect(_api.QRectF(x1, cy - bh / 2, bw, bh), 2, 2)
            p.drawRoundedRect(_api.QRectF(x2, cy - bh / 2, bw, bh), 2, 2)
        else:
            # Play: filled triangle, shifted slightly right for optical balance
            path = _api.QPainterPath()
            ts = 13.0
            ox = 1.5
            path.moveTo(cx - ts * 0.38 + ox, cy - ts * 0.5)
            path.lineTo(cx + ts * 0.62 + ox, cy)
            path.lineTo(cx - ts * 0.38 + ox, cy + ts * 0.5)
            path.closeSubpath()
            p.fillPath(path, _api.QBrush(_api.QColor("white")))

        p.end()

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._pressed = True; self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
            self._pressed = False; self.update()
            if self.rect().contains(e.position().toPoint()):
                self.clicked.emit()
        super().mouseReleaseEvent(e)

    def enterEvent(self, e):
        self._hovered = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hovered = False; self._pressed = False; self.update(); super().leaveEvent(e)

CirclePlayButton.__module__ = _api.__name__
_api.CirclePlayButton = CirclePlayButton

class AudioPlayerWidget(_api.QWidget):
    """Audio: circular play/pause + real-amplitude waveform (messenger style)."""
    block_drag = _api.pyqtSignal()

    def __init__(self, path: str, fname: str, dur_sec: float, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background:#1e1e2e;border-radius:10px;")
        self._drag_origin = None; self._dragging = False

        self._player = _api.QMediaPlayer(self)
        self._aout = _api.QAudioOutput(self)
        self._player.setAudioOutput(self._aout)
        self._aout.setVolume(1.0)

        vl = _api.QVBoxLayout(self); vl.setContentsMargins(10, 8, 10, 8); vl.setSpacing(4)

        # ── Main playback row: [●play] [time / dur] [waveform] ─
        row = _api.QHBoxLayout(); row.setSpacing(10)

        self._play_btn = _api.CirclePlayButton()
        self._play_btn.clicked.connect(self._toggle_play)
        row.addWidget(self._play_btn, alignment=_api._AlignVC)

        right = _api.QVBoxLayout(); right.setSpacing(2)

        # time / duration on one mini row
        time_row = _api.QHBoxLayout(); time_row.setContentsMargins(0, 0, 0, 0); time_row.setSpacing(4)
        self._time_lbl = _api.QLabel("0:00")
        self._time_lbl.setStyleSheet("color:#cdd6f4;font-size:10px;font-weight:700;background:transparent;")
        time_row.addWidget(self._time_lbl)
        total_str = _api.fmt_dur(dur_sec) if dur_sec else "--:--"
        self._dur_lbl = _api.QLabel(f"/ {total_str}")
        self._dur_lbl.setStyleSheet(_api._SS_LABEL_DIM)
        time_row.addWidget(self._dur_lbl)
        time_row.addStretch()
        right.addLayout(time_row)

        # waveform — start with flat placeholder, fill async
        self._wf = _api.WaveformWidget([0.3] * 60)
        self._wf.clicked_at.connect(self._seek_frac)
        right.addWidget(self._wf)

        row.addLayout(right, stretch=1)
        vl.addLayout(row)

        # ── Info label (filename + bitrate + LUFS) — shown below the waveform row ──
        self._info_lbl = _api._lbl(f"🎵  {fname}", "color:#6c7086;font-size:10px;background:transparent;")
        self._info_lbl.setWordWrap(True)
        self._info_lbl.setTextInteractionFlags(_api.Qt.TextInteractionFlag.TextSelectableByMouse)
        self._info_lbl.setCursor(_api.Qt.CursorShape.IBeamCursor)
        self._info_lbl.setToolTip(f"Имя файла: {fname}  (выделите для копирования)")
        self._info_lbl.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
        def _audio_ctx_menu(pos, lbl=self._info_lbl):
            menu = _api.QMenu(lbl)
            sel = lbl.selectedText()
            menu.addAction("Копировать имя файла").triggered.connect(
                lambda: _api.QApplication.clipboard().setText(
                    lbl.text().replace("🎵  ", "").split("   ")[0].strip()))
            if sel:
                menu.addAction("Копировать выделенное").triggered.connect(
                    lambda: _api.QApplication.clipboard().setText(sel))
            menu.exec(lbl.mapToGlobal(pos))
        self._info_lbl.customContextMenuRequested.connect(_audio_ctx_menu)
        vl.addWidget(self._info_lbl)

        # ── Single background thread: waveform + media-info + LUFS ──
        # Previously two threads were spawned per widget. Merging them
        # halves thread-creation overhead and avoids two concurrent disk reads.
        def _do_audio_bg(p=path, wf=self._wf, lbl=self._info_lbl,
                         fname_=fname, dur=dur_sec):
            bars    = _api._extract_waveform_bars(p)
            info_str = _api._get_media_info(p, is_video=False, dur_sec=dur)
            lufs    = _api._measure_lufs(p)
            full    = info_str + (f"  ·  {lufs}" if lufs else "")
            disp    = f"🎵  {fname_}" + (f"   {full}" if full else "")
            bridge  = _api._get_ui_bridge()
            bridge.deliver_call(lambda b=bars, w=wf: w.set_bars(b))
            bridge.deliver_text(lbl, disp)
        _api._threading.Thread(target=_do_audio_bg, daemon=True,
                          name="audio-bg").start()

        # ── Signals ──────────────────────────────────────────
        self._player.positionChanged.connect(self._on_position)
        self._player.durationChanged.connect(self._on_duration)
        self._player.playbackStateChanged.connect(self._on_state)
        self._player.mediaStatusChanged.connect(self._on_media_status)
        self._player.setSource(_api.QUrl.fromLocalFile(path))

    def _toggle_play(self):
        st = self._player.playbackState()
        if st == _api.QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_media_status(self, status):
        if status == _api.QMediaPlayer.MediaStatus.EndOfMedia:
            self._player.setPosition(0)
            self._wf.set_progress(0.0)
            self._play_btn.set_playing(False)
            self._wf.set_playing(False)

    def _on_state(self, state):
        playing = (state == _api.QMediaPlayer.PlaybackState.PlayingState)
        self._play_btn.set_playing(playing)
        self._wf.set_playing(playing)

    def _seek_frac(self, frac):
        dur = self._player.duration()
        if dur > 0: self._player.setPosition(int(dur * frac))

    def _on_position(self, pos_ms):
        self._time_lbl.setText(_api.fmt_dur(pos_ms / 1000))
        dur = self._player.duration()
        if dur > 0: self._wf.set_progress(pos_ms / dur)

    def _on_duration(self, dur_ms):
        if dur_ms > 0:
            self._dur_lbl.setText(f"/ {_api.fmt_dur(dur_ms / 1000)}")

    def mousePressEvent(self, e):
        if e.button() == _api.Qt.MouseButton.LeftButton:
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

AudioPlayerWidget.__module__ = _api.__name__
_api.AudioPlayerWidget = AudioPlayerWidget
