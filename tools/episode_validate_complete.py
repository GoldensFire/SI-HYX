"""Verify final structure and unchanged bytes against fully decoded components."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import animepack
from tools.episode_pack_audit import sheets


def validate(folder):
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    output = folder / "validation"
    output.mkdir(parents=True, exist_ok=True)
    known = {}
    for component in report["components"]:
        source = Path(component) / "validation"
        checked = json.loads((source / "audit.json").read_text(encoding="utf-8"))
        if not checked["passed"]:
            raise ValueError(f"A component did not pass decoding: {component}")
        for index, row in enumerate(checked["questions"], 1):
            if row["sha256"] in known:
                raise ValueError("Identical media exists in separate generation components")
            known[row["sha256"]] = (row, source / f"{index:02}" / "review.png")
    result = {"package": report["path"], "expected": 100, "errors": [], "questions": [],
              "validation": "full component decoding plus final byte/structure integrity"}
    pictures = []
    with zipfile.ZipFile(report["path"]) as archive:
        broken = archive.testzip()
        if broken:
            raise ValueError(f"Archive CRC failed: {broken}")
        xml = ET.fromstring(archive.read("content.xml"))
        rows = json.loads(archive.read("episodes.json"))
        questions = xml.findall(".//{*}question")
        references = [item.text for question in questions for item in question.findall(".//{*}item")
                      if item.get("type") == "video"]
        if len(rows) != 100 or len(questions) != 100 or len(references) != 100:
            raise ValueError("The final count must be exactly 100")
        if sorted(references) != sorted(row["file"] for row in rows):
            raise ValueError("Question references do not match the episode metadata")
        themes = xml.findall(".//{*}theme")
        if len(xml.findall(".//{*}round")) != 2 or len(themes) != 20 or any(
                len(theme.findall("{*}questions/{*}question")) != 5 for theme in themes):
            raise ValueError("Expected two rounds, ten themes per round and five questions per theme")
        members = set(archive.namelist())
        for question in questions:
            for item in question.findall(".//{*}item"):
                if str(item.get("isRef", "")).lower() == "true":
                    prefix = {"video": "Video", "image": "Images", "audio": "Audio"}.get(item.get("type"))
                    if prefix and prefix + "/" + unquote(item.text or "") not in members:
                        raise ValueError("A referenced media resource is absent")
        used = set()
        for index, row in enumerate(rows, 1):
            digest = hashlib.sha256(archive.read("Video/" + row["file"])).hexdigest()
            if digest in used or digest not in known:
                raise ValueError("Duplicate video or bytes without full decoding verification")
            used.add(digest)
            original, picture = known[digest]
            for field in ("provider", "episode", "start", "duration", "source_height", "subtitle_language"):
                if row.get(field) != original.get(field):
                    raise ValueError(f"Merged metadata changed {field}")
            if not row.get("ru_subtitles") or row.get("subtitle_language") != "ru":
                raise ValueError("Russian subtitles must be present in every video")
            checked = deepcopy(original)
            checked.update(row, number=index, sha256=digest, bytes_unchanged=True)
            result["questions"].append(checked)
            pictures.append((picture, f"{index:03} " + row["file"].split("(")[-1].removesuffix(").mp4")))
    result.update(passed=True, decoded=100, unique_videos=100,
                  gemini_scenes=sum(bool(row.get("scene_check")) for row in rows),
                  local_scenes=sum(bool(row.get("local_check")) for row in rows),
                  average_level=report["average_level"])
    (output / "audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    sheets(pictures, output)
    print("Verified 100 decoded, unique videos and complete SIQ references")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    validate(args.folder)


if __name__ == "__main__":
    main()
