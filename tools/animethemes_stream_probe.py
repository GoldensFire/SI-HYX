"""Compare FFmpeg HTTP profiles without changing application settings."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time

from animethemes_probe import ROOT, URLS, Recorder
import config


def options(size):
    if size == -2:
        return ["-seekable", "0", "-rw_timeout", "10000000"]
    if not size:
        return []
    return ["-initial_request_size", "65536", "-request_size", str(size),
            "-short_seek_size", str(size), "-multiple_requests", "1",
            "-rw_timeout", "10000000", "-reconnect", "1",
            "-reconnect_on_network_error", "1", "-reconnect_on_http_error", "429,5xx",
            "-reconnect_streamed", "1", "-reconnect_delay_max", "8",
            "-reconnect_max_retries", "4", "-reconnect_delay_total_max", "30"]


def sample(recorder, url, size, index):
    name = f"{index}-{Path(url).stem}-{size or 'default'}"
    output = recorder.folder / (name + ".mkv")
    command = [config.FFMPEG, "-y", "-loglevel", "debug"] + options(size) + [
        "-ss", "20", "-i", url, "-t", "15", "-map", "0:v:0", "-map", "0:a:0",
        "-c", "copy", str(output)]
    if size == -2:
        command = [config.FFMPEG, "-y", "-loglevel", "debug"] + options(size) + [
            "-i", url, "-ss", "20", "-t", "15", "-c:v", "libx264", "-preset",
            "ultrafast", "-c:a", "libopus", str(output)]
    start = time.monotonic()
    try:
        result = subprocess.run(command, capture_output=True, timeout=120,
                                creationflags=config.CREATE_NO_WINDOW)
        code, error = result.returncode, result.stderr.decode("utf-8", "replace")
    except subprocess.TimeoutExpired as failure:
        code, error = -1, (failure.stderr or b"").decode("utf-8", "replace")
    elapsed = round(time.monotonic() - start, 3)
    (recorder.folder / (name + ".log")).write_text(error, encoding="utf-8")
    data, decode_error = {}, ""
    if output.exists():
        probe = subprocess.run([config.FFPROBE, "-v", "error", "-show_entries",
                                "format=duration:stream=codec_type", "-of", "json",
                                str(output)], capture_output=True, timeout=30,
                               creationflags=config.CREATE_NO_WINDOW)
        if probe.returncode == 0:
            data = json.loads(probe.stdout)
        decode = subprocess.run([config.FFMPEG, "-v", "error", "-i", str(output),
                                 "-f", "null", "-"], capture_output=True, timeout=60,
                                creationflags=config.CREATE_NO_WINDOW)
        decode_error = decode.stderr.decode("utf-8", "replace")
    recorder.add(phase="ffmpeg", sample=index, url=url, size=size, code=code,
                 seconds=elapsed, duration=data.get("format", {}).get("duration"),
                 streams=[row.get("codec_type") for row in data.get("streams", [])],
                 ranges=re.findall(r"Range: bytes=([^\r\n]+)", error),
                 http_errors=re.findall(r"HTTP error [^\r\n]+", error),
                 premature="prematurely" in error,
                 bytes=output.stat().st_size if output.exists() else 0,
                 decode_error=decode_error[-500:], tail=error[-400:] if code else "")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, default=-1)
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--folder", type=Path,
                        default=Path(tempfile.gettempdir()) / "si-hyx-animethemes-probe")
    args = parser.parse_args()
    recorder = Recorder(args.folder / f"streams-{args.size}")
    sizes = [0, 1024 * 1024, 4 * 1024 * 1024] if args.size == -1 else [args.size]
    for index, size in enumerate(sizes):
        sample(recorder, URLS[1], size, index + 1)
        time.sleep(8)
    if args.size not in (-1, -2):
        for index, url in enumerate(URLS[:args.count]):
            sample(recorder, url, args.size, index + 2)
            time.sleep(3)


if __name__ == "__main__":
    main()
