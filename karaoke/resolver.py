"""Priority chain and mandatory recording verification before trusting timing."""
from __future__ import annotations

from contextlib import nullcontext
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import time

from .amll import Amll
from .ass import read_ass
from .http import Http, MediaUnavailable
from .lyrics import LyricSites, add_translations
from .matching import decode, metadata_matches, metadata_mismatch, verify_audio
from .mugen import Mugen
from .ttml import read_ttml
from .model import Line, Unit, validate
from .rejections import Rejections, SourceRejected, cache_key, AI_POLICY, REFERENCE_POLICY
from .search import SEARCH_POLICY
from .paired_lyrics import PairedLyrics, POLICY
from .source_audit import SourceAudit
from .availability import TemporaryUnavailable, temporary
from .files import replace_file
from storage_guard import raise_if_full


class Resolver:
    def __init__(self, session, settings, ffmpeg, run, *, stopped=lambda: False, log=lambda _: None,
                 cache=None, timed=None, authored_sources=True, excerpt_duration=0):
        self.settings, self.ffmpeg, self.run = settings, ffmpeg, run
        self.stopped, self.log = stopped, log
        self.timed = timed
        self.http = Http(session, stopped=stopped, cache=cache)
        self.authored_sources = authored_sources
        self.excerpt_duration = excerpt_duration
        self.providers = [Mugen(self.http), Amll(self.http)] if authored_sources else []
        self.audit = SourceAudit()
        self.lyrics = LyricSites(self.http, log, audit=self.audit)
        self.paired = PairedLyrics(self.http, self.audit, log)
        self.cache = Path(cache or Path.home() / ".cache/si-hyx-karaoke") / "verified"
        self.rejections = Rejections(self.cache.parent)
        self._bad_references = {}
        self._devices = {}  # ML devices are probed once per run.

    def _stage(self, name):
        return self.timed(name) if self.timed else nullcontext()

    def _searched(self, provider, title, artist, options):
        """Provider results with the search time measured apart from verification."""
        found = iter(provider.search(title, artist, **options))
        while True:
            with self._stage("караоке: поиск изданий"):
                track = next(found, None)
            if track is None:
                return
            yield track

    def authored_available(self, title, artist, context=None, duration=None):
        """Есть ли хоть один кандидат готовых таймингов — до загрузки записи.

        True — кандидат есть (запись всё равно проверяется в resolve()), False —
        ни один источник ничего подходящего не знает, None — источник не ответил
        и судить нельзя. Поиски кэшируются Http, resolve() их не повторит.
        duration — длина записи из каталога: издание полной версии (258 с против
        89 с у TV-size) отсекается до загрузки; без неё длительность не сравнивается."""
        if not self.authored_sources:
            return None
        unknown = False
        context = context or {}
        options = {"context": context} if context else {}
        for provider in self.providers:
            try:
                for track in self._searched(provider, title, artist, options):
                    if metadata_matches(title, artist, float(duration or 0), track,
                                        aliases=context.get("titles", []),
                                        artists=context.get("artists", []),
                                        lineup=context.get("performer_lineup", [])):
                        return True
            except Exception:
                if self.stopped():
                    raise
                unknown = True
        try:
            if self.paired.available(title, artist, context):
                return True
        except Exception:
            if self.stopped():
                raise
            unknown = True
        return None if unknown else False

    def resolve(self, source, title, artist, context=None):
        source = Path(source)
        sha = hashlib.sha256(source.read_bytes()).hexdigest()
        key = cache_key(sha, title, artist, "karaoke-v8", SEARCH_POLICY, REFERENCE_POLICY, context or {})
        if not self.authored_sources:
            key = cache_key(key, "untimed-lyrics-only-v2", AI_POLICY)
        if self.excerpt_duration:
            key = cache_key(key, "confirmed-excerpt-v1", self.excerpt_duration)
        target = self.cache / (key + ".json")
        if target.is_file():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                lines = [Line(row["start"], row["end"], [Unit(**u) for u in row["units"]],
                              row.get("translations", {}), row.get("cutoff")) for row in data["lines"]]
                ai_cached = data["metadata"].get("ai_used")
                if (not ai_cached or (self.settings.karaoke_ai_fallback
                                      and data["metadata"].get("source_policy") == POLICY)):
                    self.audit.record(data["metadata"]["source"], "cache_used", title, artist)
                    return self._present(validate(lines), data["metadata"], title, artist, target, context)
            except (ValueError, KeyError, TypeError):
                target.unlink(missing_ok=True)
        rejection_key = cache_key(key, "song", POLICY, REFERENCE_POLICY,
                                  bool(self.settings.karaoke_ai_fallback))
        if self.settings.karaoke_ai_fallback:
            rejection_key = cache_key(rejection_key, AI_POLICY)
        rejected = self.rejections.get(rejection_key)
        if rejected:
            raise SourceRejected("Недельный кэш: " + rejected)
        audio = decode(source, self.ffmpeg, self.run)
        from cover_audio import SR
        duration = len(audio) / SR
        metadata = {"source_audio_sha256": sha, "duration": duration, "ai_used": False,
                    "source_policy": POLICY,
                    "title": title, "artist": artist}
        found = None
        transient_error = False
        for provider in self.providers:
            if self.stopped():
                raise RuntimeError("Караоке: остановлено.")
            try:
                provider_name = {"Mugen": "Karaoke Mugen", "Amll": "AMLL TTML"}.get(
                    type(provider).__name__, type(provider).__name__)
                self.audit.record(provider_name, "searched", title, artist)
                options = {"context": context} if context else {}
                for track in self._searched(provider, title, artist, options):
                    if self._bad_references.get(track.audio_url, 0) > time.monotonic():
                        transient_error = True
                        continue
                    mismatch = metadata_mismatch(title, artist, duration, track,
                                                 aliases=(context or {}).get("titles", []),
                                                 artists=(context or {}).get("artists", []),
                                                 lineup=(context or {}).get("performer_lineup", []))
                    if mismatch:
                        self.audit.record(track.source, "metadata_rejected", title, artist,
                                          reason=mismatch, lyrics_url=track.lyrics_url,
                                          edition=track.title, edition_duration=track.duration)
                        continue
                    track_key = cache_key(key, REFERENCE_POLICY, track.source,
                                          track.lyrics_url, track.audio_url)
                    if self.rejections.get(track_key):
                        continue
                    try:
                        payload = track.payload or self.http.bytes(track.lyrics_url, maximum=4_000_000)
                        parser = read_ass if track.format == "ass" else read_ttml
                        lines = parser(payload)
                        with tempfile.TemporaryDirectory(prefix="karaoke-reference-", dir=source.parent) as directory:
                            reference = Path(directory) / "reference.audio"
                            with self._stage("караоке: загрузка эталона"):
                                reference.write_bytes(self.http.bytes(track.audio_url, ttl=7 * 86400, media=True))
                            try:
                                with self._stage("караоке: декодирование эталона"):
                                    decoded = decode(reference, self.ffmpeg, self.run)
                            except (ValueError, OSError) as error:
                                raise MediaUnavailable(str(error)) from error
                            with self._stage("караоке: аудиоотпечатки"):
                                verdict = verify_audio(audio, decoded)
                        metadata.update(source=track.source, lyrics_url=track.lyrics_url,
                                        reference_url=track.audio_url,
                                        lyrics_sha256=hashlib.sha256(payload).hexdigest(),
                                        reference_artists=track.artists,
                                        reference_artist_groups=track.artist_groups,
                                        reference_policy=REFERENCE_POLICY,
                                        recording=verdict, offset=verdict["offset"])
                        found = lines
                        self.audit.record(track.source, "used", title, artist)
                        break
                    except Exception as error:
                        raise_if_full(error, source.parent)
                        if self.stopped():
                            raise
                        unreadable = isinstance(error, MediaUnavailable)
                        if unreadable:
                            self.http.invalidate(track.audio_url)
                        if unreadable or isinstance(error, RuntimeError):
                            if len(self._bad_references) >= 256:
                                self._bad_references.clear()
                            self._bad_references[track.audio_url] = time.monotonic() + 300
                        if isinstance(error, ValueError) and not unreadable and not temporary(error):
                            self.rejections.put(track_key, error)
                        else:
                            transient_error = True
                        self.log(f"Караоке: {track.source}, «{track.title}»: {str(error)[:180]}")
                        self.audit.record(track.source, "rejected" if isinstance(error, ValueError) else "error",
                                          title, artist, reason=str(error)[:300])
                if found:
                    break
                self.audit.record(provider_name, "no_match", title, artist)
            except Exception as error:
                raise_if_full(error, source.parent)
                if self.stopped():
                    raise
                transient_error = True
                self.audit.record(provider_name, "error", title, artist, reason=str(error)[:300])
                self.log(f"Караоке: {type(provider).__name__}: {str(error)[:180]}")
        if found is None and self.authored_sources:
            try:
                paired = self.paired.resolve(title, artist, duration, context)
                if paired:
                    found, details = paired
                    metadata.update(details)
            except Exception as error:
                raise_if_full(error, source.parent)
                if self.stopped():
                    raise
                transient_error = True
                self.audit.record("PetitLyrics + Uta-Net Global", "error", title, artist,
                                  reason=str(error)[:300])
                self.log(f"Караоке: PetitLyrics + Uta-Net Global: {str(error)[:180]}")
        if found is None:
            if not self.settings.karaoke_ai_fallback:
                reason = "Не найдены готовые тайминги этой версии; AI fallback выключен."
                if not transient_error:
                    self.rejections.put(rejection_key, reason)
                    raise SourceRejected(reason)
                raise TemporaryUnavailable("Источники таймингов временно не ответили; отсутствие таймингов не подтверждено.")
            from .fallback import align
            sheet = self.lyrics.search(title, artist, duration=duration, context=context)
            details = {}
            options = {"excerpt_duration": self.excerpt_duration} if self.excerpt_duration else {}
            try:
                found = align(source, sheet, self.settings, stopped=self.stopped,
                              log=self.log, timed=self.timed, details=details, devices=self._devices,
                              cache=self.cache.parent / "alignment", **options)
            except Exception as error:
                self.audit.record("Whisper + lyric-align", "error", title, artist,
                                  lyrics_url=sheet.url if sheet else None, reason=str(error)[:500])
                raise
            backend = details.get("separator_backend") or (
                "HTDemucs" if getattr(self.settings, "karaoke_separator", "auto") == "htdemucs"
                else "Kim ONNX / HTDemucs")
            metadata.update(source=f"Whisper + lyric-align ({backend})", offset=0.0, ai_used=True,
                            lyrics_url=sheet.url, recording={"aligned_to_source_sha256": sha},
                            timing_origin="source_audio_asr",
                            original_lyrics_sha256=hashlib.sha256(
                                "\n".join(sheet.original).encode("utf-8")).hexdigest(),
                            original_lyrics_lines=len(sheet.original))
            if not self.authored_sources:
                metadata["authored_timing_sources_excluded"] = True
            metadata.update(details)
            self.audit.record(metadata["source"], "used", title, artist)
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
            written = Path(stream.name)
        replace_file(written, target)
        if not self.settings.karaoke_translations:
            lines = [Line(row.start, row.end, row.units, cutoff=row.cutoff) for row in lines]
            metadata.pop("translation_url", None)
        return lines, metadata
