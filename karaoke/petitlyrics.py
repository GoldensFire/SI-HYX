"""PetitLyrics app protocol: bounded editions, pinned IDs and real timing tiers."""
from dataclasses import dataclass
import base64
import os
from xml.etree import ElementTree as ET

from .identity import exact_identity, recording_matches
from .petit_timing import word_sync, line_sync
from .search import title_names, artist_names

ENDPOINT = "https://p0.petitlyrics.com/api/GetPetitLyricsData.php"


@dataclass
class Edition:
    id: str
    title: str
    artist: str
    album: str
    duration: float
    payload: bytes
    tier: int

    @property
    def url(self):
        return "https://petitlyrics.com/lyrics/" + self.id


class PetitLyrics:
    def __init__(self, http, audit):
        self.http, self.audit = http, audit
        # Public client identifier observed in the app protocol; deployments can
        # supply their registered identifier without editing the adapter.
        self.client_id = os.environ.get("SI_HYX_PETITLYRICS_APP_ID", "p1110417")

    def request(self, title, artist, *, tier=3, id=""):
        data = dict(clientAppId=self.client_id, terminalType="10", lyricsType=str(tier),
                    key_title=title, key_artist=artist, key_album="", maxCount="20")
        if id:
            data["key_lyricsId"] = id
        payload = self.http.post(ENDPOINT, data, headers={"User-Agent": "SI-HYX/1.0"})
        tree = ET.fromstring(payload)
        status = tree.findtext("status")
        if status != "00000000":
            raise RuntimeError("PetitLyrics: API status " + str(status))
        result = []
        for song in tree.findall("./songs/song")[:20]:
            identity = song.findtext("lyricsId") or ""
            if not identity.isdecimal():
                continue
            raw = base64.b64decode(song.findtext("lyricsData") or "", validate=True)
            result.append(Edition(identity, song.findtext("title") or "",
                                  song.findtext("artist") or "", song.findtext("album") or "",
                                  float(song.findtext("duration") or 0) / 1000, raw,
                                  int(song.findtext("lyricsType") or 0)))
        return result

    def identities(self, title, artist, context=None):
        """Издания с точным названием и исполнителем — без проверки версии записи."""
        for name in title_names(title, context)[:3]:
            for singer in artist_names(artist, context)[:2]:
                found = [option for option in self.request(name, singer)
                         if exact_identity(title, artist, option.title, option.artist, context)]
                if found:
                    return found
        return []

    def search(self, title, artist, duration, context=None):
        seen = set()
        accepted = []
        for name in title_names(title, context)[:3]:
            for singer in artist_names(artist, context)[:2]:
                options = self.request(name, singer)
                self.audit.record("PetitLyrics", "response", title, artist, editions=len(options))
                for option in options:
                    if option.id in seen:
                        continue
                    seen.add(option.id)
                    if not exact_identity(title, artist, option.title, option.artist, context):
                        self.audit.record("PetitLyrics", "identity_rejected", title, artist, id=option.id,
                                          actual_title=option.title, actual_artist=option.artist)
                    elif not recording_matches(title, duration, option):
                        self.audit.record("PetitLyrics", "version_rejected", title, artist,
                                          id=option.id, duration=option.duration,
                                          actual_title=option.title, album=option.album)
                    else:
                        accepted.append(option)
                if accepted:
                    # Try all distinct publications of the matching recording.
                    return sorted(accepted, key=lambda e: (e.tier != 3, abs(e.duration - duration)))
        return accepted

    def timings(self, option):
        if not option.payload:
            loaded = next((item for item in self.request(option.title, option.artist, id=option.id)
                           if item.id == option.id and item.title == option.title
                           and item.artist == option.artist and item.duration == option.duration), None)
            if loaded is None or not loaded.payload:
                raise ValueError("PetitLyrics: тайминги выбранного ID недоступны.")
            option.payload, option.tier = loaded.payload, loaded.tier
        if option.tier == 3:
            return word_sync(option.payload, option.duration)
        if option.tier != 2:
            raise ValueError("PetitLyrics: доступен только текст без таймингов.")
        # Joining text from a different upload can silently shift every line.
        plain = next((item for item in self.request(option.title, option.artist, tier=1,
                     id=option.id) if item.id == option.id and item.tier == 1
                     and item.title == option.title and item.artist == option.artist
                     and abs(item.duration - option.duration) < .001), None)
        if plain is None:
            raise ValueError("PetitLyrics: текст LSY для выбранного ID недоступен.")
        return line_sync(option.payload, plain.payload.decode("utf-8-sig"), option.duration)
