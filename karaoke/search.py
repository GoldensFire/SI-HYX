"""Bounded lyric discovery from song, performer and anime metadata."""
from __future__ import annotations

import re
import unicodedata
from .model import normalize

SEARCH_POLICY = "lyrics-search-v2"


def unique(values):
    seen, result = set(), []
    for value in values:
        if not isinstance(value, str):
            continue
        value = " ".join(value.split()).strip()
        key = normalize(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result


def values(mapping, keys):
    result = []
    for key in keys:
        value = mapping.get(key)
        result.extend(value if isinstance(value, (list, tuple)) else [value])
    return result


def context(song, anime, kind=""):
    return {
        "titles": unique(values(song, ("songName", "songNameJapanese", "songNameRomaji",
                                       "songNameEnglish", "songAliases"))),
        "artists": unique(values(song, ("songArtist", "songArtists", "artistAliases"))),
        "anime": unique(values(anime, ("name", "english", "russian", "japanese", "romaji",
                                      "synonyms", "title")) +
                        values(song, ("animeENName", "animeJPName", "animeAltName"))),
        "kind": kind,
        "song_type": str(song.get("songType") or ""),
    }


def title_names(title, info=None):
    names = unique([title, *(info or {}).get("titles", [])])
    # Version qualifiers commonly exist only in the audio catalogue. Retain
    # the exact name first, then search its base spelling as well.
    base = [re.sub(r"\s*[~(\[]?\s*(?:tv[ ._-]*(?:size|ver(?:sion)?)|"
                   r"full[ ._-]*ver(?:sion)?|classic[ ._-]*version)\b.*$", "", name,
                   flags=re.I).strip() for name in names]
    return unique(names + base)


def artist_names(artist, info=None):
    names = unique([artist, *(info or {}).get("artists", [])])
    return unique(names + [re.sub(r"[（(]\s*CV\s*[:：].*?[）)]", "", name,
                                  flags=re.I).strip() for name in names])


def queries(title, artist, info=None):
    info = info or {}
    titles, artists = title_names(title, info)[:3], artist_names(artist, info)[:3]
    anime = unique(info.get("anime", []))[:4]
    candidates = []
    for name in titles:
        candidates.extend([f"{name} {artist}".strip(), name])
    candidates.extend(artists)
    marker = info.get("song_type") or {"opening": "opening", "ending": "ending",
                                       "insert": "insert song"}.get(info.get("kind"), "")
    for name in anime:
        candidates.extend([f"{title} {name}".strip(), f"{name} {artist}".strip(),
                           f"{name} {marker}".strip(), name])
    return unique(candidates)[:20]


def matches_page(title, artist, heading, text, info=None):
    from .matching import title_key
    heading_key = title_key(heading)
    # Formatting/punctuation may differ, but a longer band's name containing
    # the requested singer as a substring is not an identity match.
    folded = unicodedata.normalize("NFKD", text).casefold()
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    def performer(name):
        pattern = r"(?<!\w)" + r"[\W_]*".join(map(re.escape, normalize(name))) + r"(?!\w)"
        return bool(normalize(name) and re.search(pattern, folded))
    return (any(title_key(name) and title_key(name) in heading_key
                for name in title_names(title, info)) and
            any(performer(name) for name in artist_names(artist, info)))
