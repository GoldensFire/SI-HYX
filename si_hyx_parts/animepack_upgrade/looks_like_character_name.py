# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""looks_like_character_name. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def looks_like_character_name(text) -> bool:
    """Стоит ли на этот ответ переспросить базу персонажей."""
    line = str(text or "").strip()
    if not line or _api._RE_CYRILLIC.search(line) or _api.has_cjk(line):
        return False
    words = _api.norm_title(line).split()
    return 1 <= len(words) <= 3

looks_like_character_name.__module__ = _api.__name__
_api.looks_like_character_name = looks_like_character_name

def character_hit(query: str, chars: list) -> _api.Optional[str]:
    """Имя персонажа, совпавшее с ответом слово в слово, — или None.

    Сравниваем только с латинским именем (см. looks_like_character_name):
    русское имя персонажа сплошь и рядом совпадает с русским названием тайтла,
    в котором он играет."""
    needle = _api.norm_title(query)
    if not needle:
        return None
    for char in chars or []:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or "").strip()
        if name and _api.norm_title(name) == needle:
            return name
    return None

character_hit.__module__ = _api.__name__
_api.character_hit = character_hit

def exact_main(query: str, card: dict) -> bool:
    """Совпало ли с СОБСТВЕННЫМ названием тайтла слово в слово.

    Это и есть граница, за которой переспрашивать базу персонажей вредно:
    «Shiki», «Monster» и «Goblin Slayer» — настоящие аниме, у которых главный
    герой зовётся так же, и точный персонаж там находится всегда (проверено
    запросами). Раз собственное название тайтла совпало точь-в-точь — это
    тайтл, и мнение базы персонажей ничего не добавит.

    Опечатка сюда не входит НАРОЧНО (в отличие от is_exact): раз в ответе всё
    равно не то, что написано на Shikimori, у базы персонажей стоит спросить —
    вдруг это вообще имя героя, а тайтл подвернулся похожим."""
    needle = _api.norm_title(_api.strip_year(query))
    return bool(needle) and any(_api.norm_title(_api.strip_year(n)) == needle
                                for n in _api.main_names(card))

exact_main.__module__ = _api.__name__
_api.exact_main = exact_main

def matched_by_typo(query: str, card: dict) -> bool:
    """Совпало ли название только с точностью до опечатки — ни одно имя карточки
    не написано так же, как ответ. Нужно, чтобы сказать об этом в лог: правка
    вносится молча, а буква в ответе всё-таки чужая."""
    needle = _api.norm_title(_api.strip_year(query))
    if not needle or not _api.is_exact(query, card):
        return False
    return all(_api.norm_title(_api.strip_year(n)) != needle for n in _api.card_names(card))

matched_by_typo.__module__ = _api.__name__
_api.matched_by_typo = matched_by_typo

def is_exact(query: str, card: dict) -> bool:
    """Совпало ли название слово в слово (регистр, знаки и год не в счёт) — или
    оно же, но с опечаткой в букву-другую (см. is_typo).

    По этому признаку работают обе новые правки: и постер в ответе, и написание
    названия. Нестрогое совпадение сюда не годится — «Наруто» и «Наруто:
    Ураганные хроники» это разные тайтлы, и подставлять им общий постер или
    переписывать один под другой нельзя."""
    return _api.match_score(query, card) >= 1.0

is_exact.__module__ = _api.__name__
_api.is_exact = is_exact
