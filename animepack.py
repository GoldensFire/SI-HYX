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

import bisect
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
                           AnisongApi, FandomApi, KitsuApi, MalApi, ShikimoriApi,
                           TmdbApi, make_session)
# Общая с «Апгрейдом аниме-пака» кладовая обложек: скачанный постер лежит на
# диске и второй раз не качается ни здесь, ни там.
import poster_cache
# Эффект «проявление из пикселей» — общий с вкладкой «Монтаж» (кнопка
# «Пикселизация»): и размеры блоков, и цепочка фильтров считаются там.
from pixelize import pixelize_filter
# Вопросы по сюжету: пересказ с фэндом-вики → вопрос руками Gemini.
from animepack_plot import (PLOT_MODES, PLOT_MODE_LABELS, make_question,
                            pick_plot)
from avif_fit import fit_to_limit, start_cq_guess
from filenames import safe_filename, unique_path
# «Индекс популярности» считается ровно той же формулой, что и сортировка во
# вкладке ShikimoriHYX (одна реализация на оба места — в shikimori_api).
from shikimori_api import (franchise_parts_index, index_base_from_statuses_stats,
                           popularity_index)

try:
    from config import FFMPEG, FFPROBE, CREATE_NO_WINDOW, CONFIG_DIR
except Exception:  # pragma: no cover — модуль должен жить и без приложения
    FFMPEG, FFPROBE, CREATE_NO_WINDOW = "ffmpeg", "ffprobe", 0
    CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".unified_media_tool")

SIQ_NS = "https://github.com/VladimirKhil/SI/blob/master/assets/siq_5.xsd"

SONG_KINDS = ("opening", "ending", "insert")
# Вставку (Insert Song) везде — и в настройках, и в подсказке, и в ответе —
# зовём OST: так её называют игроки (просьба пользователя).
SONG_KIND_LABELS = {"opening": "Опенинг", "ending": "Эндинг", "insert": "OST"}
# Подпись, которая ВИСИТ НА ЭКРАНЕ, пока играет песня (галочка «Подсказка: тип
# песни»). У вопроса-ролика та же подпись уходит ведущему в реплику: поверх
# видео надпись загораживала бы картинку, а произнести её вслух — в самый раз
# (просьба пользователя).
HINT_LABELS = {"opening": "Опенинг", "ending": "Эндинг", "insert": "OST"}
# Задание вопроса-персонажа. Без него портрет неотличим от обычного кадра, и
# игроки называют аниме вместо героя (просьба пользователя).
CHAR_TASK_TEXT = "Назвать персонажа"
# Вопрос-кадр: в режиме «только кадры» такой весь пак, в смешанном режиме они
# идут вперемешку с песнями. Для квот это такой же «тип вопроса», как опенинг.
FRAME_KIND = "frame"
# Вопрос-персонаж: показывается портрет персонажа с Shikimori, ответ —
# «Название аниме (год) — 『Имя персонажа』». Стоит дороже кадра того же тайтла
# (см. _KIND_PRICE_MULT): узнать персонажа сложнее, чем сам тайтл.
CHAR_KIND = "character"
# Вопрос-ролик: вместо отрезка звука играет видео опенинга/эндинга с
# AnimeThemes. Для квот это такой же «тип вопроса», как кадр или персонаж, — его
# долю задаёт тот же ползунок состава. Внутри это всё та же песня: и ответ, и
# подсказка, и надбавка к цене берутся от неё (см. SongCandidate.base_kind).
VIDEO_KIND = "video"
# Вопрос по манге/манхве/манхуа/ранобэ. Кадров у книги нет, поэтому вопросом
# служит либо портрет персонажа (по умолчанию), либо обложка — что именно,
# решает настройка manga_question. Ответ и цена считаются точно так же, как у
# аниме: карточка Shikimori у манги устроена один в один (см. MANGA_FIELDS).
MANGA_KIND = "manga"
# Вопрос-ПИКСЕЛИ: тот же кадр из аниме, но не картинкой, а роликом — кадр
# начинается крупными блоками и за несколько шагов проясняется. Эффект тот же
# самый, что у кнопки «Пикселизация» во вкладке «Монтаж»: и размеры блоков, и
# цепочка фильтров считаются общим модулем pixelize.py.
PIXEL_KIND = "pixel"
# Вопрос-АНАГРАММА: буквы названия тайтла перемешаны, ответ — сам тайтл.
# Медиа не нужно вовсе, сеть — тоже: анаграмма считается из названия, которое
# уже есть в карточке Shikimori (см. make_anagram).
ANAGRAM_KIND = "anagram"
# Вопрос ПО СЮЖЕТУ: пересказ серии с фэндом-вики, из которого Gemini делает
# вопрос (см. animepack_plot.py). Ответом служит либо сам тайтл, либо деталь
# сюжета — решает настройка plot_mode.
PLOT_KIND = "plot"
KIND_TITLES = dict(SONG_KIND_LABELS,
                   **{FRAME_KIND: "Кадр", CHAR_KIND: "Персонаж",
                      VIDEO_KIND: "Ролик", MANGA_KIND: "Манга",
                      PIXEL_KIND: "Пиксели", ANAGRAM_KIND: "Анаграмма",
                      PLOT_KIND: "Сюжет"})
# Кого из персонажей брать: главных, второстепенных или всех подряд.
CHAR_ROLES = ("main", "supporting", "both")
CHAR_ROLE_LABELS = {"main": "Главные герои", "supporting": "Второстепенные",
                    "both": "И те, и другие"}
# Чем спрашивать мангу: портретом персонажа или обложкой тома.
MANGA_QUESTIONS = ("character", "cover")
MANGA_QUESTION_LABELS = {"character": "Портрет персонажа",
                         "cover": "Обложка"}
# Типы вопросов, у которых нет песни: вопрос — картинка (или собранный из неё
# ролик-проявление). Кадр и пиксели устроены одинаково: та же случайная
# картинка тайтла, та же память «не повторять», разная только подача.
FRAME_KINDS = (FRAME_KIND, PIXEL_KIND)
IMAGE_KINDS = (FRAME_KIND, PIXEL_KIND, CHAR_KIND, MANGA_KIND)
# Вопросы, состоящие из одного текста: ни картинки, ни звука в них нет.
TEXT_KINDS = (ANAGRAM_KIND, PLOT_KIND)
# Всё, чему не нужна песня. Для квот и ползунка состава это такие же «роды
# вопросов», как опенинг или ролик.
SILENT_KINDS = IMAGE_KINDS + TEXT_KINDS
SONG_CATEGORIES = ("standard", "instrumental", "chanting", "character")
CATEGORY_LABELS = {"standard": "Обычные", "instrumental": "Инструментал",
                   "chanting": "Речитатив", "character": "От персонажа"}
ANIME_KINDS = ("tv", "movie", "ova", "ona", "special")
KIND_LABELS = {"tv": "ТВ", "movie": "Фильм", "ova": "OVA", "ona": "ONA",
               "special": "Спешл"}

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
IMAGE_FIT_PASSES = 4     # столько кодирований на картинку, как дефолт «Обработки»
# Больше этой стороны картинке в паке взяться неоткуда: SIGame показывает её на
# экране 1080p, а лишние пиксели — это только время кодирования. Постеры
# Shikimori приезжают в 1200×1700 и ужимались до лимита всё равно.
IMAGE_MAX_SIDE = 1280
# Дольше стольких секунд постер в ответе не висит (просьба пользователя): всё
# нужное с него считывается за пару секунд, а игра тем временем стоит. Ноль —
# особый случай, «без ограничения».
ANSWER_IMAGE_MAX = 5

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
PIXEL_SECONDS = 10       # длительность ролика
PIXEL_FPS = 10           # кадров в секунду: картинка статична, больше незачем
# Выше этой строны кадр не поднимаем: ролик и так смотрят на экране SIGame, а
# лишние пиксели — только вес пака и время кодирования.
PIXEL_HEIGHT = 720

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


def anagram_seconds(text: str, chars_per_sec: float = ANAGRAM_CHARS_PER_SEC) -> int:
    """Сколько секунд держать анаграмму на экране (0 — без таймера).

    Считаются ВСЕ символы вопроса, вместе с пробелами и знаками: игрок видит
    именно их. Дробь округляется ВВЕРХ — обрывать показ на середине секунды
    незачем, — а совсем короткому тексту достаётся ANAGRAM_MIN_SECONDS."""
    cps = max(0.0, float(chars_per_sec or 0.0))
    length = len(str(text or ""))
    if cps <= 0 or not length:
        return 0
    return max(ANAGRAM_MIN_SECONDS, math.ceil(length / cps))


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


class AnimePackError(Exception):
    """Ошибка генерации, которую не стыдно показать пользователю."""


# ── Кэш списков пользователей ────────────────────────────────────────────────
# Список с MAL/Shikimori/AniList — это десятки запросов и добрая минута
# ожидания, а от пака к паку он не меняется. Пока программа не перезапущена,
# один и тот же ник со теми же статусами спрашивается ровно один раз (просьба
# пользователя: так следующий пак собирается заметно быстрее). На диск ничего
# не пишется нарочно — перезапуск и есть способ обновить список.
_LISTS_CACHE: dict[tuple, list[int]] = {}
_LISTS_LOCK = threading.Lock()


def user_list_cache_key(source: str, username: str, statuses) -> tuple:
    """Ключ кэша: источник + ник без учёта регистра + набор статусов."""
    return (str(source or "").strip().lower(),
            str(username or "").strip().casefold(),
            tuple(sorted(str(s) for s in (statuses or []))))


def cached_user_list(key: tuple) -> Optional[list[int]]:
    with _LISTS_LOCK:
        ids = _LISTS_CACHE.get(key)
    return list(ids) if ids is not None else None


def remember_user_list(key: tuple, ids) -> None:
    with _LISTS_LOCK:
        _LISTS_CACHE[key] = [int(i) for i in ids]


def clear_user_list_cache() -> None:
    """Забыть все запомненные списки (нужно тестам и кнопке «обновить»)."""
    with _LISTS_LOCK:
        _LISTS_CACHE.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Кэш каталога Shikimori (карточки случайной выборки + части франшиз)
