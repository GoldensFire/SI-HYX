"""Keep each requested average reachable through the remaining quotas."""
import math
import random
from collections import Counter

import animepack as ap

# Разброс сложности вокруг средней: при цели 5 пак берёт и 4/6, и 3/7, а не
# одни пятёрки. Ключ — смещение от нужного сейчас уровня, значение — вес.
SPREAD_WEIGHTS = {-2: 2, -1: 3, 0: 3, 1: 3, 2: 2}


def drift_limit(count) -> float:
    """Насколько текущая средняя может уйти от цели после count вопросов.

    Узкая рамка ±0.25 с третьего вопроса держала каждую выборку у цели, и пак
    собирался из одних пятёрок. Случайный разброс ±2 даёт отклонение средней
    порядка 2/√n — его и пропускаем; к концу пака рамка сужается до ±0.25."""
    return max(.25, 2 / math.sqrt(max(1, count)))


def spread_offset(generator) -> int:
    rng = getattr(generator, "rng", None) or random
    return rng.choices(list(SPREAD_WEIGHTS), weights=list(SPREAD_WEIGHTS.values()))[0]


def spreads(generator, kind) -> bool:
    """Строгие цели манги (по третям) расписаны заранее — их не размываем."""
    return not (kind == ap.MANGA_KIND and getattr(generator.s, "manga_strict_targets", False))


def fits(generator, candidate, levels, kind=None, flying=(), selected=None):
    kind = candidate.kind if kind is None else kind
    bucket = ap.own_bucket(generator.s, kind)
    target = ap.level_avg_target(generator.s, bucket)
    if not target:
        return True
    if kind == ap.MANGA_KIND and getattr(generator.s, "manga_strict_targets", False):
        from .manga_targets import average_fits
        return average_fits(generator, candidate, levels, flying)
    # Каталог кончился, а пак не набран: полный пак важнее точной середины
    # (см. _take_level_bench). Строгой остаётся только своя средняя песен.
    relaxed = (getattr(generator, "_level_relaxed", False)
               or kind != ap.MANGA_KIND and getattr(generator, "_anime_level_relaxed", False))
    if relaxed and yields(generator, kind):
        return True
    accepted = getattr(generator, "_selected_songs", ()) if selected is None else selected
    if selected is None:
        seen = list(levels if bucket is None else generator._bucket_levels.get(bucket, ()))
    else:
        from .level_avg import question_level
        seen = [question_level(c) for c in selected if ap.own_bucket(generator.s, c.kind) == bucket]
    queued = [c for c in flying if c is not candidate
              and ap.own_bucket(generator.s, c.kind) == bucket]
    seen.extend(int(c.level) for c in queued)
    quotas = getattr(generator, "_selection_quotas", generator.s.question_quotas)
    relevant = {k: int(n) for k, n in quotas.items() if n and ap.own_bucket(generator.s, k) == bucket}
    slots = sum(relevant.values())
    if not slots:
        # Мест под корзину в квотах нет (прямой вызов): точную сумму считать
        # не по чему — просто не уводим среднюю дальше от цели.
        return toward(seen, candidate.level, target)
    if len(seen) >= slots:
        return False
    used = Counter(c.kind for c in [*accepted, *queued]
                   if ap.own_bucket(generator.s, c.kind) == bucket)
    used[kind] += 1
    points = sum(seen) + int(candidate.level)
    if len(seen) >= 3:
        current = abs(sum(seen) / len(seen) - target)
        projected = abs(points / (len(seen) + 1) - target)
        limit = drift_limit(len(seen) + 1)
        if projected > limit and (current <= limit or projected >= current):
            return False
    remaining = slots - len(seen) - 1
    bounds = [(max(0, count - used[k]), generator.s.level_range(k))
              for k, count in relevant.items()]
    low = sum(count * band[0] for count, band in bounds)
    high = sum(count * band[1] for count, band in bounds)
    # Lightweight callers may supply levels without candidate objects.
    if sum(count for count, _ in bounds) != remaining:
        low = remaining * min(band[0] for _, band in bounds)
        high = remaining * max(band[1] for _, band in bounds)
    if points + low <= target * slots <= points + high:
        return True
    # Цель уже недостижима никаким кандидатом (набранное слишком далеко) —
    # тогда берём тех, кто ведёт к ней, а не отвергаем всех подряд.
    left = slots - len(seen)
    floor = min(band[0] for _, band in bounds)
    ceiling = max(band[1] for _, band in bounds)
    if sum(seen) + left * floor <= target * slots <= sum(seen) + left * ceiling:
        return False
    return toward(seen, candidate.level, target)


def toward(seen, level, target) -> bool:
    """Вопрос приближает среднюю к цели (или держит её в ±0.25)."""
    if not seen:
        return True
    current = abs(sum(seen) / len(seen) - target)
    projected = abs((sum(seen) + int(level)) / (len(seen) + 1) - target)
    return projected <= .25 or projected < current


def yields(generator, kind) -> bool:
    """Может ли средняя этого рода уступить ради полного пака.

    Не уступают явно строгие цели: своя средняя песен и «строгие цели» манги."""
    from .level_avg import SONG_BUCKET
    if kind == ap.MANGA_KIND and getattr(generator.s, "manga_strict_targets", False):
        return False
    return ap.own_bucket(generator.s, kind) != SONG_BUCKET


def selection_questions(generator):
    """Immutable snapshot: accepted questions plus those already downloading."""
    return getattr(generator, '_selection_state',
                   tuple(getattr(generator, '_selected_songs', ())))


