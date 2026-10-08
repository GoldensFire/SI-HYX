"""CVH, Aniboom and native AnimeLIB links, fetched through the bounded transport."""
from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, unquote, urlsplit

from .episode_ru_animego import Tags
from .episode_ru_catalog import get, integer, normalized, release, stream_from, subtitle_release

CVH = "https://plapi.cdnvideohub.com/api/v1/player/sv"


async def subtitle_playlist(embed, referer, source, *, title_id=None, publisher="747", aggregator="mali"):
    match = re.search(r"/cdn-iframe/(\d+)((?:/[^/?#]+){0,3})", embed)
    if not match and not title_id:
        return {}
    segments = [part for part in match[2].split("/") if part] if match else []
    numbers = [integer(part) for part in segments if part.isdigit()]
    season = numbers[0] if numbers else 1
    data = (await get(CVH + "/playlist", headers={"Referer": referer},
                      params={"pub": str(publisher), "aggr": str(aggregator),
                              "id": str(title_id or match[1])})).json()
    catalog = {}
    for item in data.get("items") or []:
        number = integer(item.get("episode"))
        if (not number or integer(item.get("season") or 1) != season
                or not subtitle_release(item.get("voiceType")) or not item.get("vkId")):
            continue
        catalog.setdefault(number, []).append(release(
            source, "cvh", embed, referer, label=item.get("voiceStudio") or "Субтитры",
            video_id=str(item["vkId"]), release_id=str(item["vkId"])))
    return catalog


async def cvh(row):
    url = row["embed"]
    if row.get("video_id"):
        return await cvh_video(row, row["video_id"])
    match = re.search(r"/cdn-iframe/(\d+)((?:/[^/?#]+){0,3})", url)
    if not match:
        return []
    segments = [unquote(v) for v in match[2].split("/") if v]
    studio = segments.pop(0) if segments and not segments[0].isdigit() else None
    studio = (parse_qs(urlsplit(url).query).get("dubbing") or [studio])[0]
    numbers = [int(v) for v in segments if v.isdigit()]
    if len(numbers) < 2:
        return []  # Never silently select episode 1 of an incomplete embed.
    headers = {"Referer": row["referer"], "Accept": "application/json"}
    data = (await get(CVH + "/playlist", headers=headers,
                      params={"pub": "747", "aggr": "mali", "id": match[1]})).json()
    candidates = [item for item in data.get("items", [])
                  if int(item.get("season") or 1) == numbers[0]
                  and int(item.get("episode") or 0) == numbers[1]
                  and subtitle_release(item.get("voiceType"))
                  and (not studio or subtitle_release(studio)
                       or normalized(item.get("voiceStudio")) == normalized(studio))]
    result = []
    for item in candidates:
        result.extend(await cvh_video(row, str(item["vkId"])))
    return result


async def cvh_video(row, ident):
    video = (await get(CVH + "/video/" + ident, headers={"Referer": row["referer"]})).json()
    result = []
    for key, target in (video.get("sources") or {}).items():
        if not isinstance(target, str) or not target.startswith("http"):
            continue
        kind = "hls" if key == "hlsUrl" else "dash" if key in ("dashUrl", "dashManifestUrl") else "mp4"
        # The API key is only a hint; ffprobe must still measure the actual MP4.
        if kind == "mp4" and key not in ("mpegFullHdUrl", "mpegQhdUrl", "mpeg2kUrl", "mpeg4kUrl"):
            continue
        result.append(stream_from(row, target, kind, referer=row["embed"]))
    return result


def source_url(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return value if value.startswith(("http", "//")) else ""
    return value.get("src", "") if isinstance(value, dict) else ""


async def aniboom(row):
    response = await get(row["embed"], headers={"Referer": row["referer"]})
    params = next((attrs.get("data-parameters") for tag, attrs in Tags(response.text).tags
                   if tag == "video" and attrs.get("data-parameters")), None)
    if not params:
        return []
    data = json.loads(params)
    origin = urlsplit(row["embed"])
    referer = f"{origin.scheme}://{origin.netloc}/"
    result = []
    for key, kind in (("hls", "hls"), ("dash", "dash"), ("fallbackHls", "hls"), ("fallbackDash", "dash")):
        target = source_url(data.get(key))
        if target:
            result.append(stream_from(row, target, kind, referer=referer))
    return result


def native_urls(payload):
    """Read supplied native URLs; never invent /1080 variants of a 720 path."""
    result = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            if isinstance(value, str):
                if re.search(r"\.(mp4|m3u8|mpd)(?:[?:]|$)", value, re.I):
                    result.append(value)
            elif isinstance(value, (dict, list)):
                result.extend(native_urls(value))
    elif isinstance(payload, list):
        for value in payload:
            result.extend(native_urls(value))
    return list(dict.fromkeys(result))


async def animelib(row):
    payload = row.get("payload") or {}
    video = payload.get("video") or {}
    qualities = video.get("quality") or []
    if qualities:
        # Native API supplies relative quality.href paths and named video servers.
        from .episode_ru_animelib import HEADERS
        base = row.get("api_base", "https://api.animelib.org/api")
        constants = (await get(base + "/constants", headers=row.get("api_headers", HEADERS),
                               params={"fields[]": "videoServers"})).json().get("data") or {}
        servers = constants.get("videoServers") or []
        server_id = payload.get("video_domain") or "main"
        servers.sort(key=lambda s: s.get("id") != server_id)
        result = []
        for server in servers:
            for quality in qualities:
                target = str(quality.get("href") or "")
                if target:
                    # Заявленное качество (файл …_360.mp4) отсекает 360p/720p без
                    # ffprobe по сети: в живом прогоне на них ушло 268 проверок.
                    # 1080p всё равно меряется ffprobe — подпись не доказательство.
                    claimed = integer(quality.get("quality"))
                    result.append(stream_from(row, str(server["url"]).rstrip("/") + "/" + target.lstrip("/"),
                                              "mp4", referer=row["referer"], hardsub=False,
                                              subtitles=native_subtitles(payload, str(server["url"])),
                                              server=server.get("id"),
                                              **({"manifest_height": claimed} if claimed else {})))
        return result
    targets = native_urls(payload)
    if not targets and row["embed"]:
        response = await get(row["embed"], headers={"Referer": row["referer"], "Site-Id": "5"})
        try:
            targets = native_urls(response.json())
        except ValueError:
            targets = [attrs["src"] for tag, attrs in Tags(response.text).tags
                       if tag in ("video", "source") and attrs.get("src")]
    return [stream_from(row, target, "hls" if ".m3u8" in target else "dash" if ".mpd" in target else "mp4",
                        referer=row["referer"]) for target in targets]


def native_subtitles(payload, server):
    result = []
    data = payload.get("subtitles") or []
    if isinstance(data, dict):
        data = [data]
    for row in data:
        if str(row.get("language") or "").casefold() not in ("", "ru", "rus"):
            continue
        for key in ("url", "src", "href"):
            target = row.get(key)
            if target:
                from .episode_ru_catalog import absolute
                path = urlsplit(target).path.rsplit("/", 1)[-1]
                name = path if path.endswith((".ass", ".srt", ".vtt", ".ssa")) else "captions." + str(row.get("format") or "ass")
                result.append({"url": absolute(target, server), "name": name})
                break
    return result


async def resolve(row, scope, resources):
    if row["player"] == "alloha":
        from .episode_ru_alloha import open_streams
        return await open_streams(row, scope, resources)
    function = {"cvh": cvh, "aniboom": aniboom, "animelib": animelib}.get(row["player"])
    return await function(row) if function else []
