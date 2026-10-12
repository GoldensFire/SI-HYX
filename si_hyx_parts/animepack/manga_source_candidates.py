# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Prefer exact local reader matches without changing catalog filters."""
from .ru_popularity_store import RuPopularityStore
from si_hyx_parts.animepack_api.manga_reader_base import clean_sources
from si_hyx_parts.animepack_api.ru_title_matching import match_title

READERS = ("remanga", "mangalib")


def _verdict(store, source, snapshot, card) -> str:
    """«ok», «adult» или «» — есть ли книга в сохранённом каталоге источника."""
    status, row = match_title(card, store.candidates(source, card, snapshot))
    if status != "NORMAL" or row is None or row.get("status") != "NORMAL":
        return ""
    fields = row.get("fields") or {}
    if fields.get("is_licensed") is not False or fields.get("is_forbidden") is True:
        return ""
    adult = fields.get("is_erotic") is True or fields.get("is_yaoi") is True
    age = fields.get("ageRestriction") or {}
    adult |= isinstance(age, dict) and str(age.get("label", "")).startswith("18")
    return "adult" if adult else "ok"


def _snapshots(generator, selected):
    store = RuPopularityStore(generator.db_cache, {}, persist=False)
    snapshots = {key: store._snapshot(key) for key in selected}
    return store, {key: row for key, row in snapshots.items() if row}


def reader_matches(generator, cards) -> dict:
    """{источник: {"ok": id, "adult": id}} по всем карточкам — для заготовки."""
    store, snapshots = _snapshots(generator, READERS)
    found = {}
    for source, snapshot in snapshots.items():
        sets = found[source] = {"ok": set(), "adult": set()}
        for ident, card in cards.items():
            verdict = _verdict(store, source, snapshot, card)
            if verdict:
                sets[verdict].add(ident)
    return found


def prefer_reader_matches(generator, ids):
    """Keep random order within matched and remaining titles; never fetch."""
    generator._manga_catalog_matches = 0
    language = str(getattr(generator.s, "manga_lang", "") or "")
    if language and language != "ru":
        return ids
    enabled = clean_sources(getattr(generator.s, "manga_sources", None))
    selected = [key for key in READERS if enabled[key]]
    if not selected:
        return ids
    allow_adult = bool(getattr(generator.s, "manga_allow_erotica", False))
    verdicts = {"ok", "adult"} if allow_adult else {"ok"}
    from .catalog_levels import load
    readers = (load(generator) or {}).get("readers") or {}
    if all(key in readers for key in selected):
        # Сопоставление заготовлено при «Обновить базу» (catalog_levels).
        allowed = set().union(*(readers[key][v] for key in selected for v in verdicts))
        matched = [ident in allowed for ident in ids]
    else:
        store, snapshots = _snapshots(generator, selected)
        if not snapshots:
            return ids
        matched = [any(_verdict(store, source, snapshot, generator._manga_cache[ident])
                       in verdicts for source, snapshot in snapshots.items())
                   for ident in ids]
    preferred = [ident for ident, found in zip(ids, matched) if found]
    remaining = [ident for ident, found in zip(ids, matched) if not found]
    generator._manga_catalog_matches = len(preferred)
    if preferred:
        generator.log(f"Манга: в сохранённых каталогах выбранных источников "
                      f"сопоставлено {len(preferred)} тайтлов — проверяю их первыми.")
    return preferred + remaining
