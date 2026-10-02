# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Three comic edition shares, including migration of older checkboxes."""
KEYS = ("manga", "manhwa", "manhua")
LABELS = {"manga": "Манга", "manhwa": "Манхва", "manhua": "Маньхуа"}
SUPPORTED = KEYS + ("one_shot", "doujin")


def shares(settings) -> dict:
    manhwa = max(0, min(100, int(settings.manga_pct_manhwa or 0)))
    manhua = max(0, min(100, int(settings.manga_pct_manhua or 0)))
    raw = {"manga": max(0, 100 - manhwa - manhua),
           "manhwa": manhwa, "manhua": manhua}
    kinds = settings.manga_kinds
    enabled = [k for k in KEYS if kinds.get(k) or
               (k == "manga" and (kinds.get("one_shot") or kinds.get("doujin")))]
    if not enabled:
        return dict.fromkeys(KEYS, 0)
    weights = {k: raw[k] for k in enabled}
    if not any(weights.values()):
        weights = dict.fromkeys(enabled, 1)
    total = sum(weights.values())
    result = {k: weights.get(k, 0) * 100 // total for k in KEYS}
    rest = 100 - sum(result.values())
    order = sorted(enabled, key=lambda k: -(weights[k] * 100 % total))
    for key in order[:rest]:
        result[key] += 1
    return result


def migrate(settings, source) -> None:
    old = source.get("manga_kinds") or {}
    settings.manga_kinds = {k: bool(settings.manga_kinds.get(k)) for k in SUPPORTED}
    if (not any(settings.manga_kinds.values())
            and any(old.get(k) for k in ("light_novel", "novel"))):
        settings.manga_kinds.update(dict.fromkeys(KEYS, True))
    values = shares(settings)
    settings.manga_pct_manhwa = values["manhwa"]
    settings.manga_pct_manhua = values["manhua"]


def edition(card) -> str:
    kind = str(card.get("kind") or "").lower()
    return kind if kind in ("manhwa", "manhua") else "manga"
