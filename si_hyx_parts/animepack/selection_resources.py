"""Scheduling permits are acquired before tasks enter the shared worker pool."""
from functools import wraps

import animepack as ap
from storage_guard import require_space


def capacity(kind, workers):
    # Each real reader worker now owns its cursor and request session.
    if kind == ap.MANGA_KIND:
        return workers
    if kind == ap.EPISODE_KIND:
        # Отрывки — самый долгий этап каждого прогона (50–60 % времени), а ждут
        # они в основном сеть: AV1 ограничен отдельно, HTTP — по хостам.
        return max(1, min(6, workers * 3 // 4))
    return workers * 2


def take_deferred(deferred, inflight, workers):
    for index in range(len(deferred) - 1, -1, -1):
        candidate = deferred[index]
        if inflight[candidate.kind] < capacity(candidate.kind, workers):
            return deferred.pop(index)
    return None


def guarded_fetch(generator):
    @wraps(generator._fetch_media)
    def fetch(candidate):
        if getattr(generator, "_storage_error", None):
            raise generator._storage_error
        require_space(generator.folder)
        from .media_transfer import trouble_reset, trouble_seen
        from .visual_batch import hold, wait_reset, wait_seen
        trouble_reset()
        wait_reset()
        try:
            # Проверки картинок Gemini на паузе: вопрос, которому они нужны,
            # ждёт её конца, не скачивая медиа впустую.
            result = False if hold(generator, candidate) else generator._fetch_media(candidate)
            # Сорвалось на сбое сети или паузе Gemini — тайтл откладывается на повтор.
            candidate._gemini_wait_until = 0.0 if result else wait_seen()
            candidate._network_temporary = not result and (
                trouble_seen() or candidate._gemini_wait_until > 0)
            return result
        finally:
            if getattr(generator, "_storage_error", None):
                raise generator._storage_error
            require_space(generator.folder)
    return fetch