# ─────────────────────────────────────────────────────────────────────────────
class ShikimoriDbCache:
    """Карточки каталога Shikimori и части франшиз, сохранённые на диск.

    Зачем: раньше каждая генерация «случайных из базы Shikimori» заново
    вычерпывала каталог постранично (order: random) и заново спрашивала
    узнаваемость франшиз — это и была та самая минута «поиска кандидатов».
    Теперь набранное лежит в файле и переживает перезапуск программы; обновляет
    его только кнопка «Обновить базу» (см. refresh_shikimori_db).

    Карточки хранятся МЕШКАМИ по набору фильтров, с которым их спрашивали
    (`signature`): выборка «ТВ, 2000–2010, оценка от 7» — совсем не то же самое,
    что «всё подряд», и подменять одну другой нельзя. Части франшиз общие: они
    от фильтров не зависят.
    """

    def __init__(self, path: Optional[str] = None):
        # Путь берём в момент создания, а не значением по умолчанию: значения
        # аргументов вычисляются один раз при импорте, и тесты не смогли бы
        # увести кэш из настоящего %APPDATA% пользователя.
        self.path = path or SHIKI_CACHE_FILE
        self._lock = threading.Lock()
        self._data: Optional[dict] = None
        self._dirty = False

    # ── чтение/запись ─────────────────────────────────────────────────────
    def _read(self) -> dict:
        """Содержимое кэша (зовётся уже под замком)."""
        if self._data is None:
            try:
                with open(self.path, encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:  # noqa: BLE001 — кэша может не быть вовсе
                raw = {}
            if not isinstance(raw, dict):
                raw = {}
            for key in ("anime", "manga", "franchises"):
                if not isinstance(raw.get(key), dict):
                    raw[key] = {}
            self._data = raw
        return self._data

    def save(self) -> bool:
        """Сбрасывает накопленное на диск (без изменений — ничего не делает)."""
        with self._lock:
            if not self._dirty or self._data is None:
                return False
            data = self._data
            self._dirty = False
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = f"{self.path}.tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            os.replace(tmp, self.path)
            return True
        except OSError:
            return False

    def clear(self) -> None:
        """Забыть всё: и карточки, и франшизы (кнопка «Обновить базу»)."""
        with self._lock:
            self._data = {"anime": {}, "manga": {}, "franchises": {}}
            self._dirty = False
        try:
            os.remove(self.path)
        except OSError:
            pass

    # ── карточки каталога ─────────────────────────────────────────────────
    def cards(self, target: str, signature: str) -> list[dict]:
        """Карточки, набранные с этим набором фильтров (пусто — не набирали)."""
        with self._lock:
            group = self._read().get(str(target)) or {}
            bucket = group.get(str(signature)) or {}
            stored = bucket.get("cards") if isinstance(bucket, dict) else None
            rows = list((stored or {}).values())
        return [c for c in rows if isinstance(c, dict)]

    def add_cards(self, target: str, signature: str, cards) -> int:
        """Кладёт карточки в мешок этого набора фильтров. Возвращает, сколько
        их стало всего."""
        with self._lock:
            group = self._read().setdefault(str(target), {})
            bucket = group.setdefault(str(signature), {})
            store = bucket.setdefault("cards", {})
            for card in cards:
                if not isinstance(card, dict):
                    continue
                try:
                    mal = int(card.get("malId") or card.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if mal:
                    store[str(mal)] = card
            bucket["fetched"] = time.time()
            # Самые старые наборы фильтров выбрасываем целиком.
            if len(group) > SHIKI_CACHE_BUCKETS:
                old = sorted(group,
                             key=lambda k: float((group.get(k) or {})
                                                 .get("fetched") or 0.0))
                for key in old[:len(group) - SHIKI_CACHE_BUCKETS]:
                    group.pop(key, None)
            self._dirty = True
            return len(store)

    # ── части франшиз ─────────────────────────────────────────────────────
    def franchise(self, key: str) -> Optional[list]:
        """Карточки частей франшизы (None — не спрашивали)."""
        with self._lock:
            rows = (self._read().get("franchises") or {}).get(str(key))
        return list(rows) if isinstance(rows, list) else None

    def add_franchises(self, parts: dict) -> None:
        """Запоминает части франшиз. Пустой список тоже запоминаем: «у этой
        франшизы частей не нашлось» — такой же ответ, и спрашивать его снова
        каждую генерацию незачем."""
        if not isinstance(parts, dict) or not parts:
            return
        with self._lock:
            store = self._read().setdefault("franchises", {})
            for key, rows in parts.items():
                store[str(key)] = [r for r in (rows or []) if isinstance(r, dict)]
            self._dirty = True


def shiki_cache_signature(s: "PackSettings", manga: bool = False) -> str:
    """Ключ мешка карточек: те же фильтры, что уходят в запрос к Shikimori.

    Ровно они и решают, какие карточки приедут (год, типы, оценка, исключённые
    жанры), поэтому мешок с одними фильтрами нельзя выдать за мешок с другими."""
    if manga:
        kinds = [k for k in MANGA_KINDS if s.manga_kinds.get(k)]
    else:
        kinds = [k for k in ANIME_KINDS if s.kinds.get(k)]
    excl = ",".join(str(int(g)) for g in sorted(s.genres_exclude or []))
    return (f"{int(s.year_from)}-{int(s.year_to)}|{','.join(kinds)}"
            f"|{int(s.score_from)}|{excl}")


# ─────────────────────────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class UserList:
    """Один пользователь и его списки (карточка «Add List» в ASPG)."""
    username: str = ""
    source: str = "shikimori"            # shikimori | myanimelist | anilist
    statuses: list[str] = field(
        default_factory=lambda: ["watching", "completed"])
    # Что берём из списка: аниме или мангу/ранобэ (у всех трёх сайтов это
    # отдельные разделы — см. LIST_TARGETS).
    target: str = "anime"
    # Доля вопросов пака, которую даёт ЭТОТ список, в процентах. 0 — «как
    # получится»: тогда порядок общий и большой список просто перевешивает
    # маленькие (у кого 1500 тайтлов, тот и заполнит пак). Ползунок на вкладке
    # раздаёт сотню между всеми списками.
    share: int = 0
    # «В основном музыка»: тайтлы из этого списка по возможности становятся
    # песенными вопросами, а не кадрами и персонажами. Нужно для списков, где
    # человек угадывает только музыку (просьба пользователя).
    prefer_music: bool = False

    def to_dict(self) -> dict:
        return {"username": self.username, "source": self.source,
                "statuses": list(self.statuses), "target": self.target,
                "share": int(self.share),
                "prefer_music": bool(self.prefer_music)}

    @classmethod
    def from_dict(cls, d: dict) -> "UserList":
        d = d or {}
        st = [s for s in (d.get("statuses") or []) if s in LIST_STATUSES]
        target = str(d.get("target") or "anime")
        try:
            share = max(0, min(100, int(d.get("share") or 0)))
        except (TypeError, ValueError):
            share = 0
        return cls(username=str(d.get("username") or "").strip(),
                   source=str(d.get("source") or "shikimori"),
                   statuses=st or ["watching", "completed"],
                   target=target if target in LIST_TARGETS else "anime",
                   share=share,
                   prefer_music=bool(d.get("prefer_music")))


def _current_year() -> int:
    return date.today().year


@dataclass
class PackSettings:
    """Полный набор настроек генерации (соответствует форме ASPG)."""
    # ── Пак ──────────────────────────────────────────────────────────────
    title: str = "Сгенерировано в SI-HYX"
    rounds: int = 3
    themes: int = 5
    questions: int = 6
    theme_title: str = "SI-HYX"
    # ── Списки ───────────────────────────────────────────────────────────
    random_mode: bool = True             # True — случайные аниме из общей базы
    # Откуда берутся случайные аниме: "shikimori" — каталог Shikimori запросом
    # order: random (фильтры уходят на сервер, поэтому мусора приезжает меньше),
    # "amq" — мастер-лист AnimeMusicQuiz. По умолчанию Shikimori: мастер-лист
    # AMQ знает только те тайтлы, у которых есть песни, поэтому годится он лишь
    # песенным пакам (см. has_songs и collect_anime_ids).
    random_source: str = "shikimori"
    users: list[UserList] = field(default_factory=list)
    # Запомненные ники: кнопка «Из сохранённых» показывает именно их. В отборе
    # НЕ участвуют — это просто адресная книга вкладки.
    saved_users: list[UserList] = field(default_factory=list)
    similar_count: int = 2               # у стольких человек должен быть тайтл
    # ── Состав пака ──────────────────────────────────────────────────────
    # Доли вопросов, в процентах: песни / ролики / кадры / персонажи. Ползунок
    # на вкладке двигает именно их, а прежние галочки «только кадры», «только
    # персонажи» и «ещё и кадры по N на песню» — это те же доли (100/0/0 и
    # т.п.), поэтому отдельных настроек больше нет (миграция старых — в
    # from_dict). Доля роликов участвует, только пока стоит галочка song_video
    # (см. percents).
    pct_songs: int = 100
    pct_videos: int = 0
    pct_frames: int = 0
    pct_chars: int = 0
    # Доля вопросов по манге/манхве/ранобэ. Своя часть ползунка: у книги нет ни
    # песен, ни кадров, поэтому подмешать её к аниме-вопросам иначе нельзя.
    # Участвует, только пока стоит галочка pack_manga — ровно как доля роликов
    # при song_video (просьба пользователя: без галочки манги на ползунке быть
    # не должно вовсе).
    pack_manga: bool = False
    pct_manga: int = 0
    # Доля вопросов-ПИКСЕЛЕЙ: тот же кадр, но роликом-проявлением (эффект
    # «Пикселизация» из вкладки «Монтаж»). Своя галочка, как у роликов и манги:
    # без неё части на ползунке нет вовсе.
    pack_pixel: bool = False
    pct_pixel: int = 0
    pixel_steps: int = PIXEL_STEPS
    pixel_block: int = PIXEL_BLOCK
    pixel_seconds: int = PIXEL_SECONDS
    pixel_fps: int = PIXEL_FPS
    # Доля вопросов-АНАГРАММ и язык названия, которое перемешивается.
    pack_anagram: bool = False
    pct_anagram: int = 0
    anagram_lang: str = "russian"        # russian | english | romaji
    # Потолок длины названия под анаграмму (0 — без потолка): слишком длинное
    # название перемешивается в нечитаемую кашу.
    anagram_max_chars: int = ANAGRAM_MAX_CHARS
    # Скорость показа анаграммы, символов в секунду (0 — без таймера вовсе):
    # из неё считается duration текста в паке, см. anagram_seconds.
    anagram_cps: float = ANAGRAM_CHARS_PER_SEC
    # Доля вопросов ПО СЮЖЕТУ (Fandom + Gemini) и что именно спрашивать.
    pack_plot: bool = False
    pct_plot: int = 0
    plot_mode: str = "title"             # title | detail
    # Ключ и модель Gemini — нужны только вопросам по сюжету. Ключ всегда
    # пользовательский: зашивать общий в открытое GPL-приложение нельзя.
    gemini_key: str = ""
    gemini_model: str = ""
    # ── Обложки ──────────────────────────────────────────────────────────
    # Ключ themoviedb.org — ЗАПАСНОЙ источник постера: он идёт в дело только
    # там, где у карточки Shikimori постера нет вовсе или ссылка не открылась.
    # Ключ пользовательский по той же причине, что и у Gemini.
    tmdb_key: str = ""
    # Складывать скачанные обложки в общую папку и брать их оттуда в следующий
    # раз. Кладовая общая с «Апгрейдом аниме-пака» (см. poster_cache).
    poster_cache: bool = True
    frames_no_repeat: bool = False       # не брать кадры, уже бывшие в паках
    char_roles: str = "both"             # main | supporting | both
    # Чем спрашивать мангу: "character" — портрет персонажа, "cover" — обложка.
    manga_question: str = "character"
    # Типы изданий (kind у Manga): манга, манхва, манхуа, ранобэ и т.п.
    manga_kinds: dict = field(
        default_factory=lambda: {k: k in ("manga", "manhwa", "manhua",
                                          "light_novel")
                                 for k in MANGA_KINDS})
    # ── Видео ────────────────────────────────────────────────────────────
    song_video: bool = False             # включает долю роликов в ползунке
    video_cut: int = VIDEO_CUT
    video_crf: int = VIDEO_CRF
    video_preset: int = VIDEO_PRESET
    # Какие типы песен вообще брать. Снятая галочка = типа в паке нет, сколько
    # бы ни стояло в его счётчике.
    pick_openings: bool = True
    pick_endings: bool = True
    pick_inserts: bool = True
    openings: int = 54
    endings: int = 20
    inserts: int = 16
    difficulty_min: int = 0
    difficulty_max: int = 100
    categories: dict = field(default_factory=lambda: {c: True for c in SONG_CATEGORIES})
    allow_rebroadcast: bool = True
    allow_dub: bool = False
    # ── Аниме ────────────────────────────────────────────────────────────
    # «Сложность пака» — 1…10 по узнаваемости тайтла (индексу популярности):
    # 1 — то, что знают все, 10 — то, что почти никто не смотрел. Работает в
    # любом режиме, в том числе когда песен нет вовсе (кадры).
    level_min: int = 1
    level_max: int = 10
    # Средняя узнаваемость пака: 0 — не следить, 1…10 — стараться держать
    # среднюю сложность около этого значения. Работает ВНУТРИ рамок level_min…
    # level_max: «от 1 до 10, в среднем 4» — это пак с редкими крайностями и
    # серединой около четвёрки (просьба пользователя).
    level_avg: int = 0
    # То же самое, но отдельно для вопросов-ПЕРСОНАЖЕЙ: их сложность считается
    # не только по узнаваемости тайтла, но и по тому, скольким людям персонаж
    # попал в избранное на Shikimori (см. char_question_level). 0 — не следить.
    char_level_avg: int = 0
    score_from: float = 0.0
    score_to: float = 10.0
    kinds: dict = field(default_factory=lambda: {k: True for k in ANIME_KINDS})
    year_from: int = 1944
    year_to: int = field(default_factory=_current_year)
    genres_include: list[int] = field(default_factory=list)
    genres_exclude: list[int] = field(default_factory=list)
    genres_partial: bool = True          # достаточно одного из выбранных жанров
    # ── Прочее ───────────────────────────────────────────────────────────
    # Дубли выключены навсегда: галочек для них на вкладке больше нет (просьба
    # пользователя — «должны всегда быть выключены»). Поля оставлены, потому что
    # на них завязаны проверки отбора, но включить их неоткуда.
    dup_anime: bool = False              # несколько песен одного аниме
    dup_franchise: bool = False          # несколько аниме одной франшизы
    sort_by_index: bool = False          # порядок и цены — по индексу популярности
    images: bool = False                 # коллаж из скриншотов в вопросе
    images_time: int = 7                 # за сколько секунд до конца он появится
    # Сколько секунд висит постер в ОТВЕТЕ. 0 — без ограничения: картинка
    # остаётся на экране, пока ведущий не перейдёт дальше (просьба пользователя
    # — раньше три секунды были зашиты намертво). Потолок — ANSWER_IMAGE_MAX:
    # дольше пяти секунд разглядывать постер уже незачем, игра стоит.
    answer_image_time: int = 3
    hint: bool = True                    # подсказка «Опенинг/Эндинг/OST»
    # Общая база + списки людей разом: тайтлы берутся случайно, но если
    # выпавший тайтл есть у кого-то из добавленных списков, его ник пишется в
    # реплике ведущего (просьба пользователя). Проверяется В КОНЦЕ, когда
    # вопросы уже отобраны.
    mark_owners: bool = False
    # Паки, чьи ответы нельзя повторять: франшизы из них в новый пак не попадут.
    exclude_siq: list[str] = field(default_factory=list)
    compress_audio: bool = True          # opus 192 + нормализация вместо исходника
    compress_images: bool = True         # AVIF под лимит вместо исходной картинки
    image_limit_kb: int = IMAGE_LIMIT_KB  # до скольки КБ ужимать картинку
    image_speed: int = IMAGE_SPEED       # -cpu-used: 8 — самая быстрая
    shuffle_questions: bool = False      # вопросы в теме в разнобой, а не по цене
    audio_cut: int = 20                  # длина отрезка песни, сек
    parallel: int = 8                    # одновременных загрузок
    max_pack_mb: int = MAX_PACK_MB       # потолок веса готового .siq
    out_dir: str = ""                    # куда класть .siq (пусто — «Загрузки»)

    # ── производные ──────────────────────────────────────────────────────
    @property
    def total_questions(self) -> int:
        return max(0, int(self.rounds)) * max(0, int(self.themes)) * max(0, int(self.questions))

    @property
    def picked_kinds(self) -> dict:
        """Какие типы песен разрешены галочками."""
        return {"opening": bool(self.pick_openings),
                "ending": bool(self.pick_endings),
                "insert": bool(self.pick_inserts)}

    @property
    def quotas(self) -> dict:
        picked = self.picked_kinds
        return {"opening": max(0, int(self.openings)) if picked["opening"] else 0,
                "ending": max(0, int(self.endings)) if picked["ending"] else 0,
                "insert": max(0, int(self.inserts)) if picked["insert"] else 0}

    @property
    def total_quota(self) -> int:
        return sum(self.quotas.values())

    @property
    def random_pool(self) -> bool:
        """Брать ли аниме из общей базы, а не из чьих-то списков.

        Отдельной галочки «Похожие» больше нет: сняты обе общие базы — значит
        пак собирается по спискам людей, это и есть единственное, что тогда
        остаётся. Сколько человек должны сойтись, задаёт similar_count."""
        return bool(self.random_mode)

    @property
    def mix_shares(self) -> dict:
        """Доли ВСЕХ родов вопросов, в сумме ровно 100: {ключ: проценты}.

        Ключи — «songs» (обычные песенные вопросы) и типы вопросов как они
        зовутся в квотах: VIDEO_KIND, FRAME_KIND, CHAR_KIND, MANGA_KIND,
        PIXEL_KIND, ANAGRAM_KIND, PLOT_KIND.

        Необязательные части считаются, только пока стоят их галочки («Вопрос —
        ролик», «— манга», «— пиксели», «— анаграмма», «— по сюжету»): снятая
        галочка убирает часть из ползунка целиком, а не оставляет молча
        работать сохранённый процент."""
        raw = {
            "songs": max(0, int(self.pct_songs)),
            VIDEO_KIND: max(0, int(self.pct_videos)) if self.song_video else 0,
            FRAME_KIND: max(0, int(self.pct_frames)),
            CHAR_KIND: max(0, int(self.pct_chars)),
            MANGA_KIND: max(0, int(self.pct_manga)) if self.pack_manga else 0,
            PIXEL_KIND: max(0, int(self.pct_pixel)) if self.pack_pixel else 0,
            ANAGRAM_KIND: (max(0, int(self.pct_anagram))
                           if self.pack_anagram else 0),
            PLOT_KIND: max(0, int(self.pct_plot)) if self.pack_plot else 0,
        }
        keys = list(raw)
        total = sum(raw.values())
        if total <= 0:
            return {k: (100 if k == "songs" else 0) for k in keys}
        if total == 100:
            return raw                             # обычный случай — без дележа
        out = {k: v * 100 // total for k, v in raw.items()}
        rest = 100 - sum(out.values())
        for key in sorted(keys, key=lambda k: -(raw[k] * 100 % total)):
            if rest <= 0:
                break
            out[key] += 1
            rest -= 1
        return out

    # Порядок родов вопросов в «исторической» пятёрке percents.
    _LEGACY_MIX_ORDER = ("songs", VIDEO_KIND, FRAME_KIND, CHAR_KIND, MANGA_KIND)

    @property
    def percents(self) -> tuple[int, int, int, int, int]:
        """Доли (песни, ролики, кадры, персонажи, манга) — первые пять частей.

        Это срез mix_shares, а не отдельный расчёт: сумма его пяти чисел равна
        сотне только пока нет пикселей, анаграмм и вопросов по сюжету — они
        забирают свою долю из той же сотни. Полный состав — в mix_shares."""
        shares = self.mix_shares
        return tuple(shares.get(k, 0) for k in self._LEGACY_MIX_ORDER)

    @property
    def songs_percent(self) -> int:
        """Доля вопросов, которым нужна песня из AnisongDB: и обычных, и
        роликов (ролик — это та же песня, только видео)."""
        shares = self.mix_shares
        return shares.get("songs", 0) + shares.get(VIDEO_KIND, 0)

    @property
    def manga_percent(self) -> int:
        """Доля вопросов по манге/манхве/ранобэ."""
        return self.mix_shares.get(MANGA_KIND, 0)

    @property
    def silent_kinds(self) -> list[str]:
        """Роды вопросов без песни, у которых есть доля, — в порядке SILENT_KINDS."""
        shares = self.mix_shares
        return [k for k in SILENT_KINDS if shares.get(k, 0)]

    @property
    def only_kind(self) -> Optional[str]:
        """Режим «весь пак одним родом вопросов без песни» — кадры, персонажи,
        манга, пиксели, анаграммы или сюжет."""
        if self.songs_percent:
            return None
        picked = self.silent_kinds
        return picked[0] if len(picked) == 1 else None

    @property
    def mixed(self) -> bool:
        """Смешанный пак: больше одного рода вопросов сразу."""
        return sum(1 for p in self.mix_shares.values() if p) > 1

    @property
    def has_songs(self) -> bool:
        """Будут ли в паке вопросы, которым нужна песня (обычные или ролики).

        От этого зависит выбор общей базы: мастер-лист AMQ знает только тайтлы
        с песнями, поэтому пакам из кадров и персонажей он не годится вовсе —
        база для них всегда берётся с Shikimori."""
        return bool(self.songs_percent and any(self.picked_kinds.values()))

    @property
    def question_quotas(self) -> dict:
        """Сколько вопросов какого типа нужно набрать.

        Доли задаёт ползунок (проценты песен/роликов/кадров/персонажей), а
        заданные пользователем опенинги/эндинги/OST ужимаются пропорционально —
        их сумма становится ровно числом обычных песенных вопросов (ролики
        считаются отдельной квотой)."""
        total = self.total_questions
        shares = self.mix_shares
        songs_ok = bool(self.has_songs)
        # Вопросы без песни в словаре первыми: при делении поровну (9 вопросов
        # на две равные доли) лишний вопрос по стабильной сортировке достаётся
        # тому, кто раньше, — пусть это будут кадры, а не песня.
        weights = {k: shares.get(k, 0) for k in SILENT_KINDS}
        weights[VIDEO_KIND] = shares.get(VIDEO_KIND, 0) if songs_ok else 0
        weights["songs"] = shares.get("songs", 0) if songs_ok else 0
        if sum(weights.values()) <= 0:
            weights = {k: 0 for k in weights}
            weights["songs"] = 1
        counts = _split_total(total, weights)
        quotas = _scale_quotas(self.quotas, counts["songs"])
        for kind in SILENT_KINDS + (VIDEO_KIND,):
            quotas[kind] = counts.get(kind, 0)
        return quotas

    def validate(self) -> list[str]:
        """Список проблем, из-за которых генерацию запускать бессмысленно."""
        problems: list[str] = []
        if self.total_questions <= 0:
            problems.append("Раундов, тем и вопросов должно быть хотя бы по одному.")
        # Квоты по типам песен — только для песенного режима: в режиме кадров
        # песен нет вовсе, там вопросов ровно столько, сколько тайтлов. В
        # смешанном режиме квоты ужимаются под число песенных вопросов сами,
        # поэтому достаточно, чтобы хоть один тип песни был разрешён.
        if self.only_kind or not self.songs_percent:
            pass
        elif not any(self.picked_kinds.values()):
            problems.append("Не выбран ни один тип песни: включите опенинги, "
                            "эндинги или OST — либо уведите ползунок состава "
                            "на кадры и персонажей.")
        elif self.total_quota <= 0:
            # Ролику песня нужна ровно так же, как обычному вопросу: он берётся
            # из тех же опенингов и эндингов, только видео вместо звука.
            problems.append("Опенингов, эндингов и OST ноль — песен в паке не "
                            "будет вовсе. Распределите их или уведите ползунок "
                            "состава с песен и роликов.")
        if self.percents[1] and not (self.pick_openings or self.pick_endings):
            problems.append("Ролики бывают только из опенингов и эндингов — OST "
                            "на AnimeThemes не лежат вовсе. Включите опенинги "
                            "или эндинги либо уведите долю роликов в ноль.")
        if not self.random_pool:
            live = [u for u in self.users if u.username.strip() and u.statuses]
            if not live:
                problems.append("Добавьте хотя бы одного пользователя со списком "
                                "(или включите общую базу — тогда аниме "
                                "возьмутся случайно).")
            if self.similar_count > max(1, len(live)):
                problems.append(
                    f"Совпадение требуется у {self.similar_count} человек, а "
                    f"списков всего {len(live)} — столько не наберётся.")
        # Песенные настройки проверяем, только пока песни в паке есть: пак из
        # одних кадров, анаграмм и сюжетов до AnisongDB не доходит вовсе, и
        # ругаться на его категории не за что.
        if self.songs_percent and not any(self.categories.get(c)
                                          for c in SONG_CATEGORIES):
            problems.append("Не выбрана ни одна категория песен.")
        if not any(self.kinds.get(k) for k in ANIME_KINDS):
            problems.append("Не выбран ни один тип аниме.")
        if self.manga_percent and not any(self.manga_kinds.get(k)
                                          for k in MANGA_KINDS):
            problems.append("В паке есть доля манги, но не выбран ни один её "
                            "тип: включите мангу, манхву или ранобэ.")
        if self.mix_shares.get(PLOT_KIND) and not str(self.gemini_key or "").strip():
            problems.append(
                "В паке есть доля вопросов по сюжету, а ключ Gemini не введён: "
                "вопрос из пересказа делает модель, без ключа взяться ему "
                "неоткуда. Введите ключ или уведите долю сюжета в ноль.")
        if self.mix_shares.get(ANAGRAM_KIND) and self.anagram_lang not in ANAGRAM_LANGS:
            problems.append("Для анаграмм выбран неизвестный язык названия.")
        if self.mix_shares.get(PIXEL_KIND) and int(self.pixel_seconds or 0) < 2:
            problems.append("Ролик-проявление короче двух секунд — проявляться "
                            "в нём нечему.")
        if self.manga_percent and not self.random_pool:
            live = [u for u in self.users
                    if u.username.strip() and u.statuses and u.target == "manga"]
            if not live:
                problems.append(
                    "В паке есть доля манги, а списков манги нет: переключите "
                    "хотя бы один список на «Манга/ранобэ» либо уведите долю "
                    "манги в ноль.")
        if self.difficulty_min > self.difficulty_max:
            problems.append("Сложность песни: «от» больше, чем «до».")
        if self.level_min > self.level_max:
            problems.append("Сложность пака: «от» больше, чем «до».")
        if self.level_avg and not (self.level_min <= self.level_avg <= self.level_max):
            problems.append(
                f"Средняя сложность {self.level_avg} не попадает в рамки "
                f"«от {self.level_min} до {self.level_max}».")
        if self.score_from > self.score_to:
            problems.append("Оценка: «от» больше, чем «до».")
        if self.year_from > self.year_to:
            problems.append("Год: «от» больше, чем «до».")
        if self.songs_percent and self.audio_cut < 5:
            problems.append("Отрезок песни короче 5 секунд.")
        if self.songs_percent and self.images and self.images_time >= self.audio_cut:
            problems.append(
                "Картинки должны появляться раньше, чем кончится песня: "
                f"{self.images_time} с ≥ отрезка {self.audio_cut} с.")
        return problems

    # ── сохранение в settings.json ───────────────────────────────────────
    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items()
             if k not in ("users", "saved_users")}
        d["users"] = [u.to_dict() for u in self.users]
        d["saved_users"] = [u.to_dict() for u in self.saved_users]
        return d

    # Как старые галочки состава превращаются в проценты ползунка. Ключи —
    # то, что могло лежать в settings.json до появления ползунка.
    _LEGACY_MIX = ("frames_only", "chars_only", "mix_frames", "mix_chars",
                   "mix_frames_per", "mix_chars_per")

    @staticmethod
    def _percents_from_legacy(d: dict) -> Optional[tuple[int, int, int]]:
        """Проценты состава по старым настройкам («только кадры», «ещё и кадры
        по N на песню»). None — старых настроек в файле нет."""
        if not any(k in d for k in PackSettings._LEGACY_MIX):
            return None
        if d.get("frames_only"):
            return (0, 100, 0)
        if d.get("chars_only"):
            return (0, 0, 100)
        per_f = max(1, int(d.get("mix_frames_per") or 2)) if d.get("mix_frames") else 0
        per_c = max(1, int(d.get("mix_chars_per") or 1)) if d.get("mix_chars") else 0
        if not per_f and not per_c:
            return (100, 0, 0)
        weight = 1 + per_f + per_c
        songs = int(round(100.0 / weight))
        frames = int(round(100.0 * per_f / weight))
        return (songs, frames, max(0, 100 - songs - frames))

    @classmethod
    def from_dict(cls, d: dict) -> "PackSettings":
        s = cls()
        if not isinstance(d, dict):
            return s
        legacy = cls._percents_from_legacy(d)
        if legacy is not None and "pct_songs" not in d:
            s.pct_songs, s.pct_frames, s.pct_chars = legacy
        for key, value in d.items():
            if value is None:
                continue
            if key in ("users", "saved_users"):
                setattr(s, key, [UserList.from_dict(u) for u in (value or [])
                                 if isinstance(u, dict)])
            elif key == "exclude_siq":
                s.exclude_siq = [str(p) for p in (value or []) if p]
            elif key in ("categories", "kinds", "manga_kinds"):
                if isinstance(value, dict):
                    getattr(s, key).update({k: bool(v) for k, v in value.items()})
            elif key in ("dup_anime", "dup_franchise"):
                # Дубли аниме и франшиз выключены навсегда (просьба
                # пользователя): сохранённое «включено» из старых настроек
                # молча игнорируем, галочек для них больше нет.
                continue
            elif key in ("genres_include", "genres_exclude"):
                out = []
                for g in (value or []):
                    try:
                        out.append(int(g))
                    except (TypeError, ValueError):
                        continue
                setattr(s, key, out)
            elif hasattr(s, key):
                try:
                    setattr(s, key, type(getattr(s, key))(value))
                except (TypeError, ValueError):
                    pass
        if s.song_video and "pct_videos" not in d:
            # До ползунка галочка «Вопрос — ролик» превращала в ролики ВСЕ
            # песенные вопросы разом — читаем её как «доля роликов = вся доля
            # песен», иначе сохранённая галочка молча перестала бы работать.
            s.pct_videos, s.pct_songs = int(s.pct_songs), 0
        if "pack_manga" not in d and int(s.pct_manga or 0) > 0:
            # Галочки манги раньше не было, а доля была: включаем её, иначе
            # сохранённая доля манги молча пропала бы из ползунка.
            s.pack_manga = True
        # Потолок появился позже самой настройки — подрезаем и сохранённое.
        s.answer_image_time = max(0, min(ANSWER_IMAGE_MAX,
                                         int(s.answer_image_time or 0)))
        # Потолок длины названия под анаграмму: 0 — снят совсем, иначе не короче
        # самой короткой анаграммы, какая вообще бывает (иначе не прошло бы ни
        # одно название и род вопросов молча вымер бы).
        limit = max(0, int(s.anagram_max_chars or 0))
        s.anagram_max_chars = limit and max(ANAGRAM_MIN_LETTERS, limit)
        # Скорость показа анаграммы: 0 — таймера нет, иначе от единицы до
        # потолка (быстрее шестидесяти символов в секунду текст не прочитать).
        try:
            cps = max(0.0, float(s.anagram_cps or 0.0))
        except (TypeError, ValueError):
            cps = ANAGRAM_CHARS_PER_SEC
        s.anagram_cps = cps and min(ANAGRAM_CPS_MAX, max(1.0, cps))
        return s


@dataclass
class SongCandidate:
    """Песня, прошедшая все фильтры, вместе с карточкой аниме."""
    song: dict
    anime: dict
    users: list[str] = field(default_factory=list)
    kind: str = "opening"
    trim_start: int = 0
    has_poster: bool = False
    has_collage: bool = False
    has_frame: bool = False
    # Ролик опенинга/эндинга с AnimeThemes вместо отрезка звука.
    has_video: bool = False
    video_url: str = ""
    # Персонаж вопроса «угадай персонажа»: {"name", "poster", "main"}.
    character: dict = field(default_factory=dict)
    # Сколько человек добавили этого персонажа в избранное на Shikimori.
    # −1 — не спрашивали или не узнали; ноль — спросили, и он ни у кого.
    char_favorites: int = -1
    # Кандидата отвергли по сложности уже во время загрузки (средняя сложность
    # персонажей). Не то же самое, что упавшая загрузка: в счётчик «не
    # скачалось» такие не идут.
    rejected: bool = False
    # Из какого каталога карточка: "anime" или "manga" (манга, манхва, ранобэ).
    # У манги нет ни песен, ни кадров — вопросом служит персонаж или обложка.
    media: str = "anime"
    price: int = 0                   # проставляется assign_prices()
    compress_audio: bool = True      # копия одноимённых настроек пака
    compress_images: bool = True
    # Реальные имена картинок проставляет загрузчик: без сжатия расширение
    # берётся от исходника (.jpg/.png/.webp), со сжатием это всегда .avif.
    poster_name: str = ""
    frame_name: str = ""
    collage_name: str = ""
    # Ссылка на скриншот, ставший вопросом-кадром: по ней ведётся память о том,
    # какие кадры уже показывались в прошлых паках.
    frame_url: str = ""
    # Перемешанные буквы названия — сам вопрос-анаграмма (см. make_anagram).
    anagram: str = ""
    # Вопрос по сюжету: текст вопроса от модели и, в режиме «деталь сюжета»,
    # варианты правильного ответа. Пустой список — отвечают названием тайтла.
    plot_question: str = ""
    plot_answers: list[str] = field(default_factory=list)
    # Откуда взят пересказ — уходит в реплику ведущего («Наруто вики, Серия 12»).
    plot_source: str = ""
    # Индекс самой популярной части франшизы: сиквел спрашивается так же, как
    # оригинал, поэтому и узнаваемость у него оригинала (0.0 — не считали).
    franchise_index: float = 0.0

    # Имя медиафайлов внутри пака. Пустое — считается по media_key (так работают
    # тесты и старые паки); генератор проставляет сюда «Сгенерировано в
    # SI-HYX(Название тайтла)», чтобы файлы в архиве читались глазами.
    media_base: str = ""

    @property
    def base_kind(self) -> str:
        """Тип песни, лежащей в основе вопроса.

        У вопроса-ролика это опенинг или эндинг: сам ролик — только форма
        подачи, а подсказка, надбавка к цене и ответ берутся от песни, как у
        обычного песенного вопроса."""
        if self.kind == VIDEO_KIND:
            return song_kind(self.song.get("songType")) or "opening"
        return self.kind

    @property
    def is_video(self) -> bool:
        """Вопрос-ролик (ролика могло и не найтись — тогда играет звук)."""
        return self.kind == VIDEO_KIND

    @property
    def is_frame(self) -> bool:
        """Вопрос-кадр — картинкой или роликом-проявлением (песни в нём нет,
        даже если карточка песни осталась от отбора)."""
        return self.kind in FRAME_KINDS

    @property
    def is_pixel(self) -> bool:
        """Вопрос-пиксели: кадр подаётся роликом, который проясняется."""
        return self.kind == PIXEL_KIND

    @property
    def is_text(self) -> bool:
        """Вопрос из одного текста — анаграмма или сюжет."""
        return self.kind in TEXT_KINDS

    @property
    def is_silent(self) -> bool:
        """Вопросу не нужна песня вовсе: картинка, ролик-проявление или текст."""
        return self.kind in SILENT_KINDS

    @property
    def is_manga(self) -> bool:
        """Карточка из каталога манги/манхвы/ранобэ, а не аниме."""
        return self.media == "manga"

    @property
    def is_character(self) -> bool:
        """Вопрос «угадай персонажа»: показывается портрет, а не кадр.

        Вопрос по манге тоже считается таким, если персонаж для него выбран
        (настройка «Вопрос по манге: портрет персонажа») — ответ, цена и
        варианты у них общие. С обложкой персонажа нет, и вопрос остаётся
        обычным «угадай произведение по картинке»."""
        return self.kind == CHAR_KIND or (self.kind == MANGA_KIND
                                          and bool(self.character))

    @property
    def is_picture(self) -> bool:
        """Вопросом служит КАРТИНКА тайтла — кадр, пиксели, персонаж, обложка.

        Не то же самое, что is_silent: анаграмме и сюжету картинка не нужна
        вовсе, а этим — нужна, и без неё вопроса не будет."""
        return self.kind in IMAGE_KINDS

    @property
    def char_name(self) -> str:
        return str((self.character or {}).get("name") or "").strip()

    @property
    def char_names(self) -> list[str]:
        """ВСЕ имена персонажа: русское, ромадзи и «Прочие» с его страницы на
        Shikimori (поле synonyms). Именно их и засчитываем в ответе — угадывают
        персонажа, и звать его игрок может как угодно."""
        char = self.character or {}
        names = [char.get("name"), char.get("russian"), char.get("romaji")]
        names += list(char.get("names") or [])
        # Сырые «Прочие» Shikimori бывают одной строкой через запятую («Al,
        # Armored Alchemist») — разбиваем (обычно это уже сделал animepack_api).
        for syn in (char.get("synonyms") or []):
            names += str(syn or "").split(",")
        out, seen = [], set()
        for name in names:
            text = str(name or "").strip()
            if text and text.casefold() not in seen:
                seen.add(text.casefold())
                out.append(text)
        return out

    @property
    def audio_file(self) -> str:
        return str(self.song.get("audio") or "")

    @property
    def ann_id(self) -> int:
        try:
            return int(self.song.get("annId") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def mal_id(self) -> int:
        try:
            return int(self.anime.get("malId") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def media_key(self) -> str:
        """Основа имён медиафайлов. Берём annSongId, а не annId: при разрешённых
        дублях аниме два вопроса одного тайтла иначе делили бы один файл. В
        режиме кадров песни нет вовсе — тогда ключом служит MAL id."""
        sid = (self.song.get("annSongId") or self.song.get("amqSongId")
               or self.ann_id or self.mal_id)
        return str(sid)

    @property
    def file_base(self) -> str:
        """Основа имени файлов вопроса внутри пака. Генератор кладёт сюда
        «Сгенерировано в SI-HYX(Название тайтла)»; пустое — старое поведение с
        числовым ключом."""
        return self.media_base or self.media_key

    @property
    def audio_out(self) -> str:
        """Имя дорожки ВНУТРИ пака. Со сжатием это opus, без — тот же файл, что
        приехал с CDN (mp3), просто обрезанный."""
        if self.compress_audio:
            return f"{self.file_base}.opus"
        ext = os.path.splitext(self.audio_file)[1] or ".mp3"
        return f"{self.file_base}{ext}"

    @property
    def video_out(self) -> str:
        """Имя ролика внутри пака. mp4, как и у «Обработки»: AV1 в mp4 —
        то, что она сама выдаёт на выходе."""
        return f"{self.file_base}.mp4"

    @property
    def image_ext(self) -> str:
        return ".avif" if self.compress_images else ".jpg"

    @property
    def poster_file(self) -> str:
        return self.poster_name or f"{self.file_base}_poster{self.image_ext}"

    @property
    def collage_file(self) -> str:
        return self.collage_name or f"{self.file_base}{self.image_ext}"

    @property
    def frame_file(self) -> str:
        """Картинка-вопрос: кадр из аниме либо портрет персонажа."""
        return self.frame_name or f"{self.file_base}_frame{self.image_ext}"

    @property
    def difficulty(self) -> float:
        try:
            return float(self.song.get("songDifficulty") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def title_ru(self) -> str:
        return (self.anime.get("russian") or self.anime.get("name")
                or self.song.get("animeENName") or "")

    @property
    def year(self) -> int:
        try:
            return int((self.anime.get("airedOn") or {}).get("year") or 0)
        except (TypeError, ValueError):
            return 0

    @property
    def song_name(self) -> str:
        """Название песни — у вопроса без песни его нет, даже если карточка
        песни осталась от отбора (в смешанном режиме кандидат приходит с
        песней, а вопросом становится кадр или анаграмма)."""
        if self.is_silent:
            return ""
        return str(self.song.get("songName") or "").strip()

    @property
    def artist(self) -> str:
        if self.is_silent:
            return ""
        return str(self.song.get("songArtist") or "").strip()

    @property
    def score(self) -> float:
        try:
            return float(self.anime.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @property
    def own_index(self) -> float:
        """«Индекс популярности» самого тайтла — та же величина, по которой
        сортирует ShikimoriHYX: взвешенные по статусам списки, приглушённые
        возрастом тайтла и слегка — его оценкой."""
        base = index_base_from_statuses_stats(self.anime.get("statusesStats"))
        return popularity_index(base, self.year or None, self.score)

    @property
    def index(self) -> float:
        """Узнаваемость вопроса. У сиквела она равна узнаваемости franchise —
        «Доктор Стоун: Научное будущее. Часть 3» знают ровно настолько же,
        насколько «Доктора Стоуна», хотя своих зрителей у части мало."""
        return max(self.own_index, float(self.franchise_index or 0.0))

    @property
    def level(self) -> int:
        """Сложность ТАЙТЛА 1…10 (1 — узнают все, 10 — не узнает никто)."""
        return index_level(self.index)

    @property
    def char_level(self) -> int:
        """Сложность вопроса-персонажа 1…10.

        Считается по двум мерам сразу (просьба пользователя): узнаваемость
        самого тайтла и то, скольким людям персонаж попал в избранное на
        Shikimori — чем больше добавивших, тем персонаж легче. Пока избранное не
        спрошено (−1), остаётся одна узнаваемость тайтла."""
        return char_question_level(self.level, self.char_favorites)

    @property
    def question_level(self) -> int:
        """Сложность именно ЭТОГО вопроса: у персонажа своя (char_level), у
        остальных — узнаваемость тайтла."""
        return self.char_level if self.is_character else self.level

    @property
    def tag(self) -> str:
        """«OP1», «ED2», «OST» — что именно за песня. У вопроса без песни
        (картинка, анаграмма, сюжет) тега нет."""
        if self.is_silent:
            return ""
        return song_tag(self.song.get("songType"))

    # ── правильный ответ ─────────────────────────────────────────────────
    @property
    def title_with_year(self) -> str:
        """«Название (год)» с тегом песни, если он есть."""
        title = self.title_ru.strip()
        year = self.year
        # У части тайтлов Shikimori сам держит год в названии («Могучий Атом
        # (2003)») — второй раз его дописывать не надо, а тег песни встаёт
        # перед годом («Могучий Атом OP1 (2003)»).
        if year:
            title = re.sub(rf"\s*\(\s*{year}\s*\)\s*$", "", title)
        tag = self.tag
        if tag:
            title = f"{title} {tag}"
        if year:
            title = f"{title} ({year})".strip()
        return title

    @property
    def main_answer(self) -> str:
        """«Русское название OP1 (год) — 『Песня』». У вопроса-персонажа на месте
        песни стоит имя персонажа: «Название (2020) — 『Имя』». Без того и
        другого остаётся просто название с годом — так и просили."""
        title = self.title_with_year
        if self.is_character and self.char_name:
            return f"{title} — 『{self.char_name}』"
        if self.song_name:
            return f"{title} — 『{self.song_name}』"
        return title

    def answer_variants(self) -> list[str]:
        """Все засчитываемые варианты ответа: основной, голое русское название и
        остальные имена тайтла с Shikimori (ромадзи, английское, «лицензировано
        в РФ под названием», синонимы). Дубли схлопываются без учёта регистра —
        SIGame сверяет ответы построчно.

        Порядок: сперва основной ответ, потом ИНЫЕ названия (ромадзи,
        английское, лицензионное, синонимы), а голое русское название — в самом
        конце: сразу после основного оно смотрится копией («Повар-боец Сома
        (2014), Повар-боец Сома…»).

        Иероглифы не берём вовсе: японское название и японские синонимы ведущему
        не прочитать, а игрок их не наберёт (просьба пользователя)."""
        if self.plot_answers:
            # Вопрос по сюжету с ответом-ДЕТАЛЬЮ: тайтл в таком вопросе назван
            # прямо, а угадывают саму деталь — её написания и засчитываем.
            return _dedup_answers(list(self.plot_answers))
        variants = [self.main_answer]
        if self.is_character:
            # В вопросе-персонаже угадывают ПЕРСОНАЖА, а не тайтл: голое
            # название аниме верным ответом быть не должно, иначе вопрос
            # решается с одного взгляда на постер.
            #
            # Название произведения пишется РОВНО ОДИН РАЗ — в основном ответе,
            # а доп-варианты состоят из одних только других имён персонажа
            # (просьба пользователя). Раньше каждое имя дублировалось ещё и в
            # паре с названием, и список ответов выглядел как десять почти
            # одинаковых строк.
            variants.extend(self.char_names)
            return _dedup_answers(variants)
        variants.append(self.anime.get("name"))            # ромадзи
        variants.append(self.anime.get("english"))
        for syn in (self.anime.get("synonyms") or []):
            variants.append(syn)
        variants.append(self.anime.get("licenseNameRu"))   # «Лицензировано в РФ»
        variants.append(self.title_ru)                     # то же, но без года
        return _dedup_answers(variants)


@dataclass
class PackResult:
    path: str = ""
    songs: list = field(default_factory=list)
    requested: int = 0
    failed_media: int = 0
    cancelled: bool = False
    elapsed: float = 0.0             # сколько секунд заняла генерация


# ─────────────────────────────────────────────────────────────────────────────
# Вспомогательные чистые функции (их и проверяют тесты)
# ─────────────────────────────────────────────────────────────────────────────
# Лесенка цен по сложности. Разрыв между самым лёгким и самым трудным вопросом
# нарочно неполный: по просьбе пользователя шаг ужат с 2 до 1,5 очка, так что
# крайние цены расходятся втрое (6 → 20), а не в десять раз (2 → 20), как было.
_PRICE_RANGES = ((90, 6), (80, 8), (70, 9), (60, 11), (50, 12),
                 (40, 14), (30, 15), (20, 17), (10, 18), (0, 20))
_PRICE_MIN = _PRICE_RANGES[0][1]

# Надбавка к цене за тип песни (просьба пользователя): опенинг < эндинг <
# OST, ровно по единице. То есть если опенинг стоит 6, эндинг того же
# тайтла — 7, а OST — 8.
_KIND_PRICE_STEP = {"opening": 0, "ending": 1, "insert": 2}
# Множитель цены за вопрос-персонажа. Персонажа узнать труднее, чем сам тайтл,
# а второстепенного — труднее, чем главного, поэтому множители разные (просьба
# пользователя): главный герой — полтора, второстепенный — 1,8.
_CHAR_PRICE_MULT = {True: 1.5, False: 1.8}


def char_price_mult(cand) -> float:
    """Во сколько раз вопрос-персонаж дороже вопроса о самом тайтле."""
    if getattr(cand, "kind", "") != CHAR_KIND:
        return 1.0
    main = bool((getattr(cand, "character", None) or {}).get("main"))
    return _CHAR_PRICE_MULT[main]


# ── «В избранном» у персонажа ────────────────────────────────────────────────
# Лесенка узнаваемости персонажа по числу добавивших его в избранное на
# Shikimori: 1 — знают все (у «Лелуша» 10 740), 10 — не знает никто (единицы).
# Пороги подобраны по живым данным: главные герои хитов набирают тысячи,
# заметный второстепенный — сотню, проходной — единицы.
CHAR_FAV_LEVELS = (5000, 2000, 900, 400, 180, 80, 30, 12, 4)
CHAR_MAX_LEVEL = len(CHAR_FAV_LEVELS) + 1
# Сколько в сложности вопроса-персонажа весит узнаваемость самого тайтла (а
# остальное — избранное персонажа). Поровну: тайтл подсказывает, откуда герой,
# избранное — насколько он на слуху сам по себе.
CHAR_TITLE_WEIGHT = 0.5


def char_fav_level(favorites) -> int:
    """Уровень персонажа 1…10 по числу добавивших в избранное."""
    try:
        value = int(favorites)
    except (TypeError, ValueError):
        return CHAR_MAX_LEVEL
    for level, threshold in enumerate(CHAR_FAV_LEVELS, start=1):
        if value >= threshold:
            return level
    return CHAR_MAX_LEVEL


def char_question_level(title_level: int, favorites) -> int:
    """Сложность вопроса-персонажа 1…10 по узнаваемости тайтла и избранному.

    favorites < 0 — «не спрашивали»: тогда остаётся один только уровень тайтла,
    как было до появления этой меры."""
    try:
        base = max(1, min(MAX_LEVEL, int(title_level)))
    except (TypeError, ValueError):
        base = MAX_LEVEL
    try:
        fav = int(favorites)
    except (TypeError, ValueError):
        return base
    if fav < 0:
        return base
    mixed = CHAR_TITLE_WEIGHT * base + (1.0 - CHAR_TITLE_WEIGHT) * char_fav_level(fav)
    return max(1, min(MAX_LEVEL, int(round(mixed))))


# Насколько цена вопроса-персонажа отходит от цены его тайтла из-за избранного:
# по столько очков на каждый уровень разницы. Много в избранном — персонажа
# узнают, и вопрос дешевеет; редкого спрашивать дороже.
CHAR_FAV_PRICE_STEP = 1


def char_fav_price_shift(cand) -> int:
    """Надбавка (или скидка) к цене вопроса-персонажа за его известность."""
    if not getattr(cand, "is_character", False):
        return 0
    try:
        fav = int(getattr(cand, "char_favorites", -1))
    except (TypeError, ValueError):
        return 0
    if fav < 0:
        return 0                       # избранное не спрашивали — цена как была
    return CHAR_FAV_PRICE_STEP * (cand.char_level - cand.level)
# Надбавка за сложность самой песни (просьба пользователя): когда цены считаются
# по индексу популярности, сложность угадывания из AMQ иначе пропадала бы вовсе.
# Трудную песню (difficulty близка к нулю — её почти никто не угадывает) вопрос
# стоит на столько очков дороже, лёгкую — ровно столько же, сколько и был.
SONG_DIFF_BONUS_MAX = 3


def song_difficulty_bonus(difficulty) -> int:
    """0…SONG_DIFF_BONUS_MAX очков сверху за сложность песни."""
    try:
        d = float(difficulty)
    except (TypeError, ValueError):
        return 0
    if d <= 0 or d > 100:
        return 0
    return int(round((100.0 - d) / 100.0 * SONG_DIFF_BONUS_MAX))


# Что в названии считается буквой: перемешиваем только их, а пробелы, дефисы и
# знаки остаются на своих местах — иначе по одной длинной каше не видно даже,
# из скольких слов состоит ответ.
_ANAGRAM_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)


def anagram_source(anime: dict, lang: str = "russian",
                   max_chars: int = 0) -> str:
    """Название, из которого делается анаграмма («» — годного нет).

    Язык берётся с карточки Shikimori СТРОГО тот, что просят: русское —
    russian, английское — english, ромадзи — name. Подмены на соседний язык
    больше нет (просьба пользователя): раньше при отсутствующем, слишком
    коротком или слишком длинном русском названии вопрос молча уезжал на
    латиницу, и в русском паке всплывали анаграммы вида «HHA CEYIG MOR NN».
    Теперь такой тайтл просто уступает место следующему.

    Заодно проверяется сама письменность: у Shikimori в поле russian нередко
    лежит латиница («Ao Ashi»), а в name — иероглифы. Для русского нужны
    кириллические буквы и ни одной латинской, для английского и ромадзи —
    наоборот.

    Отсеиваются и продолжения с приписками — «Мастера меча онлайн:
    Порядковый ранг», «Второй Мэйджор 2», «Log Horizon: Entaku Houkai»
    (см. is_plain_title): в анаграмму идёт только простое название.

    max_chars (0 — без потолка) отсекает названия-простыни."""
    card = anime or {}
    by_lang = {"russian": card.get("russian"), "english": card.get("english"),
               "romaji": card.get("name")}
    key = lang if lang in ANAGRAM_LANGS else "russian"
    text = " ".join(str(by_lang.get(key) or "").split())
    limit = max(0, int(max_chars or 0))
    if not text or (limit and len(text) > limit):
        return ""
    if has_cjk(text) or not _is_lang_script(text, key):
        return ""
    if _letters_count(text) < ANAGRAM_MIN_LETTERS or not is_plain_title(text):
        return ""
    return text


# Письменность названия. Кириллица и латиница (вместе с диакритикой европейских
# языков — «Gintama°», «Fate/stay night»), чтобы отличить настоящее русское
# название от латинского огрызка в том же поле карточки.
_RE_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_RE_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def _is_lang_script(text: str, lang: str) -> bool:
    """Написано ли название той письменностью, какой ждут от этого языка."""
    cyr = bool(_RE_CYRILLIC.search(text))
    lat = bool(_RE_LATIN.search(text))
    if lang == "russian":
        return cyr and not lat
    return lat and not cyr


def _letters_count(text: str) -> int:
    return sum(1 for ch in str(text or "") if _ANAGRAM_LETTER.match(ch))


def _letter_runs(text: str) -> list[list[int]]:
    """Позиции букв, разбитые по словам: подряд идущие буквы — одно слово.

    Всё, что буквой не считается (пробел, дефис, апостроф, двоеточие, цифра),
    слово обрывает и остаётся на своём месте."""
    runs: list[list[int]] = []
    cur: list[int] = []
    for i, ch in enumerate(text):
        if _ANAGRAM_LETTER.match(ch):
            cur.append(i)
        elif cur:
            runs.append(cur)
            cur = []
    if cur:
        runs.append(cur)
    return runs


def make_anagram(title: str, rng: Optional[random.Random] = None) -> str:
    """Анаграмма названия: в каждом слове перемешаны ЕГО СОБСТВЕННЫЕ буквы.

    Буквы не переезжают из слова в слово (просьба пользователя): «Мастера меча
    онлайн» даёт «АРЕТСАМ АЧЕМ НЙАЛНО», и в каждом слове ровно тот набор букв,
    что был в нём. Раньше буквы мешались по всему названию сразу — «Охотник х
    Охотник» превращался в «ОКИТИХХ Х ОТНКОНО», где второе слово составлено из
    чужих букв, и разгадывать было нечем.

    Форма слов при этом сохраняется — сколько слов и какой длины было, столько
    и останется (знаки, цифры и пробелы стоят на прежних местах). Регистр
    приводим к прописным целиком: иначе заглавная буква выдавала бы начало
    настоящего слова.

    Результат гарантированно отличается от исходника; на пустое, слишком
    короткое или неперемешиваемое название («Я И ТЫ», «ААА») возвращается «»."""
    text = " ".join(str(title or "").split())
    if _letters_count(text) < ANAGRAM_MIN_LETTERS:
        return ""
    rng = rng or random.Random()
    upper = text.upper()
    out = list(upper)
    changed = False
    for spots in _letter_runs(upper):
        letters = [upper[i] for i in spots]
        # Одна буква или сплошь одинаковые («ААА») — мешать в этом слове нечего.
        if len(set(letters)) < 2:
            continue
        # Несколько попыток: у короткого слова перестановка запросто совпадает
        # с исходной, и одной попытки мало.
        for _ in range(12):
            shuffled = list(letters)
            rng.shuffle(shuffled)
            if shuffled != letters:
                for pos, ch in zip(spots, shuffled):
                    out[pos] = ch
                changed = True
                break
    return "".join(out) if changed else ""


def _dedup_answers(variants) -> list[str]:
    """Схлопывает варианты ответа без учёта регистра и выбрасывает иероглифику
    (её ведущему не прочитать, а игроку не набрать)."""
    out, seen = [], set()
    for v in variants:
        text = str(v or "").strip()
        if not text or text.casefold() in seen or has_cjk(text):
            continue
        seen.add(text.casefold())
        out.append(text)
    return out


def _split_total(total: int, weights: dict) -> dict:
    """Делит total между ключами по весам «наибольшим остатком»: сумма долей
    всегда ровно total, а лишние единицы достаются тем, у кого дробная часть
    больше. Так ползунок «60/25/15» на 20 вопросах не теряет ни одного."""
    base = sum(max(0, int(v)) for v in weights.values())
    if total <= 0 or base <= 0:
        return {k: 0 for k in weights}
    exact = {k: max(0, int(v)) * total / base for k, v in weights.items()}
    out = {k: int(v) for k, v in exact.items()}
    rest = total - sum(out.values())
    for key in sorted(exact, key=lambda k: (exact[k] - out[k], exact[k]),
                      reverse=True):
        if rest <= 0:
            break
        out[key] += 1
        rest -= 1
    return out


def _scale_quotas(quotas: dict, target: int) -> dict:
    """Ужимает квоты по типам песен так, чтобы их сумма стала ровно target.
    Пропорции сохраняются, остаток раздаётся по наибольшей дробной части."""
    base = sum(max(0, int(v)) for v in quotas.values())
    if target <= 0 or base <= 0:
        return {k: 0 for k in quotas}
    exact = {k: max(0, int(v)) * target / base for k, v in quotas.items()}
    out = {k: int(v) for k, v in exact.items()}
    rest = target - sum(out.values())
    for key in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True):
        if rest <= 0:
            break
        out[key] += 1
        rest -= 1
    return out


def price_for_difficulty(difficulty) -> int:
    """Цена вопроса по сложности AMQ: угадываемая песня стоит дёшево."""
    try:
        d = float(difficulty)
    except (TypeError, ValueError):
        return 1
    for threshold, price in _PRICE_RANGES:
        if d >= threshold:
            return price
    return 1


def price_for_index(index: float, sorted_indexes: list[float]) -> int:
    """Цена по «индексу популярности» — по той же лесенке 2…20, что и по
    сложности AMQ, только шкалу задаёт не сам индекс (он абсолютный и у разных
    паков разного порядка), а место тайтла СРЕДИ ОТОБРАННЫХ: самый узнаваемый
    вопрос пака стоит 2, самый безвестный — 20. Равные индексы (например все
    нули у тайтлов без статистики) получают одну цену."""
    n = len(sorted_indexes)
    if n <= 1:
        return price_for_difficulty(50)          # одному вопросу сравнивать не с чем
    lower = bisect.bisect_left(sorted_indexes, index)   # строго менее популярных
    return price_for_difficulty(100.0 * lower / (n - 1))


def assign_prices(songs: list, s: PackSettings) -> list:
    """Проставляет cand.price всем отобранным песням и возвращает их же.

    База — сложность угадывания из AMQ (или место по индексу популярности, если
    включена галочка), сверху — надбавка за тип песни: опенинги дешевле
    эндингов, эндинги дешевле вставок (их узнают хуже всего)."""
    # У вопроса-кадра сложности AMQ нет вовсе — единственная доступная мера
    # узнаваемости там индекс. Как только в паке появляется хоть один кадр,
    # по индексу считаются ВСЕ вопросы: две разные шкалы цен в одном паке дали
    # бы кадры и песни, несравнимые между собой.
    by_index = bool(getattr(s, "sort_by_index", False)
                    or getattr(s, "only_kind", None)
                    or any(c.is_silent for c in songs))
    ladder = sorted(c.index for c in songs) if by_index else []
    for cand in songs:
        base = (price_for_index(cand.index, ladder) if by_index
                else price_for_difficulty(cand.difficulty))
        # Персонаж — та же цена, что за его тайтл, с надбавкой за роль и
        # поправкой на «в избранном» (известного героя узнают — вопрос дешевеет,
        # редкого спрашивать дороже).
        base = int(round(base * char_price_mult(cand))) + char_fav_price_shift(cand)
        # У ролика надбавка та же, что у его песни: опенинг он или эндинг.
        cand.price = max(_PRICE_MIN,
                         base + _KIND_PRICE_STEP.get(cand.base_kind, 0))
        if by_index and not cand.is_silent:
            # Цены по индексу — про узнаваемость ТАЙТЛА, а трудность самой
            # песни там никак не учтена. Добавляем её отдельной небольшой
            # надбавкой, чтобы редкая вставка не стоила столько же, сколько
            # заезженный опенинг того же аниме.
            cand.price += song_difficulty_bonus(cand.difficulty)
    return songs


def arrange_questions(songs: list, s: PackSettings) -> list[list]:
    """Раскладка пака: список тем, в каждой — вопросы в том порядке, в каком они
    попадут в content.xml. Одно место на всех, чтобы таблица во вкладке и сам
    пак не разъезжались.

    Обычно вопросы в теме идут по возрастанию цены; галочка «в разнобой»
    (`shuffle_questions`) оставляет их ровно в том порядке, в каком их набрал
    генератор (а он этот список уже перемешал) — цены тогда скачут, как в живых
    паках. Само перемешивание живёт в select_songs, а не здесь: функция обязана
    быть чистой, иначе таблица во вкладке и содержимое пака разъедутся."""
    assign_prices(songs, s)
    ordered = list(songs)
    shuffled = bool(getattr(s, "shuffle_questions", False))
    if getattr(s, "sort_by_index", False) and not shuffled:
        # Пак идёт от самых узнаваемых тайтлов к самым безвестным.
        ordered.sort(key=lambda c: c.index, reverse=True)
    per_theme = max(1, int(s.questions))
    chunks = [ordered[i:i + per_theme] for i in range(0, len(ordered), per_theme)]
    if shuffled:
        return chunks
    return [sorted(chunk, key=lambda c: c.price) for chunk in chunks]


def fmt_duration(seconds) -> str:
    """Секунды → «00:01:05». В ASPG строка склеивалась вручную и давала
    «00:00:3» (без ведущего нуля), а при большом времени картинок — минус."""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    total = max(1, total)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def fmt_elapsed(seconds) -> str:
    """Длительность генерации по-человечески: «3 мин 20 с», «48 с», «1 ч 5 мин»."""
    try:
        total = int(round(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    total = max(0, total)
    if total < 60:
        return f"{total} с"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} ч {m} мин"
    return f"{m} мин {s} с" if s else f"{m} мин"


# Иероглифика (кана, кандзи, хангыль, «широкие» знаки препинания). Строка с
# любым таким символом в ответ не идёт.
_RE_CJK = re.compile(r"[぀-ヿ㐀-䶿一-鿿가-힯"
                     r"豈-﫿＀-￯]")


def has_cjk(text) -> bool:
    """Есть ли в строке иероглифы/кана/хангыль."""
    return bool(_RE_CJK.search(str(text or "")))


# «Сложность пака» 1…10 по индексу популярности. Пороги идут делением примерно
# на 1,8: 1 — то, что смотрели все, 10 — то, что почти никто. Калибровано по
# живым данным Shikimori (сверху «Клинок, рассекающий демонов» ≈ 1 000 000,
# снизу «Торико» ≈ 8 000).
INDEX_LEVELS = (700_000, 390_000, 215_000, 120_000, 66_000, 37_000, 20_000,
                11_000, 6_000)
MAX_LEVEL = len(INDEX_LEVELS) + 1


def index_level(index) -> int:
    """Уровень сложности тайтла: 1 — узнают все, 10 — не узнает никто."""
    try:
        value = float(index)
    except (TypeError, ValueError):
        return MAX_LEVEL
    for level, threshold in enumerate(INDEX_LEVELS, start=1):
        if value >= threshold:
            return level
    return MAX_LEVEL


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
_RE_TRAIL_PUNCT = re.compile(r"[\s.,!?:;]+$")


def title_root(name) -> str:
    """Корень названия: «Доктор Стоун: Научное будущее. Часть 3» → «доктор
    стоун». Пустая строка — корня нет (сравнивать не с чем)."""
    text = str(name or "").strip()
    if not text:
        return ""
    text = _RE_TITLE_TAIL.sub("", text)
    text = re.sub(r"[\s.,!?:;]+$", "", text)     # хвостовая пунктуация
    text = _RE_TITLE_TRAIL_NUM.sub("", text)
    text = re.sub(r"[\s.,!?:;]+", " ", text).strip().casefold()
    # Слишком короткий корень («Ван», «Ай») схлопнул бы посторонние тайтлы.
    return text if len(text) >= 5 else ""


def is_plain_title(name) -> bool:
    """Простое ли это название — без хвоста сезона, части и подзаголовка.

    «Мастера меча онлайн» — да; «Мастера меча онлайн: Порядковый ранг»,
    «Второй Мэйджор 2», «Трусливый велосипедист: Новое поколение», «Log
    Horizon: Entaku Houkai» — нет. Отличается от title_root тем, что ничего не
    обрезает, а отвечает на вопрос «обрезать вообще есть что?»: хвост нашёлся —
    значит перед нами продолжение или побочка.

    Нужно анаграммам (просьба пользователя): загадывать надо сам тайтл, а не
    его третий сезон с приставкой — по перемешанным буквам подзаголовка ответ
    всё равно никто не наберёт."""
    text = " ".join(str(name or "").split())
    if not text:
        return False
    # Восклицание в конце («Убийца Акамэ!», «Маленькие проказники!») — часть
    # самого названия, а не приписка: снимаем его с ОБЕИХ сравниваемых строк.
    bare = _RE_TRAIL_PUNCT.sub("", text)
    core = _RE_TITLE_TAIL.sub("", text)
    core = _RE_TRAIL_PUNCT.sub("", core)
    core = _RE_TITLE_TRAIL_NUM.sub("", core)          # «… 2», «… II»
    return " ".join(core.split()) == bare


def song_kind(song_type: str) -> Optional[str]:
    """«Opening 1» → «opening». None — незнакомый тип."""
    head = str(song_type or "").split(" ")[0].lower()
    return head if head in SONG_KINDS else None


# Как тип песни выглядит в правильном ответе: «Название OP1 (2010)».
_TAG_BY_KIND = {"opening": "OP", "ending": "ED", "insert": "OST"}
_RE_TAG_NUM = re.compile(r"(\d+)\s*$")


def song_tag(song_type: str) -> str:
    """«Opening 1» → «OP1», «Ending 12» → «ED12», «Insert Song» → «OST».
    Незнакомый тип — пустая строка (в ответ ничего не дописываем)."""
    kind = song_kind(song_type)
    if not kind:
        return ""
    m = _RE_TAG_NUM.search(str(song_type or ""))
    return _TAG_BY_KIND[kind] + (m.group(1) if m else "")


def _truthy(value) -> bool:
    """AnisongDB когда-то слал 0/1, теперь шлёт true/false — понимаем оба."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes")
    return False


def _chunks(seq, size):
    seq = list(seq)
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


def _genre_ids(anime: dict) -> set[int]:
    out: set[int] = set()
    for g in (anime.get("genres") or []):
        if not isinstance(g, dict):
            continue
        try:
            out.add(int(g.get("id")))
        except (TypeError, ValueError):
            continue
    return out


def filter_song(song: dict, s: PackSettings) -> bool:
    """Проходит ли песня по настройкам (без обращения к сети)."""
    if not isinstance(song, dict):
        return False
    if not song.get("audio"):
        return False
    if not song.get("songLength"):
        return False
    kind = song_kind(song.get("songType"))
    if kind is None:
        return False
    # Снятая галочка типа («только опенинги») — песня даже не рассматривается.
    if not s.picked_kinds.get(kind, True):
        return False
    if not song.get("animeType"):
        return False
    if not (song.get("linked_ids") or {}).get("myanimelist"):
        return False
    if not s.allow_rebroadcast and _truthy(song.get("isRebroadcast")):
        return False
    if not s.allow_dub and _truthy(song.get("isDub")):
        return False
    category = str(song.get("songCategory") or "").lower()
    if not s.categories.get(category, False):
        return False
    difficulty = song.get("songDifficulty")
    if difficulty is None:
        return False
    try:
        difficulty = float(difficulty)
    except (TypeError, ValueError):
        return False
    return s.difficulty_min <= difficulty <= s.difficulty_max


def filter_anime(anime: dict, s: PackSettings, manga: bool = False) -> bool:
    """Проходит ли карточка Shikimori по настройкам.

    manga=True — та же проверка для карточки манги/ранобэ: у неё свой набор
    типов (манга/манхва/ранобэ) и нет ни скриншотов, ни коллажа."""
    if not isinstance(anime, dict):
        return False
    if not anime.get("malId"):
        return False
    if not (anime.get("poster") or {}).get("originalUrl"):
        return False
    kind = str(anime.get("kind") or "").lower()
    if manga:
        if not s.manga_kinds.get(kind, False):
            return False
    else:
        # Скриншоты нужны, только если из них собирается коллаж (ASPG требовал
        # их всегда и зря выбрасывал половину подходящих тайтлов). Для
        # вопроса-кадра они уже не обязательны: кадры всегда добираются ещё и
        # с AniList/Kitsu.
        if s.images and len(anime.get("screenshots") or []) < COLLAGE_IMAGES:
            return False
        if not s.kinds.get(kind, False):
            return False
    year = ((anime.get("airedOn") or {}).get("year"))
    try:
        year = int(year)
    except (TypeError, ValueError):
        return False
    if not (s.year_from <= year <= s.year_to):
        return False
    try:
        score = float(anime.get("score") or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if not (s.score_from <= score <= s.score_to):
        return False
    genres = _genre_ids(anime)
    if s.genres_exclude and genres & set(s.genres_exclude):
        return False
    if s.genres_include:
        need = set(s.genres_include)
        if s.genres_partial:
            if not (genres & need):
                return False
        elif not need <= genres:
            return False
    return True


def frame_url_key(url) -> str:
    """Ключ кадра в истории: ссылка без ?query (Shikimori дописывает к ней
    метку времени, и один и тот же кадр иначе выглядел бы новым каждый раз)."""
    return str(url or "").split("?")[0].strip()


def load_frame_history(path: str = FRAMES_HISTORY_FILE) -> list[str]:
    """Ссылки на кадры, уже побывавшие в собранных паках (пусто — файла нет)."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:  # noqa: BLE001 — истории может не быть вовсе
        return []
    urls = data.get("frames") if isinstance(data, dict) else data
    if not isinstance(urls, list):
        return []
    return [str(u) for u in urls if u]


def save_frame_history(urls, path: str = FRAMES_HISTORY_FILE) -> bool:
    """Перезаписывает историю кадров (самые старые обрезаются по лимиту)."""
    keep = [u for u in urls if u][-FRAME_HISTORY_LIMIT:]
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"frames": keep}, f, ensure_ascii=False)
        os.replace(tmp, path)
        return True
    except OSError:
        return False


# ── Что уже спрашивали в других паках ────────────────────────────────────────
# Правильный ответ сгенерированного пака выглядит как «Наруто OP1 (2002) —
# 『Song』»; чтобы понять, о какой франшизе речь, из него надо отрезать песню,
# год и тег типа песни, а остаток прогнать через title_root().
_RE_ANSWER_SONG = re.compile(r"\s*[—–-]\s*『.*$")
_RE_ANSWER_YEAR = re.compile(r"\s*\(\s*\d{4}\s*\)\s*$")
_RE_ANSWER_TAG = re.compile(r"\s+(OP|ED|OST)\s*\d*\s*$", re.IGNORECASE)


def answer_title(text) -> str:
    """Название тайтла из строки правильного ответа (без песни, года и тега)."""
    line = str(text or "").strip()
    line = _RE_ANSWER_SONG.sub("", line)
    line = _RE_ANSWER_YEAR.sub("", line)
    line = _RE_ANSWER_TAG.sub("", line)
    return line.strip()


def siq_answer_roots(path: str) -> set[str]:
    """Корни названий, спрошенных в готовом паке .siq.

    Нужны для галочки «не повторять франшизы из этих паков»: читаем только
    content.xml (это миллисекунды, медиа из архива не достаём), берём ВСЕ
    варианты правильного ответа и сводим каждый к корню названия — так «Наруто:
    Ураганные хроники» схлопнется с «Наруто»."""
    roots: set[str] = set()
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith("content.xml")]
            if not names:
                return roots
            root_el = ET.fromstring(zf.read(names[0]))
    except Exception:  # noqa: BLE001 — битый или чужой файл просто пропускаем
        return roots
    for ans in root_el.iter():
        if not ans.tag.rsplit("}", 1)[-1] == "answer":
            continue
        rt = title_root(answer_title(ans.text))
        if rt:
            roots.add(rt)
    return roots


def franchise_key(anime: dict) -> str:
    """Ключ франшизы. Пустая франшиза у Shikimori значит «одиночный тайтл» —
    такие нельзя схлопывать между собой, поэтому ключ делаем уникальным."""
    fr = str(anime.get("franchise") or "").strip()
    return fr or f"#{anime.get('malId') or anime.get('id')}"


# ─────────────────────────────────────────────────────────────────────────────
# Сборка content.xml
# ─────────────────────────────────────────────────────────────────────────────
PACK_AUTHOR = "Сгенерировано в программе SI-HYX"
# Как называются медиафайлы ВНУТРИ пака: «Сгенерировано в SI-HYX(Название
# тайтла).opus/.avif». Раньше это были номера песен из AnisongDB, и открывать
# такой архив вручную было невозможно.
MEDIA_NAME_PREFIX = "Сгенерировано в SI-HYX"


def build_content_xml(songs: list, s: PackSettings,
                      author: str = PACK_AUTHOR) -> bytes:
    """SIQ 5: раунды → темы → вопросы. Вопросы внутри темы идут по возрастанию
    цены (в ASPG порядок был случайный, и таблица в SIGame выглядела рвано)."""
    pkg = ET.Element("package", {
        "name": s.title or "Generated Songs Anime Pack",
        "version": "5",
        "id": str(uuid.uuid4()),
        "date": date.today().strftime("%d.%m.%Y"),
        "xmlns": SIQ_NS,
    })
    tags = ET.SubElement(pkg, "tags")
    ET.SubElement(tags, "tag").text = "Аниме"
    info = ET.SubElement(pkg, "info")
    authors = ET.SubElement(info, "authors")
    ET.SubElement(authors, "author").text = author
    rounds_el = ET.SubElement(pkg, "rounds")

    themes = arrange_questions(songs, s)
    per_round = max(1, int(s.themes))
    for r in range(max(1, int(s.rounds))):
        chunk = themes[r * per_round:(r + 1) * per_round]
        if not chunk:
            break
        round_el = ET.SubElement(rounds_el, "round", {"name": f"Раунд {r + 1}"})
        themes_el = ET.SubElement(round_el, "themes")
        for theme in chunk:
            theme_el = ET.SubElement(themes_el, "theme",
                                     {"name": s.theme_title or "SONGS ONLY"})
            questions_el = ET.SubElement(theme_el, "questions")
            for cand in theme:
                _append_question(questions_el, cand, s)
    return ET.tostring(pkg, encoding="utf-8", xml_declaration=True)


def _append_question(questions_el, cand: SongCandidate, s: PackSettings) -> None:
    price = cand.price or price_for_difficulty(cand.difficulty)
    q = ET.SubElement(questions_el, "question", {"price": str(price)})
    params = ET.SubElement(q, "params")

    # ── Вопрос: текст, кадр, ролик ЛИБО аудио (фоном) с коллажем и подсказкой ─
    q_param = ET.SubElement(params, "param", {"name": "question", "type": "content"})
    if cand.is_text:
        # Вопрос из одного текста — анаграмма или пересказ сюжета. У пересказа
        # задание идёт ПЕРЕД текстом и с waitForFinish="False", как у портрета
        # персонажа: без него это просто рассказ, и непонятно, что называть.
        # У анаграммы подписи нет вовсе (просьба пользователя): перемешанные
        # прописные буквы говорят сами за себя.
        if cand.kind != ANAGRAM_KIND:
            task = ET.SubElement(q_param, "item", {"waitForFinish": "False"})
            task.text = PLOT_TASK_TEXT
        text = (cand.anagram if cand.kind == ANAGRAM_KIND
                else cand.plot_question)
        attrs = {}
        if cand.kind == ANAGRAM_KIND:
            # Своё время показа: без duration SIGame берёт «скорость чтения» из
            # настроек ИГРОКА, и анаграмма улетает вдвое быстрее, чем её успеешь
            # разобрать. Ноль в настройке — таймера нет, текст висит до ответа.
            seconds = anagram_seconds(text, getattr(s, "anagram_cps",
                                                    ANAGRAM_CHARS_PER_SEC))
            if seconds:
                attrs["duration"] = fmt_duration(seconds)
        body = ET.SubElement(q_param, "item", attrs)
        body.text = text
    elif cand.is_pixel:
        # Вопрос-пиксели: кадр подаётся роликом, который за несколько шагов
        # проясняется (эффект «Пикселизация» из вкладки «Монтаж»). duration —
        # длина самого ролика: обрывать проявление на середине незачем.
        video = ET.SubElement(q_param, "item", {
            "type": "video", "isRef": "True",
            "duration": fmt_duration(s.pixel_seconds)})
        video.text = cand.video_out
    elif cand.is_picture:
        # Вопрос-картинка: песни нет, показывается кадр тайтла либо портрет
        # персонажа. Без duration картинка висит, пока ведущий не откроет ответ.
        if cand.is_character:
            # У портрета задание неочевидно: с виду это такой же кадр из аниме,
            # и игроки называют тайтл вместо героя. Поэтому текстом ПЕРЕД
            # картинкой и с waitForFinish="False" — задание висит на экране
            # ровно тогда, когда виден портрет (просьба пользователя).
            task = ET.SubElement(q_param, "item", {"waitForFinish": "False"})
            task.text = CHAR_TASK_TEXT
        frame = ET.SubElement(q_param, "item", {"type": "image", "isRef": "True"})
        frame.text = cand.frame_file
    else:
        # Подсказка «Опенинг/Эндинг/OST» идёт ПЕРЕД дорожкой и с
        # waitForFinish="False": так текст выводится одновременно с песней и
        # висит на экране, пока она играет. Раньше он стоял последним и
        # показывался уже ПОСЛЕ отрезка — то есть впустую.
        # Поверх ролика той же надписи нет: она загородила бы картинку. Там
        # «Опенинг»/«Эндинг» уходит ведущему в реплику — он произносит это вслух
        # одновременно с видео (просьба пользователя, см. ниже).
        hint_text = HINT_LABELS.get(cand.base_kind,
                                    KIND_TITLES.get(cand.base_kind,
                                                    cand.base_kind))
        if s.hint and not cand.has_video:
            hint = ET.SubElement(q_param, "item", {"waitForFinish": "False"})
            hint.text = hint_text
        if cand.has_video:
            if s.hint:
                # placement="replic" — это устный текст ведущего, а
                # waitForFinish="False" пускает его ОДНОВРЕМЕННО с роликом, а не
                # до него.
                said = ET.SubElement(q_param, "item",
                                     {"waitForFinish": "False",
                                      "placement": "replic"})
                said.text = hint_text
            # Ролик опенинга с AnimeThemes: он и картинка, и звук сразу, так
            # что ни коллаж, ни фоновая дорожка тут не нужны.
            video = ET.SubElement(q_param, "item", {
                "type": "video", "isRef": "True",
                "duration": fmt_duration(s.video_cut)})
            video.text = cand.video_out
            _append_answer(params, q, cand, s)
            return
        audio_seconds = s.audio_cut - (s.images_time if (s.images and cand.has_collage) else 0)
        audio = ET.SubElement(q_param, "item", {
            "type": "audio", "isRef": "True", "placement": "background",
            "duration": fmt_duration(audio_seconds)})
        audio.text = cand.audio_out
        if s.images and cand.has_collage:
            img = ET.SubElement(q_param, "item", {
                "type": "image", "isRef": "True",
                "duration": fmt_duration(s.images_time)})
            img.text = cand.collage_file

    _append_answer(params, q, cand, s)


def _append_answer(params, q, cand: SongCandidate, s: PackSettings) -> None:
    """Ответ: кто смотрел + исполнитель + постер.

    Никакой подписи-плашки на экране: из содержимого ответа остаётся только
    постер (как в паках пользователя) — название игроки видят строкой
    правильного ответа, а исполнитель уходит в реплику ведущего."""
    a_param = ET.SubElement(params, "param", {"name": "answer", "type": "content"})
    # Порядок в реплике один и тот же, откуда бы ни собрался пак (просьба
    # пользователя): сперва исполнитель — если вопрос песенный, — а следом голые
    # никнеймы тех, у кого тайтл есть в списке. Никаких «Есть у»: ведущий и так
    # читает имена людей.
    artist = cand.artist
    parts = []
    if artist:
        parts.append(f"Исполнитель — 『{artist}』")
    # У вопросов по сюжету (пересказ с фэндом-вики) в ответе НЕТ устного текста
    # вовсе — ни названия тайтла, ни адреса вики (просьба пользователя). Раньше
    # ведущему доставалась строка вида «Наруто (2002) · Naruto Wiki, Episode 12»,
    # и её приходилось зачитывать на каждом таком вопросе.
    if cand.users:
        parts.append(", ".join(cand.users))
    if parts:
        replic = ET.SubElement(a_param, "item",
                               {"waitForFinish": "False", "placement": "replic"})
        replic.text = " · ".join(parts)
    if cand.has_poster:
        # Без waitForFinish="False": постер не «играет одновременно» с репликой,
        # а показывается своим чередом (просьба пользователя).
        # Сколько он висит — настройка «Картинка в ответе»; ноль означает «без
        # ограничения»: тогда duration не пишем вовсе и картинка остаётся на
        # экране, пока ведущий не пойдёт дальше.
        attrs = {"type": "image", "isRef": "True"}
        seconds = max(0, min(ANSWER_IMAGE_MAX,
                             int(getattr(s, "answer_image_time", 3) or 0)))
        if seconds:
            attrs["duration"] = fmt_duration(seconds)
        poster = ET.SubElement(a_param, "item", attrs)
        poster.text = cand.poster_file

    # Первый <answer> показывается игрокам, остальные — синонимы, которые
    # ведущему засчитываются как верные (ромадзи, английское, японское,
    # российское лицензионное имя и синонимы с Shikimori).
    right = ET.SubElement(q, "right")
    for text in cand.answer_variants():
        ET.SubElement(right, "answer").text = text


# ─────────────────────────────────────────────────────────────────────────────
# Генератор
# ─────────────────────────────────────────────────────────────────────────────
class AnimePackGenerator:
    """Полный цикл: списки аниме → песни → медиа → .siq.

    Все длительные шаги зовут log()/progress() и проверяют should_stop(), чтобы
    вкладка могла показывать ход дела и останавливать генерацию.
    """

    def __init__(self, settings: PackSettings, *,
                 session=None, amq=None, anisong=None, mal=None, shikimori=None,
                 anilist=None, kitsu=None, themes=None, fandom=None, gemini=None,
                 tmdb=None,
                 log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None,
                 rng: Optional[random.Random] = None,
                 frames_history_path: str = FRAMES_HISTORY_FILE,
                 db_cache: Optional[ShikimoriDbCache] = None):
        self.s = settings
        self.session = session or make_session()
        self.amq = amq or AmqApi(self.session)
        self.anisong = anisong or AnisongApi(self.session)
        self.mal = mal or MalApi(self.session)
        self.shikimori = shikimori or ShikimoriApi(self.session)
        self.anilist = anilist or AniListApi(self.session)
        self.kitsu = kitsu or KitsuApi(self.session)
        self.themes = themes or AnimeThemesApi(self.session)
        # Фэндом-вики и Gemini нужны ровно одному роду вопросов — «по сюжету».
        # Без его доли клиенты не создаются вовсе: лишний ключ и лишняя сессия
        # ни к чему, а Gemini без ключа и не заработал бы.
        self.fandom = fandom
        self.gemini = gemini
        if settings.mix_shares.get(PLOT_KIND):
            if self.fandom is None:
                self.fandom = FandomApi(self.session)
            if self.gemini is None and str(settings.gemini_key or "").strip():
                from gemini_api import DEFAULT_MODEL, GeminiClient
                self.gemini = GeminiClient(
                    settings.gemini_key,
                    model=(settings.gemini_model or DEFAULT_MODEL),
                    log=lambda msg: self.log(msg),
                    stopped=lambda: self.stopped())
        # Запасной источник обложек. Без ключа клиент всё равно создаётся —
        # просто ничего не умеет (enabled=False), и проверок по всему коду не
        # нужно.
        self.tmdb = tmdb if tmdb is not None else TmdbApi(
            self.session, key=str(getattr(settings, "tmdb_key", "") or ""))
        # Пересказы уже спрошенных тайтлов и вики, у которых сюжета не нашлось:
        # медиа качается в несколько потоков, поэтому под замком.
        self._plot_lock = threading.Lock()
        self._plot_seen: set[str] = set()
        # Роды вопросов, которые в этом прогоне больше не получатся (кончился
        # ключ Gemini и т.п.): их места отдаются оставшимся, а не жгут
        # кандидатов впустую — см. _drop_kind и select_songs.
        self._dead_kinds: set[str] = set()
        # Сколько обложек взято из общей кладовой, а сколько пришло с TMDB —
        # печатается в итогах прогона. Считается из рабочих потоков, поэтому
        # под замком.
        self._poster_lock = threading.Lock()
        self._poster_hits = 0
        self._poster_tmdb = 0
        self._log = log or (lambda msg: None)
        self._progress = progress or (lambda done, total, msg: None)
        self._should_stop = should_stop or (lambda: False)
        self.rng = rng or random.Random()
        self.folder: str = ""
        self._failed_media = 0
        # Карточки каталога и части франшиз, пережившие перезапуск программы.
        self.db_cache = db_cache if db_cache is not None else ShikimoriDbCache()
        # Узнаваемость франшизы: ключ Shikimori → индекс серии целиком (самая
        # популярная часть + надбавка за живые сезоны и послабление по году,
        # см. shikimori_api.franchise_parts_index). Считается один раз на
        # франшизу за всю генерацию, а сами части — один раз на все генерации.
        self._fr_index: dict[str, float] = {}
        # Кадры, уже показанные в прошлых паках (галочка «не повторять»), плюс
        # взятые в этом паке. Медиа качается из нескольких потоков — выбор и
        # резервирование кадра идут под замком.
        self.frames_history_path = frames_history_path
        self._frames_lock = threading.Lock()
        self._frames_used: set[str] = set()
        if settings.frames_no_repeat:
            self._frames_used = {frame_url_key(u)
                                 for u in load_frame_history(frames_history_path)}
            self._frames_used.discard("")
        # Имена медиафайлов внутри пака («Сгенерировано в SI-HYX(Тайтл)») —
        # раздаются из нескольких потоков, поэтому счётчик под замком.
        self._names_lock = threading.Lock()
        self._names: dict[str, int] = {}
        # Франшизы, уже спрошенные в чужих паках (список .siq в настройках).
        self._excluded_roots: set[str] = set()
        # Запущенные ffmpeg: по «Стоп» их надо убить, иначе вкладка ждёт
        # окончания кодирования (до нескольких секунд на вопрос).
        self._procs_lock = threading.Lock()
        self._procs: set = set()
        # Карточки, уже приехавшие из каталога Shikimori (order: random).
        self._card_cache: dict[int, dict] = {}
        # То же для манги — отдельным словарём: id манги и аниме на MAL живут в
        # разных пространствах и совпадают сплошь и рядом.
        self._manga_cache: dict[int, dict] = {}
        # Вес пака: бюджет в байтах и то, что уже набрано. Ничего под лимит не
        # подгоняется — по среднему весу вопроса виден прогноз на весь пак, и
        # как только он вылезает за потолок, отбор останавливается.
        self._byte_budget = (max(1, int(getattr(settings, "max_pack_mb", MAX_PACK_MB)
                                        or MAX_PACK_MB))
                             * 1024 * 1024 * PACK_OVERHEAD)
        self._bytes_used = 0
        # Ролики опенингов с AnimeThemes: {MAL id: {«OP1»: {...}}}, спрашиваются
        # пачками по ходу отбора.
        self._themes_cache: dict[int, dict] = {}
        self._themes_lock = threading.Lock()
        # Ролики качаются строго по одному (см. VIDEO_RETRIES).
        self._video_lock = threading.Lock()
        # {url ролика: его длительность в секундах} — нужна, чтобы взять из
        # ролика случайный отрезок (_video_start).
        self._video_len: dict[str, float] = {}
        self._video_len_lock = threading.Lock()
        # Сколько времени ушло на каждый этап — итог печатается в конце (просьба
        # пользователя). Храним не сумму, а сами отрезки «с какой по какую
        # секунду шёл этап»: загрузки идут в несколько потоков, и сумма их
        # длительностей запросто больше всей генерации (те самые «картинки:
        # 17 мин, 487%» при трёх с половиной минутах работы). Проценты считаются
        # по СКЛЕЕННЫМ отрезкам — сколько времени на часах этап реально занимал.
        self._stage_lock = threading.Lock()
        self._stage_spans: dict[str, list[tuple[float, float]]] = {}
        self._stage_order: list[str] = []
        # Ники, чьи списки просили «в основном музыку»: их тайтлы по возможности
        # становятся песенными вопросами, а не кадрами и персонажами.
        self._music_nicks = {u.username.strip().casefold()
                             for u in (settings.users or [])
                             if u.prefer_music and u.username.strip()}
        # Счётчик подряд отвергнутых ради средней сложности (см. _level_fits).
        self._level_skips = 0
        self._level_warned = False
        # То же самое, но для средней сложности ПЕРСОНАЖЕЙ: она считается по
        # своей мере (тайтл + «в избранном»), и проверять её приходится уже в
        # рабочем потоке — персонаж выбирается только при загрузке медиа.
        self._char_levels: list[int] = []
        self._char_lock = threading.Lock()
        self._char_skips = 0
        self._char_warned = False
        # Сложность, которую реально держим: ноль — ту, что просили. Просимая
        # бывает недостижима в принципе (см. _char_reach), и тогда генератор
        # переезжает на ближайшую достижимую, а не «берёт что есть».
        self._char_target_eff = 0
        # Какие персонажи в этом паке реально попадались (по их сложности) и по
        # скольким кандидатам это уже видно.
        self._char_reach_lo = MAX_LEVEL
        self._char_reach_hi = 1
        self._char_seen = 0
        # А это теоретический размах: что вообще возможно при таких тайтлах.
        # Нужен только для формулировки — «таких не бывает» или «не попадались».
        self._char_floor = MAX_LEVEL
        self._char_ceil = 1
        # Сколько раз уже жаловались на одну и ту же беду (см. _log_rare).
        self._warn_lock = threading.Lock()
        self._warn_counts: dict[str, int] = {}
        # Отчёт «почему кандидатов не хватило»: сколько тайтлов база вообще
        # дала, сколько из них прошло проверки и на чём отсеялись остальные
        # (см. _accept_anime и _log_shortage).
        self._seen_titles = 0
        self._good_titles = 0
        self._skips: Counter = Counter()

    # ── служебное ─────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        self._log(msg)

    # Сколько раз подряд можно повторить в логе одну и ту же жалобу.
    WARN_REPEATS = 3

    def _log_rare(self, tag: str, message: str) -> None:
        """Пишет повторяющуюся жалобу не больше WARN_REPEATS раз за прогон.

        Когда сервер начинает отказывать, ошибка приходит на КАЖДЫЙ вопрос, и
        консоль превращается в простыню из одинаковых строк — по ней уже не
        видно, что вообще происходит с паком."""
        with self._warn_lock:
            n = self._warn_counts.get(tag, 0) + 1
            self._warn_counts[tag] = n
        if n <= self.WARN_REPEATS:
            self.log(message)
        elif n == self.WARN_REPEATS + 1:
            self.log(f"{tag}: та же ошибка повторяется — дальше молчу, "
                     "итог будет в конце.")

    def _log_warn_totals(self) -> None:
        """Итог по замолчанным жалобам: сколько раз каждая из них случилась."""
        with self._warn_lock:
            rows = [(tag, n) for tag, n in self._warn_counts.items()
                    if n > self.WARN_REPEATS]
        for tag, n in rows:
            self.log(f"{tag}: всего таких ошибок за прогон — {n}.")

    def stopped(self) -> bool:
        return bool(self._should_stop())

    # ── сколько времени ушло на что ───────────────────────────────────────
    @contextmanager
    def _timed(self, stage: str):
        """Запоминает отрезок работы этапа: «с какой по какую секунду».

        Зовётся и из рабочих потоков, поэтому под замком; порядок первых
        появлений запоминаем — по нему потом печатается итог."""
        started = time.monotonic()
        try:
            yield
        finally:
            ended = time.monotonic()
            with self._stage_lock:
                if stage not in self._stage_spans:
                    self._stage_spans[stage] = []
                    self._stage_order.append(stage)
                self._stage_spans[stage].append((started, ended))

    @staticmethod
    def _merge_spans(spans) -> float:
        """Длина СКЛЕЕННЫХ отрезков — сколько времени на часах этап шёл хоть в
        одном потоке. Восемь картинок, качавшихся одновременно по десять секунд,
        это десять секунд работы, а не восемьдесят."""
        rows = sorted((a, b) for a, b in spans if b > a)
        total, cur_start, cur_end = 0.0, None, None
        for start, end in rows:
            if cur_end is None or start > cur_end:
                if cur_end is not None:
                    total += cur_end - cur_start
                cur_start, cur_end = start, end
            elif end > cur_end:
                cur_end = end
        if cur_end is not None:
            total += cur_end - cur_start
        return total

    def log_stage_times(self, total: float = 0.0) -> None:
        """Печатает в лог, сколько заняла каждая часть работы.

        Время этапа — по часам, а не в человеко-секундах: сумма длительностей
        параллельных загрузок раньше давала «картинки: 17 мин, 487%» при трёх
        минутах работы. Сумма по потокам всё же остаётся в строке — по ней
        видно, насколько плотно этап был загружен."""
        with self._stage_lock:
            stages = [(name, list(self._stage_spans[name]))
                      for name in self._stage_order]
        if not stages:
            return
        if total > 0:
            self.log(f"Время по этапам (всего {fmt_elapsed(total)}):")
        else:
            self.log("Время по этапам:")
        parallel = max(1, int(self.s.parallel))
        for name, spans in stages:
            wall = self._merge_spans(spans)
            summed = sum(max(0.0, b - a) for a, b in spans)
            share = f", {min(100.0, wall / total * 100):.0f}%" if total > 0 else ""
            tail = ""
            if parallel > 1 and summed > wall * 1.2:
                tail = f" (в {parallel} потоков суммарно {fmt_elapsed(summed)})"
            self.log(f"  • {name}: {fmt_elapsed(wall)}{share}{tail}")

    def _over_budget(self, done: int, total: int) -> bool:
        """Пора ли останавливаться из-за веса.

        Ждать, пока пак реально перевалит за потолок, поздно — половина работы
        к тому моменту уже сделана впустую. Поэтому смотрим на средний вес
        набранного вопроса и прикидываем, во что выльется весь пак; первые
        BUDGET_WARMUP вопросов в расчёт не берём — на них разброс слишком велик
        (у одного тайтла ролик, у другого один постер)."""
        if self._bytes_used >= self._byte_budget:
            return True
        if done < BUDGET_WARMUP or done >= total:
            return False
        return self._bytes_used / done * total > self._byte_budget

    def _media_size(self, cand: SongCandidate) -> int:
        """Сколько байт занимает медиа этого вопроса в готовом паке."""
        names = []
        if cand.has_video:
            names.append(os.path.join("Video", cand.video_out))
        elif not cand.is_silent:
            names.append(os.path.join("Audio", cand.audio_out))
        for flag, name in ((cand.has_poster, cand.poster_file),
                           (cand.has_collage, cand.collage_file),
                           (cand.has_frame, cand.frame_file)):
            if flag and name:
                names.append(os.path.join("Images", name))
        total = 0
        # Через set: у вопроса-обложки картинка вопроса и постер ответа — это
        # ОДИН файл, и считать его дважды нельзя.
        for rel in dict.fromkeys(names):
            try:
                total += os.path.getsize(os.path.join(self.folder, rel))
            except OSError:
                pass
        return total

    def load_exclusions(self) -> None:
        """Собирает франшизы из чужих паков (настройка «Не повторять из этих
        .siq»). Непрочитанный файл — не ошибка: о нём просто пишем в лог."""
        self._excluded_roots = set()
        for path in (self.s.exclude_siq or []):
            if self.stopped():
                return
            roots = siq_answer_roots(path)
            if roots:
                self._excluded_roots |= roots
            else:
                self.log(f"Не вышло прочитать ответы из {os.path.basename(path)}")
        if self._excluded_roots:
            self.log(f"Не повторяю франшизы из чужих паков: "
                     f"{len(self._excluded_roots)} шт.")

    # ── шаг 1: список аниме ───────────────────────────────────────────────
    def _user_lists(self, target: str = "anime") -> list:
        """Живые карточки списков нужного раздела (аниме либо манга)."""
        return [u for u in self.s.users
                if u.username.strip() and u.statuses
                and str(u.target or "anime") == target]

    def _fetch_user_list(self, user, target: str = "anime") -> list[int]:
        """Список одного человека — с оглядкой на память между генерациями."""
        nick = user.username.strip()
        key = user_list_cache_key(f"{user.source}:{target}", nick, user.statuses)
        ids = cached_user_list(key)
        if ids is not None:
            self.log(f"Список {nick} ({user.source}) уже спрашивали — беру "
                     f"из памяти: {len(ids)} шт.")
            return list(ids)
        self.log(f"Беру список {nick} ({user.source}, "
                 f"{TARGET_LABELS.get(target, target)})…")
        if user.source == "shikimori":
            api = self.shikimori
        elif user.source == "anilist":
            api = self.anilist
        else:
            api = self.mal
        ids = api.user_anime_ids(nick, user.statuses, progress_cb=self.log,
                                 should_stop=self._should_stop, target=target)
        # Оборванный по «Стоп» список неполон — запоминать его нельзя:
        # следующий пак собрался бы по огрызку.
        if ids and not self.stopped():
            remember_user_list(key, ids)
        return list(ids)

    def _order_by_shares(self, seen: dict, by_user: dict) -> list[tuple[int, list]]:
        """Раскладывает id по долям списков (ползунок «Доли списков»).

        Без него порядок был просто случайным, и список на 1500 тайтлов
        забивал пак целиком, пока три списка по сотне почти не попадали в него
        (просьба пользователя). Здесь id выдаются по очереди, но очередь
        взвешенная: у кого доля больше, тот чаще и ходит.

        Метод — тот же, что при дележе мест по голосам (Д'Ондт): следующим
        берём список с наибольшим share/(взято+1). Тайтл, который есть у
        нескольких, отдаётся тому, чья очередь, и второй раз уже не выдаётся."""
        shares = {nick: max(0, int(pct)) for nick, pct in by_user.items()}
        if sum(shares.values()) <= 0 or len(shares) < 2:
            pairs = list(seen.items())
            self.rng.shuffle(pairs)
            return pairs
        pools: dict[str, list] = {}
        for nick in shares:
            pool = [aid for aid, owners in seen.items() if nick in owners]
            self.rng.shuffle(pool)
            pools[nick] = pool
        taken = {nick: 0 for nick in shares}
        out: list[tuple[int, list]] = []
        used: set = set()
        live = [n for n in shares if shares[n] > 0 and pools.get(n)]
        while live:
            nick = max(live, key=lambda n: shares[n] / (taken[n] + 1))
            pool = pools[nick]
            while pool and pool[-1] in used:
                pool.pop()
            if not pool:
                live.remove(nick)
                continue
            aid = pool.pop()
            used.add(aid)
            taken[nick] += 1
            out.append((aid, seen[aid]))
        # Хвост: тайтлы, до которых очередь не дошла (списки кончились
        # неодновременно). Они идут последними — если пак к тому времени не
        # набрался, пусть лучше будут они, чем недобор вопросов.
        rest = [(aid, owners) for aid, owners in seen.items() if aid not in used]
        self.rng.shuffle(rest)
        parts = ", ".join(f"{n} {shares[n]}%" for n in sorted(shares))
        self.log(f"Доли списков: {parts}")
        return out + rest

    def collect_manga_ids(self) -> list[tuple[int, list[str]]]:
        """[(id манги, у кого она в списке)] — то же, что collect_anime_ids, но
        для раздела манги/манхвы/ранобэ.

        Общей базы вроде AMQ у манги нет вовсе, поэтому случайный режим всегда
        идёт в каталог Shikimori."""
        if self.s.random_pool:
            return [(i, []) for i in self._random_shikimori_ids(manga=True)]
        seen: dict[int, list[str]] = {}
        by_user: dict[str, int] = {}
        for user in self._user_lists("manga"):
            if self.stopped():
                break
            nick = user.username.strip()
            by_user[nick] = int(user.share or 0)
            ids = self._fetch_user_list(user, "manga")
            for aid in ids:
                seen.setdefault(int(aid), [])
                if nick not in seen[int(aid)]:
                    seen[int(aid)].append(nick)
            self.log(f"{nick}: {len(ids)} манги/ранобэ")
        if not seen:
            return []
        pairs = self._order_by_shares(seen, by_user)
        self.log(f"Всего манги в работе: {len(pairs)}")
        return pairs

    def collect_anime_ids(self) -> list[tuple[int, list[str]]]:
        """[(id аниме, кто его смотрел)] в случайном порядке.

        Id — это ANN id только когда случайные аниме берутся из мастер-листа
        AMQ (так он устроен). И списки людей, и каталог Shikimori дают MAL id."""
        if self.s.random_pool:
            if not self.s.random_mode:
                # Галочка «Похожие» снята — списки не спрашиваем вовсе: пак
                # собирается случайными аниме, как и просил пользователь.
                self.log("«Похожие» снято — списки не спрашиваю, беру случайные "
                         "аниме из общей базы.")
            if self._random_source == "shikimori":
                if str(self.s.random_source or "") == "amq":
                    self.log("Песен в паке нет — базу беру с Shikimori: "
                             "мастер-лист AMQ знает только тайтлы с песнями.")
                return [(i, []) for i in self._random_shikimori_ids()]
            library = self.amq.library(progress_cb=self.log,
                                       should_stop=self._should_stop)
            ids = [ann for ann, year in library.items()
                   if year and self.s.year_from <= int(year) <= self.s.year_to]
            self.rng.shuffle(ids)
            self.log(f"Подходящих по году аниме в базе AMQ: {len(ids)}")
            return [(i, []) for i in ids]

        seen: dict[int, list[str]] = {}
        by_user: dict[str, int] = {}
        users = self._user_lists("anime")
        for user in users:
            if self.stopped():
                break
            nick = user.username.strip()
            by_user[nick] = int(user.share or 0)
            ids = self._fetch_user_list(user, "anime")
            for aid in ids:
                seen.setdefault(int(aid), [])
                if nick not in seen[int(aid)]:
                    seen[int(aid)].append(nick)
            self.log(f"{nick}: {len(ids)} аниме")

        if self.s.similar_count > 1:
            before = len(seen)
            need = int(self.s.similar_count)
            seen = {k: v for k, v in seen.items() if len(v) >= need}
            self.log(f"«Похожие»: из {before} аниме у {need}+ пользователей "
                     f"нашлось {len(seen)}")
        elif len(users) > 1:
            # «Похожие: 1 чел.» — списки просто складываются, совпадение не
            # требуется. Пишем об этом прямо, чтобы не выглядело, будто
            # совпадение всё-таки проверяется.
            self.log("«Похожие: 1 чел.» — беру всё из всех списков подряд, "
                     "совпадение не требуется.")
        pairs = self._order_by_shares(seen, by_user)
        self.log(f"Всего аниме в работе: {len(pairs)}")
        return pairs

    # Сколько карточек тянем из каталога Shikimori на один вопрос пака: часть
    # отсеют фильтры (оценка, жанры, дубли франшиз), часть не переживёт загрузку
    # медиа, так что запас нужен изрядный.
    RANDOM_OVERSHOOT = 8
    # Песенному паку запас нужен куда больше: песня в AnisongDB нашлась лишь у
    # 59 случайных тайтлов Shikimori из 150 (у ТВ-сериалов — у 31 из 52), а
    # мастер-лист AMQ по определению состоит из одних только «песенных».
    RANDOM_OVERSHOOT_SONGS = 20
    RANDOM_MAX_PAGES = 60

    def _random_shikimori_ids(self, manga: bool = False) -> list[int]:
        """Случайные тайтлы прямо из каталога Shikimori (order: random).

        В отличие от мастер-листа AMQ (16 МБ, только id и год) фильтры уходят на
        сервер, а карточки приезжают сразу целиком. Набранное складывается в
        кэш на диске и переживает перезапуск программы: следующая генерация с
        теми же фильтрами не тратит на каталог ни одного запроса, пока не нажата
        кнопка «Обновить базу» (просьба пользователя). manga=True берёт каталог
        манги: своей общей базы вроде AMQ у книг нет вовсе."""
        overshoot = (self.RANDOM_OVERSHOOT_SONGS if (self.s.has_songs and not manga)
                     else self.RANDOM_OVERSHOOT)
        want = max(50, self.s.total_questions * overshoot)
        what = "манги" if manga else "тайтлов"
        cache = self._manga_cache if manga else self._card_cache
        target = "manga" if manga else "anime"
        sig = shiki_cache_signature(self.s, manga)

        ids: list[int] = []
        seen: set[int] = set()

        def take(cards) -> int:
            """Кладёт карточки в память генератора и возвращает число новых."""
            fresh = 0
            for card in cards:
                try:
                    mal = int(card.get("malId") or card.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if not mal or mal in seen:
                    continue
                seen.add(mal)
                ids.append(mal)
                cache[mal] = card
                fresh += 1
            return fresh

        take(self.db_cache.cards(target, sig))
        if ids:
            self.log(f"Каталог Shikimori: {len(ids)} {what} взято из кэша "
                     "(обновить — кнопкой «Обновить базу»)")
        if len(ids) < want:
            self._fetch_random_cards(manga, want, sig, take, lambda: len(ids))
        self.rng.shuffle(ids)
        self.log(f"Случайных {what} с Shikimori: {len(ids)}")
        return ids

    def _fetch_random_cards(self, manga: bool, want: int, sig: str,
                            take: Callable[[list], int],
                            have: Callable[[], int]) -> None:
        """Дочерпывает каталог Shikimori постранично, пока набранного меньше
        `want`.

        Всё, что приехало, тут же уходит в кэш на диск — даже если генерацию
        оборвали кнопкой «Стоп»: следующий запуск начнёт не с нуля."""
        if manga:
            kinds = [k for k in MANGA_KINDS if self.s.manga_kinds.get(k)]
        else:
            kinds = [k for k in ANIME_KINDS if self.s.kinds.get(k)]
        season = f"{int(self.s.year_from)}_{int(self.s.year_to)}"
        what = "манги" if manga else "тайтлов"
        target = "manga" if manga else "anime"
        fetch = (self.shikimori.random_mangas if manga
                 else self.shikimori.random_animes)
        try:
            for page in range(1, self.RANDOM_MAX_PAGES + 1):
                if self.stopped() or have() >= want:
                    break
                try:
                    cards = fetch(page, season=season, kinds=kinds,
                                  score=int(self.s.score_from),
                                  genres_exclude=self.s.genres_exclude)
                except AnimePackApiError as e:
                    self.log(f"Shikimori: {e} — беру, что успел набрать")
                    break
                if not cards:
                    break
                fresh = take(cards)
                self.db_cache.add_cards(target, sig, cards)
                self.log(f"Каталог Shikimori: набрано {have()} {what}…")
                if fresh == 0:
                    break             # каталог по этим фильтрам кончился
        finally:
            self.db_cache.save()

    # Обход каталога ЦЕЛИКОМ (кнопка «Обновить базу»). Порядок тут нужен
    # устойчивый: при order: random сервер тасует выборку на каждый запрос,
    # страницы накладываются друг на друга, и обход упирался в «страницу без
    # новых id» на первых же сотнях карточек, сколько бы их ни было в каталоге
    # на самом деле. С order: id каждая страница отдаёт свой кусок ровно один
    # раз, и каталог по-настоящему кончается.
    FULL_ORDER = "id"
    # Предохранитель от бесконечного цикла, если сервер вдруг перестанет
    # слушаться page: 50 карточек на страницу — это четверть миллиона тайтлов,
    # больше всего каталога Shikimori.
    FULL_MAX_PAGES = 5000

    def fetch_full_catalog(self, manga: bool = False) -> list[int]:
        """Вычерпывает каталог Shikimori ЦЕЛИКОМ под текущие фильтры.

        В отличие от _random_shikimori_ids здесь нет потолка «сколько нужно на
        пак»: страницы идут одна за другой, пока каталог не кончится или пока не
        нажали «Остановить». Всё, что приехало, тут же уходит в кэш на диск —
        остановка на середине не теряет набранного. Возвращает id карточек."""
        if manga:
            kinds = [k for k in MANGA_KINDS if self.s.manga_kinds.get(k)]
        else:
            kinds = [k for k in ANIME_KINDS if self.s.kinds.get(k)]
        season = f"{int(self.s.year_from)}_{int(self.s.year_to)}"
        what = "манги" if manga else "тайтлов"
        target = "manga" if manga else "anime"
        cache = self._manga_cache if manga else self._card_cache
        sig = shiki_cache_signature(self.s, manga)
        fetch = (self.shikimori.random_mangas if manga
                 else self.shikimori.random_animes)
        ids: list[int] = []
        seen: set[int] = set()
        try:
            for page in range(1, self.FULL_MAX_PAGES + 1):
                if self.stopped():
                    self.log(f"Каталог Shikimori: остановлено на {len(ids)} "
                             f"{what} — набранное сохранено.")
                    break
                try:
                    cards = fetch(page, season=season, kinds=kinds,
                                  score=int(self.s.score_from),
                                  genres_exclude=self.s.genres_exclude,
                                  order=self.FULL_ORDER)
                except AnimePackApiError as e:
                    self.log(f"Shikimori: {e} — беру, что успел набрать")
                    break
                if not cards:
                    break                 # каталог по этим фильтрам кончился
                fresh = 0
                for card in cards:
                    try:
                        mal = int(card.get("malId") or card.get("id") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not mal or mal in seen:
                        continue
                    seen.add(mal)
                    ids.append(mal)
                    cache[mal] = card
                    fresh += 1
                self.db_cache.add_cards(target, sig, cards)
                self.log(f"Каталог Shikimori: набрано {len(ids)} {what}…")
                if fresh == 0:
                    break                 # страница без новых id — дальше пусто
        finally:
            self.db_cache.save()
        return ids

    def _animes_by_ids(self, ids) -> list[dict]:
        """Карточки аниме с оглядкой на кэш: то, что уже приехало из каталога
        Shikimori (order: random), второй раз не запрашиваем."""
        ids = [int(i) for i in ids]
        cached = [self._card_cache[i] for i in ids if i in self._card_cache]
        rest = [i for i in ids if i not in self._card_cache]
        if not rest:
            return cached
        return cached + self.shikimori.animes_by_ids(rest)

    def _mangas_by_ids(self, ids) -> list[dict]:
        """То же для карточек манги/ранобэ (свой кэш: id манги и аниме на MAL
        считаются отдельно и запросто совпадают)."""
        ids = [int(i) for i in ids]
        cached = [self._manga_cache[i] for i in ids if i in self._manga_cache]
        rest = [i for i in ids if i not in self._manga_cache]
        if not rest:
            return cached
        return cached + self.shikimori.mangas_by_ids(rest)

    # ── шаг 2: кандидаты ──────────────────────────────────────────────────
    def iter_candidates(self) -> Iterator[SongCandidate]:
        """Все кандидаты пака: аниме и (если есть их доля) манга вперемешку.

        Два потока идут не подряд, а по очереди, взвешенной по квотам: иначе
        манга набралась бы только после того, как кончатся аниме, и при
        нехватке кандидатов её доля не собралась бы вовсе."""
        quotas = self.s.question_quotas
        manga_need = int(quotas.get(MANGA_KIND, 0))
        anime_need = sum(v for k, v in quotas.items() if k != MANGA_KIND)
        streams = []
        if anime_need > 0:
            streams.append((self._iter_anime_candidates(), max(1, anime_need)))
        if manga_need > 0:
            streams.append((self._iter_manga_candidates(), manga_need))
        if len(streams) == 1:
            yield from streams[0][0]
            return
        yield from self._merge_streams(streams)

    @staticmethod
    def _merge_streams(streams) -> Iterator[SongCandidate]:
        """Тянет из нескольких потоков по очереди, взвешенной по их весам
        (тот же дележ Д'Ондта, что и у долей списков)."""
        live = [[it, float(weight), 0] for it, weight in streams if weight > 0]
        while live:
            row = max(live, key=lambda r: r[1] / (r[2] + 1))
            cand = next(row[0], None)
            if cand is None:
                live.remove(row)
                continue
            row[2] += 1
            yield cand

    def _iter_manga_candidates(self) -> Iterator[SongCandidate]:
        """Кандидаты-вопросы по манге/манхве/ранобэ.

        Песен и кадров у книги нет, поэтому вопрос — либо портрет персонажа
        (его выберет _download_character уже при загрузке медиа), либо обложка;
        всё остальное — ответ, цена, узнаваемость — считается ровно как у
        аниме: карточка Shikimori у манги устроена так же."""
        pairs = self.collect_manga_ids()
        if not pairs:
            return
        users_by_id = {aid: users for aid, users in pairs}
        used_manga: set[int] = set()
        used_franchise: set[str] = set()
        for batch in _chunks([aid for aid, _ in pairs], SHIKIMORI_BATCH):
            if self.stopped():
                return
            try:
                cards = self._mangas_by_ids([i for i in batch
                                             if i not in used_manga])
            except AnimePackApiError as e:
                self.log(f"Shikimori (манга): {e} — пропускаю пачку")
                continue
            self._load_franchise_indexes(cards)
            for card in cards:
                if self.stopped():
                    return
                try:
                    mal = int(card.get("malId") or 0)
                except (TypeError, ValueError):
                    continue
                if not mal:
                    continue
                if not self._accept_anime(card, mal, used_manga, used_franchise,
                                          manga=True):
                    continue
                yield SongCandidate(song={}, anime=card, kind=MANGA_KIND,
                                    media="manga",
                                    users=list(users_by_id.get(mal, [])),
                                    franchise_index=self._franchise_index(card),
                                    compress_images=self.s.compress_images)

    def _iter_anime_candidates(self) -> Iterator[SongCandidate]:
        """Лениво выдаёт песни, прошедшие все фильтры, с учётом дублей."""
        pairs = self.collect_anime_ids()
        if not pairs:
            return
        users_by_id = {aid: users for aid, users in pairs}
        ids = [aid for aid, _ in pairs]

        used_anime: set[int] = set()
        used_franchise: set[str] = set()

        # Пак без единого песенного вопроса до AnisongDB не доходит вовсе:
        # кадры, пиксели, персонажи, анаграммы и сюжеты берутся прямо с
        # карточек Shikimori. Отдаём кандидатов первым же родом вопроса — если
        # их несколько, _pick_kind сам переставит род по недобранным квотам.
        # Манга сюда не попадает: у неё свой поток (_iter_manga_candidates).
        silent = [k for k in self.s.silent_kinds if k != MANGA_KIND]
        if not self.s.songs_percent and silent:
            yield from self._iter_picture_candidates(
                silent[0], ids, users_by_id, used_anime, used_franchise)
            return
        # (ниже используется тот же набор проверок, что и в режиме кадров:
        #  _accept_anime добавляет тайтл в used_* и режет дубли/сложность)

        for batch in _chunks(ids, ANISONG_BATCH):
            if self.stopped():
                return
            self.log(f"AnisongDB: спрашиваю песни для {len(batch)} аниме…")
            try:
                if self._ids_are_ann:
                    songs = self.anisong.songs_by_ann_ids(batch)
                else:
                    songs = self.anisong.songs_by_mal_ids(batch)
            except AnimePackApiError as e:
                self.log(f"AnisongDB: {e} — пропускаю пачку")
                continue
            songs = [s for s in songs if filter_song(s, self.s)]
            if not songs:
                continue
            self.rng.shuffle(songs)

            by_mal: dict[int, list[dict]] = {}
            for song in songs:
                try:
                    mal = int((song.get("linked_ids") or {})["myanimelist"])
                except (KeyError, TypeError, ValueError):
                    continue
                if not self.s.dup_anime and mal in used_anime:
                    continue
                by_mal.setdefault(mal, []).append(song)
            if not by_mal:
                continue

            for sub in _chunks(list(by_mal), SHIKIMORI_BATCH):
                if self.stopped():
                    return
                try:
                    animes = self._animes_by_ids(sub)
                except AnimePackApiError as e:
                    self.log(f"Shikimori: {e} — пропускаю пачку")
                    continue
                self._load_franchise_indexes(animes)
                for anime in animes:
                    if self.stopped():
                        return
                    try:
                        mal = int(anime.get("malId") or 0)
                    except (TypeError, ValueError):
                        continue
                    if mal not in by_mal:
                        continue
                    if not self._accept_anime(anime, mal, used_anime,
                                              used_franchise):
                        continue
                    picked = by_mal[mal] if self.s.dup_anime else by_mal[mal][:1]
                    for song in picked:
                        yield SongCandidate(
                            song=song, anime=anime,
                            users=list(users_by_id.get(mal, [])),
                            kind=song_kind(song.get("songType")) or "opening",
                            trim_start=self._trim_start(song),
                            franchise_index=self._franchise_index(anime),
                            compress_audio=self.s.compress_audio,
                            compress_images=self.s.compress_images)

    @property
    def _random_source(self) -> str:
        """Откуда брать случайные тайтлы на самом деле.

        Мастер-лист AMQ — это список тайтлов, у которых есть песни в AMQ, и
        больше он ни о чём не знает. Поэтому пакам без песен (кадры, персонажи)
        он не годится: база для них всегда Shikimori, что бы ни стояло в
        галочках."""
        want = str(self.s.random_source or "shikimori")
        if want == "amq" and not self.s.has_songs:
            return "shikimori"
        return want

    @property
    def _ids_are_ann(self) -> bool:
        """Мастер-лист AMQ хранит ANN id; списки людей и каталог Shikimori —
        MAL id. От этого зависит, каким запросом спрашивать AnisongDB."""
        return bool(self.s.random_pool and self._random_source != "shikimori")

    def _iter_picture_candidates(self, kind, ids, users_by_id, used_anime,
                                 used_franchise) -> Iterator[SongCandidate]:
        """Кандидаты для пака без единой песни: кадры, пиксели, персонажи,
        анаграммы, сюжет. Вопросом служит картинка или текст, и AnisongDB такому
        паку не нужен вовсе.

        Списки людей и каталог Shikimori дают MAL id сразу, поэтому AnisongDB
        там не нужен вовсе. А мастер-лист AMQ хранит ANN id, и перевести их в
        MAL умеет только AnisongDB — тогда пачка всё равно идёт через него, но
        уже без фильтров по песням."""
        for batch in _chunks(ids, ANISONG_BATCH):
            if self.stopped():
                return
            if self._ids_are_ann:
                self.log(f"AnisongDB: перевожу {len(batch)} id в MAL…")
                try:
                    songs = self.anisong.songs_by_ann_ids(batch)
                except AnimePackApiError as e:
                    self.log(f"AnisongDB: {e} — пропускаю пачку")
                    continue
                mal_ids, seen = [], set()
                for song in songs:
                    try:
                        mal = int((song.get("linked_ids") or {})["myanimelist"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if mal in seen or mal in used_anime:
                        continue
                    seen.add(mal)
                    mal_ids.append(mal)
            else:
                mal_ids = [i for i in batch if i not in used_anime]
            if not mal_ids:
                continue

            for sub in _chunks(mal_ids, SHIKIMORI_BATCH):
                if self.stopped():
                    return
                try:
                    animes = self._animes_by_ids(sub)
                except AnimePackApiError as e:
                    self.log(f"Shikimori: {e} — пропускаю пачку")
                    continue
                self._load_franchise_indexes(animes)
                for anime in animes:
                    if self.stopped():
                        return
                    try:
                        mal = int(anime.get("malId") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not mal:
                        continue
                    if not self._accept_anime(anime, mal, used_anime,
                                              used_franchise):
                        continue
                    yield SongCandidate(song={}, anime=anime, kind=kind,
                                        users=list(users_by_id.get(mal, [])),
                                        franchise_index=self._franchise_index(anime),
                                        compress_images=self.s.compress_images)

    # ── общие проверки тайтла (оба потока кандидатов) ─────────────────────
    def _load_franchise_indexes(self, animes: list) -> None:
        """Догружает узнаваемость франшиз для пачки карточек.

        Части франшизы (до FRANCHISE_PARTS штук по убыванию популярности)
        спрашиваются один раз на все генерации — дальше они лежат в кэше на
        диске. Из них считается индекс серии целиком: самая популярная часть
        плюс надбавка за живые сезоны и послабление по году, если у старого
        тайтла есть заметное продолжение (franchise_parts_index)."""
        need = {str(a.get("franchise") or "").strip()
                for a in animes if isinstance(a, dict)}
        need = {f for f in need if f and f not in self._fr_index}
        if not need:
            return
        fresh: dict[str, list] = {}
        ask = set()
        for key in need:
            known = self.db_cache.franchise(key)
            if known is None:
                ask.add(key)
            else:
                fresh[key] = known
        if ask:
            try:
                loaded = self.shikimori.franchise_parts(sorted(ask))
            except Exception as e:  # noqa: BLE001 — без этого пак всё равно соберётся
                self.log(f"Узнаваемость франшиз не загрузилась: {e}")
                loaded = {}
            # В кэш идут ТОЛЬКО те франшизы, про которые сервер и правда
            # ответил (пустой список — тоже ответ: «частей нет»). Про молчание
            # не запоминаем ничего: разовый обрыв связи иначе навсегда осел бы
            # в кэше нулевой узнаваемостью.
            got = {key: list(rows) for key, rows in (loaded or {}).items()
                   if key in ask}
            self.db_cache.add_franchises(got)
            self.db_cache.save()
            fresh.update(got)
        for key in need:
            self._fr_index[key] = franchise_parts_index(fresh.get(key) or [])

    def _franchise_index(self, anime: dict) -> float:
        return self._fr_index.get(str(anime.get("franchise") or "").strip(), 0.0)

    def _accept_anime(self, anime: dict, mal: int, used_anime: set,
                      used_franchise: set, manga: bool = False) -> bool:
        """Годится ли тайтл: фильтры, дубли и сложность. Принятый сразу
        помечается использованным."""
        self._seen_titles += 1
        if not self.s.dup_anime and mal in used_anime:
            self._skips["тайтл уже брали"] += 1
            return False
        if not filter_anime(anime, self.s, manga=manga):
            self._skips["фильтры (тип, год, оценка, жанры)"] += 1
            return False
        fkey = franchise_key(anime)
        # Корень названия — вторая линия обороны от дублей серии: у свежих
        # тайтлов Shikimori иногда не проставил franchise, и тогда «Доктор
        # Стоун: Научное будущее. Часть 3» проскакивал мимо проверки франшизы.
        root = title_root(anime.get("russian") or anime.get("name"))
        if self._excluded_roots:
            # Франшизы, уже спрошенные в чужих паках (галочка «не повторять»).
            for name in (anime.get("russian"), anime.get("name"),
                         anime.get("english")):
                rt = title_root(name)
                if rt and rt in self._excluded_roots:
                    self._skips["уже спрашивали в чужих паках"] += 1
                    return False
        if not self.s.dup_franchise:
            if fkey in used_franchise:
                self._skips["франшиза уже в паке"] += 1
                return False
            if root and root in used_franchise:
                self._skips["франшиза уже в паке"] += 1
                return False
        # Сложность считаем через карточку-пустышку: там year/score разбираются
        # безопасно, и величина получается ровно та же, что у кандидата.
        probe = SongCandidate(song={}, anime=anime,
                              franchise_index=self._franchise_index(anime))
        if not (self.s.level_min <= probe.level <= self.s.level_max):
            self._skips["рамки сложности пака"] += 1
            return False
        self._good_titles += 1
        used_anime.add(mal)
        used_franchise.add(fkey)
        if root:
            used_franchise.add(root)
        return True

    def _trim_start(self, song: dict) -> int:
        """Случайная точка старта отрезка. Короткую песню берём с начала —
        в ASPG получалось отрицательное смещение."""
        try:
            length = float(song.get("songLength") or 0.0)
        except (TypeError, ValueError):
            length = 0.0
        latest = int(length) - int(self.s.audio_cut)
        if latest <= 0:
            return 0
        return self.rng.randint(0, latest)

    # ── шаг 3: медиа ──────────────────────────────────────────────────────
    def prepare_dirs(self) -> str:
        self.folder = tempfile.mkdtemp(prefix="sihyx_animepack_")
        for sub in ("Audio", "Images", "Video"):
            os.makedirs(os.path.join(self.folder, sub), exist_ok=True)
        return self.folder

    def _get_bytes(self, url: str, timeout=(10, 90)) -> bytes:
        last: Optional[Exception] = None
        for attempt in range(_DOWNLOAD_RETRIES + 1):
            if self.stopped():
                raise AnimePackError("Остановлено")
            try:
                resp = self.session.get(url, timeout=timeout)
                resp.raise_for_status()
                return resp.content
            except Exception as e:  # noqa: BLE001 — любая сетевая беда
                last = e
                if attempt < _DOWNLOAD_RETRIES:
                    time.sleep(0.8 * (attempt + 1))
        raise AnimePackError(str(last))

    @staticmethod
    def audio_filters(duration: float) -> str:
        """Цепочка `-af` для отрезка песни — та же, что в «Обработке»:
        нормализация громкости (loudnorm), затухание в конце и фикс раскладки
        каналов под libopus. Отсчёт от нуля: вход режется input-seek'ом, так что
        фильтры видят уже обнулённое время."""
        fade_at = max(0.0, float(duration) - AUDIO_FADE_OUT)
        return ",".join([
            f"loudnorm=I={AUDIO_LOUDNORM_I}:LRA={AUDIO_LOUDNORM_LRA}"
            f":TP={AUDIO_LOUDNORM_TP}",
            f"afade=t=out:st={fade_at:.3f}:d={AUDIO_FADE_OUT}",
            OPUS_LAYOUT_FIX,
        ])

    @classmethod
    def opus_args(cls, duration: float) -> list[str]:
        """Opus 192 кбит с нормализацией и затуханием — единственный способ,
        которым в паке кодируется звук: и отрезок песни, и дорожка ролика."""
        return ["-af", cls.audio_filters(duration),
                "-c:a", "libopus", "-b:a", AUDIO_BITRATE,
                "-vbr", "on", "-application", "audio"]

    def audio_encode_args(self, duration: float) -> list[str]:
        """Чем кодировать отрезок. Со сжатием — opus 192 кбит с нормализацией,
        без — поток копируется как есть: mp3 с CDN попадает в пак ровно в том
        качестве, в каком его отдал сервер, без единого перекодирования."""
        if not self.s.compress_audio:
            return ["-c:a", "copy"]
        return self.opus_args(duration)

    def _run_killable(self, cmd, timeout: float = 180.0) -> tuple[int, str]:
        """Запускает ffmpeg так, чтобы «Стоп» останавливал вкладку СРАЗУ.

        subprocess.run() ждал бы конца кодирования (секунды на каждый вопрос, а
        их качается parallel штук разом) — из-за этого кнопка «Стоп» и казалась
        залипшей. Здесь процесс живёт в реестре self._procs: stop_processes()
        убивает всё разом, а цикл ожидания просыпается каждые 0,2 с и сам
        проверяет флаг остановки."""
        code, _out, err = self._run_capture(cmd, timeout)
        return code, err

    def _run_capture(self, cmd, timeout: float = 180.0) -> tuple[int, str, str]:
        """То же самое, но с выводом процесса: ffprobe отвечает в stdout, а
        ffmpeg — в stderr, реестр процессов и «Стоп» им нужны одинаково."""
        kw = {"creationflags": CREATE_NO_WINDOW} if os.name == "nt" else {}
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, **kw)
        except Exception as e:  # noqa: BLE001
            return 1, "", str(e)
        with self._procs_lock:
            self._procs.add(proc)
        deadline = time.monotonic() + max(1.0, float(timeout))
        try:
            while True:
                try:
                    out, err = proc.communicate(timeout=0.2)
                    return (proc.returncode,
                            (out or b"").decode("utf-8", "replace"),
                            (err or b"").decode("utf-8", "replace"))
                except subprocess.TimeoutExpired:
                    pass
                if self.stopped() or time.monotonic() > deadline:
                    self._kill(proc)
                    try:
                        proc.communicate(timeout=5)
                    except Exception:  # noqa: BLE001
                        pass
                    return 1, "", "остановлено"
        finally:
            with self._procs_lock:
                self._procs.discard(proc)

    @staticmethod
    def _kill(proc) -> None:
        try:
            proc.kill()
        except Exception:  # noqa: BLE001 — процесс мог уже завершиться
            pass

    def stop_processes(self) -> None:
        """Убивает все запущенные ffmpeg (зовётся по «Стоп» и при уборке)."""
        with self._procs_lock:
            procs = list(self._procs)
        for proc in procs:
            self._kill(proc)

    def download_audio(self, cand: SongCandidate) -> bool:
        """Качает mp3 с CDN AMQ и режет его ffmpeg-ом до нужной длины."""
        name = cand.audio_file
        if not name:
            return False
        final = os.path.join(self.folder, "Audio", cand.audio_out)
        if os.path.exists(final):
            return True
        raw = os.path.join(self.folder, "Audio", f"_tmp_{name}")
        try:
            data = self._get_bytes(f"{AMQ_CDN}/{name}")
            if len(data) < _MIN_AUDIO_BYTES:
                raise AnimePackError("файл подозрительно мал")
            with open(raw, "wb") as f:
                f.write(data)
            try:
                length = float(cand.song.get("songLength") or 0.0)
            except (TypeError, ValueError):
                length = 0.0
            duration = self.s.audio_cut
            if length:
                duration = min(duration, max(1, int(length - cand.trim_start)))
            cmd = ([FFMPEG, "-y", "-loglevel", "error",
                    "-ss", str(int(cand.trim_start)), "-i", raw,
                    "-t", str(int(duration)), "-vn"]
                   + self.audio_encode_args(duration) + [final])
            code, err = self._run_killable(cmd, timeout=180)
            if code != 0 or not os.path.exists(final):
                if self.stopped():
                    return False
                raise AnimePackError((err or "ffmpeg не справился").strip()[:200])
            return True
        except Exception as e:  # noqa: BLE001
            self.log(f"Не вышло со звуком «{cand.title_ru}»: {e}")
            try:
                if os.path.exists(final):
                    os.remove(final)
            except OSError:
                pass
            return False
        finally:
            try:
                if os.path.exists(raw):
                    os.remove(raw)
            except OSError:
                pass

    @staticmethod
    def _url_ext(url, default: str = ".jpg") -> str:
        """Расширение картинки по ссылке (без ?query). Незнакомое — .jpg."""
        ext = os.path.splitext(str(url or "").split("?")[0])[1].lower()
        return ext if ext in (".jpg", ".jpeg", ".png", ".webp", ".gif") else default

    def _save_image(self, data: bytes, base: str, src_ext: str = ".jpg") -> str:
        """Кладёт картинку в Images/ и возвращает её имя внутри пака («» — не
        вышло). Со сжатием это AVIF под лимит (кодирование общее с «Обработкой»),
        без — исходные байты как есть: ни ужимания, ни перекодирования."""
        if self.s.compress_images:
            name = f"{base}.avif"
            return name if self._to_avif(data, name, src_ext) else ""
        name = f"{base}{src_ext}"
        with open(os.path.join(self.folder, "Images", name), "wb") as f:
            f.write(data)
        return name

    def _to_avif(self, data: bytes, out_name: str, src_ext: str = ".jpg") -> bool:
        """Кладёт скачанную картинку в Images/<out_name> как AVIF ≤ лимита.

        Кодирование — общее с «Обработкой» (avif_fit: libaom, tune=iq, подбор
        CQ под размер, при нужде ужимание разрешения)."""
        raw = os.path.join(self.folder, "Images", f"_tmp_{uuid.uuid4().hex}{src_ext}")
        out = os.path.join(self.folder, "Images", out_name)
        try:
            with open(raw, "wb") as f:
                f.write(data)
            limit = max(10, int(self.s.image_limit_kb))
            # Стартовый CQ считаем сами: проба с CQ=0 (самая медленная) для
            # такого лимита промахивается на порядок и уходит впустую. Плюс
            # заранее ужимаем гигантские постеры Shikimori — на экране SIGame
            # больше IMAGE_MAX_SIDE всё равно не видно, а время кодирования
            # почти прямо пропорционально числу пикселей.
            try:
                from config import Image
                with Image.open(raw) as im:
                    w, h = im.size
                # Считаем по размеру ПОСЛЕ предварительного ужимания: кодировать
                # будут уже его, а от числа пикселей оценка и зависит.
                if max(w, h) > IMAGE_MAX_SIDE:
                    k = IMAGE_MAX_SIDE / float(max(w, h))
                    w, h = max(1, int(w * k)), max(1, int(h * k))
                start = start_cq_guess(w, h, limit)
            except Exception:  # noqa: BLE001 — без Pillow просто идём как раньше
                start = None
            return fit_to_limit(raw, out, limit,
                                speed=max(0, min(8, int(self.s.image_speed))),
                                passes=IMAGE_FIT_PASSES,
                                start_cq=start, max_side=IMAGE_MAX_SIDE,
                                should_stop=self._should_stop)
        finally:
            try:
                if os.path.exists(raw):
                    os.remove(raw)
            except OSError:
                pass

    # ── персонажи ─────────────────────────────────────────────────────────
    def _pick_character(self, cand: SongCandidate) -> None:
        """Выбирает персонажа для вопроса (и уводит ответ на первый тайтл).

        Персонажи спрашиваются по тайтлу прямо здесь, а не на этапе отбора:
        characterRoles — тяжёлое поле, и тянуть его для всех кандидатов подряд
        (а в пак попадает малая их часть) вышло бы дороже, чем взять по одному
        запросу на реально нужный вопрос."""
        if (cand.kind == MANGA_KIND
                and str(self.s.manga_question or "character") != "character"):
            return                       # вопрос по манге — обложка, не персонаж
        manga = cand.is_manga
        try:
            rows = self.shikimori.characters_by_anime_ids(
                [cand.mal_id], target="manga" if manga else "anime").get(
                    cand.mal_id, [])
        except AnimePackApiError as e:
            self.log(f"Персонажи «{cand.title_ru}»: {e}")
            return
        role = str(self.s.char_roles or "both").lower()
        if role == "main":
            rows = [r for r in rows if r.get("main")]
        elif role == "supporting":
            rows = [r for r in rows if not r.get("main")]
        # Персонажа с иероглифическим именем не спросить: игрок его не наберёт.
        rows = [r for r in rows if not has_cjk(r.get("name"))]
        # Одного и того же персонажа два раза в пак не пускаем (Shikimori
        # держит сквозные id — совпадения ловятся даже между сиквелами).
        with self._frames_lock:
            free = [r for r in rows
                    if f"char:{r.get('id')}" not in self._frames_used]
            if not free:
                if rows:
                    self.log(f"«{cand.title_ru}»: подходящих персонажей не "
                             "осталось — беру следующий тайтл")
                return
            row = self.rng.choice(free)
            self._frames_used.add(f"char:{row.get('id')}")
        cand.character = dict(row)
        cand.char_favorites = self._char_favorites(row.get("id"))
        # _use_first_title здесь НЕ зовём: это ещё один-два запроса к Shikimori,
        # а кандидата вот-вот могут отвергнуть по средней сложности (см.
        # _fetch_media). Сначала проверка, потом уже поиск первого тайтла.

    def _char_favorites(self, char_id) -> int:
        """Сколько человек добавили персонажа в избранное (−1 — не узнали).

        Это вторая мера сложности вопроса-персонажа помимо узнаваемости тайтла
        (просьба пользователя): чем больше добавивших, тем персонаж легче. Одна
        страница на вопрос — а вопросов-персонажей в паке единицы."""
        if not char_id:
            return -1
        getter = getattr(self.shikimori, "character_favorites", None)
        if getter is None:
            return -1
        try:
            return int(getter(char_id))
        except Exception:  # noqa: BLE001 — мера полезная, но не обязательная
            return -1

    def _download_character(self, cand: SongCandidate) -> None:
        """Портрет выбранного персонажа — сам вопрос «угадай персонажа»."""
        row = cand.character or {}
        url = str(row.get("poster") or "")
        if not url:
            return
        cand.frame_url = url
        # Портрет тоже лежит в общей кладовой: один и тот же герой попадается в
        # паках раз за разом, а картинка у него не меняется.
        key = poster_cache.character_key(row.get("id"))
        use_cache = bool(getattr(self.s, "poster_cache", True)) and bool(key)
        data, ext = (poster_cache.find(key) if use_cache else (b"", ""))
        try:
            if not data:
                data, ext = self._get_bytes(url), self._url_ext(url)
                if use_cache:
                    poster_cache.put(key, data, ext)
            name = self._save_image(data, f"{cand.file_base}_frame", ext)
            cand.frame_name = name or cand.frame_name
            cand.has_frame = bool(name)
        except Exception as e:  # noqa: BLE001
            self.log(f"Портрет «{row.get('name')}» не скачался: {e}")

    def _frame_urls(self, anime: dict) -> list[str]:
        """Все ссылки на кадры тайтла.

        Основной источник — скриншоты Shikimori, к ним всегда добавляются
        превью серий AniList (по кадру на серию, с легальных стримингов) и
        Kitsu (тоже по серии): сцены получаются разные, а один и тот же тайтл в
        разных паках выглядит по-новому. Отдельной галочки для этого больше нет
        — лишняя пара запросов на вопрос того стоит."""
        out = []
        for shot in (anime.get("screenshots") or []):
            url = (shot or {}).get("originalUrl") or (shot or {}).get("x332Url")
            if url:
                out.append(str(url))
        try:
            mal = int(anime.get("malId") or 0)
        except (TypeError, ValueError):
            mal = 0
        if not mal:
            return out
        for api in (self.anilist, self.kitsu):
            if self.stopped():
                break
            try:
                out.extend(api.frames(mal))
            except Exception:  # noqa: BLE001 — доп. источник, молча пропускаем
                continue
        # Порядок сохраняем, дубли убираем: AniList и Kitsu иногда отдают одно
        # и то же превью с общего CDN.
        seen, uniq = set(), []
        for url in out:
            key = frame_url_key(url)
            if key and key not in seen:
                seen.add(key)
                uniq.append(url)
        return uniq

    def _pick_frame_url(self, cand: SongCandidate) -> str:
        """Какой скриншот станет вопросом-кадром («» — годного нет).

        Кадр всегда случайный, а не первый: один и тот же тайтл в разных паках
        спрашивается разными сценами (настройки для этого больше нет — первый
        кадр никому не был нужен). Уже показанные кадры пропускаются — в этом
        паке всегда, а с галочкой «не повторять» ещё и те, что были в прошлых.
        Если у тайтла свободных кадров не осталось, вопроса не будет вовсе: пак
        возьмёт следующий тайтл."""
        urls = self._frame_urls(cand.anime)
        if not urls:
            return ""
        with self._frames_lock:
            free = [u for u in urls if frame_url_key(u) not in self._frames_used]
            if not free:
                if self.s.frames_no_repeat:
                    return ""
                free = urls          # в пределах пака повторов и так не будет
            url = self.rng.choice(free)
            self._frames_used.add(frame_url_key(url))
        return url

    def save_frames_history(self, songs: list) -> None:
        """Запоминает кадры собранного пака, чтобы они не повторились в
        следующем. Пишется только при включённой галочке и только по вопросам,
        реально попавшим в пак."""
        if not self.s.frames_no_repeat:
            return
        # Вопрос-пиксели тоже помнится: там тот же самый кадр, просто поданный
        # роликом — картинки в Images/ у него нет, поэтому «дошло до пака»
        # означает не has_frame, а собранный ролик.
        fresh = [frame_url_key(c.frame_url) for c in songs
                 if c.frame_url and ((c.kind == FRAME_KIND and c.has_frame)
                                     or (c.is_pixel and c.has_video))]
        if not fresh:
            return
        old = [frame_url_key(u) for u in load_frame_history(self.frames_history_path)]
        seen, merged = set(), []
        for url in old + fresh:
            if url and url not in seen:
                seen.add(url)
                merged.append(url)
        if save_frame_history(merged, self.frames_history_path):
            self.log(f"Кадров в памяти «не повторять»: {len(merged)} "
                     f"(+{len(fresh)})")
        else:
            self.log("Не вышло запомнить кадры пака — в следующий раз они "
                     "могут повториться.")

    # ── обложки: общая кладовая → Shikimori → TMDB ────────────────────────
    def _poster_bytes(self, cand: SongCandidate, url: str) -> tuple[bytes, str]:
        """Исходные байты обложки тайтла и её расширение (b"", "" — нет никакой).

        Три источника по очереди, и первый же годный побеждает:
          1. общая кладовая на диске (poster_cache) — обложка тайтла не меняется
             годами, а качают её и генератор, и «Апгрейд пака»;
          2. постер карточки Shikimori — основной источник;
          3. themoviedb.org — запасной, по ключу из настроек: у свежих ONA,
             спешлов и редкой манги постера в карточке Shikimori попросту нет.

        Скачанное сразу кладётся в кладовую — в том виде, в каком приехало:
        ужимает его каждая вкладка под свой лимит сама."""
        key = poster_cache.anime_key(cand.mal_id, book=cand.is_manga)
        use_cache = bool(getattr(self.s, "poster_cache", True)) and bool(key)
        if use_cache:
            data, ext = poster_cache.find(key)
            if data:
                with self._poster_lock:
                    self._poster_hits += 1
                return data, ext
        data, ext = b"", ".jpg"
        if url:
            try:
                data, ext = self._get_bytes(url), self._url_ext(url)
            except Exception as e:  # noqa: BLE001 — есть ещё TMDB
                if not self.stopped():
                    self._log_rare("Постер",
                                   f"Постер «{cand.title_ru}» не скачался: {e}")
        if not data and not self.stopped():
            data, ext = self._tmdb_poster(cand)
        if data and use_cache:
            poster_cache.put(key, data, ext)
        return data, ext

    def _tmdb_poster(self, cand: SongCandidate) -> tuple[bytes, str]:
        """Обложка с themoviedb.org (b"", "" — ключа нет или тайтл не нашёлся).

        Манга там бывает редко, но обложку томика TMDB иногда всё же знает — по
        экранизации; пробуем и её, хуже от этого не будет."""
        tmdb = getattr(self, "tmdb", None)
        if tmdb is None or not tmdb.enabled:
            return b"", ""
        names = [cand.anime.get("name"), cand.anime.get("english"),
                 cand.title_ru]
        names = [n for n in (str(x or "").strip() for x in names) if n]
        if not names:
            return b"", ""
        movie = str(cand.anime.get("kind") or "") == "movie"
        try:
            url = tmdb.poster_url(names, year=cand.year, movie=movie)
        except AnimePackApiError as e:
            self._log_rare("TMDB", f"TMDB: {e}")
            return b"", ""
        if not url:
            return b"", ""
        try:
            data = self._get_bytes(url)
        except Exception as e:  # noqa: BLE001
            self._log_rare("TMDB", f"Обложка с TMDB не скачалась: {e}")
            return b"", ""
        with self._poster_lock:
            self._poster_tmdb += 1
        return data, self._url_ext(url)

    def download_images(self, cand: SongCandidate) -> None:
        """Постер (в ответ), кадр (сам вопрос в режиме кадров) и коллаж 2×2 из
        скриншотов (поверх песни).

        Провал картинки не отменяет вопрос: просто не будет соответствующего
        элемента в XML (в ASPG ссылка оставалась и пак ломался). Исключение —
        кадр в режиме «только кадры»: без него вопроса нет вовсе."""
        from PIL import Image  # локально: Pillow нужен только здесь
        import io

        poster_url = (cand.anime.get("poster") or {}).get("originalUrl")
        data, ext = self._poster_bytes(cand, str(poster_url or ""))
        if data:
            try:
                name = self._save_image(data, f"{cand.file_base}_poster", ext)
                cand.poster_name = name or cand.poster_name
                cand.has_poster = bool(name)
            except Exception as e:  # noqa: BLE001
                self.log(f"Постер «{cand.title_ru}» не сохранился: {e}")

        shots = list(cand.anime.get("screenshots") or [])
        if cand.is_text:
            # Анаграмме и вопросу по сюжету картинка не нужна вовсе: весь вопрос
            # — текст, а постер для ответа уже скачан выше.
            return
        if cand.is_character:
            self._download_character(cand)
            return
        if cand.kind == MANGA_KIND:
            # Вопрос по манге без персонажа — это обложка. Второй раз её качать
            # незачем: постер уже лежит в паке, он же и станет картинкой вопроса.
            cand.frame_url = str(poster_url or "")
            cand.frame_name = cand.poster_name
            cand.has_frame = bool(cand.poster_name)
            if not cand.has_frame:
                self.log(f"Обложка «{cand.title_ru}» не скачалась")
            return
        if cand.is_pixel:
            # Кадр вопроса-пикселей уже стал роликом (download_pixel) — второй
            # раз качать его в Images/ незачем.
            return
        if cand.is_frame:
            url = self._pick_frame_url(cand)
            if not url:
                if shots:
                    self.log(f"«{cand.title_ru}»: все кадры уже были в прошлых "
                             "паках — беру следующий тайтл")
                return
            cand.frame_url = url
            try:
                name = self._save_image(self._get_bytes(url),
                                        f"{cand.file_base}_frame",
                                        self._url_ext(url))
                cand.frame_name = name or cand.frame_name
                cand.has_frame = bool(name)
            except Exception as e:  # noqa: BLE001
                self.log(f"Кадр «{cand.title_ru}» не скачался: {e}")
            return

        if not self.s.images:
            return
        self.rng.shuffle(shots)
        tiles = []
        for shot in shots:
            if len(tiles) >= COLLAGE_IMAGES:
                break
            url = (shot or {}).get("originalUrl") or (shot or {}).get("x332Url")
            if not url:
                continue
            try:
                tile = Image.open(io.BytesIO(self._get_bytes(url))).convert("RGB")
                tiles.append(tile.resize(COLLAGE_CELL, Image.LANCZOS))
            except Exception:  # noqa: BLE001 — попробуем следующий скриншот
                continue
        if len(tiles) < COLLAGE_IMAGES:
            self.log(f"Коллаж «{cand.title_ru}» пропущен: скриншотов не хватило")
            return
        try:
            collage = Image.new("RGB", COLLAGE_SIZE, (0, 0, 0))
            cw, ch = COLLAGE_CELL
            for i, tile in enumerate(tiles):
                collage.paste(tile, ((i % 2) * cw, (i // 2) * ch))
            buf = io.BytesIO()
            collage.save(buf, "PNG")
            name = self._save_image(buf.getvalue(), cand.file_base, ".png")
            cand.collage_name = name or cand.collage_name
            cand.has_collage = bool(name)
        except Exception as e:  # noqa: BLE001
            self.log(f"Коллаж «{cand.title_ru}» не собрался: {e}")

    # ── видео с AnimeThemes ───────────────────────────────────────────────
    def _theme_video(self, cand: SongCandidate) -> str:
        """Ссылка на ролик именно этой песни («» — не нашлось).

        Ищем по MAL id и метке «OP1»/«ED2»: в AnisongDB та же песня зовётся
        «Opening 1», перевод делает song_tag. OST на AnimeThemes не лежат
        вовсе, поэтому для них сразу пусто."""
        mal = cand.mal_id
        tag = cand.tag.replace(" ", "").upper()
        if not mal or not tag or cand.base_kind == "insert":
            return ""
        with self._themes_lock:
            known = self._themes_cache.get(mal)
        if known is None:
            try:
                fresh = self.themes.themes_by_mal_ids([mal])
            except AnimePackApiError as e:
                self.log(f"AnimeThemes: {e}")
                fresh = {}
            with self._themes_lock:
                self._themes_cache[mal] = fresh.get(mal, {})
                known = self._themes_cache[mal]
        row = (known or {}).get(tag) or {}
        return str(row.get("url") or "")

    def video_encode_args(self) -> list[str]:
        """Флаги кодирования ролика — тот же libsvtav1, что в «Обработке»
        (ProcessWorker._svt_args): keyint=-1 и scd=1, ключевые кадры только на
        сменах сцены. Из настроек вкладки берутся crf и пресет, остальное
        оттуда же, что и у «Обработки»."""
        crf = max(0, min(63, int(self.s.video_crf)))
        preset = max(0, min(13, int(self.s.video_preset)))
        return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
                "-svtav1-params", f"tune={VIDEO_TUNE}:keyint=-1:scd=1",
                "-pix_fmt", "yuv420p10le",
                "-vf", f"scale=-2:{VIDEO_HEIGHT}:flags=bicubic"]

    def _video_seconds(self, url: str) -> float:
        """Длительность ролика на сервере AnimeThemes.

        В ответе API её нет (есть только размер и разрешение), поэтому
        спрашиваем ffprobe: он читает заголовки файла Range-запросом, а не
        качает все сорок мегабайт. Ответ кладём в кэш — один и тот же ролик
        может попасться в паке дважды. Не ответил (нет ffprobe, сеть) — ноль,
        и точка старта останется прежней, фиксированной."""
        with self._video_len_lock:
            known = self._video_len.get(url)
        if known is not None:
            return known
        cmd = [FFPROBE, "-v", "error", "-show_entries", "format=duration",
               "-of", "default=noprint_wrappers=1:nokey=1", url]
        # Под тем же замком, что и сама загрузка: CDN отвергает параллельные
        # чтения, а проба — такое же чтение, только короткое.
        with self._video_lock:
            code, out, _err = self._run_capture(cmd, timeout=60)
        try:
            value = float(out.strip()) if code == 0 else 0.0
        except (TypeError, ValueError):
            value = 0.0
        if value < 0:
            value = 0.0
        with self._video_len_lock:
            self._video_len[url] = value
        return value

    def _video_start(self, cand: SongCandidate, url: str, duration: int) -> int:
        """Откуда резать ролик — СЛУЧАЙНАЯ секунда, ровно как у отрезка песни
        (_trim_start): иначе один и тот же опенинг во всех паках начинался бы с
        одной и той же секунды (просьба пользователя).

        Первые секунды опенинга — заставка студии, их пропускаем (VIDEO_LEAD_IN).
        Если длительность узнать не вышло, остаётся прежнее поведение: начало
        ролика со сдвигом на заставку."""
        lead = VIDEO_LEAD_IN if cand.base_kind == "opening" else 0
        total = self._video_seconds(url)
        if total <= 0:
            return lead
        latest = int(total) - int(duration)
        if latest <= lead:
            # Ролик короче отрезка (или почти) — берём его с самого начала,
            # иначе ffmpeg вернул бы пустой файл.
            return max(0, latest)
        return self.rng.randint(lead, latest)

    def download_video(self, cand: SongCandidate) -> bool:
        """Режет ролик прямо с сервера AnimeThemes и кодирует его в пак.

        Файл там весит под полсотни мегабайт, но сервер отдаёт Range (206), и
        ffmpeg с input-seek скачивает только нужные секунды — качать всё
        целиком, чтобы взять пятнадцать секунд, не приходится."""
        url = self._theme_video(cand)
        if not url:
            return False
        cand.video_url = url
        final = os.path.join(self.folder, "Video", cand.video_out)
        duration = max(3, int(self.s.video_cut))
        start = self._video_start(cand, url, duration)
        # Звук ролика кодируется ровно так же, как любой другой звук в паке:
        # opus 192 кбит, нормализация громкости и затухание в конце отрезка
        # (opus_args). Иначе ролик звучал бы заметно громче или тише соседних
        # вопросов-песен.
        def make_cmd(seek: int) -> list[str]:
            return ([FFMPEG, "-y", "-loglevel", "error", "-ss", str(seek),
                     "-i", url, "-t", str(duration)]
                    + self.video_encode_args()
                    + self.opus_args(duration)
                    + ["-movflags", "+faststart", final])

        err = ""
        for attempt in range(VIDEO_RETRIES + 1):
            if self.stopped():
                return False
            # Первая попытка — со случайной секунды; если не вышло, повторяем с
            # начала ролика: вдруг длительность мы угадали неверно и отрезка там
            # попросту нет.
            cmd = make_cmd(start if attempt == 0 else 0)
            # По одному за раз: параллельные чтения CDN отвергает.
            with self._video_lock:
                code, err = self._run_killable(cmd, timeout=600)
            size = os.path.getsize(final) if os.path.exists(final) else 0
            if code == 0 and size >= MIN_VIDEO_BYTES:
                cand.has_video = True
                return True
            # Оборванный вход ffmpeg не считает ошибкой: код ноль, а в файле
            # одни заголовки — поэтому и смотрим на размер, а не только на код.
            try:
                if os.path.exists(final):
                    os.remove(final)
            except OSError:
                pass
            if attempt < VIDEO_RETRIES:
                time.sleep(VIDEO_RETRY_PAUSE * (attempt + 1))
        if not self.stopped():
            self.log(f"Ролик «{cand.title_ru}» не вышел, беру звук: "
                     f"{(err or 'пустой файл').strip()[:160]}")
        return False

    # ── пиксели: кадр, который проявляется ────────────────────────────────
    def pixel_encode_args(self, vf: str) -> list[str]:
        """Флаги кодирования ролика-проявления: тот же libsvtav1 и те же
        crf/пресет, что у вопроса-ролика (video_encode_args) — разница лишь в
        цепочке фильтров, её собирает вызывающий."""
        crf = max(0, min(63, int(self.s.video_crf)))
        preset = max(0, min(13, int(self.s.video_preset)))
        return ["-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
                "-svtav1-params", f"tune={VIDEO_TUNE}:keyint=-1:scd=1",
                "-pix_fmt", "yuv420p10le", "-vf", vf, "-an"]

    def pixel_filter(self) -> str:
        """Цепочка -vf для ролика-проявления: сперва кадр приводится к 720p (в
        паке он всё равно смотрится на экране SIGame), затем идёт та же
        пикселизация, что у кнопки «Пикселизация» во вкладке «Монтаж».

        Порядок нарочно такой: масштабирование ПОСЛЕ пикселизации размыло бы
        блоки, и «крупные пиксели» вышли бы мыльными пятнами."""
        chain = [f"scale=-2:{PIXEL_HEIGHT}"]
        pix = pixelize_filter(max(2, int(self.s.pixel_seconds)),
                              max(1, int(self.s.pixel_steps)),
                              max(2, int(self.s.pixel_block)))
        if pix:
            chain.append(pix)
        return ",".join(chain)

    def download_pixel(self, cand: SongCandidate) -> bool:
        """Собирает вопрос-пиксели: случайный кадр тайтла превращается в ролик,
        который начинается крупными блоками и проясняется к концу.

        Кадр берётся ровно там же, где у обычного вопроса-кадра (те же
        источники и та же память «не повторять»), а видео из него делает ffmpeg
        зацикленной картинкой (-loop 1) — один в один как «Пикселизация» у
        картинки во вкладке «Монтаж»."""
        url = self._pick_frame_url(cand)
        if not url:
            if not self.stopped():
                self.log(f"«{cand.title_ru}»: свободных кадров нет — беру "
                         "следующий тайтл")
            return False
        cand.frame_url = url
        raw = os.path.join(self.folder, "Images",
                           f"_pix_{uuid.uuid4().hex}{self._url_ext(url)}")
        final = os.path.join(self.folder, "Video", cand.video_out)
        try:
            with open(raw, "wb") as f:
                f.write(self._get_bytes(url))
        except Exception as e:  # noqa: BLE001
            self.log(f"Кадр «{cand.title_ru}» не скачался: {e}")
            return False
        dur = max(2, int(self.s.pixel_seconds))
        fps = max(1, min(60, int(self.s.pixel_fps)))
        cmd = ([FFMPEG, "-y", "-loglevel", "error", "-loop", "1",
                "-framerate", str(fps), "-i", raw, "-t", str(dur)]
               + self.pixel_encode_args(self.pixel_filter())
               + ["-movflags", "+faststart", final])
        try:
            code, err = self._run_killable(cmd, timeout=300)
        finally:
            try:
                os.remove(raw)
            except OSError:
                pass
        size = os.path.getsize(final) if os.path.exists(final) else 0
        if code == 0 and size > 0:
            cand.has_video = True
            return True
        if not self.stopped():
            self.log(f"Проявление «{cand.title_ru}» не собралось: "
                     f"{(err or 'пустой файл').strip()[:160]}")
        try:
            if os.path.exists(final):
                os.remove(final)
        except OSError:
            pass
        return False

    # ── анаграмма ─────────────────────────────────────────────────────────
    def build_anagram(self, cand: SongCandidate) -> bool:
        """Перемешивает буквы названия — весь вопрос-анаграмма и есть.

        Ни сети, ни медиа тут не нужно: название уже лежит в карточке
        Shikimori. Не вышло (на выбранном языке названия нет или оно написано
        не той письменностью, оно короче минимума, длиннее потолка либо это
        продолжение с приставкой) — кандидат уступает место следующему
        тайтлу."""
        limit = max(0, int(getattr(self.s, "anagram_max_chars", 0) or 0))
        source = anagram_source(cand.anime, str(self.s.anagram_lang or "russian"),
                                max_chars=limit)
        if not source:
            why = (f", не длиннее {limit} символов" if limit else "")
            self.log(f"«{cand.title_ru}»: под анаграмму нужно простое название "
                     f"на выбранном языке{why} — беру следующий тайтл")
            return False
        cand.anagram = make_anagram(source, self.rng)
        if not cand.anagram:
            self.log(f"«{cand.title_ru}»: из названия анаграммы не выходит")
            return False
        return True

    # ── вопрос по сюжету (Fandom + Gemini) ────────────────────────────────
    def make_plot_question(self, cand: SongCandidate) -> bool:
        """Достаёт пересказ серии с фэндом-вики и делает из него вопрос.

        Вики есть не у всякого тайтла, а раздел с пересказом — не на всякой
        странице: это нормальный ход дел, и такой кандидат просто уступает
        место следующему. А вот беда с ключом или кончившаяся квота Gemini
        отключают этот род вопросов целиком — иначе на каждый следующий тайтл
        в лог валилась бы та же ошибка."""
        # Клиента забираем В МЕСТНУЮ переменную и дальше зовём только его:
        # соседний поток может обнулить self.gemini прямо посреди работы, и
        # тогда в лог сыпалось «'NoneType' object has no attribute
        # generate_json» вместо настоящей причины.
        gemini = self.gemini
        if gemini is None or self.fandom is None:
            # Ключа нет или он уже отвалился: этот род вопросов в прогоне
            # больше не получится вовсе. Кандидат при этом ни в чём не виноват
            # — медиа мы даже не трогали, и «не скачалось» это не считается.
            self._drop_kind(PLOT_KIND)
            cand.rejected = True
            return False
        names = [cand.anime.get("name"), cand.anime.get("english"),
                 cand.title_ru]
        names = [n for n in (str(x or "").strip() for x in names) if n]
        try:
            with self._timed("сюжет"):
                got = pick_plot(self.fandom, names, self.rng)
        except AnimePackApiError as e:
            self._log_rare("Fandom", f"Фэндом-вики: {e}")
            return False
        if not got:
            self._log_rare("Сюжет не найден",
                           f"«{cand.title_ru}»: пересказа на фэндом-вики нет — "
                           "беру следующий тайтл")
            return False
        page = f"{got.get('wiki', '')}|{got.get('page', '')}"
        with self._plot_lock:
            if page in self._plot_seen:
                return False           # эту серию уже спрашивали в этом паке
            self._plot_seen.add(page)
        mode = str(self.s.plot_mode or "title")
        # В режиме «ответ — название» из вопроса вычищаются и сам тайтл, и его
        # написания: иначе вопрос решается с первого слова.
        hide = names + list(cand.anime.get("synonyms") or [])
        try:
            with self._timed("сюжет"):
                question, answers = make_question(
                    cand.title_ru or (names[0] if names else ""),
                    got["text"], gemini, mode=mode,
                    page=str(got.get("page") or ""), names=hide)
        except Exception as e:  # noqa: BLE001 — тип зависит от gemini_api
            name = type(e).__name__
            if name == "GeminiBlockedError":
                # Модель не взялась именно за ЭТОТ пересказ (расправа, война —
                # у аниме такое сплошь и рядом). Ключ и квота при этом целы:
                # берём следующий тайтл, а род вопросов не трогаем.
                self._log_rare("Сюжет не по правилам",
                               f"«{cand.title_ru}»: Gemini не берётся за этот "
                               "пересказ — беру следующий тайтл")
                return False
            if name in ("GeminiAuthError", "GeminiQuotaError"):
                self.gemini = None
                self._drop_kind(PLOT_KIND)
                cand.rejected = True
                self.log(f"Вопросы по сюжету отключены: {e}")
            else:
                self._log_rare("Gemini", f"Gemini: {e}")
            return False
        if not question:
            self._log_rare("Сюжет без вопроса",
                           f"«{cand.title_ru}»: по пересказу вопроса не вышло "
                           "— беру следующий тайтл")
            return False
        cand.plot_question = question
        cand.plot_answers = list(answers)
        wiki = str(got.get("wiki") or "")
        page_name = str(got.get("page") or "")
        cand.plot_source = ", ".join(p for p in (wiki, page_name) if p)
        return True

    def _fetch_media(self, cand: SongCandidate) -> bool:
        if self.stopped():
            return False
        # Персонажа выбираем ДО имён файлов и до постера: ответом станет самое
        # первое произведение с ним, а значит и постер в ответе, и имена файлов
        # должны быть уже от него (см. _use_first_title).
        if cand.kind in (CHAR_KIND, MANGA_KIND):
            with self._timed("персонажи"):
                self._pick_character(cand)
            # Средняя сложность персонажей проверяется ЗДЕСЬ, а не при отборе:
            # раньше персонажа попросту не существовало. Зато проверка идёт до
            # загрузки портрета — впустую качается ровно ничего.
            if cand.character and not self._char_level_fits(cand):
                cand.rejected = True
                return False
            if cand.character:
                # Кандидат остаётся — вот теперь можно потратиться на поиск
                # самого первого произведения с этим персонажем.
                with self._timed("персонажи"):
                    self._use_first_title(cand)
            if not cand.character:
                if cand.kind == CHAR_KIND:
                    if not self.stopped():
                        self.log(f"«{cand.title_ru}» без персонажа — беру "
                                 "следующий тайтл")
                    return False
                if str(self.s.manga_question or "character") == "character":
                    # Персонажей у этой книги нет — спрашиваем обложкой, а не
                    # выбрасываем кандидата совсем.
                    self.log(f"«{cand.title_ru}»: персонажей нет — спрошу "
                             "обложкой")
        cand.media_base = self._media_base(cand)
        # Текстовые вопросы (анаграмма, сюжет) складываются ДО картинок: не
        # вышел вопрос — нечего и качать постер.
        if cand.kind == ANAGRAM_KIND and not self.build_anagram(cand):
            return False
        if cand.kind == PLOT_KIND and not self.make_plot_question(cand):
            return False
        if not cand.is_silent:
            # Видео-вопрос: если ролика для этой песни нет, вопрос всё равно
            # состоится — просто обычным отрезком звука.
            if cand.is_video:
                with self._timed("ролики"):
                    got = self.download_video(cand)
            else:
                got = False
            if not got:
                with self._timed("аудио"):
                    if not self.download_audio(cand):
                        return False
        if cand.is_pixel:
            # Кадр-проявление: сам вопрос — ролик, и без него вопроса нет.
            with self._timed("пиксели"):
                if not self.download_pixel(cand):
                    return False
        try:
            with self._timed("картинки"):
                self.download_images(cand)
        except Exception as e:  # noqa: BLE001 — картинки не критичны
            self.log(f"Картинки «{cand.title_ru}»: {e}")
        if cand.is_picture and not cand.is_pixel and not cand.has_frame:
            if not self.stopped():
                what = "портрета" if cand.is_character else "картинки"
                self.log(f"«{cand.title_ru}» без {what} — беру следующий тайтл")
            return False
        return True

    def _use_first_title(self, cand: SongCandidate) -> None:
        """Меняет карточку вопроса-персонажа на САМОЕ ПЕРВОЕ произведение, где
        этот персонаж вообще появлялся (просьба пользователя).

        Персонажа мы вытащили из того тайтла, что попался в списке, — а это
        запросто третий сезон или спин-офф. Отвечать «Наруто: Ураганные
        хроники» там, где по-человечески ответ «Наруто», неправильно, поэтому
        спрашиваем у Shikimori все его тайтлы и берём самый ранний по дате
        выхода. Не вышло — остаёмся на прежней карточке."""
        char_id = (cand.character or {}).get("id")
        if not char_id:
            return
        try:
            titles = self.shikimori.character_titles(char_id)
        except AnimePackApiError as e:
            self._log_rare("Где ещё был персонаж",
                           f"Где ещё был «{cand.char_name}»: {e}")
            return
        rows = titles.get("mangas" if cand.is_manga else "animes") or []
        best, best_date = None, ""
        for row in rows:
            aired = str((row or {}).get("aired_on") or "")
            try:
                rid = int(row.get("id") or 0)
            except (TypeError, ValueError):
                continue
            # Даты Shikimori — «ГГГГ-ММ-ДД», сравниваются как строки. Тайтлы без
            # даты (анонсы) в расчёт не берём: у них ничего не известно.
            if not rid or not aired:
                continue
            if best is None or aired < best_date:
                best, best_date = rid, aired
        if not best or best == cand.mal_id:
            return
        try:
            cards = (self._mangas_by_ids([best]) if cand.is_manga
                     else self._animes_by_ids([best]))
        except AnimePackApiError as e:
            self.log(f"Первый тайтл франшизы не загрузился: {e}")
            return
        card = cards[0] if cards else None
        if not isinstance(card, dict) or not (card.get("poster") or {}).get("originalUrl"):
            return
        # В лог о подмене не пишем: это рабочая мелочь отбора, а не событие, и
        # строчка на каждый вопрос-персонаж только засоряла консоль (просьба
        # пользователя).
        cand.anime = card

    def _media_base(self, cand: SongCandidate) -> str:
        """Имя медиафайлов вопроса внутри пака — «Сгенерировано в
        SI-HYX(Название тайтла)» (просьба пользователя: чтобы файлы в архиве
        читались глазами, а не числами).

        Одноимённые вопросы (несколько песен одного тайтла при разрешённых
        дублях) разводятся номером в конце — иначе они делили бы один файл."""
        title = safe_filename(cand.title_ru or str(cand.media_key), "Аниме",
                              max_len=80)
        base = f"{MEDIA_NAME_PREFIX}({title})"
        with self._names_lock:
            n = self._names.get(base, 0) + 1
            self._names[base] = n
        return base if n == 1 else f"{base} {n}"

    # ── шаг 4: набор пака ─────────────────────────────────────────────────
    def _prefers_music(self, cand: SongCandidate) -> bool:
        """Тайтл пришёл из списка с пометкой «в основном музыка»?

        Такой список человек ведёт ради песен: тайтл он может и не узнать в
        лицо, а вот опенинг угадает. Поэтому его тайтлы по возможности идут в
        песенные вопросы, а в кадры и персонажи — только если песенных мест уже
        не осталось (просьба пользователя)."""
        if not self._music_nicks:
            return False
        return any(str(n).strip().casefold() in self._music_nicks
                   for n in (cand.users or []))

    def _pick_kind(self, cand: SongCandidate, counts, inflight, quotas):
        """Каким вопросом станет кандидат — или None, если он больше не нужен.

        В смешанном режиме песня может стать вопросом-кадром: карточка аниме у
        неё уже есть, кадр берётся оттуда же. Выбираем из доступного тот тип,
        который сильнее отстаёт от своей квоты, — так пак набирается ровно, а не
        сначала все песни, потом все кадры."""
        options = [cand.kind]
        if cand.kind != MANGA_KIND:
            # Мангу не трогаем ни с какой стороны: её карточка приходит из
            # своего каталога, ни кадров, ни песен у книги нет.
            options += [k for k in SILENT_KINDS
                        if k not in (MANGA_KIND, cand.kind) and quotas.get(k, 0)]
            # Роликом может стать любая песня, кроме OST: их на AnimeThemes
            # нет вовсе (см. _theme_video). А вот у кандидата без песни ролику
            # взяться неоткуда.
            if (cand.kind not in SILENT_KINDS and cand.kind != "insert"
                    and quotas.get(VIDEO_KIND, 0)):
                options.append(VIDEO_KIND)
        free = [k for k in options
                if k not in self._dead_kinds
                and counts[k] + inflight[k] < quotas.get(k, 0)]
        if not free:
            return None
        if self._prefers_music(cand):
            # Песенные места есть — картинки и текст этому тайтлу не предлагаем
            # вовсе.
            songs = [k for k in free if k not in SILENT_KINDS]
            if songs:
                free = songs
        if len(free) == 1:
            return free[0]
        return min(free, key=lambda k: (counts[k] + inflight[k]) / max(1, quotas[k]))

    def _level_fits(self, cand: SongCandidate, levels: list) -> bool:
        """Держит среднюю сложность пака около level_avg.

        Рамки «от … до» задают, что вообще пускать, а это — на что должна
        выйти СЕРЕДИНА (просьба пользователя): пока набранная средняя выше
        цели, берём только тайтлы полегче, и наоборот. Первые несколько вопросов
        пропускаем без проверки — по одному-двум средняя ещё ничего не значит.

        Клапан на случай, когда подходящих просто нет: после
        LEVEL_AVG_GIVE_UP подряд отвергнутых кандидат проходит любой, иначе пак
        остался бы недобранным."""
        target = int(self.s.level_avg or 0)
        if not target:
            return True
        if len(levels) < 3:
            return True
        if self._level_skips >= self.LEVEL_AVG_GIVE_UP:
            if not self._level_warned:
                self._level_warned = True
                self.log(f"Средняя сложность {target} не выдерживается — "
                         "подходящих тайтлов не хватает, беру что есть.")
            self._level_skips = 0
            return True
        avg = sum(levels) / len(levels)
        if avg > target + 0.25 and cand.level > target:
            self._level_skips += 1
            return False
        if avg < target - 0.25 and cand.level < target:
            self._level_skips += 1
            return False
        self._level_skips = 0
        return True

    # Столько кандидатов подряд можно отвергнуть ради средней сложности.
    LEVEL_AVG_GIVE_UP = 60
    # То же для персонажей. Порог ниже: каждый отвергнутый персонаж — это уже
    # сделанный запрос к Shikimori, и полсотни таких подряд заняли бы минуту.
    CHAR_LEVEL_GIVE_UP = 20

    # «В избранном у всех на свете»: с таким числом char_question_level даёт
    # самый лёгкий уровень, какой у персонажа этого тайтла вообще возможен.
    _FAV_ALL = 10 ** 9
    # Со стольких увиденных персонажей верим границам достижимого. Раньше
    # недостижимость вскрывалась только после двух десятков впустую перебранных
    # кандидатов — а каждый из них это ещё и запрос к Shikimori. Меньше десятка
    # брать не стоит: границы ещё гуляют, и генератор объявляет о переезде
    # несколько раз подряд.
    CHAR_REACH_SAMPLE = 10

    def _char_reach(self, cand: SongCandidate) -> tuple[int, int]:
        """От какого до какого уровня бывают персонажи ЭТОГО тайтла.

        Сложность персонажа наполовину состоит из узнаваемости самого тайтла
        (CHAR_TITLE_WEIGHT), поэтому тайтл работает и полом, и потолком разом: из
        тайтла-шестёрки персонаж легче четвёртого уровня не получится, даже если
        его добавили в избранное десять тысяч человек."""
        base = cand.level
        return (char_question_level(base, self._FAV_ALL),
                char_question_level(base, 0))

    def _char_level_fits(self, cand: SongCandidate) -> bool:
        """Держит среднюю сложность ВОПРОСОВ-ПЕРСОНАЖЕЙ около char_level_avg.

        Отдельная от общей средней величина (просьба пользователя): сложность
        персонажа считается не только по узнаваемости тайтла, но и по тому,
        скольким людям он попал в избранное на Shikimori. Зовётся из рабочих
        потоков, поэтому список набранного — под замком.

        Просимая сложность бывает недостижима в принципе — не «подходящих мало»,
        а «таких не бывает»: при паке из тайтлов шестого уровня персонажа легче
        четвёртого взять неоткуда (см. _char_reach). Тогда генератор не хватает
        что попало, а переезжает на БЛИЖАЙШУЮ достижимую сложность и дальше
        держит уже её (просьба пользователя)."""
        target = int(getattr(self.s, "char_level_avg", 0) or 0)
        if not target or not cand.is_character:
            return True
        floor, ceil = self._char_reach(cand)
        level = cand.char_level
        message = ""
        with self._char_lock:
            # Границы считаем по РЕАЛЬНО попадавшимся персонажам, а не по
            # теоретическому размаху тайтлов: один удачный хит в пуле иначе
            # объявлял бы тройку достижимой, и генератор гнался бы за ней весь
            # пак. Границы только расширяются (min/max), поэтому цель ходит лишь
            # В СТОРОНУ просимой — туда-сюда она не мечется.
            self._char_reach_lo = min(self._char_reach_lo, level)
            self._char_reach_hi = max(self._char_reach_hi, level)
            self._char_floor = min(self._char_floor, floor)
            self._char_ceil = max(self._char_ceil, ceil)
            self._char_seen += 1
            near = max(self._char_reach_lo, min(self._char_reach_hi, target))
            if (self._char_seen >= self.CHAR_REACH_SAMPLE
                    and near != (self._char_target_eff or target)):
                self._char_target_eff = near
                self._char_skips = 0
                if near == target:
                    message = ("Нашлись персонажи поподходящее — возвращаюсь к "
                               f"запрошенной сложности {target}.")
                else:
                    side = "легче" if near > target else "сложнее"
                    # Одно дело «таких не бывает» (сложность персонажа наполовину
                    # из узнаваемости тайтла — из шестёрки легче четвёрки не
                    # выйдет), другое — «пока не попадались».
                    why = ("не бывает" if near == self._char_floor
                           else "пока не попадалось")
                    message = (f"Сложность персонажей {target} недостижима: "
                               f"{side} {near} в этом паке {why} — держу "
                               f"ближайшую, {near}.")
            aim = self._char_target_eff or target
            levels = list(self._char_levels)
            give_up = self._char_skips >= self.CHAR_LEVEL_GIVE_UP
            if give_up:
                self._char_skips = 0
                if not self._char_warned:
                    self._char_warned = True
                    message = (f"Средняя сложность персонажей {aim} не "
                               "выдерживается — подходящих не хватает, беру "
                               "что есть.")
            if give_up or len(levels) < 3:
                fits = True
            else:
                avg = sum(levels) / len(levels)
                level = cand.char_level
                fits = not ((avg > aim + 0.25 and level > aim)
                            or (avg < aim - 0.25 and level < aim))
                self._char_skips = 0 if fits else self._char_skips + 1
        if message:
            self.log(message)
        return fits

    def _remember_char_level(self, cand: SongCandidate) -> None:
        """Запоминает сложность принятого вопроса-персонажа."""
        if not cand.is_character:
            return
        with self._char_lock:
            self._char_levels.append(cand.char_level)

    def _drop_kind(self, kind: str) -> None:
        """Помечает род вопросов как больше не получающийся в этом прогоне.

        Зовётся из рабочего потока (Gemini отваливается прямо на загрузке), а
        разбирается с этим главный цикл отбора: свободные места надо отдать
        оставшимся родам, иначе они так и будут жечь кандидатов впустую."""
        with self._warn_lock:
            self._dead_kinds.add(kind)

    def _share_out_dead(self, quotas: dict, counts, inflight) -> None:
        """Отдаёт места отвалившихся родов вопросов остальным.

        Без этого пак недобирался на ровном месте: доля «по сюжету» с
        кончившимся ключом Gemini продолжала просить кандидатов, каждый из них
        тут же отваливался, и база кончалась раньше, чем набирались анаграммы
        (лог пользователя: 21 вопрос из 48 при живых 2891 тайтлах)."""
        with self._warn_lock:
            dead = sorted(self._dead_kinds)
        for kind in dead:
            left = quotas.get(kind, 0) - counts[kind] - inflight[kind]
            if left <= 0:
                continue
            quotas[kind] = counts[kind] + inflight[kind]
            alive = [k for k in quotas
                     if quotas.get(k, 0) > 0 and k not in dead]
            name = KIND_TITLES.get(kind, kind).lower()
            if not alive:
                self.log(f"Мест под «{name}» больше не занимаю ({left} шт.) — "
                         "переложить их не на кого, пак будет короче.")
                continue
            # Крупные доли первыми: лишние места достаются тому рода вопросов,
            # которого в паке и так больше всего.
            alive.sort(key=lambda k: (-quotas[k], k))
            for i in range(left):
                quotas[alive[i % len(alive)]] += 1
            where = ", ".join(KIND_TITLES.get(k, k).lower() for k in alive)
            self.log(f"Оставшиеся места «{name}» ({left} шт.) отдаю "
                     f"остальным: {where}.")

    def _log_shortage(self, got: int, total: int) -> None:
        """Почему кандидатов не хватило — цифрами, а не «кандидаты кончились»."""
        self.log(f"Кандидаты кончились: набрано {got} вопросов из {total}.")
        if self._seen_titles:
            self.log(f"Тайтлов база дала {self._seen_titles}, годных из них "
                     f"{self._good_titles}.")
        for reason, num in self._skips.most_common():
            if num:
                self.log(f"  • отсеяно «{reason}»: {num}")
        if self._failed_media:
            self.log("  • годный тайтл не дал вопроса (медиа, сюжет, "
                     f"персонаж): {self._failed_media}")
        self.log("Что делать: расширить рамки сложности и годов, разрешить "
                 "повтор франшизы или нажать «Обновить базу» — в кэше каталога "
                 "тайтлов ровно столько, сколько набралось в прошлый раз.")

    def select_songs(self) -> list:
        """Набирает ровно столько вопросов, сколько в паке, соблюдая квоты по
        типам. Медиа качаются параллельно прямо по ходу отбора."""
        total = self.s.total_questions
        quotas = self.s.question_quotas
        accepted: list[SongCandidate] = []
        levels: list[int] = []          # узнаваемость набранного (level_avg)
        counts: Counter = Counter()
        inflight: Counter = Counter()
        candidates = self.iter_candidates()
        exhausted = False
        over_budget = False
        workers = max(1, min(16, int(self.s.parallel)))
        pending: dict = {}

        self._progress(0, total, "Отбираю вопросы…")
        # Пул НЕ через `with`: выход из блока ждал бы конца всех запущенных
        # загрузок, и «Стоп» отзывался бы только через десятки секунд. Здесь
        # очередь сбрасывается, а работающие ffmpeg убиваются сразу.
        pool = ThreadPoolExecutor(max_workers=workers,
                                  thread_name_prefix="animepack")
        try:
            try:
                while not self.stopped():
                    # Род вопросов мог отвалиться совсем (кончился ключ Gemini) —
                    # его места надо отдать остальным ДО того, как просить
                    # следующего кандидата.
                    if self._dead_kinds:
                        self._share_out_dead(quotas, counts, inflight)
                    # Досыпаем задач, пока есть куда: набранное + в работе < нужного.
                    while (not exhausted
                           and len(accepted) + sum(inflight.values()) < total
                           and len(pending) < workers * 2):
                        with self._timed("поиск кандидатов"):
                            cand = next(candidates, None)
                        if cand is None:
                            exhausted = True
                            break
                        kind = self._pick_kind(cand, counts, inflight, quotas)
                        if kind is None:
                            continue        # квоты подходящих типов уже заняты
                        if not self._level_fits(cand, levels):
                            continue        # средняя сложность уехала бы дальше
                        cand.kind = kind    # в смешанном режиме тип мог смениться
                        inflight[kind] += 1
                        pending[pool.submit(self._fetch_media, cand)] = cand
                    if not pending:
                        break
                    # timeout: без него цикл спал бы до конца первой загрузки и
                    # не замечал нажатого «Стоп» по полминуты.
                    done, _ = wait(list(pending), timeout=0.3,
                                   return_when=FIRST_COMPLETED)
                    for fut in done:
                        cand = pending.pop(fut)
                        inflight[cand.kind] -= 1
                        try:
                            ok = fut.result()
                        except Exception as e:  # noqa: BLE001
                            self.log(f"Загрузка сорвалась: {e}")
                            ok = False
                        if not ok:
                            # Отвергнутый по средней сложности — не «не
                            # скачалось»: медиа мы даже не трогали.
                            if not cand.rejected:
                                self._failed_media += 1
                            continue
                        if len(accepted) >= total or counts[cand.kind] >= quotas.get(cand.kind, 0):
                            continue        # пока качали, место уже заняли
                        accepted.append(cand)
                        levels.append(cand.level)
                        self._remember_char_level(cand)
                        counts[cand.kind] += 1
                        self._bytes_used += self._media_size(cand)
                        # Название тайтла на прогресс-баре не пишем (просьба
                        # пользователя): в лог оно и так идёт, а на баре нужны
                        # только счётчик и оставшееся время.
                        self._progress(len(accepted), total, "")
                        if self._over_budget(len(accepted), total):
                            over_budget = True
                            break
                    if over_budget:
                        mb = self._bytes_used / (1024.0 * 1024.0)
                        self.log(
                            f"Пак упрётся в потолок {self.s.max_pack_mb} МБ: "
                            f"останавливаюсь на {len(accepted)} вопросах из "
                            f"{total} ({mb:.1f} МБ набрано). Дайте паку больше "
                            "мегабайт или ужмите медиа.")
                        break
                    if len(accepted) >= total:
                        break
            finally:
                for fut in pending:
                    fut.cancel()
        finally:
            # cancel_futures сбрасывает очередь не начатых загрузок, wait=False —
            # не ждём тех, что уже качаются (их ffmpeg добьёт stop_processes).
            if self.stopped():
                self.stop_processes()
            pool.shutdown(wait=False, cancel_futures=True)

        if self.s.only_kind:
            self.log(f"Отобрано тайтлов: {len(accepted)} из {total}")
        else:
            # OST — аббревиатура, строчными её писать нельзя.
            by_kind = ", ".join(
                f"{KIND_TITLES[k] if KIND_TITLES[k].isupper() else KIND_TITLES[k].lower()}"
                f": {counts[k]}"
                for k in (SONG_KINDS + (VIDEO_KIND,) + SILENT_KINDS)
                if quotas.get(k))
            self.log(f"Отобрано вопросов: {len(accepted)} из {total} ({by_kind})")
        if levels:
            avg = sum(levels) / len(levels)
            target = int(self.s.level_avg or 0)
            aim = f" (просили {target})" if target else ""
            self.log(f"Средняя сложность пака: {avg:.1f}{aim}")
        # Персонажей выделяем отдельной строкой (просьба пользователя): их
        # сложность считается по своей мере — узнаваемость тайтла плюс «в
        # избранном» на Shikimori.
        chars = [c for c in accepted if c.is_character]
        if chars:
            avg = sum(c.char_level for c in chars) / len(chars)
            target = int(getattr(self.s, "char_level_avg", 0) or 0)
            eff = int(self._char_target_eff or 0)
            aim = f" (просили {target})" if target else ""
            if target and eff and eff != target:
                # Просимая сложность оказалась недостижимой — говорим, какую
                # держали вместо неё, иначе цифра выглядит промахом.
                aim = f" (просили {target}, достижимо {eff})"
            known = [c.char_favorites for c in chars if c.char_favorites >= 0]
            fav = (f", в избранном в среднем у {sum(known) / len(known):.0f} чел."
                   if known else "")
            self.log(f"Средняя сложность персонажей: {avg:.1f}{aim}{fav}")
        if self._failed_media:
            self.log(f"Не скачалось и заменено: {self._failed_media}")
        if self._poster_hits or self._poster_tmdb:
            parts = []
            if self._poster_hits:
                parts.append(f"из кладовой обложек {self._poster_hits}")
            if self._poster_tmdb:
                parts.append(f"с TMDB {self._poster_tmdb}")
            self.log("Обложки: " + ", ".join(parts) + ".")
        # Кладовая обложек не должна расти без конца: лишнее выбрасывается по
        # времени последнего обращения (см. poster_cache.prune).
        if getattr(self.s, "poster_cache", True):
            gone = poster_cache.prune()
            if gone:
                self.log(f"Кладовая обложек подчищена: убрано {gone} давних.")
        if exhausted and len(accepted) < total and not self.stopped():
            self._log_shortage(len(accepted), total)
        self._log_warn_totals()
        if self.s.sort_by_index and not self.s.shuffle_questions:
            # Порядок задаст индекс популярности (arrange_questions) — мешать
            # список смысла нет, а лог приятнее читать по убыванию узнаваемости.
            accepted.sort(key=lambda c: c.index, reverse=True)
        else:
            self.rng.shuffle(accepted)
        return accepted[:total]

    # ── шаг 4б: у кого из списков есть отобранное ─────────────────────────
    def mark_list_owners(self, songs: list) -> None:
        """Дописывает в реплику ведущего ники тех, у кого тайтл есть в списке.

        Работает при общей базе (галочка «Отмечать, у кого есть»): аниме
        берутся случайно, но если выпавший тайтл нашёлся у кого-то из
        добавленных списков — его ник попадёт в ответ. Списки спрашиваются
        В КОНЦЕ, когда вопросы уже отобраны (просьба пользователя): раньше
        неизвестно, какие id вообще понадобятся."""
        if not (self.s.random_pool and getattr(self.s, "mark_owners", False)):
            return
        if not songs:
            return
        want = {"anime": {c.mal_id for c in songs if not c.is_manga and c.mal_id},
                "manga": {c.mal_id for c in songs if c.is_manga and c.mal_id}}
        owners: dict[str, dict[int, list[str]]] = {"anime": {}, "manga": {}}
        for target in ("anime", "manga"):
            if not want[target]:
                continue
            for user in self._user_lists(target):
                if self.stopped():
                    return
                nick = user.username.strip()
                try:
                    ids = set(self._fetch_user_list(user, target))
                except AnimePackApiError as e:
                    self.log(f"Список {nick}: {e} — отметок от него не будет")
                    continue
                for mal in want[target] & ids:
                    owners[target].setdefault(mal, []).append(nick)
        marked = 0
        for cand in songs:
            found = owners["manga" if cand.is_manga else "anime"].get(cand.mal_id)
            if found:
                cand.users = list(found)
                marked += 1
        if owners["anime"] or owners["manga"]:
            self.log(f"Есть в чьих-то списках: {marked} из {len(songs)} вопросов")

    # ── шаг 5: упаковка ───────────────────────────────────────────────────
    def write_package(self, songs: list, out_path: Optional[str] = None) -> str:
        from pathlib import Path
        xml = build_content_xml(songs, self.s)
        with open(os.path.join(self.folder, "content.xml"), "wb") as f:
            f.write(xml)

        used_audio = {c.audio_out for c in songs
                      if not c.is_silent and not c.has_video}
        # Ролик — и с AnimeThemes, и собранный из кадра (вопрос-пиксели).
        used_video = {c.video_out for c in songs if c.has_video}
        used_images = {c.poster_file for c in songs if c.has_poster}
        used_images |= {c.collage_file for c in songs if c.has_collage}
        used_images |= {c.frame_file for c in songs if c.has_frame}

        if out_path:
            target = Path(out_path)
        else:
            out_dir = self.s.out_dir.strip()
            if not out_dir:
                try:
                    from utils import default_download_dir
                    out_dir = default_download_dir()
                except Exception:  # pragma: no cover
                    out_dir = os.path.expanduser("~")
            target = Path(out_dir) / f"{safe_filename(self.s.title, 'Аниме пак')}.siq"
        target.parent.mkdir(parents=True, exist_ok=True)
        target = unique_path(target)

        with zipfile.ZipFile(target, "w") as zf:
            zf.writestr("content.xml", xml, zipfile.ZIP_DEFLATED)
            # Медиа уже сжато (opus/avif) — deflate только жжёт время.
            for folder, names in (("Audio", used_audio), ("Images", used_images),
                                  ("Video", used_video)):
                for name in sorted(names):
                    src = os.path.join(self.folder, folder, name)
                    if os.path.exists(src):
                        zf.write(src, f"{folder}/{name}", zipfile.ZIP_STORED)
        return str(target)

    def cleanup(self) -> None:
        self.stop_processes()
        if self.folder and os.path.isdir(self.folder):
            shutil.rmtree(self.folder, ignore_errors=True)
        self.folder = ""

    # ── кнопка «Обновить базу» ────────────────────────────────────────────
    def refresh_db(self) -> int:
        """Забывает кэш каталога Shikimori и набирает его заново.

        Каталог берётся ЦЕЛИКОМ, а не «сколько нужно на пак»: кнопка на то и
        нужна, чтобы база потом хватала на любой пак с этими фильтрами (просьба
        пользователя — раньше обход останавливался на нескольких сотнях
        карточек). Идёт это долго, поэтому на каждой странице проверяется
        «Остановить», а набранное сохраняется по ходу дела.

        Заодно прогревает узнаваемость франшиз: без этого первая же генерация
        снова потратила бы минуту на запросы (просьба пользователя — «обновить
        базу, то есть и индекс популярности ему»). Возвращает, сколько карточек
        оказалось в кэше."""
        self.db_cache.clear()
        self.log("База Shikimori: собираю заново — каталог берётся целиком, "
                 "это дольше минуты. Кнопка «Остановить» сохранит набранное.")
        cards: list[dict] = []
        ids = self.fetch_full_catalog()
        cards += [self._card_cache[i] for i in ids if i in self._card_cache]
        if self.s.manga_percent and not self.stopped():
            for i in self.fetch_full_catalog(manga=True):
                if i in self._manga_cache:
                    cards.append(self._manga_cache[i])
        if self.stopped():
            self.log("База Shikimori: остановлено, набранное всё же сохранено.")
            return len(cards)
        franchises = {str(c.get("franchise") or "").strip() for c in cards}
        franchises.discard("")
        if franchises:
            self.log(f"База Shikimori: считаю узнаваемость {len(franchises)} "
                     "франшиз…")
            for batch in _chunks(cards, 200):
                if self.stopped():
                    break
                self._load_franchise_indexes(batch)
        self.db_cache.save()
        self.log(f"База Shikimori обновлена: {len(cards)} карточек, "
                 f"{len(self._fr_index)} франшиз.")
        return len(cards)

    # ── всё вместе ────────────────────────────────────────────────────────
    def run(self, out_path: Optional[str] = None) -> PackResult:
        problems = self.s.validate()
        if problems:
            raise AnimePackError("\n".join(problems))
        result = PackResult(requested=self.s.total_questions)
        started = time.monotonic()
        with self._timed("чтение чужих паков"):
            self.load_exclusions()
        self.prepare_dirs()
        try:
            songs = self.select_songs()
            result.songs = songs
            result.failed_media = self._failed_media
            if self.stopped():
                result.cancelled = True
                return result
            if not songs:
                raise AnimePackError(
                    "Не набралось ни одной песни. Ослабьте фильтры "
                    "(сложность, жанры, годы, типы аниме) или добавьте списки.")
            if len(songs) < self.s.total_questions:
                self.log(f"Внимание: вопросов будет {len(songs)}, а не "
                         f"{self.s.total_questions} — кандидаты кончились.")
                if self.s.random_pool and self.s.has_songs \
                        and self._random_source == "shikimori":
                    # Замерено: песня в AnisongDB находится у 59 случайных
                    # тайтлов Shikimori из 150. С фильтром «Сложность пака»
                    # (узнаваемость) остаётся и того меньше.
                    self.log("Для песенного пака база AMQ плотнее: в каталоге "
                             "Shikimori песня есть примерно у четырёх тайтлов "
                             "из десяти, а «Сложность пака» режет ещё сильнее. "
                             "Поставьте «Случайные из базы AMQ» или ослабьте "
                             "сложность.")
            with self._timed("проверка списков"):
                self.mark_list_owners(songs)
            self.log("Собираю пакет…")
            with self._timed("сборка .siq"):
                result.path = self.write_package(songs, out_path)
            self.save_frames_history(songs)
            try:
                mb = os.path.getsize(result.path) / (1024.0 * 1024.0)
                limit = int(self.s.max_pack_mb)
                self.log(f"Вес пака: {mb:.1f} МБ (потолок {limit} МБ)")
                if mb > limit:
                    self.log("Внимание: пак вышел тяжелее потолка — так бывает, "
                             "когда сжатие медиа выключено и размер задаём не мы.")
            except OSError:
                pass
            self.log(f"Готово: {result.path}")
            return result
        finally:
            result.elapsed = time.monotonic() - started
            # Раскладка времени по этапам — в самом конце, чтобы её было видно
            # последней строкой лога (просьба пользователя).
            self.log_stage_times(result.elapsed)
            self.cleanup()
