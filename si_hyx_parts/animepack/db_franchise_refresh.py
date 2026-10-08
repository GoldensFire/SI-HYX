"""Measured franchise refresh with retries and bounded checkpoints."""
import time


def refresh_franchises(generator, cards):
    import animepack as api
    representatives = {}
    for card in cards:
        key = str(card.get("franchise") or "").strip()
        if key:
            representatives.setdefault(key, card)
    generator.db_cache.clear_part("franchises")
    generator._fr_index.clear()
    generator._fr_parts.clear()
    pending = list(representatives)
    previous = getattr(generator, "_defer_cache_writes", False)
    generator._defer_cache_writes = True
    saved = time.monotonic()
    try:
        for attempt in range(1, 4):
            retry = []
            for keys in api._chunks(pending, int(getattr(generator.shikimori, "FRANCHISE_BATCH", 13))):
                if generator.stopped():
                    return
                generator._load_franchise_indexes([representatives[key] for key in keys])
                retry.extend(key for key in keys if key not in generator._fr_parts)
                generator.log(f"Франшизы: получено {len(generator._fr_parts)} "
                              f"из {len(representatives)}; попытка {attempt}.")
                if time.monotonic() - saved >= 60:
                    generator.db_cache.save()
                    saved = time.monotonic()
            pending = retry
            if not pending:
                break
    finally:
        generator._defer_cache_writes = previous
        generator._franchise_refresh_missing = pending
        generator.db_cache.save()
