# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: search_characters_by_name. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def search_characters_by_name(self, name: str) -> list[dict]:
    """Карточки персонажей по имени (пустая строка — пустой список)."""
    query = str(name or "").strip()
    if not query:
        return []
    self.limiter.acquire()
    try:
        data = self.client._graphql(self.CHARACTER_SEARCH_QUERY,
                                    {"search": query})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    rows = (data or {}).get("characters") if isinstance(data, dict) else None
    return [c for c in (rows or []) if isinstance(c, dict)]

def search_animes_by_name(self, name: str, limit: int = 0) -> list[dict]:
    """Карточки аниме по названию (поиск Shikimori). Пустая строка — пустой
        список, сеть при этом не трогается вовсе."""
    query = str(name or "").strip()
    if not query:
        return []
    limit = max(1, min(50, int(limit or self.SEARCH_LIMIT)))
    self.limiter.acquire()
    try:
        data = self.client._graphql(self.SEARCH_QUERY,
                                    {"search": query, "limit": limit})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    animes = (data or {}).get("animes") if isinstance(data, dict) else None
    return [a for a in (animes or []) if isinstance(a, dict)]

def search_mangas_by_name(self, name: str, limit: int = 0) -> list[dict]:
    """Карточки манги, манхвы, манхуа и ранобэ по названию — то же, что
        search_animes_by_name, только по книгам."""
    query = str(name or "").strip()
    if not query:
        return []
    limit = max(1, min(50, int(limit or self.SEARCH_LIMIT)))
    self.limiter.acquire()
    try:
        data = self.client._graphql(self.MANGA_SEARCH_QUERY,
                                    {"search": query, "limit": limit})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
    return [m for m in (mangas or []) if isinstance(m, dict)]
