"""AMLL TTML catalog, preserving the exact platform recording as reference."""
from __future__ import annotations

import json
import threading
from urllib.parse import quote
from .model import Track
from .matching import title_key
from .search import title_names

BASE = "https://raw.githubusercontent.com/amll-dev/amll-ttml-db/main"


class Amll:
    def __init__(self, http):
        self.http = http
        self._index = None
        self._by_title = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._index is None:
                data = self.http.bytes(BASE + "/metadata/raw-lyrics-index.jsonl", maximum=16_000_000)
                rows = [json.loads(line) for line in data.splitlines() if line.strip()]
                # Normalised names once: a linear pass per song repeated the
                # normalisation of 3307 publications (6.4 s for 50 songs).
                by_title = {}
                for position, row in enumerate(rows):
                    names = dict(row.get("metadata") or []).get("musicName") or []
                    for key in {title_key(name) for name in names}:
                        by_title.setdefault(key, []).append(position)
                self._index, self._by_title = rows, by_title
        return self._index, self._by_title

    def search(self, title, artist, *, context=None):
        index, by_title = self._load()
        wanted = {title_key(name) for name in title_names(title, context)}
        positions = sorted({position for key in wanted for position in by_title.get(key, ())},
                           reverse=True)  # Newest publications first, as before.
        count = 0
        for position in positions:
            row = index[position]
            meta = dict(row.get("metadata") or [])
            names = meta.get("musicName") or []
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
