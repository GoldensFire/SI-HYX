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

NAME = "anikoto"
BASE = "https://anikototv.to"
MAPPER = "https://mapper.nekostream.site/api/mal"
SPOOF_REF = "https://hianimes.re/"

LANG_MAP = {
    "en": "en", "english": "en", "ja": "ja", "japanese": "ja",
    "fr": "fr", "french": "fr", "de": "de", "german": "de",
    "es": "es", "spanish": "es", "pt": "pt", "portuguese": "pt",
}

_SBOX = (
    0x63, 0x7c, 0x77, 0x7b, 0xf2, 0x6b, 0x6f, 0xc5, 0x30, 0x01, 0x67, 0x2b,
    0xfe, 0xd7, 0xab, 0x76, 0xca, 0x82, 0xc9, 0x7d, 0xfa, 0x59, 0x47, 0xf0,
    0xad, 0xd4, 0xa2, 0xaf, 0x9c, 0xa4, 0x72, 0xc0, 0xb7, 0xfd, 0x93, 0x26,
    0x36, 0x3f, 0xf7, 0xcc, 0x34, 0xa5, 0xe5, 0xf1, 0x71, 0xd8, 0x31, 0x15,
    0x04, 0xc7, 0x23, 0xc3, 0x18, 0x96, 0x05, 0x9a, 0x07, 0x12, 0x80, 0xe2,
    0xeb, 0x27, 0xb2, 0x75, 0x09, 0x83, 0x2c, 0x1a, 0x1b, 0x6e, 0x5a, 0xa0,
    0x52, 0x3b, 0xd6, 0xb3, 0x29, 0xe3, 0x2f, 0x84, 0x53, 0xd1, 0x00, 0xed,
    0x20, 0xfc, 0xb1, 0x5b, 0x6a, 0xcb, 0xbe, 0x39, 0x4a, 0x4c, 0x58, 0xcf,
    0xd0, 0xef, 0xaa, 0xfb, 0x43, 0x4d, 0x33, 0x85, 0x45, 0xf9, 0x02, 0x7f,
    0x50, 0x3c, 0x9f, 0xa8, 0x51, 0xa3, 0x40, 0x8f, 0x92, 0x9d, 0x38, 0xf5,
    0xbc, 0xb6, 0xda, 0x21, 0x10, 0xff, 0xf3, 0xd2, 0xcd, 0x0c, 0x13, 0xec,
    0x5f, 0x97, 0x44, 0x17, 0xc4, 0xa7, 0x7e, 0x3d, 0x64, 0x5d, 0x19, 0x73,
    0x60, 0x81, 0x4f, 0xdc, 0x22, 0x2a, 0x90, 0x88, 0x46, 0xee, 0xb8, 0x14,
    0xde, 0x5e, 0x0b, 0xdb, 0xe0, 0x32, 0x3a, 0x0a, 0x49, 0x06, 0x24, 0x5c,
    0xc2, 0xd3, 0xac, 0x62, 0x91, 0x95, 0xe4, 0x79, 0xe7, 0xc8, 0x37, 0x6d,
    0x8d, 0xd5, 0x4e, 0xa9, 0x6c, 0x56, 0xf4, 0xea, 0x65, 0x7a, 0xae, 0x08,
    0xba, 0x78, 0x25, 0x2e, 0x1c, 0xa6, 0xb4, 0xc6, 0xe8, 0xdd, 0x74, 0x1f,
    0x4b, 0xbd, 0x8b, 0x8a, 0x70, 0x3e, 0xb5, 0x66, 0x48, 0x03, 0xf6, 0x0e,
    0x61, 0x35, 0x57, 0xb9, 0x86, 0xc1, 0x1d, 0x9e, 0xe1, 0xf8, 0x98, 0x11,
    0x69, 0xd9, 0x8e, 0x94, 0x9b, 0x1e, 0x87, 0xe9, 0xce, 0x55, 0x28, 0xdf,
    0x8c, 0xa1, 0x89, 0x0d, 0xbf, 0xe6, 0x42, 0x68, 0x41, 0x99, 0x2d, 0x0f,
    0xb0, 0x54, 0xbb, 0x16,
)

