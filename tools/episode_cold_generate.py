"""Generate a real episode pack from cold source memory and record timings."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import random
import shutil
import signal
import sys
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import animepack as api
from si_hyx_parts.animepack.episode_suitability import Suitability
from si_hyx_parts.animepack.episode_generation import error_text
from utils import load_settings


def pinned(value, saved):
    return saved if value is None else value


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--exclude-report", type=Path, action="append", default=[])
    parser.add_argument("--exclude-id", type=int, action="append", default=[])
    parser.add_argument("--gemini-model")
    parser.add_argument("--local-check", action="store_true")
    parser.add_argument("--tv-only", action="store_true")
    parser.add_argument("--seed", type=int, default=20261007)
    # Pin the conditions of an earlier run; omitted values come from saved settings.
    for name in ("level-min", "level-max", "level-avg", "parallel", "video-preset", "video-crf"):
        parser.add_argument("--" + name, type=int)
    args = parser.parse_args()
    out = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        parser.error("Use a new empty output directory for a cold generation.")
    out.mkdir(parents=True, exist_ok=True)
    saved = load_settings()
    previous = api.PackSettings.from_dict(saved.get("animepack") or {})
    settings = api.PackSettings(
        rounds=2 if args.count == 100 else 1,
        themes=10 if args.count == 100 else 1,
        questions=5 if args.count == 100 else args.count,
        pct_songs=0, pack_episode=True, pct_episode=100,
        random_mode=True, random_source="shikimori",
        level_min=pinned(args.level_min, previous.level_min),
        level_max=pinned(args.level_max, previous.level_max),
        level_avg=pinned(args.level_avg, previous.level_avg),
        episode_ru_subtitles=True, episode_subtitle_mode="required",
        episode_scene_check=not args.local_check, mark_owners=False,
        parallel=pinned(args.parallel, previous.parallel),
        video_preset=pinned(args.video_preset, previous.video_preset),
        video_crf=pinned(args.video_crf, previous.video_crf), generation_priority="normal",
        gemini_model=args.gemini_model or previous.gemini_model,
        gemini_thinking=previous.gemini_thinking,
        title="Отрывки аниме с русскими субтитрами — 100 видео",
        out_dir=str(out))
    keys = saved.get("api_keys") or {}
    if args.tv_only:
        settings.kinds = {kind: kind == "tv" for kind in settings.kinds}
    settings.gemini_key = str(keys.get("gemini") or "")
    settings.animelib_token = str(keys.get("animelib") or "")
    snapshot = {k: v for k, v in settings.to_dict().items()
                if not any(word in k for word in ("key", "token", "credentials"))}
    (out / "settings.json").write_text(
        json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    stop = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    lock = threading.Lock()
    local = threading.local()
    started = time.monotonic()
    attempts, source_calls, process_errors, warnings = [], [], [], []

    def log(message):
        line = f"[{datetime.now().isoformat(timespec='seconds')}] {message}"
        with lock:
            with (out / "console.log").open("a", encoding="utf-8") as stream:
                stream.write(line + "\n")
            print(line, flush=True)

    def record(filename, row, collection):
        with lock:
            collection.append(row)
            with (out / filename).open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")

    generator = api.AnimePackGenerator(settings, log=log,
        should_stop=lambda: stop.is_set() or (out / "STOP").exists(),
        rng=random.Random(args.seed))
    excluded = set(args.exclude_id)
    for excluded_report in args.exclude_report:
        previous_report = json.loads(excluded_report.read_text(encoding="utf-8"))
        excluded.update(row["mal_id"] for row in previous_report.get("questions", []))
    if excluded:
        original_candidates = generator.iter_candidates

        def candidates():
            for candidate in original_candidates():
                if candidate.mal_id not in excluded:
                    yield candidate

        generator.iter_candidates = candidates
    generator._episode_suitability = Suitability(str(out / "source-memory.json"))
    local_check = None
    if args.local_check:
        from tools.episode_local_check import LocalSceneCheck
        local_check = LocalSceneCheck(generator, out / "local-validation")
        generator.gemini = None
        generator.gemini_episode = None
    original_download = generator.download_episode

    def download(candidate):
        at = time.monotonic()
        local.title = candidate.mal_id
        success = False
        error = ""
        try:
            success = original_download(candidate)
            if success and local_check is not None:
                success = local_check.check(candidate)
            return success
        except Exception as exc:
            error = error_text(exc)
            raise
        finally:
            row = {"mal_id": candidate.mal_id, "title": candidate.title_ru,
                   "started_seconds": round(at - started, 3),
                   "seconds": round(time.monotonic() - at, 3),
                   "success": bool(success), "clip": candidate.episode_clip or {}}
            if error:
                row["error"] = error
            record("attempts.jsonl", row, attempts)
            local.title = None

    generator.download_episode = download
    original_capture = generator._run_capture

    def capture(command, *args, **kwargs):
        code, output, error = original_capture(command, *args, **kwargs)
        if code:
            record("process-errors.jsonl", {
                "program": Path(command[0]).name, "code": code,
                "seconds_from_start": round(time.monotonic() - started, 3),
                "error": error_text(error)}, process_errors)
        return code, output, error

    generator._run_capture = capture
    original_warning = generator._log_rare

    def warning(tag, message):
        record("warnings.jsonl", {"tag": tag, "message": error_text(message),
            "seconds_from_start": round(time.monotonic() - started, 3)}, warnings)
        return original_warning(tag, message)

    generator._log_rare = warning

    def measured_source(name, method):
        def call(*args, **kwargs):
            at = time.monotonic()
            value = None
            error = ""
            try:
                value = method(*args, **kwargs)
                return value
            except Exception as exc:
                error = error_text(exc)
                raise
            finally:
                row = {"operation": name, "mal_id": getattr(local, "title", None),
                       "seconds": round(time.monotonic() - at, 3),
                       "results": len(value) if isinstance(value, (dict, list)) else None}
                if error:
                    row["error"] = error
                record("source-calls.jsonl", row, source_calls)
        return call

    for name in ("catalogue", "more_catalogue", "releases", "streams", "variants", "captions"):
        original = getattr(generator.episode_ru, name)
        setattr(generator.episode_ru, name, measured_source(name, original))
    report = {"requested": args.count, "cold_episode_sources": True,
              "preloaded_video_files": 0, "catalogue_reused": True,
              "initial_suitability_streams": len(generator._episode_suitability.data["streams"])}
    report["excluded_titles"] = sorted(excluded)
    report["scene_check_method"] = "local-speech-and-ocr" if args.local_check else "gemini"
    result = None
    try:
        log(f"Холодный прогон: {args.count} отрывков, обязательные RU, проверка сцены.")
        result = generator.run(str(out / "anime-episodes-100-ru.siq"))
        report.update(path=result.path, generated=len(result.songs),
                      cancelled=result.cancelled,
                      questions=[{"mal_id": c.mal_id, "title": c.title_ru,
                                  "file": c.video_out, **c.episode_clip} for c in result.songs])
        if result.log_path:
            shutil.copy2(result.log_path, out / "generation.log")
    except Exception as exc:
        report["error"] = error_text(exc)
        log(f"Генерация: {report['error']}")
    finally:
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["attempts"] = len(attempts)
        report["process_errors"] = len(process_errors)
        report["accepted_attempts"] = sum(row["success"] for row in attempts)
        report["providers"] = dict(Counter(row.get("provider")
                                           for row in report.get("questions", [])))
        diagnostic = generator._diagnostics
        with diagnostic.lock:
            report["timings"] = [
                {"stage": stage, "operation": operation,
                 "wall_seconds": round(generator._merge_spans(spans), 3),
                 "task_seconds": round(sum(b - a for a, b in spans), 3)}
                for (stage, operation), spans in diagnostic.spans.items()]
            report["peak_workers"] = diagnostic.peak
            report["started_tasks"] = diagnostic.started
        generator.cleanup()
        (out / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"Итог: {report.get('generated', 0)}/{args.count}, "
        f"{report['elapsed_seconds']:.1f} с; файл: {report.get('path', '')}")
    return 0 if report.get("generated") == args.count and report.get("path") else 1


if __name__ == "__main__":
    raise SystemExit(main())
