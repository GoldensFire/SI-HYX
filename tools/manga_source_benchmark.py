"""Compare source searches at 2/4/8 workers on the same cached comic cards."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import animepack as ap
from config import SETTINGS_FILE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--count", type=int, default=8)
    args = parser.parse_args()
    settings = ap.PackSettings.from_dict(json.loads(args.profile.read_text(encoding="utf-8")))
    saved = json.loads(Path(SETTINGS_FILE).read_text(encoding="utf-8"))
    settings.gemini_key = str(saved.get("api_keys", {}).get("gemini") or "")
    generator = ap.AnimePackGenerator(settings, rng=random.Random(7), log=lambda _: None)
    cache = generator.db_cache
    # This also commits the recoverable memo migration once, before timing searches.
    cache.remember_memo("generation_upgrade_v1", "comic_pipeline", {"version": 1})
    cache.save()
    pairs = generator.collect_manga_ids()
    cards = []
    for ident, _ in pairs:
        card = generator._manga_cache[ident]
        if ap.filter_anime(card, settings, manga=True):
            cards.append(card)
        if len(cards) == args.count:
            break
    results = []
    for workers in (2, 4, 8):
        source = ap.MangaPageSources(sources=settings.manga_sources,
                                    language=settings.manga_lang, rng=random.Random(7))
        started = time.monotonic()
        def search(card):
            before = time.monotonic()
            selection = source.select_page(card)
            return {"mal": card["malId"], "title": card.get("name"),
                    "found": bool(selection.url), "seconds": time.monotonic() - before,
                    "errors": list(selection.errors)}
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                rows = list(pool.map(search, cards))
        finally:
            source.close()
        elapsed = time.monotonic() - started
        result = {"workers": workers, "seconds": elapsed,
                  "found": sum(row["found"] for row in rows), "rows": rows}
        results.append(result)
        print(json.dumps({k: v for k, v in result.items() if k != "rows"}), flush=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps({"stage": "source_search", "same_card_ids":
            [c["malId"] for c in cards], "cases": results}, ensure_ascii=False, indent=2),
            encoding="utf-8")
    generator.cleanup()


if __name__ == "__main__":
    main()
