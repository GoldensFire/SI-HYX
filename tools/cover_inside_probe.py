# -*- coding: utf-8 -*-
"""Стенд отпечатка: отличаем игру ПОД ОРИГИНАЛ от честного кавера.

Считает `cover_fingerprint.inside` на размеченных парах «эталон — ролик» и
показывает, с каким запасом порог MAX_OVERLAP их делит. Разметка — в
tools/cover_inside_cases.json: эталон это либо файл AMQ («amq:1uhrww.mp3»),
либо ролик YouTube («yt:<id>»), кандидат — всегда id ролика.

    python tools/cover_inside_probe.py --fetch     # скачать и разобрать (сеть)
    python tools/cover_inside_probe.py             # посчитать по скачанному

Рабочая папка — %TEMP%\\si_hyx_cover_inside; собирается один раз и живёт на
диске, как и стенд звука (tools/cover_audio_probe.py).
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AMQ = "https://naedist.animemusicquiz.com"
CASES = Path(__file__).resolve().parent / "cover_inside_cases.json"
WORK = Path(tempfile.gettempdir()) / "si_hyx_cover_inside"


def _tool(name: str) -> str:
    local = Path(__file__).resolve().parent.parent / "bin" / f"{name}.exe"
    return str(local) if local.exists() else name


def _stem(key: str) -> str:
    return key.replace(":", "_").replace(".", "_")


def _wav(key: str, fetch: bool) -> Path:
    import cover_audio as audio
    out = WORK / f"{_stem(key)}.wav"
    if out.exists():
        return out
    if not fetch:
        raise FileNotFoundError(f"{key}: запустите с --fetch")
    if key.startswith("amq:"):
        raw = WORK / key[4:]
        if not raw.exists():
            urllib.request.urlretrieve(f"{AMQ}/{key[4:]}", raw)
    else:
        raw = WORK / f"{_stem(key)}.m4a"
        if not raw.exists():
            subprocess.run([_tool("yt-dlp"), "-f", "139/140/bestaudio",
                            "--no-playlist", "-o", str(raw),
                            f"https://www.youtube.com/watch?v={key.split(':')[-1]}"],
                           check=True)
    subprocess.run(audio.decode_args(_tool("ffmpeg"), str(raw), str(out)),
                   check=True)
    return out


def _marks(key: str, fetch: bool):
    import numpy as np
    import cover_audio as audio
    import cover_fingerprint as fingerprint
    cache = WORK / f"{_stem(key)}.marks.npz"
    if cache.exists():
        data = np.load(cache)
        return data["points"], int(data["frames"])
    points, frames = fingerprint.marks(audio.read_wav(_wav(key, fetch)))
    np.savez(cache, points=points, frames=frames)
    return points, frames


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true",
                        help="скачать недостающее (сеть, ~40 МБ)")
    args = parser.parse_args()
    import cover_fingerprint as fingerprint

    os.makedirs(WORK, exist_ok=True)
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    honest, mixed, missed = [], [], []
    for group, rows in cases.items():
        for ref_key, cover_key, note in rows:
            try:
                ref, _ = _marks(ref_key, args.fetch)
                cover, frames = _marks(cover_key, args.fetch)
            except Exception as error:                      # noqa: BLE001
                print(f"!! {note}: {error}")
                continue
            caught, score = fingerprint.inside(ref, cover, frames)
            print(f"{group:10s} {score:8.2f} "
                  f"{'ОТСЕЯН' if caught else 'прошёл':7s} {note}")
            if group == "genuine":
                (mixed if caught else honest).append(score)
            elif caught:
                pass
            else:
                missed.append((score, note))
    print()
    print(f"порог: {fingerprint.MAX_OVERLAP}")
    if honest:
        print(f"самый «липкий» честный кавер: {max(honest):.2f}")
    if mixed:
        print(f"ЧЕСТНЫХ ОТСЕЯНО: {len(mixed)} — порог занижен")
    for score, note in missed:
        print(f"не поймали: {score:.2f} — {note}")
    return 1 if mixed else 0


if __name__ == "__main__":
    raise SystemExit(main())
