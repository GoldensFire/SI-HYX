"""Detect characters whose names are already printed in the anime title."""
from __future__ import annotations

import re
import unicodedata


def _plain(value) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return " ".join(re.findall(r"[^\W_]+", text, flags=re.UNICODE))


def character_named_in_title(character: dict, anime: dict) -> bool:
    """True when any usable full character name occurs in any title spelling."""
    names = [character.get("name"), character.get("russian"),
             character.get("romaji")]
    names += list(character.get("names") or [])
    names += list(character.get("synonyms") or [])
    titles = [anime.get("name"), anime.get("russian"), anime.get("english"),
              anime.get("japanese")]
    titles += list(anime.get("synonyms") or [])
    title_texts = [f" {_plain(title)} " for title in titles if _plain(title)]
    for raw in names:
        name = _plain(raw)
        # Both the full name and its given/family-name parts count: Naruto
        # Uzumaki in a title called Naruto is just as self-answering. Ignore
        # single letters because aliases such as "D" create false positives.
        forms = {name, *(part for part in name.split() if len(part) >= 2)}
        for form in forms:
            if len(form) >= 2 and any(f" {form} " in title
                                      for title in title_texts):
                return True
    return False
