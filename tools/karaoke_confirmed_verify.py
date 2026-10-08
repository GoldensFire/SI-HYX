"""Verify the test pack excludes authored timings and contains complete confirmed clips."""
import json
from pathlib import Path
from urllib.parse import urlparse
import zipfile


def verify(path, *, count=48, duration=20):
    report = []
    with zipfile.ZipFile(path) as archive:
        rows = json.loads(archive.read("karaoke.json"))["questions"]
        if len(rows) != count:
            raise ValueError(f"Expected {count} confirmed questions, got {len(rows)}")
        for row in rows:
            if not row.get("ai_used") or not row.get("authored_timing_sources_excluded"):
                raise ValueError("A question does not prove exclusion of authored timings")
            if row.get("timing_origin") != "source_audio_asr" or row.get("reference_url"):
                raise ValueError("A question uses a timing reference instead of its source audio")
            if urlparse(row.get("lyrics_url", "")).hostname not in (
                    "www.animelyrics.com", "www.animesonglyrics.com", "www.uta-net.com"):
                raise ValueError("Unexpected lyric source")
            start, end = row["confirmed_excerpt"]
            clip_start = row["crop_start"]
            clip_end = clip_start + row["output_duration"]
            if abs(row["output_duration"] - duration) > .001:
                raise ValueError("The question does not contain the requested clip duration")
            if clip_start < start - .001 or clip_end > end + .001:
                raise ValueError("The question extends outside its confirmed excerpt")
            if clip_end > row["duration"] + .001:
                raise ValueError("The confirmed clip extends past the actual source audio")
            if row["recording"].get("aligned_to_source_sha256") != row["source_audio_sha256"]:
                raise ValueError("The alignment refers to another source recording")
            indices = row["selected_lyric_indices"]
            if len(indices) < 3 or any(b != a + 1 for a, b in zip(indices, indices[1:])):
                raise ValueError("The confirmed excerpt bridges missing lyric lines")
            if row["aligned_lyrics_lines"] != len(indices):
                raise ValueError("The aligner omitted a line from the confirmed excerpt")
            report.append({"song": row["title"], "artist": row["artist"],
                           "lyrics_url": row["lyrics_url"], "confirmed_excerpt": [start, end],
                           "clip": [clip_start, clip_end], "seconds": duration,
                           "full_lyrics_coverage": row["full_lyrics_coverage"],
                           "confirmed_lines": len(indices), "passed": True})
    return report
