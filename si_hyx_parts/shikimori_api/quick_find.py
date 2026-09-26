# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""quick_find. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


# Удобный шорткат под пример из ТЗ: find_anime(query, max_score=6, …)
def quick_find(query: str = "", *, max_score: _api.Optional[float] = None,
               min_score: _api.Optional[float] = None,
               kind: str = "", status: str = "",
               year_from: _api.Optional[int] = None, year_to: _api.Optional[int] = None,
               episodes_min: _api.Optional[int] = None,
               episodes_max: _api.Optional[int] = None,
               genres: _api.Optional[_api.Iterable[int]] = None,
               exclude_genres: _api.Optional[_api.Iterable[int]] = None,
               client: _api.Optional[_api.ShikimoriApiClient] = None,
               **find_kwargs: _api.Any) -> list[_api.Anime]:
    """Однострочный поиск без ручного создания клиента/фильтра.
    Пример: quick_find("наруто", max_score=6)."""
    own_client = client is None
    client = client or _api.ShikimoriApiClient()
    try:
        flt = _api.AnimeFilter(
            query=query, kind=kind, status=status,
            year_from=year_from, year_to=year_to,
            score_min=min_score, score_max=max_score,
            episodes_min=episodes_min, episodes_max=episodes_max,
            genres=list(genres) if genres else [],
            exclude_genres=list(exclude_genres) if exclude_genres else [],
        )
        return _api.find_anime(client, flt, **find_kwargs)
    finally:
        if own_client:
            client.close()

quick_find.__module__ = _api.__name__
_api.quick_find = quick_find
