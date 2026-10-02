# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Эффекты появления: каталог, выбор и общие настройки без зависимости от Qt."""
from __future__ import annotations

EFFECTS = {
    "crash_zoom": ("Резкое приближение", "Crash Zoom In", "Картинка резко приближается с коротким перелётом масштаба."),
    "spin": ("Вращение", "Spin In", "Картинка появляется, совершая полный оборот."),
    "spiral": ("По спирали", "Spiral In", "Картинка закручивается по спирали к центру."),
    "bounce": ("С отскоком", "Bounce In", "Картинка падает сверху и несколько раз отскакивает."),
    "fly": ("Влёт", "Fly In", "Картинка влетает по диагонали с увеличением."),
    "whip": ("Хлёсткий влёт", "Whip In", "Быстрый боковой влёт с размытым следом."),
    "flash": ("Из вспышки", "Flash In", "Белая вспышка открывает картинку."),
    "shake": ("С тряской", "Shake In", "Картинка появляется с затухающей тряской."),
    "stretch": ("С растяжением", "Stretch In", "Растянутая картинка пружинит до обычных пропорций."),
    "expand": ("Разворачивание", "Expand In", "Узкая полоска разворачивается в полную картинку."),
    "pop": ("Выскок", "Pop In", "Картинка выскакивает из центра с коротким увеличением."),
    "flip": ("Переворот", "Flip In", "Картинка переворачивается вокруг вертикальной оси."),
    "rotate_zoom": ("Поворот и приближение", "Rotate + Zoom In", "Наклонённая картинка поворачивается и увеличивается."),
    "blur_sharp": ("Из размытия в резкость", "Blur → Sharp", "Размытая картинка плавно становится чёткой."),
    "radial_zoom": ("Радиальное приближение", "Radial Zoom In", "Приближение с лучистым следом от центра."),
    "split": ("Раскрытие половинами", "Split Screen Reveal", "Две половины картинки сходятся с разных сторон."),
    "clone": ("Появление копиями", "Clone Reveal", "Несколько копий сходятся в одну картинку."),
    "mosaic": ("Мозаичное появление", "Mosaic Reveal", "Плитки мозаики увеличиваются и собираются в картинку."),
    "star": ("Раскрытие звездой", "Star Wipe In", "Растущая звезда открывает картинку."),
    "ripple": ("Раскрытие рябью", "Ripple Reveal", "Картинка открывается круговой волной с рябью."),
    "explosion": ("Взрывное появление", "Explosion Reveal", "Разлетевшиеся фрагменты собираются в картинку."),
    "dramatic_slide": ("Драматичный сдвиг", "Dramatic Slide In", "Картинка въезжает снизу с наклоном и перелётом."),
    "multiple_zoom": ("Несколько приближений", "Multiple Zoom In", "Картинка появляется тремя последовательными приближениями."),
    "shake_zoom": ("Тряска и приближение", "Shake + Zoom In", "Приближение сопровождается затухающей тряской."),
    "flash_spin": ("Вспышка и вращение", "Flash + Spin In", "Картинка вращается и появляется из серии вспышек."),
}
EFFECT_LABELS = {key: value[0] for key, value in EFFECTS.items()}
EDITOR_ONLY_EFFECTS = {"crash_zoom", "fly", "whip", "blur_sharp", "dramatic_slide"}
PACK_EFFECTS = {key: value for key, value in EFFECTS.items() if key not in EDITOR_ONLY_EFFECTS}
PACK_EFFECT_LABELS = {key: value[0] for key, value in PACK_EFFECTS.items()}
TARGET_LABELS = {
    "frame": "Кадры", "manga": "Манга / манхва / ранобэ",
    "character": "Персонажи", "ai_art": "ИИ-арты", "pixiv_art": "Pixiv-арты",
    "studio": "Кадры студий", "sakuga": "Сакуга", "video": "Ролики песен",
    "pixel": "Кадры с эффектами",
}


def clean_keys(value, labels):
    if not isinstance(value, (list, tuple)):
        return []
    return list(dict.fromkeys(k for k in value if isinstance(k, str) and k in labels))


def choose_effect(settings, rng):
    mode = settings.entrance_effect
    if mode == "random":
        choices = clean_keys(settings.entrance_effects, PACK_EFFECT_LABELS)
        if not choices:
            raise ValueError("Отметьте хотя бы один эффект появления.")
        return rng.choice(choices)
    if mode not in PACK_EFFECT_LABELS:
        raise ValueError("Выбран неизвестный эффект появления.")
    return mode


def validate(settings):
    if not settings.entrance_enabled:
        return []
    problems = []
    if not clean_keys(settings.entrance_targets, TARGET_LABELS):
        problems.append("Выберите составы пака для эффектов появления.")
    if settings.entrance_effect not in (*PACK_EFFECT_LABELS, "random"):
        problems.append("Выбран неизвестный эффект появления.")
    if settings.entrance_effect == "random" and not clean_keys(settings.entrance_effects, PACK_EFFECT_LABELS):
        problems.append("Отметьте хотя бы один эффект появления для случайного выбора.")
    if not 0.2 <= settings.entrance_seconds <= 5:
        problems.append("Длительность появления должна быть от 0,2 до 5 секунд.")
    if not 10 <= settings.entrance_fps <= 60:
        problems.append("Частота кадров появления должна быть от 10 до 60.")
    if not 10 <= settings.entrance_strength <= 100:
        problems.append("Сила появления должна быть от 10 до 100%.")
    if not 0 <= settings.entrance_preset <= 13:
        problems.append("Пресет кодирования появления должен быть от 0 до 13.")
    return problems


def fitted_size(width, height, max_height=720):
    ratio = min(1.0, max_height / height, 1920 / width)
    return tuple(max(2, round(side * ratio / 2) * 2) for side in (width, height))
