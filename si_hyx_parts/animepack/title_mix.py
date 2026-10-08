"""Integer distribution of the shared title quota over selected puzzle kinds."""
from .title_kinds import TITLE_KINDS

KINDS = ("anagram",) + TITLE_KINDS


def weights(settings):
    selected = settings.title_enabled
    if selected is None:
        selected = [k for k in KINDS if getattr(settings, "pack_" + k)]
    return {k: max(0, int(settings.title_shares.get(k, 0))) if k in selected else 0
            for k in KINDS}


def split(total, weights):
    weights = {k: max(0, int(weights.get(k, 0))) for k in KINDS}
    denominator = sum(weights.values())
    if not denominator:
        return dict.fromkeys(KINDS, 0)
    result = {k: total * v // denominator for k, v in weights.items()}
    for key in sorted(weights, key=lambda k: -(total * weights[k] % denominator))[:total - sum(result.values())]:
        result[key] += 1
    return result
