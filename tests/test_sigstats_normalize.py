# -*- coding: utf-8 -*-
"""Тесты sigstats/normalize.py — нормализация тем и названий пакетов."""
import pytest

from sigstats import normalize as nz


class TestStripEmoji:
    def test_removes_emoji(self):
        assert nz.strip_emoji("Угадать игру😃") == "Угадать игру"

    def test_removes_invisible(self):
        assert nz.strip_emoji("тема​‍﻿") == "тема"

    def test_plain(self):
        assert nz.strip_emoji("просто текст") == "просто текст"

    def test_empty(self):
        assert nz.strip_emoji("") == ""
        assert nz.strip_emoji(None) == ""

    def test_keycap(self):
        assert "⃣" not in nz.strip_emoji("1️⃣ раунд")


class TestDisplayTheme:
    def test_keeps_emoji(self):
        assert nz.display_theme("🎶Музыка") == "🎶Музыка"

    def test_collapses_whitespace(self):
        assert nz.display_theme("  Тема   с   пробелами  ") == "Тема с пробелами"

    def test_empty(self):
        assert nz.display_theme("") == ""
        assert nz.display_theme(None) == ""


class TestNormalizeTheme:
    def test_emoji_variants_merge(self):
        assert nz.normalize_theme("🎶Музыка") == nz.normalize_theme("Музыка")

    def test_case_insensitive(self):
        assert nz.normalize_theme("МУЗЫКА") == nz.normalize_theme("музыка")

    def test_yo_replaced(self):
        assert nz.normalize_theme("Ёжики") == nz.normalize_theme("ежики")

    def test_decor_stripped(self):
        assert nz.normalize_theme("— Музыка —") == nz.normalize_theme("Музыка")
        assert nz.normalize_theme("«Музыка»") == nz.normalize_theme("Музыка")

    def test_parens_kept(self):
        # скобки — часть названия, не декор
        a = nz.normalize_theme("Перемотка (ОП)")
        b = nz.normalize_theme("Перемотка")
        assert a != b

    def test_plural_merge(self):
        assert nz.normalize_theme("Фильм по кадру") == \
            nz.normalize_theme("Фильмы по кадру")

    def test_word_form_merge(self):
        assert nz.normalize_theme("Рандом вопрос") == \
            nz.normalize_theme("Рандомные вопросы")

    def test_alias_english(self):
        assert nz.normalize_theme("cosplay 18+") == nz.normalize_theme("косплей 18+")

    def test_alias_opening(self):
        assert nz.normalize_theme("Openings") == nz.normalize_theme("опенинг")

    def test_short_words_not_stemmed(self):
        # короткие слова не калечатся (остаток должен быть ≥ 4 букв)
        assert nz.normalize_theme("игра") != ""

    def test_different_themes_stay_apart(self):
        assert nz.normalize_theme("Музыка") != nz.normalize_theme("Кино")

    def test_empty(self):
        assert nz.normalize_theme("") == ""
        assert nz.normalize_theme(None) == ""
        assert nz.normalize_theme("😃") == ""  # только эмодзи

    def test_only_decor(self):
        assert nz.normalize_theme("—–—") == ""


class TestStemWord:
    def test_suffix_stripped(self):
        assert nz._stem_word("фильмы") == "фильм"

    def test_min_stem_respected(self):
        # "игра" → остаток "игр" (3 < 4) — суффикс не режется
        assert nz._stem_word("игра") == "игра"

    def test_no_suffix(self):
        assert nz._stem_word("кадр") == "кадр"


class TestNormalizeName:
    def test_lower_and_emoji(self):
        assert nz.normalize_name("Мой Пак🔥") == "мой пак"

    def test_yo(self):
        assert nz.normalize_name("Всё обо всём") == "все обо всем"

    def test_whitespace_collapsed(self):
        assert nz.normalize_name("Пак  с   пробелами") == "пак с пробелами"

    def test_empty(self):
        assert nz.normalize_name("") == ""
        assert nz.normalize_name(None) == ""


class TestPickDisplayVariant:
    def test_prefers_emoji(self):
        assert nz.pick_display_variant(["Музыка", "🎶Музыка"]) == "🎶Музыка"

    def test_longest_without_emoji(self):
        assert nz.pick_display_variant(["Кино", "Кино и сериалы"]) == "Кино и сериалы"

    def test_single(self):
        assert nz.pick_display_variant(["Одна"]) == "Одна"

    def test_empty(self):
        assert nz.pick_display_variant([]) == ""

    def test_tie_broken_deterministically(self):
        a = nz.pick_display_variant(["абв", "где"])
        b = nz.pick_display_variant(["где", "абв"])
        assert a == b
