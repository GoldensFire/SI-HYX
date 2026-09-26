"""Resolve title riddles to the main first entry before checking their text."""
from copy import copy
import re

from .title_kinds import TITLE_KINDS

TITLE_QUESTION_KINDS = TITLE_KINDS + ("anagram",)
MAX_TITLE_LENGTH = 40
_SEASON = re.compile(
    r"\b(?:season|сезон|part|часть)\s*(?:[2-9]\d*|ii|iii|iv|v)\b|"
    r"\b[2-9]\d*(?:nd|rd|th)?\s*(?:season|сезон|part|часть)\b|"
    r"\b(?:ii|iii|iv|v)\s*$|\bfinal\s+season\b", re.I)


def short_title(card):
    title = " ".join(str(card.get("russian") or "").split())
    return bool(title) and len(title) <= MAX_TITLE_LENGTH


def first_title(generator, original):
    cache = getattr(generator, "_first_title_cards", None)
    if cache is None:
        cache = generator._first_title_cards = {}
    card = original
    visited = []
    result = None
    for _ in range(30):
        if generator.stopped():
            return None
        ident = str(card.get("id") or card.get("malId") or "")
        if ident in visited:
            break
        if ident and ident in cache:
            result = cache[ident]
            break
        if ident:
            visited.append(ident)
        related = card.get("related")
        if not isinstance(related, list) and card.get("kind"):
            # Refresh old catalog entries that predate relationship metadata.
            card = load_card(generator, ident)
            if card is None:
                break
            related = card.get("related")
            if not isinstance(related, list):
                break
        parents = [row["anime"] for row in (related or [])
                   if isinstance(row, dict) and isinstance(row.get("anime"), dict)
                   and row.get("relationKind") in ("prequel", "parent_story", "full_story")]
        if not parents:
            if card.get("kind") and card["kind"] not in ("tv", "ona", "ova", "movie"):
                break
            # Numbered seasons with incomplete links must not slip through.
            if not any(_SEASON.search(str(card.get(key) or ""))
                       for key in ("russian", "english", "name")):
                result = card
            break
        parents.sort(key=lambda row: (row.get("kind") not in ("tv", "ona"),
                                      str(row.get("id") or "")))
        card = load_card(generator, parents[0].get("id"))
        if card is None:
            break
    for ident in visited:
        cache[ident] = result
    return result


def load_card(generator, ident):
    cache = getattr(generator, "_first_title_cards", {})
    if str(ident) in cache:
        return cache[str(ident)]
    try:
        rows = generator.shikimori.animes_by_ids([int(ident)])
        return next((row for row in rows if isinstance(row, dict)
                     and str(row.get("id")) == str(ident)), None)
    except (AttributeError, TypeError, ValueError):
        return None
    except Exception as exc:  # noqa: BLE001 — do not substitute an unverified sequel
        generator.log(f"Первая часть для загадки не загрузилась: {exc}")
        return None


def prepare_variant(generator, cand):
    if cand.is_manga:
        return None
    card = first_title(generator, cand.anime)
    if card is None or not short_title(card):
        return None
    variant = copy(cand)
    variant.anime = card
    return variant
