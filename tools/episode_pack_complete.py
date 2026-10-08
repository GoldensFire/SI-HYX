"""Combine clips prepared during one interrupted cold generation into one SIQ."""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile


def read(folder, name="report.json"):
    return json.loads((folder / name).read_text(encoding="utf-8"))


def stamp(folder, last=False):
    lines = (folder / "console.log").read_text(encoding="utf-8").splitlines()
    matches = [re.match(r"\[([^]]+)\]", line) for line in lines]
    times = [datetime.fromisoformat(match[1]) for match in matches if match]
    return times[-1] if last else times[0]


def complete(folders, failed, output, expected, excluded=()):
    reports = [read(folder) for folder in folders]
    if sum(report.get("generated", 0) for report in reports) != expected:
        raise ValueError("The component packs do not contain the required count")
    questions, rows, members, manifests = [], [], {}, []
    root = None
    for folder, report in zip(folders, reports):
        with zipfile.ZipFile(report["path"]) as archive:
            tree = ET.fromstring(archive.read("content.xml"))
            if root is None:
                root = tree
            elif root.tag != tree.tag:
                raise ValueError("Incompatible SIQ XML versions")
            additions = deepcopy(tree.findall(".//{*}question"))
            metadata_by_file = {row["file"]: row for row in report["questions"]}
            metadata = [metadata_by_file[next(item.text for item in question.findall(".//{*}item")
                        if item.get("type") == "video")] for question in additions]
            if len(additions) != len(metadata):
                raise ValueError("Question XML does not match the generation report")
            renamed = {}
            for member in archive.infolist():
                name = member.filename
                if name in ("content.xml", "episodes.json", "si-hyx-pack.json"):
                    continue
                payload = archive.read(member)
                if name in members and members[name] != payload:
                    original = Path(name)
                    number = 2
                    replacement = name
                    while replacement in members:
                        replacement = original.with_name(f"{original.stem}_{number}{original.suffix}").as_posix()
                        number += 1
                    renamed[name] = replacement
                    name = replacement
                members[name] = payload
            for question in additions:
                for item in question.findall(".//{*}item"):
                    media = {"video": "Video", "audio": "Audio", "image": "Images"}.get(item.get("type"))
                    if media and str(item.get("isRef", "")).lower() == "true":
                        old = media + "/" + unquote(item.text or "")
                        if old in renamed:
                            item.text = renamed[old].split("/", 1)[1]
            for item in metadata:
                item = dict(item)
                old = "Video/" + item["file"]
                if old in renamed:
                    item["file"] = renamed[old].split("/", 1)[1]
                rows.append(item)
            questions.extend(additions)
            manifests.append(json.loads(archive.read("si-hyx-pack.json")))
    if len({row["mal_id"] for row in rows}) != expected:
        raise ValueError("The generation components repeat an anime title")
    if any(row["mal_id"] in excluded for row in rows):
        raise ValueError("An explicitly excluded title is present")
    namespace = root.tag.split("}", 1)[0].lstrip("{")
    rounds = root.findall(".//{*}round")
    if len(rounds) != 2:
        raise ValueError("The base must have the requested two rounds")
    template = deepcopy(root.findall(".//{*}theme")[0])
    for round_number, current in enumerate(rounds):
        themes = current.find("{*}themes")
        themes.clear()
        for theme_number in range(10):
            theme = deepcopy(template)
            theme.set("name", f"Отрывки серий {round_number * 10 + theme_number + 1}")
            target = theme.find("{*}questions")
            target.clear()
            start = round_number * 50 + theme_number * 5
            target.extend(questions[start:start + 5])
            themes.append(theme)
    if len(root.findall(".//{*}question")) != expected:
        raise ValueError("The rebuilt round layout has the wrong count")
    manifest = dict(manifests[0])
    for field in ("titles", "studios", "characters"):
        combined = []
        for source in manifests:
            for item in source.get(field, []):
                if item not in combined:
                    combined.append(item)
        manifest[field] = combined
    output.mkdir(parents=True, exist_ok=True)
    final = output / "anime-episodes-100-ru.siq"
    if final.exists():
        raise FileExistsError(final)
    ET.register_namespace("", namespace)
    episode_rows = [{key: value for key, value in row.items() if key not in ("mal_id", "title")}
                    for row in rows]
    staging = final.with_suffix(".assembling.siq")
    with zipfile.ZipFile(staging, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("content.xml", ET.tostring(root, encoding="utf-8", xml_declaration=True))
        archive.writestr("episodes.json", json.dumps(episode_rows, ensure_ascii=False, indent=2))
        archive.writestr("si-hyx-pack.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        for name, payload in members.items():
            archive.writestr(name, payload)
    staging.replace(final)
    all_folders = folders + failed
    levels = [int(match[1]) for question in questions for item in question.findall(".//{*}item")
              for match in [re.search(r"Ур\. (\d+)", item.text or "")] if match]
    result = {"requested": expected, "generated": len(rows), "path": str(final.resolve()),
              "cancelled": False, "questions": rows, "preloaded_video_files": 0,
              "cold_episode_sources": all(read(folder).get("cold_episode_sources") for folder in all_folders),
              "elapsed_seconds": (stamp(folders[-1], True) - stamp(folders[0])).total_seconds(),
              "generation_elapsed_seconds": sum(read(folder)["elapsed_seconds"] for folder in all_folders),
              "components": [str(folder.resolve()) for folder in folders],
              "failed_components": [str(folder.resolve()) for folder in failed],
              "providers": dict(Counter(row["provider"] for row in rows)),
              "average_level": sum(levels) / len(levels), "timings": [],
              "scene_check_methods": {
                  "gemini": sum(bool(row.get("scene_check")) for row in rows),
                  "local": sum(bool(row.get("local_check")) for row in rows)}}
    for name in ("attempts.jsonl", "source-calls.jsonl", "warnings.jsonl", "resources.jsonl", "process-errors.jsonl", "generation.log"):
        with (output / name).open("w", encoding="utf-8") as target:
            for folder in all_folders:
                path = folder / name
                if path.exists():
                    target.write(path.read_text(encoding="utf-8") + "\n")
    shutil.copy2(folders[0] / "settings.json", output / "settings.json")
    review = folders[0] / "caption-review"
    if review.exists():
        shutil.copytree(review, output / "caption-review", dirs_exist_ok=True)
    for name in ("season-review.json", "auto-endpoint-check.json", "recovery-check.json", "video-interactions-check.json"):
        source = folders[0] / name
        if source.exists():
            shutil.copy2(source, output / name)
    for folder in folders:
        local = folder / "local-validation"
        if local.exists():
            shutil.copytree(local, output / "local-validation" / folder.name, dirs_exist_ok=True)
    (output / "report.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Completed {len(rows)} questions")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", type=Path, action="append", required=True)
    parser.add_argument("--failed-component", type=Path, action="append", default=[])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--exclude-id", type=int, action="append", default=[])
    args = parser.parse_args()
    complete(args.component, args.failed_component, args.out, args.count, args.exclude_id)


if __name__ == "__main__":
    main()
