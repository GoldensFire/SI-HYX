"""Audit ordinary lyric availability before expensive acoustic alignment."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import json
from pathlib import Path
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke.http import Http
from karaoke.lyrics import LyricSites
from karaoke.search import context
from karaoke.source_audit import SourceAudit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", nargs="+", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    candidates = {}
    for path in args.candidates:
        for row in json.loads(path.read_text(encoding="utf-8")):
            c = ap.SongCandidate(**row)
            candidates[(c.song_name.casefold(), c.artist.casefold())] = c
    audit, local = SourceAudit(), threading.local()

    def probe(c):
        if not hasattr(local, "sites"):
            local.sites = LyricSites(Http(ap.make_session(), cache=args.cache), audit=audit)
        started = time.monotonic()
        sheet = local.sites.search(c.song_name, c.artist,
            duration=float(c.karaoke.get("duration") or c.song.get("songLength") or 90),
            context=context(c.song, c.anime, c.base_kind))
        return c, {"song": c.song_name, "artist": c.artist, "level": c.level,
                   "original_lines": len(sheet.original) if sheet else 0,
                   "romaji_lines": len(sheet.romaji) if sheet else 0,
                   "url": sheet.url if sheet else None, "seconds": time.monotonic() - started}

    results, available = [], []
    with ThreadPoolExecutor(max_workers=4) as pool:
        tasks = [pool.submit(probe, c) for c in candidates.values()]
        for future in as_completed(tasks):
            c, result = future.result()
            results.append(result)
            if result["original_lines"]:
                available.append(asdict(c))
            (args.output / "sources.json").write_text(json.dumps(results, ensure_ascii=False,
                                                indent=2), encoding="utf-8")
            (args.output / "available-candidates.json").write_text(json.dumps(available,
                                            ensure_ascii=False, indent=2), encoding="utf-8")
            (args.output / "audit.json").write_text(json.dumps(audit.snapshot(), ensure_ascii=False,
                                                 indent=2), encoding="utf-8")
            print(f"TEXT {len(results)}/{len(tasks)} available {len(available)}: "
                  f"{c.song_name} / {result['original_lines']} lines", flush=True)


if __name__ == "__main__":
    main()
