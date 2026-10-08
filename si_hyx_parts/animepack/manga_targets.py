"""Strict comic quotas and a reachable average, including pending questions."""
from collections import Counter

import animepack as ap

from .manga_editions import edition


def average_fits(generator, candidate, levels, flying=()):
    settings = generator.s
    bucket = ap.own_bucket(settings, ap.MANGA_KIND)
    target = ap.level_avg_target(settings, bucket)
    if not target:
        return True
    seen = list(levels if bucket is None else generator._bucket_levels.get(bucket, ()))
    seen.extend(int(c.level) for c in flying
                if ap.own_bucket(settings, c.kind) == bucket)
    quotas = settings.question_quotas
    slots = sum(count for kind, count in quotas.items()
                if ap.own_bucket(settings, kind) == bucket)
    left = slots - len(seen) - 1
    tolerance = max(0.0, min(1.0, float(settings.manga_average_tolerance)))
    low, high = settings.level_range(ap.MANGA_KIND)
    points = sum(seen) + int(candidate.level)
    if left < 0 or not (points + left * low <= (target + tolerance) * slots
                        and points + left * high >= (target - tolerance) * slots):
        return False
    planned = getattr(generator, "_manga_plan_stats", {}).get("desired_levels")
    if planned and len(seen) < slots * .8:
        return edition_fits(generator, candidate, flying, planned, target, low, high)
    if len(seen) < 3:
        return True
    previous = abs(sum(seen) / len(seen) - target)
    projected = abs(points / (len(seen) + 1) - target)
    return projected <= tolerance or projected < previous


def edition_fits(generator, candidate, flying, planned, target, low, high):
    """Leave lighter manga available to balance harder webtoons later."""
    books = [c for c in [*getattr(generator, "_selected_songs", ()), *flying]
             if c.is_manga]
    groups = {key: [int(c.level) for c in books if edition(c.anime) == key]
              for key in planned}
    quotas = generator._manga_mix.kind_target
    wanted = {"manga": quotas[""], "manhwa": quotas["manhwa"], "manhua": quotas["manhua"]}
    desired = dict(planned)
    if wanted["manga"]:
        estimates = {key: sum(values) / len(values) if len(values) >= 3 else desired[key]
                     for key, values in groups.items() if key != "manga"}
        desired["manga"] = max(low, min(high, (target * sum(wanted.values())
            - sum(wanted[key] * value for key, value in estimates.items())) / wanted["manga"]))
    key = edition(candidate.anime)
    seen = groups[key]
    if len(seen) < 3:
        return True
    aim = desired[key]
    previous = abs(sum(seen) / len(seen) - aim)
    projected = abs((sum(seen) + int(candidate.level)) / (len(seen) + 1) - aim)
    return projected <= .75 or projected < previous


def final_error(settings, candidates):
    if not getattr(settings, "manga_strict_targets", False):
        return ""
    # Partial results remain recoverable; they must never masquerade as complete.
    if len(candidates) != settings.total_questions:
        return ""
    books = [c for c in candidates if c.is_manga]
    quota = settings.question_quotas.get(ap.MANGA_KIND, 0)
    mix = ap.MangaMix(settings, quota)
    expected = {"manga": mix.kind_target[""], "manhwa": mix.kind_target["manhwa"],
                "manhua": mix.kind_target["manhua"]}
    actual = Counter(edition(c.anime) for c in books)
    if len(books) != quota or any(actual[k] != n for k, n in expected.items()):
        return f"Состав комиксов не выполнен: получили {dict(actual)}, нужно {expected}."
    bucket = ap.own_bucket(settings, ap.MANGA_KIND)
    target = ap.level_avg_target(settings, bucket)
    group = [c for c in candidates if ap.own_bucket(settings, c.kind) == bucket]
    if target and group:
        average = sum(c.level for c in group) / len(group)
        tolerance = max(0.0, min(1.0, float(settings.manga_average_tolerance)))
        if abs(average - target) > tolerance + 1e-9:
            return (f"Средняя сложность комиксов {average:.2f}, нужно "
                    f"{target} ± {tolerance:.2f}. Готовые вопросы сохранены для добора.")
    return ""
