# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""_numbering. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def _numbering(words: list[str]) -> list[str]:
    """Номера из названия — арабские и римские. Они должны совпасть точно."""
    return [w for w in words if w.isdigit() or _api._RE_ROMAN.match(w)]

_numbering.__module__ = _api.__name__
_api._numbering = _numbering

def _edits(a: str, b: str, limit: int) -> int:
    """Расстояние Левенштейна, но не дальше limit + 1: дальше нам всё равно."""
    stop = max(0, int(limit)) + 1
    prev = list(range(len(b) + 1))
    for i, ch in enumerate(a, 1):
        cur = [i]
        for j, other in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ch != other)))
        if min(cur) >= stop:
            return stop
        prev = cur
    return min(prev[-1], stop)

_edits.__module__ = _api.__name__
_api._edits = _edits

def is_typo(a: str, b: str) -> bool:
    """Одно и то же название с точностью до опечатки (обе строки — уже
    нормализованные, см. norm_title)."""
    if not a or not b or a == b:
        return False
    if min(len(a), len(b)) < _api.TYPO_MIN_LEN:
        return False
    limit = 2 if max(len(a), len(b)) >= _api.TYPO_LONG_LEN else 1
    if abs(len(a) - len(b)) > limit:
        return False
    words_a, words_b = a.split(), b.split()
    if len(words_a) != len(words_b):
        return False
    if _api._numbering(words_a) != _api._numbering(words_b):
        return False
    return _api._edits(a, b, limit) <= limit

is_typo.__module__ = _api.__name__
_api.is_typo = is_typo

def glued(text: str) -> str:
    """Название без пробелов вовсе — «Tegami bachi» и «Tegamibachi» это одно и
    то же слово, разбитое на слоги по вкусу писавшего."""
    return str(text or "").replace(" ", "")

glued.__module__ = _api.__name__
_api.glued = glued

def same_title(a: str, b: str) -> bool:
    """Одно ли это название: слово в слово, с точностью до пробелов или до
    опечатки. Обе строки должны быть уже пропущены через
    norm_title(strip_year(...)).

    Пробелы прощаются только длинным названиям (тот же порог, что у опечаток):
    склеить «K-On!» до «kon» — это уже другое слово, а «Tegamibachi» короче
    восьми букв не бывает."""
    if not a:
        return False
    if a == b or _api.is_typo(a, b):
        return True
    one, two = _api.glued(a), _api.glued(b)
    return one == two and len(one) >= _api.TYPO_MIN_LEN

same_title.__module__ = _api.__name__
_api.same_title = same_title

def match_score(query: str, card: dict) -> float:
    """Насколько карточка похожа на искомое название: 1.0 — точное совпадение
    хотя бы одного из имён (или оно же с опечаткой), ниже — по близости строк."""
    needle = _api.norm_title(_api.strip_year(query))
    if not needle:
        return 0.0
    best = 0.0
    for name in _api.card_names(card):
        # Год в сравнении не участвует: Shikimori держит его прямо в названии у
        # части тайтлов («Могучий Атом (2003)»), а в паке его обычно нет.
        other = _api.norm_title(_api.strip_year(name))
        if not other:
            continue
        if _api.same_title(needle, other):
            return 1.0
        best = max(best, _api.difflib.SequenceMatcher(None, needle, other).ratio())
    return best

match_score.__module__ = _api.__name__
_api.match_score = match_score
