"""Decode source-audit SIQs and inspect actual captions in both requested modes."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import animepack as api
from episode_pack_audit import run, frame, visible, sheets, caption_check
from si_hyx_parts.animepack.episode_media import valid_clip
from si_hyx_parts.animepack.episode_caption_text import russian


def check(package, mode_report, mode, output, ocr):
    output.mkdir(parents=True, exist_ok=True)
    reader = SimpleNamespace(stopped=lambda: False, log=lambda _: None, _ocr_models=None,
                             db_cache=SimpleNamespace(memo=lambda *a: None,
                                                      remember_memo=lambda *a: None))
    report = {"package": str(package), "mode": mode, "questions": [], "errors": []}
    previous = output / "audit.json"
    old = json.loads(previous.read_text(encoding="utf-8")) if previous.exists() else {}
    checked_before = {row["file"]: row for row in old.get("questions", [])
                      if row.get("decode_ok")}
    questions = {row["file"]: row for row in mode_report["questions"]}
    pictures = []
    with zipfile.ZipFile(package) as archive:
        rows = json.loads(archive.read("episodes.json"))
        xml = ET.fromstring(archive.read("content.xml"))
        refs = [item.text for item in xml.findall(".//{*}item") if item.get("type") == "video"]
        if sorted(refs) != sorted(row["file"] for row in rows):
            report["errors"].append("Package video references differ from metadata")
        if len(rows) != len(questions):
            report["errors"].append("Package and generation counts differ")
        for number, row in enumerate(rows, 1):
            checked = {"number": number, **questions[row["file"]]}
            folder = output / f"{number:02}"
            folder.mkdir(exist_ok=True)
            video = folder / "clip.mp4"
            if row["file"] in checked_before:
                checked = checked_before[row["file"]]
                report["questions"].append(checked)
                if checked.get("error"):
                    report["errors"].append({"number": number, "error": checked["error"]})
                if (folder / "review.png").exists():
                    pictures.append((folder / "review.png", f"{number:02} {checked['title']}"))
                continue
            try:
                video.write_bytes(archive.read("Video/" + row["file"]))
                info = json.loads(run([api.FFPROBE, "-v", "error", "-show_streams",
                                       "-show_format", "-of", "json", str(video)]))
                if not valid_clip(info):
                    raise ValueError("Invalid duration or missing audio/video")
                tracks = {s["codec_type"]: s for s in info["streams"]}
                if tracks["video"]["codec_name"] != "av1":
                    raise ValueError("Expected AV1")
                if tracks["audio"]["codec_name"] != "opus":
                    raise ValueError("Expected Opus")
                if tracks["video"]["height"] != row["output_height"]:
                    raise ValueError("Output height differs from metadata")
                floor = 480 if 0 < checked["year"] <= 2005 else 1080
                if row["source_height"] < floor or row["output_height"] > 720:
                    raise ValueError("Source/output quality violates release-year policy")
                if bool(row.get("ru_subtitles")) != (mode == "ru"):
                    raise ValueError("Wrong requested caption mode")
                run([api.FFMPEG, "-v", "error", "-xerror", "-i", str(video),
                     "-map", "0:v:0", "-map", "0:a:0", "-f", "null", "-"])
                checked.update(decode_ok=True,
                               actual_duration=float(info["format"]["duration"]),
                               video_height=tracks["video"]["height"],
                               audio_language=tracks["audio"].get("tags", {}).get("language"),
                               bytes=video.stat().st_size)
                if ocr:
                    if mode == "ru":
                        checked["caption_check"] = caption_check(reader, video, row, folder)
                    else:
                        observations = []
                        for index, at in enumerate((1, 7, 13) if row.get("hardsub") else (7,)):
                            picture = folder / f"caption-{index:02}.png"
                            frame(video, at, picture)
                            observations.append({"at": at, "text": visible(reader, picture)})
                        ru = [t for observation in observations for t in observation["text"]
                              if russian(t) and len(re.sub(r"\W", "", t)) > 10]
                        checked["caption_check"] = {"frames": observations,
                                                    "russian_text_detected": ru}
                        if ru:
                            raise ValueError("Russian text detected in no-RU clip: " + str(ru))
                cues = row.get("subtitle_cues") or []
                at = (cues[0]["start"] + cues[0]["end"]) / 2 if cues else 7
                picture = folder / "review.png"
                frame(video, at, picture)
                pictures.append((picture, f"{number:02} {checked['title']}"))
            except Exception as error:
                checked["error"] = str(error)
                report["errors"].append({"number": number, "error": str(error)})
            report["questions"].append(checked)
            (output / "audit.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"{package.parent.parent.name}/{mode} {number:02}: "
                  f"{checked.get('error', 'OK')}", flush=True)
    sheets(pictures, output)
    report["passed"] = not report["errors"]
    report["technical_passed"] = all(row.get("decode_ok") for row in report["questions"])
    (output / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--ocr", action="store_true")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--sources", default="")
    parser.add_argument("--modes", default="")
    args = parser.parse_args()
    summary = json.loads((args.root / "summary.json").read_text(encoding="utf-8"))
    validation = args.root / "validation.json"
    reports = json.loads(validation.read_text(encoding="utf-8")) if validation.exists() else []
    chosen_sources = set(args.sources.split(",")) if args.sources else set()
    chosen_modes = set(args.modes.split(",")) if args.modes else set()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = []
        for source in summary["sources"]:
            if chosen_sources and source["source"] not in chosen_sources:
                continue
            for mode, result in source.get("modes", {}).items():
                if chosen_modes and mode not in chosen_modes:
                    continue
                if result.get("package"):
                    package = Path(result["package"])
                    jobs.append(pool.submit(check, package, result, mode,
                                            package.parent / "audit", args.ocr))
        for job in as_completed(jobs):
            result = job.result()
            reports = [r for r in reports if r["package"] != result["package"]]
            reports.append(result)
            (args.root / "validation.json").write_text(
                json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
