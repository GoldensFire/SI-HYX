"""Bounded live checks of AnimeThemes pacing, connections and complete files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tempfile
import time

import requests

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

URLS = ["https://v.animethemes.moe/" + name for name in (
    "BreakBlade1-OP1.webm", "MigiToDali-OP1.webm", "Ingress-OP1.webm",
    "BirdieWingS2-ED2.webm", "KimiAi-OP1.webm", "AriaTheNatural-OP3.webm")]


class Recorder:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self.rows = []

    def add(self, **row):
        self.rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        (self.folder / "results.json").write_text(
            json.dumps(self.rows, ensure_ascii=False, indent=2), encoding="utf-8")


def small_request(session, url, recorder, phase, sample, headers=None):
    started = time.monotonic()
    headers = {"Range": "bytes=0-1023", **(headers or {})}
    try:
        with session.get(url, headers=headers, timeout=(8, 20)) as response:
            status = response.status_code
            recorder.add(phase=phase, sample=sample, url=url, status=status,
                         bytes=len(response.content),
                         seconds=round(time.monotonic() - started, 3),
                         range=response.headers.get("Content-Range"),
                         retry_after=response.headers.get("Retry-After"))
            return status
    except requests.RequestException as error:
        recorder.add(phase=phase, sample=sample, url=url, error=str(error),
                     seconds=round(time.monotonic() - started, 3))
        return 0


def sequence(recorder, delay, keepalive, count=8):
    phase = f"tiny delay={delay} keepalive={keepalive}"
    with requests.Session() as session:
        for sample in range(count):
            status = small_request(session, URLS[sample % 3], recorder,
                                   phase, sample + 1,
                                   {} if keepalive else {"Connection": "close"})
            if status == 503 or not status:
                break
            if sample + 1 < count and delay:
                time.sleep(delay)


def held_connections(recorder, count):
    responses = []
    phase = f"held full streams={count}"
    try:
        for index in range(count):
            response = requests.get(URLS[index], stream=True, timeout=(8, 20))
            responses.append(response)
            recorder.add(phase=phase, sample=f"open-{index + 1}",
                         status=response.status_code,
                         length=response.headers.get("Content-Length"))
            if response.status_code != 200:
                return
            # Leave a full body unread, matching FFmpeg's abandoned seeks.
            time.sleep(1)
        with requests.Session() as session:
            small_request(session, URLS[2], recorder, phase, "control")
    finally:
        for response in responses:
            response.close()


def boundary(recorder):
    for delay, keepalive in ((0, True), (0, False), (.5, False),
                             (1, False), (2, False), (3, False)):
        sequence(recorder, delay, keepalive)
        time.sleep(8)
    for count in (1, 2, 3):
        held_connections(recorder, count)
        time.sleep(8)
        with requests.Session() as session:
            small_request(session, URLS[2], recorder, "recovery", count)
        time.sleep(5)


def full_files(recorder):
    import config
    import subprocess

    for index, url in enumerate(URLS):
        output = recorder.folder / Path(url).name
        started = time.monotonic()
        size = 0
        try:
            with requests.get(url, stream=True, timeout=(8, 30)) as response:
                status = response.status_code
                expected = int(response.headers.get("Content-Length") or 0)
                response.raise_for_status()
                with output.open("wb") as stream:
                    for chunk in response.iter_content(256 * 1024):
                        stream.write(chunk)
                        size += len(chunk)
            recorder.add(phase="full", sample=index + 1, url=url, status=status,
                         bytes=size, expected=expected,
                         seconds=round(time.monotonic() - started, 3))
            command = [config.FFPROBE, "-v", "error", "-show_entries",
                       "format=duration", "-of", "json", str(output)]
            process = subprocess.run(command, capture_output=True, timeout=30,
                                     creationflags=config.CREATE_NO_WINDOW)
            metadata = json.loads(process.stdout) if process.returncode == 0 else {}
            recorder.add(phase="local probe", sample=index + 1,
                         code=process.returncode,
                         duration=metadata.get("format", {}).get("duration"),
                         error=process.stderr.decode("utf-8", "replace")[-300:])
        except (requests.RequestException, OSError, subprocess.TimeoutExpired) as error:
            recorder.add(phase="full", sample=index + 1, url=url, bytes=size,
                         error=str(error), seconds=round(time.monotonic() - started, 3))
        time.sleep(3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("boundary", "full"))
    parser.add_argument("--folder", type=Path,
                        default=Path(tempfile.gettempdir()) / "si-hyx-animethemes-probe")
    args = parser.parse_args()
    recorder = Recorder(args.folder / args.mode)
    print(f"Results: {recorder.folder}", flush=True)
    (boundary if args.mode == "boundary" else full_files)(recorder)


if __name__ == "__main__":
    main()
