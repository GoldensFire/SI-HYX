"""AMLL TTML catalog, preserving the exact platform recording as reference."""
from __future__ import annotations

import json
import threading
from urllib.parse import quote
from .model import Track
from .matching import title_key

BASE = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main"


class Amll:
    def __init__(self, http):
        self.http = http
        self._index = None
        self._lock = threading.Lock()

    def search(self, title, artist):
        with self._lock:
            if self._index is None:
                data = self.http.bytes(BASE + "/metadata/raw-lyrics-index.jsonl", maximum=16_000_000)
                self._index = [json.loads(line) for line in data.splitlines() if line.strip()]
        count = 0
        for row in reversed(self._index):
            meta = dict(row.get("metadata") or [])
            names = meta.get("musicName") or []
            if not any(title_key(name) == title_key(title) for name in names):
                continue
            # Unverified platform IDs are never a substitute for audio identity.
            ids = meta.get("ncmMusicId") or []
            if not ids:
                continue
            name = str(row["rawLyricFile"])
            yield Track(names[0], meta.get("artists") or [], 0.0, "AMLL TTML",
                        BASE + "/raw-lyrics/" + quote(name, safe=""),
                        "https://music.163.com/song/media/outer/url?id=" + quote(str(ids[0]), safe="") + ".mp3",
                        "ttml", aliases=names, version=" ".join(names))
            count += 1
            if count >= 4:
                break
