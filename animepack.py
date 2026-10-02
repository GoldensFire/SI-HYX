# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# Логика портирована с разрешения автора из проекта ASPG (Anime Songs SiGame
# Pack Generator), Copyright (c) Leleath, лицензия MIT —
# https://github.com/Leleath/aspg
#
# animepack.py — отбор песен и сборка .siq. Здесь НЕТ Qt: модуль тестируется
# отдельно от GUI (сама вкладка — animepack_tab.py, сеть — animepack_api.py).
#
# Как это работает:
#   1. Собираем список аниме — либо вся база AMQ (фильтр по году), либо списки
#      пользователей с MAL/Shikimori (фильтр по статусам, опционально «есть у N
#      пользователей»).
#   2. Пачками спрашиваем у AnisongDB песни этих аниме, отсеиваем по типу/
#      сложности/категории, а сами аниме — по карточке Shikimori (оценка, тип,
#      год, жанры, наличие постера/скриншотов).
#   3. КАНДИДАТЫ отдаются лениво (генератором), а качалка забирает их ровно
#      столько, сколько нужно вопросов: упавшую загрузку заменяет следующим
#      кандидатом, а не оставляет в паке вопрос с битой ссылкой (как ASPG).
#   4. Из принятых песен строим content.xml формата SIQ 5 и пакуем zip → .siq.
#
# Отличия от оригинала — это ИСПРАВЛЕНИЯ, а не смена поведения:
#   • качаются только те песни, что реально попали в пак (ASPG скачивал все
#      отобранные и паковал лишние файлы в архив);
#   • песня с несостоявшейся загрузкой заменяется следующей;
#   • длительность в XML пишется с ведущими нулями и не уходит в минус; без
#      картинок аудио играет ВЕСЬ отрезок (ASPG всё равно вычитал 7 секунд);
#   • dub/rebroadcast фильтруются по булевым полям (AnisongDB сменил формат);
#   • «дубли аниме» проверяются по списку аниме, а не по списку франшиз;
#   • «Похожие» (аниме есть у N пользователей) и «Подсказка типа песни»
#      реально работают — в ASPG обе настройки собирались, но не применялись.
from __future__ import annotations
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


import bisect
import io
import json
import math
import os
import random
import threading
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterator, Optional

from animepack_api import (AMQ_CDN, ANISONG_BATCH, LIST_STATUSES, LIST_TARGETS,
                           MANGA_KINDS, SHIKIMORI_BATCH, TARGET_LABELS,
                           AmqApi, AnimePackApiError, AniListApi, AnimeThemesApi,
                           AnisongApi, AniZipApi,
                           FandomApi, JimakuApi, KitsuApi, MalApi, MangaDexApi,
                           MangaPageSources,
                           SakugaApi,
                           SubdlApi, SubdlQuotaError,
                           fandom_page_link, mangadex_chapter_link,
                           sakuga_post_link, jimaku_clean_source_url,
                           ShikimoriApi, TmdbApi, make_session)
# Общая с «Апгрейдом аниме-пака» кладовая обложек: скачанный постер лежит на
# диске и второй раз не качается ни здесь, ни там.
import poster_cache
# Вторая половина общего 10-гигабайтного бюджета: исходники песен/кадров и
# детерминированно сжатые картинки, которые действительно используются снова.
import media_cache
# Эффект «проявление из пикселей» — общий с вкладкой «Монтаж» (кнопка
# «Пикселизация»): и размеры блоков, и цепочка фильтров считаются там.
from pixelize import pixelize_filter
# Вопросы по сюжету: пересказ с фэндом-вики → вопрос руками Gemini.
from animepack_plot import (PLOT_MODES, PLOT_MODE_LABELS, episode_number,
                            make_question, make_question_with_explanation,
                            pick_plot,
                            season_title)
from si_hyx_parts.animepack.dialogue_questions import (
    dialogue_text, parse_subtitles)
from avif_fit import fit_to_limit, start_cq_guess
from filenames import safe_filename, unique_path
from pixiv_art_api import MIN_BOOKMARKS as PIXIV_MIN_BOOKMARKS
# «Индекс популярности» считается ровно той же формулой, что и сортировка во
# вкладке ShikimoriHYX (одна реализация на оба места — в shikimori_api).
from shikimori_api import (franchise_parts_index, index_base_from_statuses_stats,
                           index_favorites_factor, popularity_index)

