# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# hdr_tonemap.py — HDR10 (PQ) в SDR BT.709 при экспорте «Монтажа» так, как
# кадр выглядит в его просмотре.
"""Тонмаппинг HDR10 при экспорте «Монтажа»: вид как в просмотре.

Просмотр «Монтажа» рисует PQ-кадр шейдером Qt nv12_bt2020_pq (тонмаппинг
BT.2390 по яркости мастеринга, BT.2020 → sRGB; см. edit_tab_frames). Экспорт
повторяет ту же формулу 3D-таблицей для фильтра lut3d: кадр переводится в
R'G'B' BT.2020 (PQ), таблица даёт sRGB BT.709, и файл выходит SDR с тегами
BT.709 и без HDR-метаданных — в любом плеере он такой же, как в просмотре.

Раньше экспорт писал PQ-кадр как есть в H.264 (8 бит — полосы на градиентах,
High 10 — не играют многие декодеры) с HDR-тегами: без HDR-экрана картинка
выходила блёклой. SDR-источники и HLG этот модуль не трогает."""
import json
import os
import subprocess

from ffmpeg_env import CREATE_NO_WINDOW, FFPROBE, TEMP_DIR

LUT_SIZE = 65               # узлов на канал: тетраэдрическая интерполяция ±1 уровень
SDR_NITS = 100.0            # белый SDR, к которому шейдер Qt сводит яркость
SDR_COLOR_ARGS = ["-color_primaries", "bt709", "-color_trc", "bt709",
                  "-colorspace", "bt709"]
_RGB_FORMATS = ("rgb24", "bgr24")
# Матрица YUV → RGB по тегу colorspace: BT.709 или BT.601 (PAL/NTSC).
_SDR_MATRICES = {"bt709": "bt709", "bt470bg": "smpte170m", "smpte170m": "smpte170m"}
# Без тега SD-видео плееры (и Qt) читают по BT.601, выше 576 строк — по BT.709.
_SD_MAX_HEIGHT = 576

_PROPS_CACHE = {}


def _pq_from_linear(sig):
    """PQ-сигнал (ST 2084) от яркости в долях SDR-белого (1.0 = 100 кд/м²),
    как pq_from_linear шейдера Qt."""
    m1, m2 = 1305 / 8192, 2523 / 32
    c1, c2, c3 = 107 / 128, 2413 / 128, 2392 / 128
    p = (sig * 100.0 / 10000.0) ** m1
    return ((c1 + c2 * p) / (1 + c3 * p)) ** m2


def qt_pq_to_srgb(y, rgb, max_luminance, max_nits=SDR_NITS):
    """sRGB BT.709 (три массива 0..1) из PQ-сигнала BT.2020 — формула шейдера
    Qt nv12_bt2020_pq, та же, что у edit_tab_frames.qt_pq_image.

    y — яркость Y' в полном диапазоне 0..1, rgb — (R', G', B') в полном
    диапазоне, max_luminance — maxLuminance кадра у Qt
    (media_probe.qt_pq_max_luminance: яркость мастеринга × 10000)."""
    import numpy as np

    mw = _pq_from_linear(max_luminance / 100.0)
    ml = _pq_from_linear(max_nits / 100.0)
    # Тонмаппинг BT.2390 по яркости (tonemapScaleForLuminosity шейдера Qt).
    p = y / mw
    ks = 1.5 * ml - 0.5
    t = (p - ks) / (1.0 - ks)
    t2, t3 = t * t, t * t * t
    pn = (2 * t3 - 3 * t2 + 1) * ks + (t3 - 2 * t2 + t) * (1 - ks) + (-2 * t3 + 3 * t2) * ml
    with np.errstate(divide="ignore", invalid="ignore"):
        scale = np.where(p < ks, 1.0, pn * mw / y)
        lin = []
        for ch in rgb:
            e = np.power(ch * scale, 32 / 2523)        # отрицательное → NaN → чёрный, как у Qt
            num = np.maximum(e - 107 / 128, 0)
            den = 2413 / 128 - e * 2392 / 128
            lin.append(np.power(num / den, 8192 / 1305) * 100.0)
        m = ((1.6605, -0.5876, -0.0728), (-0.1246, 1.1329, -0.0083), (-0.0182, -0.1006, 1.1187))
        out = []
        for row in m:
            o = row[0] * lin[0] + row[1] * lin[1] + row[2] * lin[2]
            hi = np.power(np.maximum(o, 0), 1 / 2.4) * 1.055 - 0.055
            o = np.where(o <= 0.0031308, o * 12.92, hi)
            out.append(np.clip(np.nan_to_num(o, nan=0.0), 0.0, 1.0))
    return out


