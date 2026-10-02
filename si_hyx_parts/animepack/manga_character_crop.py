# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Find a readable character scene on the original page using Gemini."""
from __future__ import annotations

import base64
import hashlib
import io
import math

from PIL import Image, ImageStat

from .manga_crop import PAGE_MAX_RATIO, _encode, is_vertical_strip
from .manga_visual_check import titles
from .visual_batch import request
from .manga_margins import trim, has_large_gap
from .manga_page_context import is_webtoon
from .manga_scene_review import check as review_scene
from .manga_scene_bounds import expand

MEMO_GROUP = "manga_character_crop_v5"
MAX_TILES = 32
SEND_SIDE = 1200
SCHEMA = {
    "type": "object",
    "properties": {
        "accept": {"type": "boolean"},
        "has_title_text": {"type": "boolean"},
        "has_characters": {"type": "boolean"},
        "tile_index": {"type": "integer"},
        "box": {"type": "array", "items": {"type": "integer"},
                "minItems": 4, "maxItems": 4},
        "reason": {"type": "string"},
    },
    "required": ["accept", "has_title_text", "has_characters", "tile_index",
                 "box", "reason"],
}


def crop(generator, cand, data: bytes, ext: str, *, manga_titles=()):
    """Inspect webtoons of any chunk size; keep ordinary book pages intact."""
    with Image.open(io.BytesIO(data)) as opened:
        if not is_vertical_strip(*opened.size) and not is_webtoon(cand):
            return data, ext
        picture = opened.convert("RGB")
    client = getattr(generator, "gemini_manga", None)
    if client is None:
        raise RuntimeError("Gemini для выбора сцены с персонажами недоступна")
    windows = _windows(*picture.size)
    prompt = _prompt(cand, manga_titles)
    model = str(getattr(client, "model", "") or "default")
    key = (f"{model}:{hashlib.sha256(data).hexdigest()}:"
           f"{hashlib.sha256(prompt.encode()).hexdigest()}")
    verdict = generator.db_cache.memo(MEMO_GROUP, key)
    if verdict is None:
        if generator.stopped():
            return None
        parts = [{"type": "text", "text": prompt}]
        for index, window in enumerate(windows):
            tile = picture.crop(window)
            tile.thumbnail((SEND_SIDE, SEND_SIDE), Image.Resampling.LANCZOS)
            payload = io.BytesIO()
            tile.save(payload, "JPEG", quality=88)
            parts.extend([
                {"type": "text", "text": f"Фрагмент tile_index={index}"},
                {"type": "image", "mime_type": "image/jpeg",
                 "data": base64.b64encode(payload.getvalue()).decode("ascii")},
            ])
        verdict = request(generator, client, parts, SCHEMA)
        if not isinstance(verdict, dict):
            return None
        generator.db_cache.remember_memo(MEMO_GROUP, key, verdict)
    failures = []
    contexts = []
    frame = _frame(picture, windows, verdict, failures, contexts)
    if frame is None:
        reason = failures[0]
        generator._log_rare("Сцена манги",
                            f"«{cand.title_ru}»: {reason} — беру другую страницу")
        return None
    good, reason = review_scene(generator, frame,
                               " / ".join(titles(cand.anime or {}) + list(manga_titles)),
                               source_context=contexts[0])
    if not good:
        generator._log_rare("Сцена манги",
                            f"«{cand.title_ru}»: проверка вырезки: {reason} — беру другую страницу")
        return None
    return _encode(frame, ext)


def _prompt(cand, manga_titles=()):
    return (
        "Выбери ОДНУ сцену для викторины по манге, манхве или маньхуа. "
        "Перед тобой последовательные фрагменты ОДНОЙ исходной страницы. "
        "Просмотри все фрагменты и найди наиболее выразительный кадр с хорошо "
        "видимым лицом или фигурой персонажа. Сохрани лица ВСЕХ заметных "
        "персонажей целиком и достаточно "
        "контекста рисунка. Лицо/голова должны быть видны ЦЕЛИКОМ; один рот, "
        "подбородок, макушка, руки или обрубок соседней панели не годятся. "
        "Крупный портрет в исходной панели допустим, даже если часть волос "
        "выходит за её край, когда глаза, нос и рот хорошо читаются. "
        "Не выбирай пустые белые/чёрные полосы, промежутки "
        "между кадрами, одни реплики, пейзаж без персонажей, логотипы или "
        "титры переводчиков. Изображение должно быть читаемо на экране. "
        "Высота выбранной области не должна превышать её ширину более чем "
        "в 1.6 раза. box должен охватывать ОДНУ цельную панель по ВСЕЙ "
        "ширине исходного рисунка и ВСЕ её реплики. Реплики, облачка и "
        "текстовые плашки нельзя обрезать или удалять, даже когда они "
        "выходят за рамку панели на белое поле. Не приближай лицо за счёт "
        "обрезки боков. Если панель вместе с репликами не помещается, "
        "выбери другую сцену. Обрезай только ПОЛНОСТЬЮ пустые поля; "
        "не объединяй рисунки через "
        "большой пустой промежуток. Маленькие поля допустимы. Фрагменты "
        "перекрываются: если персонажа режет край, найди его целиком на "
        "соседнем фрагменте. Ожидаемое произведение: "
        + " / ".join(titles(cand.anime or {}) + list(manga_titles)) + ". "
        "Верни tile_index выбранного фрагмента и box=[y_min,x_min,y_max,x_max] "
        "в целых координатах 0..1000 относительно ЭТОГО фрагмента. "
        "has_characters=true только если персонажи действительно видны "
        "ВНУТРИ box. has_title_text относится только к выбранной области: "
        "название произведения там недопустимо. Если подходящей сцены нет, "
        "accept=false, has_characters=false, box=[0,0,0,0]. Имена персонажей "
        "и обычные реплики допустимы. Причину напиши кратко по-русски.")


