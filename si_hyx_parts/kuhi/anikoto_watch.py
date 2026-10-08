# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import json
import re
from urllib.parse import quote, urljoin, urlparse
from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import fetch_json, fetch_text
from si_hyx_parts.kuhi._match import (
    attr, build_titles, decode_entities, episode_meta, expected_count,
    find_top_slugs, get_prequel_offset, select_series, strip_tags,
)
from si_hyx_parts.kuhi._media import build_ctx

from . import anikoto as _api


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0
    return int(f) if float(f).is_integer() else f


def _split_servers(server_html: str, audio: str):
    server_items, download_items = [], []
    for tm in re.finditer(
            r'<div class=\"type\" data-type=\"([^\"]+)\">([\s\S]*?)</ul>\s*</div>',
            server_html, re.IGNORECASE):
        type_name = tm.group(1)
        for li in re.finditer(
                r"<li\s+([^>]*data-link-id[^>]*)>([\s\S]*?)</li>",
                tm.group(2), re.IGNORECASE):
            lm = re.search(r'data-link-id=\"([^\"]+)\"', li.group(1))
            if not lm:
                continue
            name = strip_tags(li.group(2))
            if type_name == "dl" or "download" in name.lower() or "kiwi" in name.lower():
                download_items.append({"linkId": lm.group(1), "name": name})
            elif type_name == audio:
                server_items.append({"linkId": lm.group(1), "name": name})
    return server_items, download_items


def _merge_mapper(mapper_data, audio: str, server_items: list, download_items: list):
    if not isinstance(mapper_data, dict):
        return
    for s_key, s_obj in mapper_data.items():
        if s_key == "status" or not isinstance(s_obj, dict):
            continue
        clean = re.sub(r"[-_]+$", "", s_key).strip()
        entry = s_obj.get(audio)
        if not isinstance(entry, dict):
            continue
        url = entry.get("url")
        if isinstance(url, str) and url:
            server_items.append({"linkId": url, "name": clean})
        downloads = entry.get("download")
        if isinstance(downloads, dict):
            for _label, durl in downloads.items():
                if isinstance(durl, str) and durl:
                    download_items.append({"url": durl, "name": clean})


async def _resolve_server_url(link_id: str):
    if link_id.startswith("http"):
        return {"result": {"url": link_id}}
    try:
        return await fetch_json(
            f"{_api.BASE}/ajax/server?get={quote(link_id, safe='')}",
            {"X-Requested-With": "XMLHttpRequest", "Referer": _api.BASE + "/"},
        )
    except Exception:
        return None


