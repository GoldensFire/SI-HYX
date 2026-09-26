# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# shikimori_api.py — слой доступа к Shikimori API (REST v1) и слой фильтрации.
# Здесь НЕТ ничего из Qt: модуль чисто сетевой/логический, его можно тестировать
# и переиспользовать отдельно от GUI (вкладка ShikimoriHYX в shikimori_tab.py).
#
# Архитектура (как просили — раздельные слои):
#   • ShikimoriApiClient — тонкий HTTP-клиент поверх requests (таймауты, ретраи
#     на 429/5xx, типизированные результаты, понятные ошибки).
#   • Anime               — типизированная модель элемента ответа.
#   • AnimeFilter         — критерии поиска. Часть отдаёт серверу (search/kind/
#     status/season/score/genre), а чего сервер не умеет (верхняя граница оценки,
#     диапазоны эпизодов/лет) — досчитывается ЛОКАЛЬНО (matches_local).
#   • find_anime()        — высокоуровневый помощник: серверный поиск с
#     пагинацией + локальная доводка под полный набор критериев.
from __future__ import annotations
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


import datetime
import math
import time
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

try:
    import requests
    from requests import Session
    _HAS_REQUESTS = True
except Exception:  # pragma: no cover - requests есть в requirements
    requests = None  # type: ignore
    Session = Any  # type: ignore
    _HAS_REQUESTS = False


# Текущий рабочий домен Shikimori.
DEFAULT_BASE_URL = "https://shikimori.io"
# Shikimori ТРЕБУЕТ осмысленный User-Agent (иначе 403/429). Подставляется
# название приложения; вызывающая сторона может переопределить.
DEFAULT_USER_AGENT = "SI-HYX/0.4 (+https://github.com)"

# Допустимые значения серверных фильтров (для валидации в UI и тестах).
KINDS = ("tv", "movie", "ova", "ona", "special", "music",
         "tv_13", "tv_24", "tv_48")
STATUSES = ("anons", "ongoing", "released")
ORDERS = ("ranked", "popularity", "name", "aired_on", "episodes",
          "kind", "id", "random")

# Человеко-читаемые подписи (RU) для UI — здесь, чтобы маппинг жил рядом с API.
KIND_LABELS = {
    "tv": "ТВ-сериал", "movie": "Фильм", "ova": "OVA", "ona": "ONA",
    "special": "Спешл", "music": "Клип", "tv_13": "ТВ ≤13 эп.",
    "tv_24": "ТВ ≤24 эп.", "tv_48": "ТВ ≤48 эп.",
}
STATUS_LABELS = {"anons": "Анонс", "ongoing": "Онгоинг", "released": "Вышло"}

# ── Манга ────────────────────────────────────────────────────────────────────
# Shikimori отдаёт мангу через /api/mangas с теми же параметрами поиска
# (search/kind/status/season/score/genre/order), но другими допустимыми kind/
# status и «главами» (chapters) вместо эпизодов.
MANGA_KINDS = ("manga", "manhwa", "manhua", "light_novel", "novel",
               "one_shot", "doujin")
MANGA_STATUSES = ("anons", "ongoing", "released", "paused", "discontinued")
MANGA_KIND_LABELS = {
    "manga": "Манга", "manhwa": "Манхва", "manhua": "Маньхуа",
    "light_novel": "Ранобэ", "novel": "Роман", "one_shot": "Ваншот",
    "doujin": "Додзинси",
}
MANGA_STATUS_LABELS = {
    "anons": "Анонс", "ongoing": "Онгоинг", "released": "Вышло",
    "paused": "Пауза", "discontinued": "Брошено",
}

# Тип контента вкладки.
CONTENT_ANIME = "anime"
CONTENT_MANGA = "manga"

