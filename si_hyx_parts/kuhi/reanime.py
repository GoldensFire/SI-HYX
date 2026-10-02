# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import base64
import hashlib
import re
from urllib.parse import urlencode, urlparse

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import fetch_json, fetch_text
from si_hyx_parts.kuhi._match import build_titles, episode_meta, expected_count
from si_hyx_parts.kuhi._media import build_ctx

NAME = "reanime"
BASE = "https://reanime.to"
FLIX = "https://flixcloud.cc"

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


from .reanime_aes import _xtime


from .reanime_aes import _gmul

_M9 = [_gmul(i, 0x09) for i in range(256)]
_M11 = [_gmul(i, 0x0B) for i in range(256)]
_M13 = [_gmul(i, 0x0D) for i in range(256)]
_M14 = [_gmul(i, 0x0E) for i in range(256)]


from .reanime_aes import _rot_word


from .reanime_aes import _sub_word


from .reanime_aes import _expand_key_256


from .reanime_aes import _add_round_key


from .reanime_aes import _inv_shift_rows


from .reanime_aes import _inv_mix_columns


from .reanime_aes import _decrypt_block


from .reanime_aes import _aes256_cbc_decrypt


from .reanime_aes import _sha256_hex


from .reanime_aes import _b64_to_bytes


from .reanime_aes import _derive_fields


from .reanime_wasm import _extract_ssr_obj


from .reanime_wasm import _parse_js_literal


from .reanime_wasm import _read_leb


from .reanime_wasm import _parse_wasm_decrypt


from .reanime_wasm import _run_decrypt


from .reanime_flixcloud import _extract_flixcloud


from .reanime_flixcloud import _num_or_none


async def search(query: str) -> list:
    data = await fetch_json(BASE + "/api/v1/search?" + urlencode({"q": query, "limit": 10}))
    results = data.get("results") if isinstance(data, dict) else None
    return results if isinstance(results, list) else []


async def _fetch_anime_detail(anime_id: str):
    try:
        return await fetch_json(f"{BASE}/api/v1/anime/{anime_id}")
    except Exception:
        return None


def _cover_anilist_id(cover_image) -> int | None:
    if not isinstance(cover_image, dict):
        return None
    for key in ("extra_large", "large", "medium"):
        url = cover_image.get(key)
        if isinstance(url, str):
            m = re.search(r"anilist\.co/.*/bx(\d+)-", url)
            if m:
                try:
                    return int(m.group(1))
                except ValueError:
                    return None
    return None


def _series_title(title, fallback: str) -> str:
    if isinstance(title, dict):
        return title.get("english") or title.get("romaji") or fallback
    return fallback


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    anilist_id = int(anilist_id)
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:reanime:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    mal_id = media.get("idMal")
    queries = build_titles(media, ctx.get("anizip"))[:5]

    async def _one(q):
        try:
            return await search(q)
        except Exception:
            return []

    found = await asyncio.gather(*[_one(q) for q in queries]) if queries else []
    candidates: dict = {}
    for results in found:
        for r in results or []:
            if isinstance(r, dict) and r.get("anime_id") and r["anime_id"] not in candidates:
                candidates[r["anime_id"]] = r

    for rid, r in candidates.items():
        if _cover_anilist_id(r.get("cover_image")) == anilist_id:
            data = {
                "animeId": rid,
                "title": _series_title(r.get("title"), rid),
                "anilistId": anilist_id,
                "malId": None,
                "subbed": _num_or_none(r.get("subbed")),
                "dubbed": _num_or_none(r.get("dubbed")),
                "episodesCount": _num_or_none(r.get("episodes")),
                "matchType": "cover_image",
                "matchScore": 1.0,
            }
            _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
            return data

    need_detail = [rid for rid, r in candidates.items()
                   if _cover_anilist_id(r.get("cover_image")) is None]

    async def _det(rid):
        return rid, await _fetch_anime_detail(rid)

    details = await asyncio.gather(*[_det(rid) for rid in need_detail]) if need_detail else []

    for rid, detail in details:
        if isinstance(detail, dict) and detail.get("anilist_id") is not None:
            try:
                detail_al = int(detail["anilist_id"])
            except (TypeError, ValueError):
                continue
            if detail_al == anilist_id:
                data = {
                    "animeId": rid,
                    "title": _series_title(detail.get("title"),
                                          _series_title((candidates[rid] or {}).get("title"), rid)),
                    "anilistId": anilist_id,
                    "malId": detail.get("mal_id"),
                    "subbed": _num_or_none(detail.get("subbed")),
                    "dubbed": _num_or_none(detail.get("dubbed")),
                    "episodesCount": _num_or_none(detail.get("episodes")),
                    "matchType": "anilist",
                    "matchScore": 1.0,
                }
                _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
                return data

    if mal_id is not None:
        for rid, detail in details:
            if not isinstance(detail, dict) or detail.get("mal_id") is None:
                continue
            try:
                detail_mal = int(detail["mal_id"])
            except (TypeError, ValueError):
                continue
            if detail_mal == int(mal_id):
                data = {
                    "animeId": rid,
                    "title": _series_title(detail.get("title"), rid),
                    "anilistId": anilist_id,
                    "malId": detail_mal,
                    "subbed": _num_or_none(detail.get("subbed")),
                    "dubbed": _num_or_none(detail.get("dubbed")),
                    "episodesCount": _num_or_none(detail.get("episodes")),
                    "matchType": "mal",
                    "matchScore": 0.9,
                }
                _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
                return data

    raise RuntimeError(f"No confirmed reanime match for AniList {anilist_id}")