def qt_pq_lut(max_luminance):
    """Путь к .cube-таблице PQ BT.2020 → sRGB BT.709 под эту яркость
    мастеринга. Таблица одна на яркость и живёт в TEMP_DIR между экспортами:
    расчёт и запись 65³ узлов — около секунды."""
    import numpy as np

    path = os.path.join(TEMP_DIR, f"sihyx_qt_pq_{LUT_SIZE}_{int(round(max_luminance))}.cube")
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    g = np.linspace(0.0, 1.0, LUT_SIZE)
    # Порядок узлов .cube: быстрее всех меняется R, медленнее всех — B.
    b, gg, r = (a.ravel() for a in np.meshgrid(g, g, g, indexing="ij"))
    y = 0.2627 * r + 0.6780 * gg + 0.0593 * b          # Y' BT.2020 NCL
    out = np.stack(qt_pq_to_srgb(y, (r, gg, b), max_luminance), axis=-1)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"LUT_3D_SIZE {LUT_SIZE}\n")
        np.savetxt(f, out, fmt="%.6f")
    os.replace(tmp, path)
    return path


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _video_color(path):
    """Цвет первого видеопотока: {'range', 'space', 'height', 'pq'} или None
    (файла нет). pq — maxLuminance для Qt у PQ-видео, иначе None. Ответ
    кэшируется по файлу (время изменения и размер)."""
    stamp = _stamp(path)
    if stamp is None:
        return None
    key = (os.path.normcase(os.path.abspath(str(path))), stamp)
    if key in _PROPS_CACHE:
        return _PROPS_CACHE[key]
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries",
             "stream=color_transfer,color_range,color_space,height", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=CREATE_NO_WINDOW, timeout=20)
        st = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
    except (OSError, ValueError, subprocess.SubprocessError):
        st = {}
    pq = None
    if st.get("color_transfer") == "smpte2084":
        import media_probe
        pq = media_probe.qt_pq_max_luminance(media_probe.probe_mastering_nits(path))
    found = {"range": "pc" if st.get("color_range") == "pc" else "tv",
             "space": st.get("color_space") or "", "height": int(st.get("height") or 0),
             "pq": pq}
    _PROPS_CACHE[key] = found
    return found


def pq_source(path):
    """(диапазон «tv»/«pc», maxLuminance для Qt) у PQ-видео, иначе None.

    HDR по цветовым тегам первого видеопотока: перенос smpte2084 — как и
    плеер Qt, который включает HDR-шейдер по нему же."""
    color = _video_color(path)
    if not color or color["pq"] is None:
        return None
    return color["range"], color["pq"]


def tonemap_filter(path, escape_path, pix_fmt="yuv420p"):
    """Цепочка фильтров «PQ-кадр → SDR как в просмотре» для файла path или
    "" (не PQ — кадр идёт как раньше). escape_path экранирует путь таблицы
    для libavfilter. На выходе кадр pix_fmt с тегами BT.709 и без HDR-
    метаданных: кодировщик иначе записал бы их из кадра в поток. pix_fmt
    rgb24/bgr24 — кадр sRGB для путей, которые правят кадры сами (см.
    rgb_decode_filter)."""
    props = pq_source(path)
    if props is None:
        return ""
    rng, max_lum = props
    lut = escape_path(qt_pq_lut(max_lum))
    if pix_fmt in _RGB_FORMATS:
        out = f"format={pix_fmt},setparams=range=pc:"
    else:
        out = f"scale=out_color_matrix=bt709:out_range=tv,format={pix_fmt},setparams=range=tv:"
    return (f"scale=in_color_matrix=bt2020:in_range={rng}:flags=accurate_rnd+full_chroma_int,"
            f"format=gbrp16le,lut3d=file={lut}:interp=tetrahedral,{out}"
            "color_primaries=bt709:color_trc=bt709:colorspace=bt709,"
            "sidedata=mode=delete:type=MASTERING_DISPLAY_METADATA,"
            "sidedata=mode=delete:type=CONTENT_LIGHT_LEVEL")


def tonemap_filters(paths, escape_path, pix_fmt="yuv420p"):
    """{montage_project.source_key(файл): цепочка} для PQ-файлов из paths —
    аргумент tonemap у montage_project.build_source."""
    import montage_project
    out = {}
    for p in sorted({str(p) for p in paths if p}):
        vf = tonemap_filter(p, escape_path, pix_fmt)
        if vf:
            out[montage_project.source_key(p)] = vf
    return out


def _sdr_matrix(path):
    """Матрица YUV ↔ RGB, по которой SDR-файл path покажут плееры, или None
    (PQ, BT.2020, HLG и прочее — такие кадры этот путь не трогает)."""
    color = _video_color(path)
    if not color or color["pq"] is not None:
        return None
    space = color["space"]
    if space in ("", "unknown", "unspecified"):
        return "bt709" if color["height"] > _SD_MAX_HEIGHT else "smpte170m"
    return _SDR_MATRICES.get(space)


def rgb_decode_filter(path, escape_path, pix_fmt="bgr24"):
    """Цепочка «кадр файла → pix_fmt (rgb24/bgr24)» для путей, которые правят
    кадры сами (привязка к объекту, удаление объекта), или "".

    HDR10 сводится в SDR, как в просмотре (tonemap_filter). SDR переводится
    в RGB явной матрицей — той же, которой rgb_encode_filter вернёт его в YUV.
    Раньше туда шло по тегу файла, а обратно ffmpeg сводил RGB по BT.601 без
    тегов: у BT.709-видео цвет уезжал."""
    if pq_source(path) is not None:
        return tonemap_filter(path, escape_path, pix_fmt)
    matrix = _sdr_matrix(path)
    if matrix is None:
        return ""
    rng = _video_color(path)["range"]
    return f"scale=in_color_matrix={matrix}:in_range={rng},format={pix_fmt}"


def rgb_encode_filter(path):
    """Цепочка «RGB-кадры → yuv420p с тегами» для кадров, полученных
    rgb_decode_filter из файла path, или "" (тот вернул "")."""
    matrix = "bt709" if pq_source(path) is not None else _sdr_matrix(path)
    if matrix is None:
        return ""
    return (f"scale=out_color_matrix={matrix}:out_range=tv,format=yuv420p,"
            f"setparams=range=tv:color_primaries={matrix}:color_trc={matrix}:"
            f"colorspace={matrix}")
