# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Сцена длинной страницы (вебтун, манхва) без Gemini — по головам персонажей.

Замена manga_character_crop / manga_scene_batch в режиме «только OCR»
(visual_mode): детектор голов (local_character_detect) находит персонажей на
полосе, лучшие головы — крупные и уверенные — становятся затравкой, а
frame_at, общий с выбором через Gemini, расширяет её до цельной панели с
репликами и отбраковывает пустые, узкие и разорванные вырезки. Готовая
вырезка ещё раз проверяется на голову: панель могла отрезать персонажа."""
from __future__ import annotations

import io

from PIL import Image

from .local_character_detect import heads, visible
from .manga_character_crop import _windows, frame_at
from .manga_crop import _encode

# Сколько голов одной страницы пробовать затравкой.
SEEDS = 8
# Окон детектора на весь пул страниц (≈0.2 с на окно на CPU).
MAX_TILES = 24
# Голова уже этой доли ширины полосы — фигурка вдали или чиби, вопросу не
# годится (в пробном прогоне 0.08 пропустил панель из одних чиби-голов).
MIN_HEAD_WIDTH = 0.11


def _seeds(boxes, width):
    """Головы по пригодности: крупная и уверенная — первой."""
    usable = [box for box in boxes if box[2] - box[0] >= width * MIN_HEAD_WIDTH]
    return sorted(usable, key=lambda box: -box[4] * min(1.0, (box[2] - box[0]) / (width * .25)))


def _page_scene(generator, picture, limit, failures):
    from .manga_scene_prefilter import windows as drawing_windows
    width, height = picture.size
    regions = drawing_windows(picture, limit) or _windows(width, height, max_tiles=limit)
    area = width * min(height, round(width * 2.4))
    taken = []
    for x0, y0, x1, y1, _score in _seeds(heads(generator, picture, regions), width)[:SEEDS]:
        if generator.stopped():
            return None
        if any(top <= (y0 + y1) / 2 <= bottom for top, bottom in taken):
            continue        # эта голова уже в отвергнутой или взятой панели
        h = y1 - y0
        seed = (0, max(0, y0 - h // 2), width, min(height, y1 + h))
        context = []
        frame = frame_at(picture, seed, area, failures, context)
        if frame is None:
            taken.append((y0, y1))
            continue
        if not [box for box in visible(heads(generator, frame), frame.size)
                if box[2] - box[0] >= frame.width * MIN_HEAD_WIDTH]:
            failures.append("в вырезанной панели персонаж не виден целиком")
            taken.append((y0, y1))
            continue
        return frame
    if not failures:
        failures.append("персонажей крупным планом на странице нет")
    return None


def crop_pages(generator, cand, pages):
    """(индекс страницы, байты вырезки) из пула страниц — как manga_scene_batch."""
    if not pages or generator.stopped():
        return None
    from .manga_budget import check
    limit = max(1, MAX_TILES // len(pages))
    failures = []
    for index, page in enumerate(pages):
        check(generator, cand)
        with Image.open(io.BytesIO(page["data"])) as opened:
            picture = opened.convert("RGB")
        frame = _page_scene(generator, picture, limit, failures)
        del picture
        if frame is not None:
            generator._log_rare("Сцена манги", f"«{cand.title_ru}»: сцена выбрана "
                                f"локально по персонажам ({index + 1}-я из {len(pages)} страниц)")
            return index, _encode(frame, page["ext"])
    generator._log_rare("Сцена манги", f"«{cand.title_ru}»: пачка из {len(pages)} "
                        f"страниц отклонена: {failures[0]}")
    return None


def crop(generator, cand, data: bytes, ext: str):
    """Байты вырезки одной длинной страницы (None — сцены нет)."""
    picked = crop_pages(generator, cand, [{"data": data, "ext": ext}])
    return None if picked is None else picked[1]
