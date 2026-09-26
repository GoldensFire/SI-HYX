# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""answer_query. Public namespace: animepack_upgrade."""
from __future__ import annotations
import animepack_upgrade as _api


def answer_query(text) -> str:
    """Что искать на Shikimori по строке правильного ответа.

    Общим правилом генератора отрезаем песню, год и тег («Наруто OP1 (2002) —
    『Song』» → «Наруто»), потом снимаем кавычки и хвостовое пояснение вида
    «(аниме)». Косую черту тут НЕ трогаем: «Fate/Zero» — это целое название, а
    ответы вида «Ueno-san wa Bukiyou/ Неуклюжая Уэно» разбираются отдельно, уже
    после того, как поиск по строке целиком ничего не дал (см. slash_parts)."""
    line = _api.answer_title(text)
    line = _api._RE_KIND_TAIL.sub("", line)
    line = _api._RE_QUOTES.sub("", line)
    return line.strip()

answer_query.__module__ = _api.__name__
_api.answer_query = answer_query

def slash_parts(text) -> list[str]:
    """Части ответа, записанного через косую черту, — по одной на название.

    Shikimori и сам показывает тайтл двумя названиями сразу («Неуклюжая Уэно /
    Ueno-san wa Bukiyou»), и в паках ответ пишут ровно так же — иногда без
    пробелов вокруг черты. Строкой целиком такой ответ не ищется, а каждой
    частью — находится.

    Части идут ПОСЛЕ строки целиком (см. answer_queries): «Fate/Zero» и
    «Robotics;Notes» — это цельные названия, и они опознаются раньше, чем дело
    дойдёт до разбиения."""
    line = str(text or "")
    if "/" not in line:
        return []
    return [part.strip() for part in line.split("/") if part.strip()]

slash_parts.__module__ = _api.__name__
_api.slash_parts = slash_parts

def answer_queries(answers, *, use_others: bool = True, min_len: int = 3,
                   limit: int = _api.MAX_QUERIES_PER_QUESTION) -> list[str]:
    """Чем пытаться опознать тайтл по всем вариантам ответа вопроса.

    Порядок важен: сначала первый ответ целиком, потом он же без песни за тире
    («Эхо террора - Trigger» → «Эхо террора»), потом его части через косую черту
    («Ueno-san wa Bukiyou/ Неуклюжая Уэно» → каждое название по отдельности), и
    только затем остальные строки ответа — в живых паках вторая строка обычно и
    есть голое название. Ищем до первого попадания, поэтому лишние варианты
    стоят запросов только там, где предыдущие ничего не дали."""
    texts = [str(a or "").strip() for a in (answers or [])]
    texts = [t for t in texts if t]
    if not texts:
        return []
    head = _api._RE_DASH_TAIL.sub("", texts[0])
    raw = [texts[0], head] + _api.slash_parts(head)
    if use_others:
        raw += texts[1:]
    out, seen = [], set()
    for text in raw:
        query = _api.answer_query(text)
        key = _api.norm_title(query)
        # Совсем короткое и то, в чём нет ни одной буквы («1945», «12»), не
        # ищем вовсе: к аниме это отношения не имеет, а запрос стоит секунды.
        if (len(query) < min_len or not key or key in seen
                or not _api.re.search(r"[^\W\d_]", query)):
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= max(1, limit):
            break
    return out

answer_queries.__module__ = _api.__name__
_api.answer_queries = answer_queries

def norm_title(text) -> str:
    """Название в сравнимом виде: без знаков, регистра и лишних пробелов."""
    return _api._RE_NON_WORD.sub(" ", str(text or "")).strip().casefold()

norm_title.__module__ = _api.__name__
_api.norm_title = norm_title

def card_names(card: dict) -> list[str]:
    """Все названия карточки Shikimori — по ним и опознаём тайтл."""
    names = _api.main_names(card) + [card.get("japanese")]
    names += list(card.get("synonyms") or [])
    return [str(n).strip() for n in names if str(n or "").strip()]

card_names.__module__ = _api.__name__
_api.card_names = card_names

def main_names(card: dict) -> list[str]:
    """Собственные названия тайтла — без синонимов и японского.

    Синонимы на Shikimori правит кто угодно и кладёт туда что угодно (у клипа
    «Yababaina» в них лежит «Teto Kasane» — имя вокалоида), поэтому совпадение
    только по ним доверия не заслуживает. Японское поле сюда тоже не идёт: у
    части записей там латиница строчными («mumei»)."""
    return [str(n).strip() for n in (card.get("russian"), card.get("name"),
                                     card.get("english"),
                                     card.get("licenseNameRu"))
            if str(n or "").strip()]

main_names.__module__ = _api.__name__
_api.main_names = main_names

def spelling_names(card: dict) -> list[str]:
    """Названия, по которым можно править НАПИСАНИЕ ответа.

    То же, что main_names, плюс синонимы: японское поле исключено намеренно —
    у записи «Mumei» там лежит «mumei», и «исправление регистра» понижало в
    ответе заглавную букву (живой случай из пака пользователя)."""
    return _api.main_names(card) + [str(n).strip()
                               for n in (card.get("synonyms") or [])
                               if str(n or "").strip()]

spelling_names.__module__ = _api.__name__
_api.spelling_names = spelling_names
