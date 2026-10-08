"""Fully decode each preserved component once and retain its media fingerprints."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import animepack
from tools.episode_pack_audit import audit


def release_years(archive):
    tree = ET.fromstring(archive.read("content.xml"))
    years = {}
    for question in tree.findall(".//{*}question"):
        videos = [item.text for item in question.findall(".//{*}item") if item.get("type") == "video"]
        answers = question.findall("{*}right/{*}answer")
        if videos and answers:
            match = re.search(r"\((\d{4})\)\s*$", answers[0].text or "")
            if match:
                years[videos[0]] = int(match[1])
    return years


def validate(folder):
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    destination = folder / "validation"
    if (destination / "audit.json").exists():
        raise FileExistsError("This unchanged component has already been audited")
    with zipfile.ZipFile(report["path"]) as archive:
        years = release_years(archive)
    return audit(Path(report["path"]), destination, report["generated"], False, years)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folders", type=Path, nargs="+")
    args = parser.parse_args()
    return 0 if all(validate(folder) for folder in args.folders) else 1


if __name__ == "__main__":
    raise SystemExit(main())
