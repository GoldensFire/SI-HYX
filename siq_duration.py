# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# siq_duration.py — общие ПРАВИЛА оценки длительности .siq-пака (группировка
# одновременных элементов, длительность ответа), без единого байта IO.
#
# Используется и sigstats/siq.py (сбор статистики: ffprobe-проба медиа,
# извлечённого на диск), и siquester/siq_package.py (редактор паков: быстрая
# in-Python проба mp4/mp3 прямо из открытого zip-потока, без субпроцессов) —
# формула одна и та же, разнится только item_seconds_fn (как измерить
# длительность ОДНОГО элемента) — это отдаётся вызывающему модулю.
from __future__ import annotations
from typing import Callable

CHARS_PER_SEC = 20.0      # скорость чтения текста вопроса/ответа
IMAGE_SEC = 5.0            # показ одной картинки
ANSWER_TEXT_SEC = 3.0      # фиксированная длительность обычного текстового ответа

ItemSecondsFn = Callable[[dict], float]


def parse_dur_attr(s: str | None) -> float | None:
    """Разбирает атрибут duration: «5», «5.0», «mm:ss», «hh:mm:ss»."""
    if not s:
        return None
    s = s.strip()
    try:
        if ":" in s:
            parts = [float(p) for p in s.split(":")]
            sec = 0.0
            for p in parts:
                sec = sec * 60 + p
            return sec
        return float(s)
    except ValueError:
        return None


def content_duration(items: list[dict], item_seconds_fn: ItemSecondsFn) -> float:
    """Длительность последовательности элементов с учётом одновременного показа.

    Каждый item — словарь минимум с ключами:
      type      — "image" | "audio" | "video" | что угодно ещё (текст и т.п.)
      placement — "background" (фоновая музыка, идёт параллельно всему) или
                  что угодно ещё (обычный элемент переднего плана)
      wait_false — True, если элемент показывается ОДНОВРЕМЕННО со следующим
                  (аналог waitForFinish=False у .siq) — они попадают в одну
                  «группу одновременного показа».

    В группе с медиа устный текст не считается; «2 фото разом» = 5 сек (берём
    МАКСИМУМ по группе, а не сумму). Последовательные группы складываются.
    Фон (background) суммируется отдельно и идёт параллельно всему остальному
    (итог = max(последовательность переднего плана, сумма фона)).

    item_seconds_fn(item) -> float — длительность ОДНОГО элемента; реализация
    специфична для вызывающего модуля (ffprobe-проба у sigstats, пробование
    zip-потока у siquester).
    """
    fg = [it for it in items if it.get("placement") != "background"]
    bg = [it for it in items if it.get("placement") == "background"]

    groups: list[list[dict]] = []
    cur: list[dict] = []
    for it in fg:
        cur.append(it)
        if it.get("wait_false"):
            continue
        groups.append(cur)
        cur = []
    if cur:
        groups.append(cur)

    fg_total = 0.0
    for g in groups:
        media = [it for it in g if it.get("type") in ("image", "audio", "video", "html")]
        if media:                       # текст при одновременном медиа не считаем
            fg_total += max(item_seconds_fn(it) for it in media)
        else:
            fg_total += max((item_seconds_fn(it) for it in g), default=0.0)
    bg_total = sum(item_seconds_fn(it) for it in bg)
    return max(fg_total, bg_total)


def question_duration(q_items: list[dict], a_items: list[dict],
                      answer_time: float | None, has_answer_content: bool,
                      has_plain_answer: bool,
                      item_seconds_fn: ItemSecondsFn) -> float:
    """Итоговая длительность вопроса = длительность контента вопроса +
    длительность ответа.

    answer_time — «время на ответ» (таймер на вопросе целиком или на блоке
    ответа), если задан явно — тогда длительность ответа = answer_time − 5 сек
    (5 сек — типовая «пауза на обдумывание», отсчитывается сама по себе).
    Иначе — по контенту «сложного ответа» (a_items) плюс ANSWER_TEXT_SEC за
    обычный текстовый ответ, если сложного контента в ответе нет, а простой
    правильный ответ есть (has_plain_answer).
    """
    q_dur = content_duration(q_items, item_seconds_fn)
    if answer_time is not None:
        a_dur = max(0.0, answer_time - 5.0)
    else:
        a_dur = content_duration(a_items, item_seconds_fn)
        if not has_answer_content and has_plain_answer:
            a_dur += ANSWER_TEXT_SEC
    return q_dur + a_dur
