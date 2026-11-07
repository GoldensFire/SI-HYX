# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# meta_watermark.py — поиск и снятие видимой вотермарки Meta AI: белого
# полупрозрачного логотипа (восемь лепестков) и надписи «Meta AI» у правого
# нижнего угла.
#
# Знак всегда один и тот же, поэтому он ищется по эталонной маске в правом
# нижнем углу. Наложение белое с α ≈ 0.6, но из-за сжатия и разного фона
# точное альфа-смешивание неустойчиво; маску заливают по соседям (inpaint),
# как при удалении мелких надписей. На ровном фоне следов не остаётся.
#
# Здесь НЕТ Qt — только numpy / opencv.

import base64

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


# Маска знака (231×47) в градациях серого: контур сглажен, чтобы шаблон
# совпадал с antialiasing реальной вотермарки. PNG в base64, чтобы модуль
# оставался самодостаточным и не зависел от путей сборки.
_MASK_B64 = """
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
bDupdjcAAAAASUVORK5CYII=
"""

_SCORE_MIN = 0.68      # порог совпадения с эталоном
_SCORE_MIN_HINT = 0.60  # порог, когда имя файла намекает на Meta AI

_TEMPLATE = None


def _template():
    """Эталонная маска знака (float32 0..1), загружается один раз."""
    global _TEMPLATE
    if _TEMPLATE is None:
        raw = np.frombuffer(base64.b64decode(_MASK_B64), np.uint8)
        mask = cv2.imdecode(raw, cv2.IMREAD_GRAYSCALE)
        _TEMPLATE = mask.astype(np.float32) / 255.0
    return _TEMPLATE


def _resize(mask, width, height):
    """Масштабирует маску: уменьшение — площадным, увеличение — линейным."""
    interp = cv2.INTER_AREA if width < mask.shape[1] else cv2.INTER_LINEAR
    return cv2.resize(mask, (width, height), interpolation=interp)


def _search(template, high, x0, y0):
    """Лучшее совпадение шаблона в правом нижнем углу high."""
    search = high[y0:, x0:]
    if search.size == 0:
        return None
    best = None
    # Грубый перебор масштаба: знак бывает уменьшен/увеличен вместе с картинкой.
    scales = list(np.arange(0.5, 1.5001, 0.025))
    for coarse in (True, False):
        if coarse:
            items = scales
        else:
            s0 = best[1]
            items = np.arange(max(0.35, s0 - 0.03), min(1.8, s0 + 0.0301), 0.005)
        for s in items:
            tw = int(round(template.shape[1] * s))
            th = int(round(template.shape[0] * s))
            if tw < 24 or th < 8 or tw >= search.shape[1] or th >= search.shape[0]:
                continue
            t = _resize(template, tw, th)
            res = cv2.matchTemplate(search, t, cv2.TM_CCOEFF_NORMED)
            # Почти ровные окна (сплошной 0 или насыщение) дают ложную 1.0.
            mu = cv2.boxFilter(search, -1, (tw, th), anchor=(0, 0),
                               borderType=cv2.BORDER_CONSTANT)
            mu2 = cv2.boxFilter(search * search, -1, (tw, th), anchor=(0, 0),
                                borderType=cv2.BORDER_CONSTANT)
            var = (mu2 - mu * mu)[:res.shape[0], :res.shape[1]]
            res[(var < 1e-4) | ~np.isfinite(res)] = 0.0
            _, score, _, loc = cv2.minMaxLoc(res)
            if best is None or score > best[0]:
                best = (float(score), float(s), x0 + loc[0], y0 + loc[1], tw, th)
        if best is None:
            return None
    return best


def find_watermark(rgb, hint=False):
    """Ищет вотермарку Meta AI на картинке rgb (H×W×3/4, uint8).

    hint=True — имя файла уже говорит, что это Meta AI: порог чуть мягче.
    Возвращает словарь {x, y, w, h, score, scale} или None."""
    if cv2 is None or rgb is None or rgb.ndim != 3 or min(rgb.shape[:2]) < 120:
        return None
    img = rgb[..., :3]
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY).astype(np.float32)
    # Светлый знак на фоне: убираем плавную яркость, оставляем локальный подъём.
    # Белое наложение поднимает яркость на α·(255 − фон): на белой ткани это
    # единицы, на тёмной коже — сотни, и знак наполовину на светлом не
    # совпадал с эталоном (0.46). Доля подъёма до белого ≈ α на любом фоне.
    bg = cv2.medianBlur(gray.astype(np.uint8), 31).astype(np.float32)
    high = np.clip((gray - bg) / np.maximum(255.0 - bg, 24.0), 0.0, 1.0)
    h, w = gray.shape[:2]
    # Знак стоит у правого нижнего угла; область с запасом под масштаб.
    x0 = max(0, w - max(400, int(w * 0.45)))
    y0 = max(0, h - max(120, int(h * 0.28)))
    best = _search(_template(), high, x0, y0)
    if best is None:
        return None
    score, scale, x, y, tw, th = best
    if score < (_SCORE_MIN_HINT if hint else _SCORE_MIN):
        return None
    return {'x': int(x), 'y': int(y), 'w': int(tw), 'h': int(th),
            'score': score, 'scale': scale}


def remove_watermark(rgb, found, inpainter=None):
    """Снимает найденный знак: маску заливает по соседям, сохраняя фон
    вокруг. Альфа-смешивание не используется: у Meta AI цвет и
    прозрачность меняются от картинки к картинке, а край эталона не
    совпадает с краем знака — оставались тёмные контуры букв.

    inpainter — LaMa (lama_inpaint): дорисовывает линии рисунка под
    надписью, тогда как cv2.inpaint рвёт их в серые пятна. Ошибку LaMa
    не глушит: вызывающий решает, повторить ли без неё."""
    out = rgb.copy()
    h, w = rgb.shape[:2]
    mask = np.zeros((h, w), np.uint8)
    x, y = max(0, found['x']), max(0, found['y'])
    tw = min(found['w'], w - x)
    th = min(found['h'], h - y)
    if tw <= 0 or th <= 0:
        return out
    m = _resize(_template(), found['w'], found['h'])[:th, :tw]
    mask[y:y + th, x:x + tw] = (m > 0.12).astype(np.uint8)
    if inpainter is not None:
        bgr = np.ascontiguousarray(rgb[..., 2::-1])
        clean = inpainter.inpaint(bgr, mask * 255, dilate=2)
        out[..., :3] = clean[..., ::-1]
        return out
    # 1 px запаса закрывает возможное смещение совпадения на пиксель.
    mask = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    clean = cv2.inpaint(np.ascontiguousarray(rgb[..., :3]), mask, 4,
                        cv2.INPAINT_TELEA)
    out[..., :3] = clean
    return out
