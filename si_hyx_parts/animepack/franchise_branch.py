# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Отделяет ошибочно склеенные Shikimori ветки одной франшизы.

У Shikimori ключ ``franchise`` иногда охватывает не одну серию, а несколько
тайтлов, встретившихся в кроссовере. Самый заметный пример — «Котик Даян»:
кроссовер с «Тамой» дал всем сезонам Даяна индекс гораздо более популярной
«Тамы и друзей». Фильтр консервативный: ветка отделяется лишь когда с обеих
сторон есть как минимум по две части с устойчивым корнем названия.
"""
from __future__ import annotations

from collections import Counter
import re

import animepack as _api


def _science_adventure_branch(card: dict) -> str:
    """Отдельные серии Science Adventure, склеенные ключом Shikimori."""
    if str((card or {}).get("franchise") or "") != "science_adventure":
        return ""
    names = " ".join(str((card or {}).get(field) or "").casefold()
                     for field in ("russian", "name", "english"))
    branches = {
        "steins_gate": ("врата штейна", "steins;gate", "steins gate"),
        "robotics_notes": ("записки о робототехнике", "robotics;notes",
                           "robotics notes"),
        "chaos_head": ("вершина хаоса", "chaos;head", "chaos head"),
        "chaos_child": ("дитя хаоса", "chaos;child", "chaos child"),
        "occultic_nine": ("оккультная девятка", "occultic;nine",
                           "occultic nine"),
    }
    return next((key for key, forms in branches.items()
                 if any(form in names for form in forms)), "")


def _roots(card: dict) -> set[str]:
    roots = set()
    for field in ("russian", "name", "english"):
        value = str((card or {}).get(field) or "").strip()
        root = _api.title_root(value)
        if not root:
            # Общий title_root намеренно отбрасывает короткие слова, чтобы не
            # склеивать ими тайтлы. Здесь уже известен общий ключ франшизы, а
            # короткое имя «Тама» как раз нужно для РАЗДЕЛЕНИЯ веток.
            root = re.split(r"[:—]", value, maxsplit=1)[0].strip().casefold()
            root = re.sub(r"\s+\d+$", "", root).strip()
            if len(root) < 3:
                root = ""
        if root:
            roots.add(root)
    return roots


def franchise_branch_parts(card: dict, parts) -> list[dict]:
    """Части собственной ветки карточки; при сомнении возвращает все."""
    rows = [row for row in (parts or []) if isinstance(row, dict)]
    branch = _science_adventure_branch(card)
    if branch:
        return [row for row in rows if _science_adventure_branch(
            dict(row, franchise="science_adventure")) == branch]
    roots = _roots(card or {})
    if not roots or len(rows) < 4:
        return rows
    own_id = str((card or {}).get("id") or (card or {}).get("malId") or "")
    matched = []
    foreign = Counter()
    for row in rows:
        row_id = str(row.get("id") or row.get("malId") or "")
        row_roots = _roots(row)
        if (own_id and row_id == own_id) or roots.intersection(row_roots):
            matched.append(row)
        else:
            foreign.update(row_roots)
    if not matched:
        # Проморолики и кроссоверы могут иметь новое имя и отсутствовать в
        # минимальной выдаче частей. Тогда основной веткой служит самая
        # большая устойчивая серия, а не новая «ветка всей франшизы».
        counts = Counter(root for row in rows for root in _roots(row))
        root = min(counts, key=lambda value: (-counts[value], value),
                   default="")
        matched = [row for row in rows if root and root in _roots(row)]
        foreign = Counter(other for row in rows if row not in matched
                          for other in _roots(row))
    # Одиночный спин-офф с иным названием не доказывает ошибочную склейку.
    # Две устойчивые серии по разные стороны — доказывают.
    if len(matched) >= 2 and max(foreign.values(), default=0) >= 2:
        return matched
    return rows


def franchise_branch_key(card: dict, parts=None) -> str:
    """Стабильный ключ ветки; пусто, если франшиза разделения не требует."""
    special = _science_adventure_branch(card)
    if special:
        return special
    rows = [row for row in (parts or []) if isinstance(row, dict)]
    scoped = franchise_branch_parts(card, rows)
    if len(scoped) >= len(rows):
        return ""
    # Ключ берётся из ВСЕЙ ветки, а не из корней самой карточки: у полной
    # карточки есть name/english, у частей франшизы — часто только russian, и
    # «самый длинный корень» у сезонов разный («kusuriya no hitorigoto 2nd»,
    # «…3rd»). Тогда каждый сезон «Монолога фармацевта» становился отдельной
    # франшизой в панели базы. Общий корень ветки одинаков у всех её частей.
    counts = Counter(root for row in scoped for root in _roots(row))
    if not counts:
        return ""
    return min(counts, key=lambda value: (-counts[value], -len(value), value))


def branch_franchise_index(card: dict, parts) -> float:
    """Индекс только своей серии внутри возможной склейки Shikimori."""
    return _api.franchise_parts_index(franchise_branch_parts(card, parts))


for _fn in (franchise_branch_parts, franchise_branch_key,
            branch_franchise_index):
    _fn.__module__ = _api.__name__
    setattr(_api, _fn.__name__, _fn)
