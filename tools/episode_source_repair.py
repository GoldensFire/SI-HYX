"""Retain valid source clips and replace concrete audited failures in separate SIQs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import sys
import threading
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import animepack as api
import gemini_api as gemini
from utils import load_settings
from episode_source_clients import Recorder, SourceKuhi, SourceRu
from episode_source_probe import ContextCache, write_json
from episode_source_semantic_audit import inspect
from si_hyx_parts.animepack.episode_suitability import Suitability

PLANS = (("anikoto", "ru", (12365,)),
         ("anikoto", "no_ru", (12365, 59597)),
         ("animegg", "no_ru", (52505, 56876)),
         ("anizone", "no_ru", (9989,)),
         ("animego", "ru", (9989,)),
         ("animego", "no_ru", (44516, 59002)),
         ("animelib", "no_ru", (59597,)))


def repair(root, source, mode, rejected, raw, contexts):
    original = json.loads((root / source / mode / "report.json").read_text(encoding="utf-8"))
    cards = json.loads((root / "cohort.json").read_text(encoding="utf-8"))
    by_id = {int(card["id"]): card for card in cards}
    output = root / "ready" / source / mode
    output.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()

    def log(message):
        with lock:
            with (output / "generation.log").open("a", encoding="utf-8") as stream:
                stream.write(str(message) + "\n")
        print(f"REPAIR {source}/{mode}: {message}", flush=True)

    def event(value):
        with (output / "events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(value, ensure_ascii=False) + "\n")

    recorder = Recorder(event)
    recorder.mode = mode
    settings = api.PackSettings(rounds=1, themes=2, questions=5, pct_songs=0,
        pack_episode=True, pct_episode=100, level_min=4, level_max=4, level_avg=4,
        episode_ru_subtitles=mode == "ru", mark_owners=False, parallel=2,
        video_preset=int(raw["animepack"].get("video_preset", 7)),
        video_crf=int(raw["animepack"].get("video_crf", 45)),
        generation_priority="normal", title=f"Отрывки {source} {mode}, проверено")
    settings.gemini_key = str(raw.get("api_keys", {}).get("gemini") or "")
    settings.animelib_token = str(raw.get("api_keys", {}).get("animelib") or "")
    settings.gemini_model = raw["animepack"].get("gemini_model", settings.gemini_model)
    settings.gemini_thinking = raw["animepack"].get("gemini_thinking", settings.gemini_thinking)
    kuhi = SourceKuhi(source, recorder, lambda: False, log)
    ru = SourceRu(source, recorder, lambda: False, log)
    ru.no_ru = mode == "no_ru"
    gen = api.AnimePackGenerator(settings, kuhi=kuhi, episode_ru=ru, anizip=contexts,
                                 log=log, rng=random.Random(20261006),
                                 db_cache=api.ShikimoriDbCache(str(output / "isolated-db.json")))
    gen._episode_suitability = Suitability(str(output / "suitability.json"))
    gen.prepare_dirs()
    client = gemini.GeminiClient(settings.gemini_key, model=settings.gemini_model,
                                 thinking=settings.gemini_thinking, timeout=60, log=log)
    selected, metadata, checks = [], [], []
    old_ids = {row["mal"] for row in original["questions"]}
    try:
        with zipfile.ZipFile(original["package"]) as archive:
            for row in original["questions"]:
                if row["mal"] in rejected:
                    continue
                cand = api.SongCandidate({}, by_id[row["mal"]], kind=api.EPISODE_KIND)
                cand.has_video = True
                cand.episode_clip = {key: value for key, value in row.items()
                                     if key not in ("mal", "title", "level", "year", "file")}
                (Path(gen.folder) / "Video" / cand.video_out).write_bytes(
                    archive.read("Video/" + row["file"]))
                selected.append(cand)
                metadata.append(row)
        # Begin after the original source's selection, rather than retrying its
        # known failures or repeating an already used title.
        last = max(index for index, card in enumerate(cards) if int(card["id"]) in old_ids)
        pool = cards[last + 1:] + cards[:last + 1]
        for card in pool:
            if len(selected) == 10:
                break
            if int(card["id"]) in old_ids:
                continue
            cand = api.SongCandidate({}, card, kind=api.EPISODE_KIND)
            recorder.title = cand.mal_id
            log(f"замена: «{cand.title_ru}»")
            if not gen.download_episode(cand):
                continue
            row = {"mal": cand.mal_id, "title": cand.title_ru, "level": cand.level,
                   "year": cand.year, "file": cand.video_out, **cand.episode_clip}
            video = Path(gen.folder) / "Video" / cand.video_out
            checked = inspect(client, source, mode, row, video.read_bytes())
            checks.append(checked)
            write_json(output / "new-clips-semantic.json", checks)
            if not checked["passed"]:
                log(f"отклонён: {checked['reason']}")
                video.unlink(missing_ok=True)
                continue
            if bool(cand.episode_clip.get("ru_subtitles")) != (mode == "ru"):
                continue
            selected.append(cand)
            metadata.append(row)
        settings.rounds, settings.themes, settings.questions = 1, 1, len(selected)
        selected = api.assign_prices(selected, settings)
        package = gen.write_package(selected, str(output / f"{source}-{mode}-checked.siq"))
        report = {"source": source, "mode": mode, "made": len(selected),
                  "requested": 10, "package": package, "questions": metadata,
                  "replaced_mal_ids": list(rejected), "average_level": 4.0,
                  "new_clips": [row for row in checks if row["passed"]]}
        write_json(output / "report.json", report)
        return report
    finally:
        gen.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    raw = load_settings()
    contexts = ContextCache()
    chosen = set(args.only.split(",")) if args.only else set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = [pool.submit(repair, args.root, source, mode, rejected, raw, contexts)
                for source, mode, rejected in PLANS
                if not chosen or f"{source}:{mode}" in chosen]
        reports = [job.result() for job in jobs]
    write_json(args.root / "repairs.json", reports)


if __name__ == "__main__":
    main()
