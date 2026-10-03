"""AnimeLIB episode API; exclude dub players and retain all subtitle teams."""
from __future__ import annotations

from .episode_ru_catalog import get, integer, matches, names, player_name, release, subtitle_release

BASES = ("https://api.animelib.org/api", "https://api.cdnlibs.org/api")
SITE = "https://animelib.org"
HEADERS = {"Referer": SITE + "/", "Site-Id": "5"}


async def paged(url, params, headers=None):
    rows, page = [], 1
    while True:
        data = (await get(url, headers=headers or HEADERS, params={**params, "page": page})).json()
        rows.extend(data.get("data") or [])
        if not (data.get("links") or {}).get("next"):
            return rows
        page += 1


async def catalogue(candidate, ctx):
    headers = dict(HEADERS)
    if ctx.get("animelib_token"):
        headers["Authorization"] = "Bearer " + ctx["animelib_token"]
    for base in BASES:
        try:
            found = {}
            for query in names(candidate, ctx)[:3]:
                for row in await paged(base + "/anime", {"site_id[]": 5, "q": query}, headers):
                    if matches(row, candidate, ctx):
                        found[str(row["id"])] = row
                if found:
                    break
            catalog = {}
            for ident, row in found.items():
                referer = SITE + "/ru/anime/" + str(row.get("slug_url") or ident) + "/watch"
                for ep in await paged(base + "/episodes", {"anime_id": ident}, headers):
                    number = integer(ep.get("number"))
                    if number and str(ep.get("anime_id", ident)) == ident:
                        catalog.setdefault(number, []).append(release(
                            "animelib", "", base + "/episodes/" + str(ep["id"]), referer,
                            native_episode=True, episode_id=ep["id"], anime_id=ident, number=number,
                            api_headers=headers))
            if catalog:
                return catalog
        except Exception:
            continue
    return {}


def releases(data, row):
    if (str(data.get("id")) != str(row["episode_id"])
            or str(data.get("anime_id")) != str(row["anime_id"])
            or integer(data.get("number")) != row["number"]):
        return []
    result = []
    for player in data.get("players") or []:
        if not subtitle_release(player.get("translation_type")):
            continue
        embed = player.get("src") or player.get("href")
        name = player_name(player.get("player"), embed)
        if not name:
            continue
        label = (player.get("team") or {}).get("name") or "Субтитры"
        result.append(release("animelib", name, embed or row["embed"], row["referer"],
                              label=label, payload=player, release_id=player.get("id"),
                              api_headers=row.get("api_headers", HEADERS),
                              api_base=row["embed"].partition("/episodes/")[0]))
    return result


async def expand(row):
    data = (await get(row["embed"], headers=row.get("api_headers", HEADERS))).json().get("data") or {}
    return releases(data, row)