def level_snapshot(generator, questions) -> list:
    """Лёгкие копии вопросов: род и уровень, посчитанные один раз.

    Средняя проверяется для каждого кандидата резерва и каждой группы каталога,
    и каждый раз по всем набранным вопросам. Снимок отбора — кортеж, который
    генератор пересоздаёт при любой перемене, поэтому кэш держится за него
    самого; изменяемый список считается заново."""
    from types import SimpleNamespace
    from .level_avg import question_level
    frozen = isinstance(questions, tuple)
    if frozen:
        memo = generator.__dict__.get("_level_snapshot")
        if memo is not None and memo[0] is questions:
            return memo[1]
    lights = [SimpleNamespace(kind=c.kind, level=question_level(c),
                              char_level=c.char_level if c.kind == ap.CHAR_KIND else 0)
              for c in questions]
    if frozen:
        generator.__dict__["_level_snapshot"] = (questions, lights)
    return lights


def desired_level(generator, kind, questions=None):
    """Required average of the remaining slots, including category-specific bounds."""
    from .level_avg import question_level
    questions = selection_questions(generator) if questions is None else questions
    bucket = ap.own_bucket(generator.s, kind)
    target = ap.level_avg_target(generator.s, bucket)
    if kind == ap.CHAR_KIND and getattr(generator.s, 'char_level_avg', 0):
        seen = [c.char_level for c in questions if c.kind == ap.CHAR_KIND]
        target = generator.s.char_level_avg
        quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
        slots = quotas.get(kind, 0)
    elif target:
        seen = [question_level(c) for c in level_snapshot(generator, questions)
                if ap.own_bucket(generator.s, c.kind) == bucket]
        quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
        slots = sum(n for k, n in quotas.items() if ap.own_bucket(generator.s, k) == bucket)
    else:
        return None
    desired = (target * slots - sum(seen)) / max(1, slots - len(seen))
    low, high = generator.s.level_range(kind)
    return max(low, min(high, desired))


def aim_level(generator, kind, desired, offset=None):
    """Уровень, к которому тянется следующий выбор: нужный ± случайный шаг.

    Без смещения ближайшим к нужному всегда оказывался кандидат ровно на
    средней. Итог при этом сходится: desired_level пересчитывает нужное по
    уже набранному, а fits не пускает среднюю за drift_limit."""
    if desired is None:
        return None
    if offset is None:
        offset = spread_offset(generator) if spreads(generator, kind) else 0
    low, high = generator.s.level_range(kind)
    return max(low, min(high, desired + offset))


def priority(generator, candidate, kind=None):
    kind = candidate.kind if kind is None else kind
    questions = selection_questions(generator)
    # Одно смещение на состояние отбора: все кандидаты резерва сравниваются с
    # одной точкой, а после каждого принятого вопроса шаг выбирается заново.
    memo = generator.__dict__.get("_level_aims")
    if memo is None or memo[0] is not questions:
        memo = questions, {}
        if isinstance(questions, tuple):
            generator.__dict__["_level_aims"] = memo
    aims = memo[1]
    if kind not in aims:
        aims[kind] = aim_level(generator, kind, desired_level(generator, kind, questions))
    aim = aims[kind]
    if kind == ap.MANGA_KIND:
        # У манги, манхвы и маньхуа средние свои: прицел сдвигается по изданию.
        from .manga_editions import aim as edition_aim
        aim = edition_aim(generator.s, candidate.anime, aim)
    return abs(candidate.level - aim) if aim is not None else 0


def selection_fits(generator, candidate, kind):
    """Use the same average check before choosing a category or probing a source."""
    questions = selection_questions(generator)
    lights = level_snapshot(generator, questions)
    accepted_ids = {id(c) for c in getattr(generator, '_selected_songs', ())}
    selected = [light for c, light in zip(questions, lights) if id(c) in accepted_ids]
    flying = [c for c in questions if id(c) not in accepted_ids]
    levels = [c.level for c in selected if ap.own_bucket(generator.s, c.kind) is None]
    return (fits(generator, candidate, levels, kind, flying, selected)
            and character_fits(generator, candidate, kind, questions))


def character_fits(generator, candidate, kind=None, questions=None):
    target = int(getattr(generator.s, 'char_level_avg', 0) or 0)
    kind = candidate.kind if kind is None else kind
    if kind != ap.CHAR_KIND or not target:
        return True
    with generator._char_lock:
        if questions is None and hasattr(generator, '_selection_state'):
            questions = selection_questions(generator)
        values = ([c.char_level for c in questions if c.kind == ap.CHAR_KIND and c is not candidate]
                  if questions is not None else list(generator._char_levels))
        generator._char_target_eff = target
        quotas = getattr(generator, '_selection_quotas', generator.s.question_quotas)
        slots = quotas.get(ap.CHAR_KIND, 0)
        remaining = slots - len(values) - 1
        if remaining < 0:
            return False
        points = sum(values) + candidate.char_level
        low, high = generator.s.char_level_min, generator.s.char_level_max
        if not low <= candidate.char_level <= high:
            return False
        if not points + remaining * low <= target * slots <= points + remaining * high:
            return False
        if len(values) >= 3:
            current = abs(sum(values) / len(values) - target)
            projected = abs(points / (len(values) + 1) - target)
            limit = drift_limit(len(values) + 1)
            if projected > limit and (current <= limit or projected >= current):
                return False
        return True