try:
    from config import FFMPEG, FFPROBE, CREATE_NO_WINDOW, CONFIG_DIR
except Exception:  # pragma: no cover — модуль должен жить и без приложения
    FFMPEG, FFPROBE, CREATE_NO_WINDOW = "ffmpeg", "ffprobe", 0
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".unified_media_tool")

SIQ_NS = "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"

# Реестр родов вопросов целиком вынесен в отдельный модуль: имена, подписи и
# семьи (картинка / ролик / текст) нужны и генератору, и вкладке, и тестам, а
# менять их удобнее там, где они лежат все вместе.
from si_hyx_parts.animepack.question_kinds import (
    AI_ART_KIND, ANAGRAM_KIND, ANIME_KINDS, CATEGORY_LABELS, CHAR_KIND,
    CHAR_ROLE_LABELS, CHAR_ROLES, CHAR_TASK_TEXT, CLIP_KINDS, FRAME_KIND,
    DESCRIPTION_AUDIO_KIND, DIALOGUE_KIND, FRAME_KINDS, GEMINI_TITLE_KINDS,
    HINT_LABELS, IMAGE_KINDS, KIND_LABELS,
    KIND_TITLES, MANGA_KIND, MANGA_LANG_LABELS, MANGA_LANGS,
    PIXEL_KIND, PIXIV_ART_KIND,
    PLOT_KIND, SAKUGA_KIND, EPISODE_KIND, SILENT_KINDS,
    SONG_CATEGORIES, SONG_KIND_LABELS, SONG_KINDS, STUDIO_FRAMES,
    STUDIO_FRAME_SECONDS, STUDIO_KIND, STUDIO_SECONDS_MAX,
    STUDIO_TASK_TEXT, TEXT_KINDS, TITLE_KINDS, TITLE_LABELS, VIDEO_KIND)

# Разрешение коллажа — как в ASPG. Постер больше не ужимается заранее: его
# размер добирает AVIF-кодер под лимит (см. IMAGE_LIMIT_KB).
COLLAGE_SIZE = (800, 600)
COLLAGE_CELL = (400, 300)
# Сколько скриншотов идёт в коллаж 2×2.
COLLAGE_IMAGES = 4

# ── Кодирование медиа (та же логика, что во вкладке «Обработка») ─────────────
# Применяется, только когда включены галочки «Сжимать аудио»/«Сжимать картинки».
# Выключены — медиа кладётся в пак как пришло с сервера (см. download_audio /
# _save_image): без единого перекодирования, в исходном качестве.
# Звук: opus 192 кбит + нормализация громкости и затухание в конце отрезка —
# фильтры собираются ровно как в ProcessWorker._build_audio_filters.
AUDIO_BITRATE = "192k"
AUDIO_LOUDNORM_I = -20.0
AUDIO_LOUDNORM_LRA = 11.0
AUDIO_LOUDNORM_TP = -1.5
AUDIO_FADE_OUT = 1.0
# libopus отвергает «боковые»/нестандартные раскладки каналов — тот же фикс,
# что в workers.OPUS_LAYOUT_FIX (на stereo/mono это no-op).
OPUS_LAYOUT_FIX = ("aformat=channel_layouts=mono|stereo|3.0|4.0|quad|5.0|5.1"
                   "|6.1|7.1")
# Картинки: AVIF (libaom, tune=iq) с подбором CQ под лимит — см. avif_fit.
# Значения по умолчанию для настроек пака; сами кодирования идут с низким
# приоритетом процесса (avif_fit._LOW_PRIORITY), чтобы не мешать работе за ПК.
IMAGE_LIMIT_KB = 150
IMAGE_SPEED = 8          # -cpu-used: 0 — медленно и лучше, 8 — быстро и хуже
# Пяти проходов хватает и сложной ч/б странице манги. На четырёх подбор иногда
# успевал найти лишь пробу на 14 КБ при разрешённом лимите 150 КБ: исходник с
# MangaDex был качественным, но в пакет попадал именно этот черновой AVIF.
IMAGE_FIT_PASSES = 5
# Больше этой стороны картинке в паке взяться неоткуда: SIGame показывает её на
# экране 1080p, а лишние пиксели — это только время кодирования. Постеры
# Shikimori приезжают в 1200×1700 и ужимались до лимита всё равно.
IMAGE_MAX_SIDE = 1280
# Дольше стольких секунд постер в ответе не висит (просьба пользователя): всё
# нужное с него считывается за пару секунд, а игра тем временем стоит. Ноль —
# особый случай, «без ограничения».
ANSWER_IMAGE_MAX = 5
# Планка «лайков» (закладок Pixiv) у арта по умолчанию. Отбор живёт в
# pixiv_art_api, откуда число сюда и берётся: значение по умолчанию должно
# быть ровно одно на всё приложение.
PIXIV_MIN_LIKES = PIXIV_MIN_BOOKMARKS

