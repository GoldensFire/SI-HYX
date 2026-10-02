# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import re

from si_hyx_parts.kuhi import _transport as httpx

from si_hyx_parts.kuhi import _cache
from si_hyx_parts.kuhi._http import UA, fetch_json
from si_hyx_parts.kuhi._match import build_titles, dice_coeff, episode_meta, expected_count
from si_hyx_parts.kuhi._media import build_ctx

NAME = "kaa"
BASE = "https://kaa.lt"
HLS_BASE = "https://hls.krussdomi.com/manifest"

_JSON_HEADERS = {"User-Agent": UA, "Accept": "application/json"}


async def kaa_search(query: str) -> list:

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        res = await client.post(f"{BASE}/api/fsearch",
                                headers={**_JSON_HEADERS, "Content-Type": "application/json"},
                                json={"page": 1, "query": query})
    if res.status_code != 200:
        raise RuntimeError(f"kaa fsearch HTTP {res.status_code}")
    data = res.json()
    result = data.get("result") if isinstance(data, dict) else None
    return result if isinstance(result, list) else []


async def kaa_show_info(show_slug: str):
    return await fetch_json(f"{BASE}/api/show/{show_slug}")


async def kaa_episode_page(show_slug: str, ep: int):
    return await fetch_json(f"{BASE}/api/show/{show_slug}/episodes?ep={ep}&lang=ja-JP")


async def kaa_all_episodes(show_slug: str) -> list:
    first = await kaa_episode_page(show_slug, 1)
    first = first if isinstance(first, dict) else {}
    pages = first.get("pages") if isinstance(first.get("pages"), list) else []
    all_eps = list(first.get("result")) if isinstance(first.get("result"), list) else []

    if len(pages) > 1:
        async def _one(pg):
            eps = pg.get("eps") if isinstance(pg, dict) else None
            start_ep = (eps or [None])[0]
            if not start_ep:
                return []
            d = await kaa_episode_page(show_slug, start_ep)
            d = d if isinstance(d, dict) else {}
            return d.get("result") if isinstance(d.get("result"), list) else []

        rest = await asyncio.gather(*[_one(pg) for pg in pages[1:]])
        for batch in rest:
            all_eps.extend(batch)

    return all_eps


async def kaa_episode_servers(show_slug: str, full_ep_slug: str):
    return await fetch_json(f"{BASE}/api/show/{show_slug}/episode/{full_ep_slug}")


def build_kaa_queries(titles: list) -> list:
    queries, seen = [], set()

    def _add(q):
        if q and q not in seen:
            seen.add(q)
            queries.append(q)

    for title in (titles or [])[:4]:
        if re.search(r"[\u3000-\u9fff\u4e00-\u9faf]", title):
            continue
        clean = re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", title, flags=re.ASCII)).strip()
        if not clean or len(clean) < 3:
            continue
        words = [w for w in clean.split(" ") if w]
        if len(words) <= 3:
            _add(clean)
        else:
            _add(" ".join(words[:2]))
            _add(" ".join(words[:3]))
    return queries


def score_candidate(candidate: dict, titles: list, season_year, anilist_format) -> float:
    title_en = candidate.get("title_en") or ""
    title_jp = candidate.get("title") or ""
    try:
        kaa_year = int(candidate.get("year"))
    except (TypeError, ValueError):
        kaa_year = 0
    kaa_type = str(candidate.get("type") or "").lower()

    base = 0.0
    for t in (titles or [])[:3]:
        if re.search(r"[\u3000-\u9fff\u4e00-\u9faf]", t):
            continue
        base = max(base, dice_coeff(t, title_en), dice_coeff(t, title_jp))

    year_mult = 1.0
    if season_year and kaa_year:
        diff = abs(int(season_year) - kaa_year)
        if diff == 0:
            year_mult = 1.2
        elif diff == 1:
            year_mult = 0.8
        else:
            year_mult = 0.5

    type_mult = 1.0
    af = str(anilist_format or "").upper()
    if af == "MOVIE" and kaa_type != "movie":
        type_mult = 0.25
    elif af != "MOVIE" and kaa_type == "movie":
        type_mult = 0.25
    elif af in ("OVA", "ONA", "SPECIAL") and kaa_type == "tv":
        type_mult = 0.5
    elif af == "TV" and kaa_type in ("ova", "special"):
        type_mult = 0.5

    return min(1, base * year_mult) * type_mult


