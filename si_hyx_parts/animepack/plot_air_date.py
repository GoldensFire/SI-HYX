# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Дата выхода серии из инфобокса вики — и часть франшизы, которой она своя.

Номер сезона в инфобоксе есть не всегда, а когда есть — по нему не найти
карточку Shikimori: у «Мастеров Меча Онлайн» третьим сезоном вики зовёт всю
«Алисизацию», а у Shikimori это ТРИ отдельных тайтла («Алисизация», «Война в
Подмирье», «Война в Подмирье 2»), и серия 45 лежит в последнем. Названия тут
тоже не помогают: «Алисизация» номера сезона в себе не несёт, и проверка
порядка по названиям такую франшизу отвергает целиком.

Зато дата выхода серии в инфобоксе стоит почти всегда и врать ей незачем:
`|Air Date = September 5, 2020` попадает ровно в окно показа «Войны в Подмирье
2» (12 июля — 20 сентября 2020). По ней часть и выбирается — без единого
названия и без номеров сезонов.
"""
from __future__ import annotations

import re

# `|Air Date = September 5, 2020`, `|japanese_air_date = February 26, 2021`.
# Между «japanese» и «air» бывает и пробел, и подчёркивание: у вики «Обещанного
# Неверленда» поле зовётся `japanese_air_date`, и прежний шаблон (с одним лишь
# пробелом) не находил там ничего. Серия 19 из-за этого оставалась при карточке
# первого сезона — с его постером и со сплошным номером серии.
# Английскую дату («english_air_date») не берём: она либо пустая, либо отстаёт
# от японской на годы, — поэтому приставка перечислена поимённо, а не «любая».
_AIR_FIELD = re.compile(
    r"^\s*\|\s*(?:(?:japanese|jp|original)\.?[ _]*)?air[ _]*date\s*=\s*(.+?)\s*$",
    re.IGNORECASE | re.MULTILINE)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5,
    "june": 6, "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_MONTH_FIRST = re.compile(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?"
                          r"\s+(\d{4})\b")
_DAY_FIRST = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?\s*,?"
                        r"\s+(\d{4})\b")
# Максимум суток сверх последней серии: у части нет-нет да и сдвинется финал
# (перенос, спецвыпуск вдогонку), а окно всё равно её.
_TAIL_DAYS = 21


def parse_date(value) -> tuple:
    """Дата из человеческой записи → (год, месяц, день); () — не разобрать."""
    text = re.sub(r"\[\[([^\]|]*\|)?|\]\]|'{2,}|<[^>]+>", " ", str(value or ""))
    match = _ISO.search(text)
    if match:
        year, month, day = (int(g) for g in match.groups())
    else:
        match = _MONTH_FIRST.search(text)
        if match:
            month = _MONTHS.get(match.group(1).casefold(), 0)
            day, year = int(match.group(2)), int(match.group(3))
        else:
            match = _DAY_FIRST.search(text)
            if not match:
                return ()
            month = _MONTHS.get(match.group(2).casefold(), 0)
            day, year = int(match.group(1)), int(match.group(3))
    if not (1 <= month <= 12 and 1 <= day <= 31 and 1900 <= year <= 2999):
        return ()
    return (year, month, day)


def air_date_of_page(raw: str) -> tuple:
    """Дата выхода серии из инфобокса страницы (() — не написана)."""
    for match in _AIR_FIELD.finditer(str(raw or "")):
        got = parse_date(match.group(1))
        if got:
            return got
    return ()


def card_date(card: dict, field: str = "airedOn") -> tuple:
    """Дата из карточки Shikimori; () — неизвестна хоть одна её часть.

    Месяц и день у Shikimori есть только в полной карточке (см. ANIME_FIELDS);
    в кэше частей франшизы лежит один год, и такая карточка сюда не годится."""
    block = (card or {}).get(field) or {}
    try:
        year = int(block.get("year") or 0)
        month = int(block.get("month") or 0)
        day = int(block.get("day") or 0)
    except (TypeError, ValueError):
        return ()
    if not (year and month and day):
        return ()
    return (year, month, day)


def _shifted(date: tuple, days: int) -> tuple:
    """Дата плюс сутки — грубо, помесячно: точность тут и не нужна."""
    year, month, day = date
    day += days
    while day > 28:
        day -= 30
        month += 1
        if month > 12:
            month, year = 1, year + 1
    return (year, month, max(day, 1))


def part_for_date(parts: list, date: tuple) -> int:
    """Какая из частей шла в этот день; -1 — ни одна.

    Части ждём уже упорядоченными по дате начала показа. Берём последнюю из
    начавшихся к этому дню и проверяем, что она к нему ещё не кончилась: серия,
    вышедшая между двумя частями, не принадлежит ни одной, и приписывать её
    предыдущей нельзя."""
    found = -1
    for index, card in enumerate(parts):
        start = card_date(card)
        if start and start <= date:
            found = index
    if found < 0:
        return -1
    end = card_date(parts[found], "releasedOn")
    if end and date > _shifted(end, _TAIL_DAYS):
        return -1
    return found


def episodes_of(card) -> int:
    """Сколько серий в части (0 — неизвестно)."""
    try:
        return max(0, int((card or {}).get("episodes") or 0))
    except (TypeError, ValueError):
        return 0


def episode_in_part(parts: list, index: int, absolute) -> str:
    """Номер серии внутри найденной части по сплошному номеру («» — никак).

    Сплошной номер вики ведёт от начала СВОЕЙ нумерации, а где та началась —
    неизвестно: у «Мастеров Меча Онлайн» серии «Алисизации» считаются с единицы
    заново, у «Моей геройской академии» — от самой первой серии франшизы.
    Поэтому идём от найденной части назад и вычитаем серии предыдущих, пока
    остаток остаётся живым номером внутри части. Берём САМЫЙ ДЛИННЫЙ такой
    разбег: у «Академии» подходят и «-2 сезона» (23), и «-3 сезона» (10), а
    верен второй — вики считает от начала всего сериала."""
    try:
        number = int(str(absolute).strip())
    except (TypeError, ValueError):
        return ""
    if number <= 0 or not (0 <= index < len(parts)):
        return ""
    limit = episodes_of(parts[index])
    best = str(number) if limit and number <= limit else ""
    total = 0
    for card in reversed(parts[:index]):
        count = episodes_of(card)
        if count <= 0:
            break
        total += count
        rest = number - total
        if rest < 1:
            break
        if limit and rest <= limit:
            best = str(rest)
    return best
