"""Retain expensive real-media successes even if a diagnostic run is interrupted."""
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import threading
import time


def install(generator, output):
    output = Path(output)
    root = output / "checkpoints"
    root.mkdir(exist_ok=True)
    fetch = generator._fetch_media
    lock = threading.Lock()
    rows = {}
    attempts = []

    def checkpoint(candidate):
        started = time.monotonic()
        good = fetch(candidate)
        with lock:
            attempts.append({"song": candidate.song_name, "artist": candidate.artist,
                             "level": candidate.level, "success": bool(good),
                             "seconds": time.monotonic() - started})
            (output / "media-attempts.json").write_text(json.dumps(attempts, ensure_ascii=False,
                                                indent=2), encoding="utf-8")
            if good and candidate.has_video and candidate.karaoke:
                folder = Path(generator.folder)
                for directory, name in (("Video", candidate.video_out),
                                        ("Video", Path(candidate.video_out).stem + ".ass"),
                                        ("Images", candidate.poster_file)):
                    source = folder / directory / name
                    if source.is_file():
                        target = root / directory / name
                        target.parent.mkdir(exist_ok=True)
                        shutil.copy2(source, target)
                rows[(candidate.song_name.casefold(), candidate.artist.casefold())] = asdict(candidate)
                temporary = output / "checkpoint-candidates.tmp"
                temporary.write_text(json.dumps(list(rows.values()), ensure_ascii=False,
                                                indent=2), encoding="utf-8")
                temporary.replace(output / "checkpoint-candidates.json")
            snapshot = output / "source-audit.tmp"
            snapshot.write_text(json.dumps(generator.karaoke_resolver.audit.snapshot(),
                                            ensure_ascii=False, indent=2), encoding="utf-8")
            snapshot.replace(output / "source-audit.json")
        return good

    generator._fetch_media = checkpoint
