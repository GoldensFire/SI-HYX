"""Generate up to ten real clips per isolated source and actual subtitle mode."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
import json
from pathlib import Path
import random
import shutil
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import animepack as api
from utils import load_settings
from episode_source_clients import Recorder, SourceKuhi, SourceRu, SOURCES
from si_hyx_parts.animepack.episode_suitability import Suitability
from si_hyx_parts.animepack.episode_generation import error_text


class ContextCache:
    """Keep AniZip lookups identical across sources, without persisting signed media."""
    def __init__(self):
        self.lock = threading.Lock()
        self.rows = {}
        self.locks = {}
        self.client = api.AniZipApi(api.make_session())

    def info(self, mal):
        with self.lock:
            guard = self.locks.setdefault(mal, threading.Lock())
        with guard:
            if mal not in self.rows:
                self.rows[mal] = self.client.info(mal)
            return self.rows[mal]


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def run_source(source, cards, args, raw, contexts, stop):
    folder = args.out / source
    folder.mkdir(exist_ok=True)
    lock = threading.Lock()

    def log(message):
        # Production logs redact source URLs; redact again at the artifact boundary.
        import re
        line = re.sub(r"https?://\S+", "[URL]", str(message))
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {source}: {line}"
        with lock:
            with (folder / "generation.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
        print(line, flush=True)

    def event(value):
        with lock:
            with (folder / "events.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(value, ensure_ascii=False) + "\n")

    recorder = Recorder(event)
    report_path = folder / "report.json"
    report = (json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists()
              else {"source": source, "target_per_mode": args.count, "modes": {}})
    started_source = time.monotonic()
    for mode in args.modes.split(","):
        if stop.is_set():
            report["cancelled"] = True
            break
        recorder.mode = mode
        mode_folder = folder / mode
        mode_folder.mkdir(exist_ok=True)
        settings = api.PackSettings(
            rounds=1, themes=2, questions=5, pct_songs=0,
            pack_episode=True, pct_episode=100, random_mode=True,
            random_source="shikimori", level_min=4, level_max=4, level_avg=4,
            episode_ru_subtitles=mode == "ru", mark_owners=False, parallel=2,
            video_preset=int(raw.get("animepack", {}).get("video_preset", 7)),
            video_crf=int(raw.get("animepack", {}).get("video_crf", 45)),
            generation_priority="normal", title=f"Проверка серий {source} {mode}",
            out_dir=str(mode_folder))
        settings.gemini_key = str(raw.get("api_keys", {}).get("gemini") or "")
        settings.animelib_token = str(raw.get("api_keys", {}).get("animelib") or "")
        # Keep the user's model selection for translations.
        for name in ("gemini_model", "gemini_thinking", "gemini_daily_limits"):
            if name in raw.get("animepack", {}):
                setattr(settings, name, raw["animepack"][name])
        safe = {key: value for key, value in settings.to_dict().items()
                if not any(term in key for term in ("key", "token", "credentials"))}
        write_json(mode_folder / "settings.json", safe)
        kuhi = SourceKuhi(source, recorder, stop.is_set, log)
        ru = SourceRu(source, recorder, stop.is_set, log)
        ru.no_ru = mode == "no_ru"
        gen = api.AnimePackGenerator(settings, log=log, should_stop=stop.is_set,
                                     rng=random.Random(args.seed), kuhi=kuhi, episode_ru=ru,
                                     anizip=contexts, db_cache=api.ShikimoriDbCache(
                                         str(mode_folder / "isolated-db.json")),
                                     frames_history_path=str(mode_folder / "frames-history.json"))
        gen._episode_suitability = Suitability(str(mode_folder / "suitability.json"))
        gen.prepare_dirs()
        selected, attempts, wrong_mode = [], [], []
        started = time.monotonic()
        before_found = recorder.found_catalogues
        mode_deadline = started + args.minutes * 60
        try:
            for index, card in enumerate(cards[:args.max_titles]):
                if stop.is_set() or time.monotonic() >= mode_deadline:
                    break
                cand = api.SongCandidate({}, card, kind=api.EPISODE_KIND)
                recorder.title = cand.mal_id
                if cand.level != 4:
                    raise ValueError(f"Cohort level changed: MAL {cand.mal_id}, {cand.level}")
                at = time.monotonic()
                log(f"{mode}: кандидат {index + 1}, «{cand.title_ru}», уровень {cand.level}.")
                made = gen.download_episode(cand)
                metadata = dict(cand.episode_clip) if made else {}
                correct = made and bool(metadata.get("ru_subtitles")) == (mode == "ru")
                row = {"mal": cand.mal_id, "title": cand.title_ru, "level": cand.level,
                       "year": cand.year, "generated": bool(made), "accepted": bool(correct),
                       "seconds": round(time.monotonic() - at, 3), "clip": metadata}
                attempts.append(row)
                if correct:
                    selected.append(cand)
                elif made:
                    rejected = mode_folder / "wrong-mode"
                    rejected.mkdir(exist_ok=True)
                    shutil.copy2(Path(gen.folder) / "Video" / cand.video_out,
                                 rejected / cand.video_out)
                    wrong_mode.append(row)
                    log(f"Неверный режим: запрос {mode}, фактический язык "
                        f"{metadata.get('subtitle_language') or 'не записан'}.")
                write_json(mode_folder / "attempts.json", attempts)
                if len(selected) >= args.count:
                    break
                # Ten fresh titles with no catalogue are sufficient evidence of
                # failure on this cohort, not evidence of universal source death.
                if index >= 9 and recorder.found_catalogues == before_found and mode == "ru":
                    log("В десяти тайтлах источник не дал ни одного каталога серий.")
                    break
                if mode == "no_ru" and index >= 9 and not selected:
                    # Retest more titles if any raw/non-RU result was generated.
                    prior_ru = report.get("modes", {}).get("ru", {})
                    demonstrated_video = prior_ru.get("made", 0) or prior_ru.get("wrong_mode", 0)
                    if not any(item["generated"] for item in attempts) and not demonstrated_video:
                        break
                if mode == "ru" and index >= 9 and len(wrong_mode) >= 10 and not selected:
                    log("Десять готовых роликов оказались EN вместо запрошенных RU.")
                    break
            package = ""
            if selected:
                # Use production prices, XML and transactional SIQ assembly.
                settings.rounds, settings.themes, settings.questions = 1, 1, len(selected)
                selected = api.assign_prices(selected, settings)
                package = gen.write_package(selected, str(mode_folder / f"{source}-{mode}.siq"))
            rows = [{"mal": c.mal_id, "title": c.title_ru, "level": c.level,
                     "year": c.year, "file": c.video_out, **c.episode_clip} for c in selected]
            result = {"made": len(selected), "requested": args.count, "attempted": len(attempts),
                      "wrong_mode": len(wrong_mode), "package": package, "questions": rows,
                      "average_level": sum(c.level for c in selected) / len(selected) if selected else None,
                      "elapsed_seconds": round(time.monotonic() - started, 3),
                      "deadline_reached": time.monotonic() >= mode_deadline}
            report["modes"][mode] = result
            write_json(mode_folder / "report.json", result)
            log(f"РЕЗУЛЬТАТ {mode}: {len(selected)}/{args.count}, попыток {len(attempts)}, "
                f"неверный язык {len(wrong_mode)}.")
        except Exception as error:
            report["modes"][mode] = {"error": error_text(error), "attempted": len(attempts)}
            log(f"ОШИБКА {mode}: {error_text(error)}")
        finally:
            gen.cleanup()
            write_json(folder / "report.json", report)
    report["elapsed_seconds"] = round(time.monotonic() - started_source, 3)
    report["fresh_catalogues"] = recorder.fresh_catalogues
    report["found_catalogues"] = recorder.found_catalogues
    write_json(folder / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--sources", default=",".join(SOURCES))
    parser.add_argument("--modes", default="ru,no_ru")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--max-titles", type=int, default=40)
    parser.add_argument("--minutes", type=int, default=35)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20261005)
    args = parser.parse_args()
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    cards = json.loads((args.out / "cohort.json").read_text(encoding="utf-8"))
    sources = args.sources.split(",")
    if any(source not in SOURCES for source in sources):
        parser.error("Unknown source")
    if any(mode not in ("ru", "no_ru") for mode in args.modes.split(",")):
        parser.error("Unknown mode")
    # Avoid reading the 400 MB catalogue when the frozen cohort already stays
    # at level four with the public candidate calculation.
    if any(api.SongCandidate({}, card, kind=api.EPISODE_KIND).level != 4 for card in cards):
        api.install_favorites_norms(api.ShikimoriDbCache())
    raw = load_settings()
    stop = threading.Event()
    contexts = ContextCache()
    previous = args.out / "summary.json"
    reports = ([row for row in json.loads(previous.read_text(encoding="utf-8"))["sources"]
                if row["source"] not in sources] if previous.exists() else [])
    started = time.monotonic()
    import signal
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    with ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="Source audit") as pool:
        jobs = {pool.submit(run_source, name, cards, args, raw, contexts, stop): name
                for name in sources}
        for job in as_completed(jobs):
            try:
                reports.append(job.result())
            except Exception as error:
                reports.append({"source": jobs[job], "error": error_text(error)})
            write_json(args.out / "summary.json", {
                "requested_per_source_per_mode": args.count, "sources": reports,
                "elapsed_seconds": round(time.monotonic() - started, 3)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
