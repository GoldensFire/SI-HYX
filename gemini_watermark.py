# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# gemini_watermark.py — поиск и снятие видимой вотермарки Gemini: белой
# полупрозрачной «искры» (четыре вогнутых луча) у правого нижнего угла.
#
# Знак наложен обычным альфа-смешиванием с белым:
#     наблюдаемое = исходное·(1 − α·M) + 255·α·M,
# где M — антиалиасная маска звезды. Зная M и α, исходник восстанавливается
# точно, вместе с текстурой под звездой (а не дорисовывается, как у LaMa):
#     исходное = (наблюдаемое − 255·α·M) / (1 − α·M).
#
# Замеры по ~70 картинкам Gemini: полуразмах звезды 25.75 px, изгиб лучей 0.2;
# центр ровно в 56 px от правого и нижнего края при α = 0.50 (ранние картинки)
# или в 120 px при α = 0.29 (поздние) — независимо от размера картинки.
# Уменьшенные/увеличенные копии ищутся тем же шаблоном в масштабе.
#
# Здесь НЕТ Qt — только numpy / opencv.

import warnings

import numpy as np

try:
    import cv2
except Exception:  # pragma: no cover
    cv2 = None


_HALF = 25.75                              # полуразмах звезды при масштабе 1, px
_BEND = 0.2                                # контрольная точка луча: 0 — вогнутее, 0.5 — ромб
_PLACES = ((56.0, 0.50), (120.0, 0.29))    # (центр от угла, px; непрозрачность α)
_SEAM_MAX = 1.25                           # предел перепадов на краю после/до снятия


def _star_outline(n=32):
    """Контур звезды единичного полуразмаха: четыре квадратичные кривые
    Безье от луча к лучу с контрольной точкой у центра."""
    t = np.linspace(0.0, 1.0, n)
    qx = 2*t*(1 - t)*_BEND + t*t
    qy = -(1 - t)**2 - 2*t*(1 - t)*_BEND
    parts = []
    for sx, sy, rev in ((1, 1, False), (1, -1, True), (-1, -1, False), (-1, 1, True)):
        px, py = qx*sx, qy*sy
        if rev:
            px, py = px[::-1], py[::-1]
        parts.append(np.stack([px, py], 1))
    return np.concatenate(parts)


def _contour_probes(n=40):
    """Точки на краях лучей (без самых кончиков) и внешние нормали к ним."""
    t = np.linspace(0.12, 0.88, n)
    qx = 2*t*(1 - t)*_BEND + t*t
    qy = -(1 - t)**2 - 2*t*(1 - t)*_BEND
    nx = -(2*(1 - t) - 2*(1 - 2*t)*_BEND)
    ny = 2*(1 - 2*t)*_BEND + 2*t
    norm = np.hypot(nx, ny)
    sign = np.sign(nx*qx + ny*qy)
    nx, ny = nx/norm*sign, ny/norm*sign
    pts, nrm = [], []
    for sx, sy in ((1, 1), (1, -1), (-1, -1), (-1, 1)):
        pts.append(np.stack([qx*sx, qy*sy], 1))
        nrm.append(np.stack([nx*sx, ny*sy], 1))
    return np.concatenate(pts), np.concatenate(nrm)


_OUTLINE = _star_outline()
_PROBES, _NORMALS = _contour_probes()


def star_mask(size, cx, cy, half, supersample=8):
    """Маска звезды (0..1, float32) в квадрате size×size, центр (cx, cy)
    в пикселях окна. Края сглажены суперсэмплингом."""
    ss = supersample
    big = np.zeros((size*ss, size*ss), np.uint8)
    poly = (_OUTLINE*half + (cx, cy))*ss
    cv2.fillPoly(big, [np.round(poly*16).astype(np.int32)], 255, cv2.LINE_8, 4)
    return cv2.resize(big, (size, size), interpolation=cv2.INTER_AREA).astype(np.float32)/255


def _bilinear(img, x, y):
    x0 = np.floor(x).astype(np.int64)
    y0 = np.floor(y).astype(np.int64)
    fx = (x - x0)[..., None]
    fy = (y - y0)[..., None]
    x0 = x0.clip(0, img.shape[1] - 2)
    y0 = y0.clip(0, img.shape[0] - 2)
    top = img[y0, x0]*(1 - fx) + img[y0, x0 + 1]*fx
    bot = img[y0 + 1, x0]*(1 - fx) + img[y0 + 1, x0 + 1]*fx
    return top*(1 - fy) + bot*fy


