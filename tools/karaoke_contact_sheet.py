"""Extract a real mid-sweep frame from every packaged video for visual review."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke.ass import read_ass
from karaoke.style import FONT_FILE


def visible_moment(lines, limit):
    """Middle of a sung syllable that is on screen inside the clip.

    A line cut by the clip end used to give a syllable past the last frame:
    ffmpeg wrote no PNG and the tool fell with FileNotFoundError."""
    end = limit - .05
    rows = []
    for line in lines:
        shown_end = min(line.visible_end, end)
        units = [(max(u.start, line.start), min(u.end, shown_end)) for u in line.units
                 if u.end > u.start and u.text.strip()]
        units = [(a, b) for a, b in units if b > a]
        if units:
            rows.append((abs(len(line.text) - 45), units))
    if not rows:
        return max(0.0, min(lines[0].start if lines else 0.0, end))
    units = min(rows, key=lambda row: row[0])[1]
    start, stop = units[len(units) // 2]
    return (start + stop) / 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    levels = {row["file"]: row["level"] for row in report["questions"]}
    previews = []
    font = ImageFont.truetype(str(FONT_FILE), 20)
    with zipfile.ZipFile(args.package) as archive, tempfile.TemporaryDirectory() as directory:
        manifest = json.loads(archive.read("karaoke.json"))
        for index, row in enumerate(manifest["questions"]):
            name = Path(row["file"]).stem
            subtitle = archive.read("Karaoke/" + name + ".ass").decode("utf-8-sig")
            lines = read_ass(subtitle)
            limit = float(row.get("output_duration") or row.get("crop_duration") or 0) or float("inf")
            when = visible_moment(lines, limit)
            video = Path(directory) / "video.mp4"
            video.write_bytes(archive.read("Video/" + row["file"]))
            target = args.output / f"{index + 1:02d}.png"
            target.unlink(missing_ok=True)
            subprocess.run([ap.FFMPEG, "-y", "-v", "error", "-ss", f"{when:.3f}",
                            "-i", str(video), "-frames:v", "1", str(target)], check=True,
                           capture_output=True, timeout=30)
            if not target.is_file():
                print(f"{index + 1}: ffmpeg не извлёк кадр на {when:.3f} с — пропускаю.")
                continue
            with Image.open(target) as frame:
                tile = Image.new("RGB", (640, 160), "#111827")
                region = frame.crop((0, 250, 1280, 470)).resize((640, 110), Image.Resampling.LANCZOS)
                tile.paste(region, (0, 40))
                draw = ImageDraw.Draw(tile)
                label = row["title"].replace("♪", " ")
                draw.text((12, 8), f"{index+1}. {label} · уровень {levels[row['file']]}",
                          font=font, fill="white")
                previews.append(tile)
            if index == 0:
                with Image.open(target) as preview_image:
                    preview_image.save(args.output / "preview.png")
    sheet = Image.new("RGB", (1280, ((len(previews) + 1) // 2) * 160), "#111827")
    for index, preview in enumerate(previews):
        sheet.paste(preview, ((index % 2) * 640, (index // 2) * 160))
    sheet.save(args.output / "contact.png")
    print(args.output / "contact.png")


if __name__ == "__main__":
    main()
