# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Ступени раскрытия кадра: устойчивые маски, эффекты и общие настройки."""
from __future__ import annotations

import importlib
import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageStat


EFFECT_LABELS = {
    "pixelize": "Пикселизация",
    "tiles": "Закрытые плитки",
    "window": "Растущее окно",
    "zoom": "Отдаление кадра",
    "dark": "Из темноты",
    "overexposed": "Из пересвета",
    "waves": "Волны",
    "stripes": "Сдвиг полос",
    "swirl": "Спираль",
    "thumbnail": "Миниатюра",
    "puzzle": "Пазл — вразнобой",
    "puzzle_center": "Пазл — от центра",
    "dvd": "DVD-заставка",
}
EFFECT_HINTS = {
    "pixelize": "Крупные пиксели уменьшаются до чёткого кадра.",
    "tiles": "Плитки исчезают группами. Открытые участки остаются видимыми.",
    "window": "Маленькое окно на чёрном фоне постепенно расширяется. Масштаб кадра не меняется.",
    "zoom": ("Кадр начинается с огромного увеличения и с каждой ступенью "
             "отдаляется, пока не станет виден целиком."),
    "dark": "Почти чёрный кадр: возвращаются яркость, цвета и детали.",
    "overexposed": "Почти белый кадр: из пересвета проступают тёмные, затем светлые детали.",
    "waves": "Кадр изогнут волнами; их размах уменьшается до нуля.",
    "stripes": "Горизонтальные полосы разъехались влево и вправо и съезжаются на место.",
    "swirl": "Кадр закручен вокруг центра; закрутка ослабевает до нуля.",
    "thumbnail": "Крошечная миниатюра посреди чёрного экрана растёт до полного кадра.",
    "puzzle": "Куски кадра перемешаны и встают на место в случайном порядке.",
    "puzzle_center": "Куски кадра перемешаны и встают на место от центра к краям.",
    "dvd": ("Чёрный экран, по нему летает прямоугольник, как логотип на "
            "заставке DVD, и расчищает кадр там, где пролетел; к концу "
            "времени улетает за край, необлетённое остаётся чёрным. Движется плавно, 30 или 60 кадров в секунду. Можно указать "
            "папку с картинками и видео — тогда прямоугольник показывает их "
            "по очереди."),
}
# Эффекты, которые считаются отдельными модулями на numpy. Модуль грузится
# только при первом раскрытии — запуск программы numpy не ждёт.
_EXTERNAL = {
    "dark": ("frame_reveal_tone", "DarknessReveal"),
    "overexposed": ("frame_reveal_tone", "OverexposureReveal"),
    "waves": ("frame_reveal_warp", "WaveReveal"),
    "stripes": ("frame_reveal_warp", "StripesReveal"),
    "swirl": ("frame_reveal_warp", "SwirlReveal"),
    "thumbnail": ("frame_reveal_layout", "ThumbnailReveal"),
    "puzzle": ("frame_reveal_layout", "PuzzleReveal"),
    "puzzle_center": ("frame_reveal_layout", "PuzzleReveal"),
    "dvd": ("frame_reveal_dvd", "DvdReveal"),
}
# Эффекты, которые кодируются покадровой анимацией (30/60 к/с), а не
# ступенями: число ступеней и «кадров/с» из настроек их не касаются.
ANIMATED_EFFECTS = ("dvd",)
# Эффекты, которых не было в настройках до появления списка
# frame_effects_known: сохранённый случайный набор получает их включёнными.
LEGACY_EFFECTS = ("pixelize", "tiles", "window", "zoom")
# Эффекты, которые убраны по просьбе пользователя (не понравились). Старые
# настройки с ними читаются: одиночный выбор уходит в пикселизацию, а из
# списка случайного выбора они просто выпадают.
REMOVED_EFFECTS = ("sketch", "blur", "palette", "noise", "stretch",
                   "holes", "spots", "blots")


def clean_effects(value) -> list[str]:
    """Читаем только известные эффекты, сохраняя порядок без дублей."""
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(k for k in value
                              if isinstance(k, str) and k in EFFECT_LABELS))


def add_new_effects(selected: list[str], known) -> list[str]:
    """Эффекты, которых ещё не было при сохранении, включаются в набор."""
    seen = set(clean_effects(known) or LEGACY_EFFECTS)
    fresh = [k for k in EFFECT_LABELS if k not in seen and k not in selected]
    return list(selected) + fresh


def choose_effect(mode: str, selected, rng: random.Random) -> str:
    if mode == "random":
        choices = clean_effects(selected)
        if not choices:
            raise ValueError("Отметьте хотя бы один эффект для случайного выбора.")
        return rng.choice(choices)
    if mode not in EFFECT_LABELS:
        raise ValueError("Выбран неизвестный эффект раскрытия кадра.")
    return mode


