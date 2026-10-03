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
            line = min(lines, key=lambda line: abs(len(line.text) - 45))
            units = [unit for unit in line.units if unit.end > unit.start and unit.text.strip()]
            unit = units[len(units) // 2]
            when = (unit.start + unit.end) / 2
            video = Path(directory) / "video.mp4"
            video.write_bytes(archive.read("Video/" + row["file"]))
            target = args.output / f"{index + 1:02d}.png"
            subprocess.run([ap.FFMPEG, "-y", "-v", "error", "-ss", f"{when:.3f}",
                            "-i", str(video), "-frames:v", "1", str(target)], check=True,
                           capture_output=True, timeout=30)
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
