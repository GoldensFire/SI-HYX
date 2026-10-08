"""Bounded source prefetch overlaps network I/O with the current encoder."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import nullcontext
import threading

import animepack as ap


class SongDownloads:
    def __init__(self, generator):
        self.generator = generator
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="song-download")
        self.stopping = threading.Event()

    def _load(self, url):
        if self.stopping.is_set() or self.generator.stopped():
            raise RuntimeError("Загрузка песни остановлена.")
        runtime = getattr(self.generator, "_runtime", None)
        worker = runtime.worker() if runtime else nullcontext()
        with worker:
            if runtime:
                runtime.local.candidate_stop = self.stopping
            try:
                with self.generator._timed("загрузка песен"):
                    return self.generator._cached_bytes(url, "amq-audio", ap._MIN_AUDIO_BYTES)
            finally:
                if runtime:
                    runtime.local.candidate_stop = None

    def submit(self, candidate):
        if not getattr(candidate, "_audio_download", None):
            url = f"{ap.AMQ_CDN}/{candidate.audio_file}"
            candidate._audio_download = self.pool.submit(self._load, url)

    def close(self):
        self.stopping.set()
        self.pool.shutdown(wait=True, cancel_futures=True)


def prefetch(generator, candidate):
    from .song_video import requested as wants_video
    if (not candidate.audio_file or candidate.music_effect not in {"original", "karaoke", "chiptune"}
            or wants_video(generator.s, candidate)):
        return
    # Karaoke's shared source queue also serves ordinary/chiptune slots in a mix.
    if not generator.s.karaoke_enabled:
        return
    if candidate.music_effect == "karaoke":
        # The worker first checks authored timing availability. Prefetching
        # here would still download every rejected song in the background.
        if not generator.s.karaoke_ai_fallback and generator.s.karaoke_effect != "reverse":
            return
        from .karaoke_processing import known_rejection
        if known_rejection(generator, candidate):
            return
    service = getattr(generator, "_song_downloads", None)
    if service is None:
        service = generator._song_downloads = SongDownloads(generator)
    service.submit(candidate)


def source_bytes(generator, candidate):
    from .song_audio_fallback import load
    try:
        return _source_bytes(generator, candidate)
    except Exception as error:
        return load(generator, candidate, error)


def _source_bytes(generator, candidate):
    future = getattr(candidate, "_audio_download", None)
    if future is not None:
        try:
            while True:
                if generator.stopped():
                    future.cancel()
                    raise RuntimeError("Загрузка песни остановлена.")
                try:
                    return future.result(timeout=.1)
                except TimeoutError:
                    if future.done():
                        raise
        finally:
            candidate._audio_download = None
    return generator._cached_bytes(f"{ap.AMQ_CDN}/{candidate.audio_file}",
                                   "amq-audio", ap._MIN_AUDIO_BYTES)


def close(generator):
    service = getattr(generator, "_song_downloads", None)
    if service is not None:
        service.close()
        generator._song_downloads = None