def _windows(width: int, height: int, *, max_tiles=MAX_TILES) -> list[tuple]:
    """Cover the entire strip, keeping faces large enough in individual tiles."""
    overlap = max(1, math.ceil(width * PAGE_MAX_RATIO))
    keep = min(height, max(1, round(width * 2.4),
                          math.ceil((height + (max_tiles - 1) * overlap) / max_tiles)))
    if keep == height:
        return [(0, 0, width, height)]
    # Any scene up to PAGE_MAX_RATIO fits fully in at least one tile, even
    # when its face straddles a boundary. Merely 20% overlap was insufficient.
    count = min(max_tiles, math.ceil((height - keep) / max(1, keep - overlap)) + 1)
    tops = [round(i * (height - keep) / (count - 1)) for i in range(count)]
    return [(0, top, width, min(height, top + keep)) for top in tops]


def _rejected(failures, reason):
    if failures is not None:
        failures.append(reason)
    return None


def _frame(picture, windows, verdict, failures=None, contexts=None):
    if (not isinstance(verdict, dict) or verdict.get("accept") is not True
            or verdict.get("has_characters") is not True
            or verdict.get("has_title_text") is not False):
        reason = verdict.get("reason") if isinstance(verdict, dict) else ""
        return _rejected(failures, str(reason or "нет сцены с персонажем без названия"))
    index, box = verdict.get("tile_index"), verdict.get("box")
    if (type(index) is not int or not 0 <= index < len(windows)
            or not isinstance(box, list) or len(box) != 4
            or any(type(v) is not int or not 0 <= v <= 1000 for v in box)):
        return _rejected(failures, "Gemini вернула некорректные координаты области")
    y0, x0, y1, x1 = box
    if y1 <= y0 or x1 <= x0:
        return _rejected(failures, "область имеет нулевую или отрицательную площадь")
    left, top, right, bottom = windows[index]
    width, height = right - left, bottom - top
    bounds = (left + round(width * x0 / 1000), top + round(height * y0 / 1000),
              left + round(width * x1 / 1000), top + round(height * y1 / 1000))
    if bounds[2] - bounds[0] < 64 or bounds[3] - bounds[1] < 64:
        return _rejected(failures, "выбран слишком маленький фрагмент")
    bounds = expand(picture, bounds, PAGE_MAX_RATIO)
    if bounds is None:
        return _rejected(failures, "нет безопасных границ цельной панели с репликами")
    frame = trim(picture.crop(bounds), max_ratio=PAGE_MAX_RATIO)
    fw, fh = frame.size
    if min(fw, fh) < 64 or fw * fh < width * height * 0.02:
        return _rejected(failures, "после обрезки полей рисунок слишком мал")
    if fh > fw * PAGE_MAX_RATIO:
        return _rejected(failures, "выбрана узкая полоса вместо цельной панели")
    if not _has_drawing(frame):
        return _rejected(failures, "выбранная область почти целиком пустая")
    if has_large_gap(frame):
        return _rejected(failures, "панели разделены большим пустым промежутком")
    if contexts is not None:
        pad = round(picture.width * .3)
        contexts.append(picture.crop((0, max(0, bounds[1] - pad), picture.width,
                                      min(picture.height, bounds[3] + pad))))
    return frame


def _has_drawing(frame) -> bool:
    preview = frame.convert("L")
    preview.thumbnail((256, 256))
    if ImageStat.Stat(preview).stddev[0] < 8:
        return False
    histogram = preview.histogram()
    total = preview.width * preview.height
    return (sum(histogram[245:]) < total * 0.97
            and sum(histogram[:10]) < total * 0.97)
