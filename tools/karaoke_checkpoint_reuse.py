"""Copy this test's acoustically confirmed clips into an exact recipe."""
from dataclasses import fields
import json
from pathlib import Path
import shutil
from urllib.parse import urlparse

import animepack as ap


def confirmed(metadata, duration):
    """Only accept complete, consecutive excerpts produced from source audio."""
    if not (metadata.get("ai_used") and metadata.get("authored_timing_sources_excluded")
            and metadata.get("timing_origin") == "source_audio_asr"):
        return False
    if metadata.get("reference_url") or urlparse(metadata.get("lyrics_url", "")).hostname not in (
            "www.animelyrics.com", "www.animesonglyrics.com", "www.uta-net.com"):
        return False
    bounds, indices = metadata.get("confirmed_excerpt", []), metadata.get("selected_lyric_indices", [])
    if len(bounds) != 2 or len(indices) < 3:
        return False
    if any(b != a + 1 for a, b in zip(indices, indices[1:])):
        return False
    start = metadata.get("crop_start", -1)
    return (metadata.get("output_duration") == duration
            and metadata.get("aligned_lyrics_lines") == len(indices)
            and bounds[0] <= start and start + duration <= bounds[1]
            and start + duration <= metadata.get("duration", 0)
            and bool(metadata.get("source_audio_sha256"))
            and bool(metadata.get("original_lyrics_sha256"))
            and metadata.get("recording", {}).get("aligned_to_source_sha256")
            == metadata.get("source_audio_sha256"))


def install(generator, directory, duration):
    directory = Path(directory)
    rows = json.loads((directory / "checkpoint-candidates.json").read_text(encoding="utf-8"))
    cached = {}
    for number, row in enumerate(rows, 1):
        old = ap.SongCandidate(**row)
        if (old.has_video and old.has_poster and old.music_effect == "karaoke"
                and confirmed(old.karaoke, duration)):
            cached[(old.song_name.casefold(), old.artist.casefold())] = (number, old)
    fetch = generator._fetch_media
    root = directory / "checkpoints"

    def reuse(candidate):
        found = cached.get((candidate.song_name.casefold(), candidate.artist.casefold()))
        if not found:
            return fetch(candidate)
        number, old = found
        # Keep the recipe's public level inputs identical to the cached question.
        if (candidate.song != old.song or candidate.anime != old.anime
                or candidate.level != old.level or candidate.base_kind != old.base_kind):
            return fetch(candidate)
        sources = [root / "Video" / old.video_out,
                   root / "Video" / (Path(old.video_out).stem + ".ass"),
                   root / "Images" / old.poster_file]
        if not all(path.is_file() for path in sources):
            return fetch(candidate)
        for field in fields(candidate):
            setattr(candidate, field.name, getattr(old, field.name))
        candidate.media_base = f"confirmed-{number}-" + old.file_base
        candidate.poster_name = f"confirmed-{number}-" + old.poster_file
        folder = Path(generator.folder)
        targets = [folder / "Video" / candidate.video_out,
                   folder / "Video" / (Path(candidate.video_out).stem + ".ass"),
                   folder / "Images" / candidate.poster_file]
        for source, target in zip(sources, targets):
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        generator.karaoke_resolver.audit.record(old.karaoke["source"], "checkpoint_used",
                                               old.song_name, old.artist)
        generator.log(f"Подтверждённый {duration:g}-секундный ролик перенесён: {old.song_name}.")
        return True

    generator._fetch_media = reuse