async def _fetch_episodes_list(anime_id: str, limit: int = 2000) -> list:
    data = await fetch_json(
        f"{BASE}/api/v1/anime/{anime_id}/episodes?" + urlencode({"limit": limit}))
    eps = data.get("data") if isinstance(data, dict) else None
    return eps if isinstance(eps, list) else []


def _merge_episode(anilist_id: int, ep: dict, ctx: dict, audio: str) -> dict:
    number = ep.get("episode_number")
    meta = episode_meta(number, ctx)
    duration = meta["duration"]
    if duration is None and _num_or_none(ep.get("duration")) is not None:
        duration = ep["duration"] * 60
    filler = ep.get("is_filler")
    if filler is None:
        filler = meta["filler"]
    return {
        "id": f"watch/reanime/{anilist_id}/{audio}/reanime-{number}",
        "number": number,
        "title": meta["title"] or ep.get("title") or f"Episode {number}",
        "duration": duration,
        "filler": bool(filler),
        "uncensored": False,
        "description": meta["description"] or ep.get("description"),
        "image": meta["image"] or ep.get("thumbnail"),
        "airDate": meta["airDate"] or ep.get("aired"),
        "sourceNumber": number,
        "audio": audio,
    }


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    anilist_id = int(anilist_id)
    ctx = ctx or await build_ctx(anilist_id)
    series = await resolve_series(anilist_id, ctx)
    re_eps = await _fetch_episodes_list(series["animeId"])
    if not re_eps:
        raise RuntimeError(
            f"No reanime episodes found for AniList {anilist_id} (slug {series['animeId']})")
    has_sub = series.get("subbed") is None or series.get("subbed") > 0
    dub_count = series.get("dubbed") or 0
    try:
        dub_count = int(dub_count)
    except (TypeError, ValueError):
        dub_count = 0
    sub, dub = [], []
    for ep in sorted(re_eps, key=lambda e: e.get("episode_number") or 0):
        if not isinstance(ep, dict) or ep.get("episode_number") is None:
            continue
        if has_sub:
            sub.append(_merge_episode(anilist_id, ep, ctx, "sub"))
        if dub_count > 0 and ep["episode_number"] <= dub_count:
            dub.append(_merge_episode(anilist_id, ep, ctx, "dub"))
    sub.sort(key=lambda e: e["number"])
    dub.sort(key=lambda e: e["number"])
    return {
        "meta": {
            "id": series["animeId"],
            "title": series["title"],
            "source": NAME,
            "matchScore": series.get("matchScore", 1.0),
            "numbering": "local",
            "episodeOffset": 0,
        },
        "episodes": {"sub": sub, "dub": dub},
    }


from .reanime_watch import _resolve_stream


from .reanime_watch import _norm_audio


from .reanime_watch import watch
