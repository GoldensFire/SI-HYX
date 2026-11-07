# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Труба кадров для эффекта проявления: декодер → эффект → кодировщик.

Эффекты проявления, которые считаются по кадрам (frame_reveal_video), идут
ОДНИМ кодированием: ffmpeg-декодер отдаёт кадры в stdout, Python кладёт на
каждый эффект и пишет его в stdin ffmpeg-кодировщика. Промежуточного файла
нет. Пользуются этим экспорт Монтажа (RevealVideoWorker) и «Обработка»
(si_hyx_parts/workers/process_reveal.py).

Кадры в трубах — PPM: размер кадра виден из заголовка, его не нужно знать
заранее (кадрирование Монтажа задано выражением от размера исходника).
"""
from __future__ import annotations

import subprocess

import hdr_tonemap

PPM_ARGS = ["-f", "image2pipe", "-c:v", "ppm"]
# RGB → YUV для кодировщика с тегами BT.709 (COLOR_ARGS). Начинается не со
# «scale=»: _metric_vf «Обработки» оставляет такие фильтры пробам подбора CRF.
ENCODE_VF = ("setsar=1,scale=trunc(iw/2)*2:trunc(ih/2)*2:out_color_matrix=bt709:"
             "out_range=tv,format=yuv420p,setparams=range=tv:color_primaries=bt709:"
             "color_trc=bt709:colorspace=bt709")
COLOR_ARGS = list(hdr_tonemap.SDR_COLOR_ARGS)


def rgb_filter(path, escape_path, tonemapped=False) -> str:
    """Последний фильтр декодера: кадр файла path → rgb24 той матрицей, по
    которой его показывают плееры. tonemapped — HDR уже сведён в SDR BT.709
    раньше в цепочке (Монтаж делает это в _wrap_vf)."""
    if tonemapped and hdr_tonemap.pq_source(path) is not None:
        return "scale=in_color_matrix=bt709:in_range=tv,format=rgb24"
    return hdr_tonemap.rgb_decode_filter(path, escape_path, "rgb24") or "format=rgb24"


def probe_rate(ffprobe, path, creationflags=0) -> tuple[str, float]:
    """Частота кадров файла: строка для -framerate и число (25, если не вышло)."""
    try:
        r = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "V:0",
             "-show_entries", "stream=r_frame_rate,avg_frame_rate",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            creationflags=creationflags, timeout=30)
        rates = (r.stdout or "").split()
    except Exception:
        rates = []
    for rate in rates:
        num, _, den = rate.partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            continue
        if fps > 0:
            return rate, fps
    return "25", 25.0


def pump(src, dst, reveal, stopped=lambda: False) -> int:
    """Кадры PPM из src → reveal.apply → PPM в dst; число кадров. dst
    закрывается в конце — кодировщик видит конец видео. reveal=None — кадры
    идут как есть (картинка в «Обработку» без покадрового эффекта)."""
    import numpy as np
    idx = 0
    try:
        while not stopped():
            head = [src.readline() for _ in range(3)]
            if not head[0]:
                break
            w, h = (int(v) for v in head[1].split())
            size = w * h * 3
            data = src.read(size)
            if len(data) < size:
                break
            frame = np.frombuffer(data, np.uint8).reshape(h, w, 3)
            out = frame if reveal is None else np.ascontiguousarray(reveal.apply(idx, frame))
            dst.write(b"P6\n%d %d\n255\n" % (w, h))
            dst.write(out.tobytes())
            idx += 1
    finally:
        try:
            dst.close()
        except Exception:
            pass
    return idx
