"""Find authored karaoke candidates in the saved anime catalogue before media work."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import animepack as ap
from karaoke.matching import metadata_matches
from karaoke.mugen import Mugen
from si_hyx_parts.animepack.catalog_superset import cached_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--titles", type=int, default=150)
    parser.add_argument("--minimum", type=int, default=3)
    parser.add_argument("--maximum", type=int, default=7)
    args = parser.parse_args()
    generator = ap.AnimePackGenerator(ap.PackSettings(karaoke_enabled=True))
    cards, _ = cached_catalog(generator.db_cache, "anime", ap.shiki_cache_signature(generator.s, False))
    candidates = [ap.SongCandidate({}, card, kind="opening") for card in cards
                  if ap.filter_anime(card, generator.s)]
    candidates = [c for c in candidates if args.minimum <= c.level <= args.maximum]
    candidates.sort(key=lambda c: c.index, reverse=True)
    ids = [c.mal_id for c in candidates[:args.titles]]
    songs = []
    for offset in range(0, len(ids), 50):
        rows = generator.anisong.songs_by_mal_ids(ids[offset:offset + 50])
        songs.extend(row for row in rows if row.get("audio") and ap.filter_song(row, generator.s))
        print(f"CATALOG {min(offset + 50, len(ids))}/{len(ids)} titles; {len(songs)} songs", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    raw = args.output.with_name(args.output.stem + "-raw.json")
    raw.write_text(json.dumps(songs, ensure_ascii=False, indent=1), encoding="utf-8")
    provider = Mugen(generator.karaoke_resolver.http)
    def check(song):
        title, artist = song["songName"], song["songArtist"]
        try:
            tracks = provider.search(title, artist)
            return any(metadata_matches(title, artist, float(song.get("songLength") or 0), track)
                       for track in tracks)
        except Exception as error:
            print(f"SEARCH {title}: {error}", flush=True)
            return False
    matched = []
    started = time.monotonic()
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="karaoke-catalog") as pool:
        pending = {pool.submit(check, row): row for row in songs}
        for number, future in enumerate(as_completed(pending), 1):
            row = pending[future]
            if future.result():
                matched.append(row)
                print(f"MATCH {row['songName']}", flush=True)
            if number % 25 == 0:
                print(f"SEARCHED {number}/{len(songs)}; matched {len(matched)}; {time.monotonic()-started:.0f}s", flush=True)
                args.output.write_text(json.dumps(matched, ensure_ascii=False, indent=1), encoding="utf-8")
    args.output.write_text(json.dumps(matched, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"COMPLETE {len(matched)} authored karaoke candidates", flush=True)


if __name__ == "__main__":
    main()
