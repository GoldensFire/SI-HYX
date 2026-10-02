# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Shikimori собирает карточки, пока внешние источники обновляют популярность."""
from concurrent.futures import ThreadPoolExecutor
import threading

from . import ru_popularity_refresh
from .ru_popularity_store import service


def refresh_database_sources(generator, wanted, catalogs, favorites):
    external = [source for source in ("remanga", "mangalib") if source in wanted]
    shiki = "manga" in wanted or "favorites" in wanted

    def primary():
        cards = catalogs(generator, wanted)
        if "favorites" in wanted and not generator.stopped():
            favorites(generator)
        return cards

    if not external or not any(part in wanted for part in ("anime", "manga", "favorites")):
        cards = primary()
        sources = external + (["shikimori"] if shiki else [])
        if sources and not generator.stopped():
            ru_popularity_refresh.refresh_ru_popularity(generator, sources=sources)
        return cards

    # Создаём единый сервис до рабочих потоков; Shikimori использует одну сессию.
    service(generator)
    halt = threading.Event()

    def stopped():
        return halt.is_set() or generator.stopped()

    generator.log("База: Shikimori, " + ", ".join(external)
                  + " обновляются параллельно.")
    with ThreadPoolExecutor(max_workers=len(external),
                            thread_name_prefix="db-source") as pool:
        futures = [pool.submit(ru_popularity_refresh.refresh_ru_popularity, generator,
                               sources=[source], stopped=stopped)
                   for source in external]
        try:
            cards = primary()
            if shiki and not stopped():
                ru_popularity_refresh.refresh_ru_popularity(generator, sources=["shikimori"])
            for future in futures:
                future.result()
            return cards
        finally:
            halt.set()
