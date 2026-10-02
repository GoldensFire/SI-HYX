# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Catalog sweeps run on database refresh, never on question generation."""
import time
from concurrent.futures import ThreadPoolExecutor

from .ru_popularity_math import KINDS, SNAPSHOT_GROUP
from .ru_popularity_store import service
from .ru_catalog_snapshot import external_snapshot
from .catalog_pages import iter_catalog_pages


def shikimori_snapshot(generator, config, stopped=None):
    import animepack as api
    stopped = stopped or generator.stopped
    raw = {kind: [] for kind in KINDS}
    books = {kind: [] for kind in KINDS}
    favorites = generator.db_cache.memo_group("manga_favorites")
    seen = set()
    # Independent unfiltered census; its smaller selection fits 15 pages/request.
    for page, rows in iter_catalog_pages(
            generator.shikimori, config.max_catalog_pages, stopped,
            manga=True, population=True, limit=50, order="id", kinds=KINDS):
        if stopped():
            return None
        if not rows:
            return {"version": 1, "source": "shikimori", "timestamp": time.time(),
                    "complete": True, "readership": {k: sorted(v) for k, v in raw.items()},
                    "book_index": {k: sorted(v) for k, v in books.items()},
                    "scope": "unfiltered_censored_manga_manhwa_manhua",
                    "favorites": "current_cached_favorites; unknown values use existing factor"}
        for card in rows:
            ident, kind = str(card.get("id") or ""), card.get("kind")
            if not ident or ident in seen:
                raise ValueError("Shikimori census repeated/missing id")
            seen.add(ident)
            if kind not in KINDS or not isinstance(card.get("statusesStats"), list):
                raise ValueError("Shikimori census schema changed")
            candidate = api.SongCandidate({}, card, media="manga",
                                          favorites=favorites.get(ident, -1))
            raw[kind].append(candidate.own_base)
            books[kind].append(candidate.book_index)
        if page % 20 == 0:
            generator.log(f"RU popularity: Shikimori, {len(seen)} тайтлов…")
    if stopped():
        return None
    raise ValueError("Shikimori census incomplete; previous snapshot retained")


def refresh_ru_popularity(generator, sources=None, *, stopped=None):
    """Независимые источники обновляются одновременно, каждый со своей квотой."""
    available = ("remanga", "mangalib", "shikimori")
    if isinstance(sources, str):
        sources = (sources,)
    selected = set(available if sources is None else sources)
    if selected - set(available):
        raise ValueError("unknown popularity source")
    current = service(generator)
    stopped = stopped or generator.stopped
    if "shikimori" in selected:
        import animepack as api
        api.install_favorites_norms(generator.db_cache)
    ordered = [source for source in available if source in selected]
    if not ordered or stopped():
        return
    if len(ordered) == 1:
        _refresh_source(generator, current, ordered[0], stopped)
        return
    generator.log("RU popularity: источники обновляются параллельно: "
                  + ", ".join(ordered) + ".")
    with ThreadPoolExecutor(max_workers=len(ordered),
                            thread_name_prefix="ru-source") as pool:
        futures = [pool.submit(_refresh_source, generator, current, source, stopped)
                   for source in ordered]
        for future in futures:
            future.result()


def _refresh_source(generator, current, source, stopped):
    if stopped():
        return
    generator.log(f"RU popularity: обновляю распределения {source}…")
    if source == "remanga":
        generator.log("ReManga: каталог по 40 тайтлов со счётчиком закладок; "
                      "детали запрашиваются только при недостающих полях.")
    elif source == "mangalib":
        generator.log("MangaLib: каталог по 60 тайтлов с числом голосов rating.votes; "
                      "детали запрашиваются только при недостающей метрике. "
                      f"Кэш деталей — {current.config.normal_ttl / 86400:g} дней; "
                      "«Остановить» сохранит набранное для продолжения.")
    try:
        snapshot = (shikimori_snapshot(generator, current.config, stopped)
                    if source == "shikimori" else external_snapshot(
                        current.clients[source], current.config, stopped,
                        generator.db_cache, generator.log))
        if snapshot is not None and not stopped():
            generator.db_cache.remember_memo(SNAPSHOT_GROUP, source, snapshot)
            with current._lock:
                current.snapshots[source] = snapshot
                current._observations.clear()
                current._disabled.discard(source)
            generator.db_cache.remember_memo("ru_population_refresh_status_v1", source,
                {"status": "NORMAL", "timestamp": time.time()})
            generator.log(f"RU popularity: snapshot {source} сохранён.")
    except Exception as exc:
        if not stopped():
            generator.log(f"RU popularity: {source}: {exc}; прежний snapshot сохранён.")
            generator.db_cache.remember_memo("ru_population_refresh_status_v1", source,
                {"status": "ERROR", "timestamp": time.time(), "reason": str(exc)})
    finally:
        generator.db_cache.save()
