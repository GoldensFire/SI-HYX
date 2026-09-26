# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
"""Какому сезону принадлежит серия, по которой собран вопрос по сюжету.

Вики держит серии сплошной нумерацией: у «Моей геройской академии» страница
зовётся «Episode 73», хотя это десятая серия ЧЕТВЁРТОГО сезона. Карточка же
кандидата — первый сезон, потому что именно он попался в каталоге. Получалось
вранье в обе стороны: вопрос назывался «Моя геройская академия» без сезона, в
ответе висел постер первого сезона, а ведущему полагалось объявить «серия 73»,
которой в первом сезоне отродясь не было (просьба пользователя).

Сезон берётся из инфобокса самой страницы (`|season number=4`) — вики его и
проставляет. Дальше по франшизе Shikimori находится карточка нужного сезона, а
номер серии пересчитывается: из сплошного вычитаются серии предыдущих сезонов.
Не сошлось хоть что-нибудь (сезона нет в инфобоксе, частей франшизы меньше, чем
сезонов, названия не подтверждают порядок) — не трогаем ничего: вопрос без
сезона лучше вопроса с чужим сезоном.
"""
from __future__ import annotations

import re

import animepack as _api

from .plot_air_date import (air_date_of_page, card_date, episode_in_part,
                            episodes_of, part_for_date)

# `|season number = 4`, `|season=4`, `|сезон=4` в инфобоксе серии. Значение —
# только число: «Season 4 Part 2» и прочую вольницу разбирать не берёмся.
_SEASON_FIELD = re.compile(
    r"^\s*\|\s*(?:season[ _]*(?:number|no)?|сезон)\s*=\s*(\d{1,2})\s*$",
    re.IGNORECASE | re.MULTILINE)
# `|ep number = 73`, `|episode=73` — сплошной номер серии оттуда же. Нужен,
# когда в имени страницы номера нет («Temp Squad»).
_EPISODE_FIELD = re.compile(
    r"^\s*\|\s*(?:number|ep(?:isode)?[ _]*(?:number|no)?|серия|эпизод)\s*="
    r"\s*([^\n|}]+?)\s*$", re.IGNORECASE | re.MULTILINE)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5,
    "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}
# Верхняя защита от случайного числа; у «Покемона» уже больше 20 сезонов.
MAX_SEASON = 99


def season_of_page(raw: str) -> int:
    """Номер сезона из инфобокса страницы серии (0 — не написан)."""
    match = _SEASON_FIELD.search(str(raw or ""))
    if not match:
        return 0
    number = int(match.group(1))
    return number if 1 <= number <= MAX_SEASON else 0


def episode_of_page(raw: str) -> str:
    """Сплошной номер серии из инфобокса («» — не написан)."""
    match = _EPISODE_FIELD.search(str(raw or ""))
    if not match:
        return ""
    value = match.group(1).strip()
    digits = re.search(r"\b(\d{1,3})\b", value)
    if digits:
        return str(int(digits.group(1)))
    word = re.sub(r"[^a-z]+", "", value.casefold())
    number = _NUMBER_WORDS.get(word, 0)
    return str(number) if number else ""


def episode_in_season(absolute, before: int) -> str:
    """Номер серии внутри сезона по сплошному номеру («» — не пересчитать).

    before — сколько серий вышло во всех предыдущих сезонах. Номер, который и
    так меньше этой суммы, значит, что вики считает серии посезонно: пересчёт
    только испортил бы его."""
    try:
        number = int(str(absolute).strip())
    except (TypeError, ValueError):
        return ""
    if number <= 0 or before <= 0 or number <= before:
        return ""
    return str(number - before)


def ordered_tv_parts(parts) -> list:
    """ТВ-части франшизы по порядку выхода — это и есть её сезоны.

    Фильмы, OVA и спешлы сезонами не считаются: вики нумерует по телесериалу.
    Порядок — по году выхода, при совпадении по номеру Shikimori (он растёт
    вместе с датой добавления)."""
    rows = [p for p in (parts or [])
            if isinstance(p, dict) and str(p.get("kind") or "") == "tv"]
    def _key(card):
        try:
            year = int((card.get("airedOn") or {}).get("year") or 0)
        except (TypeError, ValueError):
            year = 0
        try:
            ident = int(card.get("id") or 0)
        except (TypeError, ValueError):
            ident = 0
        return (year or 9999, ident)
    rows.sort(key=_key)
    return rows


