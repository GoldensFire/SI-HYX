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


def catalog_pages(self, page=1, *, manga=False, population=False, pages=None,
                  order="id", **filters):
    """Return consecutive pages in one HTTP request, preserving page boundaries.

    Verified 2026-10-01: complete anime/manga pages cost 67/47 each; the
    population-only selection costs 12. The server allows complexity <=190.
    A lower server budget is remembered for this client after a rejection.
    """
    if population and not manga:
        raise ValueError("population census requires manga")
    page = max(1, int(page))
    root = "mangas" if manga else "animes"
    fields = (POPULATION_FIELDS if population else
              self.MANGA_FIELDS if manga else self.ANIME_FIELDS)
    maximum = page_batch_size(self, manga, population)
    sizes = getattr(self, "_catalog_page_sizes", None)
    if sizes is None:
        sizes = self._catalog_page_sizes = {}
    key = (manga, population)
    count = max(1, min(int(pages or maximum), maximum, sizes.get(key, maximum)))
    # Iterable filters must be reusable for every alias and any budget retry.
    filters = dict(filters)
    for name in ("kinds", "genres", "genres_exclude", "studios"):
        if name in filters:
            filters[name] = tuple(filters[name])
    while True:
        selections = []
        for offset in range(count):
            args = catalog_args(self._RE_ARG, page + offset,
                                order=order, **filters)
            selections.append(f"p{offset}: {root}({args}) {{ {fields} }}")
        self.limiter.acquire()
        try:
            data = self.client._graphql("query {\n" + "\n".join(selections) + "\n}", {})
        except Exception as exc:
            message = str(exc).lower()
            if count > 1 and "complexity" in message and "exceeds" in message:
                count -= 1
                sizes[key] = count
                continue
            raise _api._friendly(exc, "Shikimori") from exc
        result = []
        for offset in range(count):
            rows = data.get(f"p{offset}") if isinstance(data, dict) else None
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise _api.AnimePackApiError("Shikimori: некорректная страница каталога.")
            result.append(rows)
        return result