async def _scrape_episode_watch(anilist_id: int, audio: str, ep_num: int, ctx: dict) -> list:
    series = await _api.resolve_series(anilist_id, ctx)
    provider_ep = int(ep_num) + series["offset"] if series["mode"] == "offset" else int(ep_num)
    audios = ["sub", "dub"] if audio == "all" else [audio]
    show_id = series.get("show_id") or await _api._fetch_show_id(series["slug"])
    list_json = await fetch_json(
        f"{_api.BASE}/ajax/episode/list/{show_id}",
        {"X-Requested-With": "XMLHttpRequest", "Referer": f"{_api.BASE}/watch/{series['slug']}"},
    )
    html = (list_json.get("result") if isinstance(list_json, dict) else None) or ""
    target = None
    wanted_mal = int((ctx.get("media") or {}).get("idMal") or 0)
    foreign = False
    for m in re.finditer(r"<a\s+[^>]*data-id=\"[^\"]*\"[^>]*>", html, re.IGNORECASE):
        tag = m.group(0)
        try:
            num = int(_api._data_attr(tag, "num"))
        except ValueError:
            continue
        if num == provider_ep:
            published = _api._data_attr(tag, "mal")
            if wanted_mal and published.isdigit() and int(published) not in (0, wanted_mal):
                foreign = True
                continue
            target = {"ids": _api._data_attr(tag, "ids"), "mal": _api._data_attr(tag, "mal"),
                      "slug": _api._data_attr(tag, "slug"), "timestamp": _api._data_attr(tag, "timestamp")}
            break
    if not target or not target["ids"]:
        if foreign:
            raise RuntimeError("Anikoto: MAL id выбранной серии не совпадает с тайтлом")
        raise RuntimeError(f"Episode {provider_ep} not found for show: {series['title']}")

    async def _servers():
        try:
            return await fetch_json(
                f"{_api.BASE}/ajax/server/list?servers={quote(target['ids'], safe='')}",
                {"X-Requested-With": "XMLHttpRequest", "Referer": _api.BASE + "/"},
            )
        except Exception:
            return None

    async def _mapper():
        if target["mal"] and target["slug"] and target["timestamp"]:
            try:
                return await fetch_json(
                    f"{_api.MAPPER}/{target['mal']}/{target['slug']}/{target['timestamp']}",
                    {"Referer": _api.BASE + "/"},
                )
            except Exception:
                return None
        return None

    server_data, mapper_data = await asyncio.gather(_servers(), _mapper())
    server_html = (server_data.get("result") if isinstance(server_data, dict) else None) or ""

    streams, download_pool, sub_seen = [], [], set()
    for aud in audios:
        server_items, download_items = _api._split_servers(server_html, aud)
        _api._merge_mapper(mapper_data, aud, server_items, download_items)
        for dl in download_items:
            if dl not in download_pool:
                download_pool.append((aud, dl))
        seen_names = set()
        for item in server_items:
            if item["name"] in seen_names:
                continue
            seen_names.add(item["name"])
            resolved = await _api._resolve_server_url(item["linkId"])
            embed_url = (resolved.get("result") or {}).get("url") if isinstance(resolved, dict) else None
            if not embed_url:
                continue
            server_intro = {"start": 0, "end": 0}
            server_outro = {"start": 0, "end": 0}
            if isinstance(resolved, dict):
                skip_data = (resolved.get("result") or {}).get("skip_data") or {}
                for key, dest in (("intro", server_intro), ("outro", server_outro)):
                    val = skip_data.get(key)
                    if isinstance(val, (list, tuple)) and len(val) == 2:
                        s, e = _api._num(val[0]), _api._num(val[1])
                        if s or e:
                            dest["start"], dest["end"] = s, e
            hls_sources = []
            if "#aHR0c" in embed_url:
                frag = embed_url.split("#", 1)[1]
                try:
                    decoded = base64.b64decode(frag + "=" * (-len(frag) % 4)).decode("utf-8", "errors")
                    if ".m3u8" in decoded:
                        hls_sources.append({"url": decoded, "variant": None})
                except ValueError:
                    pass
            extracted = await _api._extract_megaplay_details(embed_url)
            item_subs = []
            if extracted:
                for source in extracted["sources"]:
                    if not any(h["url"] == source["url"] for h in hls_sources):
                        hls_sources.append(source)
                for t in extracted["tracks"]:
                    if not isinstance(t, dict):
                        continue
                    mapped = _api._map_track(t, item["name"])
                    if mapped.get("url") and mapped["url"] not in sub_seen:
                        sub_seen.add(mapped["url"])
                        item_subs.append(mapped)
                for key, dest in (("intro", server_intro), ("outro", server_outro)):
                    val = extracted.get(key) or {}
                    if isinstance(val, dict):
                        s, e = _api._num(val.get("start")), _api._num(val.get("end"))
                        if s or e:
                            dest["start"], dest["end"] = s, e
            try:
                parsed = urlparse(embed_url)
                embed_origin = parsed.scheme + "://" + parsed.netloc + "/"
            except Exception:
                embed_origin = _api.BASE + "/"
            referer = (extracted["origin"] + "/" if extracted and extracted.get("origin")
                       else embed_origin)
            if hls_sources:
                for source in hls_sources:
                    obj = {
                        "url": source["url"],
                        "type": "hls",
                        "server": item["name"],
                        "audio": aud,
                        "embed": embed_url,
                        "referer": referer,
                        "subtitles": item_subs,
                        "priority": 5 if not streams else 4,
                        "isActive": not streams,
                    }
                    if source.get("variant"):
                        obj["variant"] = source["variant"]
                    if server_intro["start"] or server_intro["end"]:
                        obj["intro"] = dict(server_intro)
                    if server_outro["start"] or server_outro["end"]:
                        obj["outro"] = dict(server_outro)
                    streams.append(obj)
                streams.append({
                    "url": embed_url,
                    "type": "embed",
                    "server": item["name"],
                    "audio": aud,
                    "referer": embed_origin,
                    "priority": 4,
                    "isActive": False,
                })
            else:
                obj = {
                    "url": embed_url,
                    "type": "embed",
                    "server": item["name"],
                    "audio": aud,
                    "referer": embed_origin,
                    "priority": 4,
                    "isActive": not streams,
                }
                if server_intro["start"] or server_intro["end"]:
                    obj["intro"] = dict(server_intro)
                if server_outro["start"] or server_outro["end"]:
                    obj["outro"] = dict(server_outro)
                streams.append(obj)

    dl_seen = set()
    for aud, dl in download_pool:
        durl = dl.get("url")
        if not durl and dl.get("linkId"):
            resolved = await _api._resolve_server_url(dl["linkId"])
            durl = (resolved.get("result") or {}).get("url") if isinstance(resolved, dict) else None
        if durl and durl not in dl_seen:
            dl_seen.add(durl)
            streams.append({
                "url": durl,
                "type": "mp4",
                "server": dl.get("name", "Download"),
                "audio": aud,
                "referer": _api.BASE + "/",
                "priority": 1,
                "isActive": False,
            })
    return streams


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    if audio not in ("sub", "dub", "all"):
        raise ValueError("audio must be sub, dub or all")
    ctx = ctx or await build_ctx(int(anilist_id))
    return await _api._scrape_episode_watch(int(anilist_id), audio, int(ep), ctx)
