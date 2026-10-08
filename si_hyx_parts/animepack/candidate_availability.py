"""Cheap, cached availability probes before a candidate uses a media slot."""
from collections import Counter

from .average_selection import priority, selection_fits, selection_questions


def probe(generator, candidate):
    settings = generator.s
    from .candidate_options import available_kinds
    quotas = getattr(generator, '_selection_quotas', settings.question_quotas)
    candidate._possible_kinds = available_kinds(generator, candidate, quotas)
    # Сетевые пробы — только под роды, где ещё есть места. Иначе, пока
    # добирается манга, поток аниме спрашивал кадры AniList у каждого тайтла
    # и полчаса упирался в 429.
    used = Counter(c.kind for c in selection_questions(generator))
    open_kinds = [k for k in candidate._possible_kinds if used[k] < quotas.get(k, 0)]
    if not any(selection_fits(generator, candidate, kind) for kind in open_kinds):
        # Keep it for a later state of the pack; no HTTP probe is useful now.
        candidate._availability_deferred = True
        return
    candidate._availability_deferred = False
    # With AI the probe still runs: candidates with verified authored timing
    # rank first and avoid the shared model queue.
    if (candidate.kind in open_kinds and candidate.kind in ('opening', 'ending', 'insert')
            and settings.karaoke_enabled and settings.karaoke_percent
            and settings.karaoke_effect != 'reverse'):
        from karaoke.identity import context
        from karaoke.budget import attempt
        from .karaoke_processing import known_rejection, instrumental, catalog_duration
        if known_rejection(generator, candidate) or instrumental(candidate):
            candidate._authored_available = False
        else:
            with generator._timed('доступность таймингов, пачки'), attempt(generator.stopped, 30):
                candidate._authored_available = generator.karaoke_resolver.authored_available(
                    candidate.song_name, candidate.artist,
                    context(candidate.song, candidate.anime, candidate.kind),
                    duration=catalog_duration(candidate))
    if any(kind in ('frame', 'pixel') for kind in open_kinds):
        candidate._available_frames = generator._frame_urls(candidate.anime)
        candidate._frame_probe_done = True
        candidate._available_frame_mal = candidate.mal_id
        if not candidate._available_frames:
            candidate._possible_kinds = [kind for kind in candidate._possible_kinds
                                         if kind not in ('frame', 'pixel')]


def rank(generator, candidate):
    available = getattr(candidate, '_authored_available', None)
    from .candidate_options import available_kinds
    quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
    used = Counter(c.kind for c in selection_questions(generator))
    options = [k for k in available_kinds(generator, candidate, quotas)
               if used[k] < quotas.get(k, 0)]
    if getattr(candidate, '_frame_probe_done', False) and not candidate._available_frames:
        options = [k for k in options if k not in ('frame', 'pixel')]
    fitting = [k for k in options if selection_fits(generator, candidate, k)]
    return (not fitting, min((priority(generator, candidate, k) for k in fitting or options),
                            default=float('inf')), available is False)