def order_confirmed(parts: list) -> bool:
    """Подтверждают ли сами названия, что порядок совпал с нумерацией сезонов.

    У Shikimori сезоны подписаны номером («Моя геройская академия 4», «Kingdom
    4th Season»), и это единственная доступная проверка. Хотя бы одно название
    не на своём месте — порядку не верим вовсе: подставить чужой сезон хуже,
    чем не подставить никакого.

    Проверяются РОВНО те части, которые нужны вопросу, а не вся франшиза: у
    «Моей геройской академии» восьмым телесериалом идёт «Финал» без номера, и
    сверка всей серии заваливала бы совершенно исправные первые семь."""
    from animepack_plot import season_number
    for number, card in enumerate(parts, start=1):
        said = season_number(str(card.get("russian") or ""),
                             str(card.get("name") or ""))
        if said != number:
            return False
    return True


def episodes_before(cards: list) -> int:
    """Сколько серий вышло в этих сезонах вместе (0 — хоть у одного неизвестно).

    Ноль у любой части — повод не пересчитывать номер вовсе: наполовину
    сложенная сумма дала бы номер серии, которой нет."""
    total = 0
    for card in cards:
        try:
            count = int(card.get("episodes") or 0)
        except (TypeError, ValueError):
            count = 0
        if count <= 0:
            return 0
        total += count
    return total


def _has_kinds(parts) -> bool:
    """Знает ли кэш частей про их тип (`kind`) — иначе он из старой базы."""
    return all(isinstance(p, dict) and "kind" in p for p in (parts or []))


def _cached_tv_parts(generator, card: dict) -> list:
    """ТВ-части франшизы из базы, включая полный локальный каталог."""
    key = str((card or {}).get("franchise") or "").strip()
    if not key:
        return []
    parts = generator.db_cache.franchise(key)
    if parts is not None and not _has_kinds(parts):
        # Части, набранные до того, как мы стали спрашивать `kind`: отличить
        # сезон от полнометражки по такой карточке нечем, а «нет поля» и
        # «не сериал» — разные вещи. Спрашиваем заново и кладём в базу.
        parts = None
    if parts is None:
        try:
            parts = (generator.shikimori.franchise_parts([key]) or {}).get(key)
        except Exception:  # noqa: BLE001 — без сезона вопрос всё равно выйдет
            return []
        if parts is not None:
            generator.db_cache.add_franchises({key: list(parts)})
    combined = list(parts or [])
    try:
        combined += [row for row in generator.db_cache.all_cards("anime")
                     if str((row or {}).get("franchise") or "").strip() == key]
    except Exception:  # noqa: BLE001 — старый тестовый кэш без каталога
        pass
    by_id = {}
    for row in combined:
        ident = str((row or {}).get("malId") or (row or {}).get("id") or "")
        if ident:
            # Полная карточка каталога идёт последней и заменяет куцую часть.
            by_id[ident] = row
    scoped = _api.franchise_branch_parts(card, list(by_id.values()))
    return ordered_tv_parts(scoped)


def franchise_seasons(generator, card: dict, upto: int = 0) -> list:
    """Карточки сезонов франшизы этого тайтла — с числом серий у каждого.

    upto — сколько сезонов нужно вопросу (0 — все, сколько нашлось). Части
    франшизы лежат в базе (их набирает та же кнопка «Обновить базу»), но числа
    серий в них нет: карточка части намеренно куцая. Поэтому у нужных сезонов
    карточки берутся целиком — одним запросом, и только когда сезон вопроса и
    правда не первый."""
    ordered = _cached_tv_parts(generator, card)
    if upto > 0:
        if len(ordered) < upto:
            return []
        ordered = ordered[:upto]
    if not ordered or not order_confirmed(ordered):
        return []
    return _full_cards(generator, ordered)


def _full_cards(generator, ordered: list) -> list:
    """Полные карточки этих частей, в том же порядке (пусто — не все нашлись)."""
    ids = []
    for part in ordered:
        try:
            mal = int(part.get("malId") or 0)
        except (TypeError, ValueError):
            mal = 0
        if mal:
            ids.append(mal)
    if not ids:
        return []
    by_id = {}
    try:
        cached = generator.db_cache.all_cards("anime")
    except Exception:  # noqa: BLE001
        cached = []
    for row in cached:
        try:
            by_id[int(row.get("malId") or 0)] = row
        except (TypeError, ValueError):
            continue
    missing = [ident for ident in ids if ident not in by_id]
    if missing:
        try:
            full = generator.shikimori.animes_by_ids(missing)
        except Exception:  # noqa: BLE001
            return []
        for row in full:
            try:
                by_id[int(row.get("malId") or 0)] = row
            except (TypeError, ValueError):
                continue
    out = [by_id[i] for i in ids if i in by_id]
    return out if len(out) == len(ids) else []


