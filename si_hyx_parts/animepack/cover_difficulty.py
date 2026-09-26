# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Сложность музыкального вопроса: песня и кавер вместе. Namespace: animepack.

У песенного вопроса надбавка к цене была одна — за сложность самой песни в AMQ
(songDifficulty, см. song_difficulty_bonus). У кавера появляется вторая:
насколько исполнение ушло от оригинала (closeness из cover_match — величина
замеренная, у вокальных каверов медиана 0.53, у фортепианных 0.34).

Складываются они НЕ сложением очков. Две надбавки по десять очков дали бы
двадцать сверху на лесенке, где весь разброс цен 6…20, — то есть кавер
известной песни стоил бы дороже любого вопроса про безвестный тайтл. Здесь обе
величины сперва приводятся к «доле тех, кто не угадает», и объединяются как
независимые препятствия:

    вместе = песня + кавер − песня × кавер

Трудная песня в трудном исполнении становится труднее и той, и другого, но
надбавка остаётся в прежних десяти очках. У вопроса без кавера вторая доля
равна нулю, и число выходит В ТОЧНОСТИ прежнее — старые паки и тесты не
меняются.

Форма записи именно такая, а не равное ей `1 − (1 − песня) × (1 − кавер)`:
второе считает то же самое, но через разность единиц, и на сложности песни 95
давало 0.050000000000000044 вместо 0.05 — то есть лишнее очко к цене там, где
округление стоит ровно на половине. Поймано тестом
test_sort_by_index_orders_pack_and_prices.
"""
from __future__ import annotations
import animepack as _api


def song_hardness(difficulty) -> float:
    """0…1 — насколько трудна САМА песня (по songDifficulty из AnisongDB)."""
    try:
        value = float(difficulty)
    except (TypeError, ValueError):
        return 0.0
    if value <= 0 or value > 100:
        return 0.0                      # сложности не знаем — надбавки нет
    return (100.0 - value) / 100.0


def cover_hardness(cand) -> float:
    """0…1 — насколько далеко исполнение от оригинала (не кавер — ноль)."""
    if getattr(cand, "music_effect", "") != "cover":
        return 0.0
    processing = getattr(cand, "music_processing", None) or {}
    if not processing.get("similarity_checked", True):
        return 0.0
    close = processing.get("closeness")
    try:
        close = float(close)
    except (TypeError, ValueError):
        return 0.0
    return 1.0 - min(1.0, max(0.0, close))


def music_difficulty_bonus(cand) -> int:
    """0…SONG_DIFF_BONUS_MAX очков сверху за трудность угадать музыку."""
    song = song_hardness(getattr(cand, "difficulty", 0.0))
    cover = cover_hardness(cand)
    together = song + cover - song * cover
    return int(round(together * _api.SONG_DIFF_BONUS_MAX))


song_hardness.__module__ = _api.__name__
cover_hardness.__module__ = _api.__name__
music_difficulty_bonus.__module__ = _api.__name__
_api.song_hardness = song_hardness
_api.cover_hardness = cover_hardness
_api.music_difficulty_bonus = music_difficulty_bonus
