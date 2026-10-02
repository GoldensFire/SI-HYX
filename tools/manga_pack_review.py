# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Review every retained manga frame, repair failures and rebuild its entrance."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import random
import re
import shutil
import sys
import threading
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image
import animepack as ap
from config import SETTINGS_FILE
from image_entrance import EFFECT_LABELS, choose_effect
from si_hyx_parts.animepack.entrance_encoding import encode_image
from si_hyx_parts.animepack.entrance_processing import apply as apply_entrance
from si_hyx_parts.animepack.generation_priority import parallel_limit
from si_hyx_parts.animepack.manga_margins import trim, has_large_gap
from si_hyx_parts.animepack.manga_scene_review import check, MEMO_GROUP
from manga_pack_probe import contact_sheets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Folder produced by manga_pack_probe.py")
    parser.add_argument("--replace-title", action="append", default=[],
                        help="Replace a scene rejected by manual visual inspection")
    parser.add_argument("--parallel", type=int,
                        help="Override concurrency for this review only")
    args = parser.parse_args()
    root = Path(args.output).resolve()
    forced = set(args.replace_title)
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    original_pack = Path(report["pack"])
    settings = ap.PackSettings.from_dict(json.loads(
        (root / "settings.json").read_text(encoding="utf-8")))
    if args.parallel is not None:
        if not 1 <= args.parallel <= 16:
            parser.error("--parallel must be between 1 and 16")
        settings.parallel = args.parallel
    saved = json.loads(Path(SETTINGS_FILE).read_text(encoding="utf-8"))
    settings.gemini_key = str(saved.get("api_keys", {}).get("gemini") or "")
    lock = threading.Lock()

    def log(message):
        with lock:
            with (root / "review.log").open("a", encoding="utf-8") as stream:
                stream.write(message + "\n")
            print(message, flush=True)

    generator = ap.AnimePackGenerator(settings, log=log, rng=random.Random(7))
    generator.prepare_dirs()
    generator.load_exclusions()
    cards = {int(c.get("malId") or c.get("id") or 0): c
             for c in generator.db_cache.all_cards("manga")}
    effects = {v: k for k, v in EFFECT_LABELS.items()}
    original_log = (root / "generation.log").read_text(encoding="utf-8")
    with zipfile.ZipFile(original_pack) as archive:
        members = set(archive.namelist())
        xml = ET.fromstring(archive.read("content.xml"))
    rows = report["questions"]
    repaired = root / "reviewed-frames"
    repaired.mkdir(exist_ok=True)
    progress = root / "review-progress"
    progress.mkdir(exist_ok=True)
    algorithms = Path(__file__).resolve().parents[1] / "si_hyx_parts" / "animepack"
    algorithm_key = hashlib.sha256(b"".join(
        (algorithms / name).read_bytes() for name in
        ("manga_margins.py", "manga_drawing_band.py"))).hexdigest()

    def review(row):
        title, name = row["title"], row["frame"]
        original_data = (root / "frames" / name).read_bytes()
        fingerprint = hashlib.sha256(original_data).hexdigest() + MEMO_GROUP + algorithm_key
        checkpoint = progress / (hashlib.sha256(name.encode()).hexdigest() + ".json")
        if checkpoint.exists():
            saved = json.loads(checkpoint.read_text(encoding="utf-8"))
            satisfied = title not in forced or saved["note"]["replaced_scene"]
            if saved["fingerprint"] == fingerprint and satisfied:
                updates = {key: (progress / "resources" / key).read_bytes()
                           for key in saved["updates"]}
                fresh = None
                if saved.get("fresh"):
                    fresh = ap.SongCandidate({}, cards[int(row["mal"])],
                                             kind=ap.MANGA_KIND, media="manga")
                    fresh.frame_url = saved["fresh"]["page"]
                    fresh.extra_frame_urls = saved["fresh"]["context"]
                    fresh.has_frame = True
                log(f"Продолжаю с сохранённой проверкой: «{title}»")
                return saved["row"], updates, saved["note"], fresh
        with generator._runtime.worker():
            with Image.open(root / "frames" / name) as opened:
                original = opened.convert("RGB")
            frame = trim(original, max_ratio=1.6)
            good, reason = check(generator, frame, title)
            good = good and not has_large_gap(frame)
            if title in forced:
                good, reason = False, "замена по результату ручного просмотра"
            changed = frame.size != original.size
            updates = {}
            fresh = None
            stem = name.rsplit("_frame", 1)[0]
            video = stem + " — появление 1.mp4"
            if not good:
                log(f"«{title}»: вырезка отклонена ({reason}); подбираю новую сцену")
                card = cards.get(int(row["mal"]))
                if not card:
                    raise RuntimeError(f"Нет карточки для замены сцены: {title}")
                for _ in range(4):
                    fresh = ap.SongCandidate({}, card, kind=ap.MANGA_KIND, media="manga",
                                             compress_images=settings.compress_images)
                    # Repair only the scene of an already selected question;
                    # its title, difficulty, poster and price stay in the pack.
                    fresh.media_base = generator._media_base(fresh)
                    if (generator.download_manga_panel(fresh)
                            and apply_entrance(generator, fresh)):
                        break
                else:
                    raise RuntimeError(f"Не удалось заменить плохую сцену: {title}")
                source = Path(generator.folder) / "Images" / fresh.frame_name
                data = source.read_bytes()
                with Image.open(source) as opened:
                    frame = opened.convert("RGB")
                generated_video = fresh.entrance_frames.get(fresh.frame_name)
                if "Video/" + video in members:
                    if not generated_video:
                        raise RuntimeError(f"Не собралось появление: {title}")
                    updates["Video/" + video] = (
                        Path(generator.folder) / "Video" / generated_video).read_bytes()
                row = dict(row, chapter=fresh.source_link, page=fresh.frame_url)
                changed = True
            elif changed:
                output = io.BytesIO()
                frame.save(output, "PNG")
                encoded = generator._save_image(output.getvalue(), stem + "_review", ".png")
                if not encoded:
                    raise RuntimeError(f"Не удалось сохранить вырезку: {title}")
                source = Path(generator.folder) / "Images" / encoded
                data = source.read_bytes()
                if "Video/" + video in members:
                    match = re.search(re.escape(f"«{title}»: появление — ") + r"([^\r\n]+)",
                                      original_log)
                    effect = effects.get(match[1]) if match else None
                    effect = effect or choose_effect(settings, generator.rng)
                    target = Path(generator.folder) / "Video" / video
                    encode_image(generator, source, target, effect, 7, settings.entrance_seconds)
                    updates["Video/" + video] = target.read_bytes()
            else:
                data = (root / "frames" / name).read_bytes()
            (repaired / name).write_bytes(data)
            if changed and "Images/" + name in members:
                updates["Images/" + name] = data
            note = {"title": title, "accepted": True, "changed": changed,
                    "replaced_scene": fresh is not None, "before": list(original.size),
                    "after": list(frame.size), "reason": reason}
            for key, payload in updates.items():
                target = progress / "resources" / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
            saved = {"fingerprint": fingerprint, "row": row, "note": note,
                     "updates": list(updates), "fresh": None if fresh is None else
                     {"page": fresh.frame_url, "context": fresh.extra_frame_urls}}
            checkpoint.write_text(json.dumps(saved, ensure_ascii=False, indent=2),
                                  encoding="utf-8")
            log(f"Проверено: «{title}»; {original.size} → {frame.size}"
                + ("; новая сцена" if fresh is not None else ""))
            return row, updates, note, fresh

    try:
        with ThreadPoolExecutor(max_workers=parallel_limit(settings)) as pool:
            verified = list(pool.map(review, rows))
        updates, notes, fresh_scenes = {}, [], []
        new_rows = []
        for row, changed, note, fresh in verified:
            updates.update(changed)
            notes.append(note)
            new_rows.append(row)
            if fresh is not None:
                fresh_scenes.append(fresh)
        namespace = {"s": xml.tag.split("}")[0].lstrip("{")}
        ET.register_namespace("", namespace["s"])
        for previous, current in zip(rows, new_rows):
            if previous["chapter"] == current["chapter"]:
                continue
            for answer in xml.findall(".//s:right/s:answer", namespace):
                if answer.text == previous["chapter"]:
                    answer.text = current["chapter"]
        updates["content.xml"] = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        final_pack = root / "Проверка манга 48 — проверено.siq"
        staging_pack = final_pack.with_suffix(".reviewing.siq")
        with zipfile.ZipFile(original_pack) as source, zipfile.ZipFile(
                staging_pack, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for member in source.infolist():
                target.writestr(member, updates.get(member.filename, source.read(member)))
        staging_pack.replace(final_pack)
        old_frames = root / "original-frames"
        old_frames.mkdir(exist_ok=True)
        for row in new_rows:
            name = row["frame"]
            if not (old_frames / name).exists():
                shutil.copy2(root / "frames" / name, old_frames / name)
            shutil.copy2(repaired / name, root / "frames" / name)
        earlier = {note["title"]: note for note in report.get("visual_review", [])}
        for note in notes:
            previous = earlier.get(note["title"])
            if previous:
                note.update(before=previous["before"],
                            changed=previous["changed"] or note["changed"],
                            replaced_scene=previous["replaced_scene"] or note["replaced_scene"])
        report.update(pack=str(final_pack), original_pack=report.get("original_pack", str(original_pack)),
                      questions=new_rows, visual_review=notes)
        (root / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        contact_sheets(new_rows, root)
        generator.save_frames_history(fresh_scenes)
        log(f"REVIEW COMPLETE: {len(notes)}; repaired {sum(n['changed'] for n in notes)}")
    finally:
        generator.db_cache.save()
        generator.cleanup()


if __name__ == "__main__":
    main()
