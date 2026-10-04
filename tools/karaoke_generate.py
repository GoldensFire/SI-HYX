"""Generate and verify a real pack using the normal selector and song average."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import random
import shutil
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke_pack_probe import verify_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=12)
    parser.add_argument("--average", type=int, default=4)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--crf", type=int, default=ap.VIDEO_CRF)
    parser.add_argument("--preset", type=int, default=10)
    parser.add_argument("--catalog", type=Path, help="Use an existing AnisongDB snapshot as input")
    parser.add_argument("--no-ai-fallback", action="store_true", help="Require authored ASS/TTML only")
    parser.add_argument("--allow-title-repeats", action="store_true",
                        help="Allow distinct songs from the same anime or franchise")
    args = parser.parse_args()
    if args.count < 1 or not 1 <= args.average <= 15:
        parser.error("Нужны положительный размер пака и средняя сложность 1–15.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    settings = ap.PackSettings(
        title=f"Аниме · {args.count} песен · средняя {args.average}",
        rounds=1, themes=3 if args.count == 12 else 1,
        questions=4 if args.count == 12 else args.count,
        song_level_avg=args.average, song_level_min=1, song_level_max=15,
        level_avg=0, pct_songs=100, random_source="shikimori",
        karaoke_enabled=True, karaoke_percent=100, karaoke_translations=False,
        karaoke_ai_fallback=not args.no_ai_fallback, karaoke_crf=args.crf, karaoke_preset=args.preset,
        dup_anime=args.allow_title_repeats, dup_franchise=args.allow_title_repeats,
        audio_cut=20, images=False, parallel=args.parallel, sort_by_index=False)
    problems = settings.validate()
    if problems:
        parser.error("; ".join(problems))
    (output / "settings.json").write_text(json.dumps(settings.to_dict(), ensure_ascii=False,
                                                     indent=2), encoding="utf-8")
    ap.FFMPEG = shutil.which("ffmpeg") or ap.FFMPEG
    ap.FFPROBE = shutil.which("ffprobe") or ap.FFPROBE
    lock = threading.Lock()

    def log(message):
        with lock:
            with (output / "generation.log").open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
            print(message, flush=True)

    def progress(done, total, label):
        (output / "progress.json").write_text(json.dumps(
            {"ready": done, "total": total, "status": label}, ensure_ascii=False), encoding="utf-8")

    generator = ap.AnimePackGenerator(settings, log=log, progress=progress,
                                      rng=random.Random(args.seed))
    original_write = generator.write_package
    def save_candidates(songs, out_path=None):
        (output / "candidates.json").write_text(json.dumps([asdict(c) for c in songs],
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
        return original_write(songs, out_path)
    generator.write_package = save_candidates
    if args.catalog:
        songs = json.loads(args.catalog.read_text(encoding="utf-8"))
        ids = sorted({int((song.get("linked_ids") or {}).get("myanimelist") or 0)
                      for song in songs} - {0})
        generator.rng.shuffle(ids)
        generator.collect_anime_ids = lambda: [(mal, []) for mal in ids]
        generator.anisong.songs_by_mal_ids = lambda wanted: [
            row for row in songs if (row.get("linked_ids") or {}).get("myanimelist") in wanted]
        log(f"AnisongDB snapshot: {len(ids)} аниме, {len(songs)} песен.")
    started = time.monotonic()
    result = generator.run(str(output / f"Аниме-Песни-{args.count}-Средняя-{args.average}.siq"))
    rows = [{"song": c.song_name, "anime": c.title_ru, "level": c.level,
             "mal": c.mal_id, "kind": c.base_kind, "file": c.video_out,
             "highlight": c.karaoke.get("highlight_colour")} for c in result.songs]
    actual = sum(row["level"] for row in rows) / len(rows) if rows else 0
    summary = {"package": result.path, "requested": args.count, "made": len(rows),
               "target_average": args.average, "actual_average": actual,
               "generation_seconds": time.monotonic() - started,
               "settings": settings.to_dict(), "questions": rows}
    (output / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if len(rows) != args.count:
        raise RuntimeError(f"Получилось {len(rows)} из {args.count}; см. generation.log.")
    summary["verification"] = verify_package(result.path, ap.FFPROBE, generator._run_capture,
                                              expected=args.count, require_authored=args.no_ai_fallback)
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Готово: {len(rows)} песен, средняя сложность {actual:.2f}; {result.path}")


if __name__ == "__main__":
    main()
