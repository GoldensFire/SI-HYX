"""Scheduling permits are acquired before tasks enter the shared worker pool."""
from functools import wraps

import animepack as ap
from storage_guard import require_space


def capacity(kind, workers):
    # Each real reader worker now owns its cursor and request session.
    if kind == ap.MANGA_KIND:
        return workers
    if kind == ap.EPISODE_KIND:
        return max(1, min(4, workers // 2))
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
        trouble_reset()
        try:
            result = generator._fetch_media(candidate)
            # Сорвалось на сбое сети — тайтл откладывается на повтор.
            candidate._network_temporary = not result and trouble_seen()
            return result
        finally:
            if getattr(generator, "_storage_error", None):
                raise generator._storage_error
            require_space(generator.folder)
    return fetch
