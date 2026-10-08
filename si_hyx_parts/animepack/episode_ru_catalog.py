"""Shared identity checks and release metadata for Russian subtitle catalogues."""
from __future__ import annotations

import math
import re
from urllib.parse import urljoin, urlsplit

from si_hyx_parts.kuhi._http import UA
from si_hyx_parts.kuhi._transport import AsyncClient

PLAYER_ORDER = ("animelib", "cvh", "aniboom", "alloha")


class Catalogue(dict):
    """Keep the public episode mapping while explaining an empty result."""
    def __init__(self, *args, reason="", **kwargs):
        super().__init__(*args, **kwargs)
        self.reason = reason


def error_detail(error):
    return re.sub(r"https?://\S+", "[URL]", str(error))[:180]


def integer(value):
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number.is_integer() and number > 0 else 0
    except (TypeError, ValueError):
        return 0


def normalized(value):
    return re.sub(r"[\W_]+", "", str(value or "").casefold())


def names(candidate, ctx):
    card = candidate.anime
    values = [card.get(k) for k in ("russian", "name", "english", "japanese")]
    values += list((ctx.get("anizip", {}).get("titles") or {}).values())
    values += list(card.get("synonyms") or [])
    return list(dict.fromkeys(str(v).strip() for v in values if v and str(v).strip()))


def matches(row, candidate, ctx):
    """An explicit foreign id never falls back to a similar-looking title."""
    remote = row.get("remote_ids") or {}
    mal = integer(remote.get("myanimelist_id") or remote.get("shikimori_id") or row.get("mal_id"))
    shiki = re.search(r"/animes/(\d+)", str(row.get("shikimori_href") or ""))
    mal = mal or (int(shiki[1]) if shiki else 0)
    aid = integer(row.get("anilist_id"))
    wanted_aid = integer((ctx.get("media") or {}).get("id"))
    if mal or aid:
        return ((not mal or mal == candidate.mal_id)
                and (not aid or not wanted_aid or aid == wanted_aid))
    aliases = [row.get(k) for k in ("title", "name", "rus_name", "eng_name", "original_title")]
    aliases += list(row.get("other_titles") or [])
    if not set(map(normalized, filter(None, aliases))) & set(map(normalized, names(candidate, ctx))):
        return False
    year = integer(row.get("year"))
    wanted_year = integer((ctx.get("media") or {}).get("seasonYear"))
    return not year or not wanted_year or year == wanted_year


def subtitle_release(value):
    if isinstance(value, dict):
        # AnimeLIB documents 1 = subtitles and 2 = dubbing.
        if value.get("id") is not None:
            return str(value["id"]) == "1"
        value = value.get("label") or value.get("name") or ""
    label = str(value or "").casefold()
    return (bool(re.search(r"субтитр|\bsub(?:title)?s?\b", label))
            and not re.search(r"\b(?:eng(?:lish)?|en|dub)\b|английск|озвуч", label))


def player_name(label, url):
    value = (str(label) + " " + str(url)).casefold()
    if "kodik" in value or "aniqit" in value:
        return ""
    if "cvh" in value or "cdnvideohub" in value or "/cdn-iframe/" in value:
        return "cvh"
    for player in ("aniboom", "alloha"):
        if player in value:
            return player
    if "animelib" in value or "anilib" in value or "lib" == str(label).casefold():
        return "animelib"
    return ""


def absolute(url, base):
    result = urljoin(base, str(url or ""))
    return result if urlsplit(result).scheme in ("http", "https") else ""


async def get(url, *, headers=None, params=None):
    async with AsyncClient(follow_redirects=True) as client:
        response = await client.get(url, headers={"User-Agent": UA, **(headers or {})}, params=params)
    response.raise_for_status()
    return response


def release(source, player, embed, referer, *, label="", **extra):
    return {"source": source, "player": player, "embed": absolute(embed, referer),
            "referer": referer, "release": str(label), **extra}


def stream_from(row, url, kind, **extra):
    return {"provider": f"{row['source']}/{row['player']}", "player": row["player"],
            "source": row["source"], "source_link": row["referer"], "release": row.get("release", ""),
            "audio": "sub", "ru_subtitles": True, "hardsub": True,
            "url": absolute(url, row["embed"]), "type": kind, **extra}
