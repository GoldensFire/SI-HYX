# -*- coding: utf-8 -*-
"""Only TV originals may become AI art questions; unknown relations fail closed."""
import re
from animepack_api import AnimePackApiError


_SEQUEL = re.compile(
    r"\b(?:season|сезон|part|часть)\s*(?:[2-9]\d*|ii|iii|iv|v)\b|"
    r"\b[2-9]\d*(?:nd|rd|th)?\s*(?:season|сезон|part|часть)\b|"
    r"\bfinal\s+season\b", re.IGNORECASE)


def possible_art_title(anime):
    if str(anime.get("kind", "")).lower() != "tv":
        return False
    # FLUX receives only the English title supplied by Shikimori. Do not fall
    # back to Russian or romaji: that would silently violate the API-language
    # promise shown in the UI.
    if not str(anime.get("english") or "").strip():
        return False
    if any(_SEQUEL.search(str(anime.get(key) or ""))
           for key in ("name", "english", "russian")):
        return False
    related = anime.get("related")
    if isinstance(related, list):
        return not any(isinstance(row, dict) and row.get("anime")
                       and row.get("relationKind") == "prequel" for row in related)
    return True


def eligible_art_title(anime, shikimori):
    if not possible_art_title(anime):
        return False
    if not isinstance(anime.get("related"), list):
        # Old catalog caches predate relation metadata. Refresh only this card.
        try:
            cards = shikimori.animes_by_ids([int(anime["id"])])
            card = next(c for c in cards if str(c.get("id")) == str(anime["id"]))
            if not isinstance(card.get("related"), list):
                return False
            anime.update(card)
        except (AnimePackApiError, AttributeError, KeyError, TypeError, ValueError, StopIteration):
            return False
    return possible_art_title(anime)
