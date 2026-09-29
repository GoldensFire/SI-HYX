# -*- coding: utf-8 -*-
"""Название самой узнаваемой части собственной ветки франшизы."""
from __future__ import annotations

import animepack as ap


def popular_franchise_title(card: dict, parts) -> str:
    """Берёт максимум по индексу, а не по порядку выдачи Shikimori."""
    if not (card or {}).get("franchise"):
        return ""
    scoped = ap.franchise_branch_parts(card, parts)
    # Ролики, клипы и рекламные материалы не служат ответом о тайтле.
    eligible = [row for row in scoped
                if str(row.get("kind") or "") in ap.ANIME_KINDS]
    if not eligible:
        return ""
    best = max(eligible, key=lambda row: ap.SongCandidate(
        song={}, anime=row).own_index)
    return str(best.get("russian") or best.get("name") or "").strip()
