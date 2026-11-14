# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# sub_search.py — «Поиск по сабам» без Qt: фраза (по умолчанию «six seven») в
# английских субтитрах аниме. Тайтлы и их уровни — из базы Shikimori
# генератора аниме-паков, субтитры — SubDL, SubSource, TSDB и OpenSubtitles (ключи — общие, в Настройках → «Ключи API»). Реплики
# скачанных файлов лежат в кэше (corpus.sqlite), поэтому повторный поиск,
# в том числе другой фразы, идёт без сети. Вкладка — sub_search_tab.py.
#
# Реализация — si_hyx_parts/sub_search/; части обращаются сюда как `_api`.
"""Поиск фразы в английских субтитрах аниме (без интерфейса)."""
import sys as _sys
_api = _sys.modules[__name__]

import os

try:
    from config import CONFIG_DIR, APP_NAME, APP_VERSION
except Exception:  # pragma: no cover — запуск вне приложения
    CONFIG_DIR, APP_NAME, APP_VERSION = os.path.expanduser("~"), "SI-HYX", "0"

CACHE_DIR = os.path.join(CONFIG_DIR, "sub_search")
CORPUS_FILE = os.path.join(CACHE_DIR, "corpus.sqlite")
USER_AGENT = f"{APP_NAME}/{APP_VERSION} (anime subtitle phrase search)"

# Сроки кэша (секунды).
SUBS_TTL = 120 * 86400        # реплики скачанного файла (содержимое почти не меняется)
ERROR_TTL = 6 * 3600          # неудачное скачивание — спросить снова через 6 ч
LISTING_TTL = 7 * 86400       # список файлов тайтла у источников
MAPPING_TTL = 180 * 86400     # сопоставления AniZip (aniDB/MAL → TMDB/IMDb)
KV_MAX_AGE = 365 * 86400      # прочие ответы API старше года удаляются

# Источники, чьи файлы держит кэш (прочие — например, убранный GitHub-архив —
# вычищаются при первом прогоне).
SOURCES = ("subdl", "subsource", "tsdb", "opensubtitles")

ANIZIP_BASE = "https://api.ani.zip"
SUBDL_BASE = "https://api.subdl.com/api/v1"
SUBDL_DL = "https://dl.subdl.com"
SUBSOURCE_BASE = "https://api.subsource.net/api/v1"
TSDB_BASE = "https://api.thesubtitledb.org"
TSDB_GET = "https://api.thesubtitledb.org/get"
OPENSUBTITLES_BASE = "https://api.opensubtitles.com/api/v1"
REANIME_BASE = "https://reanime.to"   # ссылка «смотреть серию с момента»

from si_hyx_parts.sub_search.matcher import (  # noqa: E402
    Cue, Match, find_phrase, format_timecode, tokenize,
)
from si_hyx_parts.sub_search.parsers import parse_subtitles, is_english, guess_episode  # noqa: E402
from si_hyx_parts.sub_search.corpus import Corpus  # noqa: E402
from si_hyx_parts.sub_search.titles import (  # noqa: E402
    ORDER_EASY, ORDER_HARD, ORDER_VIEWS, ORDER_RANDOM, ORDER_LABELS,
    KIND_GROUPS, KIND_GROUP_LABELS, TitleInfo,
)
from si_hyx_parts.sub_search.engine import (  # noqa: E402
    SOURCE_LABELS, SearchRequest, SearchEngine, Hit, run_search,
)
from si_hyx_parts.sub_search.reanime import episode_link as reanime_link  # noqa: E402

__all__ = [
    "Cue", "Match", "find_phrase", "format_timecode", "tokenize",
    "parse_subtitles", "is_english", "guess_episode", "Corpus",
    "ORDER_EASY", "ORDER_HARD", "ORDER_VIEWS", "ORDER_RANDOM", "ORDER_LABELS",
    "KIND_GROUPS", "KIND_GROUP_LABELS", "TitleInfo",
    "SOURCE_LABELS", "SearchRequest", "SearchEngine", "Hit", "run_search",
    "reanime_link",
]
