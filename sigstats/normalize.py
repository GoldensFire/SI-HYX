"""Нормализация названий тем и пакетов.

Главная задача — чтобы «Угадать игру😃» и «Угадать игру» считались одной темой.
Эмодзи стрипаются только для ключа сравнения; для отображения хранится оригинал.
"""
from __future__ import annotations
import re
import emoji

# Невидимые символы: селекторы вариаций (FE00–FE0F), ZWJ (200D), keycap (20E3),
# нулевой пробел/нонджойнер (200B–200C), BOM (FEFF).
_INVISIBLE = re.compile("[︀-️‍⃣​‌﻿]")
_WS = re.compile(r"\s+")
# Декор, который липнет к темам в начале/конце — стрипаем ТОЛЬКО в ключе сравнения.
# Скобки сюда НЕ входят: они часто часть названия, напр. «Перемотка (ОП)».
_TRIM_KEY = " \t\r\n-–—_.,:;!?\"'«»“”*#·•►▶▷●○◆■"

# Англо-русские синонимы (применяются к ключу темы пословно). Добавлять по мере
# нахождения: «cosplay» и «косплей» — одна тема.
_THEME_ALIASES = {
    "cosplay": "косплей",
    "anime": "аниме",
    "random": "рандом",
    "music": "музыка",
    "meme": "мем", "memes": "мем",
    "movie": "фильм", "movies": "фильм", "film": "фильм", "films": "фильм",
    "game": "игра", "games": "игра",
    "guess": "угадай",
    "opening": "опенинг", "openings": "опенинг",
}

# Лёгкий стеммер: убираем типовые окончания, чтобы «Фильм по кадру» и «Фильмы по
# кадру», «Рандом вопрос» и «Рандомные вопросы», «Косплей»/«cosplay» сходились в
# один ключ. Суффиксы — от длинных к коротким; стрижём только если остаток ≥ 4
# букв (чтобы не калечить короткие слова и не склеивать разные темы).
_SUFFIXES = (
    "ными", "ыми", "ого", "его", "ому", "ему", "ыми", "ими",
    "ные", "ный", "ная", "ное", "ный", "ний", "няя", "нее",
    "ах", "ях", "ам", "ям", "ов", "ев", "ами", "ями", "ии", "ие", "ия",
    "ы", "и", "а", "я", "о", "е", "у", "ю", "й",
)
_MIN_STEM = 4


def _stem_word(w: str) -> str:
    for suf in _SUFFIXES:
        if len(w) - len(suf) >= _MIN_STEM and w.endswith(suf):
            return w[: -len(suf)]
    return w


def strip_emoji(text: str) -> str:
    """Убирает эмодзи и невидимые управляющие символы."""
    if not text:
        return ""
    t = emoji.replace_emoji(text, replace="")
    t = _INVISIBLE.sub("", t)
    return t


def display_theme(name: str) -> str:
    """Оригинальное имя темы (с эмодзи и скобками) — только пробелы приводим."""
    if not name:
        return ""
    return _WS.sub(" ", name).strip()


def normalize_theme(name: str) -> str:
    """Ключ группировки тем: без эмодзи, lower, ё→е, без декора, с алиасами и
    лёгким стеммингом.

    Цель — чтобы в одну тему сходились: «🎶Музыка»/«Музыка» (эмодзи),
    «Фильм по кадру»/«Фильмы по кадру» (число), «Рандом вопрос»/«Рандомные
    вопросы» (форма слова), «cosplay 18+»/«косплей 18+» (язык).
    """
    if not name:
        return ""
    t = strip_emoji(name)
    t = t.replace("ё", "е").replace("Ё", "Е")
    t = _WS.sub(" ", t).strip(_TRIM_KEY).strip().lower()
    if not t:
        return ""
    tokens = []
    for raw in t.split(" "):
        w = raw.strip(_TRIM_KEY)
        if not w:
            continue
        w = _THEME_ALIASES.get(w, w)   # англо-русский синоним
        w = _stem_word(w)              # лёгкий стемминг формы слова
        tokens.append(w)
    return " ".join(tokens)


def normalize_name(name: str) -> str:
    """Ключ дедупликации пакета по названию: без эмодзи, lower, ё→е."""
    if not name:
        return ""
    t = strip_emoji(name)
    t = t.replace("ё", "е").replace("Ё", "Е")
    t = _WS.sub(" ", t).strip(_TRIM_KEY).strip()
    return t.lower()


def pick_display_variant(variants: list[str]) -> str:
    """Из нескольких написаний одной темы выбирает вариант для показа:
    предпочитает написание с эмодзи, затем самое длинное."""
    if not variants:
        return ""
    with_emoji = [v for v in variants if strip_emoji(v) != v]
    pool = with_emoji or variants
    return max(pool, key=lambda v: (len(v), v))
