"""Search without holding the global page reservation lock."""
import animepack as ap


def pick(generator, candidate):
    from .manga_budget import check
    for _ in range(3):
        check(generator, candidate)
        with generator._frames_lock:
            excluded = set(generator._frames_used)
        selected = generator.mangadex.select_page(candidate.anime, excluded,
                    deadline=getattr(candidate, "_manga_deadline", None),
                    stopped=generator.stopped)
        for error in selected.errors:
            generator._log_rare("Источники манги", error)
        if selected.url:
            with generator._frames_lock:
                key = ap.frame_url_key(selected.url)
                if key in generator._frames_used:
                    continue
                generator._frames_used.add(key)
        candidate.source_link = selected.source_link
        candidate._manga_page_client = selected.client
        candidate._manga_page_info = selected.info
        return selected.url, selected.chapter, list(selected.titles)
    return "", "", []
