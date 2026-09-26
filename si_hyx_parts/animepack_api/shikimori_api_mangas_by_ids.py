# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: mangas_by_ids. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def mangas_by_ids(self, ids: _api.Iterable[int]) -> list[dict]:
    """Карточки манги/ранобэ пачкой (≤50 за раз) — как animes_by_ids."""
    ids = [str(int(i)) for i in ids]
    if not ids:
        return []
    self.limiter.acquire()
    try:
        data = self.client._graphql(self.MANGAS_QUERY,
                                    {"ids": ",".join(ids), "limit": len(ids)})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
    return [m for m in (mangas or []) if isinstance(m, dict)]

def random_mangas(self, page: int = 1, *, limit: int = 50,
                  season: str = "", kinds: _api.Iterable[str] = (),
                  score: int = 0, genres: _api.Iterable[int] = (),
                  genres_exclude: _api.Iterable[int] = (),
                  order: str = "random") -> list[dict]:
    """Страница случайных карточек манги (order: random) с фильтрами.

        Про order — см. random_animes: обход каталога целиком идёт с `order: id`,
        случайная выборка — с `random`."""
    args = [f"page: {max(1, int(page))}", f"limit: {max(1, min(50, int(limit)))}",
            f"order: {self._RE_ARG.sub('', str(order or 'random')) or 'random'}",
            "censored: true"]
    if season:
        args.append(f'season: "{self._RE_ARG.sub("", str(season))}"')
    kinds = [self._RE_ARG.sub("", str(k)) for k in kinds]
    kinds = [k for k in kinds if k]
    if kinds:
        args.append(f'kind: "{",".join(kinds)}"')
    if score and int(score) > 0:
        args.append(f"score: {int(score)}")
    gen = [str(int(g)) for g in genres]
    gen += [f"!{int(g)}" for g in genres_exclude]
    if gen:
        args.append(f'genre: "{",".join(gen)}"')
    query = ("query {\n  mangas(" + ", ".join(args) + ") {"
             + self.MANGA_FIELDS + "}\n}")
    self.limiter.acquire()
    try:
        data = self.client._graphql(query, {})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    mangas = (data or {}).get("mangas") if isinstance(data, dict) else None
    return [m for m in (mangas or []) if isinstance(m, dict)]

def character_titles(self, char_id: int) -> dict:
    """{"animes": [...], "mangas": [...]} — где вообще появлялся персонаж.

        Нужно, чтобы в вопросе-персонаже ответом было САМОЕ ПЕРВОЕ произведение
        с ним, а не тот сиквел, из которого его случайно вытащили. В GraphQL у
        типа Character таких полей нет вовсе (проверено: «Field 'animes' doesn't
        exist on type 'Character'»), поэтому идём в REST /api/characters/:id —
        там у каждой строки есть и id, и aired_on."""
    try:
        cid = int(char_id)
    except (TypeError, ValueError):
        return {}
    try:
        resp = self._get(f"{self.base_url}/api/characters/{cid}",
                         timeout=(10, 30))
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    if not isinstance(data, dict):
        return {}
    out = {}
    for key in ("animes", "mangas"):
        rows = [r for r in (data.get(key) or []) if isinstance(r, dict)]
        out[key] = rows
    return out