# ── Потолок веса пака ────────────────────────────────────────────────────────
# Готовый .siq не должен весить больше этого: столько принимают площадки, куда
# паки заливают. Ничего под потолок не подгоняется — генератор просто следит за
# набранным весом и, как только становится ясно, что пак вылезет за лимит,
# останавливается на том, что уже есть, и говорит об этом.
MAX_PACK_MB = 150
# Запас под content.xml и заголовки zip: медиа кладётся без сжатия (ZIP_STORED),
# так что на каждый файл уходит ещё сотня-другая байт служебных данных.
PACK_OVERHEAD = 0.97
# Сколько вопросов должно набраться, прежде чем средний вес считается годным для
# прогноза: на первых двух-трёх разброс слишком велик.
BUDGET_WARMUP = 5

# ── Видео-вопросы (AnimeThemes) ──────────────────────────────────────────────
# Ролик опенинга/эндинга вместо отрезка звука. Кодирование — тот же libsvtav1,
# что во вкладке «Обработка» (ProcessWorker._svt_args): crf и пресет вынесены в
# настройки, остальное берётся оттуда же.
VIDEO_CUT = 15           # секунд в ролике
VIDEO_HEIGHT = 720
VIDEO_CRF = 45
VIDEO_PRESET = 13        # 13 — самый быстрый пресет libsvtav1
VIDEO_TUNE = 0           # 0 = tune=vq, как «тёмный» пресет «Обработки»
# CDN AnimeThemes не терпит параллельных чтений: два одновременных ffmpeg
# получают 503 Service Temporarily Unavailable, вход обрывается, а ffmpeg при
# этом ВОЗВРАЩАЕТ НОЛЬ и оставляет mp4 из одних заголовков (262 байта).
# Поэтому ролики качаются по одному и результат проверяется по размеру.
VIDEO_RETRIES = 2
VIDEO_RETRY_PAUSE = 2.0
MIN_VIDEO_BYTES = 64 * 1024
# Начало ролика опенинга — заставка студии и первые титры: отрезок берём не с
# самого начала, а с этой секунды и дальше.
VIDEO_LEAD_IN = 5

# ── Вопрос-пиксели (кадр, который проявляется) ───────────────────────────────
# Ровно тот же эффект, что у кнопки «Пикселизация» во вкладке «Монтаж»: кадр
# зацикливается на PIXEL_SECONDS секунд, и по нему идёт цепочка pixelize с
# уменьшающимся блоком (pixelize.pixelize_filter). Кодирование — тот же
# libsvtav1 и те же crf/пресет, что у вопроса-ролика.
PIXEL_STEPS = 6          # шагов проявления
PIXEL_BLOCK = 64         # стартовый размер блока, px
PIXEL_SECONDS = 12       # шесть ступеней по две секунды, последняя — чистый кадр
PIXEL_FPS = 10           # кадров в секунду: картинка статична, больше незачем
# Выше этой строны кадр не поднимаем: ролик и так смотрят на экране SIGame, а
# лишние пиксели — только вес пака и время кодирования.
PIXEL_HEIGHT = 720

# ── Вопрос-сакуга (Sakugabooru) ──────────────────────────────────────────────
# Вырезки на Sakugabooru короткие — обычно от трёх до пятнадцати секунд, — и
# режется отрывок с самого начала: там ровно та сцена, ради которой вырезку и
# выложили. Звука у таких файлов, как правило, нет вовсе, и мы его не пишем в
# любом случае: голоса и музыка выдали бы тайтл мимо самой анимации.
SAKUGA_CUT = 8           # секунд в вопросе
# Дольше этого вырезка в вопрос не идёт (просьба пользователя): длинный отрывок
# перестаёт быть загадкой по рисовке и превращается в просмотр сцены.
SAKUGA_MAX_CUT = 20

