# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Download a bounded page pool before spending Gemini requests on a title."""
from copy import copy
from concurrent.futures import ThreadPoolExecutor

from .early_repeat import reserve
from .generation_diagnostics import operation
from .manga_page_context import download
from .manga_scene_batch import crop_pages

PAGE_COUNT = 4


def note_wall(generator, exc) -> None:
    """Выключенный защитой от ботов источник называем в журнале один раз.

    Обычные отказы источников гасит _log_rare, а это — смена состава
    источников на весь прогон, её пользователь должен увидеть."""
    if not any(c.__name__ == "MangaSourceWalled" for c in type(exc).__mro__):
        return
    with generator._warn_lock:
        seen = generator.__dict__.setdefault("_manga_walls_logged", set())
        fresh = str(exc) not in seen
        seen.add(str(exc))
    if fresh:
        generator.log(str(exc) + ".")


def gemini_transient(exc) -> bool:
    """503/таймаут Gemini — беда минуты, а не тайтла: его стоит повторить."""
    return (isinstance(exc, (TimeoutError, ConnectionError))
            or any(c.__name__ == "GeminiUnavailableError" for c in type(exc).__mro__))


@operation("подготовка страницы")
def prepare(generator, cand, *, source_round=0):
    # Import at call time: manga_panel delegates to this module.
    import animepack as api
    from .manga_panel import _miss, _pick_page

    from .manga_page_downloads import PageDownloads
    from .manga_budget import check
    from .manga_page_reuse import take
    kept = take(generator, cand) if not source_round else None
    if kept and kept[0] == "pool":
        pages = kept[1]
        if not cand.source_link:
            cand.source_link = pages[0]["candidate"].source_link
        if not reserve(generator, cand):
            return None
        generator._log_rare("Повтор страниц манги",
                            f"«{cand.title_ru}»: беру скачанные в прошлой попытке страницы")
        return _choose(generator, cand, pages)
    pages, downloads, used, selections = [], PageDownloads(), set(), []
    for _ in range(PAGE_COUNT):
        if generator.stopped():
            return None
        check(generator, cand)
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
        selections.append((url, names, snapshot))

    def fetch(selection):
        url, names, snapshot = selection
        try:
            data, ext = download(generator, snapshot, url, cache=downloads)
        except Exception as exc:  # noqa: BLE001 — unavailable reader/CDN
            note_wall(generator, exc)
            generator._log_rare("Источники манги",
                                f"Страница «{cand.title_ru}» не скачалась: {exc}")
            return None
        return dict(data=data, ext=ext, url=url, titles=names, candidate=snapshot)

    with ThreadPoolExecutor(max_workers=2, thread_name_prefix="manga-pages") as pool:
        pages = [page for page in pool.map(fetch, selections) if page is not None]
    if not pages:
        if not used:
            _miss(generator, cand)
        elif source_round < 1 and not generator.stopped():
            # Parallel downloads report CDN denials only after the initial pool
            # was selected. Give the now-updated reader health one fallback pool.
            check(generator, cand)
            return prepare(generator, cand, source_round=source_round + 1)
        return None
    with generator._manga_lock:
        generator._mangadex_misses = 0
    return _choose(generator, cand, pages)


def _choose(generator, cand, pages):
    """Сцена из скачанного пула страниц: один запрос Gemini на весь пул."""
    import animepack as api
    from .manga_page_reuse import keep
    try:
        result = crop_pages(generator, cand, pages)
    except Exception as exc:  # noqa: BLE001 — preserve terminal service handling
        if (generator.gemini_manga is None or type(exc).__name__ in
                ("GeminiAuthError", "GeminiQuotaError", "GeminiDownError")):
            generator._drop_kind(api.MANGA_KIND, f"Gemini не выбрал сцену вебтуна: {exc}")
            cand.rejected = True
        elif gemini_transient(exc):
            # Редкую манхву/маньхуа не сжигаем из-за перегрузки: тайтл уйдёт
            # на повтор через минуту, как при сбое сети (selection_results),
            # и возьмёт эти же страницы, не выбирая и не скачивая новые.
            from .media_transfer import trouble_mark
            trouble_mark()
            if not generator.stopped():
                keep(generator, cand, ("pool", pages))
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
