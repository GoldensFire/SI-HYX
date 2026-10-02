"""AniList context, existing episode selection and stream preferences for Kuhi."""
from __future__ import annotations

import math
from urllib.parse import urlsplit

CUT_SECONDS = 20.0


def context(generator, candidate):
    data = generator.anizip.info(candidate.mal_id)
    card = candidate.anime
    mapping = data.get("mappings") or {}
    aid = int(card.get("anilistId") or card.get("anilist_id")
              or mapping.get("anilist_id") or 0)
    if not aid:
        return 0, {}
    titles = data.get("titles") or {}
    date = card.get("airedOn") or {}
    year = date.get("year") if isinstance(date, dict) else None
    count = int(card.get("episodes") or 0) or None
    media = {"id": aid, "idMal": candidate.mal_id,
             "title": {"english": card.get("english") or titles.get("en"),
                       "romaji": card.get("name") or titles.get("x-jat"),
                       "native": card.get("japanese") or titles.get("ja")},
             "synonyms": card.get("synonyms") or [], "episodes": count,
             "format": str(card.get("kind") or "tv").upper(),
             "status": "RELEASING" if card.get("status") == "ongoing" else "FINISHED",
             "seasonYear": year, "startDate": {"year": year}}
    return aid, {"media": media, "anizip": data}


def episode_catalog(result):
    """{actual episode number: {provider: [raw/sub]}}; never derive 1..N."""
    catalog = {}
    for provider, data in (result.get("providers") or {}).items():
        for audio in ("raw", "sub"):
            if audio == "raw" and provider != "mkissa":
                continue
            for row in (data.get("episodes") or {}).get(audio, ()):
                if not isinstance(row, dict) or row.get("audio", audio) != audio:
                    continue
                try:
                    value = float(row.get("number"))
                except (TypeError, ValueError):
                    continue
                if not math.isfinite(value) or not value.is_integer() or value <= 0:
                    continue
                modes = catalog.setdefault(int(value), {}).setdefault(provider, [])
                if audio not in modes:
                    modes.append(audio)
    return catalog


def hard_subbed(stream):
    explicit = stream.get("hardsub", stream.get("hardSub"))
    if explicit is not None:
        return str(explicit).lower() in ("true", "1", "yes")
    variant = str(stream.get("variant") or stream.get("subtitleType") or "").casefold()
    if "hard" in variant:
        return True
    if stream.get("audio") == "raw" or stream.get("subtitles") or "soft" in variant:
        return False
    # Kuhi's unlabelled sub streams may have burned captions; treat conservatively.
    return True


def playable(streams):
    seen, result = set(), []
    for stream in streams:
        url = str(stream.get("url") or "")
        if (stream.get("audio") not in ("raw", "sub")
                or stream.get("type") not in ("mp4", "hls", "dash")
                or urlsplit(url).scheme not in ("http", "https")):
            continue
        key = (url, stream.get("audio"), str(stream.get("headers")), stream.get("referer"))
        if key not in seen:
            seen.add(key)
            result.append(stream)
    return sorted(result, key=lambda s: (hard_subbed(s), s.get("audio") != "raw",
                                        -float(s.get("priority") or 0)))


def _range(value, duration):
    if not isinstance(value, dict):
        return None
    try:
        start, end = float(value["start"]), float(value["end"])
    except (KeyError, TypeError, ValueError):
        return None
    if math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration:
        return start, end
    return None


def choose_start(duration, stream, rng):
    """Sample uniformly over starts whose complete 20 seconds exclude OP/ED."""
    if not math.isfinite(duration) or duration < CUT_SECONDS + 2:
        return None
    intro = _range(stream.get("intro"), duration)
    outro = _range(stream.get("outro"), duration)
    guard = min(180.0, duration * 0.15)
    blocks = [intro or (0, guard), outro or (duration - guard, duration)]
    # Subtract forbidden ranges from the episode, then shorten by the clip length.
    segments = [(0.0, duration)]
    for start, end in sorted(blocks):
        remaining = []
        for left, right in segments:
            if end <= left or start >= right:
                remaining.append((left, right))
            else:
                if left < start:
                    remaining.append((left, start))
                if end < right:
                    remaining.append((end, right))
        segments = remaining
    windows = [(a, b - CUT_SECONDS) for a, b in segments if b - a >= CUT_SECONDS]
    total = sum(b - a for a, b in windows)
    if not windows:
        return None
    if total == 0:
        return windows[0][0]
    offset = rng.uniform(0, total)
    for left, right in windows:
        width = right - left
        if offset <= width:
            return left + offset
        offset -= width
    return windows[-1][1]