# ── Вопрос-анаграмма ─────────────────────────────────────────────────────────
# На каком языке перемешивать название. Русское — с карточки Shikimori,
# английское — поле english, ромадзи — name (у Shikimori это латиница).
ANAGRAM_LANGS = ("russian", "english", "romaji")
ANAGRAM_LANG_LABELS = {"russian": "Русское название",
                       "english": "Английское название",
                       "romaji": "Ромадзи"}
# Подписи «Анаграмма — назвать аниме» перед перемешанными буквами больше нет:
# пользователь попросил убрать, вопросом остаётся один текст анаграммы.
# Короче этого анаграмма бессмысленна: из четырёх букв «Кадо» вариантов больше,
# чем игроков.
ANAGRAM_MIN_LETTERS = 6
# А длиннее этого — нерешаемая каша: у ранобэ названия бывают в целое
# предложение («Я переродился торговым автоматом и брожу по лабиринту»), и
# перемешанные буквы такой длины не разбирает никто. Потолок настраивается
# (просьба пользователя), 0 — снять его совсем. Считаются ВСЕ символы названия,
# вместе с пробелами и знаками: на экране игрок видит именно их.
ANAGRAM_MAX_CHARS = 40
# Сколько анаграмма висит на экране — символов в секунду (просьба
# пользователя). Ровно в этих единицах считает и сам SIGame: при пустом
# duration он делит длину текста на «скорость чтения» из настроек игры
# (GameController.GetReadingDurationForTextLength), а она по умолчанию вдвое
# быстрее и на разгадывание не рассчитана. Поэтому время пишем в пак сами, а не
# полагаемся на настройки чужого клиента. 0 — таймера нет вовсе: анаграмма
# висит, пока ведущий не откроет ответ.
ANAGRAM_CHARS_PER_SEC = 10.0
ANAGRAM_CPS_MAX = 60.0
# Пол времени показа: короткая анаграмма из двенадцати символов иначе мелькнула
# бы за секунду, и прочитать её не успел бы никто.
ANAGRAM_MIN_SECONDS = 3

from si_hyx_parts.animepack.anagram_seconds import anagram_seconds


# ── Вопрос по сюжету (Fandom + Gemini) ───────────────────────────────────────
# Задание, которое висит на экране вместе с пересказом: без него вопрос
# выглядит как обычный текст, и непонятно, что именно называть.
PLOT_TASK_TEXT = "Назвать аниме по сюжету"

# Сколько раз повторяем скачивание одного файла, прежде чем считать его упавшим.
_DOWNLOAD_RETRIES = 2
_MIN_AUDIO_BYTES = 4096

# ── Память о показанных кадрах ───────────────────────────────────────────────
# Чтобы вопрос-кадр не повторился в следующем паке, ссылки на уже
# использованные скриншоты складываются в отдельный файл рядом с настройками
# (см. галочку «Не повторять кадры из прошлых паков»). Хранится только список
# ссылок; при переполнении выбрасываются самые старые.
FRAMES_HISTORY_FILE = os.path.join(CONFIG_DIR, "animepack_frames_used.json")
FRAME_HISTORY_LIMIT = 20_000

# ── Кэш каталога Shikimori ───────────────────────────────────────────────────
# Случайная выборка каталога (order: random) — это десятки запросов и добрая
# минута ожидания на КАЖДУЮ генерацию, а сам каталог меняется раз в сезон.
# Поэтому набранные карточки (вместе с их статистикой, из которой считается
# индекс популярности) складываются в файл рядом с настройками и живут там,
# пока не нажата кнопка «Обновить базу» — срока годности у кэша нет нарочно
# (просьба пользователя: «один раз сделал — и в кэше пусть хранится»).
SHIKI_CACHE_FILE = os.path.join(CONFIG_DIR, "animepack_shikimori_db.json")
# Сколько наборов фильтров держим одновременно: у каждого свой мешок карточек,
# и без предела файл рос бы с каждым сдвигом года или галочкой типа.
SHIKI_CACHE_BUCKETS = 4
# Ссылки на кадры/темы и состав персонажей меняются редко, но в отличие от
# карточек каталога всё же обновляются. Месяц убирает повторные API-запросы и
# не превращает старую ссылку в вечную.
ENRICHMENT_CACHE_TTL = 30 * 24 * 60 * 60

from si_hyx_parts.animepack.anime_pack_error import AnimePackError


