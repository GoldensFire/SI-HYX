# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Как кавер называется в самом вопросе. Namespace: animepack.

Подсказка на экране раньше говорила одно на все каверы — «Опенинг · Кавер», — и
игрок не понимал, чего ждать: то ли сейчас кто-то споёт по-английски, то ли
зазвучит фортепиано без единого слова. Теперь вид исполнения называется прямо:
«Опенинг (кавер на английском)», «Опенинг (кавер на фортепиано)» (просьба
пользователя).

Вид и язык берутся из ЗАГОЛОВКА ролика — того самого, по которому кандидат
проходил гейт (cover_meta_rules). Ничего не скачивается и не считается заново:
и вид, и заголовок уже лежат в записи прозвучавшего кавера (cover_record).

cover_meta_rules тянет за собой только re и unicodedata — в отличие от
cover_match, которому нужен numpy, поэтому импорт здесь обычный, наверху.
"""
from __future__ import annotations

import animepack as _api
from cover_meta_rules import cover_language

# Как называется исполнение каждого вида. Ключи — TYPES из cover_meta_rules.
# «Вокальный» и «на другом языке» сюда не входят: у них подпись собирается из
# языка, на котором спето (см. cover_phrase).
COVER_PHRASES = {
    "piano": "кавер на фортепиано",
    "guitar": "кавер на гитаре",
    # Просто «кавер» (просьба пользователя): «кавер группы» игроку ничего не
    # говорило — по нему не понять, чего ждать, а сам вид исполнения остался
    # в настройках отдельной галочкой «Группа».
    "band": "кавер",
    "metal": "метал-кавер",
    "orchestra": "оркестровый кавер",
    "chiptune": "8-битный кавер",
}
# Когда язык важнее инструмента. У фортепианного кавера слов нет вовсе, и
# «кавер на английском» там было бы прямой ложью, а вот у спетого — наоборот:
# язык это первое, что слышно.
VOCAL_TYPES = ("vocal", "other_lang")


def cover_phrase(record) -> str:
    """«кавер на английском», «кавер на гитаре», «кавер» — что написать в скобках.

    `record` — запись прозвучавшего исполнения (candidate.music_processing):
    вид, заголовок ролика и канал. Пустой записи хватает на простое «кавер»."""
    record = record or {}
    kind = str(record.get("type") or "")
    if kind and kind not in VOCAL_TYPES:
        return COVER_PHRASES.get(kind, "кавер")
    language = cover_language(record.get("title") or "",
                              record.get("channel") or "")
    if language:
        return f"кавер на {language}"
    return "кавер на другом языке" if kind == "other_lang" else "кавер"


def cover_hint(base: str, record) -> str:
    """Подсказка вопроса целиком: «Опенинг (кавер на английском)»."""
    return f"{base} ({cover_phrase(record)})"


def cover_credit(record) -> str:
    """Устный текст ведущего: откуда взято исполнение («» — канал неизвестен).

    Читается ОДНОВРЕМЕННО с отрезком (просьба пользователя): игрок слышит
    чужое исполнение и сразу знает, чьё оно, — иначе кавер выглядит как
    неудачная запись оригинала."""
    channel = str((record or {}).get("channel") or "").strip()
    return f"Взято с канала {channel}" if channel else ""


for _name in ("cover_phrase", "cover_hint", "cover_credit"):
    globals()[_name].__module__ = _api.__name__
    setattr(_api, _name, globals()[_name])
