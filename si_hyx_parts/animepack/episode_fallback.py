"""Use ready Kuhi providers immediately, retaining every unfinished alternative."""
from contextlib import closing
import time

from .episode_sources import episode_catalog, playable


def native(generator, candidate, aid, ctx, final, scope, batches):
    from .episode_generation import EPISODE_ATTEMPTS, _verified, _try_cut, _finish
    selected = []
    for batch in batches:
        catalog = episode_catalog(batch)
        names = ", ".join((batch.get("providers") or {}).keys())
        generator.log(f"Kuhi / AniList {aid}: готовы серии — {names}.")
        numbers = [n for n in selected if n in catalog]
        extra = [n for n in catalog if n not in selected]
        generator.rng.shuffle(extra)
        numbers += extra[:max(0, EPISODE_ATTEMPTS - len(selected))]
        selected.extend(n for n in numbers if n not in selected)
        for episode in numbers:
            if generator.stopped() or time.monotonic() >= scope.deadline:
                return False
            with closing(generator.kuhi.stream_batches(aid, episode, ctx, catalog[episode], scope)) as sources:
                for streams in sources:
                    generator.log(f"Kuhi / AniList {aid}, серия {episode}: готовы потоки {len(streams)}.")
                    for stream in _verified(generator, playable(streams), final, scope):
                        if generator.stopped() or time.monotonic() >= scope.deadline:
                            return False
                        start = _try_cut(generator, candidate, stream, final, scope)
                        if start is not None and _finish(generator, candidate, aid, episode, stream, start, final, scope):
                            return True
    return False