_INV_SBOX = (
    0x52, 0x09, 0x6a, 0xd5, 0x30, 0x36, 0xa5, 0x38, 0xbf, 0x40, 0xa3, 0x9e,
    0x81, 0xf3, 0xd7, 0xfb, 0x7c, 0xe3, 0x39, 0x82, 0x9b, 0x2f, 0xff, 0x87,
    0x34, 0x8e, 0x43, 0x44, 0xc4, 0xde, 0xe9, 0xcb, 0x54, 0x7b, 0x94, 0x32,
    0xa6, 0xc2, 0x23, 0x3d, 0xee, 0x4c, 0x95, 0x0b, 0x42, 0xfa, 0xc3, 0x4e,
    0x08, 0x2e, 0xa1, 0x66, 0x28, 0xd9, 0x24, 0xb2, 0x76, 0x5b, 0xa2, 0x49,
    0x6d, 0x8b, 0xd1, 0x25, 0x72, 0xf8, 0xf6, 0x64, 0x86, 0x68, 0x98, 0x16,
    0xd4, 0xa4, 0x5c, 0xcc, 0x5d, 0x65, 0xb6, 0x92, 0x6c, 0x70, 0x48, 0x50,
    0xfd, 0xed, 0xb9, 0xda, 0x5e, 0x15, 0x46, 0x57, 0xa7, 0x8d, 0x9d, 0x84,
    0x90, 0xd8, 0xab, 0x00, 0x8c, 0xbc, 0xd3, 0x0a, 0xf7, 0xe4, 0x58, 0x05,
    0xb8, 0xb3, 0x45, 0x06, 0xd0, 0x2c, 0x1e, 0x8f, 0xca, 0x3f, 0x0f, 0x02,
    0xc1, 0xaf, 0xbd, 0x03, 0x01, 0x13, 0x8a, 0x6b, 0x3a, 0x91, 0x11, 0x41,
    0x4f, 0x67, 0xdc, 0xea, 0x97, 0xf2, 0xcf, 0xce, 0xf0, 0xb4, 0xe6, 0x73,
    0x96, 0xac, 0x74, 0x22, 0xe7, 0xad, 0x35, 0x85, 0xe2, 0xf9, 0x37, 0xe8,
    0x1c, 0x75, 0xdf, 0x6e, 0x47, 0xf1, 0x1a, 0x71, 0x1d, 0x29, 0xc5, 0x89,
    0x6f, 0xb7, 0x62, 0x0e, 0xaa, 0x18, 0xbe, 0x1b, 0xfc, 0x56, 0x3e, 0x4b,
    0xc6, 0xd2, 0x79, 0x20, 0x9a, 0xdb, 0xc0, 0xfe, 0x78, 0xcd, 0x5a, 0xf4,
    0x1f, 0xdd, 0xa8, 0x33, 0x88, 0x07, 0xc7, 0x31, 0xb1, 0x12, 0x10, 0x59,
    0x27, 0x80, 0xec, 0x5f, 0x60, 0x51, 0x7f, 0xa9, 0x19, 0xb5, 0x4a, 0x0d,
    0x2d, 0xe5, 0x7a, 0x9f, 0x93, 0xc9, 0x9c, 0xef, 0xa0, 0xe0, 0x3b, 0x4d,
    0xae, 0x2a, 0xf5, 0xb0, 0xc8, 0xeb, 0xbb, 0x3c, 0x83, 0x53, 0x99, 0x61,
    0x17, 0x2b, 0x04, 0x7e, 0xba, 0x77, 0xd6, 0x26, 0xe1, 0x69, 0x14, 0x63,
    0x55, 0x21, 0x0c, 0x7d,
)

_RCON = (0x00, 0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1b, 0x36)


from .anikoto_megaplay import _xtime


from .anikoto_megaplay import _gmul

_M9 = [_gmul(i, 0x09) for i in range(256)]
_M11 = [_gmul(i, 0x0B) for i in range(256)]
_M13 = [_gmul(i, 0x0D) for i in range(256)]
_M14 = [_gmul(i, 0x0E) for i in range(256)]


from .anikoto_megaplay import _rot_word


from .anikoto_megaplay import _sub_word


from .anikoto_megaplay import _expand_key_256


from .anikoto_megaplay import _add_round_key


from .anikoto_megaplay import _inv_shift_rows


from .anikoto_megaplay import _inv_mix_columns


from .anikoto_megaplay import _decrypt_block


from .anikoto_megaplay import _aes256_cbc_decrypt


from .anikoto_megaplay import _decode_script_string


from .anikoto_megaplay import _script_strings


from .anikoto_megaplay import _megaplay_routes


from .anikoto_megaplay import _megaplay_decrypt


from .anikoto_megaplay import _build_source_url


from .anikoto_megaplay import _map_track


from .anikoto_megaplay import _extract_megaplay_details


async def search(query: str) -> list:
    html = await fetch_text(f"{BASE}/filter?keyword={quote(query)}", {"Referer": BASE + "/"})
    candidates = []
    for m in re.finditer(r"<a\b[^>]*>[\s\S]*?</a>", html, re.IGNORECASE):
        tag_m = re.search(r"<a\b[^>]*>", m.group(0), re.IGNORECASE)
        tag = tag_m.group(0) if tag_m else ""
        classes = attr(tag, "class").split()
        if "name" not in classes or "d-title" not in classes:
            continue
        href = attr(tag, "href")
        sm = re.search(r"/watch/([^/?#\"']+)", href)
        if not sm:
            continue
        slug = sm.group(1)
        if slug in ("filter", "watch"):
            continue
        inner = m.group(0)[len(tag_m.group(0)) if tag_m else 0:]
        name = strip_tags(inner)
        candidates.append({"slug": slug, "text": name or slug.replace("-", " ")})
    if not candidates:
        for m in re.finditer(r"<a\b[^>]*>[\s\S]*?</a>", html, re.IGNORECASE):
            tag_m = re.search(r"<a\b[^>]*>", m.group(0), re.IGNORECASE)
            href = attr(tag_m.group(0) if tag_m else "", "href")
            sm = re.search(r"anikototv\.to/watch/([^/?#\"']+)", href)
            if sm and sm.group(1) not in ("filter", "watch"):
                candidates.append({"slug": sm.group(1), "text": sm.group(1).replace("-", " ")})
    seen, out = set(), []
    for c in candidates:
        if c["slug"] not in seen:
            seen.add(c["slug"])
            out.append(c)
    return out


