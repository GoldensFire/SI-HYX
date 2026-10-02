# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Prefer exact local reader matches without changing catalog filters."""
from .ru_popularity_store import RuPopularityStore
from si_hyx_parts.animepack_api.manga_reader_base import clean_sources
from si_hyx_parts.animepack_api.ru_title_matching import match_title


def prefer_reader_matches(generator, ids):
    """Keep random order within matched and remaining titles; never fetch."""
    generator._manga_catalog_matches = 0
    language = str(getattr(generator.s, "manga_lang", "") or "")
    if language and language != "ru":
        return ids
    enabled = clean_sources(getattr(generator.s, "manga_sources", None))
    selected = [key for key in ("remanga", "mangalib") if enabled[key]]
    if not selected:
        return ids
    store = RuPopularityStore(generator.db_cache, {}, persist=False)
    snapshots = {key: store._snapshot(key) for key in selected}
    snapshots = {key: row for key, row in snapshots.items() if row}
    if not snapshots:
        return ids
    allow_adult = bool(getattr(generator.s, "manga_allow_erotica", False))
    preferred, remaining = [], []
    for ident in ids:
        card = generator._manga_cache[ident]
        found = False
        for source, snapshot in snapshots.items():
            status, row = match_title(card, store.candidates(source, card, snapshot))
            if status != "NORMAL" or row is None or row.get("status") != "NORMAL":
                continue
            fields = row.get("fields") or {}
            restricted = (fields.get("is_licensed") is not False
                          or fields.get("is_forbidden") is True)
            adult = fields.get("is_erotic") is True or fields.get("is_yaoi") is True
            age = fields.get("ageRestriction") or {}
            adult |= isinstance(age, dict) and str(age.get("label", "")).startswith("18")
            if not restricted and (allow_adult or not adult):
                found = True
                break
        (preferred if found else remaining).append(ident)
    generator._manga_catalog_matches = len(preferred)
    if preferred:
        generator.log(f"Манга: в сохранённых каталогах выбранных источников "
                      f"сопоставлено {len(preferred)} тайтлов — проверяю их первыми.")
    return preferred + remaining
