# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# pixelize.py — эффект «проявление из пикселей»: размеры блоков по шагам и
# готовая цепочка ffmpeg-фильтров.
#
# Один эффект — одна реализация. Ей пользуются:
#   • вкладка «Монтаж» (edit_tab) — кнопка «Пикселизация» у видео и картинок;
#   • генератор аниме-паков (animepack) — вопрос-кадр, который проявляется.
# Ни Qt, ни запуска ffmpeg здесь нет — только арифметика и строка -vf, поэтому
# модуль импортируется откуда угодно и проверяется тестами в одиночку.
from __future__ import annotations

# Минимальный размер блока для ПРЕДпоследнего (последнего «блочного») шага.
# Раньше геометрия шла до 1px, и предпоследний шаг выходил ~2px — а 2px
# визуально почти неотличим от чёткого кадра, шаг получался «пустым». Держим
# пол здесь: последний блочный шаг всегда заметно пикселизирован, потом сразу
# «чётко».
MIN_BLOCK = 6


def block_sequence(block0, steps) -> list[int]:
    """Размеры блока (px) по шагам проявления: геометрически убывают от block0
    до пола (MIN_BLOCK), а самый последний шаг — «чётко» (1). Каждый следующий
    блок мельче → «пикселей становится больше», пока кадр не прояснится.
    При steps==1 — один статичный уровень (block0) без финального прояснения.
    Предпоследний шаг не опускается ниже пола, чтобы не было «пустого» 2px-шага
    у самой чёткости."""
    block0 = max(2, int(block0))
    steps = max(1, int(steps))
    if steps == 1:
        return [max(1, min(1024, block0))]
    floor = min(block0, MIN_BLOCK)         # пол не выше самого block0
    n_block = steps - 1                    # шаги до финального «чётко»
    seq = []
    for i in range(n_block):
        if n_block == 1:
            b = block0
        else:
            # i=0 → block0, i=n_block-1 → floor (геометрически между ними).
            t = i / (n_block - 1)
            b = block0 * (floor / block0) ** t
        seq.append(max(1, min(1024, int(round(b)))))
    seq.append(1)                          # финальный шаг — чётко
    return seq


def pixelize_filter(duration, steps, block, offset=0.0):
    """Цепочка ffmpeg-фильтров «проявление из пикселей» для клипа длительностью
    `duration` секунд, либо None, если пикселить нечего. Клип делится на N
    равных окон; в каждом окне `pixelize` с уменьшающимся блоком (через
    enable='between(t,…)'), пока картинка не станет чёткой.

    ВАЖНО про `offset`: фильтрграф видит ВРЕМЯ ИСХОДНИКА, а не время
    обрезанного клипа (setpts на таймлайн `enable` не влияет — проверено).
    Поэтому окна смещаются на `offset` — время фильтрграфа, на котором
    начинается клип:
      • выходной seek (-ss после -i): offset = начало реза;
      • входной seek (-ss до -i):     offset = 0;
      • входной pre-seek + выходной -ss: offset = величина выходного -ss.
    """
    try:
        dur = float(duration)
    except (TypeError, ValueError):
        return None
    if dur <= 0:
        return None
    steps = max(1, int(steps))
    block0 = max(2, int(block))
    seq = block_sequence(block0, steps)
    win = dur / steps
    off = max(0.0, float(offset or 0.0))
    parts = []
    for i, b in enumerate(seq):
        if b <= 1:
            continue          # блок 1 = без изменений (чётко) — фильтр не нужен
        t0 = off + i * win
        t1 = off + (i + 1) * win
        parts.append(f"pixelize=w={b}:h={b}:enable='between(t,{t0:.3f},{t1:.3f})'")
    if not parts:
        return None           # всё чётко — пикселить нечего
    return ",".join(parts)
