# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Обрезка длинных страниц манхвы. Namespace: animepack.

У японской манги страница — разворот книги: высота примерно в полтора раза
больше ширины. У манхвы и маньхуа «страница» на MangaDex — это кусок
вертикальной ленты вебтуна: 800 пикселей в ширину и десять-двадцать тысяч в
высоту. В вопросе такая полоса нечитаема: SIGame вписывает её в экран целиком,
и картинка превращается в ниточку (просьба пользователя — сделать страницу
манхвы «не сильно выше манги»).

Режем только длинную вертикальную ленту, а книжные страницы сохраняем целиком,
даже если их пропорции выше PAGE_MAX_RATIO. Полоса режется до книжных
пропорций: берём случайное окно
высотой не больше ширины, умноженной на PAGE_MAX_RATIO. Окно случайное, а не с
начала: у ленты вверху обычно шапка переводчиков, а в середине — сама сцена.
"""
from __future__ import annotations
import animepack as _api

# Во сколько раз высота страницы может превышать ширину. 1,6 — чуть больше
# книжного разворота (у манги это примерно 1,4–1,5), так что обрезанная лента
# смотрится как обычная страница, а не как ниточка.
PAGE_MAX_RATIO = 1.6
# Книжная страница, включая вытянутую ёнкому, не считается лентой вебтуна.
# Порог определения ленты отличается от пропорций уже вырезанного окна.
STRIP_MIN_RATIO = 3.0
# Ленту режем не с самого края: вверху шапка с названием и переводчиками, внизу
# — «продолжение следует» и реклама. Отступ — доля всей высоты.
EDGE_SKIP = 0.08
# Ниже этой высоты обрезать нечего: короткая полоса и так читается.
MIN_KEEP = 200


def is_vertical_strip(width: int, height: int) -> bool:
    """Длинная вертикальная лента; тип издания сам по себе этого не определяет."""
    return width > 0 and height > width * STRIP_MIN_RATIO


def is_long_page(data: bytes) -> bool:
    """Определяет ленту по размерам исходной картинки, не меняя её байты."""
    try:
        from config import Image
        with Image.open(_api.io.BytesIO(data)) as im:
            return is_vertical_strip(*im.size)
    except Exception:  # noqa: BLE001 — повреждённое изображение не режем
        return False


def fit_page(data: bytes, ext: str = ".jpg", max_ratio: float = PAGE_MAX_RATIO,
             rng=None) -> _api.Optional[tuple]:
    """(байты, расширение) обрезанной страницы либо None — резать не нужно.

    None возвращается и когда Pillow недоступен или картинка не разобралась:
    вопрос тогда состоится с исходной лентой, как раньше."""
    try:
        from config import Image
    except Exception:  # noqa: BLE001 — без Pillow просто идём как раньше
        return None
    try:
        with Image.open(_api.io.BytesIO(data)) as im:
            width, height = im.size
            if not is_vertical_strip(width, height):
                return None
            keep = int(round(width * float(max_ratio)))
            if keep < MIN_KEEP or height <= keep:
                return None
            # Сколько ленты можно пропустить сверху, не выходя за край.
            edge = min(int(height * EDGE_SKIP), (height - keep) // 2)
            top = edge
            last = height - keep - edge
            if last > top:
                top = (rng.randint(top, last) if rng is not None
                       else (top + last) // 2)
            frame = im.crop((0, top, width, top + keep))
            return _encode(frame, ext)
    except Exception:  # noqa: BLE001 — битую картинку отдаём как есть
        return None


def _encode(frame, ext: str) -> _api.Optional[tuple]:
    """Кладёт вырезанное окно обратно в байты тем же форматом, что пришло.

    Формат сохраняем, потому что без галочки «Сжимать картинки» эти байты
    ложатся в пак как есть: перегонять фотографическую страницу в PNG значило бы
    раздуть пак втрое."""
    buf = _api.io.BytesIO()
    if str(ext).lower() in (".jpg", ".jpeg") and frame.mode not in ("RGBA", "LA", "P"):
        frame.save(buf, format="JPEG", quality=92, subsampling=0)
        return buf.getvalue(), ".jpg"
    frame.save(buf, format="PNG")
    return buf.getvalue(), ".png"


fit_page.__module__ = _api.__name__
_api.fit_manga_page = fit_page
