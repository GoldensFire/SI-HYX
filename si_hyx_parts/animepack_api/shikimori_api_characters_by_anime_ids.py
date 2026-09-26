# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriApi: characters_by_anime_ids. Public namespace: animepack_api."""
from __future__ import annotations
import animepack_api as _api


def characters_by_anime_ids(self, ids: _api.Iterable[int],
                            target: str = "anime") -> dict:
    """{id аниме: [{"name", "names", "poster", "main"}]} — персонажи с
        портретами. Роль «Main»/«Supporting» приходит списком rolesEn, а
        "names" — все варианты имени (русское, ромадзи и «Прочие»).

        target="manga" спрашивает то же самое у манги/ранобэ: characterRoles
        есть и у типа Manga."""
    ids = [str(int(i)) for i in ids]
    if not ids:
        return {}
    manga = str(target or "anime") == "manga"
    query = self.CHARACTERS_QUERY_MANGA if manga else self.CHARACTERS_QUERY
    root = "mangas" if manga else "animes"
    self.limiter.acquire()
    try:
        data = self.client._graphql(query,
                                    {"ids": ",".join(ids), "limit": len(ids)})
    except Exception as e:
        raise _api._friendly(e, "Shikimori") from e
    out: dict[int, list[dict]] = {}
    for anime in ((data or {}).get(root) or []):
        if not isinstance(anime, dict):
            continue
        try:
            key = int(anime.get("malId") or anime.get("id") or 0)
        except (TypeError, ValueError):
            continue
        rows = []
        for role in (anime.get("characterRoles") or []):
            char = (role or {}).get("character") or {}
            poster = (char.get("poster") or {})
            url = poster.get("originalUrl") or poster.get("mainUrl")
            name = (char.get("russian") or char.get("name") or "").strip()
            if not url or not name:
                continue
            roles = [str(r).lower() for r in (role.get("rolesEn") or [])]
            # «Прочие» Shikimori хранит списком, но внутри одной строки
            # бывает сразу несколько прозвищ через запятую («Al, Armored
            # Alchemist») — разбиваем, иначе целиком такую строку никто
            # никогда не назовёт.
            alts = [name, char.get("russian"), char.get("name")]
            for syn in (char.get("synonyms") or []):
                alts.extend(str(syn or "").split(","))
            names, seen = [], set()
            for alt in alts:
                alt = str(alt or "").strip()
                if len(alt) > 1 and alt.casefold() not in seen:
                    seen.add(alt.casefold())
                    names.append(alt)
            rows.append({"id": char.get("id"), "name": name, "names": names,
                         "poster": str(url), "main": "main" in roles})
        if rows:
            out[key] = rows
    return out
