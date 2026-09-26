# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Аниме-экранизация книги. Namespace: animepack.

У манги две совсем разные судьбы. Одну знают по её аниме — «Ван-Пис»,
«Берсерк», «Магическая битва»: игрок узнаёт разворот, потому что видел
сериал. Другую не экранизировали вовсе, и узнать её можно, только если читал.
Это два разных по трудности вопроса, поэтому они и считаются порознь:

* доля тех и других в паке задаётся настройкой (manga_adapted_percent);
* у экранизованной книги рядом с её собственным индексом встаёт индекс САМОГО
  АНИМЕ, и в дело идёт больший из двух, поэтому её вопрос стоит ровно на два
  очка дороже вопроса-кадра по тому же аниме;
* у неэкранизованной индекс свой, книжный: он поднимается на общую шкалу
  через manga_reach и упирается в потолок — книгу без аниме знают только
  читавшие, легче MANGA_MIN_LEVEL она не бывает (см. manga_scale.py).
"""
from __future__ import annotations
import animepack as _api


# Связи Shikimori, которые означают «это аниме сняли по ЭТОЙ книге». Сиквелы и
# спин-оффы сюда не входят: они говорят о родстве тайтлов, а не об экранизации.
ADAPTATION_KINDS = ("adaptation",)


def adaptation_ids(card: dict) -> list[int]:
    """id аниме-экранизаций книги (Shikimori id, в порядке карточки)."""
    out: list[int] = []
    for row in (card.get("related") or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("relationKind") or "") not in ADAPTATION_KINDS:
            continue
        anime = row.get("anime")
        if not isinstance(anime, dict):
            continue
        try:
            ident = int(anime.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if ident and ident not in out:
            out.append(ident)
    return out


def load_adaptations(gen, cards: list) -> dict:
    """{id карточки манги: карточка САМОЙ ЗАМЕТНОЙ её экранизации}.

    Спрашиваем аниме пачкой: у книги экранизаций бывает несколько (сериал,
    фильм, спешлы), а узнают её по самой популярной из них."""
    want: dict[int, list[int]] = {}
    for card in cards:
        if not isinstance(card, dict):
            continue
        ids = adaptation_ids(card)
        if ids:
            want[id(card)] = ids
    if not want:
        return {}
    cache = gen._adapt_cache
    need = sorted({i for ids in want.values() for i in ids if i not in cache})
    for batch in _api._chunks(need, _api.SHIKIMORI_BATCH):
        if gen.stopped():
            break
        try:
            rows = gen.shikimori.animes_by_ids(batch)
        except _api.AnimePackApiError as e:
            gen.log(f"Экранизации манги не загрузились: {e}")
            break
        for row in rows:
            try:
                cache[int(row.get("id") or 0)] = row
            except (TypeError, ValueError):
                continue
        for i in batch:
            cache.setdefault(i, {})
    out = {}
    for key, ids in want.items():
        best, best_index = {}, -1.0
        for i in ids:
            row = cache.get(i) or {}
            if not row:
                continue
            index = _api.SongCandidate(song={}, anime=row).own_index
            if index > best_index:
                best, best_index = row, index
        if best:
            out[key] = best
    return out


def apply_adaptation(cand, anime: dict) -> None:
    """Переносит на кандидата узнаваемость его экранизации.

    franchise_index — то самое поле, через которое SongCandidate.index берёт
    «узнаваемость серии, а не отдельной части» (у книги оно же — screen_index):
    сюда и кладём индекс аниме, чтобы и уровень, и цена книги считались по той
    же лесенке, что и вопрос-кадр по этому сериалу."""
    cand.adapted_from = dict(anime or {})
    if not cand.adapted_from:
        return
    index = _api.SongCandidate(song={}, anime=cand.adapted_from).own_index
    cand.franchise_index = max(float(cand.franchise_index or 0.0), index)

adaptation_ids.__module__ = _api.__name__
load_adaptations.__module__ = _api.__name__
apply_adaptation.__module__ = _api.__name__
_api.adaptation_ids = adaptation_ids
_api.load_adaptations = load_adaptations
_api.apply_adaptation = apply_adaptation
