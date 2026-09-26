# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_hw_decode_device_types. Public namespace: config."""
import config as _api


# ── Аппаратное декодирование видео (H.264 / HEVC) в QtMultimedia ─────────────
# По умолчанию ВКЛЮЧЕНО: H.264/HEVC декодируются на GPU (D3D11VA/DXVA2) — тяжёлые
# файлы в «Монтаже» играют плавно (как в Filmora), а не упираются в ЦП.
# AV1 в «Монтаже» ВСЕГДА перегоняется в H.264-прокси ДО плеера, поэтому ускорение
# его не ломает. ОДНАКО на iGPU без аппаратного AV1-декодера (напр. Vega у
# Ryzen 5600H) ПРЯМОЕ воспроизведение AV1 (вкладка SiQuesterHYX) при включённом
# ускорении может дать чёрный экран — тогда снимите галку «Аппаратное ускорение
# видео» в Настройках. Программный рендер видео несовместим с HW-декодером —
# при нём ускорение тоже выключается.
# Qt читает переменную один раз на процесс при первом декодировании, поэтому
# ставим её здесь — config.py импортируется раньше любого QtMultimedia-плеера
# (и вкладки «Монтаж», и вкладки SiQuesterHYX).
def _hw_decode_device_types():
    try:
        with open(_api.SETTINGS_FILE, encoding="utf-8") as _f:
            _s = _api.json.load(_f)
        if _s.get("video_software_render", False):
            return ""                       # программный рендер → только ЦП
        if not _s.get("video_hw_decode", True):
            return ""                       # пользователь выключил ускорение
    except Exception:
        pass
    return "d3d11va,dxva2"

_hw_decode_device_types.__module__ = _api.__name__
_api._hw_decode_device_types = _hw_decode_device_types
