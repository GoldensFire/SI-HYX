# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Download a bounded page pool before spending Gemini requests on a title."""
from copy import copy

from .early_repeat import reserve
from .generation_diagnostics import operation
from .manga_page_context import download
from .manga_scene_batch import crop_pages

PAGE_COUNT = 4


@operation("подготовка страницы")
def prepare(generator, cand):
    # Import at call time: manga_panel delegates to this module.
    import animepack as api
    from .manga_panel import _miss, _pick_page

    pages, downloads, used = [], {}, set()
    for _ in range(PAGE_COUNT):
        if generator.stopped():
            return None
        try:
            url, chapter, names = _pick_page(generator, cand)
        except api.AnimePackApiError as exc:
            generator._log_rare("Источники манги", f"Манга «{cand.title_ru}»: {exc}")
            continue
        if not url:
            break
        if url in used:
            continue
        used.add(url)
        if not cand.source_link:
            cand.source_link = api.mangadex_chapter_link(chapter)
        if not reserve(generator, cand):
            return None
        snapshot = copy(cand)
        try:
            data, ext = download(generator, snapshot, url, cache=downloads)
        except Exception as exc:  # noqa: BLE001 — unavailable reader/CDN
            generator._log_rare("Источники манги",
                                f"Страница «{cand.title_ru}» не скачалась: {exc}")
            continue
        pages.append(dict(data=data, ext=ext, url=url, titles=names,
                          candidate=snapshot))
    if not pages:
        if not used:
            _miss(generator, cand)
        return None
    with generator._manga_lock:
        generator._mangadex_misses = 0
    try:
        result = crop_pages(generator, cand, pages)
    except Exception as exc:  # noqa: BLE001 — preserve terminal service handling
        if (generator.gemini_manga is None or type(exc).__name__ in
                ("GeminiAuthError", "GeminiQuotaError", "GeminiDownError")):
            generator._drop_kind(api.MANGA_KIND)
            cand.rejected = True
        generator._log_rare("Выбор сцены Gemini",
                            f"Не удалось выбрать сцену с персонажами: {exc}")
        return None
    if result is None:
        return None
    index, encoded = result
    page = pages[index]
    selected = page["candidate"]
    for name in ("source_link", "_manga_page_client", "_manga_page_info",
                 "_manga_context_urls"):
        setattr(cand, name, getattr(selected, name))
    if not reserve(generator, cand):
        return None
    return page["url"], (*encoded, True), page["titles"]