def stage_frame_counts(seconds: int, fps: int, steps: int) -> list[int]:
    """Целые кадры на ступень; последний чистый кадр всегда имеет своё окно."""
    total = max(2, int(seconds)) * max(1, min(60, int(fps)))
    steps = max(2, min(20, total, int(steps)))
    bounds = [i * total // steps for i in range(steps + 1)]
    return [b - a for a, b in zip(bounds, bounds[1:])]


def window_area(strength=55, progress=0.0) -> float:
    """Доля площади: 7,4% на старте по умолчанию, медленнее в первых шагах."""
    strength = max(10, min(100, int(strength))) / 100.0
    start = 0.14 - 0.12 * strength
    p = max(0.0, min(1.0, float(progress)))
    return start + (1 - start) * p ** 1.65


class RevealRenderer:
    """Рисует лишь ступени, а не каждый видеокадр; случайность фиксирована.

    Один экземпляр принадлежит одному вопросу. Вся геометрия и шум создаются
    один раз, поэтому следующий шаг не прячет уже открытые участки.
    """

    def __init__(self, image: Image.Image, effect: str, strength=55, seed=0):
        if effect not in EFFECT_LABELS or effect == "pixelize":
            raise ValueError(f"Неизвестный растровый эффект: {effect}")
        self.image = image.convert("RGB")
        self.effect = effect
        self.strength = max(10, min(100, int(strength))) / 100.0
        self.rng = random.Random(seed)
        self.mask = None
        self.anchor = (0.5, 0.5)
        self.external = None
        if effect == "tiles":
            self.mask = self._tile_ranks()
        elif effect in ("window", "zoom"):
            self.anchor = self._detail_anchor()
        if effect in _EXTERNAL:
            module, name = _EXTERNAL[effect]
            cls = getattr(importlib.import_module(module), name)
            extra = {"from_center": True} if effect == "puzzle_center" else {}
            self.external = cls(self.image, self.strength, self.rng, self.anchor, **extra)

    def _tile_ranks(self) -> Image.Image:
        w, h = self.image.size
        # 16×9 на обычном 16:9 — плитки мельче и их заметно
        # больше, чем в прежней сетке 10×6. Число строк считаем
        # из аспекта, чтобы ячейки оставались похожими на квадраты.
        cols = min(16, w)
        rows = min(h, max(1, round(cols * h / max(1, w))))
        cells = [(x, y) for y in range(rows) for x in range(cols)]
        self.rng.shuffle(cells)
        mask = Image.new("L", (w, h))
        draw = ImageDraw.Draw(mask)
        for rank, (x, y) in enumerate(cells):
            box = (x * w // cols, y * h // rows,
                   (x + 1) * w // cols - 1, (y + 1) * h // rows - 1)
            draw.rectangle(box, fill=round(255 * rank / max(1, len(cells) - 1)))
        return mask

    def _detail_anchor(self) -> tuple[float, float]:
        """Ищем детали среди центральных областей, не распознавая персонажей."""
        small = ImageOps.grayscale(self.image).resize((96, 64))
        edges = small.filter(ImageFilter.FIND_EDGES)
        candidates = [(x, y) for x in (0.5, 0.3, 0.7) for y in (0.5, 0.35, 0.65)]

        def score(point):
            x, y = point
            crop = edges.crop((int(x * 96) - 14, int(y * 64) - 10,
                               int(x * 96) + 14, int(y * 64) + 10))
            return ImageStat.Stat(crop).mean[0]

        return max(candidates, key=score)

    def render(self, progress: float) -> Image.Image:
        p = max(0.0, min(1.0, float(progress)))
        # У DVD-заставки полного кадра в конце нет: что прямоугольник не
        # облетел, остаётся чёрным (просьба пользователя).
        if p >= 1 and self.effect not in ANIMATED_EFFECTS:
            return self.image.copy()
        if self.external is not None:
            return self.external.render(p)
        w, h = self.image.size
        if self.effect == "tiles":
            # На старте закрыто около 80% кадра при силе 55.
            # Степень дольше держит плитки: на каждой ранней
            # ступени их снимается меньше, чистый кадр всё равно последний.
            start = max(0.05, 0.38 - 0.32 * self.strength)
            visible = start + (1 - start) * p ** 1.45
            threshold = round(255 * visible)
            mask = self.mask.point(lambda v: 255 if v <= threshold else 0)
            return Image.composite(self.image, Image.new("RGB", (w, h), "#080a0f"),
                                   mask)
        if self.effect == "window":
            fraction = math.sqrt(window_area(round(self.strength * 100), p))
            ww, hh = max(1, round(w * fraction)), max(1, round(h * fraction))
            x = max(0, min(w - ww, round(self.anchor[0] * w - ww / 2)))
            y = max(0, min(h - hh, round(self.anchor[1] * h - hh / 2)))
            mask = Image.new("L", (w, h))
            ImageDraw.Draw(mask).rectangle((x, y, x + ww - 1, y + hh - 1), fill=255)
            return Image.composite(self.image, Image.new("RGB", (w, h), "black"), mask)
        # Отдаление: видимый кусок растягивается на весь кадр, поэтому в
        # начале на экране огромная деталь, а к концу — сам кадр. Размер
        # куска считается той же лесенкой, что у «окна», но края здесь не
        # чёрные: картинка просто крупнее.
        fraction = math.sqrt(window_area(round(self.strength * 100), p))
        ww, hh = max(2, round(w * fraction)), max(2, round(h * fraction))
        x = max(0, min(w - ww, round(self.anchor[0] * w - ww / 2)))
        y = max(0, min(h - hh, round(self.anchor[1] * h - hh / 2)))
        crop = self.image.crop((x, y, x + ww, y + hh))
        return crop.resize((w, h), Image.Resampling.LANCZOS)
