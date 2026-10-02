# -*- coding: utf-8 -*-
"""Доступные формы вопроса и приоритет узких рамок узнаваемости."""
import animepack as ap


def available_kinds(generator, candidate, quotas):
    from .anime_pack_generator__media_base import _level_ok, _antonyms_ok
    from .title_selection import TITLE_QUESTION_KINDS, short_title

    origin = getattr(candidate, "_origin_kind", candidate.kind)
    candidate._origin_kind = origin
    options = [origin]
    if not candidate.is_manga and origin != ap.MANGA_KIND:
        options += [k for k in ap.SILENT_KINDS
                    if k not in (ap.MANGA_KIND, origin) and quotas.get(k, 0)]
        if (origin not in ap.SILENT_KINDS and origin != "insert"
                and quotas.get(ap.VIDEO_KIND, 0)):
            options.append(ap.VIDEO_KIND)
    tried = getattr(candidate, "_tried_kinds", ())
    free = [k for k in options if quotas.get(k, 0)
            and k not in generator._dead_kinds and k not in tried
            and _level_ok(generator.s, candidate, k)]
    title = getattr(candidate, "_title_variant", candidate)
    if title is None or not short_title(title.anime):
        free = [k for k in free if k not in TITLE_QUESTION_KINDS]
    if any(k in ap.GEMINI_TITLE_KINDS for k in free):
        from .title_eligibility import russian_title, verdict
        checked = verdict(getattr(generator, "_title_eligibility", {}),
                          russian_title(title))
        if not checked["eligible"]:
            free = [k for k in free if k not in ap.GEMINI_TITLE_KINDS]
        elif "antonyms" in free and not _antonyms_ok(checked, title):
            free.remove("antonyms")
    if ap.AI_ART_KIND in free:
        from animepack_art_filter import possible_art_title
        if not possible_art_title(candidate.anime):
            free.remove(ap.AI_ART_KIND)
    if ap.STUDIO_KIND in free:
        from .studio_question import studio_possible
        if not studio_possible(candidate.anime):
            free.remove(ap.STUDIO_KIND)
    return free


def choose_kind(settings, options, counts, inflight, quotas):
    """Узкие категории получают подходящие тайтлы раньше широких.

    Например, персонажи 1–5 заполняются лёгкими тайтлами прежде кадров 1–8.
    При одинаковых рамках остаётся прежний делёж по заполненности квот.
    """
    def priority(kind):
        low, high = settings.level_range(kind)
        return (high - low,
                (counts[kind] + inflight[kind]) / max(1, quotas[kind]))
    return min(options, key=priority)
