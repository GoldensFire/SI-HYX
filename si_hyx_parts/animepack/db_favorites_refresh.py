"""Refresh favorite counters with explicit access states and fresh-value reuse."""
import time

ACCESS_GROUP = "favorites_access_status_v1"
NORMAL_TTL = 7 * 86400
FAILURE_TTLS = {"AGE_RESTRICTED": 7 * 86400, "NOT_FOUND": 86400,
                "ACCESS_DENIED": 3600, "RATE_LIMITED": 300, "ERROR": 3600}


def anonymous(client):
    session = getattr(client, "session", None)
    if session is None:
        return True
    if getattr(session, "headers", {}).get("Authorization"):
        return False
    cookies = getattr(session, "cookies", ())
    return not any("shikimori" in str(getattr(cookie, "domain", "")) for cookie in cookies)


def preflight(generator, ids, target, access):
    getter = getattr(generator.shikimori, "title_censorship_flags", None)
    if not callable(getter) or not anonymous(generator.shikimori):
        return
    pending = [ident for ident in ids if not _recent(access.get(f"{target}:{ident}"))]
    if not pending:
        return
    generator.log(f"Доступ {target}: пакетно проверяю {len(pending)} тайтлов…")
    try:
        flags = getter(pending, target, stopped=generator.stopped)
    except Exception as exc:
        generator.log(f"Признаки доступа не получены: {exc}; проверю страницы отдельно.")
        return
    for ident, flag in flags.items():
        if flag:
            entry = {"status": "AGE_RESTRICTED", "checked": time.time(),
                     "source": "public_graphql_isCensored", "reason": "Требуется вход 18+"}
            key = f"{target}:{ident}"
            access[key] = entry
            generator.db_cache.remember_memo(ACCESS_GROUP, key, entry)


def _recent(entry):
    if not isinstance(entry, dict):
        return False
    ttl = FAILURE_TTLS.get(entry.get("status"), 0)
    return bool(ttl and time.time() - float(entry.get("checked") or 0) < ttl)


def _read(generator, ident, target, url):
    getter = getattr(generator.shikimori, "title_favorites_result", None)
    if callable(getter):
        return getter(ident, target, url)
    getter = getattr(generator.shikimori, "title_favorites", None)
    if not callable(getter):
        return {"status": "ERROR", "reason": "Источник не поддерживает избранное", "value": -1}
    try:
        try:
            value = int(getter(ident, target, url))
        except TypeError:
            value = int(getter(ident, target))
        return {"status": "NORMAL" if value >= 0 else "ERROR", "value": value}
    except Exception as exc:
        return {"status": "ERROR", "value": -1, "reason": str(exc)}


def refresh_favorites(generator):
    import animepack as api
    cache = generator.db_cache
    access = cache.memo_group(ACCESS_GROUP)
    anonymous_access = anonymous(generator.shikimori)
    report = generator._favorites_refresh_report = {}
    for target in ("anime", "manga"):
        if generator.stopped():
            break
        cards = cache.all_cards(target)
        ids = api.favorites_targets(cards, target == "manga")
        entries = cache.memo_entries(f"{target}_favorites")
        now = time.time()
        valid = {key for key, row in entries.items()
                 if isinstance(row.get("value"), (int, float)) and row["value"] >= 0
                 and now - float(row.get("fetched") or 0) < NORMAL_TTL}
        need = [ident for ident in ids if str(ident) not in valid]
        preflight(generator, need, target, access)
        urls = {int(card.get("id") or 0): str(card.get("url") or "") for card in cards}
        summary = report[target] = {"targets": len(ids), "reused": len(ids) - len(need),
                                    "received": 0, "restricted": 0, "failed": 0}
        saved = time.monotonic()
        for number, ident in enumerate(need, 1):
            if generator.stopped():
                break
            key = f"{target}:{ident}"
            previous = access.get(key)
            reuse = _recent(previous)
            if previous and previous.get("status") == "AGE_RESTRICTED" and not anonymous_access:
                reuse = False
            result = previous if reuse else _read(generator, ident, target, urls.get(ident, ""))
            result = {**result, "checked": result.get("checked", time.time())}
            if result.get("status") == "NORMAL" and result.get("value", -1) >= 0:
                cache.remember_memo(f"{target}_favorites", ident, int(result["value"]))
                summary["received"] += 1
            else:
                summary["restricted" if result.get("status") == "AGE_RESTRICTED" else "failed"] += 1
            if not reuse:
                access[key] = result
                cache.remember_memo(ACCESS_GROUP, key, result)
            if number % 50 == 0:
                generator.log(f"Избранное {target}: проверено {number} из {len(need)}; "
                              f"получено {summary['received']}, доступ ограничен {summary['restricted']}, "
                              f"неизвестно {summary['failed']}.")
            if time.monotonic() - saved >= 60:
                cache.save()
                saved = time.monotonic()
        cache.save()
        generator.log(f"Избранное {target}: получено {summary['received']}, "
                      f"доступ ограничен {summary['restricted']}, неизвестно {summary['failed']}.")
