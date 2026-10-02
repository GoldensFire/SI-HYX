# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Refresh all three manga sources and write an audit of the saved database."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import animepack as api
from si_hyx_parts.animepack.ru_popularity_math import SNAPSHOT_GROUP
from si_hyx_parts.animepack.ru_popularity_store import service
from si_hyx_parts.animepack.db_source_refresh import refresh_database_sources


def audit(cache, started, required_sources=("shikimori", "remanga", "mangalib")):
    snapshots = cache.memo_group(SNAPSHOT_GROUP)
    statuses = cache.memo_group("ru_population_refresh_status_v1")
    sources = {}
    for source in ("shikimori", "remanga", "mangalib"):
        row = snapshots.get(source) or {}
        groups = row.get("readership" if source == "shikimori" else "distributions") or {}
        sources[source] = {
            "complete": row.get("complete") is True,
            "timestamp": row.get("timestamp"),
            "fresh_this_run": row.get("timestamp", 0) >= started,
            "titles": len(row.get("titles") or []) if source != "shikimori"
            else sum(len(values) for values in groups.values()),
            "samples": {key: len(values) for key, values in groups.items()},
            "title_statuses": dict(Counter(title.get("status") for title in row.get("titles", []))),
            "refresh": statuses.get(source),
        }
    catalog_complete = any(complete for _, complete in cache.buckets("manga").values())
    return {"cache_path": cache.path, "started": started, "finished": time.time(),
            "catalog_counts": cache.part_counts(), "sources": sources,
            "catalog_complete": catalog_complete,
            "success": bool(cache.all_cards("manga")) and catalog_complete
            and all(row["complete"] and (source not in required_sources or row["fresh_this_run"])
                           and (row["refresh"] or {}).get("status") == "NORMAL"
                           for source, row in sources.items())}


def verify_generation(generator):
    """Use the same saved snapshots and evaluation path as candidate generation."""
    api.install_favorites_norms(generator.db_cache)
    current = service(generator)
    statuses = {source: Counter() for source in current.clients}
    boosts = Counter()
    examples = []
    cards = generator.db_cache.all_cards("manga")
    for card in cards:
        if card.get("kind") not in ("manga", "manhwa", "manhua"):
            continue
        favorites = generator.db_cache.memo("manga_favorites", str(card.get("id")), 0)
        candidate = api.SongCandidate({}, card, media="manga", favorites=
                                      favorites if favorites is not None else -1)
        result = current.evaluate(candidate, network=False)
        for source, observation in result.get("sources", {}).items():
            statuses[source][observation["status"]] += 1
        before, after = candidate.book_index, result.get("effective_book_index", candidate.book_index)
        if after > before:
            boosts[card["kind"]] += 1
            if len(examples) < 12:
                examples.append({"id": card.get("id"), "title": candidate.title_ru,
                                 "kind": card["kind"], "before": before, "after": after,
                                 "sources": result.get("sources")})
    generator.db_cache.save()
    return {"cards": len(cards), "matches": {key: dict(value) for key, value in statuses.items()},
            "boosts": dict(boosts), "examples": examples}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-path")
    parser.add_argument("--output-dir")
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--sources", nargs="+", choices=("shikimori", "remanga", "mangalib"),
                        default=["shikimori", "remanga", "mangalib"])
    args = parser.parse_args()
    started = time.time()
    cache = api.ShikimoriDbCache(args.cache_path)
    output = Path(args.output_dir or Path(api.CONFIG_DIR) / "manga_db_refresh" /
                  datetime.now().strftime("%Y%m%d-%H%M%S"))
    output.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def log(message):
        line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}"
        with lock:
            print(line, flush=True)
            with (output / "refresh.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")

    settings = api.PackSettings(pack_manga=True, pct_manga=100, pct_songs=0,
                                year_from=0, year_to=9999, score_from=0,
                                manga_gemini_check=False)
    generator = api.AnimePackGenerator(settings, db_cache=cache, log=log,
                                      should_stop=lambda: (output / "STOP").exists(),
                                      frames_history_path=str(output / "frames_used.json"))
    if args.verify_only:
        started = 0
    else:
        if Path(cache.path).exists():
            shutil.copy2(cache.path, output / "database-before.json.bak")
        log(f"Обновление {', '.join(args.sources)}; база: {cache.path}")
        def catalogs(current, wanted):
            if "manga" in wanted:
                current.fetch_full_catalog(manga=True, unfiltered=True)
            return current.db_cache.all_cards("manga")

        wanted = {"manga" if source == "shikimori" else source for source in args.sources}
        refresh_database_sources(generator, wanted,
                                 catalogs, lambda current: None)
    # Verify what survived on disk, including failed writes, rather than
    # accepting snapshots that exist only in the collector's memory.
    result = audit(api.ShikimoriDbCache(cache.path), started, args.sources)
    if result["success"]:
        log("Все три снимка сохранены. Проверяю локальный отбор по всей базе манги…")
        result["generation"] = verify_generation(generator)
    report = output / "audit.json"
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Результат: {result['success']}; отчёт: {report}")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
