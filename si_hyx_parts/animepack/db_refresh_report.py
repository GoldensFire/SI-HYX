"""Evidence-based completion of each independently requested database section."""
import time


def finish_report(generator, wanted, started):
    import animepack as api
    from .db_settings import database_settings
    from .ru_popularity_math import SNAPSHOT_GROUP
    cache = generator.db_cache
    failures = [f"{target}: {message}" for target, message in
                getattr(generator, "_catalog_refresh_errors", {}).items() if target in wanted]
    catalogs = {}
    for target in ("anime", "manga"):
        if target in wanted:
            signature = api.shiki_cache_signature(database_settings(), target == "manga")
            complete = cache.is_complete(target, signature)
            catalogs[target] = {"complete": complete, "count": len(cache.all_cards(target))}
            if not complete:
                failures.append(f"{target}: полный каталог не завершён")
    sources = [name for name in ("remanga", "mangalib") if name in wanted]
    if "manga" in wanted or "favorites" in wanted:
        sources.append("shikimori")
    for name in sources:
        snapshot = cache.memo(SNAPSHOT_GROUP, name) or {}
        status = cache.memo("ru_population_refresh_status_v1", name) or {}
        fetched = snapshot.get("catalog_timestamp", snapshot.get("timestamp", 0))
        if (snapshot.get("complete") is not True or fetched < started
                or status.get("status") != "NORMAL" or status.get("timestamp", 0) < started):
            failures.append(f"{name}: {status.get('reason', 'нет свежего полного снимка')}")
    missing = getattr(generator, "_franchise_refresh_missing", []) if "franchises" in wanted else []
    if missing:
        failures.append(f"Франшизы: не получено {len(missing)} ответов")
    favorites = getattr(generator, "_favorites_refresh_report", {}) if "favorites" in wanted else {}
    restricted = sum(row.get("restricted", 0) for row in favorites.values())
    unknown = sum(row.get("failed", 0) for row in favorites.values())
    stopped = generator.stopped()
    status = ("STOPPED" if stopped else "ERROR" if failures else
              "PARTIAL" if restricted or unknown else "COMPLETE")
    report = {"status": status, "started": started, "finished": time.time(),
              "saved": True,
              "parts": list(wanted), "catalogs": catalogs, "favorites": favorites,
              "restricted": restricted, "unknown": unknown,
              "missing_franchises": missing, "failures": failures}
    generator._db_refresh_report = report
    cache.remember_memo("db_refresh_report_v1", "latest", report)
    report["saved"] = bool(cache.save())
    if not report["saved"]:
        report["status"] = "ERROR"
        report["failures"].append("Не удалось сохранить результат обновления на диск")
        cache.remember_memo("db_refresh_report_v1", "latest", report)
        cache.save()
    return report
