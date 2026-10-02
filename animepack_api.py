# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# Логика вкладки «Генерация аниме-пака» портирована с разрешения автора из
# проекта ASPG (Anime Songs SiGame Pack Generator), Copyright (c) Leleath,
# лицензия MIT — https://github.com/Leleath/aspg
#
# animepack_api.py — сетевой слой генератора аниме-паков. Здесь НЕТ Qt: модуль
# чисто сетевой, его можно тестировать отдельно от GUI (сама вкладка —
# animepack_tab.py, отбор и сборка пака — animepack.py).
#
# Основные источники:
#   • AMQ (animemusicquiz.com/libraryMasterList) — вся база аниме, из которой
#     AMQ гоняет свою угадайку. Ответ ~16 МБ, поэтому кэшируется на диск.
#   • AnisongDB — песни (опенинги/эндинги/OST) по спискам MAL/ANN id.
#   • MyAnimeList — публичный список аниме пользователя (load.json).
#   • Shikimori — список пользователя (user_rates) и карточки аниме (GraphQL:
#     русское название, постер, скриншоты, жанры, франшиза, оценка).
#
# Источники отдельных родов вопросов — см. docs/anime-pack-sources.md:
#   • AniZip — превью каждой серии (третий источник кадров рядом с AniList и
#     Kitsu), ищется прямо по MAL id;
#   • MangaDex, MangaFire, Comix.to, WeebCentral — страницы манги;
#   • Sakugabooru — вырезки анимации без звука и титров.
#
# ВАЖНО, чем это отличается от оригинала ASPG (проверено живыми запросами):
#   • AnisongDB принимает тела в snake_case — {"mal_ids": […]} / {"ann_ids": […]}.
#     Старые camelCase-имена сервер молча принимает и отдаёт пустой список.
#   • Поля isDub / isRebroadcast теперь булевы, а не 0/1.
#   • Shikimori 301-редиректит .one → .io; requests на 301 превращает POST в GET
#     и теряет тело — за это отвечает ShikimoriApiClient._graphql (там редирект
#     обрабатывается вручную).
#   • Списки пользователей ПАГИНИРУЮТСЯ (и на MAL, и на Shikimori) — иначе
#     большие списки молча обрезаются.
from __future__ import annotations
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


import json
import os
import random
import re
import threading
import time
from collections import deque
from typing import Any, Callable, Iterable, Optional
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from config import CONFIG_DIR, APP_NAME, APP_VERSION
except Exception:  # pragma: no cover — вне приложения (тесты модуля в одиночку)
    APP_NAME, APP_VERSION = "SI-HYX", "0.0"
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".unified_media_tool")

USER_AGENT = f"{APP_NAME}/{APP_VERSION} (+https://github.com/GoldensFire/SI-HYX)"

AMQ_BASE = "https://animemusicquiz.com"
AMQ_CDN = "https://naedist.animemusicquiz.com"
ANISONG_BASE = "https://anisongdb.com/api"
MAL_BASE = "https://myanimelist.net"
# AniList — публичный GraphQL без ключа и без регистрации (90 запросов в минуту).
# Весь список пользователя приезжает ОДНИМ запросом и сразу с MAL id, так что
# сводить каталоги не нужно.
ANILIST_BASE = "https://graphql.anilist.co"
# Kitsu — JSON:API без ключа. Нужен ради превью СЕРИЙ: у Shikimori кадров мало и
# почти все с первой серии, а Kitsu хранит миниатюру каждого эпизода.
KITSU_BASE = "https://kitsu.app/api/edge"
# AnimeThemes — ролики опенингов/эндингов, тоже без ключа. Видео там без
# кредитов (nc), то есть без названия прямо в кадре, — для угадайки это и нужно.
ANIMETHEMES_BASE = "https://api.animethemes.moe"
# Fandom — вики тайтлов, откуда берётся ПЕРЕСКАЗ СЮЖЕТА для вопросов «по
# сюжету». Работаем только через обычный MediaWiki api.php конкретной вики:
# каталог community.fandom.com и весь Fandom REST (/api/v1/…) закрыты проверкой
# Cloudflare и отвечают 403 (см. FandomApi).
FANDOM_HOST = "fandom.com"
# AniZip — сводка тайтла по всем каталогам сразу, ищется прямо по MAL id. Нужна
# ради превью КАЖДОЙ серии с TheTVDB: у Shikimori кадров три-четыре и почти все
# с первой серии.
ANIZIP_BASE = "https://api.ani.zip"
# Jimaku — каталог настоящих субтитров. Ключ передаётся только заголовком
# Authorization; в сохранённые ссылки и журналы он не попадает.
JIMAKU_BASE = "https://jimaku.cc/api"
# SubDL — субтитры сразу на русском: диалог идёт в пак без перевода Gemini.
# Поиск по точному IMDb/TMDB id из AniZip; у ключа суточная квота.
SUBDL_BASE = "https://api.subdl.com/api/v1"
SUBDL_DL = "https://dl.subdl.com"
SUBDL_SITE = "https://subdl.com"
# MangaDex — страницы самой манги. Вопросом по манге служит разворот оригинала,
# а не обложка (обложку выдаёт постер в ответе).
MANGADEX_BASE = "https://api.mangadex.org"
# Sakugabooru — вырезки самой анимации: отрывок без звука, титров и названия.
SAKUGA_BASE = "https://sakugabooru.com"

