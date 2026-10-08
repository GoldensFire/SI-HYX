"""Content-specific negative results expire after seven days, without renewal."""
import hashlib
import json
from pathlib import Path
import tempfile
import time

TTL = 7 * 86400
VERSION = "karaoke-rejections-v2"  # Old rejects may have counted the site's '+' expanders.
AI_POLICY = "multilingual-auto-demucs-budget-v6-windows"
REFERENCE_POLICY = "reference-validation-v4-edition-span-furigana"


class Rejected(ValueError):
    """A semantic failure, safe to remember; network and encoder errors are not."""


class SourceRejected(Rejected):
    """No verified timing for this recording, regardless of the requested crop."""


def cache_key(*values):
    return hashlib.sha256(json.dumps((VERSION, *values), ensure_ascii=False,
                                     sort_keys=True).encode()).hexdigest()


class Rejections:
    def __init__(self, root, *, clock=time.time):
        self.root, self.clock = Path(root) / "rejected", clock
        self.root.mkdir(parents=True, exist_ok=True)
        self.prune()

    def prune(self):
        for path in self.root.glob("*.json"):
            self._read(path)

    def _read(self, path):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data["expires"] > self.clock():
                return data["reason"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        path.unlink(missing_ok=True)
        return ""

    def get(self, key):
        return self._read(self.root / (key + ".json"))

    def put(self, key, reason):
        target = self.root / (key + ".json")
        if self.get(key):
            return
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False, mode="w",
                                         encoding="utf-8") as stream:
            json.dump({"expires": self.clock() + TTL, "reason": str(reason)[:500]}, stream)
            temporary = Path(stream.name)
        from .files import replace_file
        replace_file(temporary, target)