def _swap_card(generator, cand, target: dict, page: str, why: str) -> None:
    """Подменяет карточку кандидата на карточку нужной части франшизы."""
    try:
        same = int(target.get("id") or 0) == int(cand.anime.get("id") or 0)
    except (TypeError, ValueError):
        same = False
    if same:
        return
    # Название, постер и варианты ответа берутся из карточки — подменив её, мы
    # разом чиним и вопрос, и ответ. Цена с уровнем пересчитаются сами: у
    # частей одной франшизы узнаваемость общая.
    cand.anime = target
    # Медиа подписывается названием тайтла, а имя уже выдано по прежней
    # карточке (см. _media_base): переименовываем, иначе постер четвёртого
    # сезона лежал бы в паке под названием первого.
    rename = getattr(generator, "_media_base", None)
    if rename is not None and getattr(cand, "media_base", ""):
        cand.media_base = rename(cand)
    generator.log(f"Сюжет: «{page}» — {why}, беру карточку "
                  f"«{target.get('russian') or target.get('name')}»")


def _by_air_date(generator, cand, raw: str, page: str, absolute: str,
                 local: str = ""):
    """Часть франшизы по дате выхода серии; None — дату не применить.

    Самый надёжный путь и единственный, который берёт части без номера в
    названии: «Алисизацию» и её «Войну в Подмирье» ни номер сезона из инфобокса
    (там у всех трёх стоит «3»), ни сверка названий по порядку не различают, а
    дата показа различает сразу."""
    when = air_date_of_page(raw)
    if not when:
        return None
    parts = _full_cards(generator, _cached_tv_parts(generator, cand.anime))
    if not parts:
        return None
    # Кэш частей знает только год, а частей одного года бывает несколько (у
    # «Мастеров Меча Онлайн» в 2018-м вышли и «Алисизация», и спин-офф
    # «Призрачная пуля»): пересортировываем по полной дате из полных карточек.
    parts.sort(key=lambda row: card_date(row) or (9999, 99, 99))
    index = part_for_date(parts, when)
    if index < 0:
        return None
    _swap_card(generator, cand, parts[index], page,
               f"серия от {when[2]:02d}.{when[1]:02d}.{when[0]}")
    inside = episode_in_part(parts, index, absolute)
    if inside:
        return inside
    try:
        if local and 0 < int(local) <= episodes_of(parts[index]):
            return str(int(local))
    except (TypeError, ValueError):
        pass
    # Страница всё равно дала подтверждённый номер: не теряем его полностью.
    return absolute


def apply_season(generator, cand, raw: str, page: str) -> str:
    """Ставит кандидату сезон со страницы и возвращает номер серии в сезоне.

    Возвращает номер серии для реплики ведущего: пересчитанный, если сезон
    нашёлся, и прежний сплошной, если нет. Карточку кандидата подменяет только
    при полном совпадении — иначе оставляет как была."""
    page_number = _api.episode_number(page)
    local = episode_of_page(raw)
    absolute = page_number or local
    season = season_of_page(raw)
    if not absolute:
        return absolute
    # Лезть во франшизу есть смысл только тогда, когда карточка и правда под
    # подозрением: инфобокс назвал не первый сезон либо серий у карточки меньше,
    # чем номер серии (у «Мастеров Меча Онлайн» их 25, а страница про 45-ю).
    # Иначе каждый вопрос по сюжету стоил бы лишних запросов к Shikimori.
    when = air_date_of_page(raw)
    if (season <= 1 and not _beyond_card(cand.anime, absolute)
            and not _outside_run(cand.anime, when)):
        return absolute
    dated = _by_air_date(generator, cand, raw, page, absolute, local)
    if dated is not None:
        return dated
    if season <= 1:
        return absolute
    seasons = franchise_seasons(generator, cand.anime, season)
    if len(seasons) < season:
        return absolute
    before = episodes_before(seasons[:season - 1])
    inside = episode_in_season(absolute, before)
    _swap_card(generator, cand, seasons[season - 1], page,
               f"это {season}-й сезон")
    return inside or absolute


def _beyond_card(card: dict, absolute: str) -> bool:
    """Номер серии больше, чем серий у карточки, — значит, карточка чужая."""
    total = episodes_of(card)
    if total <= 0:
        return False
    try:
        return int(str(absolute).strip()) > total
    except (TypeError, ValueError):
        return False


def _outside_run(card: dict, when) -> bool:
    """Дата страницы лежит вне выпуска карточки — значит, часть не та."""
    if not when:
        return False
    start = card_date(card)
    released = (card or {}).get("releasedOn") or {}
    try:
        end = (int(released.get("year") or 0),
               int(released.get("month") or 12),
               int(released.get("day") or 31))
    except (TypeError, ValueError, AttributeError):
        end = ()
    return bool((start and when < start) or (end and end[0] and when > end))
