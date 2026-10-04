"""Priority chain and mandatory recording verification before trusting timing."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile

from .amll import Amll
from .ass import read_ass
from .http import Http
from .lyrics import LyricSites, add_translations
from .matching import decode, metadata_matches, verify_audio
from .mugen import Mugen
from .ttml import read_ttml
from .model import Line, Unit, validate
from .rejections import Rejections, SourceRejected, cache_key, AI_POLICY
from .search import SEARCH_POLICY


class Resolver:
    def __init__(self, session, settings, ffmpeg, run, *, stopped=lambda: False, log=lambda _: None,
                 cache=None):
        self.settings, self.ffmpeg, self.run = settings, ffmpeg, run
        self.stopped, self.log = stopped, log
        self.http = Http(session, stopped=stopped, cache=cache)
        self.providers = [Mugen(self.http), Amll(self.http)]
        self.lyrics = LyricSites(self.http, log)
        self.cache = Path(cache or Path.home() / ".cache/si-hyx-karaoke") / "verified"
        self.rejections = Rejections(self.cache.parent)

    def resolve(self, source, title, artist, context=None):
        source = Path(source)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        key = cache_key(sha, title, artist, "karaoke-v6", SEARCH_POLICY, context or {})
        target = self.cache / (key + ".json")
        if target.is_file():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                lines = [Line(row["start"], row["end"], [Unit(**u) for u in row["units"]],
                              row.get("translations", {}), row.get("cutoff")) for row in data["lines"]]
                if self.settings.karaoke_ai_fallback or not data["metadata"].get("ai_used"):
                    return self._present(validate(lines), data["metadata"], title, artist, target, context)
            except (ValueError, KeyError, TypeError):
                target.unlink(missing_ok=True)
        rejection_key = cache_key(key, "song", bool(self.settings.karaoke_ai_fallback))
        if self.settings.karaoke_ai_fallback:
            rejection_key = cache_key(rejection_key, AI_POLICY)
        rejected = self.rejections.get(rejection_key)
        if rejected:
            raise SourceRejected("Недельный кэш: " + rejected)
        audio = decode(source, self.ffmpeg, self.run)
        from cover_audio import SR
        duration = len(audio) / SR
        metadata = {"source_audio_sha256": sha, "duration": duration, "ai_used": False,
                    "title": title, "artist": artist}
        found = None
        transient_error = False
        for provider in self.providers:
            if self.stopped():
                raise RuntimeError("Караоке: остановлено.")
            try:
                options = {"context": context} if context else {}
                for track in provider.search(title, artist, **options):
                    if not metadata_matches(title, artist, duration, track,
                                            aliases=(context or {}).get("titles", []),
                                            artists=(context or {}).get("artists", [])):
                        continue
                    track_key = cache_key(key, track.source, track.lyrics_url, track.audio_url)
                    if self.rejections.get(track_key):
                        continue
                    try:
                        payload = track.payload or self.http.bytes(track.lyrics_url, maximum=4_000_000)
                        parser = read_ass if track.format == "ass" else read_ttml
                        lines = parser(payload)
                        with tempfile.TemporaryDirectory(prefix="karaoke-reference-") as directory:
                            reference = Path(directory) / "reference.audio"
                            reference.write_bytes(self.http.bytes(track.audio_url, ttl=7 * 86400))
                            verdict = verify_audio(audio, decode(reference, self.ffmpeg, self.run))
                        metadata.update(source=track.source, lyrics_url=track.lyrics_url,
                                        reference_url=track.audio_url,
                                        lyrics_sha256=hashlib.sha256(payload).hexdigest(),
                                        recording=verdict, offset=verdict["offset"])
                        found = lines
                        break
                    except Exception as error:
                        if self.stopped():
                            raise
                        if isinstance(error, ValueError):
                            self.rejections.put(track_key, error)
                        else:
                            transient_error = True
                        self.log(f"Караоке: {track.source}, «{track.title}»: {str(error)[:180]}")
                if found:
                    break
            except Exception as error:
                if self.stopped():
                    raise
                transient_error = True
                self.log(f"Караоке: {type(provider).__name__}: {str(error)[:180]}")
        if found is None:
            if not self.settings.karaoke_ai_fallback:
                reason = "Не найден ASS/TTML для этой записи; AI fallback выключен."
                if not transient_error:
                    self.rejections.put(rejection_key, reason)
                    raise SourceRejected(reason)
                raise ValueError(reason)
            from .fallback import align
            sheet = self.lyrics.search(title, artist, duration=duration, context=context)
            found = align(source, sheet, self.settings, stopped=self.stopped, log=self.log)
            metadata.update(source="Whisper + lyric-align (Kim ONNX / HTDemucs)", offset=0.0, ai_used=True,
                            lyrics_url=sheet.url, recording={"aligned_to_source_sha256": sha})
        return self._present(found, metadata, title, artist, target, context)

    def _present(self, lines, metadata, title, artist, target, context=None):
        metadata = dict(metadata)
        if self.settings.karaoke_translations and not metadata.get("translation_checked"):
            sheet = self.lyrics.search(title, artist, duration=metadata["duration"], context=context)
            add_translations(lines, sheet)
            metadata["translation_checked"] = True
            if sheet:
                metadata["translation_url"] = sheet.url
        self.cache.mkdir(parents=True, exist_ok=True)
        data = {"lines": [asdict(line) for line in lines], "metadata": metadata}
        with tempfile.NamedTemporaryFile(dir=self.cache, delete=False, mode="w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            temporary = Path(stream.name)
        temporary.replace(target)
        if not self.settings.karaoke_translations:
            lines = [Line(row.start, row.end, row.units, cutoff=row.cutoff) for row in lines]
            metadata.pop("translation_url", None)
        return lines, metadata