# «Просмотры» тайтла = сумма по спискам пользователей, КРОМЕ «запланировано»
# (и «отложено» — пользователь просил считать только реально смотревших):
# completed (просмотрено) + watching (смотрю) + dropped (брошено). Берётся из
# rates_statuses_stats полной карточки /api/animes/{id} (в списочном ответе её нет).
#
# ВАЖНО: Shikimori отдаёт `name` в rates_statuses_stats ЛОКАЛИЗОВАННОЙ строкой
# (по умолчанию по-русски: «Просмотрено»/«Смотрю»/«Брошено»…), а НЕ английским
# ключом. Поэтому матчим и английские ключи, и русские подписи (аниме и манга:
# «Прочитано»/«Читаю»). Сравнение регистронезависимое (см. views_from_card).
VIEW_STATUSES = frozenset({
    "completed", "watching", "dropped",          # английские ключи (на всякий)
    "просмотрено", "смотрю", "брошено",          # русские подписи (аниме)
    "прочитано", "читаю",                        # русские подписи (манга)
})

from si_hyx_parts.shikimori_api.views_from_card import views_from_card


# Веса статусов для «индекса популярности» (по просьбе пользователя): сколько
# «баллов» индекса даёт один пользователь из каждого списка. Реально смотревшие
# весомее планирующих. name в rates_statuses_stats приходит ЛОКАЛИЗОВАННЫМ (RU)
# или английским ключом — матчим оба, регистронезависимо (ср. VIEW_STATUSES).
_INDEX_STATUS_WEIGHTS = {
    "completed": 10.0, "просмотрено": 10.0, "прочитано": 10.0,   # просмотрено
    "watching": 8.0,   "смотрю": 8.0,       "читаю": 8.0,         # смотрю
    "dropped": 6.0,    "брошено": 6.0,                            # брошено
    "on_hold": 6.0,    "отложено": 6.0,                           # отложено
    "planned": 2.0,    "запланировано": 2.0,                      # запланировано
}

from si_hyx_parts.shikimori_api.index_base_from_card import index_base_from_card


# Каноничные RU-подписи статусов для разбивки индекса в подсказке (агрегируют и
# английские ключи, и локализованные имена аниме/манги к одной подписи).
_INDEX_STATUS_LABELS = {
    "completed": "Просмотрено", "просмотрено": "Просмотрено", "прочитано": "Прочитано",
    "watching": "Смотрю", "смотрю": "Смотрю", "читаю": "Читаю",
    "dropped": "Брошено", "брошено": "Брошено",
    "on_hold": "Отложено", "отложено": "Отложено",
    "planned": "В планах", "запланировано": "В планах",
}

from si_hyx_parts.shikimori_api.index_components_from_card import (
    index_components_from_card,
    index_base_from_statuses_stats,
)


# Параметры «индекса популярности». Половина узнаваемости теряется примерно за
# 5 лет — подобрано так, чтобы свежий тайтл с заметно меньшими просмотрами
# обходил старый «миллионник» (пример пользователя: тайтл 2025 г. с 8k узнают
# лучше, чем 2012 г. с 41k). Пол (floor) не даёт классике обнулиться совсем.
_INDEX_HALF_LIFE_YEARS = 6.0
_INDEX_RECENCY_FLOOR = 0.12
# У КНИГ год в карточке — это год НАЧАЛА выпуска, а не «когда её читали»:
# «Ван-Пис» помечен 1997-м, «Берсерк» — 1989-м, и по анимешным шести годам они
# садились на самый пол, ×8 уступая любому веб-комиксу позапрошлого сезона. На
# живом кэше из-за этого «Прощай, Эри» (2022) оказывалась узнаваемее «Берсерка»
# и «Спокойной ночи, Пунпун» вместе взятых. Мангу читают десятилетиями, поэтому
# полураспад у неё длиннее, а пол — выше.
_INDEX_MANGA_HALF_LIFE_YEARS = 14.0
_INDEX_MANGA_RECENCY_FLOOR = 0.35
# Очень слабое влияние оценки тайтла на индекс (просьба «прям незначительно»):
# отклонение оценки от ~7 баллов меняет индекс лишь на проценты.
_INDEX_SCORE_INFLUENCE = 0.04
_INDEX_SCORE_PIVOT = 7.0

