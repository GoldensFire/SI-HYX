# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_CompareProxyWorker. Public namespace: widgets."""
import widgets as _api


class _CompareProxyWorker(_api.QThread):
    """AV1 в QtMultimedia (ffmpeg-бэкенд) на части железа (iGPU без
    аппаратного AV1-декодера — см. комментарий про video_hw_decode в
    config.py) рендерится чёрным экраном при прямом воспроизведении — ровно
    как уже наблюдалось в SiQuesterHYX. «Обработка» по умолчанию перекодирует
    в AV1, поэтому «Результат» в сравнении почти всегда именно такой файл.
    Чиним тем же способом, что и «Монтаж» с AV1-прокси: если исходный кодек —
    av1, быстро перегоняем во временный H.264-файл (ultrafast) и играем его
    вместо оригинала. Не-AV1 файлы отдаём как есть — без лишней перекодировки."""
    ready = _api.pyqtSignal(str, str)  # role, путь для воспроизведения (прокси или оригинал)

    def __init__(self, role, path, parent=None):
        super().__init__(parent)
        self.role = role
        self.path = path

    def run(self):
        out_path = self.path
        try:
            if _api._probe_video_codec(self.path) == 'av1':
                tmp = _api.os.path.join(_api.TEMP_DIR, f"sihyx_cmp_{_api.uuid.uuid4().hex}.mp4")
                cmd = [_api.FFMPEG, "-y", "-i", self.path,
                       "-c:v", "libx264", "-preset", "ultrafast", "-crf", "20",
                       "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                       "-movflags", "+faststart", tmp]
                r = _api.subprocess.run(cmd, capture_output=True,
                                   creationflags=_api.CREATE_NO_WINDOW, timeout=1800)
                if r.returncode == 0 and _api.os.path.exists(tmp) and _api.os.path.getsize(tmp) > 0:
                    out_path = tmp
        except Exception:
            pass
        self.ready.emit(self.role, out_path)

_CompareProxyWorker.__module__ = _api.__name__
_api._CompareProxyWorker = _CompareProxyWorker

class _ZoomVideoView(_api.QGraphicsView):
    """QGraphicsView с видео внутри — колесо зумит, перетаскивание панорамирует
    (ScrollHandDrag), синхронно с парным видом через owner (VideoCompareViewer)."""
    def __init__(self, owner=None, parent=None):
        super().__init__(parent)
        self._owner = owner
        self._fitted = True
        self.setStyleSheet("background:#0e0e16;border:none;")
        self.setFrameShape(_api.QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setRenderHint(_api.QPainter.RenderHint.SmoothPixmapTransform)
        self.setDragMode(_api.QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(_api.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        scene = _api.QGraphicsScene(self)
        self.setScene(scene)
        self.video_item = _api.QGraphicsVideoItem()
        scene.addItem(self.video_item)
        self.horizontalScrollBar().valueChanged.connect(lambda v: self._on_scroll('h', v))
        self.verticalScrollBar().valueChanged.connect(lambda v: self._on_scroll('v', v))

    def set_native_size(self, size):
        if not size.isValid() or size.isEmpty():
            return
        self.video_item.setSize(_api.QSizeF(size))
        self.scene().setSceneRect(0, 0, size.width(), size.height())
        if self._fitted:
            self.fitInView(self.video_item, _api.Qt.AspectRatioMode.KeepAspectRatio)

    def apply_zoom_factor(self, factor):
        self._fitted = False
        self.scale(factor, factor)

    def reset_fit(self):
        self._fitted = True
        self.fitInView(self.video_item, _api.Qt.AspectRatioMode.KeepAspectRatio)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._fitted:
            self.fitInView(self.video_item, _api.Qt.AspectRatioMode.KeepAspectRatio)

    def wheelEvent(self, e):
        delta = e.angleDelta().y()
        if delta == 0:
            return
        factor = 1.2 if delta > 0 else 1.0 / 1.2
        if self._owner is not None:
            self._owner._broadcast_zoom(factor)
        e.accept()

    def _on_scroll(self, axis, val):
        if self._owner is not None:
            self._owner._sync_scroll(axis, self, val)

_ZoomVideoView.__module__ = _api.__name__
_api._ZoomVideoView = _ZoomVideoView
