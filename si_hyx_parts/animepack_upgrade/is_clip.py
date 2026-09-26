# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""is_clip. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def is_clip(card: dict) -> bool:
    """Клип, промо или реклама — не тайтл. Незнакомый тип считаем настоящим:
    список типов Shikimori пополняет, и глушить новые вслепую нельзя."""
    return str(card.get("kind") or "").strip().lower() in _api.CLIP_KINDS

is_clip.__module__ = _api.__name__
_api.is_clip = is_clip

def synonym_only(query: str, card: dict) -> bool:
    """Совпало ТОЛЬКО по синониму, и собственные названия тут ни при чём.

    «Teto Kasane» — это синоним клипа «Yababaina», у которого ни одно своё
    название на ответ не похоже: такое совпадение не значит ничего. А вот ответ
    «Наруто ТВ-1» (тоже синоним) засчитывается — собственное название «Наруто»
    в нём есть."""
    needle = _api.norm_title(_api.strip_year(query))
    if not needle:
        return True
    mains = [_api.norm_title(_api.strip_year(n)) for n in _api.main_names(card)]
    for main in [m for m in mains if m]:
        if _api.same_title(main, needle):
            return False                       # совпало собственным именем
        if f" {main} " in f" {needle} " or f" {needle} " in f" {main} ":
            return False                       # своё название есть в ответе
    return True

synonym_only.__module__ = _api.__name__
_api.synonym_only = synonym_only
