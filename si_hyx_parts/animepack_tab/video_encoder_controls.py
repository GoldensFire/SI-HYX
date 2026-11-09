# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Выбор кодировщика всего видео пака: AV1 видеокарты или SVT-AV1."""
import animepack_tab as _api
import gpu_video_encoder


def build_controls(tab):
    tab.cb_video_encoder = _api.QComboBox()
    for mode in gpu_video_encoder.MODES:
        tab.cb_video_encoder.addItem(gpu_video_encoder.MODE_LABELS[mode], mode)
    try:
        hint = gpu_video_encoder.adapters_hint()
    except Exception:  # noqa: BLE001 — подсказка не должна ронять вкладку
        hint = ""
    tab.cb_video_encoder.setToolTip(
        "Чем кодировать всё видео пака: ролики опенингов, сакугу, отрывки "
        "серий, караоке, кадры с эффектами и ролики появления. Кодек всегда "
        "AV1 — другого в паке не бывает.\n"
        "«Авто» — если видеокарта нативно кодирует AV1 (RTX 40xx и новее, "
        "Radeon RX 7000, Intel Arc), кодирует она; если нет — процессор "
        "(SVT-AV1). Поддержка проверяется пробным кадром при запуске.\n"
        "Качество на видеокарте — эквивалент того же CRF, что стоит у роликов.\n"
        "Картинки (AVIF) всегда считает процессор.\n" + hint)
