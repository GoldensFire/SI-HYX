# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ProcessWorker: _crop_from_counts. Public namespace: workers."""
import workers as _api


@classmethod
def _crop_from_counts(cls, row_counts, col_counts, iw: int, ih: int):
    """(w, h, x, y) рамки без полос — по числу ЯРКИХ пикселей в каждой
        строке/столбце кадра (максимум по всем просмотренным кадрам), либо None,
        если обрезать нечего.

        Линия считается полосой, когда ярких пикселей в ней не больше допуска на
        шум: одиночные засветки полосу не отменяют, а сотня пикселей — это уже
        содержимое, и трогать такую линию нельзя."""
    tol_row = max(cls._CROP_NOISE_MIN, int(iw * cls._CROP_NOISE_SHARE))
    tol_col = max(cls._CROP_NOISE_MIN, int(ih * cls._CROP_NOISE_SHARE))
    rows = [i for i, c in enumerate(row_counts) if c > tol_row]
    cols = [i for i, c in enumerate(col_counts) if c > tol_col]
    if not rows or not cols:
        return None      # весь сэмпл чёрный (затемнение/пустая сцена) — не режем
    y0, y1 = int(rows[0]), int(rows[-1])
    x0, x1 = int(cols[0]), int(cols[-1])
    # yuv420 (и тем более SVT-AV1) требует чётных размеров. Округляем ТОЛЬКО
    # наружу: смещение — к меньшему чётному, размер — к большему. Иначе
    # округление само срезало бы строку-столбец содержимого.
    x0 -= x0 % 2
    y0 -= y0 % 2
    w = x1 - x0 + 1
    h = y1 - y0 + 1
    if w % 2:
        w = min(w + 1, iw - x0)
    if h % 2:
        h = min(h + 1, ih - y0)
    if w <= 0 or h <= 0 or w % 2 or h % 2:
        return None
    if w >= iw - 2 and h >= ih - 2:
        return None      # рамка совпала с кадром — полос нет
    return w, h, x0, y0

@classmethod
def _detect_crop(cls, path: str, dur: float = 0.0, start: float = 0.0):
    """Рамка видео без чёрных полос: строка 'w:h:x:y' для фильтра crop или
        None, если полос нет.

        Считаем сами по нескольким кадрам, а НЕ через ffmpeg cropdetect: тот
        решает по средней яркости линии, и строка «чёрная везде, кроме мелкого
        яркого элемента» для него полоса. На записи экрана 1920×1080 это срезало
        18 строк с панелью задач вместе с реальными полосами по бокам (проверено
        на файле пользователя: cropdetect давал 1728:1062:96:0, тогда как
        содержимое идёт до 1078-й строки). Здесь линия — полоса, только если
        ярких пикселей в ней не больше допуска на шум (см. _crop_from_counts).

        Пропускаем первые ~10% (интро/логотипы на чёрном дают ложную рамку) и
        смотрим ограниченный отрезок: несколько кадров, а не весь файл.
        start — смещение начала отрезка (при обрезке сэмплить надо внутри
        [in_s,out_s), а не с начала файла)."""
    try:
        import numpy as np
        pr = _api.subprocess.run(
            [_api.FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height",
             "-of", "csv=p=0:s=x", path],
            stdout=_api.subprocess.PIPE, stderr=_api.subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace",
            creationflags=_api.CREATE_NO_WINDOW, timeout=30,
        )
        iw, ih = (int(v) for v in _api.csv_fields(pr.stdout, "x")[:2])
        if iw <= 0 or ih <= 0:
            return None
        # Чем крупнее кадр, тем меньше кадров берём — выборка целиком лежит
        # в памяти (серый кадр = w*h байт).
        frames = max(4, min(12, cls._CROP_SAMPLE_BYTES // max(1, iw * ih)))
        win = cls._CROP_WINDOW_SEC
        ss = start + (dur * 0.1 if dur and dur > win else 0.0)
        fps = max(1.0, frames / win)
        cmd = [_api.FFMPEG, "-hide_banner", "-nostdin"]
        if ss > 0:
            cmd += ["-ss", f"{ss:.2f}"]
        cmd += [
            "-i", path, "-t", f"{win:.2f}",
            "-vf", f"fps={fps:g},format=gray",
            "-frames:v", str(frames), "-an", "-sn",
            "-f", "rawvideo", "-pix_fmt", "gray", "-",
        ]
        p = _api.subprocess.run(cmd, stdout=_api.subprocess.PIPE,
                           stderr=_api.subprocess.DEVNULL,
                           creationflags=_api.CREATE_NO_WINDOW)
        buf, size = p.stdout or b"", iw * ih
        n = len(buf) // size
        if n == 0:
            return None
        a = np.frombuffer(buf[:n * size], dtype=np.uint8).reshape(n, ih, iw)
        bright = a > cls._CROP_LUMA_LIMIT
        # Максимум по кадрам, а не сумма/среднее: полоса обязана быть чёрной
        # во ВСЕХ просмотренных кадрах, иначе это содержимое, которое просто
        # темнеет местами.
        row_counts = bright.sum(axis=2).max(axis=0)
        col_counts = bright.sum(axis=1).max(axis=0)
        box = cls._crop_from_counts(row_counts, col_counts, iw, ih)
        if box is None:
            return None
        w, h, x, y = box
        return f"{w}:{h}:{x}:{y}"
    except Exception:
        return None

@staticmethod
def _choose_pix_fmt(has_alpha: bool) -> str:
    """Возвращает pix_fmt с учётом альфа-канала. Всегда 10-бит
        (yuv420p10le/yuva420p10le) — выбора 8-бит в настройках больше нет."""
    return "yuva420p10le" if has_alpha else "yuv420p10le"

@staticmethod
def _target_dims(ow, oh, adim=0, wlim=0, hlim=0):
    """Целевой размер картинки с учётом всех активных пределов сразу:
        макс. сторона (adim), макс. ширина (wlim), макс. высота (hlim). Пропорции
        сохраняются, применяется самый строгий предел, увеличение не делается.
        Возвращает (w, h) чётные, либо None если ужимать не нужно / размер неизвестен."""
    try:
        ow, oh = int(ow), int(oh)
    except Exception:
        return None
    if ow <= 0 or oh <= 0:
        return None
    factor = 1.0
    if adim and adim > 0: factor = min(factor, adim / max(ow, oh))
    if wlim and wlim > 0: factor = min(factor, wlim / ow)
    if hlim and hlim > 0: factor = min(factor, hlim / oh)
    if factor >= 1.0:
        return None  # уже вписывается во все пределы — не трогаем
    tw = max(2, int(round(ow * factor)))
    th = max(2, int(round(oh * factor)))
    tw -= tw % 2; th -= th % 2  # чётные стороны — безопасно для 4:2:0/4:2:2
    return (max(2, tw), max(2, th))
