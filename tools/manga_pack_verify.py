# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Check a live pack and render the final visible frame of every question video."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import unquote
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from config import FFMPEG
from manga_pack_probe import contact_sheets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", help="Folder produced by manga_pack_probe.py")
    root = Path(parser.parse_args().output).resolve()
    report = json.loads((root / "report.json").read_text(encoding="utf-8"))
    pack = Path(report["pack"])
    rows = report["questions"]
    with zipfile.ZipFile(pack) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Broken ZIP member: {bad}")
        members = set(archive.namelist())
        xml = ET.fromstring(archive.read("content.xml"))
    ns = {"s": xml.tag.split("}")[0].lstrip("{")}
    questions = xml.findall(".//s:question", ns)
    if len(questions) != report["requested"] or len(rows) != len(questions):
        raise RuntimeError("Question count does not match the requested pack size")
    folders = {"image": "Images", "video": "Video", "audio": "Audio"}
    references = []
    for item in xml.findall(".//s:item", ns):
        if str(item.get("isRef", "")).lower() != "true":
            continue
        member = folders[item.get("type")] + "/" + unquote(item.text or "")
        if member not in members:
            raise RuntimeError(f"Missing media: {member}")
        references.append(member)
    preview = root / "video-preview"
    frames = preview / "frames"
    frames.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="manga-video-check-", dir=root) as temporary:
        def decode(entry):
            index, row = entry
            stem = row["frame"].rsplit("_frame", 1)[0]
            member = "Video/" + stem + " — появление 1.mp4"
            source = Path(temporary) / f"{index}.mp4"
            with zipfile.ZipFile(pack) as archive:
                source.write_bytes(archive.read(member))
            name = f"{index:02}.jpg"
            # Decode the tail and overwrite the preview through the final,
            # settled frame; its first frame can still contain the entrance.
            command = [str(FFMPEG), "-hide_banner", "-loglevel", "error", "-y",
                       "-sseof", "-0.1", "-i", str(source), "-update", "1",
                       "-q:v", "2", str(frames / name)]
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=90)
            if result.returncode or not (frames / name).is_file():
                raise RuntimeError(f"Cannot decode {row['title']}: {result.stderr}")
            return dict(row, frame=name)

        with ThreadPoolExecutor(max_workers=2) as pool:
            rendered = list(pool.map(decode, enumerate(rows, 1)))
    contact_sheets(rendered, preview)
    notes = report.get("visual_review", [])
    stats = {"pack": str(pack), "questions": len(questions), "zip_integrity": True,
             "media_references": len(references), "missing_media": 0,
             "decoded_question_videos": len(rendered),
             "editions": dict(Counter(row["kind"] for row in rows)),
             "level_range": [min(row["level"] for row in rows),
                             max(row["level"] for row in rows)],
             "mean_level": sum(row["level"] for row in rows) / len(rows),
             "repaired_frames": sum(note["changed"] for note in notes),
             "replaced_scenes": sum(note["replaced_scene"] for note in notes)}
    (root / "verification.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
