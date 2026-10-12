"""Draw the required difficulty from the entire saved pool before HTTP/media."""
from collections import Counter, deque
from itertools import islice
from types import SimpleNamespace

import animepack as ap

from .average_selection import (aim_level, desired_level, selection_questions, fits,
                                level_snapshot)
from .catalog_profiles import profiles
from .level_inventory import attainable

# Кандидат с заготовленным уровнем: профиль строится, когда он дошёл до
# головы своей очереди (CatalogPlan._head).
_LAZY = object()
# На сколько уровней заготовка может разойтись с живым расчётом: карточка
# дальше от рамки в отбор не идёт. В прогоне 2026-10-08 21:07 (рамка 1–4)
# 13 минут ушло на 538 запросов AnisongDB для 10 278 карточек вне рамки, а
# прошла её 61 — все на шаг от края.
FRAME_SLACK = 1
# Средняя считается недостижимой, если даже самые крайние тайтлы рамки
# не подводят к ней ближе: запас покрывает уровни героев и дрейф заготовки.
REACH_MARGIN = .5


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
        # Книжные доли (MangaMix) в текущей пачке: книги, ещё не дошедшие до отбора.
        self.taken = Counter()
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
        # Уровни, заготовленные при «Обновить базу» (catalog_levels): по ним
        # каталог раскладывается без расчёта профилей, а кандидат собирается,
        # только когда дошёл до головы своей очереди (_head).
        from .catalog_levels import load
        ready = (load(generator) or {}).get('manga' if manga else 'anime') or {}
        index = self.index = profiles(generator, manga, prefetch=not ready)
        histogram = Counter()
        far = 0
        for position, pair in enumerate(pairs):
            if generator.stopped():
                break
            known = ready.get(pair[0])
            card = index.cards.get(pair[0]) if known else None
            if card is not None:
                level, adapted, incomplete = known
                candidate = _LAZY
            else:
                candidate = index.get(pair[0])
                if candidate is not None:
                    card = candidate.anime
                    level, adapted, incomplete = (candidate.level, bool(candidate.adapted_from),
                                                  candidate._profile_incomplete)
            if card is not None:
                if not ap.filter_anime(card, generator.s, manga=manga):
                    continue
                if generator._root_excluded(card):
                    continue
                histogram[level] += 1
                if not incomplete and self._far_outside(card, level):
                    # Рамку пака такая не пройдёт (_accept_anime), а песни
                    # и карточку для неё спрашивали бы зря.
                    far += 1
                    continue
                self.stock[level] += 1
                # Edition/adaptation groups keep different comic shares available.
                edition = str(card.get('kind') or '') if manga else ''
                key = level, edition, adapted, incomplete
            else:
                key = None, '', False, True
            self.groups.setdefault(key, deque()).append((position, pair, candidate))
        index.flush()
        if not ready and len(pairs) > 1000:
            generator.log(f'Подбор по базе: уровни {"книг" if manga else "аниме"} не '
                          'заготовлены — считаю на месте; заготовить заранее — '
                          'кнопкой «Обновить базу».')
        known = sum(histogram.values())
        generator.log(f'Подбор по базе: {"книги" if manga else "аниме"} — '
                      f'{known} карточек с рассчитанным уровнем; '
                      f'{level_spread(generator, self.kinds, histogram)}. '
                      'Сначала выбираю нужную сложность, затем проверяю источники.')
        if far:
            generator.log(f'Подбор по базе: {far} карточек дальше шага от рамки '
                          'сложности — не перебираю их.')
        if not manga:
            self._check_reach(histogram)

    def _far_outside(self, card, level):
        """Заготовленный уровень дальше FRAME_SLACK от рамки, которую проверит отбор."""
        if self.manga:
            from .manga_editions import card_range
            low, high = card_range(self.generator.s, card)
        else:
            low, high = self.generator.s.level_span
        return not low - FRAME_SLACK <= level <= high + FRAME_SLACK

    def _check_reach(self, histogram):
        """Средняя, недостижимая уже по запасу каталога, не сторожится с начала.

        Раньше такой прогон откладывал всех кандидатов на скамейку и ждал конца
        каталога: при средней 2 и нуле тайтлов уровней 1–2 пак стоял 8 минут, а
        вышел с той же средней 3,1, что даёт выбор ближайших к ней сразу."""
        from .average_selection import yields
        gen = self.generator
        quotas = getattr(gen, '_selection_quotas', gen.s.question_quotas)
        buckets = {ap.own_bucket(gen.s, k) for k in self.kinds}
        unreachable = getattr(gen, '_unreachable_buckets', set())
        for bucket in buckets:
            target = ap.level_avg_target(gen.s, bucket)
            relevant = [k for k, n in quotas.items()
                        if n and ap.own_bucket(gen.s, k) == bucket]
            if (not target or not relevant or any(k not in self.kinds for k in relevant)
                    or not all(yields(gen, k) for k in relevant)):
                continue
            slots = sum(quotas[k] for k in relevant)
            low = min(gen.s.level_range(k)[0] for k in relevant)
            high = max(gen.s.level_range(k)[1] for k in relevant)
            levels = sorted(level for level, n in histogram.items()
                            if low <= level <= high for _ in range(n))
            if len(levels) < slots:
                continue
            easiest = sum(levels[:slots]) / slots
            hardest = sum(levels[-slots:]) / slots
            if easiest - REACH_MARGIN <= target <= hardest + REACH_MARGIN:
                continue
            unreachable.add(bucket)
            closest = easiest if target < easiest else hardest
            gen.log(f'Внимание: средняя {target} недостижима — даже самые '
                    f'{"лёгкие" if target < easiest else "трудные"} {slots} тайтлов '
                    f'в рамке {low}–{high} дают {closest:.1f}. Беру ближайших к ней '
                    'сразу, не перебирая весь каталог.')
        gen._unreachable_buckets = unreachable

    def _attainable(self, level, kind, questions, quotas):
        from .level_avg import question_level
        gen = self.generator
        bucket = ap.own_bucket(gen.s, kind)
        target = ap.level_avg_target(gen.s, bucket)
        relevant = [k for k, n in quotas.items() if n and ap.own_bucket(gen.s, k) == bucket]
        bands = {gen.s.level_range(k) for k in relevant}
        # Different ranges/catalogues are checked by the ordinary quota
        # projection; this finite-stock check is exact for a shared band.
        if ap.MANGA_KIND in relevant:
            # Своя рамка у каждого издания книг: общий запас по одной полосе
            # тут неточен.
            from .manga_editions import active, level_range
            bands |= {level_range(gen.s, k) for k in active(gen.s)}
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

    def _head(self, group):
        position, pair, candidate = group[0]
        if candidate is _LAZY:
            candidate = self.index.get(pair[0])
            group[0] = position, pair, candidate
        return group[0]

    def _score(self, group, questions, used, quotas, spare=False, aims=None):
        position, _pair, candidate = self._head(group)
        if candidate is None:
            return 1, 0, 0, position, None
        level = candidate.level
        aims = self._aims(questions, spare) if aims is None else aims
        choices = []
        for kind in self.kinds:
            if not spare and used[kind] >= quotas.get(kind, 0):
                continue
            wanted = aims.get(kind)
            if kind == ap.MANGA_KIND:
                from .manga_editions import aim, card_range
                low, high = card_range(self.generator.s, candidate.anime)
                wanted = aim(self.generator.s, candidate.anime, wanted)
            else:
                low, high = self.generator.s.level_range(kind)
            if not low <= level <= high:
                continue
            distance = abs(level - wanted) if wanted is not None else 0
            fit = spare or fits(self.generator, candidate, [], kind, selected=questions)
            stock = spare or self._attainable(level, kind, questions, quotas)
            rank = 0 if fit and stock else 2 if fit else 3
            mix = getattr(self.generator, '_manga_mix', None)
            if kind == ap.MANGA_KIND and not spare and mix is not None                     and not mix.wants(candidate, self.taken):
                # Издание уже набрано: такую книгу отбор отправил бы на скамейку.
                rank += 1
            choices.append((rank, distance, used[kind] / max(1, quotas[kind]), position, kind))
        return min(choices) if choices else (4, 0, 0, position, None)

    def upcoming(self, limit):
        """Id, которые batches, скорее всего, выдаст следующими: головы групп.

        Порядок batches зависит от набранного, поэтому это лишь прогноз — им
        AnimeCardFeed добирает запрос к AnisongDB до полной пачки."""
        if not self.active:
            return [pair[0] for pair in islice(self.original, limit)]
        groups = list(self.groups.values())
        heads = []
        for depth in range(limit):
            row = [group[depth][1][0] for group in groups if depth < len(group)]
            if not row:
                break
            heads += row
            if len(heads) >= limit:
                break
        return heads[:limit]

    def _karaoke_first(self):
        """Тайтлы из индекса Karaoke Mugen — в голову своей очереди.

        Уровень и рамка не меняются: внутри группы одного уровня такие тайтлы
        лишь идут раньше остальных (см. karaoke_catalog). Индекс приходит
        фоном, поэтому очереди переставляются, когда он появился или обновился."""
        if self.manga:
            return
        version = getattr(self.generator, '_mugen_index_version', 0)
        if version == getattr(self, '_karaoke_version', 0):
            return
        self._karaoke_version = version
        from .karaoke_catalog import has_timed
        gen = self.generator
        if not self.active:
            self.original = deque(sorted(self.original, key=lambda pair: not has_timed(gen, pair[0])))
            return
        for key, group in self.groups.items():
            self.groups[key] = deque(sorted(group, key=lambda row: not has_timed(gen, row[1][0])))

    def batches(self, size):
        if not self.active:
            while self.original:
                self._karaoke_first()
                yield [self.original.popleft()[0] for _ in range(min(size, len(self.original)))]
            return
        # Recalculate against the live pack after every small batch.
        size = min(size, 20)
        gen = self.generator
        while self.groups and not gen.stopped():
            self._karaoke_first()
            # Уровни набранных считаются один раз на пачку, а не в каждом
            # _score: групп сотни, и иначе пачка из 20 книг шла минутами.
            questions = list(level_snapshot(gen, selection_questions(gen)))
            used = Counter(c.kind for c in questions)
            quotas = getattr(gen, '_selection_quotas', gen.s.question_quotas)
            spare = all(used[k] >= quotas.get(k, 0) for k in self.kinds)
            self.reachability.clear()
            self.taken.clear()
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
                # Запас считается по уровню раскладки: у заготовки он может
                # на шаг разойтись с живым уровнем кандидата.
                self.stock[key[0]] -= 1
                if kind is not None and used[kind] < quotas.get(kind, 0):
                    questions.append(SimpleNamespace(kind=kind, level=candidate.level,
                                                     char_level=candidate.level))
                    used[kind] += 1
                    mix = getattr(gen, '_manga_mix', None)
                    if kind == ap.MANGA_KIND and mix is not None:
                        mix.count(candidate, self.taken)
            if batch:
                yield batch
