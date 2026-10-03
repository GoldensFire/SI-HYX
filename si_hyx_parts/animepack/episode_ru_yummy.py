"""YummyAnime's public Yani catalogue: retain every subtitle release of a title."""
from __future__ import annotations

from .episode_ru_catalog import (Catalogue, error_detail, get, integer, matches, names,
                                 player_name, release, subtitle_release)

BASE = "https://api.yani.tv"
SITE = "https://yummyani.me"


def skip(value):
    if not isinstance(value, dict):
        return None
    try:
        start = float(value["time"])
        end = start + float(value["length"])
    except (KeyError, TypeError, ValueError):
        return None
    return {"start": start, "end": end} if 0 <= start < end else None


def releases(rows, referer):
    catalog = {}
    for row in rows:
        data = row.get("data") or {}
        number = integer(row.get("number"))
        player = player_name(data.get("player"), row.get("iframe_url"))
        if not number or not player or not subtitle_release(data.get("dubbing")):
            continue
        timings = row.get("skips") or {}
        item = release("yummyanime", player, row.get("iframe_url"), referer,
                       label=data.get("dubbing", ""), intro=skip(timings.get("opening")),
                       outro=skip(timings.get("ending")), release_id=row.get("video_id"))
        if item["embed"]:
            catalog.setdefault(number, []).append(item)
    return catalog


async def catalogue(candidate, ctx):
    found = {}
    for query in names(candidate, ctx)[:3]:
        offset = 0
        while True:
            data = (await get(BASE + "/anime", params={"q": query, "limit": 100, "offset": offset})).json()
            rows = data.get("response") or []
            for row in rows:
                if matches(row, candidate, ctx):
                    found[str(row["anime_id"])] = row
            if len(rows) < 100:
                break
            offset += len(rows)
        if found:
            break
    catalog = Catalogue()
    failures = []
    for ident, row in found.items():
        data = (await get(BASE + f"/anime/{ident}/videos")).json()
        referer = SITE + "/catalog/item/" + str(row.get("anime_url") or ident)
        videos = data.get("response") or []
        for number, items in releases(videos, referer).items():
            catalog.setdefault(number, []).extend(items)
        from .episode_ru_players import subtitle_playlist
        from .episode_ru_catalog import absolute
        import re
        seen = set()
        for video in videos:
            embed = absolute(video.get("iframe_url"), referer)
            cvh_id = re.search(r"/cdn-iframe/(\d+)/(?:[^/?#]+/)?(\d+)/", embed)
            if cvh_id and cvh_id.groups() not in seen:
                seen.add(cvh_id.groups())
                try:
                    extra = await subtitle_playlist(embed, referer, "yummyanime")
                    for number, items in extra.items():
                        catalog.setdefault(number, []).extend(items)
                except Exception as error:
                    failures.append(error_detail(error))
    if not catalog:
        if failures:
            raise RuntimeError("YummyAnime/CVH: " + "; ".join(failures))
        catalog = Catalogue(reason="тайтл найден; нет RU-субтитров в поддерживаемых плеерах; Kodik пропущен"
                            if found else "тайтл не найден в каталоге YummyAnime")
    return catalog
