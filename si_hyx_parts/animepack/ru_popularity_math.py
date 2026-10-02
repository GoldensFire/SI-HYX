# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Source-local ranks and positive-only mapping into existing book units."""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from math import isfinite

KINDS = ("manga", "manhwa", "manhua")
STATUSES = ("NORMAL", "RIGHTS_RESTRICTED", "NOT_FOUND", "AMBIGUOUS", "ERROR")
SNAPSHOT_GROUP = "ru_population_snapshots_v1"
OBSERVATION_GROUP = "ru_population_observations_v1"


@dataclass(frozen=True)
class RuPopularityConfig:
    highest_weight: float = 0.3
    second_weight: float = 0.7
    min_samples: int = 50
    snapshot_ttl: float = 30 * 86400
    normal_ttl: float = 7 * 86400
    failure_ttl: float = 6 * 3600
    max_catalog_pages: int = 10000

    def __post_init__(self):
        if (not isfinite(self.highest_weight) or not isfinite(self.second_weight)
                or self.highest_weight < 0 or self.second_weight <= 0
                or abs(self.highest_weight + self.second_weight - 1) > 1e-9):
            raise ValueError("RU percentile weights must be nonnegative and sum to 1")
        if self.min_samples < 2 or self.max_catalog_pages < 1:
            raise ValueError("RU distributions need at least two samples")


def number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if isfinite(result) and result >= 0 else None


def percentile(sorted_values, value):
    """Midrank of ties, [0, 1]; inverse is a linearly interpolated quantile."""
    value = number(value)
    if value is None or len(sorted_values) < 2:
        return None
    left, right = bisect_left(sorted_values, value), bisect_right(sorted_values, value)
    rank = (left + right - 1) / 2 if right > left else left
    return max(0.0, min(1.0, rank / (len(sorted_values) - 1)))


def quantile(sorted_values, probability):
    probability = number(probability)
    if probability is None or probability > 1 or len(sorted_values) < 2:
        return None
    position = probability * (len(sorted_values) - 1)
    low = int(position)
    high = min(low + 1, len(sorted_values) - 1)
    return sorted_values[low] + (sorted_values[high] - sorted_values[low]) * (position - low)


def reliable_percentile(observation):
    if observation.get("status") == "NORMAL":
        return number(observation.get("percentile"))
    if observation.get("status") == "RIGHTS_RESTRICTED":
        previous = observation.get("last_normal") or {}
        return number(previous.get("percentile"))
    return None


def correction(original, shiki_percentile, observations, book_distribution,
               config=RuPopularityConfig()):
    """No external evidence, weak evidence or absent baseline means exact fallback."""
    result = {"original_book_index": original, "effective_book_index": original,
              "P_shiki": shiki_percentile, "sources": observations}
    if shiki_percentile is None or len(book_distribution) < config.min_samples:
        return result
    external = [p for row in observations.values()
                if (p := reliable_percentile(row)) is not None and p <= 1]
    if not external or max(external) <= shiki_percentile:
        return result
    highest, second = sorted([shiki_percentile] + external, reverse=True)[:2]
    ru = config.highest_weight * highest + config.second_weight * second
    if ru <= shiki_percentile:
        return result
    equivalent = quantile(book_distribution, ru)
    if equivalent is not None:
        result.update(P_ru=ru, ru_equivalent_book_index=equivalent,
                      effective_book_index=max(original, equivalent))
    return result
