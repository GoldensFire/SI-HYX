"""Compare karaoke AV1 presets on the same real songs, audio and lyric timing."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import statistics
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke.render import render
from karaoke.timeline import transform


def frame_rate_args(original, fps):
    def arguments(preset=None, *, crf=None):
        args = original(preset, crf=crf)
        args[args.index("-vf") + 1] += f",fps={fps}"
        return args
    return arguments


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--fps", type=int, choices=(15, 30), default=30)
    parser.add_argument("--presets", type=int, nargs="+", default=[10, 12, 13])
    args = parser.parse_args()
    ap.FFMPEG = shutil.which("ffmpeg") or ap.FFMPEG
    ap.FFPROBE = shutil.which("ffprobe") or ap.FFPROBE
    with zipfile.ZipFile(args.package) as archive:
        manifest = json.loads(archive.read("karaoke.json"))
    songs = json.loads(args.catalog.read_text(encoding="utf-8"))
    settings = ap.PackSettings(karaoke_enabled=True, karaoke_ai_fallback=False)
    generator = ap.AnimePackGenerator(settings)
    generator.video_encode_args = frame_rate_args(generator.video_encode_args, args.fps)
    measurements = []
    with tempfile.TemporaryDirectory(prefix="karaoke-speed-") as directory:
        work = Path(directory)
        generator.folder = str(work)
        for row in manifest["questions"][:max(1, args.count)]:
            song = next(song for song in songs if song.get("songName") == row["title"]
                        and song.get("songArtist") == row["artist"] and song.get("audio"))
            source = work / "source.audio"
            source.write_bytes(generator._cached_bytes(ap.AMQ_CDN + "/" + song["audio"],
                                                        "amq-audio", ap._MIN_AUDIO_BYTES))
            lines, metadata = generator.karaoke_resolver.resolve(source, row["title"], row["artist"])
            cropped = transform(lines, crop_start=row["crop_start"],
                                crop_end=row["crop_start"] + row["crop_duration"],
                                offset=metadata["offset"])
            settings.karaoke_crf = row["crf"]
            for preset in args.presets:
                settings.karaoke_preset = preset
                target = work / f"preset-{preset}.mp4"
                start = time.monotonic()
                render(generator, source, target, cropped, start=row["crop_start"],
                       duration=row["crop_duration"])
                result = {"song": row["title"], "preset": preset,
                          "fps": args.fps,
                          "crf": settings.karaoke_crf, "seconds": time.monotonic() - start,
                          "bytes": target.stat().st_size}
                measurements.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
    summary = []
    for preset in args.presets:
        rows = [row for row in measurements if row["preset"] == preset]
        summary.append({"preset": preset,
                        "fps": args.fps,
                        "median_seconds": statistics.median(row["seconds"] for row in rows),
                        "total_seconds": sum(row["seconds"] for row in rows),
                        "total_bytes": sum(row["bytes"] for row in rows)})
    args.output.write_text(json.dumps({"measurements": measurements, "summary": summary},
                                     ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
