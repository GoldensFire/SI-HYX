# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""famous_clip. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def famous_clip(clips: list, other: dict) -> _api.Optional[dict]:
    """Клип, который известнее найденного тайтла в разы, — или None.

    Одноимённый клип отбирает ответ у тайтла только с очень большим перевесом:
    иначе в паке окажется обложка чужого фильма (см. CLIP_POPULARITY_EDGE).
    Если тайтла не нашлось вовсе, клип ответом не становится — правило «клип не
    бывает ответом» остаётся в силе, а вопрос просто не трогается."""
    best = _api._best_by_popularity(clips)
    if best is None:
        return None
    return best if _api.popularity(best) >= max(
        1.0, _api.popularity(other) * _api.CLIP_POPULARITY_EDGE) else None

famous_clip.__module__ = _api.__name__
_api.famous_clip = famous_clip

def pick_card(query: str, cards: list, strict: bool = True) -> _api.Optional[dict]:
    """Та самая карточка тайтла — или None, если ответ на аниме не похож.

    Клипы и промо не рассматриваются вовсе — кроме одного случая, см.
    CLIP_POPULARITY_EDGE. Точных совпадений бывает несколько — выбор между ними
    разбирает pick_exact; нестрогое совпадение годится, только если точных не
    нашлось вовсе и строгость снята."""
    own, syn, loose, clips = [], [], [], []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        score = _api.match_score(query, card)
        if _api.is_clip(card):
            # Клип в расчёт идёт, только если ответ совпал с его СОБСТВЕННЫМ
            # названием: по синонимам клипы ловят на себя имена персонажей
            # («Teto Kasane» — синоним клипа «Yababaina»).
            if score >= 1.0 and not _api.synonym_only(query, card):
                clips.append(card)
            continue
        if score >= 1.0:
            (syn if _api.synonym_only(query, card) else own).append(card)
        elif score > 0.0:
            loose.append((score, card))
    exact = _api.pick_exact(own, syn)
    if exact is not None:
        return _api.famous_clip(clips, exact) or exact
    if strict or not loose:
        return None
    best_score, best = max(loose, key=lambda pair: pair[0])
    return best if best_score >= _api.LOOSE_THRESHOLD else None

pick_card.__module__ = _api.__name__
_api.pick_card = pick_card
