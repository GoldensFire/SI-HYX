# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Откуда PixivArtClient берёт работы: три источника выдачи.

Методы подключаются в тело PixivArtClient обычным импортом (см.
pixiv_art_api.py) — одна связная задача: сходить в Pixiv и вернуть сырые
работы, которые ещё предстоит отобрать.

Источников три, и порядок у них не случаен:

1. «популярное превью» по ТОЧНОЙ метке названия — один запрос и почти всегда
   всё, что нужно (бесплатному ключу обычный поиск отдаёт вчерашние загрузки);
2. та же верхушка, но по ЧАСТИ метки и с минусами — Pixiv сам выбрасывает
   лишнее, и тридцать мест выдачи не тратятся впустую;
3. обычный постраничный поиск — для малоизвестных тайтлов и узких режимов.
"""
from __future__ import annotations

from pixiv_art_api import (MIN_CHOICES, POPULAR_PATH, R18_TAG,
                           SEARCH_PAGES, SEARCH_PAGE_SIZE,
                           PixivArtUnavailable, _value)


def _popular_rows(self, query: str, keep, stats: dict) -> list:
    """Подошедшие работы из «популярного превью» Pixiv — один запрос.

    Главный источник артов. Обычный поиск бесплатному ключу отдаёт
    ВЧЕРАШНИЕ загрузки: sort=popular_desc для него молча превращается в
    date_desc, и на первой странице лежат работы с нулём закладок (по
    «Психопаспорту» так и приходил рисунок с четырьмя — «в вопросе
    непонятно что»). А этот адрес открыт и без премиума и отдаёт ровно
    верхушку тега: по 鬼滅の刃 — тридцать работ от 234 000 закладок и ниже
    (проверено на живом API).

    Тридцать заметных работ разом лечат и вторую беду: выбирать случайную
    стало ИЗ ЧЕГО. Раньше планку проходила одна работа из девяноста, пул
    выбора состоял из неё одной, и пак за паком по тайтлу приходил один и
    тот же арт.

    Метод без запроса возвращает пустое: у страницы нет ни страниц, ни
    своих настроек — «только R-18» и «только ИИ» сужаются тем же тегом в
    слове запроса, что и в обычном поиске."""
    rows = self._popular_illusts(query)
    if not rows:
        return []
    self._count(rows, stats)
    return [row for row in rows if keep(row)]

def _minus_rows(self, query: str, keep, stats: dict) -> list:
    """Верхушка тега, из которой Pixiv САМ выбросил лишнее — по минусам.

    Минус понимает только поиск «по части тега» (у «полного совпадения»
    он отдаёт ноль работ — проверено на живом API), а «часть тега» сама по
    себе неточна: по запросу «Air» приходят работы с меткой «Fairy», у
    которых точной метки «Air» нет вовсе. Поэтому выдача проверяется
    здесь же: у работы должен быть КАЖДЫЙ положительный тег запроса
    целиком — ровно то, что делал бы «полное совпадение».

    Путь запасной: он подключается, когда точного поиска на пул не
    хватило. Своё место у него честное — тридцать мест выдачи не тратятся
    на то, что мы всё равно выбросим."""
    # R-18 в режиме «исключать» уходит минусом первым делом: Pixiv
    # выбросит такие работы сам и подставит вместо них следующие по
    # закладкам, а у нас они просто пропадали из тридцати мест выдачи.
    first = (R18_TAG,) if self.r18_mode == "exclude" else ()
    tail = self.rules.query_tail(query, first=first)
    if not tail:
        return []
    rows = self._popular_illusts(f"{query} {tail}",
                                 target="partial_match_for_tags")
    rows = [row for row in rows if self._exact_tags(row, query)]
    if not rows:
        return []
    self._count(rows, stats)
    return [row for row in rows if keep(row)]

def _exact_tags(self, illust, query: str) -> bool:
    """Есть ли у работы КАЖДОЕ слово запроса отдельной меткой целиком."""
    flat = {name.replace(" ", "") for name in self._tag_names(illust)}
    return all(word.casefold().replace(" ", "") in flat
               for word in query.split() if word)

def _popular_illusts(self, query: str,
                     target: str = "exact_match_for_tags") -> list:
    """Сырая выдача «популярного превью» ([] — этот путь недоступен).

    Своего метода у PixivPy для него нет, поэтому зовём адрес напрямую его
    же сессией. Всё, чего не хватает (подменённый в тестах api, старая
    версия PixivPy, ошибка сети), означает ровно «иди обычным поиском»."""
    call = getattr(self.api, "no_auth_requests_call", None)
    parse = getattr(self.api, "parse_result", None)
    host = str(getattr(self.api, "hosts", "") or "")
    token = str(getattr(self.api, "access_token", "") or "")
    if not (callable(call) and callable(parse) and host and token):
        return []
    try:
        answer = call("GET", f"{host}{POPULAR_PATH}", params={
            "word": query, "search_target": target,
            "filter": "for_ios", "include_translated_tag_results": "true",
            # Значения те же, что и в обычном поиске: 1 — «скрыть работы
            # нейросети», 0 — «показывать всё» (см. _search_pages).
            "search_ai_type": 1 if self.ai_mode == "exclude" else 0,
        }, headers={"Authorization": f"Bearer {token}"})
        return list(_value(parse(answer), "illusts", []) or [])
    except Exception:          # noqa: BLE001 — любой сбой = обычный поиск
        return []

def _search_pages(self, query: str, keep, stats: dict) -> tuple[list, int]:
    """Страницы одного запроса: (подошедшие работы, сколько всего видели).

    Запасной путь — для тайтлов, у которых верхушка тега пуста или совсем
    мала (см. _popular_rows). Листаем, ПОКА НЕ НАБРАЛОСЬ MIN_CHOICES
    работ, прошедших планку: на одной остановке пул выбора состоял из
    единственного арта, и случайность была только на словах."""
    out: list = []
    seen: set[str] = set()
    for page in range(SEARCH_PAGES):
        if self.stopped():
            break
        try:
            # popular_desc бесплатной подписке Pixiv недоступен и
            # молча превращается в date_desc — вреда от него нет, а
            # премиум-ключу он сразу отдаёт заметные работы.
            result = self.api.search_illust(
                query, search_target="exact_match_for_tags",
                sort="popular_desc",
                # ВНИМАНИЕ на значения: 1 — «скрыть работы нейросети»,
                # 0 — «показывать всё». Отдельного «только ИИ» у поиска
                # Pixiv нет, поэтому в этом режиме просим всё, сужаем
                # запрос тегом AI_TAG, а отбираем уже у себя (_safe).
                search_ai_type=1 if self.ai_mode == "exclude" else 0,
                offset=page * SEARCH_PAGE_SIZE)
        except Exception:
            raise PixivArtUnavailable("Поиск Pixiv сейчас недоступен.") from None
        fresh = []
        for row in (_value(result, "illusts", []) or []):
            mark = self._url(row) or str(_value(row, "id", "") or "")
            if not mark or mark in seen:
                continue
            seen.add(mark)
            fresh.append(row)
        self._count(fresh, stats)
        if not fresh:            # страница без новых работ — тег вычерпан
            break
        out += [row for row in fresh if keep(row)]
        if sum(1 for row in out if self._good_enough(row)) >= MIN_CHOICES:
            break
    return out, len(seen)

def _count(self, rows, stats: dict) -> None:
    """Считает, что вообще отдал Pixiv: всего работ, из них R-18 и ИИ.

    Нужно ровно для одного ответа пользователю: «Pixiv не прислал ни одной
    работы R-18» почти всегда значит, что R-18 скрыт в настройках самого
    аккаунта, а не что артов нет."""
    for row in rows:
        stats["rows"] = stats.get("rows", 0) + 1
        if int(_value(row, "x_restrict", 0) or 0) == 1:
            stats["r18"] = stats.get("r18", 0) + 1
        if int(_value(row, "illust_ai_type", 0) or 0) == 2:
            stats["ai"] = stats.get("ai", 0) + 1
