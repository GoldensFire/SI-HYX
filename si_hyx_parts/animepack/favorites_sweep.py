# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Кого спрашивать про «в избранном». Public namespace: animepack.

«В избранном» — вторая мера узнаваемости рядом со списками: тайтл могли
смотреть немногие, а в избранное класть часто — значит знают его лучше, чем
говорит посещаемость. В API Shikimori этого числа нет вовсе, оно живёт только
на странице тайтла, то есть стоит ОТДЕЛЬНОГО запроса на карточку. Поэтому
раньше оно спрашивалось лишь у кандидатов, дошедших до загрузки, и в базе на
пятьдесят тысяч карточек не было ни одного ответа.

Спросить все шестьдесят тысяч — это часов двенадцать. Но и не нужно: надбавка
за избранное работает только В ПЛЮС и упирается в потолок
(_INDEX_FAVORITES_MAX), поэтому карточка, которой даже максимальная надбавка
не поможет дотянуться до последнего порога лесенки, останется на последнем уровне при
любом ответе. Спрашивать её незачем — ответ ничего не изменит ни в сложности,
ни в цене.

Здесь и живёт этот отбор: чистая арифметика над карточками, без сети и без
состояния генератора.
"""
from __future__ import annotations
import animepack as _api


def favorites_worth_asking(card: dict, manga: bool = False) -> bool:
    """Может ли ответ про избранное вообще что-то изменить для этой карточки.

    Считаем по самому щедрому допущению: даём карточке максимальную надбавку
    и смотрим, дотягивает ли она хоть до предпоследнего уровня. Не дотянула —
    карточка остаётся на последнем уровне при любом числе в избранном."""
    cand = _api.SongCandidate(song={}, anime=card or {},
                              media="manga" if manga else "anime")
    reach = _api.manga_reach(cand.own_index) if manga else cand.own_index
    import shikimori_api as _shiki
    best = reach * float(_shiki._INDEX_FAVORITES_MAX)
    return best >= float(_api.INDEX_LEVELS[-1])


def favorites_targets(cards, manga: bool = False) -> list[int]:
    """Номера Shikimori, у которых стоит спросить избранное, — от самых
    заметных к самым тихим.

    Порядок здесь не украшение: обход долгий, его бросают на середине, и
    первыми должны узнаться те карточки, которые и правда попадают в паки."""
    rows = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        try:
            shiki_id = int(card.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not shiki_id or not favorites_worth_asking(card, manga):
            continue
        cand = _api.SongCandidate(song={}, anime=card,
                                  media="manga" if manga else "anime")
        rows.append((cand.own_index, shiki_id))
    rows.sort(key=lambda row: -row[0])
    out, seen = [], set()
    for _index, shiki_id in rows:
        if shiki_id not in seen:
            seen.add(shiki_id)
            out.append(shiki_id)
    return out

favorites_worth_asking.__module__ = _api.__name__
favorites_targets.__module__ = _api.__name__
_api.favorites_worth_asking = favorites_worth_asking
_api.favorites_targets = favorites_targets
