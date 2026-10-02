# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import re
from urllib.parse import quote, urlparse

from si_hyx_parts.kuhi._http import fetch_json, fetch_text
from si_hyx_parts.kuhi._match import episode_meta, expected_count
from si_hyx_parts.kuhi._media import build_ctx

NAME = "anibd"
BASE = "https://epeng.animeapps.top"


async def fetch_servers(anilist_id: int) -> list:
    data = await fetch_json(f"{BASE}/api2.php?epid={anilist_id}")
    return data if isinstance(data, list) else []


async def fetch_player_links(provider_link: str) -> list:
    data = await fetch_json(f"{BASE}/apilink.php?data={quote(provider_link, safe="-_.!~*'()")}")
    return data if isinstance(data, list) else []


def extract_video_url(html: str, origin: str) -> str | None:
    m = re.search(r'videoUrl\s*:\s*"([^"]+)"', html)
    if not m:
        return None
    raw = m.group(1)
    if re.match(r"^https?://", raw, re.IGNORECASE):
        return raw
    return f"{origin}{'' if raw.startswith('/') else '/'}{raw}"


async def resolve_player_stream(player_link: str) -> dict:
    parts = urlparse(player_link)
    origin = f"{parts.scheme}://{parts.netloc}"
    referer = f"{origin}/"
    html = await fetch_text(player_link, {"Referer": referer})
    hls = extract_video_url(html, origin)
    if not hls:
        raise RuntimeError(f"anibd: no videoUrl found at {player_link}")
    return {"hls": hls, "referer": referer}


def audio_from_server_name(name: str = "") -> str:
    return "dub" if re.search(r"dub", name or "", re.IGNORECASE) else "sub"


def _ep_number(value) -> int | float | None:
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    if not n >= 1 or n == float("inf"):
        return None
    return int(n) if n.is_integer() else n


def _build_lists(anilist_id: int, groups: list, ctx: dict, expected) -> dict:
    sub, dub = [], []
    seen_sub, seen_dub = set(), set()
    for group in groups or []:
        group = group if isinstance(group, dict) else {}
        audio = audio_from_server_name(group.get("server_name") or "")
        bucket = dub if audio == "dub" else sub
        seen = seen_dub if audio == "dub" else seen_sub
        for ep in group.get("server_data") or []:
            ep = ep if isinstance(ep, dict) else {}
            raw = ep.get("name") if ep.get("name") is not None else ep.get("slug")
            number = _ep_number(raw)
            if number is None:
                continue
            if expected and number > expected:
                continue
            if number in seen:
                continue
            seen.add(number)
            meta = episode_meta(number, ctx)
            bucket.append({
                "id": f"watch/{NAME}/{anilist_id}/{audio}/{NAME}-{number}",
                "number": number,
                "title": meta["title"] or f"Episode {number}",
                "duration": meta["duration"],
                "filler": meta["filler"],
                "uncensored": meta["uncensored"],
                "description": meta["description"],
                "image": meta["image"],
                "airDate": meta["airDate"],
                "sourceNumber": number,
                "sourceLink": ep.get("link"),
                "audio": audio,
            })
    sub.sort(key=lambda e: e["number"])
    dub.sort(key=lambda e: e["number"])
    return {"sub": sub, "dub": dub}


async def find_episode_link(anilist_id: int, audio: str, ep: int):
    groups = await fetch_servers(anilist_id)
    for group in groups or []:
        group = group if isinstance(group, dict) else {}
        if audio_from_server_name(group.get("server_name") or "") != audio:
            continue
        for item in group.get("server_data") or []:
            item = item if isinstance(item, dict) else {}
            raw = item.get("name") if item.get("name") is not None else item.get("slug")
            try:
                if float(raw) == float(ep):
                    return item.get("link")
            except (TypeError, ValueError):
                continue
    return None


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    groups = await fetch_servers(anilist_id)
    if not groups:
        raise RuntimeError(f"anibd: no episodes found for AniList {anilist_id}")
    expected = expected_count(media, ctx.get("anizip"))
    titles = media.get("title") or {}
    return {
        "meta": {
            "id": str(anilist_id),
            "title": titles.get("english") or titles.get("romaji"),
            "source": NAME,
            "matchScore": 1,
            "numbering": "standard",
            "episodeOffset": 0,
        },
        "episodes": _build_lists(anilist_id, groups, ctx, expected),
    }


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    provider_link = await find_episode_link(anilist_id, audio, ep)
    if not provider_link:
        raise RuntimeError(f"anibd episode {ep} not found")
    servers = await fetch_player_links(provider_link)
    streams = []
    active_assigned = False
    for entry in servers or []:
        entry = entry if isinstance(entry, dict) else {}
        link = entry.get("link")
        if not link:
            continue
        try:
            resolved = await resolve_player_stream(link)
            streams.append({
                "url": resolved["hls"],
                "type": "hls",
                "server": entry.get("server") or "AniBD",
                "audio": audio,
                "referer": resolved["referer"],
                "priority": 4 if active_assigned else 5,
                "isActive": not active_assigned,
            })
            active_assigned = True
        except Exception:
            parts = urlparse(link)
            streams.append({
                "url": link,
                "type": "embed",
                "server": entry.get("server") or "AniBD",
                "audio": audio,
                "referer": f"{parts.scheme}://{parts.netloc}/",
                "priority": 1,
                "isActive": False,
            })
    return streams
