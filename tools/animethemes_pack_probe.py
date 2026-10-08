"""Exercise real AnimeThemes preparation, AV1/Opus output and SIQ packaging."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import random
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile

from animethemes_probe import ROOT, URLS, Recorder
import animepack as ap
import config


def check(path):
    result = subprocess.run([ap.FFPROBE, "-v", "error", "-show_entries",
                             "format=duration:stream=codec_name,codec_type,duration",
                             "-of", "json", str(path)], capture_output=True,
                            timeout=30, creationflags=config.CREATE_NO_WINDOW)
    data = json.loads(result.stdout) if not result.returncode else {}
    decode = subprocess.run([ap.FFMPEG, "-v", "error", "-i", str(path),
                             "-f", "null", "-"], capture_output=True, timeout=60,
                            creationflags=config.CREATE_NO_WINDOW)
    return data, decode.returncode, decode.stderr.decode("utf-8", "replace")


def run(recorder, count, parallel, offset=0, force_full=False):
    # Isolate any auxiliary caches; user's settings and pack history are untouched.
    with tempfile.TemporaryDirectory(prefix="theme_probe_settings_") as settings_dir:
        ap.CONFIG_DIR = settings_dir
        settings = ap.PackSettings(song_video=True, pct_songs=100, video_cut=15,
                                   video_preset=12, video_crf=40, parallel=parallel,
                                   rounds=1, themes=1, questions=count,
                                   mark_owners=False, poster_cache=False, images=False)
        generator = ap.AnimePackGenerator(settings, rng=random.Random(27),
                                          log=lambda message: print(message, flush=True))
        if force_full:
            generator._theme_protocol_args = {ap.FFMPEG: None, ap.FFPROBE: None}
        generator.prepare_dirs()
        generator._title_favorites = lambda candidate: -1
        generator.download_images = lambda candidate: None
        generator._theme_video = lambda candidate: candidate.video_url

        def no_audio(candidate):
            raise RuntimeError("Video unexpectedly fell back to audio")
        generator.download_audio = no_audio
        candidates = []
        selected = URLS[offset:offset + count]
        if len(selected) != count:
            raise ValueError("Requested range exceeds the probe's six sources")
        for index, url in enumerate(selected):
            tag = "Ending 2" if "-ED" in url else "Opening 1"
            candidate = ap.SongCandidate({"songType": tag, "annSongId": index + 1},
                                        {"malId": index + 1, "name": Path(url).stem,
                                         "russian": Path(url).stem, "score": 7,
                                         "airedOn": {"year": 2020}},
                                        kind="ending" if "-ED" in url else "opening",
                                        video_url=url, media_base=f"theme-{index + 1}")
            candidates.append(candidate)

        def prepare(candidate):
            start = time.monotonic()
            try:
                ready = generator._fetch_media(candidate)
                path = Path(generator.folder) / "Video" / candidate.video_out
                data, code, error = check(path) if path.exists() else ({}, -1, "missing video")
                recorder.add(phase="pack media", url=candidate.video_url,
                             ready=ready and candidate.theme_video_ready,
                             seconds=round(time.monotonic() - start, 3),
                             metadata=data, decode_code=code, decode_error=error,
                             bytes=path.stat().st_size if path.exists() else 0)
                return ready and candidate.theme_video_ready and code == 0 and not error
            except Exception as failure:
                recorder.add(phase="pack media", url=candidate.video_url, error=str(failure))
                return False

        try:
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                passed = list(pool.map(prepare, candidates))
            if not all(passed):
                return False
            ap.arrange_questions(candidates, settings)
            package = generator.write_package(candidates, str(recorder.folder / "verified.siq"))
            with zipfile.ZipFile(package) as archive:
                xml = ET.fromstring(archive.read("content.xml"))
                media = xml.findall(".//{*}param[@name='question']/{*}item[@type='video']")
                video = [name for name in archive.namelist() if name.startswith("Video/")]
                audio = [name for name in archive.namelist() if name.startswith("Audio/")]
                good = len(media) == len(video) == count and not audio
                recorder.add(phase="siq", questions=len(media), videos=len(video),
                             audio=len(audio), good=good, package=package)
                return good
        finally:
            generator.cleanup()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, choices=range(1, 7), default=6)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--offset", type=int, choices=range(6), default=0)
    parser.add_argument("--force-full", action="store_true")
    parser.add_argument("--folder", type=Path,
                        default=Path(tempfile.gettempdir()) / "si-hyx-animethemes-probe")
    args = parser.parse_args()
    recorder = Recorder(args.folder / ("pack-full" if args.force_full else "pack"))
    raise SystemExit(0 if run(recorder, args.count, args.parallel, args.offset, args.force_full) else 1)


if __name__ == "__main__":
    main()