async def _fetch_show_id(slug: str) -> str:
    html = await fetch_text(f"{BASE}/watch/{slug}", {"Referer": BASE + "/"})
    m = re.search(r'data-id="(\d+)"', html)
    if not m:
        raise RuntimeError(f"Could not find show ID for slug: {slug}")
    return m.group(1)


def _data_attr(tag: str, name: str) -> str:
    m = re.search(r"data-" + name + r'=\"([^\"]*)\"', tag)
    return m.group(1) if m else ""


async def scrape_series(slug: str) -> list:
    show_id = await _fetch_show_id(slug)
    data = await fetch_json(
        f"{BASE}/ajax/episode/list/{show_id}",
        {"X-Requested-With": "XMLHttpRequest", "Referer": f"{BASE}/watch/{slug}"},
    )
    html = (data.get("result") if isinstance(data, dict) else None) or ""
    episodes = []
    for m in re.finditer(r"<a\s+[^>]*data-id=\"[^\"]*\"[^>]*>[\s\S]*?</a>", html, re.IGNORECASE):
        tag_m = re.search(r"<a\b[^>]*>", m.group(0), re.IGNORECASE)
        tag = tag_m.group(0) if tag_m else ""
        num_str = _data_attr(tag, "num")
        if not num_str:
            continue
        try:
            num = int(num_str)
        except ValueError:
            continue
        tm = re.search(r'<span class=\"d-title\"[^>]*>([\s\S]*?)</span>', m.group(0), re.IGNORECASE)
        title = strip_tags(tm.group(1)) if tm else ""
        episodes.append({
            "number": num,
            "title": title or f"Episode {num}",
            "hasSub": _data_attr(tag, "sub") == "1",
            "hasDub": _data_attr(tag, "dub") == "1",
        })
    episodes.sort(key=lambda e: e["number"])
    seen, out = set(), []
    for e in episodes:
        if e["number"] not in seen:
            seen.add(e["number"])
            out.append(e)
    return out


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(int(anilist_id))
    key = f"np:anikoto:{int(anilist_id)}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    titles = build_titles(media, ctx.get("anizip"))
    candidates = await find_top_slugs(titles, search)
    expected = expected_count(media, ctx.get("anizip"))
    try:
        offset = await get_prequel_offset(int(anilist_id))
    except Exception:
        offset = 0
    selected = await select_series(candidates, scrape_series, expected, media.get("status"), offset)
    if not selected:
        raise RuntimeError(f"Anikoto match not found for AniList {anilist_id}")
    show_id = await _fetch_show_id(selected["slug"])
    data = {"slug": selected["slug"], "show_id": show_id, "title": selected["title"],
            "mode": selected["mode"], "offset": offset, "score": selected["score"]}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


def _build_lists(anilist_id: int, series: dict, provider_eps: list, ctx: dict, expected) -> dict:
    sub, dub = [], []
    for src in provider_eps:
        number = src["number"] - series["offset"] if series["mode"] == "offset" else src["number"]
        if number < 1:
            continue
        if expected and number > expected:
            continue
        meta = episode_meta(number, ctx)
        base = {
            "number": number,
            "title": meta["title"] or src.get("title") or f"Episode {number}",
            "duration": meta["duration"],
            "filler": meta["filler"],
            "uncensored": meta["uncensored"],
            "description": meta["description"],
            "image": meta["image"],
            "airDate": meta["airDate"],
            "sourceNumber": src["number"],
        }
        if src.get("hasSub"):
            sub.append({"id": f"watch/anikoto/{anilist_id}/sub/anikoto-{number}", **base, "audio": "sub"})
        if src.get("hasDub"):
            dub.append({"id": f"watch/anikoto/{anilist_id}/dub/anikoto-{number}", **base, "audio": "dub"})
    return {"sub": sub, "dub": dub}


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(int(anilist_id))
    media = ctx["media"]
    series = await resolve_series(int(anilist_id), ctx)
    episodes = await scrape_series(series["slug"])
    expected = expected_count(media, ctx.get("anizip"))
    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": NAME,
            "matchScore": round(series["score"], 3),
            "numbering": series["mode"],
            "episodeOffset": series["offset"] if series["mode"] == "offset" else 0,
        },
        "episodes": _build_lists(int(anilist_id), series, episodes, ctx, expected),
    }


from .anikoto_watch import _num


from .anikoto_watch import _split_servers


from .anikoto_watch import _merge_mapper


from .anikoto_watch import _resolve_server_url


from .anikoto_watch import _scrape_episode_watch


from .anikoto_watch import watch
