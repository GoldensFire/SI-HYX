"""PetitLyrics timing + Uta-Net Romaji, before acoustic AI fallback."""
import hashlib

from .petitlyrics import PetitLyrics
from .uta_net import UtaNet
from .text_alignment import transfer

SOURCE = "PetitLyrics + Uta-Net Global"
POLICY = "petit-uta-v1"


class PairedLyrics:
    def __init__(self, http, audit, log=lambda _: None):
        self.petit = PetitLyrics(http, audit)
        self.uta = UtaNet(http, audit)
        self.audit, self.log = audit, log

    def available(self, title, artist, context=None):
        """Есть ли издание с таким названием и исполнителем и романдзи к нему.

        Длительность записи здесь не известна: версию проверит resolve()."""
        if not self.petit.identities(title, artist, context):
            return False
        return bool(self.uta.search(title, artist, context))

    def resolve(self, title, artist, duration, context=None):
        options = self.petit.search(title, artist, duration, context)
        if not options:
            self.audit.record("PetitLyrics", "no_matching_edition", title, artist)
            return None
        sheet = self.uta.search(title, artist, context)
        if not sheet:
            return None
        for option in options:
            try:
                timed = self.petit.timings(option)
                self.audit.record("PetitLyrics", "timing", title, artist, id=option.id, level=timed.level)
                lines, alignment = transfer(timed, sheet)
            except ValueError as error:
                self.audit.record(SOURCE, "rejected", title, artist, id=option.id, reason=str(error))
                self.log(f"Караоке: {SOURCE}, ID {option.id}: {error}")
                continue
            self.audit.record(SOURCE, "used", title, artist, id=option.id, **alignment)
            return lines, {"source": SOURCE, "lyrics_url": option.url, "romaji_url": sheet.url,
                           "lyrics_sha256": hashlib.sha256(option.payload).hexdigest(),
                           "romaji_sha256": hashlib.sha256("\n".join(sheet.romaji).encode()).hexdigest(),
                           "offset": 0.0, "alignment": alignment, "ai_used": False,
                           "recording": {"method": "exact-title-artist-duration",
                                         "reference_duration": option.duration, "duration": duration,
                                         "lyrics_id": option.id, "album": option.album,
                                         "audio_fingerprint_verified": False}}
        return None
