# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""age_years. Public namespace: shikimori_api."""
from __future__ import annotations
import shikimori_api as _api


def age_years(when) -> _api.Optional[float]:
    """Возраст тайтла в годах (дробных) на сегодня. when — datetime.date (точно по
    дню/месяцу), int-год (грубо по году) или None. None/ошибка → None («возраст
    неизвестен»)."""
    if when is None:
        return None
    try:
        if isinstance(when, _api.datetime.date):
            return max(0.0, (_api.datetime.date.today() - when).days / 365.25)
        return max(0.0, float(_api.datetime.date.today().year - int(when)))
    except (TypeError, ValueError):
        return None

age_years.__module__ = _api.__name__
_api.age_years = age_years

def effective_age(when, until=None, ongoing: bool = False):
    """Возраст, по которому меряется свежесть тайтла (None — неизвестен).

    «Ван-Пис» выходит с 1999 года, но идёт до сих пор: штраф за старость ему
    полагается заметно мягче, чем ровеснику, который кончился в том же
    девяносто девятом (просьба пользователя). Поэтому возраст считается по
    ОБОИМ краям выпуска — началу и концу — и берётся середина: тайтл, который
    всё ещё выходит, стареет вдвое медленнее, а тайтл, вышедший и закончившийся
    в один год, не меняется вовсе.

    until — дата (или год) окончания, ongoing=True — «ещё выходит», и тогда
    концом считается сегодняшний день. Ничего не известно (старый кэш, у
    карточки нет полей) — возраст считается по одному началу, ровно как
    раньше."""
    started = _api.age_years(when)
    if started is None:
        return None
    if ongoing:
        finished = 0.0
    else:
        finished = _api.age_years(until)
        if finished is None:
            return started
    # Конец раньше начала — в карточке путаница; верим тому краю, что старше.
    return max(0.0, (started + min(started, finished)) / 2.0)


def index_factors(when, score: float = 0.0, manga: bool = False,
                  until=None, ongoing: bool = False) -> tuple[float, float]:
    """Множители индекса: (свежесть выхода, оценка). recency ∈ [floor, 1.0],
    score_factor ∈ [0.6, 1.4]. when — дата выхода (точно по дню/месяцу) или год.
    Вынесено, чтобы и считать индекс, и показывать в подсказке влияние года/оценки.

    until/ongoing — когда тайтл кончился и идёт ли он до сих пор (см.
    effective_age): выходящий сериал забывают медленнее вышедшего.

    manga=True — книжные полураспад и пол: год в карточке книги означает начало
    выпуска, а читают её все те же десятилетия (см. _INDEX_MANGA_HALF_LIFE_YEARS)."""
    if manga:
        half_life = _api._INDEX_MANGA_HALF_LIFE_YEARS
        floor = _api._INDEX_MANGA_RECENCY_FLOOR
    else:
        half_life = _api._INDEX_HALF_LIFE_YEARS
        floor = _api._INDEX_RECENCY_FLOOR
    age = _api.effective_age(when, until, ongoing)
    if age is None:
        recency = floor                       # дата неизвестна — считаем «старым»
    else:
        recency = max(floor, 0.5 ** (age / half_life))
    score_factor = 1.0 + _api._INDEX_SCORE_INFLUENCE * (float(score or 0.0) - _api._INDEX_SCORE_PIVOT)
    score_factor = max(0.6, min(1.4, score_factor))
    return recency, score_factor

effective_age.__module__ = _api.__name__
_api.effective_age = effective_age
index_factors.__module__ = _api.__name__
_api.index_factors = index_factors

def popularity_index(base: float, when, score: float = 0.0,
                     manga: bool = False, until=None,
                     ongoing: bool = False) -> float:
    """«Индекс популярности»: взвешенная по статусам база (index_base_from_card —
    просмотрено=10, смотрю=8, брошено/отложено=6, запланировано=2), домноженная
    на свежесть выхода тайтла (точно по дате) и СЛАБО — на его оценку. Чем свежее
    тайтл и выше оценка, тем выше индекс при той же базе.

    Единственное место, где живёт эта формула: ею пользуется и сортировка во
    вкладке ShikimoriHYX, и цены вопросов в генераторе аниме-паков."""
    if base <= 0:
        return 0.0
    recency, score_factor = _api.index_factors(when, score, manga,
                                               until, ongoing)
    return base * recency * score_factor

popularity_index.__module__ = _api.__name__
_api.popularity_index = popularity_index

def index_favorites_factor(base: float, favorites) -> float:
    """Множитель индекса за «в избранном» (1.0 — поправки нет).

    Считаем не само число, а его ДОЛЮ от базы списков: тайтл, который посмотрели
    немногие, но полюбили почти все, знают куда лучше, чем говорит одна лишь
    посещаемость. Ровно про это и просил пользователь («Ван-Пис», «Детектив
    Конан», «Одинокий рокер» — смотрело мало, знают все).

    Множитель работает ТОЛЬКО В ПЛЮС, никогда не ниже 1.0. Иначе он бил бы по
    двум невиновным: по сиквелам (в избранное кладут первый сезон, а не шестой,
    и «Моя геройская академия 2» получила бы меньше собственной франшизы) и по
    тайтлам вроде «Покемона», которых знают все, хотя в избранном их почти ни у
    кого. Мера умеет доказать известность, но не умеет доказать безвестность.

    favorites < 0 значит «не спрашивали»: индекс считается как раньше."""
    try:
        fav = int(favorites)
    except (TypeError, ValueError):
        return 1.0
    if fav <= 0 or base <= 0:
        return 1.0
    share = fav / float(base)
    factor = (share / _api._INDEX_FAVORITES_PIVOT) ** _api._INDEX_FAVORITES_POWER
    return max(1.0, min(_api._INDEX_FAVORITES_MAX, factor))

index_favorites_factor.__module__ = _api.__name__
_api.index_favorites_factor = index_favorites_factor