# Кэш мастер-листа AMQ: ответ ~16 МБ, а меняется он раз в сутки.
AMQ_CACHE_PATH = os.path.join(CONFIG_DIR, "animepack_amq_library.json")
AMQ_CACHE_TTL = 24 * 3600


# Сколько id влезает в один запрос (AnisongDB держит и больше, но ответ пухнет).
ANISONG_BATCH = 300
# Shikimori GraphQL: жёсткий предел выборки animes(ids:…) — 50.
SHIKIMORI_BATCH = 50

# Статусы списков — единый внутренний словарь для обоих сайтов.
LIST_STATUSES = ("watching", "completed", "onhold", "dropped", "ptw")
STATUS_LABELS = {
    "watching": "Смотрю", "completed": "Просмотрено", "onhold": "Отложено",
    "dropped": "Брошено", "ptw": "Запланировано",
}
# Числовые статусы MAL из load.json.
_MAL_STATUS = {1: "watching", 2: "completed", 3: "onhold", 4: "dropped", 6: "ptw"}
# Строковые статусы Shikimori из /api/v2/user_rates.
_SHIKI_STATUS = {"watching": "watching", "rewatching": "watching",
                 "completed": "completed", "on_hold": "onhold",
                 "dropped": "dropped", "planned": "ptw"}
# Статусы AniList (MediaListStatus). REPEATING — это пересмотр, считаем «смотрю».
_ANILIST_STATUS = {"CURRENT": "watching", "REPEATING": "watching",
                   "COMPLETED": "completed", "PAUSED": "onhold",
                   "DROPPED": "dropped", "PLANNING": "ptw"}

# Shikimori идёт первым и по умолчанию: русские названия и статистика пака всё
# равно берутся оттуда, так что список с того же сайта совпадает точнее.
LIST_SOURCES = ("shikimori", "myanimelist", "anilist")
SOURCE_LABELS = {"myanimelist": "MyAnimeList", "shikimori": "Shikimori",
                 "anilist": "AniList"}

# Что именно берём из списка человека. Манга, манхва и маньхуа — это ОДИН
# раздел на всех трёх сайтах (Shikimori target_type=Manga, MAL /mangalist,
# AniList type: MANGA), поэтому и у нас это один тип списка, а издания
# отделяются потом фильтром «Типы» по полю kind карточки.
LIST_TARGETS = ("anime", "manga")
TARGET_LABELS = {"anime": "Аниме", "manga": "Манга/манхва/маньхуа"}
# Типы изданий Shikimori (поле kind у Manga).
MANGA_KINDS = ("manga", "manhwa", "manhua", "one_shot", "doujin")
MANGA_KIND_LABELS = {"manga": "Манга", "manhwa": "Манхва", "manhua": "Манхуа",
                     "one_shot": "Ваншот", "doujin": "Додзинси"}

from si_hyx_parts.animepack_api.anime_pack_api_error import (
    AnimePackApiError,
    RateLimiter,
    make_session,
    _friendly,
    AmqApi,
    AnisongApi,
    MalApi,
)

from si_hyx_parts.animepack_api.ani_list_api import AniListApi, KitsuApi

from si_hyx_parts.animepack_api.anizip_api import AniZipApi
from si_hyx_parts.animepack_api.jimaku_api import JimakuApi
from si_hyx_parts.animepack_api.subdl_api import SubdlApi, SubdlQuotaError

from si_hyx_parts.animepack_api.mangadex_api import (MangaDexApi,
                                                     chapter_link as
                                                     mangadex_chapter_link)
from si_hyx_parts.animepack_api.manga_json_readers import MangaFireApi, ComixApi
from si_hyx_parts.animepack_api.weebcentral_api import WeebCentralApi
from si_hyx_parts.animepack_api.remanga_reader import ReMangaApi
from si_hyx_parts.animepack_api.mangalib_reader import MangaLibApi
from si_hyx_parts.animepack_api.manga_page_sources import MangaPageSources

from si_hyx_parts.animepack_api.sakugabooru_api import (SakugaApi,
                                                        post_link as
                                                        sakuga_post_link)


# ─────────────────────────────────────────────────────────────────────────────
# TMDB (themoviedb.org) — запасной источник обложек
# ─────────────────────────────────────────────────────────────────────────────
TMDB_BASE = "https://api.themoviedb.org/3"
# Картинки TMDB лежат на своём CDN и ключа не требуют вовсе — ключ нужен только
# на поиск. «original» — исходный размер: под лимит пака его всё равно ужимает
# наш же кодировщик (avif_fit), а мельче брать незачем.
TMDB_IMG = "https://image.tmdb.org/t/p/original"

from si_hyx_parts.animepack_api.tmdb_api import TmdbApi, AnimeThemesApi

from si_hyx_parts.animepack_api.fandom_api import (FandomApi,
                                                   page_link as
                                                   fandom_page_link)


# Списки и путеводители — пересказа одной серии там нет.
_EPISODE_LIST = re.compile(r"^(list of|список)|guide$|episodes$",
                           re.IGNORECASE)
# Заголовок раздела: «== Summary ==», «===Plot===».
_HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.MULTILINE)

from si_hyx_parts.animepack_api.wiki_slugs import wiki_slugs, plot_section, strip_wikitext

from si_hyx_parts.animepack_api.shikimori_api import ShikimoriApi
