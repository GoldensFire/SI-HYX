# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Run a real manga pack with saved settings and retain its frames for review."""
import argparse
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont
import animepack as ap
from config import SETTINGS_FILE


class Probe(ap.AnimePackGenerator):
    def prepare_dirs(self):
        super().prepare_dirs()
        from manga_prepared import restore
        self.resume_candidates = restore(self, getattr(self, "resume_roots", ()))

    def iter_candidates(self):
        ready = getattr(self, "resume_candidates", ())
        used = {candidate.mal_id for candidate in ready}
        yield from ready
        for candidate in super().iter_candidates():
            if candidate.mal_id not in used:
                yield candidate

    def _fetch_media(self, candidate):
        started = time.monotonic()
        failure = None
        try:
            good = super()._fetch_media(candidate)
        except Exception as error:
            good, failure = False, error
        if good and candidate.has_frame:
            shutil.copy2(Path(self.folder) / "Images" / candidate.frame_name,
                         self.audit_dir / "frames" / candidate.frame_name)
            from manga_prepared import capture
            capture(self, candidate)
        row = {"title": candidate.title_ru, "good": good,
               "level": candidate.level, "frame": candidate.frame_name,
               "kind": candidate.anime.get("kind"),
               "seconds": time.monotonic() - started,
               "error": str(failure) if failure else "",
               "context": getattr(candidate, "_manga_context_urls", [])}
        with self.audit_lock:
            with (self.audit_dir / "attempts.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if failure is not None:
            raise failure
        return good


def contact_sheets(rows, output):
    font_path = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/arial.ttf"
    font = ImageFont.truetype(str(font_path), 16)
    for start in range(0, len(rows), 12):
        selected = rows[start:start + 12]
        sheet = Image.new("RGB", (1200, 1400), (22, 24, 35))
        draw = ImageDraw.Draw(sheet)
        for index, row in enumerate(selected):
            left, top = index % 4 * 300, index // 4 * 460
            with Image.open(output / "frames" / row["frame"]) as opened:
                picture = opened.convert("RGB")
            picture.thumbnail((280, 405), Image.Resampling.LANCZOS)
            sheet.paste(picture, (left + (300 - picture.width) // 2, top + 10))
            label = f"{start + index + 1}. {row['title']}"
            draw.text((left + 8, top + 420), label[:32], font=font, fill="white")
            draw.text((left + 8, top + 442), f"уровень {row['level']}", font=font,
                      fill=(170, 190, 210))
        sheet.save(output / f"contact-{start // 12 + 1}.jpg", quality=94)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--settings", default=SETTINGS_FILE)
    parser.add_argument("--profile", help="Reuse a redacted pack settings snapshot")
    parser.add_argument("--output", required=True)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--minutes", type=int, default=45)
    parser.add_argument("--priority", choices=("low", "normal", "high"),
                        help="Override priority for this diagnostic run only")
    parser.add_argument("--parallel", type=int,
                        help="Override concurrency for this diagnostic run only")
    parser.add_argument("--count", type=int,
                        help="Use one theme with this many diagnostic questions")
    parser.add_argument("--exclude-pack", action="append", default=[],
                        help="Exclude titles and franchises already in this pack")
    parser.add_argument("--frames-history", help="Use a continuation-specific frame history")
    parser.add_argument("--reuse-pack", action="append", default=[],
                        help="Reuse prepared resources from an earlier attempt of this pack")
    parser.add_argument("--no-average-target", action="store_true",
                        help="Ignore average difficulty when filling a diagnostic pack")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "frames").mkdir(exist_ok=True)
    raw = json.loads(Path(args.settings).read_text(encoding="utf-8"))
    profile = (json.loads(Path(args.profile).read_text(encoding="utf-8"))
               if args.profile else raw["animepack"])
    settings = ap.PackSettings.from_dict(profile)
    if settings.only_kind != ap.MANGA_KIND:
        parser.error("This probe requires a manga-only settings profile")
    if args.priority:
        settings.generation_priority = args.priority
    if args.parallel is not None:
        if not 1 <= args.parallel <= 16:
            parser.error("--parallel must be between 1 and 16")
        settings.parallel = args.parallel
    if args.count is not None:
        if args.count < 1:
            parser.error("--count must be positive")
        settings.rounds, settings.themes, settings.questions = 1, 1, args.count
    settings.exclude_siq = list(settings.exclude_siq) + args.exclude_pack
    if args.exclude_pack:
        # Explicit diagnostic exclusions also apply to test-named packs.
        settings.ignore_test_packs = False
    if args.no_average_target:
        settings.level_avg = settings.manga_level_avg = 0
    settings.gemini_key = str(raw.get("api_keys", {}).get("gemini") or settings.gemini_key)
    stop = threading.Event()
    timer = threading.Timer(args.minutes * 60, stop.set)
    timer.daemon = True
    timer.start()
    log_lock = threading.Lock()

    def log(message):
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        with log_lock:
            with (output / "generation.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            print(line, flush=True)

    from manga_probe_progress import callback
    generator = Probe(settings, log=log, progress=callback(output, lambda: generator, log),
                      frames_history_path=args.frames_history or ap.FRAMES_HISTORY_FILE,
                      should_stop=lambda: stop.is_set() or (output / "stop").exists(),
                      rng=random.Random(args.seed))
    generator.audit_dir = output
    generator.audit_lock = threading.Lock()
    generator.resume_roots = args.reuse_pack
    scene_client = generator.gemini_manga
    safe = {key: value for key, value in settings.to_dict().items()
            if not any(part in key.lower() for part in ("key", "token", "cookie", "secret"))}
    (output / "settings.json").write_text(
        json.dumps(safe, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        name = ap.safe_filename(settings.title, "Комиксы")
        result = generator.run(str(output / f"{name}.siq"))
        rows = [{"title": c.title_ru, "mal": c.mal_id, "level": c.level,
                 "kind": c.anime.get("kind"), "frame": c.frame_name,
                 "shikimori": str(c.anime.get("id") or ""),
                 "franchise_keys": list(getattr(c, "_reserved", ()) or ()),
                 "page": c.frame_url, "chapter": c.source_link}
                for c in result.songs]
        report = {"requested": result.requested, "made": len(rows),
                  "cancelled": result.cancelled, "seconds": result.elapsed,
                  "pack": result.path, "questions": rows}
        report["selection_plan"] = getattr(generator, "_manga_plan_stats", {})
        if scene_client is not None:
            report["gemini"] = {
                "http_attempts": sum(scene_client.spent.values()),
                "by_model": dict(scene_client.spent),
                "responses": dict(scene_client.response_codes)}
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        contact_sheets(rows, output)
        log(f"PROBE COMPLETE: {len(rows)}/{result.requested}; {result.path}")
        return 0 if len(rows) == result.requested and not result.cancelled else 2
    finally:
        timer.cancel()


if __name__ == "__main__":
    raise SystemExit(main())