# ── Кэш списков пользователей ────────────────────────────────────────────────
# Список с MAL/Shikimori/AniList — это десятки запросов и добрая минута
# ожидания, а от пака к паку он не меняется. Пока программа не перезапущена,
# один и тот же ник со теми же статусами спрашивается ровно один раз (просьба
# пользователя: так следующий пак собирается заметно быстрее). На диск ничего
# не пишется нарочно — перезапуск и есть способ обновить список.
_LISTS_CACHE: dict[tuple, list[int]] = {}
_LISTS_LOCK = threading.Lock()

from si_hyx_parts.animepack.user_list_cache_key import (
    user_list_cache_key,
    cached_user_list,
    remember_user_list,
    clear_user_list_cache,
    ShikimoriDbCache,
    shiki_cache_signature,
    UserList,
    _current_year,
)

from si_hyx_parts.animepack.pack_settings import PackSettings

from si_hyx_parts.animepack.song_candidate import SongCandidate

from si_hyx_parts.animepack.pack_result import PackResult


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные чистые функции (их и проверяют тесты)
# ─────────────────────────────────────────────────────────────────────────────
# Лесенка цен по сложности. Разрыв между самым лёгким и самым трудным вопросом
# нарочно неполный: по просьбе пользователя шаг ужат с 2 до 1,5 очка, так что
# крайние цены расходятся втрое (6 → 20), а не в десять раз (2 → 20), как было.
_PRICE_RANGES = ((90, 6), (80, 8), (70, 9), (60, 11), (50, 12),
                 (40, 14), (30, 15), (20, 17), (10, 18), (0, 20))
_PRICE_MIN = _PRICE_RANGES[0][1]

# Надбавка к цене за тип песни (просьба пользователя): опенинг — ничего,
# эндинг — ровно +2, OST — ровно +4. Это фиксированные числа, а не лесенка «по
# единице»: эндинг узнают хуже опенинга, а вставку — хуже всех.
_KIND_PRICE_STEP = {"opening": 0, "ending": 2, "insert": 4}
# Старые публичные константы оставлены для совместимости, но в цене и уровне
# больше не участвуют.
_CHAR_PRICE_MULT = {True: 1.5, False: 1.8}
# Фиксированная надбавка к цене тайтла: главный / второстепенный герой.
_CHAR_PRICE_STEP = {True: 4, False: 6}
CHAR_TITLE_PRICE_STEP = 1

from si_hyx_parts.animepack.char_price_mult import char_price_mult


# ── «В избранном» у персонажа ────────────────────────────────────────────────
# Лесенка узнаваемости персонажа по числу добавивших его в избранное на
# Shikimori: 1 — знают все (у «Лелуша» 10 740), 15 — не знает никто (единицы).
# Пороги подобраны по живым данным: главные герои хитов набирают тысячи,
# заметный второстепенный — сотню, проходной — единицы.
CHAR_FAV_LEVELS = (5000, 3000, 2000, 1300, 900, 600, 400, 260, 180, 120,
                   80, 30, 12, 4)
CHAR_MAX_LEVEL = len(CHAR_FAV_LEVELS) + 1

from si_hyx_parts.animepack.char_fav_level import char_fav_level, char_question_level


from si_hyx_parts.animepack.char_fav_price_shift import char_fav_price_shift
# Надбавка за сложность самой песни (просьба пользователя). Цена песенного
# вопроса складывается из двух частей: база — узнаваемость ТАЙТЛА, ровно та же,
# что у вопроса-кадра, а сверху — надбавка за сложность угадывания в AMQ.
# Считается линейно от ста: сложность 80 (песня известная) даёт +2, 50 — +5,
# ноль (её не угадывает почти никто) — все десять.
SONG_DIFF_BONUS_MAX = 10
# Надбавка к цене за род вопроса БЕЗ песни. Арт с Pixiv стоит на два очка
# дороже кадра того же тайтла (просьба пользователя): фанатский рисунок
# узнать труднее, чем кадр из самого аниме. Манга с аниме-адаптацией — тоже
# +2 к цене «кадра этого же аниме» (её индекс берётся от экранизации, см.
# SongCandidate.adapted_from).
_SILENT_PRICE_STEP = {PIXIV_ART_KIND: 2, MANGA_KIND: 2}
# Во сколько раз вопрос ПО СЮЖЕТУ дороже вопроса-кадра по тому же тайтлу
# (просьба пользователя): узнать кадр может и тот, кто видел одну серию, а
# помнить события — только тот, кто смотрел.
PLOT_PRICE_MULT = 1.5
# Вопрос-студия стоит в полтора раза дороже СРЕДНЕЙ цены трёх показанных
# тайтлов (просьба пользователя): узнать студию по кадрам труднее, чем
# назвать любой из них.
STUDIO_PRICE_MULT = 1.5

