"""Generate and verify a real pack using the normal selector and song average."""
from __future__ import annotations

import argparse
from collections import Counter
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
    parser.add_argument("--minimum", type=int, default=1)
    parser.add_argument("--maximum", type=int, default=15)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--seed", type=int, default=37)
    parser.add_argument("--crf", type=int, default=ap.VIDEO_CRF)
    parser.add_argument("--preset", type=int, default=10)
    parser.add_argument("--catalog", type=Path, help="Use an existing AnisongDB snapshot as input")
    parser.add_argument("--candidates", type=Path, nargs="+",
                        help="Revalidate known songs and select an exact balanced recipe")
    parser.add_argument("--resume", type=Path, help="Reuse questions from a previous output directory")
    parser.add_argument("--no-ai-fallback", action="store_true", help="Require existing lyric timings")
    parser.add_argument("--untimed-lyrics-only", action="store_true",
                        help="Exclude all authored timing providers and their verified caches")
    parser.add_argument("--resolver-cache", type=Path,
                        help="Reuse HTTP and AI cache from another untimed diagnostic run")
    parser.add_argument('--cold-cache', action='store_true',
                        help='Require an empty local AI cache and download source media afresh')
    parser.add_argument("--reuse-confirmed-run", type=Path,
                        help="Copy acoustically confirmed checkpoints into an exact recipe")
    parser.add_argument("--separator", choices=("auto", "kim", "htdemucs"), default="auto")
    parser.add_argument("--ai-timeout", type=int, default=300)
    parser.add_argument("--allow-title-repeats", action="store_true",
                        help="Allow distinct songs from the same anime or franchise")
    parser.add_argument("--song-mix", type=int, nargs=3, metavar=("OP", "ED", "OST"),
                        help="Relative proportions of opening, ending and insert songs")
    parser.add_argument("--confirmed-excerpts", type=int, choices=range(5, 31), metavar="SECONDS",
                        help="Accept uninterrupted acoustically confirmed lyric excerpts")
    args = parser.parse_args()
    if args.count < 1 or not 1 <= args.average <= 15:
        parser.error("Нужны положительный размер пака и средняя сложность 1–15.")
    if not 1 <= args.minimum <= args.average <= args.maximum <= 15:
        parser.error("Средняя должна находиться внутри диапазона сложности 1–15.")
    if args.resume and not args.catalog:
        parser.error("Для возобновления нужен --catalog, чтобы исключить уже готовые песни.")
    if args.untimed_lyrics_only and (args.no_ai_fallback or args.resume):
        parser.error("Тест обычной лирики требует AI и нового пака без --resume.")
    if args.confirmed_excerpts and not args.untimed_lyrics_only:
        parser.error("Подтверждённые фрагменты используются только с --untimed-lyrics-only.")
    if args.reuse_confirmed_run and not (args.untimed_lyrics_only and args.confirmed_excerpts and args.candidates):
        parser.error("Перенос подтверждённых роликов требует обычной лирики, фрагментов и точного состава.")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.cold_cache and (args.resolver_cache or args.resume or args.reuse_confirmed_run
                           or (output / 'resolver-cache').exists()):
        parser.error('Cold measurement requires a new output and no reused cache/checkpoints.')
    settings = ap.PackSettings(
        title=f"Аниме · {args.count} песен · средняя {args.average}",
        rounds=3 if args.count == 48 else 1,
        themes=4 if args.count == 48 else 3 if args.count == 12 else 1,
        questions=4 if args.count in (12, 48) else args.count,
        song_level_avg=args.average, song_level_min=args.minimum, song_level_max=args.maximum,
        level_avg=0, pct_songs=100, random_source="shikimori",
        karaoke_enabled=True, karaoke_percent=100, karaoke_translations=False,
        karaoke_ai_fallback=not args.no_ai_fallback, karaoke_crf=args.crf, karaoke_preset=args.preset,
        karaoke_separator=args.separator, karaoke_ai_timeout=args.ai_timeout,
        dup_anime=args.allow_title_repeats or bool(args.candidates),
        dup_franchise=args.allow_title_repeats or bool(args.candidates),
        audio_cut=args.confirmed_excerpts or 20, images=False,
        parallel=args.parallel, sort_by_index=False)
    if args.song_mix:
        if min(args.song_mix) < 0 or not sum(args.song_mix):
            parser.error("Доли песен должны быть неотрицательными, хотя бы одна положительная.")
        settings.openings, settings.endings, settings.inserts = args.song_mix
        settings.pick_openings, settings.pick_endings, settings.pick_inserts = map(bool, args.song_mix)
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
                                      rng=random.Random(args.seed),
                                      should_stop=lambda: (output / "stop.request").exists())
    if args.cold_cache:
        settings.poster_cache = False
        generator._cached_bytes = lambda url, namespace, minimum=1: generator._get_bytes(url)
        log('Холодный замер: старые исходники, вокал, ASR и готовые ролики не используются; веса установлены.')
    if args.untimed_lyrics_only:
        from karaoke.resolver import Resolver
        generator.karaoke_resolver = Resolver(generator.session, settings, ap.FFMPEG,
            generator._run_killable, stopped=generator.stopped, log=log,
            cache=args.resolver_cache or output / "resolver-cache",
            timed=generator._timed, authored_sources=False,
            excerpt_duration=args.confirmed_excerpts or 0)
        log("Тест обычной лирики: Mugen, AMLL, PetitLyrics и их кэши таймингов исключены.")
        if args.reuse_confirmed_run:
            from karaoke_checkpoint_reuse import install as install_reuse
            install_reuse(generator, args.reuse_confirmed_run, args.confirmed_excerpts)
        from karaoke_checkpoints import install as install_checkpoints
        install_checkpoints(generator, output)
    previous = []
    if args.resume:
        from karaoke_resume import load, install
        previous, previous_package = load(args.resume)
        install(generator, previous, previous_package, args.count)
        log(f"Сохраняю {len(previous)} готовых вопросов из предыдущего прогона.")
    original_write = generator.write_package
    def save_candidates(songs, out_path=None):
        (output / "candidates.json").write_text(json.dumps([asdict(c) for c in songs],
                                                          ensure_ascii=False, indent=2), encoding="utf-8")
        return original_write(songs, out_path)
    generator.write_package = save_candidates
    if args.catalog:
        songs = json.loads(args.catalog.read_text(encoding="utf-8"))
        used = {(c.song_name.casefold(), c.artist.casefold()) for c in previous}
        songs = [row for row in songs if (str(row.get("songName") or "").casefold(),
                 str(row.get("songArtist") or "").casefold()) not in used]
        ids = sorted({int((song.get("linked_ids") or {}).get("myanimelist") or 0)
                      for song in songs} - {0})
        generator.rng.shuffle(ids)
        generator.collect_anime_ids = lambda: [(mal, []) for mal in ids]
        generator.anisong.songs_by_mal_ids = lambda wanted: [
            row for row in songs if (row.get("linked_ids") or {}).get("myanimelist") in wanted]
        log(f"AnisongDB snapshot: {len(ids)} аниме, {len(songs)} песен.")
    if args.candidates:
        from karaoke_recipe import install as install_recipe
        install_recipe(generator, args.candidates)
    started = time.monotonic()
    try:
        result = generator.run(str(output / f"Аниме-Песни-{args.count}-Средняя-{args.average}.siq"))
    finally:
        from karaoke_profile import save as save_profile
        save_profile(generator, output, started)
        (output / "source-audit.json").write_text(json.dumps(generator.karaoke_resolver.audit.snapshot(),
                                                ensure_ascii=False, indent=2), encoding="utf-8")
    rows = [{"song": c.song_name, "anime": c.title_ru, "level": c.level,
             "mal": c.mal_id, "kind": c.base_kind, "file": c.video_out,
             "source": c.karaoke.get("source"), "ai_used": c.karaoke.get("ai_used"),
             "highlight": c.karaoke.get("highlight_colour")} for c in result.songs]
    actual = sum(row["level"] for row in rows) / len(rows) if rows else 0
    summary = {"package": result.path, "requested": args.count, "made": len(rows),
               "untimed_lyrics_only": args.untimed_lyrics_only,
               "reused_confirmed_run": str(args.reuse_confirmed_run) if args.reuse_confirmed_run else None,
               "confirmed_excerpts_seconds": args.confirmed_excerpts,
               "target_average": args.average, "actual_average": actual,
               "generation_seconds": time.monotonic() - started,
               'cold_cache': args.cold_cache,
               "source_counts": dict(Counter(row["source"] for row in rows)),
               "settings": settings.to_dict(), "questions": rows}
    (output / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if len(rows) != args.count:
        raise RuntimeError(f"Получилось {len(rows)} из {args.count}; см. generation.log.")
    if args.candidates and sum(row["level"] for row in rows) != args.count * args.average:
        raise RuntimeError("Точный состав не сохранил запрошенную среднюю сложность.")
    verification_started = time.monotonic()
    summary["verification"] = verify_package(result.path, ap.FFPROBE, generator._run_capture,
                                              expected=args.count, require_authored=args.no_ai_fallback)
    if args.untimed_lyrics_only and args.confirmed_excerpts:
        from karaoke_confirmed_verify import verify
        summary["confirmed_clips"] = verify(result.path, count=args.count,
                                              duration=args.confirmed_excerpts)
    summary['verification_seconds'] = time.monotonic() - verification_started
    summary['total_seconds_with_verification'] = time.monotonic() - started
    (output / "verification.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Готово: {len(rows)} песен, средняя сложность {actual:.2f}; {result.path}")


if __name__ == "__main__":
    main()
