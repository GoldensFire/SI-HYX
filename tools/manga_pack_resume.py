# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Rebuild only checkpointed, approved questions without more Gemini calls."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from si_hyx_parts.animepack.manga_scene_review import MEMO_GROUP
from manga_pack_probe import contact_sheets


def resume(source, output, excluded=()):
    report = json.loads((source / "report.json").read_text(encoding="utf-8"))
    algorithms = Path(__file__).resolve().parents[1] / "si_hyx_parts" / "animepack"
    algorithm_key = hashlib.sha256(b"".join(
        (algorithms / name).read_bytes() for name in
        ("manga_margins.py", "manga_drawing_band.py"))).hexdigest()
    progress = source / "review-progress"
    approved = {}
    for row in report["questions"]:
        if row["title"] in excluded:
            continue
        name = row["frame"]
        checkpoint = progress / (hashlib.sha256(name.encode()).hexdigest() + ".json")
        if not checkpoint.is_file():
            continue
        saved = json.loads(checkpoint.read_text(encoding="utf-8"))
        fingerprint = hashlib.sha256((source / "frames" / name).read_bytes()).hexdigest()
        if (saved["fingerprint"] == fingerprint + MEMO_GROUP + algorithm_key
                and saved["note"]["accepted"]):
            approved[name] = saved
    if not approved:
        raise RuntimeError("No current approved checkpoints to resume")
    output.mkdir(parents=True, exist_ok=True)
    (output / "frames").mkdir(exist_ok=True)
    updates, rows, notes = {}, [], []
    with zipfile.ZipFile(report["pack"]) as archive:
        xml = ET.fromstring(archive.read("content.xml"))
        namespace = xml.tag.split("}")[0].lstrip("{")
        ns = {"s": namespace}
        ET.register_namespace("", namespace)
        questions = xml.findall(".//s:question", ns)
        if len(questions) != len(report["questions"]):
            raise RuntimeError("Question/report order is inconsistent")
        collections = xml.findall(".//s:questions", ns)
        parents = {id(q): collection for collection in collections for q in collection}
        for previous, question in zip(report["questions"], questions):
            saved = approved.get(previous["frame"])
            if saved is None:
                parents[id(question)].remove(question)
                continue
            row = saved["row"]
            for answer in question.findall(".//s:right/s:answer", ns):
                if answer.text == previous["chapter"]:
                    answer.text = row["chapter"]
            rows.append(row)
            notes.append(saved["note"])
            for name in saved["updates"]:
                updates[name] = (progress / "resources" / name).read_bytes()
            shutil.copy2(source / "reviewed-frames" / row["frame"],
                         output / "frames" / row["frame"])
            updates["Images/" + row["frame"]] = (output / "frames" / row["frame"]).read_bytes()
        for themes in xml.findall(".//s:themes", ns):
            for theme in list(themes):
                collection = theme.find("s:questions", ns)
                if collection is not None and not len(collection):
                    themes.remove(theme)
        manifest = json.loads(archive.read("si-hyx-pack.json"))
        ids = {row["mal"] for row in rows}
        manifest["titles"] = [entry for entry in manifest["titles"]
                              if entry.get("mal") in ids or entry.get("shikimori") in ids]
        updates["si-hyx-pack.json"] = json.dumps(manifest, ensure_ascii=False).encode("utf-8")
        updates["content.xml"] = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
        required = {"content.xml", "si-hyx-pack.json", "quality.marker"}
        folders = {"image": "Images", "video": "Video", "audio": "Audio"}
        for item in xml.findall(".//s:item", ns):
            if str(item.get("isRef", "")).lower() == "true":
                required.add(folders[item.get("type")] + "/" + unquote(item.text or ""))
        required.update("Images/" + row["frame"] for row in rows)
        final = output / "Проверенные сохранённые вопросы.siq"
        staging = final.with_suffix(".resuming.siq")
        with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for name in sorted(required):
                target.writestr(name, updates[name] if name in updates else archive.read(name))
        staging.replace(final)
    for name in ("settings.json", "generation.log"):
        shutil.copy2(source / name, output / name)
    report.update(pack=str(final), made=len(rows), questions=rows, visual_review=notes,
                  original_pack=report["pack"], resumed_without_api=True,
                  manual_rejections=list(excluded))
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    contact_sheets(rows, output)
    print(f"Resumed {len(rows)} approved questions without Gemini requests")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("output")
    parser.add_argument("--exclude-title", action="append", default=[])
    args = parser.parse_args()
    resume(Path(args.source).resolve(), Path(args.output).resolve(), args.exclude_title)


if __name__ == "__main__":
    main()
