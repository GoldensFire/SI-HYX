# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Преобразования numpy ↔ QImage и загрузка альфы картинки. Public namespace: photo_tab."""
import photo_tab as _api


def np_bgr_to_qimage(arr):
    """BGR uint8 (H, W, 3) → QImage (RGB888). Делает .copy(): иначе QImage держит
    ссылку на буфер numpy, который освободится → висячий указатель и краш."""
    arr = _api._np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    rgb = _api._np.ascontiguousarray(_api._cv2.cvtColor(arr, _api._cv2.COLOR_BGR2RGB))
    img = _api.QtGuiImage(rgb.data, w, h, 3 * w, _api.QtGuiImage.Format.Format_RGB888)
    return img.copy()

np_bgr_to_qimage.__module__ = _api.__name__
_api.np_bgr_to_qimage = np_bgr_to_qimage

def qimage_to_np_bgr(img):
    """QImage → BGR uint8 (H, W, 3). Учитывает выравнивание строк (bytesPerLine),
    иначе при ширине не кратной 4 картинка «съезжает»."""
    img = img.convertToFormat(_api.QtGuiImage.Format.Format_RGB888)
    w, h = img.width(), img.height()
    bpl = img.bytesPerLine()
    ptr = img.constBits(); ptr.setsize(bpl * h)
    buf = _api._np.frombuffer(ptr, _api._np.uint8).reshape(h, bpl)
    rgb = buf[:, :w * 3].reshape(h, w, 3)
    return _api._np.ascontiguousarray(_api._cv2.cvtColor(rgb, _api._cv2.COLOR_RGB2BGR))

qimage_to_np_bgr.__module__ = _api.__name__
_api.qimage_to_np_bgr = qimage_to_np_bgr

def np_bgra_to_qimage(arr):
    """BGRA uint8 (H, W, 4) → QImage (Format_RGBA8888) с альфа-каналом.
    BGRA → RGBA перестановкой каналов (Format_RGBA8888 — порядок R,G,B,A в памяти)."""
    arr = _api._np.ascontiguousarray(arr)
    h, w = arr.shape[:2]
    rgba = _api._np.ascontiguousarray(arr[:, :, [2, 1, 0, 3]])  # BGRA → RGBA
    img = _api.QtGuiImage(rgba.data, w, h, 4 * w, _api.QtGuiImage.Format.Format_RGBA8888)
    return img.copy()

np_bgra_to_qimage.__module__ = _api.__name__
_api.np_bgra_to_qimage = np_bgra_to_qimage

def _load_image_alpha(path: str):
    """Загружает изображение сохраняя альфа-канал, если он есть.
    Возвращает BGRA uint8 (H,W,4) при наличии прозрачности, иначе BGR (H,W,3).
    Используется при добавлении overlay, чтобы PNG с прозрачностью не давал серый фон.

    Pillow — ОСНОВНОЙ путь (а не запасной): cv2.IMREAD_UNCHANGED роняет альфу у
    палитровых PNG c tRNS и у grayscale+alpha (декодит как BGR без прозрачности —
    отсюда серый фон у бейджей). Pillow достаёт альфу надёжно во всех вариантах
    (P+transparency, LA, PA, RGBA). Перестановку каналов делаем numpy-индексами,
    чтобы не зависеть от наличия cv2."""
    if _api._np is None:
        from lama_inpaint import load_bgr as _lb  # noqa — запасной вариант
        return _lb(path)
    try:
        from PIL import Image
        with Image.open(path) as pil:
            pil.load()
            has_alpha = (pil.mode in ('RGBA', 'LA', 'PA', 'La')
                         or (pil.mode in ('P', 'PA') and 'transparency' in pil.info)
                         or 'transparency' in pil.info)
            if has_alpha:
                rgba = _api._np.asarray(pil.convert('RGBA'), dtype=_api._np.uint8)
                return _api._np.ascontiguousarray(rgba[:, :, [2, 1, 0, 3]])  # RGBA → BGRA
            rgb = _api._np.asarray(pil.convert('RGB'), dtype=_api._np.uint8)
            return _api._np.ascontiguousarray(rgb[:, :, ::-1])               # RGB → BGR
    except Exception:
        pass
    # Фолбэк через OpenCV (если Pillow недоступен/не осилил формат).
    if _api._cv2 is not None:
        data = _api._np.fromfile(path, dtype=_api._np.uint8)
        img = _api._cv2.imdecode(data, _api._cv2.IMREAD_UNCHANGED) if data.size else None
        if img is not None:
            if img.ndim == 2:               # grayscale → BGR
                img = _api._cv2.cvtColor(img, _api._cv2.COLOR_GRAY2BGR)
            return _api._np.ascontiguousarray(img)  # 3ch=BGR, 4ch=BGRA
    from lama_inpaint import load_bgr as _lb
    return _lb(path)

_load_image_alpha.__module__ = _api.__name__
_api._load_image_alpha = _load_image_alpha
