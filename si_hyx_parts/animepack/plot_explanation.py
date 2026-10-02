"""Убирает известные названия аниме из развёрнутого сюжетного ответа."""
from __future__ import annotations

import re

_QUOTES = r'[«»„“”"\x27]'
_ENDINGS = ("ами", "ями", "ого", "ему", "ому", "ыми", "ими", "ая", "яя",
            "ое", "ее", "ой", "ей", "ий", "ый", "ые", "ие", "ов", "ев",
            "ам", "ям", "ах", "ях", "а", "я", "ы", "и", "е", "у", "ю", "ь")
_PREPOSITIONS = {"в": "в этом аниме", "из": "из этого аниме",
                 "по": "по этому аниме", "для": "для этого аниме"}


def _word_pattern(word, inflect):
    if inflect and re.fullmatch(r"[а-яё]+", word, re.IGNORECASE):
        for ending in _ENDINGS:
            if word.casefold().endswith(ending) and len(word) - len(ending) >= 3:
                return re.escape(word[:-len(ending)]) + r"[а-яё]{0,4}"
    return re.escape(word)


def _patterns(titles):
    names = set()
    for title in titles or ():
        name = " ".join(str(title or "").split())
        if not name:
            continue
        names.add(name)
        base = re.sub(r"\s+(?:[—–-]\s*)?(?:\d+\s*-?й\s*сезон|"
                      r"\d+(?:nd|rd|th)?\s+Season|\d+)\s*$", "", name,
                      flags=re.IGNORECASE)
        if base:
            names.add(base)
    for name in sorted(names, key=len, reverse=True):
        words = re.findall(r"[^\W_]+", name)
        if words:
            yield (r"(?<!\w)" + r"[\W_]+".join(
                _word_pattern(word, True) for word in words)
                + r"(?!\w)")


def without_titles(explanation: str, titles) -> str:
    """Сохраняет факт, заменяя название нейтральным упоминанием аниме.

    Полные написания, пунктуация и русские падежи учитываются локально:
    дополнительный запрос к модели ради очистки не требуется.
    """
    out = str(explanation or "").strip()
    for pattern in _patterns(titles):
        quoted = rf"{_QUOTES}?{pattern}{_QUOTES}?"
        out = re.sub(rf"^\s*{quoted}\s*[—–:-]\s*", "", out,
                     flags=re.IGNORECASE)
        context = (rf"\b(?P<prep>в|из|по|для)\s+"
                   rf"(?:(?:аниме|сериал[ае]?|произведени[еяи]+|манг[аеи])\s+)?"
                   rf"{quoted}")
        out = re.sub(context, lambda match: _PREPOSITIONS[
            match.group("prep").casefold()], out, flags=re.IGNORECASE)
        out = re.sub(quoted, "это аниме", out, flags=re.IGNORECASE)
    out = " ".join(out.split()).strip(" ,;:—–-")
    if out.casefold().strip(".!?") == "это аниме":
        return ""
    return out[:1].upper() + out[1:]


def candidate_titles(candidate):
    """Все написания названия карточки, включая продолжения и синонимы."""
    anime = candidate.anime
    return [candidate.title_ru, anime.get("name"), anime.get("english"),
            anime.get("japanese")] + list(anime.get("synonyms") or [])
