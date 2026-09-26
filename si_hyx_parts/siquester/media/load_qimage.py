# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_load_qimage. Public namespace: siquester.media."""
import siquester.media as _api


def _load_qimage(path: str, width: int) -> '_api.QImage | None':
    """Decode and scale an image to QImage. SAFE to call from any thread."""
    key = (path, width)
    if key in _api._IMAGE_CACHE:
        return _api._IMAGE_CACHE[key]

    img = None

    # ── Attempt 1: QImageReader ───────────────────────────────────
    reader = _api.QImageReader(path)
    reader.setAutoTransform(True)
    if reader.canRead():
        qimg = reader.read()
        if not qimg.isNull():
            img = qimg.scaledToWidth(width, _api.Qt.TransformationMode.SmoothTransformation)

    # ── Attempt 2: Pillow (+ pillow-heif for AVIF/HEIC) ──────────
    if img is None or img.isNull():
        try:
            from PIL import Image as _PILImage
            with _PILImage.open(path) as _pil:
                _pil = _pil.convert("RGBA")
                w_px, h_px = _pil.size
                raw = bytes(_pil.tobytes("raw", "RGBA"))
            qimg2 = _api.QImage(raw, w_px, h_px, w_px * 4,
                           _api.QImage.Format.Format_RGBA8888).copy()
            if not qimg2.isNull():
                img = qimg2.scaledToWidth(width, _api.Qt.TransformationMode.SmoothTransformation)
        except Exception as e:
            _api._logger.warning(f"[img] failed: {e!r} | {path}")

    if img and not img.isNull():
        if len(_api._IMAGE_CACHE) >= _api._IMAGE_CACHE_MAX:
            _api._IMAGE_CACHE.pop(next(iter(_api._IMAGE_CACHE)))
        _api._IMAGE_CACHE[key] = img
        return img
    return None

_load_qimage.__module__ = _api.__name__
_api._load_qimage = _load_qimage

def _img_size_from_path(path: str) -> tuple[int, int]:
    """Return (width, height) from image header without full decode. (0,0) on failure.
    Tries QImageReader first; falls back to Pillow (+ pillow-heif for AVIF/HEIC).
    """
    reader = _api.QImageReader(path)
    sz = reader.size()
    if sz.isValid() and sz.width() > 0:
        return sz.width(), sz.height()
    # Pillow fallback — pillow-heif registered at import time handles AVIF
    try:
        from PIL import Image as _PILImage
        with _PILImage.open(path) as _pil:
            return _pil.width, _pil.height
    except Exception:
        pass
    return 0, 0

_img_size_from_path.__module__ = _api.__name__
_api._img_size_from_path = _img_size_from_path