def _contour_score(img, cx, cy, half):
    """Проверка по краю звезды для набора центров (cx, cy — массивы).

    В каждой точке края сравнивает пиксель чуть внутри и чуть снаружи:
    у вотермарки внутри светлее ровно на α·(255 − снаружи). Текстура фона
    даёт случайный знак (доля «светлее» около половины), а звезда — почти
    везде. Возвращает (доля точек с правдоподобным α, медианный α, доля
    точек, где фон не белый и α вообще измерим)."""
    cx = np.asarray(cx, np.float32)[..., None]
    cy = np.asarray(cy, np.float32)[..., None]
    d = max(1.5, half*0.06)
    px = cx + _PROBES[:, 0]*half
    py = cy + _PROBES[:, 1]*half
    inner = _bilinear(img, px - _NORMALS[:, 0]*d, py - _NORMALS[:, 1]*d)
    outer = _bilinear(img, px + _NORMALS[:, 0]*d, py + _NORMALS[:, 1]*d)
    room = 255.0 - outer
    lift = np.where(room > 24, (inner - outer)/np.maximum(room, 1), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        alpha = np.nanmean(lift, -1)
        valid = ~np.isnan(alpha)
        good = valid & (alpha > 0.08) & (alpha < 0.85)
        nvalid = valid.sum(-1)
        frac = good.sum(-1)/np.maximum(nvalid, 1)
        med = np.nanmedian(np.where(good, alpha, np.nan), -1)
    return frac, np.nan_to_num(med), nvalid/alpha.shape[-1]


def _search(img, scales, step=0.5, places=_PLACES):
    """Лучший кандидат по масштабам и местам знака:
    (доля, покрытие, α по краю, cx, cy, полуразмах, α места)."""
    h, w = img.shape[:2]
    best = None
    for s in scales:
        half = _HALF*s
        grid = np.arange(-2.0*s, 2.0*s + 1e-6, step*max(1.0, s))
        for off, opacity in places:
            cx0, cy0 = w - off*s, h - off*s
            if cx0 - 1.3*half < 2 or cy0 - 1.3*half < 2:
                continue
            X, Y = np.meshgrid(cx0 + grid, cy0 + grid)
            frac, med, cov = _contour_score(img, X.ravel(), Y.ravel(), half)
            i = int(np.argmax(frac + 0.01*cov))
            cand = (float(frac[i]), float(cov[i]), float(med[i]),
                    float(X.ravel()[i]), float(Y.ravel()[i]), half, opacity)
            if best is None or cand[0] + 0.01*cand[1] > best[0] + 0.01*best[1]:
                best = cand
    return best


def _window(img, cx, cy, half):
    h, w = img.shape[:2]
    r = int(np.ceil(half*1.3)) + 4
    x0, y0 = max(0, int(round(cx)) - r), max(0, int(round(cy)) - r)
    x1, y1 = min(w, int(round(cx)) + r), min(h, int(round(cy)) + r)
    return x0, y0, x1, y1


def _unblend(win, mask, alpha):
    a = (alpha*mask)[..., None]
    return (win - 255.0*a)/np.maximum(1.0 - a, 1e-3)


def _refine(img, cx, cy, half, alpha):
    """Подпиксельно подгоняет центр и размер так, чтобы после снятия знака
    на его краю не осталось ступеньки (сумма перепадов в полосе края —
    минимальна). α не подгоняется: на пёстром фоне такая подгонка
    занижает его, а у Gemini он постоянный для каждого из двух мест."""
    x0, y0, x1, y1 = _window(img, cx, cy, half*1.06)
    win = img[y0:y1, x0:x1]
    size = max(x1 - x0, y1 - y0)
    masks = {}

    def mask_for(dx, dy, hf):
        key = (round(dx, 3), round(dy, 3), round(hf, 4))
        if key not in masks:
            masks[key] = star_mask(size, cx + dx - x0, cy + dy - y0, hf)[:y1 - y0, :x1 - x0]
        return masks[key]

    m0 = mask_for(0.0, 0.0, half)
    band = cv2.dilate(((m0 > 0.01) & (m0 < 0.99)).astype(np.uint8),
                      np.ones((3, 3), np.uint8)) > 0
    band_y = band[1:] | band[:-1]
    band_x = band[:, 1:] | band[:, :-1]

    def cost(dx, dy, hf):
        out = _unblend(win, mask_for(dx, dy, hf), alpha)
        return float(np.abs(np.diff(out, axis=0))[band_y].sum()
                     + np.abs(np.diff(out, axis=1))[band_x].sum())

    before = float(np.abs(np.diff(win, axis=0))[band_y].sum()
                   + np.abs(np.diff(win, axis=1))[band_x].sum())
    cur = (0.0, 0.0, half)
    best = cost(*cur)
    for sxy, sh in ((0.5, 0.02), (0.25, 0.01), (0.125, 0.005)):
        improved = True
        while improved:
            improved = False
            dx, dy, hf = cur
            for cand in ((dx + sxy, dy, hf), (dx - sxy, dy, hf),
                         (dx, dy + sxy, hf), (dx, dy - sxy, hf),
                         (dx, dy, hf*(1 + sh)), (dx, dy, hf*(1 - sh))):
                if abs(cand[0]) > 2 or abs(cand[1]) > 2 or abs(cand[2]/half - 1) > 0.04:
                    continue
                c = cost(*cand)
                if c < best - 1e-6:
                    best, cur, improved = c, cand, True
    return cx + cur[0], cy + cur[1], cur[2], best/max(before, 1e-6)


def find_watermark(rgb, hint=False):
    """Ищет вотермарку Gemini на картинке rgb (H×W×3/4, uint8).

    hint=True — имя файла уже говорит, что это Gemini («Gemini_Generated_
    Image_…»): пороги мягче, знак находится и на почти белом фоне.
    Возвращает словарь {cx, cy, half, alpha, score, coverage} или None."""
    if cv2 is None or rgb is None or rgb.ndim != 3 or min(rgb.shape[:2]) < 160:
        return None
    img = rgb[..., :3].astype(np.float32)
    # Обычный случай — картинка в исходном размере Gemini.
    best = _search(img, (0.97, 1.0, 1.03))
    frac_min, cov_min = (0.7, 0.1) if hint else (0.8, 0.25)
    if not (best and best[0] >= frac_min and best[1] >= cov_min):
        # Уменьшенная или увеличенная копия: тот же угол в другом масштабе.
        # Перебор шире — и пороги строже, чтобы не принять за знак узор.
        # Сначала грубо по яркости, затем точно вокруг лучшего масштаба.
        frac_min, cov_min = (0.8, 0.2) if hint else (0.9, 0.4)
        hi = min(3.0, min(img.shape[:2])/240.0)
        scales = np.exp(np.arange(np.log(0.35), np.log(hi), 0.03))
        best = _search(img.mean(2, keepdims=True), scales, step=1.0)
        if not (best and best[0] >= frac_min - 0.15 and best[1] >= cov_min):
            return None
        s0 = best[5]/_HALF
        place = [p for p in _PLACES if p[1] == best[6]]
        best = _search(img, s0*np.exp(np.arange(-0.03, 0.0301, 0.0075)), places=place)
        if not (best and best[0] >= frac_min and best[1] >= cov_min):
            return None
    frac, cov, seen, cx, cy, half, alpha = best
    if not 0.12 <= seen <= 0.75:
        return None
    cx, cy, half, seam = _refine(img, cx, cy, half, alpha)
    # Контрольная проба: снятие настоящего знака убирает ступеньку на его
    # краю (seam < 1), а у ложной находки вырезает тёмную звезду (seam ≥ 1.5).
    # Между ними — знак на пёстром фоне, где снятие и усиливает текстуру.
    if seam > _SEAM_MAX:
        return None
    return {'cx': cx, 'cy': cy, 'half': half, 'alpha': alpha,
            'score': frac, 'coverage': cov, 'seam': seam}


def remove_watermark(rgb, found):
    """Снимает найденный знак: обратное альфа-смешивание, затем тонкую
    полосу края (1–2 px, где маска дробная) дорисовывает по соседям."""
    out = rgb.copy()
    cx, cy, half, alpha = found['cx'], found['cy'], found['half'], found['alpha']
    x0, y0, x1, y1 = _window(rgb, cx, cy, half*1.06)
    size = max(x1 - x0, y1 - y0)
    m = star_mask(size, cx - x0, cy - y0, half)[:y1 - y0, :x1 - x0]
    win = rgb[y0:y1, x0:x1, :3].astype(np.float32)
    clean = _unblend(win, m, alpha).clip(0, 255).astype(np.uint8)
    edge = ((m > 0.02) & (m < 0.98)).astype(np.uint8)
    clean = cv2.inpaint(np.ascontiguousarray(clean), edge, 2, cv2.INPAINT_TELEA)
    out[y0:y1, x0:x1, :3] = clean
    return out
