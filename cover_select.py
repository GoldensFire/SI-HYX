# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
"""Какой из подтверждённых каверов и какие его двадцать секунд идут в пак.

Кандидаты сюда приходят уже проверенными: гейт признал их ИСПОЛНЕНИЕМ
(cover_meta), звук — ТОЙ ЖЕ композицией (cover_match). Здесь решается только
разнообразие, и решается случайно, а не «лучший по счёту»: на стенде у песни
остаётся 4…10 подтверждённых каверов, и top-1 означал бы, что в каждом паке у
одной и той же песни звучит один и тот же ролик с одного и того же места.

Вес складывается из трёх вещей:

* УВЕРЕННОСТЬ. Чем выше нормированный счёт, тем надёжнее тождество. Разброс
  берётся от порога и вверх на CONF_SPAN: на стенде принятые каверы лежат от
  3.0 до 17 (10-й и 90-й процентили), так что вес честно делит пул надвое, а не
  превращается в тот же top-1.
* РАЗНООБРАЗИЕ ТИПОВ. Вокальных каверов на YouTube больше всех, и без этого
  множителя пак состоял бы из них одних: делим вес на то, сколько раз тип уже
  попал в этот пак (TYPES из cover_meta_rules).
* ОСТЫВАНИЕ. Недавно использованный ролик берём неохотно, давний — как новый.
  Вовсе не запрещаем: у песни бывает единственный подтверждённый кавер.

Плюс два запрета: тот же ролик НЕ идёт подряд (last_used в cover_cache), и
окно не повторяет уже использованные — а если все заняты, берётся любое, лишь
бы вопрос вообще собрался.

Ни сети, ни Qt, ни диска: чистая функция от строк кэша.
"""
from __future__ import annotations

import random
import time

import cover_match as match

# На сколько счёт над порогом поднимает вес (вдвое на этом размахе). Принятые
# каверы лежат от 3.0 до 17, порог 3.0/3.5 — то есть размах 6 делит пул примерно
# пополам, а не выбирает одного лидера.
CONF_SPAN = 6.0
MAX_CONFIDENCE = 2.0
# Во сколько раз слабее берётся тип, уже попавший в пак (1 / (1 + n)).
TYPE_BIAS = 1.0
# Через сколько дней использованный кавер считается снова свежим и во сколько
# раз реже берётся сразу после пака.
COOLDOWN_DAYS = 90.0
COLD_FLOOR = 0.15
DAY = 86400.0
# Ближе этого окна считаются одним и тем же куском: у двадцатисекундного окна
# половина содержимого общая.
WINDOW_GAP = 10.0


def confidence(row) -> float:
    """1.0…MAX_CONFIDENCE — насколько уверенно звук признал композицию."""
    floor = match.floor_for(row.get("strength"))
    above = (float(row.get("norm") or 0.0) - floor) / max(CONF_SPAN, 1e-6)
    return 1.0 + min(1.0, max(0.0, above)) * (MAX_CONFIDENCE - 1.0)


def cooling(row, now: float) -> float:
    """COLD_FLOOR…1.0 — насколько остыл ролик со времени прошлого пака."""
    last = float(row.get("last_used") or 0.0)
    if last <= 0:
        return 1.0
    age = max(0.0, float(now) - last) / DAY
    return COLD_FLOOR + (1.0 - COLD_FLOOR) * min(1.0, age / max(COOLDOWN_DAYS, 1e-6))


def weight(row, *, now: float, seen_types=None) -> float:
    """Вес одного кандидата в случайном выборе (всегда больше нуля)."""
    seen = (seen_types or {}).get(str(row.get("type") or ""), 0)
    spread = 1.0 / (1.0 + TYPE_BIAS * max(0, int(seen)))
    return max(confidence(row) * spread * cooling(row, now), 1e-3)


def window(row, *, rng=None, prefer=None, gap: float = WINDOW_GAP) -> dict:
    """Окно кавера: сперва ТО ЖЕ МЕСТО песни, что у оригинала, потом не занятое
    прошлыми паками, потом любое.

    Порядок здесь не произвольный, а исправленный по замеру. Сперва фильтр
    занятых окон стоял ПЕРЕД `prefer` — и на 52 разыгранных паках
    (tools/cover_select_probe.py) попадание в место, запрошенное генератором,
    падало с 0.942 до 0.621, а разных участков прибавлялось всего 0.2 из восьми:
    отрезок оригинала и без того режется каждый раз со случайного места, так что
    память о занятых окнах боролась с уже решённой задачей ценой главного
    требования — у кавера и у оригинала звучит одна и та же часть песни."""
    good = list(row.get("windows") or ())
    near = match.nearest(good, prefer)
    if near:
        return near
    used = [float(u) for u in (row.get("used") or ())]
    if used:
        fresh = [w for w in good
                 if all(abs(float(w["at"]) - u) >= gap for u in used)]
        good = fresh or good
    return match.choose(good, rng)


def pick(rows, *, rng=None, now: float = 0.0, skip: str = "",
         seen_types=None, prefer=None) -> dict:
    """Один кавер из подтверждённых ({} — выбирать не из чего).

    Возвращает строку кандидата плюс выбранный участок: "window", "at" и
    "length" — секунда КАВЕРА и длина куска, как у cover_match.verify."""
    rows = [row for row in rows if row.get("windows")]
    if not rows:
        return {}
    # Тот же ролик подряд не берём — но если он единственный, вопрос важнее
    # запрета: без него песня осталась бы вовсе без кавера.
    choices = [row for row in rows if str(row.get("id") or "") != str(skip or "")]
    choices = choices or rows
    now = float(now or time.time())
    weights = [weight(row, now=now, seen_types=seen_types) for row in choices]
    picker = rng or random
    row = picker.choices(choices, weights=weights, k=1)[0]
    spot = window(row, rng=rng, prefer=prefer)
    if not spot:
        return {}
    begin, end = spot["cover"]
    return dict(row, window=spot, at=round(float(begin), 2),
                length=round(float(end) - float(begin), 2),
                ref_at=float(spot["at"]), density=float(spot["density"]))
