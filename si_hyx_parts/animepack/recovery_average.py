"""Repair a saved average by replacing only questions that move it off target."""
import animepack as ap

from .level_avg import own_bucket, level_avg_target, question_level
from si_hyx_parts.animepack.generator_selection import _level_ok

CHEAP_KINDS = (ap.PIXEL_KIND, ap.FRAME_KIND, ap.CHAR_KIND,
               ap.PIXIV_ART_KIND, ap.EPISODE_KIND, ap.SAKUGA_KIND, ap.STUDIO_KIND)


def repair(generator, songs):
    groups = {}
    for candidate in songs:
        groups.setdefault(own_bucket(generator.s, candidate.kind), []).append(candidate)
    targets = {bucket: level_avg_target(generator.s, bucket) for bucket in groups}
    gaps = {bucket: sum(question_level(c) for c in rows) - targets[bucket] * len(rows)
            for bucket, rows in groups.items() if targets[bucket]}
    if not any(gaps.values()):
        return 0
    generator.log('Исправляю среднюю сохранённых вопросов; готовые подходящие медиа сохраняются.')
    generator.load_exclusions()
    used = {c.mal_id for c in songs if not c.is_manga}
    franchises = generator._used_franchise
    franchises.update(str(c.anime.get('franchise') or '') for c in songs
                      if c.anime.get('franchise'))
    cards = list(generator.db_cache.all_cards('anime'))
    # Raw popularity is a cheap first pass; verified franchise indexes follow.
    cards.sort(key=lambda card: -ap.SongCandidate({}, card).index)
    replacements = 0
    examined = 0
    easy_available = 0
    for start in range(0, len(cards), 40):
        batch = cards[start:start + 40]
        generator._load_franchise_indexes(batch)
        for card in batch:
            if generator.stopped():
                raise ap.AnimePackError('Добор сохранённых вопросов остановлен.')
            if not any(gaps.values()):
                generator.log(f'Средняя исправлена: заменено только {replacements} вопросов.')
                return replacements
            probe = ap.SongCandidate({}, card, franchise_index=generator._franchise_index(card))
            examined += 1
            if probe.level <= 2:
                easy_available += 1
            if not generator._accept_anime(card, probe.mal_id, used, franchises):
                continue
            probe._reserved = generator._last_reserved
            probe.favorites = generator._title_favorites(probe)
            choices = []
            for index, old in enumerate(songs):
                bucket = own_bucket(generator.s, old.kind)
                gap = gaps.get(bucket, 0)
                if not gap or old.kind not in CHEAP_KINDS or getattr(old, 'selection_level', None) is not None:
                    continue
                if not _level_ok(generator.s, probe, old.kind):
                    continue
                delta = question_level(old) - probe.level
                if delta * gap > 0 and abs(delta) <= abs(gap):
                    choices.append((abs(delta), -CHEAP_KINDS.index(old.kind), index, bucket))
            if not choices:
                generator._release_candidate(probe)
                used.discard(probe.mal_id)
                continue
            _, _, index, bucket = max(choices)
            old = songs[index]
            probe.kind = old.kind
            probe.media_base = generator._media_base(probe)
            probe.compress_images = generator.s.compress_images
            if not generator._fetch_media(probe):
                generator._release_candidate(probe)
                used.discard(probe.mal_id)
                continue
            delta = question_level(old) - probe.level
            if not delta * gaps[bucket] > 0 or abs(delta) > abs(gaps[bucket]):
                generator._release_candidate(probe)
                used.discard(probe.mal_id)
                continue
            songs[index] = probe
            gaps[bucket] -= delta
            replacements += 1
            generator.log(f'Добор средней: заменено {replacements}; ' +
                          ', '.join(f'отклонение суммы уровней {gap:+d}' for gap in gaps.values()))
    remaining = ', '.join(f'{bucket or "общая"}: {gap:+d}' for bucket, gap in gaps.items() if gap)
    raise ap.AnimePackError(
        f'Среднюю ещё нельзя получить из доступных источников ({remaining}). '
        f'Проверено карточек {examined}, уровня 1–2 среди них {easy_available}; '
        'также действуют фильтры, исключённые франшизы и доступность проверенного медиа.')
