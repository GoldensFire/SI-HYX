"""Karaoke Mugen authored lyrics and recording metadata."""
from __future__ import annotations

from urllib.parse import urlencode, quote
from .model import Track
from .search import queries

BASE = "https://kara.moe"


class Mugen:
    def __init__(self, http):
        self.http = http

    def search(self, title, artist, *, context=None):
        seen = set()
        for query in queries(title, artist, context):
            data = self.http.json(BASE + "/api/karas/search?" + urlencode(
                {"filter": query, "size": 30}), maximum=4_000_000)
            for track in self.tracks(data):
                if track.lyrics_url not in seen:
                    seen.add(track.lyrics_url)
                    yield track

    @staticmethod
    def tracks(data):
        for row in data.get("content", []):
            lyrics = row.get("lyrics_infos") or []
            lyric = next((item for item in lyrics if item.get("default")), lyrics[0] if lyrics else {})
            if not str(lyric.get("filename", "")).endswith(".ass"):
                continue
            titles = row.get("titles") or {}
            names = list(titles.values()) + list(row.get("titles_aliases") or [])
            singers = [tag["name"] for tag in row.get("singers", [])]
            groups = [tag["name"] for tag in row.get("singergroups", [])]
            yield Track(titles.get("qro") or titles.get(row.get("titles_default_language")) or names[0],
                        singers, float(row.get("duration") or 0), "Karaoke Mugen",
                        BASE + "/downloads/lyrics/" + quote(lyric["filename"], safe=""),
                        BASE + "/downloads/medias/" + quote(row["mediafile"], safe=""),
                        aliases=names, artist_groups=groups,
                        version=" ".join([*names, *[t["name"] for t in row.get("versions", [])]]))
