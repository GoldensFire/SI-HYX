# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Запасная попытка на последние места манги.

В конце прогона остаются одна-две книги, а остальные потоки простаивают: пак
№ 131 шесть минут ждал одну мангу, у которой на попытку отведено до трёх минут
(источник, страница, выбор сцены Gemini). Когда свободны только книжные места,
на каждое из них запускается ещё один кандидат. Пак собирается по первому
успеху; лишний готовый вопрос уходит в запас («место занял другой»), а
незаконченный обрывается вместе с остальными загрузками."""
from __future__ import annotations

from collections import Counter

import animepack as ap

# Не больше стольких открытых мест манги: раньше запас только мешал бы
# обычному отбору.
TAIL_PLACES = 3


def discount(generator, inflight: Counter, counts: Counter, quotas: dict,
             pending, workers: int) -> Counter:
    """Загрузки «в работе», какими их видит планировщик.

    Для манги в хвосте из счёта вычитается по одной загрузке на открытое
    место — так на каждое место может уйти вторая попытка."""
    kind = ap.MANGA_KIND
    if kind in generator._dead_kinds or len(pending) >= workers:
        return inflight
    left = quotas.get(kind, 0) - counts[kind]
    if not 0 < left <= TAIL_PLACES or inflight[kind] < left:
        return inflight
    others_busy = all(quotas.get(k, 0) <= counts[k] + inflight[k]
                      for k in quotas if k != kind and k not in generator._dead_kinds)
    if not others_busy:
        return inflight
    seen = Counter(inflight)
    seen[kind] = max(0, inflight[kind] - left)
    return seen
