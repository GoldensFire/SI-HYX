"""Draw the required difficulty from the entire saved pool before HTTP/media."""
from collections import Counter, deque
from types import SimpleNamespace

import animepack as ap

from .average_selection import (aim_level, desired_level, selection_questions, fits,
                                level_snapshot)
from .catalog_profiles import profiles
from .level_inventory import attainable


def level_spread(generator, kinds, histogram):
    """Сколько карточек на каждом уровне диапазона пака и какая средняя нужна.

    Раньше строка показывала только «уровней 1–2» при любом диапазоне и любой
    средней. По распределению видно, хватит ли тайтлов под заданную середину:
    при средней 2 и диапазоне 1–4 уровней 1–2 нужно не меньше половины пака."""
    bands = [generator.s.level_range(k) for k in kinds]
    if not bands:
        return 'диапазон уровней не задан'
    low, high = min(b[0] for b in bands), max(b[1] for b in bands)
    inside = ', '.join(f'{level} — {histogram[level]}' for level in range(low, high + 1))
    text = f'по уровням {low}–{high}: {inside}'
    outside = sum(n for level, n in histogram.items() if not low <= level <= high)
    if outside:
        text += f'; вне диапазона {outside}'
    targets = sorted({ap.level_avg_target(generator.s, ap.own_bucket(generator.s, k))
                      for k in kinds} - {0, None})
    if targets:
        text += '; нужная средняя ' + ', '.join(str(t) for t in targets)
    return text


class CatalogPlan:
    def __init__(self, generator, pairs, manga=False):
        self.generator = generator
        self.manga = manga
        quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
        self.kinds = [k for k, n in quotas.items() if n and (k == ap.MANGA_KIND) == manga]
        self.active = any(ap.level_avg_target(generator.s, ap.own_bucket(generator.s, k))
                          or k == ap.CHAR_KIND and generator.s.char_level_avg for k in self.kinds)
        self.groups = {}
        self.stock = Counter()
        self.reachability = {}
        self.original = deque(pairs)
        if not self.active:
            return
        # ANN and MAL identifiers cannot be compared; AMQ cards are ranked
        # after their normal batched conversion to MAL.
        self.ann = not manga and generator._ids_are_ann
        if self.ann:
            # Keep the service's efficient bulk lookup when no local card
            # can be identified yet. CandidateSource ranks the resulting cards.
            self.active = False
            generator.log('Подбор по базе: AMQ — сначала получаю карточки тайтлов, '
                          'затем выбираю нужную сложность.')
            return
        index = profiles(generator, manga)
        histogram = Counter()
        for position, pair in enumerate(pairs):
            if generator.stopped():
                break
            candidate = index.get(pair[0])
            if candidate is not None:
                if not ap.filter_anime(candidate.anime, generator.s, manga=manga):
                    continue
                if generator._root_excluded(candidate.anime):
                    continue
                level = candidate.level
                histogram[level] += 1
                self.stock[level] += 1
                # Edition/adaptation groups keep different comic shares available.
                edition = str(candidate.anime.get('kind') or '') if manga else ''
                key = level, edition, bool(candidate.adapted_from), candidate._profile_incomplete
            else:
                key = None, '', False, True
            self.groups.setdefault(key, deque()).append((position, pair, candidate))
        index.flush()
        known = sum(histogram.values())
        generator.log(f'Подбор по базе: {"книги" if manga else "аниме"} — '
                      f'{known} карточек с рассчитанным уровнем; '
                      f'{level_spread(generator, self.kinds, histogram)}. '
                      'Сначала выбираю нужную сложность, затем проверяю источники.')

    def _attainable(self, level, kind, questions, quotas):
        from .level_avg import question_level
        gen = self.generator
        bucket = ap.own_bucket(gen.s, kind)
        target = ap.level_avg_target(gen.s, bucket)
        relevant = [k for k, n in quotas.items() if n and ap.own_bucket(gen.s, k) == bucket]
        bands = {gen.s.level_range(k) for k in relevant}
        # Different ranges/catalogues are checked by the ordinary quota
        # projection; this finite-stock check is exact for a shared band.
        if (not target or len(bands) != 1 or any(k not in self.kinds for k in relevant)
                or gen.s.char_level_avg and ap.CHAR_KIND in relevant
                or kind == ap.MANGA_KIND and gen.s.manga_strict_targets):
            return True
        seen = [question_level(c) for c in questions if ap.own_bucket(gen.s, c.kind) == bucket]
        slots = sum(quotas[k] for k in relevant) - len(seen) - 1
        points = target * sum(quotas[k] for k in relevant) - sum(seen) - level
        low, high = next(iter(bands))
        counts = {v: n - int(v == level) for v, n in self.stock.items() if low <= v <= high and n}
        key = slots, points, tuple(sorted(counts.items()))
        if key not in self.reachability:
            self.reachability[key] = attainable(counts, slots, points)
        return self.reachability[key]

    def _aims(self, questions, spare):
        """Уровень, к которому тянется этот выбор, по родам: нужный ± шаг."""
        gen = self.generator
        return {kind: aim_level(gen, kind, desired_level(gen, kind, () if spare else questions))
                for kind in self.kinds}

    def _score(self, group, questions, used, quotas, spare=False, aims=None):
        position, _pair, candidate = group[0]
        if candidate is None:
            return 1, 0, 0, position, None
        level = candidate.level
        aims = self._aims(questions, spare) if aims is None else aims
        choices = []
        for kind in self.kinds:
            if not spare and used[kind] >= quotas.get(kind, 0):
                continue
            low, high = self.generator.s.level_range(kind)
            if not low <= level <= high:
                continue
            wanted = aims.get(kind)
            distance = abs(level - wanted) if wanted is not None else 0
            fit = spare or fits(self.generator, candidate, [], kind, selected=questions)
            stock = spare or self._attainable(level, kind, questions, quotas)
            choices.append((0 if fit and stock else 2 if fit else 3,
                            distance, used[kind] / max(1, quotas[kind]), position, kind))
        return min(choices) if choices else (4, 0, 0, position, None)

    def batches(self, size):
        if not self.active:
            while self.original:
                yield [self.original.popleft()[0] for _ in range(min(size, len(self.original)))]
            return
        # Recalculate against the live pack after every small batch.
        size = min(size, 20)
        gen = self.generator
        while self.groups and not gen.stopped():
            # Уровни набранных считаются один раз на пачку, а не в каждом
            # _score: групп сотни, и иначе пачка из 20 книг шла минутами.
            questions = list(level_snapshot(gen, selection_questions(gen)))
            used = Counter(c.kind for c in questions)
            quotas = getattr(gen, '_selection_quotas', gen.s.question_quotas)
            spare = all(used[k] >= quotas.get(k, 0) for k in self.kinds)
            self.reachability.clear()
            batch = []
            for _ in range(size):
                if not self.groups:
                    break
                if not spare and batch and all(used[k] >= quotas.get(k, 0) for k in self.kinds):
                    break
                aims = self._aims(questions, spare)
                key = min(self.groups, key=lambda k: self._score(
                    self.groups[k], questions, used, quotas, spare, aims))
                group = self.groups[key]
                kind = self._score(group, questions, used, quotas, spare, aims)[4]
                _position, pair, candidate = group.popleft()
                if not group:
                    del self.groups[key]
                batch.append(pair[0])
                if candidate is None:
                    continue
                self.stock[candidate.level] -= 1
                if kind is not None and used[kind] < quotas.get(kind, 0):
                    questions.append(SimpleNamespace(kind=kind, level=candidate.level,
                                                     char_level=candidate.level))
                    used[kind] += 1
            if batch:
                yield batch
