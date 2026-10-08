# Native Kuhi/anime-api, MIT, Copyright (c) 2026 aryaniiil. See LICENSE.
import asyncio
import re
import html as _html

from si_hyx_parts.kuhi._anilist import anilist_query
from si_hyx_parts.kuhi import _cache

RELATION_FRAGMENT = (
    "edges{relationType(version:2) node{id type episodes relations{"
    "edges{relationType(version:2) node{id type episodes relations{"
    "edges{relationType(version:2) node{id type episodes relations{"
    "edges{relationType(version:2) node{id type episodes}}}}}}}}}}}"
)


def decode_entities(s: str = "") -> str:
    if not s:
        return ""
    s = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), s)
    s = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), s)
    return _html.unescape(s).strip()


def strip_tags(html_text: str = "") -> str:
    text = re.sub(r"<[^>]*>", " ", html_text or "")
    return decode_entities(re.sub(r"\s+", " ", text))


def attr(tag: str, name: str) -> str:
    m = re.search(name + r"=[\"']([^\"']*)[\"']", tag or "", re.IGNORECASE)
    return decode_entities(m.group(1)) if m else ""


def norm(s: str = "") -> str:
    return re.sub(r"[\W_]", "", (s or "").casefold())


def dice_coeff(a: str, b: str) -> float:
    na, nb = norm(a), norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    if len(na) < 2 or len(nb) < 2:
        return 0.0
    bigrams: dict = {}
    for i in range(len(na) - 1):
        bg = na[i:i + 2]
        bigrams[bg] = bigrams.get(bg, 0) + 1
    hits = 0
    for i in range(len(nb) - 1):
        bg = nb[i:i + 2]
        if bigrams.get(bg, 0) > 0:
            hits += 1
            bigrams[bg] -= 1
    return (2 * hits) / (len(na) + len(nb) - 2)


def title_score(query: str, candidate: str, slug: str) -> float:
    base = max(dice_coeff(query, candidate), dice_coeff(query, slug.replace("-", " ")))
    qnum = re.search(r"\d+", norm(query))
    # Opaque provider hashes in a URL are not season numbers.
    snum = re.search(r"\d+", norm(candidate))
    qnum, snum = (qnum.group(0) if qnum else ""), (snum.group(0) if snum else "")
    if qnum and snum and qnum != snum:
        return base * 0.65
    if qnum and not snum:
        return base * 0.65
    if not qnum and snum:
        n = int(snum)
        if 1 < n < 1900:
            return base * (1 - 0.06 * (n - 1))
    is_movie_q = re.search(r"\b(movie|film|the movie)\b", query or "", re.IGNORECASE)
    is_movie_m = re.search(r"\b(movie|film)\b", candidate or "", re.IGNORECASE) or re.search(r"movie|film", slug or "")
    if is_movie_q and not is_movie_m:
        return base * 0.4
    qlen, slen = len(norm(query)), len(norm(slug.replace("-", " ")))
    return base * 0.8 if slen > qlen * 1.6 + 4 else base


def _build_search_queries(title: str) -> list:
    queries = [title]
    words = (title or "").strip().split()
    if len(words) > 4:
        queries.append(" ".join(words[:4]))
    if len(words) > 3:
        queries.append(" ".join(words[:3]))
    stripped = re.sub(r"\s+", " ", re.sub(
        r"\bseason\s*\d+\b|\bpart\s*\d+\b|\b\d+(rd|th|st|nd)\b", "", title or "", flags=re.IGNORECASE)).strip()
    if stripped and stripped != title:
        queries.append(stripped)
    seen, out = set(), []
    for q in queries:
        if len(q) >= 3 and q not in seen:
            seen.add(q)
            out.append(q)
    return out


async def find_top_slugs(titles: list, search_fn, n: int = 6) -> list:
    candidates: dict = {}
    queries = []
    for title in (titles or [])[:4]:
        for q in _build_search_queries(title):
            if q not in queries:
                queries.append(q)

    async def _one(q):
        try:
            return await search_fn(q)
        except Exception:
            return []

    for results in await asyncio.gather(*[_one(q) for q in queries]):
        for r in results or []:
            if r.get("slug") not in candidates:
                candidates[r["slug"]] = r.get("text", "")
    scored = []
    for slug, text in candidates.items():
        best = 0.0
        for title in (titles or [])[:2]:
            best = max(best, title_score(title, text, slug))
        if best >= 0.5:
            scored.append({"slug": slug, "title": text, "score": best})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:n]