from si_hyx_parts.animepack.song_difficulty_bonus import song_difficulty_bonus
# Сложность кавера складывается со сложностью песни, а не удваивает её.
from si_hyx_parts.animepack.cover_difficulty import (
    song_hardness, cover_hardness, music_difficulty_bonus)
# Как кавер подписан в самом вопросе: «Опенинг (кавер на английском)».
from si_hyx_parts.animepack.cover_labels import (
    cover_phrase, cover_hint, cover_credit)


# Что в названии считается буквой: перемешиваем только их, а пробелы, дефисы и
# знаки остаются на своих местах — иначе по одной длинной каше не видно даже,
# из скольких слов состоит ответ.
_ANAGRAM_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)

from si_hyx_parts.animepack.anagram_source import anagram_source


# Письменность названия. Кириллица и латиница (вместе с диакритикой европейских
# языков — «Gintama°», «Fate/stay night»), чтобы отличить настоящее русское
# название от латинского огрызка в том же поле карточки.
_RE_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_RE_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")

from si_hyx_parts.animepack.is_lang_script import (
    _is_lang_script,
    _letters_count,
    _letter_runs,
    make_anagram,
    _dedup_answers,
    _split_total,
    _scale_quotas,
    price_for_difficulty,
    price_for_level,
    assign_prices,
    arrange_questions,
    fmt_duration,
    fmt_elapsed,
)


# Иероглифика (кана, кандзи, хангыль, «широкие» знаки препинания). Строка с
# любым таким символом в ответ не идёт.
_RE_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯"
                     r"豈-﫿＀-￯]")

from si_hyx_parts.animepack.has_cjk import has_cjk


# «Сложность пака» 1…15 по индексу популярности: 1 — то, что смотрели все,
# 15 — почти никто. Узкая прежняя лесенка заканчивалась на 6 000, поэтому в
# последний уровень сваливались две трети живого каталога — и «Слёзы Тиары» с
# индексом около 5 800, и безвестные короткометражки с индексом меньше десяти.
# Широкая логарифмическая шкала покрывает весь хвост, не раздувая интерфейс до
# трёх десятков уровней. Пороги фиксированные: обновление базы не меняет смысл
# уже сохранённых настроек сложности.
INDEX_LEVELS = (700_000, 300_000, 150_000, 70_000, 30_000, 15_000, 7_000,
                3_000, 1_500, 700, 300, 150, 70, 30)
MAX_LEVEL = len(INDEX_LEVELS) + 1

# Книжная шкала: перевод книжного индекса на общую лесенку, её потолок и
# пороги в книжных единицах (почему именно так — см. сам модуль).
from si_hyx_parts.animepack.manga_scale import (
    manga_reach,
    MANGA_MIN_LEVEL,
    MANGA_TOP_INDEX,
    MANGA_INDEX_LEVELS,
)

from si_hyx_parts.animepack.index_level import index_level


# Хвосты названий, по которым отличаются части одной серии. Нужны, чтобы
# «Доктор Стоун: Научное будущее. Часть 3» схлопнулось с «Доктор Стоун», даже
# когда Shikimori не проставил тайтлу поле franchise (у свежих тайтлов бывает).
_RE_TITLE_TAIL = re.compile(
    r"(\s*[:—–-]\s.*$)"                                  # всё после двоеточия/тире
    r"|(\s*\(\s*\d{4}\s*\)\s*$)"                         # «(2019)»
    r"|(\s*(сезон|season|часть|part|фильм|movie|ova|ona|"
    r"спешл|special|tv)\b.*$)",
    re.IGNORECASE)
_RE_TITLE_TRAIL_NUM = re.compile(r"[\s.,!?:;\-–—]*\b([IVX]+|\d+)\s*$",
                                 re.IGNORECASE)
