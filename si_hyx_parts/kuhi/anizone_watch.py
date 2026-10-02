# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import json
import math
import re
from urllib.parse import quote
from si_hyx_parts.kuhi import _transport as httpx
from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import UA, fetch_text
from si_hyx_parts.kuhi._match import (
    build_titles, decode_entities, dice_coeff, episode_meta,
    expected_count, get_prequel_offset,
)
from si_hyx_parts.kuhi._media import build_ctx

from . import anizone as _api


def _ordinal(value) -> int:
    m = re.search(
        r"\b(?:part|special|chapter)\s*(\d+|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        str(value or ""), re.IGNORECASE)
    if not m:
        return 0
    word = m.group(1).lower()
    try:
        return int(word)
    except ValueError:
        return _api._WORD_NUMS.get(word, 0)


def _align_episodes(episodes, media, expected) -> list:
    if not expected or len(episodes) <= expected:
        return episodes
    title = (media or {}).get("title") or {}
    titles = [title.get("english"), title.get("romaji"), title.get("native")]
    target = max([0] + [_api._ordinal(t) for t in titles if t])
    if target < 2:
        return episodes
    start = next((i for i, e in enumerate(episodes) if _api._ordinal(e.get("title")) == target), -1)
    if start < 0 or len(episodes) - start < expected:
        return episodes
    return [{**e, "number": i + 1} for i, e in enumerate(episodes[start:start + expected])]


def _build_lists(anilist_id: int, episodes: list, mode: str, offset: int,
                 ctx: dict, expected) -> dict:
    sub, dub = [], []
    for src in episodes:
        number = src["number"] - offset if mode == "offset" else src["number"]
        if number < 1:
            continue
        if expected and number > expected:
            continue
        meta = episode_meta(number, ctx)
        base = {
            "number": number,
            "title": meta.get("title") if meta.get("title") is not None
                      else src.get("title") or f"Episode {number}",
            "duration": meta.get("duration") if meta.get("duration") is not None
                        else src.get("duration"),
            "filler": meta.get("filler"),
            "uncensored": meta.get("uncensored"),
            "description": meta.get("description") if meta.get("description") is not None
                           else src.get("description"),
            "image": meta.get("image") if meta.get("image") is not None else src.get("image"),
            "airDate": meta.get("airDate") if meta.get("airDate") is not None
                       else src.get("airDate"),
            "sourceNumber": src.get("sourceNumber"),
        }
        if src.get("hasSub"):
            sub.append({"id": f"watch/anizone/{anilist_id}/sub/anizone-{number}",
                        **base, "audio": "sub"})
        if src.get("hasDub"):
            dub.append({"id": f"watch/anizone/{anilist_id}/dub/anizone-{number}",
                        **base, "audio": "dub"})
    return {"sub": sub, "dub": dub}


async def _series_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    local_ctx = {**ctx, "media": media}

    async def _offset():
        try:
            return await get_prequel_offset(int(anilist_id))
        except Exception:
            return 0

    series, offset = await asyncio.gather(
        _api.resolve_series(anilist_id, local_ctx), _offset())
    offset = offset or 0
    expected = expected_count(media, ctx.get("anizip"))
    limit = (expected + offset) if expected else None
    max_pages = None
    try:
        raw_mp = (ctx or {}).get("maxPages")
        if (raw_mp is not None and not isinstance(raw_mp, bool)
                and math.isfinite(float(raw_mp))):
            max_pages = max(1, int(float(raw_mp)))
    except (TypeError, ValueError):
        max_pages = None
    raw_episodes = await _api.scrape_series(series["slug"], limit, max_pages)
    mode = _api._choose_mode(raw_episodes, expected, offset)
    return {
        "media": media,
        "ctx": local_ctx,
        "series": series,
        "offset": offset,
        "expected": expected,
        "mode": mode,
        "episodes": _api._align_episodes(raw_episodes, media, expected),
    }


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    data = await _api._series_episodes(anilist_id, ctx)
    series = data["series"]
    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": _api.NAME,
            "matchScore": round(float(series["matchScore"]), 3),
            "numbering": data["mode"],
            "episodeOffset": data["offset"] if data["mode"] == "offset" else 0,
        },
        "episodes": _api._build_lists(int(anilist_id), data["episodes"], data["mode"],
                                 data["offset"], data["ctx"], data["expected"]),
    }


async def scrape_watch(slug: str, episode: int) -> dict:
    html = await fetch_text(f"{_api.BASE}/anime/{slug}/{episode}",
                            {"Referer": f"{_api.BASE}/anime/{slug}"})
    player = _api._player_data(html)
    if not isinstance(player, dict) or not player.get("src"):
        raise RuntimeError(f"AniZone player payload not found for episode {episode}")
    subtitles = []
    raw_subs = player.get("subtitles")
    for item in raw_subs if isinstance(raw_subs, list) else []:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        subtitles.append({
            "url": _api._normalize_url(item.get("file")),
            "label": item.get("title") or "",
            "srclang": item.get("language") or "",
            "format": item.get("format") or "vtt",
            "default": bool(item.get("default")),
        })
    return {
        "hls": _api._normalize_url(player.get("src")),
        "subtitles": subtitles,
        "storyboard": _api._normalize_url(player.get("storyboard")) or None,
        "chapters": _api._normalize_url(player.get("chapter")) or None,
    }


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    audio = str(audio or "sub").lower()
    if audio not in ("sub", "dub", "all"):
        raise RuntimeError(f"AniZone unknown audio '{audio}' (expected sub, dub, or all)")
    data = await _api._series_episodes(anilist_id, ctx)

    def _canon(number):
        return number - data["offset"] if data["mode"] == "offset" else number

    episode = next((e for e in data["episodes"] if _canon(e["number"]) == int(ep)), None)
    if audio == "all":
        if not episode or not episode.get("hasSub"):
            raise RuntimeError(f"AniZone sub episode {ep} not found")
        effective = "sub"
    else:
        if (not episode or (audio == "sub" and not episode.get("hasSub"))
                or (audio == "dub" and not episode.get("hasDub"))):
            raise RuntimeError(f"AniZone {audio} episode {ep} not found")
        effective = audio
    source_number = episode["sourceNumber"]
    found = await _api.scrape_watch(data["series"]["slug"], source_number)
    return [{
        "url": found["hls"],
        "type": "hls",
        "server": "AniZone",
        "audio": effective,
        "referer": f"{_api.BASE}/anime/{data['series']['slug']}/{source_number}",
        "subtitles": found["subtitles"],
        "storyboard": found["storyboard"],
        "chapters": found["chapters"],
        "priority": 1,
        "isActive": True,
    }]
