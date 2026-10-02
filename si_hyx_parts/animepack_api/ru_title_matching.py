# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Conservative matching for Russian sources. No fuzzy-title acceptance."""
import re
import unicodedata


def normalized(value):
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return re.sub(r"[\W_]+", " ", text).strip()


def title_names(card):
    found = []
    for key in ("name", "russian", "english", "japanese", "synonyms", "titles"):
        value = card.get(key)
        for name in value if isinstance(value, (list, tuple)) else [value]:
            if isinstance(name, str) and normalized(name) and name not in found:
                found.append(name)
    return found


def title_year(card):
    value = card.get("year") or (card.get("airedOn") or {}).get("year")
    try:
        return int(value) if value else None
    except (ValueError, TypeError):
        return None


def author_names(card):
    result = set()
    for author in card.get("authors") or []:
        name = author.get("name") if isinstance(author, dict) else author
        if normalized(name):
            result.add(normalized(name))
    return result


def match_title(card, candidates):
    wanted = str(card.get("id") or "")
    unique = {str(row.get("id") or row.get("slug")): row for row in candidates}
    direct = [row for row in unique.values()
              if wanted and str(row.get("shiki_id") or "") == wanted]
    if direct:
        if any(row.get("kind") and card.get("kind")
               and row["kind"] != card["kind"] for row in direct):
            return "AMBIGUOUS", None
        return ("NORMAL", direct[0]) if len(direct) == 1 else ("AMBIGUOUS", None)
    names = {normalized(n) for n in title_names(card)}
    year, kind, authors = title_year(card), card.get("kind"), author_names(card)
    accepted, uncertain = [], False
    for row in unique.values():
        linked = str(row.get("shiki_id") or "")
        if linked and linked != wanted:
            continue
        shared = names & {normalized(n) for n in row.get("titles", [])}
        if not shared:
            continue
        other_year, other_kind = title_year(row), row.get("kind")
        if kind and other_kind and kind != other_kind:
            continue
        if year and other_year and year != other_year:
            continue
        # Two independent aliases with a known compatible type, or one exact
        # distinctive title corroborated by year/author. Short names need two.
        corroborated = ((year and other_year == year)
                        or bool(authors & author_names(row)))
        distinctive = any(len(n) >= 12 for n in shared)
        if ((len(shared) >= 2 and other_kind == kind and kind)
                or (distinctive and corroborated)):
            accepted.append(row)
        else:
            uncertain = True
    if len(accepted) == 1 and not uncertain:
        return "NORMAL", accepted[0]
    return ("AMBIGUOUS" if accepted or uncertain else "NOT_FOUND"), None