# Буквенная приписка части серии: «Покемон XY», «Dragon Ball GT», «Sailor Moon
# R». Это тоже части одной франшизы, а не отдельные тайтлы: без такой обрезки
# «Покемон XY: Хупа и столкновение веков» и «Покемон: Хроники приключений»
# спокойно попадали в один пак (просьба пользователя). Берём только ЗАГЛАВНЫЕ
# латинские буквы (одну-три) через разделитель — обычное последнее слово
# названия так не выглядит.
_RE_TITLE_TRAIL_ABBR = re.compile(r"[\s.,!?:;\-–—]+[A-Z]{1,3}\s*$")
_RE_TRAIL_PUNCT = re.compile(r"[\s.,!?:;]+$")

from si_hyx_parts.animepack.title_root import title_root, is_plain_title, song_kind
from si_hyx_parts.animepack.franchise_branch import (
    branch_franchise_index,
    franchise_branch_key,
    franchise_branch_parts,
)


# Как тип песни выглядит в правильном ответе: «Название OP1 (2010)».
_TAG_BY_KIND = {"opening": "OP", "ending": "ED", "insert": "OST"}
_RE_TAG_NUM = re.compile(r"(\d+)\s*$")

from si_hyx_parts.animepack.announced import is_announced
from si_hyx_parts.animepack.song_tag import (
    song_tag,
    _truthy,
    _chunks,
    _genre_ids,
    filter_song,
    filter_anime,
    frame_url_key,
    load_frame_history,
    save_frame_history,
)


# ── Что уже спрашивали в других паках ────────────────────────────────────────
# Правильный ответ сгенерированного пака выглядит как «Наруто OP1 (2002) —
# 『Song』»; чтобы понять, о какой франшизе речь, из него надо отрезать песню,
# год и тег типа песни, а остаток прогнать через title_root().
_RE_ANSWER_SONG = re.compile(r"\s*[—–-]\s*『.*$")
_RE_ANSWER_YEAR = re.compile(r"\s*\(\s*\d{4}\s*\)\s*$")
_RE_ANSWER_TAG = re.compile(r"\s+(OP|ED|OST)\s*\d*\s*$", re.IGNORECASE)

from si_hyx_parts.animepack.answer_title import answer_title, siq_answer_roots, franchise_key


# ─────────────────────────────────────────────────────────────────────────────
# Сборка content.xml
# ─────────────────────────────────────────────────────────────────────────────
PACK_AUTHOR = "Сгенерировано в программе SI-HYX"
# Как называются медиафайлы ВНУТРИ пака: «Сгенерировано в SI-HYX(Название
# тайтла).opus/.avif». Раньше это были номера песен из AnisongDB, и открывать
# такой архив вручную было невозможно.
MEDIA_NAME_PREFIX = "Сгенерировано в SI-HYX"

from si_hyx_parts.animepack.build_content_xml import (
    build_content_xml,
    _append_question,
    _append_answer,
)

# Книжная часть пака: экранизация тайтла и доли внутри неё.
from si_hyx_parts.animepack.manga_adaptation import (
    adaptation_ids,
    load_adaptations,
    apply_adaptation,
)
from si_hyx_parts.animepack.manga_mix import MangaMix
# Каталог аниме разбирается один раз на оба потока кандидатов: песенным
# вопросам нужна песня из AnisongDB, остальным — только карточка Shikimori.
from si_hyx_parts.animepack.anime_card_feed import AnimeCardFeed
# Кого имеет смысл спрашивать про «в избранном» при обновлении базы.
from si_hyx_parts.animepack.favorites_sweep import (favorites_worth_asking,
                                                    favorites_targets)
# Размер выборки каталога аниме — по родам вопросов, а не одним множителем.
from si_hyx_parts.animepack.catalog_want import (CHEAP_COST, SONG_COST,
                                                 TITLE_COST, kind_cost,
                                                 anime_catalog_want)
# Длинная лента вебтуна режется до книжных пропорций.
from si_hyx_parts.animepack.manga_crop import fit_page as fit_manga_page

# Средняя сложность по родам вопросов: у артов и книг она своя.
from si_hyx_parts.animepack.level_avg import (
    ART_BUCKET,
    MANGA_BUCKET,
    PLOT_BUCKET,
    STUDIO_BUCKET,
    BUCKET_TITLES,
    LEVEL_BUCKETS,
    level_bucket,
    level_avg_target,
    own_bucket,
)

# «В избранном» по соседям по индексу; модуль публикует и install/clear.
from si_hyx_parts.animepack.favorites_norm import title_favorites_factor

from si_hyx_parts.animepack.anime_pack_generator import AnimePackGenerator
