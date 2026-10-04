"""Decode and inspect every episode question, with optional visible-caption OCR."""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import animepack as api
from si_hyx_parts.animepack.episode_caption_text import russian
from si_hyx_parts.animepack.episode_media import valid_clip


def run(command):
    result = subprocess.run(command, capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", "replace")[-500:])
    return result.stdout


def frame(video, at, target):
    run([api.FFMPEG, "-v", "error", "-y", "-ss", f"{at:.3f}", "-i", str(video),
         "-frames:v", "1", str(target)])


def normalized(text):
    return re.sub(r"[\W_]+", "", text.casefold())


def visible(reader, image):
    from PIL import Image, ImageOps
    import io
    from si_hyx_parts.animepack.local_visual_ocr import read
    def read_crop(top, scale):
        with Image.open(image) as picture:
            width, height = picture.size
            crop = picture.crop((0, int(height * top), width, height))
            if scale > 1:
                crop = crop.resize((crop.width * scale, crop.height * scale))
                crop = ImageOps.expand(crop, border=30, fill="black")
        buffer = io.BytesIO()
        crop.save(buffer, format="PNG")
        rows, _elapsed, _cached = read(reader, buffer.getvalue())
        crops = {}
        for row in rows:
            if row["confidence"] > .6:
                current = crops.get(row["crop"])
                if current is None or row["confidence"] > current["confidence"]:
                    crops[row["crop"]] = row
        return [row["text"] for row in crops.values()]
    texts = read_crop(.68, 1)
    if any(russian(text) for text in texts):
        return texts
    # Outlined captions over busy animation sometimes need larger glyphs.
    return read_crop(.8, 2)


def caption_check(reader, video, row, folder):
    cues = row.get("subtitle_cues") or []
    if cues:
        wanted = sorted(cues, key=lambda c: c["end"] - c["start"], reverse=True)[:3]
        times = [(c["start"] + c["end"]) / 2 for c in wanted]
    else:
        wanted = []
        times = [1, 4, 7, 10, 13]
    observed, matched = [], []
    for index, at in enumerate(times):
        target = folder / f"caption-{index:02}.png"
        frame(video, at, target)
        texts = visible(reader, target)
        observed.append({"at": round(at, 3), "text": texts})
        if cues:
            expected = normalized(wanted[index]["text"])
            recognized = normalized(" ".join(texts))
            matched.append(SequenceMatcher(None, expected, recognized).ratio() >= .55)
    ru = [text for sample in observed for text in sample["text"] if russian(text)]
    foreign = [text for sample in observed for text in sample["text"]
               if len(normalized(text)) > 12 and not russian(text)
               and re.search("[a-zA-Z]", text)]
    if row.get("subtitle_language") == "en" and not row.get("ru_subtitles"):
        english = [text for sample in observed for text in sample["text"]
                   if re.search("[a-zA-Z]", text) and not russian(text)]
        if not english or (matched and not any(matched)):
            raise ValueError("Видимые английские субтитры не подтверждены: " + str(observed))
        return {"visible_en": True, "cue_matches": matched, "frames": observed}
    if not ru or (matched and not any(matched)):
        raise ValueError("Видимые русские субтитры не подтверждены: " + str(observed))
    if foreign:
        raise ValueError("В кадре видны иностранные субтитры: " + str(foreign))
    return {"visible_ru": True, "cue_matches": matched, "frames": observed}


def sheets(pictures, out):
    from PIL import Image, ImageDraw, ImageFont
    font_path = Path("C:/Windows/Fonts/arial.ttf")
    font = ImageFont.truetype(str(font_path), 16) if font_path.exists() else ImageFont.load_default()
    for batch in range((len(pictures) + 11) // 12):
        selected = pictures[batch * 12:(batch + 1) * 12]
        canvas = Image.new("RGB", (1440, 303 * ((len(selected) + 2) // 3)), "#171717")
        draw = ImageDraw.Draw(canvas)
        for index, (path, label) in enumerate(selected):
            x, y = index % 3 * 480, index // 3 * 303
            with Image.open(path) as picture:
                canvas.paste(picture.resize((480, 270)), (x, y))
            draw.text((x + 8, y + 273), label[:48], font=font, fill="white")
        canvas.save(out / f"contact-{batch + 1}.jpg")


def audit(package, out, expected, ocr):
    out.mkdir(parents=True, exist_ok=True)
    reader = SimpleNamespace(stopped=lambda: False, log=print, _ocr_models=None,
        db_cache=SimpleNamespace(memo=lambda *a: None, remember_memo=lambda *a: None))
    report = {"package": str(package.resolve()), "expected": expected, "questions": [], "errors": []}
    pictures = []
    with zipfile.ZipFile(package) as archive:
        xml = ET.fromstring(archive.read("content.xml"))
        rows = json.loads(archive.read("episodes.json"))
        questions = xml.findall(".//{*}question")
        references = [item.text for question in questions for item in question.findall(".//{*}item")
                      if item.get("type") == "video"]
        if len(rows) != expected or len(questions) != expected or len(references) != expected:
            report["errors"].append("Число вопросов, видео или метаданных не соответствует ожидаемому")
        if sorted(references) != sorted(row["file"] for row in rows):
            report["errors"].append("Ссылки вопросов не соответствуют видео")
        for index, row in enumerate(rows, 1):
            checked = {"number": index, **row}
            folder = out / f"{index:02}"
            folder.mkdir(exist_ok=True)
            video = folder / "clip.mp4"
            try:
                video.write_bytes(archive.read("Video/" + row["file"]))
                info = json.loads(run([api.FFPROBE, "-v", "error", "-show_streams", "-show_format",
                                       "-of", "json", str(video)]))
                if not valid_clip(info):
                    raise ValueError("Неверная длительность или дорожки")
                streams = {stream["codec_type"]: stream for stream in info["streams"]}
                if streams["video"]["codec_name"] != "av1" or streams["video"]["height"] != 720:
                    raise ValueError("Ожидалось AV1 720p")
                if streams["audio"]["codec_name"] != "opus":
                    raise ValueError("Ожидалось аудио Opus")
                english = row.get("subtitle_language") == "en" and not row.get("ru_subtitles")
                if row.get("source_height", 0) < 1080 or not (row.get("ru_subtitles") or english):
                    raise ValueError("Не подтверждён источник ≥1080p с RU/EN-субтитрами")
                for cue in row.get("subtitle_cues") or []:
                    language_ok = (bool(re.search("[a-zA-Z]", cue["text"])) if english
                                   else russian(cue["text"]))
                    if not 0 <= cue["start"] < cue["end"] <= 15 or not language_ok:
                        raise ValueError("Неверный язык или таймкод реплики")
                run([api.FFMPEG, "-v", "error", "-xerror", "-i", str(video), "-map", "0:v:0", "-map", "0:a:0",
                     "-f", "null", "-"])
                if ocr:
                    checked["caption_check"] = caption_check(reader, video, row, folder)
                checked.update(decode_ok=True, actual_duration=float(info["format"]["duration"]),
                               audio_start=float(streams["audio"].get("start_time", 0)),
                               video_start=float(streams["video"].get("start_time", 0)))
                cues = row.get("subtitle_cues") or []
                at = (cues[0]["start"] + cues[0]["end"]) / 2 if cues else 7
                picture = folder / "review.png"
                frame(video, at, picture)
                pictures.append((picture, f"{index:02} " + row["file"].split("(")[-1].removesuffix(").mp4")))
                print(f"{index:02}: проверено — {row['file']}", flush=True)
            except Exception as error:
                checked["error"] = str(error)
                report["errors"].append({"number": index, "error": str(error)})
                print(f"{index:02}: ОШИБКА — {error}", flush=True)
            report["questions"].append(checked)
    sheets(pictures, out)
    report["passed"] = not report["errors"]
    (out / "audit.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report["passed"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--ocr", action="store_true")
    args = parser.parse_args()
    return 0 if audit(args.package, args.out, args.count, args.ocr) else 1


if __name__ == "__main__":
    raise SystemExit(main())
