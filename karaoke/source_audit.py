"""Thread-safe source outcomes, including misses and rejected editions."""
from collections import Counter
import threading


class SourceAudit:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows = []

    def record(self, source, status, title, artist, **details):
        with self._lock:
            self._rows.append(dict(source=source, status=status, title=title,
                                   artist=artist, **details))

    def snapshot(self):
        with self._lock:
            rows = list(self._rows)
        sources = {}
        for row in rows:
            sources.setdefault(row["source"], Counter())[row["status"]] += 1
        return {"sources": {name: dict(counts) for name, counts in sources.items()},
                "attempts": rows}
