"""Generate a small real SIQ using the normal selection/media/package pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import random
import signal
import sys
import threading
import time
from datetime import datetime

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import animepack as api


class EpisodeProbe(api.AnimePackGenerator):
    def iter_candidates(self):
        yield from self.probe_candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids", default="1,1535,5114,16498,52991",
                        help="Existing Shikimori/MAL IDs, resolved to AniList through AniZip")
    parser.add_argument("--out", default=str(ROOT / "artifacts" / "episode-live-check"))
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--current-settings", action="store_true",
                        help="Use the user's saved settings and normal random selection, unchanged")
    args = parser.parse_args()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    settings = api.PackSettings(rounds=1, themes=1, questions=args.count,
                                pct_songs=0, pack_episode=True, pct_episode=100,
                                random_mode=True, random_source="shikimori", level_min=1, level_max=15,
                                mark_owners=False, parallel=2, video_preset=12,
                                title="Проверка отрывков серий", out_dir=str(out))
    generator_type = EpisodeProbe
    if args.current_settings:
        from utils import load_settings
        saved = load_settings()
        settings = api.PackSettings.from_dict(saved.get("animepack") or {})
        for field, key in (("gemini_key", "gemini"), ("jimaku_key", "jimaku"),
                           ("subdl_key", "subdl"), ("animelib_token", "animelib")):
            setattr(settings, field, str((saved.get("api_keys") or {}).get(key) or ""))
        if settings.total_questions != args.count:
            parser.error(f"Saved settings request {settings.total_questions} questions, --count is {args.count}")
        generator_type = api.AnimePackGenerator
    snapshot = {k: v for k, v in settings.to_dict().items()
                if not any(word in k for word in ("key", "token", "credentials"))}
    (out / "settings.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    logs = []
    log_lock = threading.Lock()
    log_path = out / "generation.log"
    log_path.write_text("", encoding="utf-8")

    def log(message):
        message = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        with log_lock:
            logs.append(str(message))
            with log_path.open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
            print(message, flush=True)

    generator = generator_type(settings, log=log, should_stop=stop.is_set,
                             rng=random.Random(20261001))
    report = {"requested": args.count, "questions": [], "path": ""}
    started = time.monotonic()
    try:
        if not args.current_settings:
            ids = [int(value) for value in args.ids.split(",") if value.strip()]
            cards = generator.shikimori.animes_by_ids(ids)
            generator.probe_candidates = [api.SongCandidate({}, card, kind=api.EPISODE_KIND)
                                          for card in cards]
        log(f"Проверка RU-sub / Kuhi ≥1080p: цель — {args.count} вопросов по 15 с.")
        result = generator.run(str(out / "episode-scenes.siq"))
        report["path"] = result.path
        report["questions"] = [{"title": c.title_ru, **c.episode_clip} for c in result.songs]
    except Exception as error:
        report["error"] = str(error)
        log(f"Проверка: {error}")
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        generator.cleanup()
        (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
    return 0 if len(report["questions"]) >= args.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
