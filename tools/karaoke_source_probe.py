"""Evaluate the paired providers independently on songs in a generated pack."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests
from karaoke.http import Http
from karaoke.paired_lyrics import PairedLyrics, SOURCE
from karaoke.search import context
from karaoke.source_audit import SourceAudit
from karaoke.text_alignment import transfer


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = json.loads(args.candidates.read_text(encoding="utf-8"))
    audit, local = SourceAudit(), threading.local()

    def check(row):
        if not hasattr(local, "providers"):
            local.providers = PairedLyrics(Http(requests.Session()), audit)
        providers = local.providers
        song, anime = row["song"], row["anime"]
        title, artist = song["songName"], song["songArtist"]
        duration = row["karaoke"]["duration"]
        info = context(song, anime, row["kind"])
        result = dict(title=title, artist=artist, duration=duration,
                      petit_editions=0, uta_sheet=False, paired=False, reasons=[])
        try:
            options = providers.petit.search(title, artist, duration, info)
            result["petit_editions"] = len(options)
        except Exception as error:
            options = []
            result["reasons"].append("PetitLyrics: " + str(error))
        try:
            sheet = providers.uta.search(title, artist, info)
            result["uta_sheet"] = bool(sheet)
        except Exception as error:
            sheet = None
            result["reasons"].append("Uta-Net: " + str(error))
        if options and sheet:
            for option in options:
                try:
                    timed = providers.petit.timings(option)
                    lines, details = transfer(timed, sheet)
                    result.update(paired=True, lines=len(lines), alignment=details,
                                  lyrics_id=option.id, lyrics_url=option.url, romaji_url=sheet.url)
                    break
                except Exception as error:
                    result["reasons"].append(str(error))
        print(f"SOURCE {title}: Petit {len(options)}, Uta {bool(sheet)}, pair {result['paired']}", flush=True)
        return result

    rows = []
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(check, row) for row in candidates]
        for future in as_completed(futures):
            rows.append(future.result())
            summary = {"sample": len(candidates), "checked": len(rows),
                       "available": dict(Counter({
                           "PetitLyrics matching editions": sum(bool(r["petit_editions"]) for r in rows),
                           "Uta-Net Global sheets": sum(r["uta_sheet"] for r in rows),
                           SOURCE: sum(r["paired"] for r in rows)})),
                       "questions": rows, "audit": audit.snapshot()}
            args.output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