# «В избранном» — вторая мера узнаваемости рядом со списками (просьба
# пользователя: «есть тайтлы, которые мало кто смотрел, но все знают»).
# Считается ДОЛЯ избранных от базы списков: «Детектива Конана» на Shikimori
# смотрели немногие (база 74 тыс.), а в избранное кладут вчетверо чаще
# среднего — и знают его все.
#
# Число берётся у САМОГО Shikimori, со страницы тайтла: в его API этого поля
# нет ни в GraphQL, ни в REST (см. ShikimoriApi._RE_FAVOURED). Чужие цифры
# (AniList и прочие) сюда не годятся — там другая, нерусскоязычная аудитория и
# совсем другие порядки величин.
#
# Замер по 36 тайтлам, избранных на тысячу единиц базы: от 0.5 («Моя геройская
# академия 2») до 9.0 («Легенда о героях Галактики») при медиане 2.4. На PIVOT
# множитель ровно 1.0. Степень сжимает разброс: без неё «Легенда» получила бы
# вчетверо больший индекс, чем заслуживает.
_INDEX_FAVORITES_PIVOT = 0.0024
_INDEX_FAVORITES_POWER = 0.35
_INDEX_FAVORITES_MAX = 1.50

from si_hyx_parts.shikimori_api.age_years import (age_years, effective_age,
                                                  index_factors,
                                                  index_favorites_factor,
                                                  popularity_index)


# ── Узнаваемость франшизы ────────────────────────────────────────────────────
# Сериал, у которого вышло несколько популярных сезонов, узнают лучше, чем
# одиночный тайтл с тем же числом зрителей: франшиза дольше держится на слуху.
# И штраф за возраст ему полагается не по году ПЕРВОГО сезона, а по году
# последнего заметного продолжения (просьба пользователя: «первый сезон 2002-го,
# продолжение 2007-го и тоже популярное — минус за год не должен быть большим»).
#
# «Заметной» считается часть, у которой база индекса хотя бы такая доля от базы
# самой популярной части: иначе франшизу раздували бы спешлы и пятиминутные ONA,
# которых никто не смотрел.
FRANCHISE_PART_SHARE = 0.2
# Надбавка за каждую заметную часть сверх первой и её потолок.
FRANCHISE_SEASON_BONUS = 0.05
FRANCHISE_SEASON_BONUS_MAX = 0.25

from si_hyx_parts.shikimori_api.franchise_parts_index import (
    franchise_parts_index,
    kinds_for,
    statuses_for,
    kind_label,
    status_label,
)


# ── Группировка жанров: Жанры / Темы / Демография ────────────────────────────
# Shikimori /api/genres отдаёт «классический» набор, где у ВСЕХ записей
# kind == "genre" (тип аниме/манга — в entry_type). Сам сайт Shikimori делит
# этот набор на «Жанры», «Темы» и «Демография». Поскольку REST не присылает эту
# принадлежность, классифицируем по стабильному английскому имени (одинаково для
# аниме и манги). Если же будущий API вернёт kind="theme"/"demographic" — доверяем
# ему (см. genre_group).
GROUP_GENRE = "genre"
GROUP_THEME = "theme"
GROUP_DEMOGRAPHIC = "demographic"

GENRE_GROUP_LABELS = {
    GROUP_GENRE: "Жанры",
    GROUP_THEME: "Темы",
    GROUP_DEMOGRAPHIC: "Демография",
}
# Порядок показа групп в интерфейсе.
GENRE_GROUP_ORDER = (GROUP_GENRE, GROUP_THEME, GROUP_DEMOGRAPHIC)

# Возрастные категории Shikimori.
_DEMOGRAPHIC_NAMES = frozenset({
    "kids", "shoujo", "shounen", "seinen", "josei",
})
# «Темы» (по классификации Shikimori/MAL): сеттинг/мотив, а не жанр.
_THEME_NAMES = frozenset({
    "cars", "demons", "game", "historical", "magic", "martial arts", "mecha",
    "music", "parody", "police", "samurai", "school", "space", "super power",
    "vampire", "harem", "military", "work life", "gender bender",
})

from si_hyx_parts.shikimori_api.genre_group import genre_group, ShikimoriError, Anime, AnimeFilter

from si_hyx_parts.shikimori_api.shikimori_api_client import ShikimoriApiClient, find_anime

from si_hyx_parts.shikimori_api.quick_find import quick_find
