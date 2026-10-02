# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Полный внешний каталог, детали из кэша и прогресс возобновляемого обхода."""
import time

from .ru_popularity_math import KINDS
from .ru_catalog_details import CatalogDetails, DETAIL_GROUP
from .catalog_checkpoint import CatalogCheckpoint

SAVE_SECONDS = 60
PROGRESS_SECONDS = 30


def _snapshot(client, config, titles):
    distributions = {kind: [] for kind in (*KINDS, "all_types")}
    fallback = any(not row["kind"] for row in titles)
    for row in titles:
        if row["status"] != "NORMAL" or row["raw_metric"] is None:
            continue
        group = "all_types" if fallback else row["kind"]
        if group in distributions:
            distributions[group].append(row["raw_metric"])
    distributions = {k: sorted(v) for k, v in distributions.items()
                     if len(v) >= config.min_samples}
    if not distributions:
        raise ValueError("complete catalog has too few reliable population samples")
    return {"version": 1, "source": client.source, "metric": client.metric,
            "timestamp": time.time(), "complete": True, "titles": titles,
            "distributions": distributions,
            "type_fallback": ("complete_site_catalog_types_unresolved" if fallback else "")}


def external_snapshot(client, config, stopped, cache, progress=None):
    titles, seen = [], set()
    checkpoint = CatalogCheckpoint(cache)
    details, cached, catalog_ready, excluded = 0, 0, 0, 0
    catalog_requests = 0
    started = last_log = last_saved = time.monotonic()
    save_interval = max(SAVE_SECONDS, getattr(client, "checkpoint_interval", SAVE_SECONDS))

    def report(page, *, force=False):
        nonlocal last_log
        now = time.monotonic()
        if progress and (force or now - last_log >= PROGRESS_SECONDS):
            diagnostics = getattr(getattr(client, "limiter", None), "diagnostics", None)
            extra = ""
            if callable(diagnostics):
                state = diagnostics()
                errors = ", ".join(f"HTTP {code}: {count}" for code, count in
                                   sorted(state["retry_responses"].items()))
                if state["transport_errors"]:
                    errors += f", сеть: {state['transport_errors']}"
                extra = (f"; API: {state['requests']} запросов, "
                         f"темп {state['per_second']:.2f}/с; "
                         f"временные сбои: {errors.strip(', ') or 'нет'}")
            progress(f"RU popularity: {client.source}, страница {page}, "
                     f"{len(titles)} тайтлов; каталог: {catalog_requests} запросов, "
                     f"{catalog_ready} готовых карточек; детали: {details} запросов, "
                     f"{cached} из кэша; другие типы: {excluded}; "
                     f"прошло {(now - started) / 60:.1f} мин.{extra}")
            last_log = now

    def count(requested, hit):
        nonlocal details, cached, last_saved
        details += requested
        cached += hit
        if (requested and time.monotonic() - last_saved >= save_interval
                and checkpoint.schedule()):
            last_saved = time.monotonic()

    def page_loaded():
        nonlocal catalog_requests
        catalog_requests += 1

    def accepted(row, requested, hit):
        nonlocal catalog_ready, excluded
        count(requested, hit)
        if row["kind"] == "other":
            excluded += 1
        else:
            titles.append(row)
            catalog_ready += int(not requested and not hit)

    try:
        with CatalogDetails(client, cache, config.normal_ttl, stopped) as loader:
            return _collect(client, config, stopped, loader, titles, seen,
                            report, page_loaded, accepted)
    finally:
        # Включая прерванную первую страницу; распределение публикуется отдельно.
        checkpoint.close()


def _collect(client, config, stopped, loader, titles, seen, report, page_loaded, accepted):
    for page in range(1, config.max_catalog_pages + 1):
        if stopped():
            return None
        rows = client.catalog_page(page)
        page_loaded()
        if stopped():
            return None
        if not rows:
            result = _snapshot(client, config, titles)
            report(page, force=True)
            return None if stopped() else result
        eligible = []
        for row in rows:
            if row["id"] in seen:
                raise ValueError("catalog pagination repeated an id; snapshot discarded")
            seen.add(row["id"])
            if row["kind"] == "other":
                accepted(row, 0, 0)
                continue
            eligible.append(row)
        for row, requested, hit in loader.rows(eligible, idle=lambda: report(page)):
            accepted(row, requested, hit)
            report(page)
        if stopped():
            return None
        report(page, force=(page == 1))
    raise ValueError("catalog page limit reached; incomplete snapshot discarded")
