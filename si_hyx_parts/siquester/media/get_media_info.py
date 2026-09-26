# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_get_media_info. Public namespace: siquester.media."""
import siquester.media as _api


def _get_media_info(path: str, is_video: bool, dur_sec: float = 0.0) -> str:
    """Compact info string: size, bitrate (audio stream accurate), resolution (video)."""
    parts = []
    try:
        size_bytes = _api.os.path.getsize(path)
        parts.append(f"{size_bytes / 1024 / 1024:.1f} МБ" if size_bytes >= 1_048_576
                     else f"{size_bytes // 1024} КБ")

        ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''

        if is_video:
            if dur_sec > 0:
                kbps = int(size_bytes * 8 / dur_sec / 1000)
                if kbps > 0: parts.append(f"~{kbps} кбит/с")
            # Resolution — try pure-Python parser first; mpv will override after load
            w, h = _api._mp4_video_size(path)
            if w and h: parts.append(f"{w}×{h}")
        else:
            # ── Audio bitrate ──────────────────────────────────────
            br = None
            read_sz = min(65536, size_bytes)
            with open(path, 'rb') as f:
                head = f.read(read_sz)
            if ext == 'mp3':
                br = _api._mp3_bitrate_kbps(head)
            elif ext in ('m4a', 'mp4', 'aac', 'mp4a'):
                br = _api._m4a_audio_bitrate_kbps(head)
                if br is None and size_bytes > read_sz:
                    # moov might be at end of file
                    with open(path, 'rb') as f:
                        f.seek(max(0, size_bytes - 262144))
                        tail = f.read(262144)
                    br = _api._m4a_audio_bitrate_kbps(tail)
            elif ext in ('ogg', 'opus', 'flac', 'wav', 'wma'):
                pass  # fall through to estimation
            # Any other format or failed parse → estimate from size/duration
            if br:
                parts.append(f"{br} кбит/с")
            elif dur_sec > 0:
                est = int(size_bytes * 8 / dur_sec / 1000)
                if est > 0: parts.append(f"~{est} кбит/с")
    except Exception as e:
        _api._logger.warning(f"[media_info] {e}")
    return "  ·  ".join(parts)

_get_media_info.__module__ = _api.__name__
_api._get_media_info = _get_media_info

class _ThreadBridge(_api.QObject):
    """Universal thread-safe bridge: emit from any thread, slots run on main thread.

    Three signal types cover all background→UI update patterns in this app:
      • pixmap_ready(QPixmap|None, QLabel)  — image delivery
      • text_ready(QLabel, str)             — label text update
      • call_ready(object)                  — arbitrary zero-arg callable
    All connections use Qt.QueuedConnection so slots always execute on the
    main (GUI) thread regardless of which thread emits.
    """
    pixmap_ready = _api.pyqtSignal(object, object)   # (QPixmap | None, QLabel)
    text_ready   = _api.pyqtSignal(object, str)       # (QLabel, text)
    call_ready   = _api.pyqtSignal(object)            # (callable,)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.pixmap_ready.connect(self._on_pixmap, _api.Qt.ConnectionType.QueuedConnection)
        self.text_ready.connect(self._on_text,     _api.Qt.ConnectionType.QueuedConnection)
        self.call_ready.connect(self._on_call,     _api.Qt.ConnectionType.QueuedConnection)

    def _on_pixmap(self, img, lbl):
        """Runs on main thread. Converts QImage → QPixmap (safe here) and sets on label."""
        try:
            if img and not img.isNull():
                pm = _api.QPixmap.fromImage(img)   # QPixmap creation: main thread only ✓
                lbl.setFixedHeight(pm.height())
                lbl.setPixmap(pm)
            else:
                lbl.setText("🖼  Формат не поддержан")
        except RuntimeError:
            pass

    def _on_text(self, lbl, text):
        try: lbl.setText(text)
        except RuntimeError: pass

    def _on_call(self, fn):
        try: fn()
        except RuntimeError: pass

    # ── Convenience methods called from background threads ──────
    def deliver(self, pm, lbl):
        self.pixmap_ready.emit(pm, lbl)

    def deliver_text(self, lbl, text: str):
        self.text_ready.emit(lbl, text)

    def deliver_call(self, fn):
        """Post a zero-arg callable to run on the main thread."""
        self.call_ready.emit(fn)

_ThreadBridge.__module__ = _api.__name__
_api._ThreadBridge = _ThreadBridge
