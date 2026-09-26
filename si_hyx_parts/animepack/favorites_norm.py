# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Надбавка за «в избранном» по СОСЕДЯМ по индексу. Namespace: animepack.

Раньше доля избранного мерилась одной планкой на весь каталог (2,4 на тысячу
единиц базы списков). У аниме медиана этой доли — 0,7 на тысячу, и до планки
дотягивали пять процентов тайтлов: заметному сериалу для надбавки нужно было
около двух тысяч избранных (жалоба пользователя). У манги наоборот: доля там
втрое выше, и надбавку получала чуть ли не вся верхняя половина каталога.

Теперь тайтл сравнивается с соседями — с тайтлами того же рода (аниме или
книги) и БЛИЗКОГО индекса: сколько избранных у них в среднем. Надбавка
начинается, когда у тайтла их в FAV_NEIGHBOR_START раз больше, чем у соседей.
На живой базе так её получают 10–17 % тайтлов в каждой полосе индекса — и у
аниме, и у манги поровну. Работает она по-прежнему только в плюс.

Соседи берутся из запомненного «в избранном» базы Shikimori (memo). Пока его
мало (свежая база, тесты), действует прежняя планка — index_favorites_factor.
"""
from __future__ import annotations

import bisect
import threading

import animepack as _api
import shikimori_api as _shiki

# Сколько соседей по индексу считается «окрестностью» тайтла.
FAV_NEIGHBORS = 60
# Во сколько раз больше соседей нужно избранных, чтобы надбавка началась.
FAV_NEIGHBOR_START = 2.0
# Меньше скольких известных точек соседям не верим — считаем по-старому.
FAV_NORM_MIN_POINTS = 200
# Нижняя граница «среднего у соседей»: в хвосте каталога избранных по
# нулю-единице, и пять избранных иначе выглядели бы пятикратным перевесом.
FAV_EXPECTED_FLOOR = 3.0
# Меньше стольких избранных надбавки не бывает вовсе — это шум.
FAV_MIN_COUNT = 5

_LOCK = threading.Lock()
_NORMS: dict = {}


class FavoritesNorm:
    """Известные пары «индекс — избранных», упорядоченные по индексу."""

    def __init__(self, pairs):
        rows = sorted((float(i), int(f)) for i, f in pairs if float(i) > 0)
        self.index = [i for i, _ in rows]
        self.favorites = [f for _, f in rows]
        self._prefix = [0]
        for fav in self.favorites:
            self._prefix.append(self._prefix[-1] + fav)

    def __len__(self) -> int:
        return len(self.index)

    def expected(self, index: float, own: int = -1) -> float:
        """Сколько избранных в среднем у FAV_NEIGHBORS соседей по индексу.

        own — избранное самого тайтла: если он сам среди соседей, его в
        среднее не берём, иначе хит тянул бы планку вверх за собой."""
        n = len(self.index)
        if not n:
            return 0.0
        pos = bisect.bisect_left(self.index, float(index))
        low = max(0, min(pos - FAV_NEIGHBORS // 2, n - FAV_NEIGHBORS))
        high = min(n, low + FAV_NEIGHBORS)
        total = self._prefix[high] - self._prefix[low]
        count = high - low
        if own >= 0 and count > 1:
            left = bisect.bisect_left(self.index, float(index), low, high)
            right = bisect.bisect_right(self.index, float(index), low, high)
            if own in self.favorites[left:right]:
                total -= own
                count -= 1
        return total / float(max(1, count))


def install_favorites_norms(db_cache) -> None:
    """Собирает соседей из базы Shikimori (зовут генератор и панель базы)."""
    built = {}
    for target in ("anime", "manga"):
        manga = target == "manga"
        known = db_cache.memo_group(f"{target}_favorites")
        if len(known) < FAV_NORM_MIN_POINTS:
            continue
        cards = {}
        for card in db_cache.all_cards(target):
            cards.setdefault(str(card.get("id") or ""), card)
        pairs = []
        for key, value in known.items():
            card = cards.get(str(key))
            try:
                fav = int(value)
            except (TypeError, ValueError):
                continue
            if card is None or fav < 0:
                continue
            cand = _api.SongCandidate(
                song={}, anime=card,
                kind=_api.MANGA_KIND if manga else _api.FRAME_KIND,
                media="manga" if manga else "anime")
            pairs.append((cand.own_index, fav))
        if len(pairs) >= FAV_NORM_MIN_POINTS:
            built[target] = FavoritesNorm(pairs)
    with _LOCK:
        _NORMS.clear()
        _NORMS.update(built)


def clear_favorites_norms() -> None:
    """Забыть соседей (тестам: вернуть прежнюю планку)."""
    with _LOCK:
        _NORMS.clear()


def title_favorites_factor(index: float, base: float, favorites,
                           manga: bool = False) -> float:
    """Множитель индекса за «в избранном» (1.0 — поправки нет)."""
    with _LOCK:
        norm = _NORMS.get("manga" if manga else "anime")
    if norm is None:
        return _api.index_favorites_factor(base, favorites)
    try:
        fav = int(favorites)
    except (TypeError, ValueError):
        return 1.0
    if fav < FAV_MIN_COUNT or index <= 0:
        return 1.0
    expected = max(FAV_EXPECTED_FLOOR, norm.expected(index, fav))
    ratio = fav / expected / FAV_NEIGHBOR_START
    if ratio <= 1.0:
        return 1.0
    factor = ratio ** _shiki._INDEX_FAVORITES_POWER
    return max(1.0, min(_shiki._INDEX_FAVORITES_MAX, factor))


for _name in ("FavoritesNorm", "install_favorites_norms",
              "clear_favorites_norms", "title_favorites_factor"):
    _obj = globals()[_name]
    _obj.__module__ = _api.__name__
    setattr(_api, _name, _obj)
