# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Maximum-size, ordered catalog requests within Shikimori's query budget."""
import animepack_api as _api


PAGE_LIMIT = 50
# Only these fields enter SongCandidate.own_base and book_index in the census.
POPULATION_FIELDS = """
    id kind score status airedOn { year } releasedOn { year }
    statusesStats { status count }
"""


def catalog_args(pattern, page, *, limit=PAGE_LIMIT, season="", kinds=(),
                 score=0, genres=(), genres_exclude=(), studios=(), order="random"):
    """The same filters for single-page sampling and ordered bulk refresh."""
    args = [f"page: {max(1, int(page))}",
            f"limit: {max(1, min(PAGE_LIMIT, int(limit)))}",
            f"order: {pattern.sub('', str(order or 'random')) or 'random'}",
            "censored: true"]
    if season:
        args.append(f'season: "{pattern.sub("", str(season))}"')
    kinds = [pattern.sub("", str(kind)) for kind in kinds]
    kinds = [kind for kind in kinds if kind]
    if kinds:
        args.append(f'kind: "{",".join(kinds)}"')
    if score and int(score) > 0:
        args.append(f"score: {int(score)}")
    gen = [str(int(genre)) for genre in genres]
    gen += [f"!{int(genre)}" for genre in genres_exclude]
    if gen:
        args.append(f'genre: "{",".join(gen)}"')
    studio_ids = []
    for studio in studios:
        try:
            ident = int(studio)
        except (TypeError, ValueError):
            continue
        if ident:
            studio_ids.append(str(ident))
    if studio_ids:
        args.append(f'studio: "{",".join(studio_ids)}"')
    return ", ".join(args)


def page_batch_size(client, manga=False, population=False):
    if population:
        return int(getattr(client, "CATALOG_POPULATION_PAGES", 15))
    name = "CATALOG_MANGA_PAGES" if manga else "CATALOG_ANIME_PAGES"
    return int(getattr(client, name, 4 if manga else 2))