def _prequel_offset(relations, depth: int = 0) -> int:
    if not relations or depth > 5:
        return 0
    for e in (relations.get("edges") or []):
        node = e.get("node") or {}
        if e.get("relationType") == "PREQUEL" and node.get("type") == "ANIME" and (node.get("episodes") or 0) >= 5:
            return (node.get("episodes") or 0) + _prequel_offset(node.get("relations"), depth + 1)
    return 0


async def get_prequel_offset(anilist_id: int) -> int:
    key = f"np-offset:{anilist_id}"
    hit = _cache.cached(key, _cache.SHOW_IDENTITY_TTL)
    if hit is not None:
        return hit
    gql = "query($id:Int){Media(id:$id,type:ANIME){relations{%s}}}" % RELATION_FRAGMENT
    try:
        data = await anilist_query(gql, {"id": int(anilist_id)})
        offset = _prequel_offset((data.get("Media") or {}).get("relations"))
    except Exception:
        offset = 0
    _cache.set(key, offset, _cache.SHOW_IDENTITY_TTL)
    return offset


def build_titles(media: dict | None, anizip: dict | None) -> list:
    media = media or {}
    anizip = anizip or {}
    titles = (anizip.get("titles") or {})
    out = [
        (media.get("title") or {}).get("english"),
        (media.get("title") or {}).get("romaji"),
        (media.get("title") or {}).get("native"),
        *(media.get("synonyms") or []),
        titles.get("en"),
        titles.get("x-jat"),
        titles.get("ja"),
    ]
    return [t for t in out if t]


def expected_count(media: dict | None, anizip: dict | None):
    counts = []
    if isinstance((media or {}).get("episodes"), int):
        counts.append(media["episodes"])
    for k in ((anizip or {}).get("episodes") or {}).keys():
        try:
            v = int(k)
            if v > 0:
                counts.append(v)
        except (TypeError, ValueError):
            pass
    return max(counts) if counts else None


def episode_meta(n: int, ctx: dict) -> dict:
    ctx = ctx or {}
    anizip = ctx.get("anizip") or {}
    az = ((anizip.get("episodes") or {}).get(str(n))) or {}
    runtime = az.get("runtime", az.get("length"))
    title = ((az.get("title") or {}).get("en")
             or (az.get("title") or {}).get("x-jat"))
    images = anizip.get("images") or {}
    cover = images.get("cover") if isinstance(images, dict) else None
    return {
        "title": title,
        "duration": runtime * 60 if runtime else None,
        "filler": az.get("filler", False),
        "uncensored": False,
        "description": az.get("overview", az.get("summary")),
        "image": az.get("image", cover),
        "airDate": az.get("airdate", az.get("aired")),
    }


async def select_series(candidates: list, scrape_fn, expected, status, offset, min_score: float = 0.65):
    async def _score(cand):
        # Episode counts may reject a match, never rescue a weak title match.
        if cand["score"] < min_score:
            return None
        try:
            episodes = await scrape_fn(cand["slug"])
        except Exception:
            return None
        nums = [e.get("number", 0) for e in episodes]
        local_hits = len([x for x in nums if 1 <= x <= expected]) if expected else len(nums)
        offset_hits = (len([x for x in nums if offset < x <= offset + expected])
                       if expected and offset else 0)
        mode = "offset" if offset_hits > local_hits else "local"
        hits = max(local_hits, offset_hits)
        count_score = 1.0
        if expected and expected >= 6:
            needed = -(-expected * 9 // 10) if status == "FINISHED" else max(1, expected - 3)
            count_score = 1.0 if hits >= needed else (hits / needed if needed else 0)
        return {**cand, "episodes": episodes, "mode": mode,
                "score": cand["score"] * (0.7 + count_score * 0.3)}
    scored = [r for r in await asyncio.gather(*[_score(c) for c in candidates]) if r]
    viable = [r for r in scored if r["episodes"] and r["score"] >= min_score]
    viable.sort(key=lambda x: x["score"], reverse=True)
    return viable[0] if viable else None
