"""Exercise real Demucs/lyric-align once with an independently sourced TV lyric sheet."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke.ass import write_ass
from karaoke.fallback import align
from karaoke.http import Http
from karaoke.lyrics import LyricSites, add_translations


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = ap.make_session()
    song = next(row for row in ap.AnisongApi(session).songs_by_mal_ids([38000])
                if row["songName"] == "Gurenge")
    http = Http(session)
    source = args.output / "Gurenge-TV.mp3"
    source.write_bytes(http.bytes(ap.AMQ_CDN + "/" + song["audio"]))
    sheet = LyricSites(http, lambda message: print(message, flush=True)).search(
        song["songName"], song["songArtist"], duration=float(song["songLength"]))
    if not sheet or not sheet.original:
        raise ValueError("Нет проверенного японского текста TV-версии.")
    print(f"LYRICS {len(sheet.original)} lines: {sheet.url}", flush=True)
    started = time.monotonic()
    lines = align(source, sheet, ap.PackSettings(), stopped=lambda: False,
                  log=lambda message: print(message, flush=True))
    add_translations(lines, sheet)
    (args.output / "fallback.ass").write_text(write_ass(lines), encoding="utf-8-sig")
    report = {"song": song["songName"], "source": ap.AMQ_CDN + "/" + song["audio"],
              "lyrics_source": sheet.url, "ai_used": True,
              "elapsed": time.monotonic() - started,
              "source_lines": len(sheet.original), "aligned_lines": len(lines),
              "lines": [asdict(line) for line in lines]}
    (args.output / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"FALLBACK OK {len(lines)}/{len(sheet.original)}", flush=True)


if __name__ == "__main__":
    main()
