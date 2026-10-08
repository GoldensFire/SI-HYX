# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Ordered catalog traversal shared by refresh and the unfiltered census."""
import animepack_api as _api
from si_hyx_parts.animepack_api.shikimori_catalog import page_batch_size


def iter_catalog_pages(client, max_pages, stopped, *, manga=False,
                       population=False, start_page=1, **filters):
    fetch_batch = getattr(client, "catalog_pages", None)
    for name in ("kinds", "genres", "genres_exclude", "studios"):
        if name in filters:
            filters[name] = tuple(filters[name])
    page = max(1, int(start_page))
    while page <= max_pages and not stopped():
        if callable(fetch_batch):
            count = min(page_batch_size(client, manga, population), max_pages - page + 1)
            groups = fetch_batch(page, manga=manga, population=population,
                                 pages=count, **filters)
            if not isinstance(groups, list) or not 1 <= len(groups) <= count:
                raise _api.AnimePackApiError("Shikimori: неполная пачка страниц каталога.")
        else:  # Public compatibility with older injected clients.
            fetch = client.random_mangas if manga else client.random_animes
            groups = [fetch(page, **filters)]
        # Process every already received page; Stop prevents the next request.
        for rows in groups:
            if not isinstance(rows, list):
                raise _api.AnimePackApiError("Shikimori: некорректная страница каталога.")
            yield page, rows
            if not rows:
                return
            page += 1
