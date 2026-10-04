"""Replace one verified song, then render and audit every video with the current style."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import argparse
import json
from pathlib import Path
import random
import shutil
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke_pack_probe import verify_package
from si_hyx_parts.animepack.catalog_superset import cached_catalog
from si_hyx_parts.animepack.song_downloads import close, prefetch


def rebuild(args):
    source = args.input
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    profile = json.loads((source / "settings.json").read_text(encoding="utf-8"))
    settings = ap.PackSettings.from_dict(profile)
    settings.title = f"Аниме · {settings.total_questions} песен · средняя {settings.song_level_avg}"
    candidates = [ap.SongCandidate(**row) for row in json.loads(
        (source / "candidates.json").read_text(encoding="utf-8"))]
    old = next(c for c in candidates if c.song_name == args.replace_song)
    songs = json.loads(args.catalog.read_text(encoding="utf-8"))
    row = next(row for row in songs if row["songName"] == args.replacement
               and int((row.get("linked_ids") or {}).get("myanimelist") or 0) == args.replacement_mal)
    ap.FFMPEG = shutil.which("ffmpeg") or ap.FFMPEG
    ap.FFPROBE = shutil.which("ffprobe") or ap.FFPROBE
    def log(message):
        print(message, flush=True)
    generator = ap.AnimePackGenerator(settings, log=log, rng=random.Random(89))
    ap.install_favorites_norms(generator.db_cache)
    cards, _ = cached_catalog(generator.db_cache, "anime", ap.shiki_cache_signature(settings, False))
    generator._card_cache.update({int(card.get("malId") or card["id"]): card for card in cards})
    anime = generator._animes_by_ids([args.replacement_mal])[0]
    generator._load_franchise_indexes([anime])
    replacement = ap.SongCandidate(row, anime, kind=old.kind, music_effect="karaoke",
                                    trim_start=30, franchise_index=generator._franchise_index(anime),
                                    compress_images=settings.compress_images,
                                    compress_audio=settings.compress_audio)
    replacement.favorites = generator._title_favorites(replacement)
    replacement.media_base = generator._media_base(replacement)
    candidates[candidates.index(old)] = replacement
    log("Уровни: " + ", ".join(f"{c.song_name}={c.level}" for c in candidates))
    if sum(c.level for c in candidates) != settings.song_level_avg * len(candidates):
        raise ValueError("Замена не даёт требуемую точную среднюю.")
    started = time.monotonic()
    generator.prepare_dirs()
    try:
        for candidate in candidates:
            prefetch(generator, candidate)
        def render_song(candidate):
            if not generator.download_audio(candidate):
                raise ValueError(f"Не удалось пересобрать {candidate.song_name}")
            generator.download_images(candidate)
            if not candidate.has_poster:
                raise ValueError(f"Нет постера: {candidate.song_name}")
            return candidate
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix="karaoke-rebuild") as pool:
            jobs = {pool.submit(render_song, c): c for c in candidates}
            for number, future in enumerate(as_completed(jobs), 1):
                candidate = future.result()
                print(f"READY {number}/{len(candidates)}: {candidate.song_name}", flush=True)
        if sum(c.level for c in candidates) != settings.song_level_avg * len(candidates):
            raise ValueError("Фактическая средняя изменилась после подготовки медиа.")
        name = f"Аниме-Песни-{len(candidates)}-Средняя-{settings.song_level_avg}.siq"
        path = generator.write_package(candidates, str(output / name))
        report = verify_package(path, ap.FFPROBE, generator._run_capture, expected=len(candidates),
                                require_authored=not settings.karaoke_ai_fallback)
        rows = [{"song": c.song_name, "anime": c.title_ru, "level": c.level,
                 "mal": c.mal_id, "kind": c.kind, "file": c.video_out,
                 "highlight": c.karaoke["highlight_colour"]} for c in candidates]
        summary = {"package": path, "made": len(candidates), "target_average": settings.song_level_avg,
                   "actual_average": sum(c.level for c in candidates) / len(candidates),
                   "generation_seconds": time.monotonic() - started,
                   "settings": settings.to_dict(), "questions": rows, "verification": report}
        for filename, data in (("verification.json", summary), ("candidates.json", [asdict(c) for c in candidates]),
                               ("settings.json", settings.to_dict())):
            (output / filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"COMPLETE {len(candidates)} songs; average {summary['actual_average']:.2f}; {path}", flush=True)
    finally:
        close(generator)
        generator.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--replace-song", required=True)
    parser.add_argument("--replacement", required=True)
    parser.add_argument("--replacement-mal", type=int, required=True)
    rebuild(parser.parse_args())


if __name__ == "__main__":
    main()