async def resolve_series(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    key = f"np:{NAME}:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    media = ctx["media"]
    titles = build_titles(media, ctx.get("anizip"))
    queries = build_kaa_queries(titles)
    season_year = (media or {}).get("seasonYear")
    fmt = (media or {}).get("format")

    if not queries:
        raise RuntimeError(f"KAA: no usable search queries for AniList {anilist_id}")

    async def _one(q):
        try:
            return await kaa_search(q)
        except Exception:
            return []

    all_candidates: dict = {}
    for results in await asyncio.gather(*[_one(q) for q in queries]):
        for r in results or []:
            if isinstance(r, dict) and r.get("slug") not in all_candidates:
                all_candidates[r["slug"]] = r

    if not all_candidates:
        raise RuntimeError(f"KAA: no search results for AniList {anilist_id}")

    scored = []
    for _slug, candidate in all_candidates.items():
        score = score_candidate(candidate, titles, season_year, fmt)
        if score >= 0.5:
            scored.append({
                "slug": candidate.get("slug"),
                "title": candidate.get("title_en") or candidate.get("title"),
                "locales": candidate.get("locales") if isinstance(candidate.get("locales"), list) else [],
                "score": score,
            })
    scored.sort(key=lambda x: x["score"], reverse=True)

    if not scored:
        raise RuntimeError(f"KAA: no confident match for AniList {anilist_id}")
    best = scored[0]
    if best["score"] < 0.6:
        raise RuntimeError(
            f"KAA: low confidence match for AniList {anilist_id} "
            f'\u2014 best "{best["slug"]}" score {best["score"]:.3f}'
        )
    data = {"slug": best["slug"], "title": best["title"],
            "locales": best["locales"], "score": best["score"]}
    _cache.set(key, data, _cache.SHOW_IDENTITY_TTL)
    return data


async def build_ep_map(show_slug: str, show_info: dict) -> list:
    show_info = show_info if isinstance(show_info, dict) else {}
    if show_info.get("type") == "movie":
        m = re.search(r"/(ep-(\d+)-([a-f0-9]+))$", show_info.get("watch_uri") or "", re.IGNORECASE)
        if m:
            return [{"number": 1, "fullSlug": m.group(1)}]
        return []
    episodes = await kaa_all_episodes(show_slug)
    out = []
    for e in episodes:
        if not isinstance(e, dict):
            continue
        out.append({
            "number": e.get("episode_number"),
            "fullSlug": f"ep-{e.get('episode_number')}-{e.get('slug')}",
            "title": e.get("title"),
            "duration": round(e.get("duration_ms") / 1000) if e.get("duration_ms") else None,
        })
    return out


def _norm_num(num):
    if isinstance(num, float) and num.is_integer():
        return int(num)
    return num


async def get_episodes(anilist_id: int, ctx: dict | None = None) -> dict:
    ctx = ctx or await build_ctx(anilist_id)
    media = ctx["media"]
    series = await resolve_series(anilist_id, ctx)
    show_info = await kaa_show_info(series["slug"])
    show_info = show_info if isinstance(show_info, dict) else {}

    locales = show_info.get("locales") if isinstance(show_info.get("locales"), list) else series.get("locales")
    has_dub = "en-US" in (locales or [])

    ep_map = await build_ep_map(series["slug"], show_info)
    if not ep_map:
        raise RuntimeError(f"KAA: no episodes found for AniList {anilist_id} (slug: {series['slug']})")

    expected = expected_count(media, ctx.get("anizip"))
    sub, dub = [], []

    for ep in ep_map:
        num = _norm_num(ep.get("number"))
        if not isinstance(num, (int, float)) or isinstance(num, bool) or not num >= 1:
            continue
        if expected and num > expected:
            continue
        meta = episode_meta(num, ctx)
        base = {
            "number": num,
            "title": meta["title"] or ep.get("title") or f"Episode {num}",
            "duration": meta["duration"] if meta["duration"] is not None else ep.get("duration"),
            "filler": meta["filler"],
            "uncensored": False,
            "description": meta["description"],
            "image": meta["image"],
            "airDate": meta["airDate"],
            "sourceNumber": num,
        }
        sub.append({"id": f"watch/{NAME}/{anilist_id}/sub/{NAME}-{num}", **base, "audio": "sub"})
        if has_dub:
            dub.append({"id": f"watch/{NAME}/{anilist_id}/dub/{NAME}-{num}", **base, "audio": "dub"})

    return {
        "meta": {
            "id": series["slug"],
            "title": series["title"],
            "source": NAME,
            "matchScore": round(series["score"], 3),
            "numbering": "standard",
            "episodeOffset": 0,
        },
        "episodes": {"sub": sub, "dub": dub},
    }


async def watch(anilist_id: int, audio: str, ep: int, ctx: dict | None = None) -> list:
    ctx = ctx or await build_ctx(anilist_id)
    series = await resolve_series(anilist_id, ctx)
    show_info = await kaa_show_info(series["slug"])
    show_info = show_info if isinstance(show_info, dict) else {}

    locales = show_info.get("locales") if isinstance(show_info.get("locales"), list) else series.get("locales")
    if audio == "dub" and "en-US" not in (locales or []):
        raise RuntimeError(f"KAA: no English dub for AniList {anilist_id}")

    ep_map = await build_ep_map(series["slug"], show_info)
    try:
        target = int(ep)
    except (TypeError, ValueError):
        target = None
    found = next((e for e in ep_map if e.get("number") == target), None)
    if not found:
        raise RuntimeError(f"KAA: episode {ep} not found for AniList {anilist_id}")

    episode_data = await kaa_episode_servers(series["slug"], found["fullSlug"])
    episode_data = episode_data if isinstance(episode_data, dict) else {}
    servers = episode_data.get("servers") if isinstance(episode_data.get("servers"), list) else []
    if not servers:
        raise RuntimeError(f"KAA: no streams for episode {ep} (AniList {anilist_id})")

    streams = []
    for s in servers:
        s = s if isinstance(s, dict) else {}
        src = s.get("src")
        if not src:
            continue
        m = re.search(r"[?&]id=([^&]+)", src)
        if not m:
            continue
        streams.append({
            "url": f"{HLS_BASE}/{m.group(1)}/master.m3u8",
            "type": "hls",
            "server": s.get("name") or "KAA",
            "audio": audio,
            "referer": "https://krussdomi.com/",
            "priority": 1,
            "isActive": True,
        })

    if not streams:
        raise RuntimeError(f"KAA: could not resolve stream for episode {ep}")
    return streams
