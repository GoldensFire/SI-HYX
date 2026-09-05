# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# animepack_upgrade.py — доводка ГОТОВОГО .siq. Здесь НЕТ Qt: модуль
# тестируется отдельно от GUI (сама вкладка — animepack_upgrade_tab.py, сеть —
# animepack_api.ShikimoriApi, как у генератора).
#
# Что умеет (части включаются и выключаются по отдельности):
#   1. «Убрать спецвопросы» — со ставкой, с секретом, для себя, для всех и для
#      всех со ставкой становятся обычными вопросами. Поддержаны оба формата:
#      v4 держит тип дочерним <type name="cat">, v5 (SIGame 7) — атрибутом
#      <question type="secret"> плюс своими параметрами (тема/цена/режим
#      выбора), и убирать надо и то, и другое.
#   2. «Дописать варианты названий» — если правильный ответ похож на название
#      аниме, тайтл ищется на Shikimori, и в <right> дописываются ОСТАЛЬНЫЕ его
#      названия (ромадзи, английское, «лицензировано в РФ», синонимы) — ровно
#      так же, как это делает генератор аниме-паков (см.
#      animepack.SongCandidate.answer_variants). Там же, но только на ТОЧНОМ
#      совпадении: название переписывается в написании Shikimori («наруто» →
#      «Наруто») и в ответ кладётся постер тайтла — как у генератора.
#   3. «Сжать тяжёлые картинки» — картинки в архиве тяжелее порога пережимаются
#      в AVIF под лимит тем же кодированием, что у генератора (avif_fit), и
#      ссылки на них в content.xml переписываются на новое имя.
#   4. «Убрать повторяющийся текст» — если один и тот же короткий текстовый блок
#      («Назвать аниме») стоит в КАЖДОМ вопросе темы, он оттуда убирается: и так
#      понятно, что назвать надо аниме, а на экране это лишние секунды на каждом
#      вопросе. Плюс к тому убираются известные подписи (KNOWN_LABELS —
#      «Назвать аниме», «Назвать персонажа», «Назвать фильм»…) — эти и тогда,
#      когда в одном вопросе темы их всё-таки нет.
#   5. «Удалить пустые вопросы» — вопрос, в котором нет ни текста, ни картинки,
#      ни звука, ни ролика, выкидывается из пака целиком. Ответ не в счёт: играть
#      всё равно нечем, на экране пустота.
#   6. «Сжать тяжёлое аудио» — дорожки в паке тяжелее порога перекодируются в
#      opus на заданный битрейт (тот же список, что во вкладке «Обработка»).
#      Битрейт исходника сначала спрашивается у ffprobe: если он и так не выше
#      целевого, файл не трогается — перекод только испортил бы звук. Здесь же
#      живёт нормализация громкости (loudnorm) — та же, что в «Обработке».
#   7. «Сжать тяжёлое видео» — ролики тяжелее порога (и, по отдельной галочке,
#      вообще все, у кого кодек не AV1) перекодируются в AV1 + opus теми же
#      флагами, что во вкладке «Обработка» и в генераторе паков.
#   8. «Удалить неиспользуемые файлы» — медиа, на которое в content.xml нет ни
#      одной ссылки, в новый пак не переносится вовсе.
#
# Тайтлы ищутся на Shikimori — как и в «Генерации аниме-пака», ключей и
# регистрации не нужно вовсе.
#
# Ещё отсюда берётся карточка выбранного пака (read_pack_info): имя, автор и
# темы читаются из одного content.xml, медиа при этом не трогается.
#
# Исходный файл НЕ трогается никогда: результат пишется рядом отдельным .siq.
from __future__ import annotations

import copy
import difflib
import os
import re
import struct
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable, Iterator, Optional
from urllib.parse import unquote

from filenames import escape_uri_string, safe_filename, unique_path

# Разбор ответа («Наруто OP1 (2002) — 『Song』» → «Наруто») и отсев иероглифики
# живут в генераторе: правило одно на оба места. Оттуда же — параметры
# кодирования картинок, чтобы «быстро» тут и там значило одно и то же.
from animepack import (CREATE_NO_WINDOW, FFMPEG, FFPROBE, IMAGE_FIT_PASSES,
                       IMAGE_LIMIT_KB, IMAGE_MAX_SIDE, IMAGE_SPEED,
                       OPUS_LAYOUT_FIX, answer_title, has_cjk)
# Общая с генератором кладовая обложек: постер, скачанный там, здесь уже не
# качается (и наоборот), а запасной источник — TMDB — у них один на двоих.
import poster_cache

# Имена файла content.xml, какие встречаются в живых паках.
_CONTENT_CANDIDATES = ("content.xml", "Content.xml")

# ── Спецвопросы ──────────────────────────────────────────────────────────────
# Слева — всё, что встречается в файлах (v4 и v5 зовут одно и то же разными
# словами), справа — ключ, по которому мы их считаем. Таблица намеренно
# повторяет таблицу типов из SIQuester: имена берутся из формата пака, а не
# придумываются здесь.
SPECIAL_TYPES = {
    "auction": "stake", "stake": "stake",
    "cat": "secret", "bagcat": "secret", "secret": "secret",
    "secretpublicprice": "secret", "secretnoquestion": "secretnoquestion",
    "sponsored": "norisk", "norisk": "norisk",
    "forall": "forall",
    "stakeall": "stakeall",
}
# Подписи — НЕ самодельные: это те же слова, какими типы зовёт сам SIQuester
# (src/SIQuester/SIQuester.ViewModel/Model/QuestionTypesNamesNew.cs плюс
# Properties/Resources.ru-RU.resx). Раньше здесь стояли ходовые прозвища («кот в
# мешке», «ва-банк»), и на «кот в мешке без вопроса» это выглядело выдумкой:
# такого названия в игре нет, а тип есть — QuestionTypes.SecretNoQuestion
# ("secretNoQuestion", «Secret question type with no question (gives money
# immediately)»).
SPECIAL_LABELS = {
    "stake": "со ставкой", "secret": "с секретом",
    "secretnoquestion": "с секретом без вопроса", "norisk": "для себя",
    "forall": "для всех", "stakeall": "для всех со ставкой",
}
# Параметры v5, которые есть ТОЛЬКО у спецвопроса: тема и цена «кота», минимум
# ставки, множитель «без риска», режим выбора игрока. У обычного вопроса их быть
# не должно — SIGame покажет по ним прежнее поведение, даже если тип уже снят.
# Цену самого вопроса это не трогает: она лежит в атрибуте <question price>.
SPECIAL_PARAMS = ("theme", "price", "selectionMode")

# Как называется результат: «Пак» → «Пак (апгрейд).siq».
OUT_SUFFIX = " (апгрейд)"

# ── Профиль ──────────────────────────────────────────────────────────────────
# Профиль остался один (раньше был ещё «кино-пак» на Wikidata, его убрали), но
# поле в настройках и разбор его значения оставлены нарочно: в settings.json у
# части пользователей уже лежит старое сохранённое значение («movie»), и
# normalize_profile сводит любой мусор к единственному, что теперь есть.
PROFILE_ANIME = "anime"
PROFILES = (PROFILE_ANIME,)
PROFILE_LABELS = {PROFILE_ANIME: "Аниме-пак"}
# Как зовут базу названий в логах и подписях.
PROFILE_SOURCES = {PROFILE_ANIME: "Shikimori"}


def normalize_profile(value) -> str:
    """Имя профиля из настроек (в том числе старое «movie», мусор) → всегда
    PROFILE_ANIME — другого профиля больше нет."""
    key = str(value or "").strip().lower()
    return key if key in PROFILES else PROFILE_ANIME


# ── Повторяющийся текст темы ─────────────────────────────────────────────────
# Сколько символов позволено убираемой подписи. «Назвать аниме» — тринадцать;
# всё длинное скорее сам вопрос, а не указание, и трогать его нельзя.
REPEAT_TEXT_MAX_LEN = 60
# Сколько вопросов должно быть в теме, чтобы «в каждом» вообще что-то значило.
REPEAT_MIN_QUESTIONS = 2
# Подписи, которые в паках пишут заголовком к каждому вопросу темы. Их убираем
# и тогда, когда в одном вопросе темы такой подписи всё-таки нет: правило «в
# КАЖДОМ вопросе» на живых паках спотыкается сплошь и рядом. Живой случай —
# тема «Hayami Saori» из «Anime by Hinoriku 6»: «Назвать персонажа» стоит в семи
# вопросах из восьми, а восьмой спрашивает совсем другое («А сколько персонажей
# Hayami Saori озвучила в зимнем сезоне 2018 года?») — и из-за него подпись
# оставалась во всех семи.
#
# Список закрытый нарочно: это не «короткий текст», а именно указание, что
# делать, — его смысл виден и без подписи, потому что за ней идёт картинка или
# отрывок. Сравниваются они как и всё остальное здесь — norm_title (без
# регистра и знаков), так что «Назвать аниме:» и «назвать аниме» это одно и то
# же.
KNOWN_LABELS = (
    "Назвать аниме", "Назвать тайтл", "Назвать персонажа", "Назвать героя",
    "Назвать фильм", "Назвать сериал", "Назвать мультфильм", "Назвать актёра",
    "Назвать актера", "Назвать песню", "Назвать трек", "Назвать композицию",
    "Назвать опенинг", "Назвать эндинг", "Назвать сэйю", "Назвать студию",
    "Назвать мангу", "Назвать игру", "Угадать аниме", "Угадать персонажа",
    "Угадать фильм", "Угадать сериал", "Угадать песню",
)

# ── Картинки ─────────────────────────────────────────────────────────────────
# Что пережимаем в AVIF. GIF не берём: он бывает анимированным, а из анимации
# вышел бы один кадр. Уже готовый .avif тоже не трогаем — он и так сжат этим же
# кодером.
COMPRESS_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff")
IMAGE_MIN_MB = 1.0        # тяжелее этого — пережимаем
IMAGE_TO_KB = 500         # до скольки килобайт

# ── Аудио ────────────────────────────────────────────────────────────────────
# Что перекодируем в opus. Контейнеры с видео сюда не берём вовсе: в паке это
# вопрос-ролик, и выдирать из него звук нельзя.
AUDIO_EXTS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".oga", ".opus", ".flac",
              ".wma", ".aiff", ".aif", ".alac", ".mka")
AUDIO_MIN_MB = 5.0        # тяжелее этого — перекодируем
AUDIO_KBPS = 192          # в скольки килобитах
# Нормализация громкости — та же, что во вкладке «Обработка» (её значения по
# умолчанию, tabs._build_audio_group) и в генераторе паков. Выключена по
# умолчанию: в ЧУЖОМ паке громкость уже выставил автор, и двигать её вслепую
# без спросу нельзя.
AUDIO_NORM_I = -20.0      # целевая громкость, LUFS
AUDIO_NORM_LRA = 11.0     # разброс громкости
AUDIO_NORM_TP = -1.5      # потолок пиков, dBTP

# Список битрейтов — тот же, что во вкладке «Обработка» (config.AUDIO_BITRATES).
# «auto» оттуда не берётся: здесь битрейт — это цель, под которую жмут, а
# «сам разберись» на такой вопрос не ответ (исходный битрейт всё равно
# спрашивается у ffprobe, и файл лучше целевого не трогается вовсе).
AUDIO_BITRATES = (8, 16, 24, 32, 48, 64, 96, 128, 160, 192, 256)
# Дольше этого одно кодирование не ждём: дорожка в паке — это минуты звука, а не
# часы, и зависший ffmpeg не должен держать всю вкладку.
AUDIO_TIMEOUT = 600.0
# Кодирование идёт фоном к обычной работе за компьютером — тем же низким
# приоритетом, что и картинки (avif_fit._LOW_PRIORITY).
_LOW_PRIORITY = (getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
                 if os.name == "nt" else 0)

# ── Видео ────────────────────────────────────────────────────────────────────
# Что перекодируем в AV1. Кодирование — тот же libsvtav1, что во вкладке
# «Обработка» (workers.ProcessWorker._av1_encoder_args) и в генераторе паков
# (animepack.video_encode_args): keyint=-1 и scd=1, ключевые кадры только на
# сменах сцены. Звук ролика идёт тем же opus и с той же нормализацией, что и
# дорожки пака, — чтобы ролик не звучал громче соседних вопросов.
VIDEO_EXTS = (".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".m4v", ".mpg",
              ".mpeg", ".flv", ".ts", ".3gp", ".ogv")
VIDEO_MIN_MB = 20.0       # тяжелее этого — перекодируем
VIDEO_CRF = 45            # то же, что у вопроса-ролика в генераторе паков
VIDEO_PRESET = 13         # 13 — самый быстрый пресет libsvtav1
VIDEO_TUNE = 0            # 0 = tune=vq, как «тёмный» пресет «Обработки»
VIDEO_PIX_FMT = "yuv420p10le"
# Куда ужимать по высоте. Ноль — оставить как есть; ролик не растягивается
# никогда, только уменьшается (scale берёт min с высотой источника).
VIDEO_HEIGHTS = (0, 480, 720, 1080)
# Ролик кодируется минутами, а не секундами: даём ему в разы больше времени,
# чем дорожке. Зависший ffmpeg всё равно убьётся по этому сроку.
VIDEO_TIMEOUT = 3600.0
# Кодек, ради которого всё и затевается: файл в нём второй раз не жмём — если
# только он не тяжелее порога.
VIDEO_TARGET_CODEC = "av1"
# Роликов гоним по одному: libsvtav1 и сам ест все ядра (-threads 0 внутри), а
# два кодирования 1080p разом только толкались бы за процессор и память.
VIDEO_JOBS = 1

# ── Неиспользуемые файлы ─────────────────────────────────────────────────────
# Что считаем медиа при уборке мусора. Всё остальное (content.xml, Texts/,
# [Content_Types].xml) не трогается вовсе: это служебные части пака, ссылок на
# них в вопросах нет и быть не должно.
MEDIA_EXTS = tuple(sorted(set(
    COMPRESS_EXTS + AUDIO_EXTS + VIDEO_EXTS
    + (".gif", ".avif", ".jfif", ".heic", ".heif", ".apng", ".svg"))))

# ── Сколько кодирований гнать разом ──────────────────────────────────────────
# Числа не с потолка — замеры на живых паках (Ryzen 5 5600H, 12 потоков):
#   12 картинок из «Only Just Begun.siq»: в один поток 18,6 с │ в два 13,7 │
#     в три 12,2 │ в четыре 12,1 │ в шесть 12,0. После третьего роста нет:
#     libaom и сам жмёт картинку в несколько потоков (-row-mt, -threads 0).
#   8 дорожек из «anhime.siq»: в один поток 39,1 с │ в два 25,6 │ в четыре 17,6
#     │ в шесть 16,2 │ в восемь 13,2. libopus однопоточный, поэтому берём
#     больше — почти всё время процесс ждёт сам себя.
# Процессы идут с низким приоритетом: работать за компьютером они не мешают.
IMAGE_JOBS, AUDIO_JOBS = 3, 6


def media_jobs(want: int) -> int:
    """Сколько кодирований гнать разом на ЭТОЙ машине: на двухъядерном ноутбуке
    шесть параллельных ffmpeg только толкались бы локтями."""
    return max(1, min(int(want), os.cpu_count() or 1))

# ── Постер в ответе ──────────────────────────────────────────────────────────
# Кладём его туда же и в том же виде, что генератор паков: Images/, AVIF под тот
# же лимит. Без всякого таймера: duration не пишем вовсе, и постер висит, пока
# ведущий не пойдёт дальше. Имя — по номеру тайтла на Shikimori: один и тот же
# тайтл в паке встречается по нескольку раз, и файл на них нужен один.
POSTER_DIR = "Images"


class UpgradeError(Exception):
    """Ошибка апгрейда, которую не стыдно показать пользователю."""


def nearest_bitrate(kbps) -> int:
    """Ближайший битрейт из списка «Обработки». Настройки приезжают из
    settings.json, где могло оказаться что угодно, а на форме битрейт выбирают
    из списка — значения не из него выпадающий список показать не сможет."""
    try:
        want = int(float(kbps))
    except (TypeError, ValueError):
        return AUDIO_KBPS
    return min(AUDIO_BITRATES, key=lambda k: (abs(k - want), k))


def nearest_height(height) -> int:
    """Ближайшая высота из списка (0 — «не менять»). Как и с битрейтом:
    в settings.json могло оказаться что угодно, а на форме высоту выбирают из
    выпадающего списка."""
    try:
        want = int(float(height))
    except (TypeError, ValueError):
        return 0
    return min(VIDEO_HEIGHTS, key=lambda h: (abs(h - want), h))


def loudnorm_filter(s: "UpgradeSettings") -> str:
    """Фильтр нормализации громкости («» — выключена).

    Ровно та же строка, что собирает «Обработка»
    (workers.ProcessWorker._build_audio_filters) и генератор паков
    (animepack.audio_filters): один и тот же loudnorm с теми же тремя числами —
    целевой громкостью, разбросом и потолком пиков."""
    if not getattr(s, "audio_norm", False):
        return ""
    return (f"loudnorm=I={float(s.audio_norm_i):g}"
            f":LRA={float(s.audio_norm_lra):g}"
            f":TP={float(s.audio_norm_tp):g}")


def audio_filter_chain(s: "UpgradeSettings") -> str:
    """Готовая строка `-af` для перекода звука: нормализация (если включена) и
    ВСЕГДА фикс раскладки каналов под libopus.

    Фикс обязателен и сам по себе: libopus отвергает «боковые» раскладки
    (5.1(side) у AC3-дорожек) с «Invalid channel layout», а на stereo и mono он
    ничего не делает (то же правило, что в workers._af_arg)."""
    norm = loudnorm_filter(s)
    return f"{norm},{OPUS_LAYOUT_FIX}" if norm else OPUS_LAYOUT_FIX


# ─────────────────────────────────────────────────────────────────────────────
# Настройки
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class UpgradeSettings:
    """Что делать с паком. Все функции независимы и выключаются по одной."""
    # ── Профиль ───────────────────────────────────────────────────────────
    # Единственное значение — «anime» (тайтлы ищутся на Shikimori). Поле
    # оставлено ради settings.json старых версий (см. normalize_profile).
    profile: str = PROFILE_ANIME

    # ── Функция 1: спецвопросы → обычные ─────────────────────────────────
    strip_specials: bool = True
    # «С секретом без вопроса» (secretNoQuestion) — это выдача денег без вопроса
    # как такового: самого вопроса в нём нет. Обычным его не сделать, поэтому по
    # умолчанию такие пропускаются (о каждом пишется в отчёт).
    strip_no_question: bool = False

    # ── Функция 2: варианты названий с Shikimori ─────────────────────────
    add_titles: bool = True
    # Только точное совпадение названия — опечатка в букву-другую сюда входит
    # (см. is_typo). Выключено — засчитывается и просто близкое название, но
    # тогда чужой ответ может утащить за собой варианты постороннего тайтла.
    strict_match: bool = True
    # Какие именно названия дописывать, выбора нет: дописываются ВСЕ (ромадзи,
    # английское, лицензионное, синонимы, русское) — по просьбе пользователя
    # галочки убраны, и в паке всегда лежит полный список.
    #
    # Переписать название так, как оно написано на Shikimori («наруто» →
    # «Наруто»). Только при точном совпадении и только если разница в регистре:
    # менять сам текст ответа иначе — это уже другой ответ.
    fix_case: bool = True
    # Поставить в ответ постер тайтла (как это делает генератор паков). Тоже
    # только при точном совпадении: чужой постер в ответе хуже, чем никакого.
    add_poster: bool = True
    # Переспрашивать базу персонажей, когда ответ похож на имя героя, а не на
    # название (латиница в одно-три слова). Совпало точно — вопрос не трогаем
    # вовсе: спрашивали персонажа, а не аниме.
    check_characters: bool = True
    # Тема про мангу («Manga (для читающих)», «Ранобэ») — искать книгу, а не
    # аниме: обложка аниме в таком вопросе неверна, а у части ответов аниме нет
    # вовсе («Soul Cartel», «Noblesse» — манхва). Книга не нашлась — названия
    # всё равно доищутся по аниме, но обложка из него уже не берётся.
    book_themes: bool = True
    # Искать тайтл и по ОСТАЛЬНЫМ вариантам ответа, а не только по первому.
    # В живых паках первый ответ сплошь и рядом записан как «Название - Песня»,
    # а голое название лежит второй строкой (проверено на паке пользователя:
    # без этого не опознавался каждый третий ответ).
    use_other_answers: bool = True
    max_variants: int = 8                # сколько строк дописывать в один ответ
    # Ответы короче этого не ищем вовсе: «Да», «1945» и прочее к аниме
    # отношения не имеют, а запрос на каждый такой ответ — это секунды.
    min_query_len: int = 3

    # ── Функция 3: пережать тяжёлые картинки ─────────────────────────────
    compress_images: bool = True
    image_min_mb: float = IMAGE_MIN_MB   # тяжелее этого — пережимаем
    image_limit_kb: int = IMAGE_TO_KB    # до скольки килобайт ужимать
    image_speed: int = IMAGE_SPEED       # -cpu-used: 8 — самая быстрая

    # ── Функция 4: повторяющийся текст темы ──────────────────────────────
    strip_repeated_text: bool = True
    # Длиннее этого текст не убираем, даже если он стоит во всех вопросах темы:
    # короткая подпись — это указание («Назвать аниме»), а длинный текст скорее
    # сам вопрос, и удалять его вслепую нельзя.
    repeat_text_max_len: int = REPEAT_TEXT_MAX_LEN
    # Убирать известные подписи (KNOWN_LABELS) и там, где в одном вопросе темы
    # их нет: правило «в КАЖДОМ вопросе» на живых паках спотыкается — хватает
    # одного вопроса-исключения, чтобы подпись осталась во всех остальных.
    strip_known_labels: bool = True
    # Текстовый блок, за которым СРАЗУ идёт звук, играть одновременно с ним
    # (waitForFinish="False", в v4 — time="-1"; SIQuester зовёт это «Объединить
    # со следующим (играть одновременно)»). Иначе игра сначала выдерживает текст
    # на экране, и только потом включает отрывок — а текст там как раз подпись к
    # нему («Назвать аниме по опенингу»).
    merge_text_audio: bool = True

    # ── Функция 5: пустые вопросы ────────────────────────────────────────
    # Вопрос без содержимого (ни текста, ни картинки, ни звука, ни ролика)
    # выкидывается из пака целиком. Ответ не в счёт: играть всё равно нечем.
    drop_empty_questions: bool = True

    # ── Функция 6: тяжёлое аудио → opus ──────────────────────────────────
    compress_audio: bool = True
    audio_min_mb: float = AUDIO_MIN_MB   # тяжелее этого — перекодируем
    audio_kbps: int = AUDIO_KBPS         # в скольки килобитах
    # Нормализация громкости — та же, что во вкладке «Обработка». Выключена по
    # умолчанию: в чужом паке громкость уже выставил автор. Включённая, она
    # снимает обе оговорки «не трогаю»: дорожка перекодируется, даже если и так
    # не богаче целевого битрейта и даже если легче не станет, — иначе
    # нормализовать было бы нечего, ради чего галочку и включают.
    audio_norm: bool = False
    audio_norm_i: float = AUDIO_NORM_I
    audio_norm_lra: float = AUDIO_NORM_LRA
    audio_norm_tp: float = AUDIO_NORM_TP

    # ── Функция 7: тяжёлое видео → AV1 ───────────────────────────────────
    # Выключено по умолчанию НАРОЧНО, в отличие от остальных: перекод ролика
    # идёт минутами, а с галочкой «кодек не AV1» под него попадает вообще всё
    # видео пака — включать такое молча за пользователя нельзя.
    compress_video: bool = False
    video_min_mb: float = VIDEO_MIN_MB   # тяжелее этого — перекодируем
    # Перекодировать и лёгкие ролики, если они не в AV1: mp4 с H.264 из чужого
    # пака в AV1 худеет вдвое-втрое даже без ужимания разрешения.
    video_non_av1: bool = True
    video_crf: int = VIDEO_CRF           # 0–63, больше — легче и хуже
    video_preset: int = VIDEO_PRESET     # 0–13, больше — быстрее и хуже
    video_height: int = 0                # 0 — не менять разрешение

    # ── Функция 8: неиспользуемые файлы ──────────────────────────────────
    # Медиа, на которое в content.xml нет ни одной ссылки, в новый пак не
    # переносится. В живых паках такого добра хватает: автор поменял картинку,
    # а старая осталась лежать в архиве и весить.
    drop_unused: bool = True

    # ── Прочее ───────────────────────────────────────────────────────────
    out_dir: str = ""                    # пусто — рядом с исходным паком

    def to_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: dict) -> "UpgradeSettings":
        s = cls()
        if not isinstance(d, dict):
            return s
        for key, value in d.items():
            if value is None or not hasattr(s, key):
                continue
            try:
                setattr(s, key, type(getattr(s, key))(value))
            except (TypeError, ValueError):
                pass
        s.max_variants = max(1, min(50, int(s.max_variants)))
        s.min_query_len = max(1, min(20, int(s.min_query_len)))
        s.image_min_mb = max(0.1, min(100.0, float(s.image_min_mb)))
        s.image_limit_kb = max(50, min(20000, int(s.image_limit_kb)))
        s.image_speed = max(0, min(8, int(s.image_speed)))
        s.repeat_text_max_len = max(1, min(500, int(s.repeat_text_max_len)))
        s.audio_min_mb = max(0.1, min(500.0, float(s.audio_min_mb)))
        s.audio_kbps = nearest_bitrate(s.audio_kbps)
        s.audio_norm_i = max(-60.0, min(20.0, float(s.audio_norm_i)))
        s.audio_norm_lra = max(0.0, min(50.0, float(s.audio_norm_lra)))
        s.audio_norm_tp = max(-60.0, min(10.0, float(s.audio_norm_tp)))
        s.video_min_mb = max(0.1, min(2000.0, float(s.video_min_mb)))
        s.video_crf = max(0, min(63, int(s.video_crf)))
        s.video_preset = max(0, min(13, int(s.video_preset)))
        s.video_height = nearest_height(s.video_height)
        s.profile = normalize_profile(s.profile)
        return s

    @property
    def source_name(self) -> str:
        """Как зовут базу названий («Shikimori»)."""
        return PROFILE_SOURCES.get(normalize_profile(self.profile), "Shikimori")

    def validate(self) -> list[str]:
        problems: list[str] = []
        if not (self.strip_specials or self.add_titles or self.compress_images
                or self.strip_repeated_text or self.drop_empty_questions
                or self.compress_audio or self.compress_video
                or self.drop_unused or self.merge_text_audio):
            problems.append("Все функции выключены — паку нечего менять. "
                            "Включите «Убрать спецвопросы», «Дописать варианты "
                            "названий», «Сжать тяжёлые картинки», «Убрать "
                            "повторяющийся текст», «Текст под звук», «Удалить "
                            "пустые вопросы», «Сжать тяжёлое аудио», «Сжать "
                            "тяжёлое видео» или «Удалить неиспользуемые "
                            "файлы».")
        if self.compress_images and self.image_limit_kb >= self.image_min_mb * 1024:
            problems.append(
                f"Сжимать не во что: картинки берутся от "
                f"{self.image_min_mb:g} МБ, а ужимать велено до "
                f"{self.image_limit_kb} КБ — это не меньше исходного порога.")
        return problems


# ─────────────────────────────────────────────────────────────────────────────
# Отчёт об изменениях
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class Change:
    """Одна правка. Место в паке общее для всех функций, поэтому и класс один:
    таблица на вкладке показывает их вперемешку, в порядке пака. У картинки
    места в раундах нет — вместо темы стоит имя файла, цены нет вовсе."""
    # special | title | case | poster | image | repeat | merge | empty |
    # audio | video | unused | character
    kind: str = "special"
    round_name: str = ""
    theme_name: str = ""
    price: int = 0
    before: str = ""                     # что было («с секретом», ответ)
    after: str = ""                      # что стало («обычный», ответ + варианты)
    added: list[str] = field(default_factory=list)   # дописанные варианты
    title: str = ""                      # найденный на Shikimori тайтл
    # Номер вопроса в паке: по нему правки обеих функций выстраиваются в общую
    # таблицу в том же порядке, в каком идут в файле.
    order: int = 0

    @property
    def place(self) -> str:
        return f"«{self.round_name}» · «{self.theme_name}» · {self.price}"


@dataclass
class UpgradeResult:
    path: str = ""                       # готовый .siq
    source: str = ""                     # исходный
    questions: int = 0                   # сколько вопросов в паке
    specials: list = field(default_factory=list)     # список Change (special)
    titles: list = field(default_factory=list)       # список Change (title)
    recased: list = field(default_factory=list)      # список Change (case)
    posters: list = field(default_factory=list)      # список Change (poster)
    images: list = field(default_factory=list)       # список Change (image)
    repeats: list = field(default_factory=list)      # список Change (repeat)
    merged: list = field(default_factory=list)       # список Change (merge)
    empties: list = field(default_factory=list)      # список Change (empty)
    audios: list = field(default_factory=list)       # список Change (audio)
    videos: list = field(default_factory=list)       # список Change (video)
    unused: list = field(default_factory=list)       # список Change (unused)
    skipped_specials: list = field(default_factory=list)  # без самого вопроса
    skipped_titles: list = field(default_factory=list)    # ответ — имя персонажа
    checked_answers: int = 0             # сколько ответов искали в базе названий
    not_found: int = 0                   # столько тайтлов не нашлось
    exact_titles: int = 0                # столько ответов совпало слово в слово
    typo_titles: int = 0                 # из них столько — с опечаткой в ответе
    heavy_images: int = 0                # картинок тяжелее порога нашлось
    heavy_audio: int = 0                 # дорожек тяжелее порога нашлось
    heavy_video: int = 0                 # роликов под перекод набралось
    dropped_themes: int = 0              # тем осталось без единого вопроса
    saved_bytes: int = 0                 # столько весу ушло со сжатием картинок
    saved_audio_bytes: int = 0           # столько весу ушло с перекодом звука
    saved_video_bytes: int = 0           # столько весу ушло с перекодом видео
    saved_unused_bytes: int = 0          # столько весу ушло с мусором
    added_bytes: int = 0                 # столько весу прибавили постеры
    cancelled: bool = False
    elapsed: float = 0.0

    @property
    def parts(self) -> list:
        """Списки правок по функциям — в том порядке, в каком идут в отчёте."""
        return [self.specials, self.titles, self.recased, self.posters,
                self.images, self.repeats, self.merged, self.empties,
                self.audios, self.videos, self.unused]

    @property
    def changes(self) -> list:
        """Все правки в порядке пака (все функции вперемешку)."""
        return sorted([c for part in self.parts for c in part],
                      key=lambda c: c.order)

    @property
    def total(self) -> int:
        return sum(len(part) for part in self.parts)


# ─────────────────────────────────────────────────────────────────────────────
# Разбор .siq
# ─────────────────────────────────────────────────────────────────────────────
def _safe_parser() -> ET.XMLParser:
    """Разбор недоверенного XML: .siq чаще всего скачан из интернета.

    Объявления сущностей запрещаем совсем — это закрывает и чтение локальных
    файлов через внешние SYSTEM-сущности (XXE), и «лавину сущностей» (billion
    laughs). Предопределённые (&amp; &lt; …) к объявлениям не относятся и
    разбираются как обычно."""
    parser = ET.XMLParser()

    def _deny(*_a, **_kw):
        raise UpgradeError("В content.xml объявлены XML-сущности — такой файл "
                           "разбирать небезопасно.")

    try:
        parser.parser.EntityDeclHandler = _deny
        parser.parser.UnparsedEntityDeclHandler = _deny
    except AttributeError:  # pragma: no cover — не expat
        pass
    return parser


def parse_content(data: bytes) -> tuple[ET.Element, str]:
    """content.xml → (корень, адрес пространства имён). BOM снимаем сами:
    ElementTree на нём спотыкается."""
    if data.startswith(b"\xef\xbb\xbf"):
        data = data[3:]
    try:
        root = ET.fromstring(data, parser=_safe_parser())
    except UpgradeError:
        raise
    except ET.ParseError as e:
        raise UpgradeError(f"content.xml не разбирается: {e}") from e
    ns = root.tag.split("}")[0][1:] if "{" in root.tag else ""
    return root, ns


def tag_fn(ns: str) -> Callable[[str], str]:
    """Имя тега с пространством имён пака (у v4 его обычно нет вовсе).

    Нужен только для СОЗДАНИЯ элементов (новый <answer> обязан лечь в то же
    пространство имён). Для поиска по дереву он не используется — см. ниже."""
    if not ns:
        return lambda name: name
    return lambda name: f"{{{ns}}}{name}"


# ── Поиск по дереву: по местному имени, без пространства имён ────────────────
# Спускаемся по известным именам детей вместо findall с путями и «.//». Это и
# быстрее (нет разбора пути и рекурсивного обхода на каждом уровне), и
# устойчивее: пространство имён у пака может быть любым, а у v4 его нет вовсе,
# и тогда одно и то же дерево пришлось бы обходить двумя разными способами.
def local(tag: str) -> str:
    """«{http://…}question» → «question»."""
    return str(tag).rsplit("}", 1)[-1]


def children(el, name: str) -> list:
    """Прямые дети с таким местным именем (пустой список, если el — None)."""
    if el is None:
        return []
    return [c for c in el if local(c.tag) == name]


def child(el, name: str):
    """Первый прямой ребёнок с таким местным именем или None."""
    if el is None:
        return None
    for c in el:
        if local(c.tag) == name:
            return c
    return None


def read_content(path: str) -> tuple[str, bytes]:
    """(имя записи в архиве, содержимое) для content.xml пака."""
    try:
        with zipfile.ZipFile(path) as zf:
            name = next((n for n in _CONTENT_CANDIDATES if n in zf.namelist()),
                        None)
            if not name:
                name = next((n for n in zf.namelist()
                             if n.lower().endswith("content.xml")), None)
            if not name:
                raise UpgradeError("В архиве нет content.xml — это не пакет "
                                   "SIGame.")
            return name, zf.read(name)
    except UpgradeError:
        raise
    except (OSError, zipfile.BadZipFile) as e:
        raise UpgradeError(f"Файл не читается как .siq: {e}") from e


def iter_themes(root: ET.Element) -> Iterator[tuple[str, str, list]]:
    """(имя раунда, имя темы, все её вопросы) по всему паку, в порядке файла.

    Спуск по известным именам — package → rounds → round → themes → theme →
    questions → question.
    Темой, а не отдельным вопросом, работает уборка повторяющегося текста: там
    правило — «стоит в КАЖДОМ вопросе темы»."""
    for r_idx, rnd in enumerate(children(child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        for theme in children(child(rnd, "themes"), "theme"):
            yield (rname, theme.get("name") or "",
                   children(child(theme, "questions"), "question"))


def iter_questions(root: ET.Element) -> Iterator[tuple[str, str, ET.Element]]:
    """(имя раунда, имя темы, вопрос) по всему паку, в порядке файла."""
    for rname, tname, questions in iter_themes(root):
        for q in questions:
            yield rname, tname, q


@dataclass
class PackInfo:
    """Что показать про выбранный пак до того, как его начали править."""
    name: str = ""
    authors: list[str] = field(default_factory=list)
    date: str = ""
    version: str = ""
    questions: int = 0
    specials: int = 0
    # [(имя раунда, [темы])] — списком, чтобы карточка шла в порядке пака.
    rounds: list = field(default_factory=list)

    @property
    def themes(self) -> list[str]:
        return [t for _r, names in self.rounds for t in names]

    @property
    def author(self) -> str:
        return ", ".join(self.authors)


def read_pack_info(path: str) -> PackInfo:
    """Название, автор и темы пака — из одного content.xml.

    Медиа не трогается вовсе: из архива читается ровно один файл, так что даже
    на паке в сотню мегабайт это доли секунды."""
    _cname, data = read_content(path)
    root, _ns = parse_content(data)
    info = PackInfo(name=str(root.get("name") or ""),
                    date=str(root.get("date") or ""),
                    version=str(root.get("version") or ""))
    authors = child(child(root, "info"), "authors")
    info.authors = [str(a.text or "").strip()
                    for a in children(authors, "author")
                    if str(a.text or "").strip()]
    for r_idx, rnd in enumerate(children(child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        names = []
        for theme in children(child(rnd, "themes"), "theme"):
            names.append(str(theme.get("name") or "").strip() or "без имени")
            for q in children(child(theme, "questions"), "question"):
                info.questions += 1
                if special_key(q):
                    info.specials += 1
        info.rounds.append((str(rname), names))
    return info


def retarget_refs(root: ET.Element, renames: dict) -> int:
    """Переводит ссылки на медиа с прежних имён на новые.

    Ссылка живёт в тексте <item> (v5) или <atom> (v4); у v4 перед именем стоит
    «@» — признак файла в архиве, у v5 то же самое сказано атрибутом isRef.
    Само имя бывает percent-кодированным — сравниваем и пишем в том же виде,
    в каком оно там лежало, и кодируем так же, как это делает игра
    (escape_uri_string). Возвращает число переписанных ссылок."""
    changed = 0
    for el in root.iter():
        if local(el.tag) not in ("item", "atom"):
            continue
        raw = (el.text or "").strip()
        if not raw:
            continue
        ref, body = raw.startswith("@"), raw.lstrip("@")
        decoded = unquote(body).replace("\\", "/").rsplit("/", 1)[-1]
        new = renames.get(decoded)
        if not new:
            continue
        el.text = ("@" if ref else "") + (escape_uri_string(new)
                                          if body != unquote(body) else new)
        changed += 1
    return changed


# ─────────────────────────────────────────────────────────────────────────────
# Перенос записей в новый архив
# ─────────────────────────────────────────────────────────────────────────────
# Сколько байт за раз льём из архива в архив: запись бывает и в полсотни
# мегабайт (ролик), держать её в памяти целиком незачем.
_COPY_CHUNK = 1 << 20
# Флаги записи, при которых в чужие байты лучше не лезть: 0x01 — запись
# зашифрована, 0x08 — размеры лежат не в заголовке, а в дескрипторе за данными
# (второе мы чиним сами, размеры-то известны из центрального каталога).
_FLAG_ENCRYPTED, _FLAG_DESCRIPTOR = 0x01, 0x08


def copy_zip_entry(src: zipfile.ZipFile, dst: zipfile.ZipFile,
                   info: zipfile.ZipInfo, name: Optional[str] = None) -> bool:
    """Переносит запись из архива в архив КАК ЕСТЬ, не распаковывая.

    zipfile так не умеет: writestr(info, src.read(...)) честно разжимает запись
    и жмёт её обратно тем же дефлейтом. В паке это сотня мегабайт уже сжатого
    mp3/mp4, и на них уходило больше времени, чем на всю остальную работу
    (замер на «Anime 3 season.siq», 75 МБ: 4,9 с против 0,11 с здесь; файл на
    выходе байт в байт тот же).

    False — по-быстрому не вышло (шифрованная запись, zip64, битый заголовок):
    зовущий кладёт её обычным путём."""
    if (info.flag_bits & _FLAG_ENCRYPTED
            or info.compress_size > zipfile.ZIP64_LIMIT
            or info.file_size > zipfile.ZIP64_LIMIT):
        return False
    src_fp, dst_fp = src.fp, dst.fp
    if src_fp is None or dst_fp is None:  # pragma: no cover — архив уже закрыт
        return False
    start = dst_fp.tell()
    try:
        src_fp.seek(info.header_offset)
        fields = struct.unpack(zipfile.structFileHeader,
                               src_fp.read(zipfile.sizeFileHeader))
        if fields[zipfile._FH_SIGNATURE] != zipfile.stringFileHeader:
            return False
        # Имя и «дополнительное поле» в локальном заголовке свои: их длина с
        # центральным каталогом совпадать не обязана, поэтому берём из него.
        src_fp.seek(fields[zipfile._FH_FILENAME_LENGTH]
                    + fields[zipfile._FH_EXTRA_FIELD_LENGTH], 1)
        zi = copy.copy(info)
        if name:
            zi.filename = name
        zi.flag_bits &= ~_FLAG_DESCRIPTOR
        zi.header_offset = start
        dst_fp.write(zi.FileHeader(False))
        left = int(info.compress_size)
        while left > 0:
            chunk = src_fp.read(min(_COPY_CHUNK, left))
            if not chunk:
                raise zipfile.BadZipFile(f"запись оборвалась: {info.filename}")
            dst_fp.write(chunk)
            left -= len(chunk)
    except Exception:  # noqa: BLE001 — не вышло по-быстрому, положат обычным путём
        dst_fp.seek(start)
        dst_fp.truncate()
        return False
    dst.start_dir = dst_fp.tell()
    dst.filelist.append(zi)
    dst.NameToInfo[zi.filename] = zi
    dst._didModify = True
    return True


def fmt_size(num: int) -> str:
    """«1,8 МБ», «412 КБ» — для отчёта об изменениях."""
    mb = float(num) / (1024 * 1024)
    if mb >= 1.0:
        return f"{mb:.1f} МБ".replace(".", ",")
    return f"{max(1, int(round(float(num) / 1024)))} КБ"


def _temp_dir() -> str:
    """Куда класть промежуточные файлы кодирования (общая папка приложения)."""
    try:
        from config import TEMP_DIR
        os.makedirs(TEMP_DIR, exist_ok=True)
        return str(TEMP_DIR)
    except Exception:  # pragma: no cover — модуль должен жить и без приложения
        import tempfile
        return tempfile.gettempdir()


def question_price(q_el: ET.Element) -> int:
    try:
        return int(q_el.get("price") or 0)
    except (TypeError, ValueError):
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Функция 1: спецвопрос → обычный
# ─────────────────────────────────────────────────────────────────────────────
def special_key(q_el: ET.Element) -> Optional[str]:
    """Ключ спецвопроса (см. SPECIAL_TYPES) или None у обычного.

    v5 держит тип в атрибуте, v4 — в дочернем <type name="cat">."""
    kind = (q_el.get("type") or "").strip().lower()
    if not kind:
        t = child(q_el, "type")
        kind = ((t.get("name") if t is not None else "") or "").strip().lower()
    return SPECIAL_TYPES.get(kind)


def has_question_content(q_el: ET.Element) -> bool:
    """Есть ли у вопроса он сам — текст, картинка, звук или ролик.

    У «кота в мешке без вопроса» его нет вовсе (игрок просто получает деньги):
    обычным такой вопрос не станет, сколько тип ни снимай."""
    for params in children(q_el, "params"):
        for param in children(params, "param"):
            if (param.get("name") or "") != "question":
                continue
            if len(param) or (param.text or "").strip():
                return True
    scenario = child(q_el, "scenario")             # формат v4
    if scenario is not None and (len(scenario) or (scenario.text or "").strip()):
        return True
    return False


def make_simple(q_el: ET.Element) -> None:
    """Снимает с вопроса всё, что делало его спецвопросом.

    v5: убираем атрибут type и параметры спецвопроса (тема/цена кота, минимум
    ставки, режим выбора). v4: убираем дочерний <type> целиком — вместе с его
    параметрами, они внутри. Сам вопрос, ответы и цена не трогаются."""
    if q_el.get("type") is not None:
        del q_el.attrib["type"]
    for params in children(q_el, "params"):
        for param in list(params):
            if (param.get("name") or "") in SPECIAL_PARAMS:
                params.remove(param)
    for type_el in children(q_el, "type"):
        q_el.remove(type_el)


# ─────────────────────────────────────────────────────────────────────────────
# Функция 2: варианты названия с Shikimori
# ─────────────────────────────────────────────────────────────────────────────
# Кавычки всех сортов вокруг названия («Наруто», "Наруто", „Наруто“).
_RE_QUOTES = re.compile(r'^[«"„“”\'`\s]+|[»"“”\'`\s]+$')
# Хвостовые пояснения: «Наруто (аниме)», «血界戦線 (манга)».
_RE_KIND_TAIL = re.compile(r"\s*\(\s*(аниме|манга|манхва|ранобэ|anime|manga)"
                           r"\s*\)\s*$", re.IGNORECASE)
# Для сравнения названий: всё, кроме букв и цифр, — в пробел.
_RE_NON_WORD = re.compile(r"[^0-9a-zA-Zа-яёА-ЯЁ]+")
# «Эхо террора - Trigger» → «Эхо террора»: в живых паках песню от названия
# отделяют обычным дефисом, а не 『…』, как это делает генератор. Пробелы вокруг
# тире обязательны, иначе резались бы названия вроде «Жожо-2».
_RE_DASH_TAIL = re.compile(r"\s+[—–-]\s+.*$")
# Сколько запросов Shikimori готовы потратить на ОДИН вопрос. Больше незачем:
# запросы идут через общий лимитер (5/с и 80/мин), и на паке в полторы сотни
# вопросов каждый лишний вариант — это лишняя минута ожидания.
MAX_QUERIES_PER_QUESTION = 4


def answer_query(text) -> str:
    """Что искать на Shikimori по строке правильного ответа.

    Общим правилом генератора отрезаем песню, год и тег («Наруто OP1 (2002) —
    『Song』» → «Наруто»), потом снимаем кавычки и хвостовое пояснение вида
    «(аниме)». Косую черту тут НЕ трогаем: «Fate/Zero» — это целое название, а
    ответы вида «Ueno-san wa Bukiyou/ Неуклюжая Уэно» разбираются отдельно, уже
    после того, как поиск по строке целиком ничего не дал (см. slash_parts)."""
    line = answer_title(text)
    line = _RE_KIND_TAIL.sub("", line)
    line = _RE_QUOTES.sub("", line)
    return line.strip()


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


def answer_queries(answers, *, use_others: bool = True, min_len: int = 3,
                   limit: int = MAX_QUERIES_PER_QUESTION) -> list[str]:
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
    head = _RE_DASH_TAIL.sub("", texts[0])
    raw = [texts[0], head] + slash_parts(head)
    if use_others:
        raw += texts[1:]
    out, seen = [], set()
    for text in raw:
        query = answer_query(text)
        key = norm_title(query)
        # Совсем короткое и то, в чём нет ни одной буквы («1945», «12»), не
        # ищем вовсе: к аниме это отношения не имеет, а запрос стоит секунды.
        if (len(query) < min_len or not key or key in seen
                or not re.search(r"[^\W\d_]", query)):
            continue
        seen.add(key)
        out.append(query)
        if len(out) >= max(1, limit):
            break
    return out


def norm_title(text) -> str:
    """Название в сравнимом виде: без знаков, регистра и лишних пробелов."""
    return _RE_NON_WORD.sub(" ", str(text or "")).strip().casefold()


def card_names(card: dict) -> list[str]:
    """Все названия карточки Shikimori — по ним и опознаём тайтл."""
    names = main_names(card) + [card.get("japanese")]
    names += list(card.get("synonyms") or [])
    return [str(n).strip() for n in names if str(n or "").strip()]


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


def spelling_names(card: dict) -> list[str]:
    """Названия, по которым можно править НАПИСАНИЕ ответа.

    То же, что main_names, плюс синонимы: японское поле исключено намеренно —
    у записи «Mumei» там лежит «mumei», и «исправление регистра» понижало в
    ответе заглавную букву (живой случай из пака пользователя)."""
    return main_names(card) + [str(n).strip()
                               for n in (card.get("synonyms") or [])
                               if str(n or "").strip()]


# ── Темы про книги ───────────────────────────────────────────────────────────
# «Manga (для читающих)», «Ранобэ», «Манхва» — по названию темы видно, что
# спрашивают книгу, а не аниме. Ищем слова целиком, но с любым окончанием
# («манги», «ранобэшка»): в названиях тем их склоняют как попало. Латиница
# нужна не меньше кириллицы — в живых паках тема так и зовётся, «Manga».
_RE_BOOK_THEME = re.compile(
    r"(?:^|[^0-9a-zA-Zа-яёА-ЯЁ])"
    r"(?:манга|манги|манге|мангу|мангой|манхв\w*|маньхуа|манхуа|ранобэ\w*|"
    r"ранобе\w*|новелл\w*|manga\w*|manhwa\w*|manhua\w*|ranobe\w*|"
    r"light\s*novels?|novels?)"
    # Хвост важен: без него «мангал» и «романтика» считались бы книжной темой
    # («манга» и «новелл» — их начало).
    r"(?![0-9a-zA-Zа-яёА-ЯЁ])",
    re.IGNORECASE)


def is_book_theme(name) -> bool:
    """Спрашивают ли в этой теме мангу, манхву или ранобэ."""
    return bool(_RE_BOOK_THEME.search(str(name or "")))


# Записи Shikimori, которые аниме не являются: вокалоид-клипы и прочая музыка
# («music»), промо-ролики («pv») и реклама («cm»). Ответом в паке они не бывают
# никогда, а имена персонажей ловят на себя постоянно: на паке пользователя все
# 5 промахов из 49 пришлись ровно на «music», а 44 верных — на tv/movie.
CLIP_KINDS = ("music", "pv", "cm")


def is_clip(card: dict) -> bool:
    """Клип, промо или реклама — не тайтл. Незнакомый тип считаем настоящим:
    список типов Shikimori пополняет, и глушить новые вслепую нельзя."""
    return str(card.get("kind") or "").strip().lower() in CLIP_KINDS


def synonym_only(query: str, card: dict) -> bool:
    """Совпало ТОЛЬКО по синониму, и собственные названия тут ни при чём.

    «Teto Kasane» — это синоним клипа «Yababaina», у которого ни одно своё
    название на ответ не похоже: такое совпадение не значит ничего. А вот ответ
    «Наруто ТВ-1» (тоже синоним) засчитывается — собственное название «Наруто»
    в нём есть."""
    needle = norm_title(strip_year(query))
    if not needle:
        return True
    mains = [norm_title(strip_year(n)) for n in main_names(card)]
    for main in [m for m in mains if m]:
        if same_title(main, needle):
            return False                       # совпало собственным именем
        if f" {main} " in f" {needle} " or f" {needle} " in f" {main} ":
            return False                       # своё название есть в ответе
    return True


# ── Опечатка в ответе ────────────────────────────────────────────────────────
# «Gokukoku no Brunhildr» вместо «Brynhildr» — это тот же тайтл, набранный с
# ошибкой, а не другой: из-за одной буквы пропадали и постер, и все варианты
# названия (живой случай из пака пользователя). Условия нарочно жёсткие, иначе
# под «опечатку» попали бы соседние тайтлы франшизы:
#   • короткие названия не в счёт вовсе — в «Air» и «Aria» одна буква решает всё;
#   • слов должно быть поровну («Hellsing» и «Hellsing Ultimate» — разные вещи);
#   • номера сезонов совпадают буква в букву («Sword Art Online II» и «III»
#     отличаются ровно одним символом, но это разные тайтлы).
TYPO_MIN_LEN = 8                 # короче — сравниваем только слово в слово
TYPO_LONG_LEN = 20               # с этой длины прощаем две ошибки, а не одну
_RE_ROMAN = re.compile(r"^[ivxlcdm]+$")


def _numbering(words: list[str]) -> list[str]:
    """Номера из названия — арабские и римские. Они должны совпасть точно."""
    return [w for w in words if w.isdigit() or _RE_ROMAN.match(w)]


def _edits(a: str, b: str, limit: int) -> int:
    """Расстояние Левенштейна, но не дальше limit + 1: дальше нам всё равно."""
    stop = max(0, int(limit)) + 1
    prev = list(range(len(b) + 1))
    for i, ch in enumerate(a, 1):
        cur = [i]
        for j, other in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1,
                           prev[j - 1] + (ch != other)))
        if min(cur) >= stop:
            return stop
        prev = cur
    return min(prev[-1], stop)


def is_typo(a: str, b: str) -> bool:
    """Одно и то же название с точностью до опечатки (обе строки — уже
    нормализованные, см. norm_title)."""
    if not a or not b or a == b:
        return False
    if min(len(a), len(b)) < TYPO_MIN_LEN:
        return False
    limit = 2 if max(len(a), len(b)) >= TYPO_LONG_LEN else 1
    if abs(len(a) - len(b)) > limit:
        return False
    words_a, words_b = a.split(), b.split()
    if len(words_a) != len(words_b):
        return False
    if _numbering(words_a) != _numbering(words_b):
        return False
    return _edits(a, b, limit) <= limit


def glued(text: str) -> str:
    """Название без пробелов вовсе — «Tegami bachi» и «Tegamibachi» это одно и
    то же слово, разбитое на слоги по вкусу писавшего."""
    return str(text or "").replace(" ", "")


def same_title(a: str, b: str) -> bool:
    """Одно ли это название: слово в слово, с точностью до пробелов или до
    опечатки. Обе строки должны быть уже пропущены через
    norm_title(strip_year(...)).

    Пробелы прощаются только длинным названиям (тот же порог, что у опечаток):
    склеить «K-On!» до «kon» — это уже другое слово, а «Tegamibachi» короче
    восьми букв не бывает."""
    if not a:
        return False
    if a == b or is_typo(a, b):
        return True
    one, two = glued(a), glued(b)
    return one == two and len(one) >= TYPO_MIN_LEN


def match_score(query: str, card: dict) -> float:
    """Насколько карточка похожа на искомое название: 1.0 — точное совпадение
    хотя бы одного из имён (или оно же с опечаткой), ниже — по близости строк."""
    needle = norm_title(strip_year(query))
    if not needle:
        return 0.0
    best = 0.0
    for name in card_names(card):
        # Год в сравнении не участвует: Shikimori держит его прямо в названии у
        # части тайтлов («Могучий Атом (2003)»), а в паке его обычно нет.
        other = norm_title(strip_year(name))
        if not other:
            continue
        if same_title(needle, other):
            return 1.0
        best = max(best, difflib.SequenceMatcher(None, needle, other).ratio())
    return best


# Ниже этой близости чужое название считается просто другим тайтлом. Порог
# высокий нарочно: дописать «Наруто» в ответ про «Наруто: Ураганные хроники» —
# это уже неверный ответ, засчитанный игроку.
LOOSE_THRESHOLD = 0.92


def popularity(card: dict) -> float:
    """Насколько тайтл известен — та же «база индекса», по которой генератор
    паков расставляет цены (взвешенное число людей, у которых он в списках).

    Нужна там, где на один ответ приходится НЕСКОЛЬКО точных совпадений: у
    старых и малоизвестных записей названия сплошь и рядом совпадают с чужими.
    Нет статистики — ноль, и тогда выбор идёт по прежним правилам.

    Готовое число в поле popularity, если оно у карточки уже есть, важнее
    статистики списков — считать её заново незачем."""
    ready = (card or {}).get("popularity")
    if ready is not None:
        try:
            return float(ready)
        except (TypeError, ValueError):
            return 0.0
    try:
        from shikimori_api import index_base_from_statuses_stats
        return float(index_base_from_statuses_stats(
            (card or {}).get("statusesStats")) or 0.0)
    except Exception:  # noqa: BLE001 — без статистики просто нет предпочтения
        return 0.0


# Во сколько раз совпадение по синониму должно быть известнее совпадения по
# собственному названию, чтобы всё-таки победить. Живой случай — ответ «За
# гранью»: так зовётся и «Kyoukai no Kanata» (синонимом, 1,26 млн в списках), и
# OVA «Sweat Punch» (собственным русским названием, 53 тыс.) — разница в 24
# раза. Тройка выбрана с запасом: близкие по известности записи по-прежнему
# решаются в пользу собственного названия.
SYNONYM_POPULARITY_EDGE = 3.0


def _best_by_popularity(cards: list) -> Optional[dict]:
    """Самая известная карточка списка (при равенстве — первая: поиск Shikimori
    уже отранжировал выдачу сам)."""
    return max(cards, key=popularity) if cards else None


def pick_exact(own: list, syn: list) -> Optional[dict]:
    """Кого выбрать из ТОЧНЫХ совпадений: пришедших по собственному названию
    (own) и пришедших только из синонимов (syn).

    Обычно берётся собственное название — синонимы на Shikimori правит кто
    угодно. Но если синонимом совпал тайтл, который известен в разы лучше, верен
    он: «За гранью» — это «Kyoukai no Kanata», а не одноимённая OVA, про которую
    не слышал никто."""
    best_own = _best_by_popularity(own)
    best_syn = _best_by_popularity(syn)
    if best_own is None:
        return None
    if best_syn is not None and popularity(best_syn) >= max(
            1.0, popularity(best_own) * SYNONYM_POPULARITY_EDGE):
        return best_syn
    return best_own


# Во сколько раз клип должен быть известнее одноимённого тайтла, чтобы ответом
# признали всё-таки его. Живой случай — ответ «Shelter»: так зовут и знаменитый
# клип Porter Robinson (221 тыс. в списках), и никому не известный фильм 2015
# года (832), — и в пак вставлялась обложка фильма. Порог нарочно большой:
# правило «клип — не тайтл» этим не отменяется, а из него делается исключение
# для случаев, где иначе в ответ попадёт заведомо чужая обложка.
CLIP_POPULARITY_EDGE = 10.0


def famous_clip(clips: list, other: dict) -> Optional[dict]:
    """Клип, который известнее найденного тайтла в разы, — или None.

    Одноимённый клип отбирает ответ у тайтла только с очень большим перевесом:
    иначе в паке окажется обложка чужого фильма (см. CLIP_POPULARITY_EDGE).
    Если тайтла не нашлось вовсе, клип ответом не становится — правило «клип не
    бывает ответом» остаётся в силе, а вопрос просто не трогается."""
    best = _best_by_popularity(clips)
    if best is None:
        return None
    return best if popularity(best) >= max(
        1.0, popularity(other) * CLIP_POPULARITY_EDGE) else None


def pick_card(query: str, cards: list, strict: bool = True) -> Optional[dict]:
    """Та самая карточка тайтла — или None, если ответ на аниме не похож.

    Клипы и промо не рассматриваются вовсе — кроме одного случая, см.
    CLIP_POPULARITY_EDGE. Точных совпадений бывает несколько — выбор между ними
    разбирает pick_exact; нестрогое совпадение годится, только если точных не
    нашлось вовсе и строгость снята."""
    own, syn, loose, clips = [], [], [], []
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        score = match_score(query, card)
        if is_clip(card):
            # Клип в расчёт идёт, только если ответ совпал с его СОБСТВЕННЫМ
            # названием: по синонимам клипы ловят на себя имена персонажей
            # («Teto Kasane» — синоним клипа «Yababaina»).
            if score >= 1.0 and not synonym_only(query, card):
                clips.append(card)
            continue
        if score >= 1.0:
            (syn if synonym_only(query, card) else own).append(card)
        elif score > 0.0:
            loose.append((score, card))
    exact = pick_exact(own, syn)
    if exact is not None:
        return famous_clip(clips, exact) or exact
    if strict or not loose:
        return None
    best_score, best = max(loose, key=lambda pair: pair[0])
    return best if best_score >= LOOSE_THRESHOLD else None


# «Могучий Атом (2003)» → «Могучий Атом». Год в ответ не пишем вовсе (просьба
# пользователя): у части тайтлов Shikimori держит его прямо в названии, и в
# списке ответов это выглядит как ещё одна почти такая же строка.
_RE_YEAR_TAIL = re.compile(r"\s*[(\[]\s*(?:19|20)\d{2}\s*[)\]]\s*$")


def strip_year(text) -> str:
    """Название без хвостового «(2003)» — сколько бы их подряд ни стояло."""
    line = str(text or "").strip()
    while True:
        cut = _RE_YEAR_TAIL.sub("", line).strip()
        if cut == line:
            return line
        line = cut


def title_variants(card: dict, s: Optional[UpgradeSettings] = None) -> list[str]:
    """Названия тайтла, которые можно дописать в ответ.

    Берутся ВСЕ и всегда — ромадзи, английское, лицензионное, синонимы и русское
    (выбор их видов убран по просьбе пользователя: в паке нужен полный список).
    Порядок — как у генератора. Иероглифику не берём вовсе: ведущему её не
    прочитать, игроку не набрать (то же правило, что в animepack._dedup_answers).
    Год отрезаем: в ответе он не нужен, а Shikimori держит его в названии у части
    тайтлов."""
    out: list[str] = [card.get("name"), card.get("english"),
                      card.get("licenseNameRu")]
    out.extend(card.get("synonyms") or [])
    # Русское название дописываем последним: ответ мог быть записан ромадзи, и
    # тогда именно оно — самый нужный вариант.
    out.append(card.get("russian"))
    clean, seen = [], set()
    for name in out:
        text = strip_year(name)
        key = norm_title(text)
        if not text or not key or has_cjk(text) or key in seen:
            continue
        seen.add(key)
        clean.append(text)
    return clean


def answers_of(q_el: ET.Element) -> list[ET.Element]:
    right = child(q_el, "right")
    return children(right, "answer")


def _already_written(existing: list[str], variant: str) -> bool:
    """Есть ли это название в паке — пусть и внутри более длинного ответа.

    Сравниваем по нормализованным словам: вариант «Багровые осколки» уже
    написан в ответе «Багровые осколки - Nee», и дописывать его второй строкой
    незачем (просьба пользователя). Проверка идёт по целым словам, поэтому
    «Ди» не считается написанным из-за ответа «Дигимон»."""
    needle = norm_title(variant)
    if not needle:
        return True
    for text in existing:
        hay = norm_title(text)
        if hay and f" {needle} " in f" {hay} ":
            return True
    return False


def add_answers(q_el: ET.Element, tag, variants: list[str]) -> list[str]:
    """Дописывает варианты в <right>. То, что в паке уже написано (пусть и
    внутри другого ответа), не повторяет. Возвращает реально добавленное."""
    right = child(q_el, "right")
    if right is None:
        return []
    have = [(a.text or "") for a in children(right, "answer")]
    added = []
    for text in variants:
        if _already_written(have, text):
            continue
        have.append(text)
        el = ET.SubElement(right, tag("answer"))
        el.text = text
        added.append(text)
    return added


# Ответ, похожий на имя героя, а не на название: латиница в одно-три слова —
# ровно так имена пишут в паках («Mumei», «Teto Kasane», «Mio Akiyama»,
# «Remilia Scarlet»). Кириллицу сюда не берём НАРОЧНО: у персонажа
# «Naruto-kun» русское имя — «Наруто», и по нему проверка съела бы настоящий
# тайтл «Наруто». Латинское имя такого не даёт: у того же персонажа оно
# «Naruto-kun», а не «Naruto».
_RE_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")


def looks_like_character_name(text) -> bool:
    """Стоит ли на этот ответ переспросить базу персонажей."""
    line = str(text or "").strip()
    if not line or _RE_CYRILLIC.search(line) or has_cjk(line):
        return False
    words = norm_title(line).split()
    return 1 <= len(words) <= 3


def character_hit(query: str, chars: list) -> Optional[str]:
    """Имя персонажа, совпавшее с ответом слово в слово, — или None.

    Сравниваем только с латинским именем (см. looks_like_character_name):
    русское имя персонажа сплошь и рядом совпадает с русским названием тайтла,
    в котором он играет."""
    needle = norm_title(query)
    if not needle:
        return None
    for char in chars or []:
        if not isinstance(char, dict):
            continue
        name = str(char.get("name") or "").strip()
        if name and norm_title(name) == needle:
            return name
    return None


def exact_main(query: str, card: dict) -> bool:
    """Совпало ли с СОБСТВЕННЫМ названием тайтла слово в слово.

    Это и есть граница, за которой переспрашивать базу персонажей вредно:
    «Shiki», «Monster» и «Goblin Slayer» — настоящие аниме, у которых главный
    герой зовётся так же, и точный персонаж там находится всегда (проверено
    запросами). Раз собственное название тайтла совпало точь-в-точь — это
    тайтл, и мнение базы персонажей ничего не добавит.

    Опечатка сюда не входит НАРОЧНО (в отличие от is_exact): раз в ответе всё
    равно не то, что написано на Shikimori, у базы персонажей стоит спросить —
    вдруг это вообще имя героя, а тайтл подвернулся похожим."""
    needle = norm_title(strip_year(query))
    return bool(needle) and any(norm_title(strip_year(n)) == needle
                                for n in main_names(card))


def matched_by_typo(query: str, card: dict) -> bool:
    """Совпало ли название только с точностью до опечатки — ни одно имя карточки
    не написано так же, как ответ. Нужно, чтобы сказать об этом в лог: правка
    вносится молча, а буква в ответе всё-таки чужая."""
    needle = norm_title(strip_year(query))
    if not needle or not is_exact(query, card):
        return False
    return all(norm_title(strip_year(n)) != needle for n in card_names(card))


def is_exact(query: str, card: dict) -> bool:
    """Совпало ли название слово в слово (регистр, знаки и год не в счёт) — или
    оно же, но с опечаткой в букву-другую (см. is_typo).

    По этому признаку работают обе новые правки: и постер в ответе, и написание
    названия. Нестрогое совпадение сюда не годится — «Наруто» и «Наруто:
    Ураганные хроники» это разные тайтлы, и подставлять им общий постер или
    переписывать один под другой нельзя."""
    return match_score(query, card) >= 1.0


# «наруто - Nee» → голова «наруто» и хвост « - Nee»: в живых паках название
# отделено от песни обычным тире (см. _RE_DASH_TAIL).
_RE_HEAD_TAIL = re.compile(r"^(.*?)(\s+[—–-]\s+.*)$", re.DOTALL)


def _not_worse(was: str, now: str) -> bool:
    """Не понижаем заглавную букву в начале: «Mumei» → «mumei» это не
    исправление написания, а порча ответа (живой случай — у записи Shikimori
    японское название записано строчными)."""
    return not (was[:1].isupper() and now[:1].islower())


def recased(text: str, names: list[str]) -> Optional[str]:
    """Тот же ответ, но написанный как на Shikimori, — или None, если и так так.

    Меняем ТОЛЬКО регистр: «наруто» → «Наруто», «НАРУТО» → «Наруто». Если бы
    разрешили менять и знаки, ответ «Стальной алхимик» превратился бы в
    «Стальной алхимик: Братство» — это уже другой ответ, а не написание."""
    line = str(text or "").strip()
    if not line:
        return None
    for name in names:
        name = str(name or "").strip()
        if (name and line != name and line.casefold() == name.casefold()
                and _not_worse(line, name)):
            return name
    # «наруто - Nee»: правим голову, песню за тире не трогаем.
    m = _RE_HEAD_TAIL.match(line)
    if m:
        head, tail = m.group(1).strip(), m.group(2)
        for name in names:
            name = str(name or "").strip()
            if (name and head != name and head.casefold() == name.casefold()
                    and _not_worse(head, name)):
                return name + tail
    return None


def fix_answer_case(q_el: ET.Element, card: dict) -> list[tuple[str, str]]:
    """Переписывает ответы вопроса в написании Shikimori. Возвращает [(было,
    стало)] — пусто, если менять было нечего."""
    names = spelling_names(card)
    changed: list[tuple[str, str]] = []
    for el in answers_of(q_el):
        was = (el.text or "")
        now = recased(was, names)
        if now is None:
            continue
        el.text = now
        changed.append((was.strip(), now))
    return changed


# ─────────────────────────────────────────────────────────────────────────────
# Функция 4: постер тайтла в ответ
# ─────────────────────────────────────────────────────────────────────────────
def answer_content(q_el: ET.Element, tag) -> ET.Element:
    """Содержимое ответа вопроса — то, что показывают ПОСЛЕ ответа игроков.

    v5: <params><param name="answer" type="content">. Если такого параметра нет
    (в ответе не было ничего, кроме текста правильного ответа), заводим его.
    v4 сюда не заходит — там ответ живёт в <scenario> за маркером, см.
    scenario_answer_tail."""
    params = child(q_el, "params")
    if params is None:
        params = ET.SubElement(q_el, tag("params"))
    for param in children(params, "param"):
        if (param.get("name") or "") == "answer":
            return param
    return ET.SubElement(params, tag("param"),
                         {"name": "answer", "type": "content"})


def scenario_answer_tail(q_el: ET.Element, tag) -> Optional[ET.Element]:
    """<scenario> вопроса формата v4 с гарантированным маркером в конце.

    В v4 вопрос и ответ лежат в одном сценарии, а разделяет их <atom
    type="marker"/>: всё, что после него, показывается уже как ответ. Нет
    сценария — нет и v4-вопроса, возвращаем None."""
    scenario = child(q_el, "scenario")
    if scenario is None:
        return None
    if not any((a.get("type") or "") == "marker" for a in children(scenario,
                                                                  "atom")):
        ET.SubElement(scenario, tag("atom"), {"type": "marker"})
    return scenario


ANSWER_MEDIA_KINDS = ("image", "video", "audio", "html")


def has_answer_media(q_el: ET.Element) -> bool:
    """Есть ли в ответе своё медиа. Если есть — постер не ставим.

    Не только картинка: ролик или дорожка в ответе — это тоже готовое зрелище,
    которое автор пака собрал сам, и постер после него либо перебивает его, либо
    превращает ответ в слайд-шоу. Текст (в том числе реплика ведущего) за медиа
    не считается: рядом с ним постеру самое место."""
    params = child(q_el, "params")
    for param in children(params, "param"):
        if (param.get("name") or "") != "answer":
            continue
        for item in children(param, "item"):
            if (item.get("type") or "") in ANSWER_MEDIA_KINDS:
                return True
    scenario = child(q_el, "scenario")
    seen_marker = False
    for atom in children(scenario, "atom"):
        kind = (atom.get("type") or "")
        if kind == "marker":
            seen_marker = True
        elif seen_marker and kind in ANSWER_MEDIA_KINDS:
            return True
    return False


def add_poster(q_el: ET.Element, tag, ref: str) -> bool:
    """Кладёт картинку в ответ вопроса. False — класть было некуда.

    Формат берём тот, какой у вопроса: v5 — <item type="image" isRef="True">
    в параметре ответа, v4 — <atom type="image">@файл</atom> за маркером
    сценария. Таймера на постере нет: без duration он висит, пока ведущий не
    пойдёт дальше (просьба пользователя)."""
    if not ref:
        return False
    if child(q_el, "params") is None and child(q_el, "scenario") is not None:
        scenario = scenario_answer_tail(q_el, tag)
        if scenario is None:
            return False
        atom = ET.SubElement(scenario, tag("atom"), {"type": "image"})
        atom.text = "@" + ref
        return True
    item = ET.SubElement(answer_content(q_el, tag), tag("item"),
                         {"type": "image", "isRef": "True"})
    item.text = ref
    return True


def remove_poster(q_el: ET.Element, ref: str) -> bool:
    """Убирает из вопроса картинку, которую туда положил add_poster.

    Нужно, когда постер уже вписан в ответ, а скачать или закодировать его так и
    не вышло: ссылка на файл, которого в паке нет, — это дырка в вопросе."""
    if not ref:
        return False
    for parent in q_el.iter():
        for el in list(parent):
            if local(el.tag) in ("item", "atom") \
                    and (el.text or "").strip().lstrip("@") == ref:
                parent.remove(el)
                return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Функция 5: повторяющийся текст темы («Назвать аниме»)
# ─────────────────────────────────────────────────────────────────────────────
def question_items(q_el: ET.Element) -> list[tuple[ET.Element, ET.Element,
                                                   str, str]]:
    """Содержимое САМОГО вопроса: [(родитель, элемент, тип, текст)].

    v5 держит его в <param name="question"> элементами <item>, v4 — в
    <scenario> атомами до маркера (всё, что после маркера, показывается уже как
    ответ, и к вопросу отношения не имеет). Тип по умолчанию — text: и там, и
    там его у текста обычно не пишут вовсе."""
    out: list[tuple[ET.Element, ET.Element, str, str]] = []
    for params in children(q_el, "params"):
        for param in children(params, "param"):
            if (param.get("name") or "") != "question":
                continue
            for item in children(param, "item"):
                out.append((param, item, (item.get("type") or "text").lower(),
                            " ".join(str(item.text or "").split())))
    scenario = child(q_el, "scenario")
    for atom in children(scenario, "atom"):
        kind = (atom.get("type") or "text").lower()
        if kind == "marker":
            break
        out.append((scenario, atom, kind,
                    " ".join(str(atom.text or "").split())))
    return out


def question_text_blocks(q_el: ET.Element,
                         max_len: int = REPEAT_TEXT_MAX_LEN) -> dict[str, str]:
    """{нормализованный текст: как он написан} — короткие текстовые блоки
    вопроса. Длинные не берём вовсе: это уже сам вопрос, а не подпись к нему."""
    out: dict[str, str] = {}
    for _parent, _el, kind, text in question_items(q_el):
        key = norm_title(text)
        if kind != "text" or not key or len(text) > max(1, int(max_len)):
            continue
        out.setdefault(key, text)
    return out


def repeated_texts(questions: list, max_len: int = REPEAT_TEXT_MAX_LEN
                   ) -> list[str]:
    """Тексты, стоящие в КАЖДОМ вопросе темы, — в порядке первого вопроса.

    Тема из одного вопроса не в счёт: «в каждом» там значит «в единственном», и
    убирать по такому правилу нечего."""
    if len(questions or []) < REPEAT_MIN_QUESTIONS:
        return []
    first = question_text_blocks(questions[0], max_len)
    if not first:
        return []
    common = set(first)
    for q in questions[1:]:
        common &= set(question_text_blocks(q, max_len))
        if not common:
            return []
    return [text for key, text in first.items() if key in common]


def known_label_keys() -> set:
    """Известные подписи (KNOWN_LABELS) в сравнимом виде.

    Считается один раз на вызов — список короткий, а зовут функцию по разу на
    тему."""
    return {norm_title(text) for text in KNOWN_LABELS if norm_title(text)}


def known_labels_in(questions: list, max_len: int = REPEAT_TEXT_MAX_LEN
                    ) -> list[str]:
    """Известные подписи, встретившиеся в вопросах темы, — в порядке первого
    вопроса, где они попались.

    В отличие от repeated_texts, «в каждом вопросе» тут не требуется: подписи
    эти закрытым списком, и смысл у них один — сказать, что делать. Живой случай
    — тема «Hayami Saori»: «Назвать персонажа» стоит в семи вопросах из восьми, а
    восьмой спрашивает совсем другое; по правилу «в каждом» подпись оставалась
    во всех семи."""
    known = known_label_keys()
    out: dict[str, str] = {}
    for q in questions or []:
        for key, text in question_text_blocks(q, max_len).items():
            if key in known:
                out.setdefault(key, text)
    return list(out.values())


def drop_text_blocks(q_el: ET.Element, keys: set) -> list[str]:
    """Убирает из вопроса текстовые блоки с такими текстами. Возвращает то, что
    реально убрано.

    Вопрос без содержимого не оставляем никогда: если убрать пришлось бы всё,
    что в нём есть, — не трогаем вовсе (пустой вопрос игре показать нечем)."""
    items = question_items(q_el)
    doomed = [(parent, el, text) for parent, el, kind, text in items
              if kind == "text" and norm_title(text) in (keys or set())]
    if not doomed or len(doomed) >= len(items):
        return []
    for parent, el, _text in doomed:
        parent.remove(el)
    return [text for _p, _el, text in doomed]


# ─────────────────────────────────────────────────────────────────────────────
# Текст под звук: блок текста и следующий за ним отрывок играют одновременно
# ─────────────────────────────────────────────────────────────────────────────
# Звук в v5 зовётся audio, в v4 старым паком — voice (SIPackages.AtomTypes).
AUDIO_KINDS = ("audio", "voice")
# Текст на экране и реплика ведущего: и то, и другое игра держит по таймеру и по
# нему же решает, включать ли следующий кусок (GameLogic.OnContentScreenText /
# OnContentReplicText — оба смотрят на waitForFinish).
TEXT_KINDS = ("text", "say")


def merge_text_with_audio(q_el: ET.Element) -> list[str]:
    """Текстовому блоку, за которым СРАЗУ идёт звук, ставит «играть
    одновременно». Возвращает тексты блоков, которые пришлось поправить.

    Так это записано у SIGame: v5 — waitForFinish="False" у <item> (по
    умолчанию true, ContentItem.cs), v4 — time="-1" у <atom> (Question.cs:
    WaitForFinish = atom.AtomTime != -1). Ни новых элементов, ни <params> тут не
    заводится — правится атрибут у того, что в вопросе уже есть, поэтому обоим
    форматам это безопасно.

    Уже включённое одновременное воспроизведение не трогаем: пользователь просил
    доделать за автором, а не переписать сделанное им."""
    items = question_items(q_el)
    done: list[str] = []
    for i, (_parent, el, kind, text) in enumerate(items[:-1]):
        if kind not in TEXT_KINDS or items[i + 1][2] not in AUDIO_KINDS:
            continue
        if local(el.tag) == "atom":
            if str(el.get("time") or "").strip() == "-1":
                continue
            el.set("time", "-1")
        else:
            if str(el.get("waitForFinish") or "").strip().lower() == "false":
                continue
            el.set("waitForFinish", "False")
        done.append(text)
    return done


# ─────────────────────────────────────────────────────────────────────────────
# Функция «Удалить пустые вопросы»
# ─────────────────────────────────────────────────────────────────────────────
def is_empty_question(q_el: ET.Element) -> bool:
    """Пусто ли в САМОМ вопросе: ни текста, ни картинки, ни звука, ни ролика.

    Ответ не в счёт нарочно (просьба пользователя: «даже если есть ответ»): на
    экране такой вопрос — пустота, играть в него нечем, сколько бы вариантов
    ответа под ним ни лежало. Содержимое берётся тем же question_items, что и
    уборка повторов: у v4 всё, что стоит ПОСЛЕ маркера, показывается уже как
    ответ, и вопросом не считается."""
    return not any(text.strip() for _parent, _el, _kind, text
                   in question_items(q_el))


def empty_questions(root: ET.Element) -> list[tuple]:
    """Пустые вопросы пака: [(раунд, тема, номер, контейнер, вопрос)].

    Контейнер (<questions>) отдаётся вместе с вопросом: в ElementTree элемент
    не знает своего родителя, а удалять его придётся именно из него. Номер —
    порядковый номер вопроса в паке, по нему правка встаёт в общую таблицу."""
    out: list[tuple] = []
    number = 0
    for r_idx, rnd in enumerate(children(child(root, "rounds"), "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        for theme in children(child(rnd, "themes"), "theme"):
            box = child(theme, "questions")
            for q in children(box, "question"):
                if is_empty_question(q):
                    out.append((rname, str(theme.get("name") or ""), number,
                                box, q))
                number += 1
    return out


def drop_empty_themes(root: ET.Element) -> list[tuple[str, str]]:
    """Убирает темы, оставшиеся без единого вопроса (и раунды без тем).

    Тему без вопросов SIGame показывает пустой строкой на табло, а раунд без тем
    и вовсе некуда играть. Возвращает [(раунд, тема)] убранного."""
    gone: list[tuple[str, str]] = []
    rounds_el = child(root, "rounds")
    for r_idx, rnd in enumerate(children(rounds_el, "round")):
        rname = rnd.get("name") or f"Раунд {r_idx + 1}"
        themes_el = child(rnd, "themes")
        for theme in children(themes_el, "theme"):
            if children(child(theme, "questions"), "question"):
                continue
            themes_el.remove(theme)
            gone.append((rname, str(theme.get("name") or "")))
        if rounds_el is not None and not children(themes_el, "theme"):
            rounds_el.remove(rnd)
    return gone


# ─────────────────────────────────────────────────────────────────────────────
# Функция «Удалить неиспользуемые файлы»
# ─────────────────────────────────────────────────────────────────────────────
def entry_basename(name: str) -> str:
    """Человеческое имя файла из имени записи архива: без папок и без
    percent-кодирования («Images/%D0%BA.jpg» → «к.jpg»)."""
    return unquote(str(name or "").replace("\\", "/")).rsplit("/", 1)[-1]


def referenced_names(root: ET.Element) -> set:
    """Имена файлов, на которые в content.xml есть хоть какая-то ссылка.

    Смотрим и текст элементов, и ВСЕ значения атрибутов, а не только <item> и
    <atom>: логотип пака лежит атрибутом <package logo>, и удалить его из-за
    того, что вопросы на него не ссылаются, было бы порчей пака. Ошибаться тут
    можно только в одну сторону — лишний «занятый» файл просто останется лежать,
    а лишнее удаление это дырка в паке.

    Ключи — casefold: в архиве имя записано как записал автор, а в ссылке — как
    ему было удобно, и регистр у них расходится сплошь и рядом."""
    out: set = set()
    for el in root.iter():
        raw_values = [el.text or ""]
        raw_values += [str(v) for v in (el.attrib or {}).values()]
        for raw in raw_values:
            text = str(raw).strip().lstrip("@")
            if not text or len(text) > 400:
                continue
            name = entry_basename(text)
            if name:
                out.add(name.casefold())
    return out


def is_media_entry(name: str) -> bool:
    """Медиа ли это (по расширению). Служебные части пака — content.xml,
    Texts/authors.xml, [Content_Types].xml — сюда не попадают никогда."""
    return os.path.splitext(entry_basename(name))[1].lower() in MEDIA_EXTS


def unused_entries(names, refs: set, keep=()) -> list[str]:
    """Записи архива, на которые в паке нет ни одной ссылки.

    keep — имена записей, которые трогать нельзя, чем бы дело ни кончилось
    (пережатые картинки и дорожки: их ссылки уже переписаны на новое имя, и по
    старому их никто не зовёт — а сами они в пак всё-таки идут)."""
    keep = {str(k) for k in (keep or ())}
    out: list[str] = []
    for name in names:
        if name in keep or not is_media_entry(name):
            continue
        if entry_basename(name).casefold() not in refs:
            out.append(name)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Функция «Сжать тяжёлое аудио»
# ─────────────────────────────────────────────────────────────────────────────
def run_hidden(cmd: list, should_stop: Optional[Callable[[], bool]] = None,
               timeout: float = AUDIO_TIMEOUT,
               capture: bool = False) -> tuple[int, str]:
    """Запускает ffmpeg/ffprobe без окна консоли и с оглядкой на «Стоп».

    Ждём короткими шагами и убиваем процесс по первому же сигналу: иначе кнопка
    «Стоп» ждала бы конца кодирования всей дорожки. Вывод забирается только
    когда он нужен (ffprobe): у ffmpeg он уходит в никуда, и переполнить трубу
    ему нечем."""
    kw = ({"creationflags": CREATE_NO_WINDOW | _LOW_PRIORITY}
          if os.name == "nt" else {})
    sink = subprocess.PIPE if capture else subprocess.DEVNULL
    try:
        proc = subprocess.Popen(cmd, stdout=sink, stderr=subprocess.DEVNULL,
                                **kw)
    except Exception as e:  # noqa: BLE001 — нет ffmpeg, нет прав и т.п.
        return 1, str(e)
    deadline = time.monotonic() + max(1.0, float(timeout))
    while True:
        try:
            out, _err = proc.communicate(timeout=0.2)
            # Кодировку задаём явно: по локали Windows это была бы cp1251, и
            # ответ ffprobe пришёл бы искажённым.
            return proc.returncode, (out or b"").decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            pass
        if (should_stop and should_stop()) or time.monotonic() > deadline:
            try:
                proc.kill()
                proc.communicate(timeout=5)
            except Exception:  # noqa: BLE001 — процесс мог уже умереть сам
                pass
            return 1, ""


def parse_probe_kbps(text: str, size: int = 0) -> int:
    """Битрейт (кбит/с) из ответа ffprobe. 0 — узнать не вышло.

    ffprobe печатает `ключ=значение`, сначала по дорожке, потом по контейнеру, и
    у каждого второго формата половина значений — «N/A». Берём первое настоящее
    число, а если его нет вовсе — считаем сами по размеру и длительности (так
    отвечают, например, wav и часть ogg)."""
    rates, duration = [], 0.0
    for line in str(text or "").splitlines():
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key == "bit_rate" and value.isdigit() and int(value) > 0:
            rates.append(int(value))
        elif key == "duration":
            try:
                duration = max(duration, float(value))
            except ValueError:
                pass
    if rates:
        return int(round(rates[0] / 1000.0))
    if duration > 0.1 and size > 0:
        return int(round(size * 8 / duration / 1000.0))
    return 0


def parse_probe_codec(text: str) -> str:
    """Имя видеокодека из ответа ffprobe («av1», «h264»; «» — узнать не вышло).

    Ответ у ffprobe тут в одну строку `codec_name=av1`, но обложка альбома в
    mp3 тоже считается видеодорожкой, так что первое непустое значение и
    берём — поток спрашивается уже отфильтрованным (-select_streams v:0)."""
    for line in str(text or "").splitlines():
        key, _, value = line.partition("=")
        if key.strip() == "codec_name" and value.strip():
            return value.strip().lower()
    return ""


# ─────────────────────────────────────────────────────────────────────────────
# Апгрейд целиком
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class _MediaPlan:
    """Что делаем с одной записью архива: имя нового файла раздано заранее, до
    кодирования, — оно не должно зависеть от того, чья кодировка кончилась
    первой (кодируем-то в несколько потоков)."""
    name: str                  # имя записи в архиве, как оно там лежит
    size: int                  # сколько весит сейчас
    decoded: str               # человеческое имя файла («кадр.jpg»)
    ext: str                   # расширение исходника
    new_decoded: str           # каким станет («кадр.avif»)
    folder: str                # папка в архиве («Images»)
    percent: bool              # было ли имя записи percent-кодированным

    @property
    def new_name(self) -> str:
        """Имя новой записи в архиве.

        Обычно меняется одно расширение — тогда и берём имя ИСХОДНОЙ записи как
        есть, поменяв ему хвост: так новое имя закодировано ровно так же, как
        было старое, чем бы его ни кодировал автор пака. Игра ищет файл по имени
        из content.xml, прогоняя его через Uri.EscapeUriString, и любое
        расхождение — это «File ... was not found in the game package!».

        Слепое quote(..., safe="") этим и ломалось: скобки уходили в %28/%29, а
        SIQuester и SIGame оставляют их как есть. Имя целиком кодируем только
        тогда, когда сами его изменили (занятое имя развели суффиксом « (2)»)."""
        raw_base = self.name.replace("\\", "/").rpartition("/")[2]
        if self.new_decoded == os.path.splitext(self.decoded)[0] \
                + os.path.splitext(self.new_decoded)[1]:
            raw = os.path.splitext(raw_base)[0] \
                + os.path.splitext(self.new_decoded)[1]
        else:
            raw = escape_uri_string(self.new_decoded) if self.percent \
                else self.new_decoded
        return f"{self.folder}/{raw}" if self.folder else raw


@dataclass
class _MediaDone:
    """Ответ кодировщика. Пустой out — файл остаётся прежним, а note скажет
    почему (лог пишется в основном потоке и по порядку)."""
    out: str = ""              # готовый временный файл
    size: int = 0              # сколько он весит
    was: int = 0               # битрейт исходника (только у аудио)
    codec: str = ""            # кодек исходника (только у видео)
    note: str = ""             # что сказать в лог


@dataclass
class _PosterJob:
    """Постер тайтла, который качается и кодируется в фоне. Имя файла известно
    сразу, поэтому ссылку в вопрос пишут, не дожидаясь самой картинки; uses —
    вопросы, куда её уже вписали (если постер не дастся, ссылку оттуда надо
    убрать)."""
    ref: str = ""              # имя файла в паке
    url: str = ""              # откуда качать
    title: str = ""            # чей постер (для лога)
    key: str = ""              # ключ в общей кладовой обложек (poster_cache)
    names: tuple = ()          # названия тайтла — по ним ищется обложка на TMDB
    year: int = 0
    movie: bool = False        # аниме-фильм (kind == "movie"), а не сериал —
                                # для порядка поиска раздела на TMDB
    out: str = ""              # временный файл с готовым AVIF
    size: int = 0              # сколько он весит (0 — не вышло)
    note: str = ""             # что сказать в лог, если не вышло
    future: Optional[object] = None
    uses: list = field(default_factory=list)   # [(вопрос, строка отчёта)]


def _drop(path: str) -> None:
    """Убирает временный файл, если он есть."""
    if path and os.path.exists(path):
        try:
            os.remove(path)
        except OSError:
            pass


class PackUpgrader:
    """Читает .siq, правит content.xml и пишет результат отдельным файлом.

    Медиа из архива не распаковывается вовсе: записи копируются как есть, в том
    же виде и с тем же сжатием, — на паке в сотню мегабайт это секунды, а не
    минуты перекодирования. Исключение — тяжёлые картинки при включённой третьей
    функции: только они и достаются наружу, чтобы уйти в AVIF под лимит."""

    def __init__(self, path: str, s: UpgradeSettings,
                 log: Optional[Callable[[str], None]] = None,
                 progress: Optional[Callable[[int, int, str], None]] = None,
                 should_stop: Optional[Callable[[], bool]] = None,
                 api=None):
        self.path = str(path or "")
        self.s = s
        self._log = log or (lambda _m: None)
        self._progress = progress or (lambda _d, _t, _m: None)
        self._should_stop = should_stop or (lambda: False)
        self._api = api
        # Один и тот же тайтл спрашиваем ровно раз: в паке из 60 вопросов одно
        # аниме встречается по нескольку раз, а каждый запрос — это лимитер
        # Shikimori (5/с и 80/мин). Ключ — (книга?, название): по книгам и по
        # аниме это два разных поиска с разными ответами.
        self._cache: dict[tuple, Optional[dict]] = {}
        # То же для персонажей: {ответ: имя героя или None}.
        self._chars: dict[str, Optional[str]] = {}
        # Постеры: {номер тайтла: задание} — файл на тайтл один, сколько бы
        # вопросов про него в паке ни было. Качаются и кодируются они в фоне,
        # потоки живут в self._pool (см. _poster_job).
        self._posters: dict[str, Optional[_PosterJob]] = {}
        self._pool: Optional[ThreadPoolExecutor] = None
        self._poster_temps: list[str] = []
        # Клиент TMDB заводится по первой надобности: None — ещё не пробовали,
        # False — ключа нет или сервер сердится, больше не ходим.
        self._tmdb = None
        # Новые файлы, которых в исходном архиве не было: {имя записи: временный
        # файл}. Кладутся в пак при записи, потом временные удаляются.
        self._extra: dict[str, str] = {}
        self._taken_names: set[str] = set()
        # Имена, выданные пережатым картинкам и дорожкам: в архиве их ещё нет, а
        # занимать их второй раз уже нельзя (картинки считаются раньше аудио).
        self._new_names: set[str] = set()

    # ── мелочи ────────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        try:
            self._log(msg)
        except Exception:  # pragma: no cover — лог не должен ронять работу
            pass

    def stopped(self) -> bool:
        try:
            return bool(self._should_stop())
        except Exception:  # pragma: no cover
            return False

    @property
    def api(self):
        """Клиент базы названий — Shikimori, тот же, что у генератора
        (лимитер, ретраи, ключи полей). Создаётся лениво: без функции названий
        сеть не нужна вовсе."""
        if self._api is None:
            from animepack_api import ShikimoriApi
            self._api = ShikimoriApi()
        return self._api

    # ── поиск тайтла ──────────────────────────────────────────────────────
    def find_title(self, query: str, book: bool = False) -> Optional[dict]:
        """Карточка тайтла по названию. book — искать книгу (мангу, манхву,
        ранобэ), а не аниме: так делается на темах, где это написано в названии
        самой темы."""
        book = bool(book)
        key = (book, norm_title(query))
        if key in self._cache:
            return self._cache[key]
        what = "мангу" if book else "аниме"
        try:
            if book:
                cards = self.api.search_mangas_by_name(query)
            else:
                cards = self.api.search_animes_by_name(query)
        except AttributeError:
            # Клиент без такого поиска (старый или подставной) — не повод падать.
            cards = []
        except Exception as e:  # noqa: BLE001 — один упавший запрос не повод
            self.log(f"{self.s.source_name} не ответил(а) про {what} "
                     f"«{query}»: {e}")
            cards = []
        card = pick_card(query, cards, strict=self.s.strict_match)
        if card is not None and is_clip(card):
            self.log(f"«{query}» — это клип, а не {what}: одноимённый тайтл "
                     f"известен в разы хуже, беру клип.")
        self._cache[key] = card
        return card

    def find_character(self, query: str) -> Optional[str]:
        """Имя персонажа, совпавшее с ответом слово в слово, или None.

        Кэш — как у тайтлов: одного и того же героя в паке спрашивают по
        нескольку раз, а запрос идёт через общий лимитер Shikimori."""
        key = norm_title(query)
        if key in self._chars:
            return self._chars[key]
        try:
            chars = self.api.search_characters_by_name(query)
        except Exception as e:  # noqa: BLE001 — упавший запрос не повод падать
            self.log(f"Персонажи Shikimori не ответили про «{query}»: {e}")
            chars = []
        name = character_hit(query, chars)
        self._chars[key] = name
        return name

    # ── работа ────────────────────────────────────────────────────────────
    def run(self, out_path: Optional[str] = None) -> UpgradeResult:
        started = time.monotonic()
        if not os.path.isfile(self.path):
            raise UpgradeError(f"Файл не найден: {self.path}")
        problems = self.s.validate()
        if problems:
            raise UpgradeError("\n\n".join(problems))

        cname, data = read_content(self.path)
        root, ns = parse_content(data)
        tag = tag_fn(ns)
        result = UpgradeResult(source=self.path)

        if not list(iter_questions(root)):
            raise UpgradeError("В паке нет ни одного вопроса — править нечего.")
        # Пустые вопросы выкидываются ДО всего остального: их не за чем ни
        # расколдовывать, ни искать по ним тайтлы, а нумерация вопросов должна
        # считаться уже по тому, что в паке останется.
        if self.s.drop_empty_questions:
            self._do_empty(root, result)

        questions = list(iter_questions(root))
        result.questions = len(questions)
        if not questions:
            raise UpgradeError("В паке нет ни одного вопроса — править нечего.")
        self.log(f"В паке {len(questions)} вопрос(ов).")

        # Медиа считаем заранее: оно идёт вторым этапом, а полоса прогресса
        # должна знать про него с самого начала.
        heavy = self._heavy_images() if self.s.compress_images else []
        result.heavy_images = len(heavy)
        heavy_audio = self._heavy_audio() if self.s.compress_audio else []
        result.heavy_audio = len(heavy_audio)
        heavy_video = self._video_entries() if self.s.compress_video else []
        result.heavy_video = len(heavy_video)
        steps = (len(questions) + len(heavy) + len(heavy_audio)
                 + len(heavy_video))

        # Повторы считаются по теме целиком, поэтому идут отдельным проходом до
        # общего цикла — сети он не трогает и стоит доли секунды.
        if self.s.strip_repeated_text:
            self._do_repeats(root, questions, result)

        try:
            for i, (rname, tname, q) in enumerate(questions):
                if self.stopped():
                    result.cancelled = True
                    break
                price = question_price(q)
                if self.s.strip_specials:
                    self._do_special(q, rname, tname, price, i, result)
                if self.s.merge_text_audio:
                    self._do_merge(q, rname, tname, price, i, result)
                if self.s.add_titles:
                    self._do_titles(q, tag, rname, tname, price, i, result)
                self._progress(i + 1, steps, f"вопрос {i + 1}/{len(questions)}")
        finally:
            # Постеры готовятся фоном, пока идёт опрос базы названий, — тут они
            # догоняют. Даже если цикл сорвался, потоки надо закрыть.
            self._finish_posters(result)

        images: dict[str, tuple[str, str]] = {}
        if heavy and not result.cancelled:
            images = self._do_images(heavy, root, result, len(questions), steps)
        if heavy_audio and not result.cancelled:
            images.update(self._do_audio(heavy_audio, root, result,
                                         len(questions) + len(heavy), steps))
        if heavy_video and not result.cancelled:
            images.update(self._do_video(
                heavy_video, root, result,
                len(questions) + len(heavy) + len(heavy_audio), steps))

        # Мусор ищем ПОСЛЕДНИМ: к этому моменту ссылки уже переписаны на
        # пережатые файлы, а постеры вписаны в ответы — иначе только что
        # добавленное посчиталось бы неиспользуемым.
        dropped: set = set()
        if self.s.drop_unused and not result.cancelled:
            dropped = self._do_unused(root, result, images)

        result.added_bytes = sum(os.path.getsize(p) for p in self._extra.values()
                                 if os.path.exists(p))
        try:
            if result.cancelled:
                result.elapsed = time.monotonic() - started
                return result
            result.path = self._write(root, ns, cname, out_path, images,
                                      dropped)
        finally:
            temps = [tmp for _new_name, tmp in images.values()]
            temps += list(self._extra.values())
            # Постеры, которые не дались (в _extra их нет), тоже за собой
            # прибираем: временный файл мог остаться от сорванного кодирования.
            temps += self._poster_temps
            for tmp in temps:
                _drop(tmp)
        result.elapsed = time.monotonic() - started
        return result

    def _do_empty(self, root, result) -> None:
        """Выкидывает из пака вопросы, в которых пусто.

        Весь пак разом не сносим никогда: если пустыми оказались ВСЕ вопросы,
        значит, содержимое лежит как-то иначе, а не «пак пустой», — и трогать
        такой файл вслепую нельзя."""
        doomed = empty_questions(root)
        if not doomed:
            return
        total = sum(1 for _rname, _tname, _q in iter_questions(root))
        if len(doomed) >= total:
            self.log(f"Пустыми выглядят все {total} вопрос(ов) пака — не трогаю "
                     f"ни одного: пустой пак игре не открыть.")
            return
        for rname, tname, number, box, q in doomed:
            box.remove(q)
            answers = [str(a.text or "").strip() for a in answers_of(q)]
            answers = [a for a in answers if a]
            result.empties.append(Change(
                kind="empty", round_name=rname, theme_name=tname,
                price=question_price(q),
                before=(f"пусто, ответ «{_shorten(answers[0], 40)}»"
                        if answers else "пусто, и ответа нет"),
                after="вопрос удалён", order=number))
        self.log(f"Пустых вопросов удалено: {len(doomed)}.")
        for rname, tname in drop_empty_themes(root):
            result.dropped_themes += 1
            self.log(f"«{rname}» · «{tname}»: тема осталась без вопросов — "
                     f"убрал и её.")

    def _do_repeats(self, root, questions, result) -> None:
        """Убирает текст, стоящий в каждом вопросе темы («Назвать аниме»), и
        известные подписи (KNOWN_LABELS) — эти и там, где в одном вопросе темы
        подписи всё-таки нет.

        Номер вопроса берётся из общего списка пака: правки всех функций стоят
        в таблице в одном порядке — в том, в каком идут в файле."""
        order_of = {id(q): i for i, (_r, _t, q) in enumerate(questions)}
        for rname, tname, theme_questions in iter_themes(root):
            if self.stopped():
                return
            texts = repeated_texts(theme_questions, self.s.repeat_text_max_len)
            every = {norm_title(t) for t in texts}
            known: set = set()
            if self.s.strip_known_labels:
                labels = known_labels_in(theme_questions,
                                         self.s.repeat_text_max_len)
                known = {norm_title(t) for t in labels} - every
                texts = texts + [t for t in labels if norm_title(t) in known]
            if not texts:
                continue
            keys = every | known
            self.log(f"«{tname}»: убираю "
                     + ", ".join(f"«{t}»" for t in texts))
            for q in theme_questions:
                for text in drop_text_blocks(q, keys):
                    known_here = norm_title(text) in known
                    result.repeats.append(Change(
                        kind="repeat", round_name=rname, theme_name=tname,
                        price=question_price(q), before=text,
                        after=("убран (известная подпись)" if known_here else
                               "убран (стоял в каждом вопросе темы)"),
                        order=order_of.get(id(q), 0)))

    def _do_merge(self, q, rname, tname, price, order, result) -> None:
        """Текст, за которым сразу идёт звук, играет вместе с ним."""
        for text in merge_text_with_audio(q):
            result.merged.append(Change(
                kind="merge", round_name=rname, theme_name=tname, price=price,
                before=_shorten(text) or "текстовый блок",
                after="играет одновременно со звуком", order=order))

    def _do_special(self, q, rname, tname, price, order, result) -> None:
        key = special_key(q)
        if not key:
            return
        label = SPECIAL_LABELS.get(key, key)
        if key == "secretnoquestion" and not self.s.strip_no_question:
            result.skipped_specials.append(Change(
                kind="special", round_name=rname, theme_name=tname, price=price,
                before=label, after="оставлен как есть", order=order))
            return
        if not has_question_content(q):
            # Обычным вопрос сделать нечем: самого вопроса в нём нет.
            result.skipped_specials.append(Change(
                kind="special", round_name=rname, theme_name=tname, price=price,
                before=label, after="оставлен как есть (нет самого вопроса)",
                order=order))
            return
        make_simple(q)
        result.specials.append(Change(
            kind="special", round_name=rname, theme_name=tname, price=price,
            before=label, after="обычный вопрос", order=order))

    def _do_titles(self, q, tag, rname, tname, price, order, result) -> None:
        answers = answers_of(q)
        if not answers:
            return
        queries = answer_queries([a.text for a in answers],
                                 use_others=self.s.use_other_answers,
                                 min_len=self.s.min_query_len)
        if not queries:
            return
        result.checked_answers += 1
        # На теме про мангу первым спрашивается книга: обложка аниме в таком
        # вопросе неверна, а у манхвы аниме может не быть вовсе. Не нашлась —
        # доищем названия по аниме, но постер из него уже не возьмём.
        book_theme = bool(self.s.book_themes) and is_book_theme(tname)
        card, hit, from_book = None, "", False
        for query in queries:
            if self.stopped():
                return
            if book_theme:
                card = self.find_title(query, book=True)
                if card is not None:
                    hit, from_book = query, True
                    break
            card = self.find_title(query)
            if card is not None:
                hit = query
                break
        if card is None:
            result.not_found += 1
            return
        title = str(card.get("russian") or card.get("name") or "")
        # Ответ мог быть именем героя, а не названием: тогда «Mumei» находит
        # одноимённый клип, и вопрос про персонажа обрастал бы чужими
        # названиями и постером. Переспрашиваем базу персонажей — но только
        # когда ответ похож на имя И собственное название тайтла с ним НЕ
        # совпало точь-в-точь: иначе запрос уходил бы на каждый «Shiki» и
        # «Monster» впустую (и, если ему верить, ломал бы их).
        if (self.s.check_characters and looks_like_character_name(hit)
                and not exact_main(hit, card)):
            name = self.find_character(hit)
            if name:
                result.skipped_titles.append(Change(
                    kind="character", round_name=rname, theme_name=tname,
                    price=price, before=hit,
                    after=f"это имя персонажа, не тайтл (нашёлся «{title}»)",
                    title=name, order=order))
                return
        # Постер и написание названия — только на точном совпадении: при
        # нестрогом поиске карточка может быть от сиквела, и подставлять ему
        # чужой постер (или переписывать под него ответ) нельзя.
        exact = is_exact(hit, card)
        if exact:
            result.exact_titles += 1
            # Совпало не буква в букву, а с точностью до опечатки или пробела:
            # правку вносим, но пусть будет видно, что в ответе пака написано
            # не то («Gokukoku no Brunhildr» вместо «Brynhildr», «Tegami bachi»
            # вместо «Tegamibachi»).
            if matched_by_typo(hit, card):
                result.typo_titles += 1
                self.log(f"«{tname}»: ответ «{hit}» написан не так, как на "
                         f"{self.s.source_name} — это «{title}», дописываю "
                         f"названия и ставлю постер.")

        place = dict(round_name=rname, theme_name=tname, price=price,
                     title=title, order=order)
        # Написание правим ДО дописывания вариантов: иначе «наруто» осталось бы
        # в паке рядом с только что дописанным правильным «Наруто», и проверка
        # «уже написано» посчитала бы их разными строками.
        if exact and self.s.fix_case:
            for was, now in fix_answer_case(q, card):
                result.recased.append(Change(kind="case", before=was, after=now,
                                             **place))

        first = (answers[0].text or "").strip()
        variants = title_variants(card)[:max(1, self.s.max_variants)]
        added = add_answers(q, tag, variants)
        if added:
            result.titles.append(Change(
                kind="title", before=first,
                after=" / ".join([first] + added), added=added, **place))

        # На теме про мангу обложка ставится только та, что нашлась по книге:
        # тянуть в такой вопрос постер аниме пользователь просил не надо.
        if exact and self.s.add_poster and not self.stopped():
            if book_theme and not from_book:
                self.log(f"«{tname}»: тема про книги, а «{title}» нашёлся "
                         f"только аниме — обложку не ставлю.")
            else:
                self._do_poster(q, tag, card, result, place, book=from_book)

    # ── постер в ответе ───────────────────────────────────────────────────
    def _do_poster(self, q, tag, card: dict, result, place: dict,
                   book: bool = False) -> None:
        if has_answer_media(q):
            # В ответе уже своё медиа (картинка, ролик, дорожка) — постер туда
            # не лезет: он перебил бы то, что автор пака показывает сам.
            return
        job = self._poster_job(card, book=book)
        if job is None:
            return
        if not add_poster(q, tag, job.ref):
            return
        # Размер постера пока неизвестен — он ещё качается; допишется в
        # _finish_posters, когда файл будет готов.
        change = Change(kind="poster", before="в ответе не было картинки",
                        after="постер", **place)
        result.posters.append(change)
        job.uses.append((q, change))

    def _poster_job(self, card: dict, book: bool = False) -> Optional[_PosterJob]:
        """Ставит постер тайтла (обложку книги) в очередь на скачивание и
        кодирование. Возвращает задание с уже известным ИМЕНЕМ файла — ссылку в
        вопрос можно писать сразу, не дожидаясь картинки.

        Скачивание с кодированием уходят в фон нарочно: пока постеры готовятся,
        основной ход успевает спросить Shikimori про следующие вопросы, а он
        отвечает не быстрее двух раз в секунду (лимитер). Раньше эти два
        ожидания стояли в очередь друг за другом и вместе занимали больше
        времени, чем вся остальная работа (замер на «Лёгкий аниме пак.siq»:
        постеры 73 с, сеть 47 с из 129 с всего).

        Файл на тайтл один: одно и то же аниме встречается в паке по нескольку
        раз, а весит постер как весь остальной прирост пака. Номера у аниме и
        манги свои, поэтому в ключ и в имя файла идёт ещё и вид записи — иначе
        манга №20 забрала бы себе постер аниме №20."""
        num = str(card.get("malId") or card.get("id") or "").strip()
        poster = card.get("poster") if isinstance(card.get("poster"), dict) else {}
        url = str((poster or {}).get("originalUrl")
                  or (poster or {}).get("mainUrl") or "").strip()
        names = tuple(str(card.get(k) or "").strip()
                      for k in ("name", "english", "russian")
                      if str(card.get(k) or "").strip())
        # Ссылки может не быть вовсе — тогда обложка ещё найдётся в общей
        # кладовой (её мог скачать генератор паков) или на TMDB.
        if not num or not (url or names):
            return None
        key = ("manga:" if book else "") + num
        if key in self._posters:
            # За тем же постером второй раз не ходим — ни удачно, ни впустую.
            return self._posters[key]
        prefix = "shiki_manga_" if book else "shiki_"
        ref = self._free_poster_name(
            f"{prefix}{safe_filename(num, 'poster')}_poster.avif")
        self._taken_names.add(ref.lower())
        try:
            year = int(str((card.get("airedOn") or {}).get("year")
                           or (card.get("releasedOn") or {}).get("year") or 0))
        except (TypeError, ValueError):
            year = 0
        job = _PosterJob(ref=ref, url=url,
                         title=str(card.get("russian") or card.get("name") or num),
                         key=poster_cache.anime_key(num, book=book),
                         names=names, year=year,
                         # У аниме-фильма (kind == "movie") TMDB ищет
                         # надёжнее сперва по разделу "movie", а не "tv" — та
                         # же логика, что у поиска обложки в генераторе паков.
                         movie=str(card.get("kind") or "") == "movie",
                         out=os.path.join(_temp_dir(),
                                          f"siqposter_{uuid.uuid4().hex}.avif"))
        self._posters[key] = job
        job.future = self._poster_pool().submit(self._poster_file, job)
        return job

    def _poster_pool(self) -> ThreadPoolExecutor:
        """Потоки под постеры. Их немного: качается постер быстро, а кодируется
        тем же libaom, что и картинки пака, — больше трёх сразу только толкались
        бы за процессор."""
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=media_jobs(IMAGE_JOBS),
                thread_name_prefix="siqposter")
        return self._pool

    def _poster_bytes(self, job: _PosterJob) -> tuple[bytes, str]:
        """Исходные байты обложки: общая кладовая → Shikimori → TMDB.

        Кладовая та же самая, что у вкладки «Генерация аниме-пака» (просьба
        пользователя: обе вкладки берут обложки из одного места), и скачанное
        сюда же и складывается — в следующий раз качать его не придётся ни
        здесь, ни там."""
        if job.key:
            data, ext = poster_cache.find(job.key)
            if data:
                return data, ext
        data, ext = b"", ".jpg"
        if job.url:
            try:
                data, ext = self._fetch(job.url), self._url_ext(job.url)
            except Exception as e:  # noqa: BLE001 — попробуем ещё TMDB
                job.note = f"Постер «{job.title}»: {e}"
        if not data and job.names and not self.stopped():
            url = self._tmdb_url(job)
            if url:
                try:
                    data, ext = self._fetch(url), self._url_ext(url)
                    job.note = ""
                except Exception as e:  # noqa: BLE001
                    job.note = f"Обложка «{job.title}» с TMDB: {e}"
        if data and job.key:
            poster_cache.put(job.key, data, ext)
        return data, ext

    def _tmdb_url(self, job: _PosterJob) -> str:
        """Ссылка на обложку с themoviedb.org («» — ключа нет или не нашлась).

        Ключ тот же, что во вкладке «Генерация аниме-пака»: он лежит в
        настройках программы, отдельного поля здесь нет нарочно."""
        api = getattr(self, "_tmdb", None)
        if api is None:
            key = poster_cache.settings_tmdb_key()
            if not key:
                self._tmdb = False
                return ""
            from animepack_api import TmdbApi
            session = getattr(self._api, "session", None) if self._api else None
            api = self._tmdb = TmdbApi(session, key=key)
        if api is False:
            return ""
        try:
            return api.poster_url(job.names, year=job.year, movie=job.movie)
        except Exception as e:  # noqa: BLE001 — запасной источник не обязателен
            job.note = f"TMDB: {e}"
            self._tmdb = False       # сердится — второй раз не идём
            return ""

    def _poster_file(self, job: _PosterJob) -> int:
        """Скачивает и кодирует один постер, возвращает размер готового файла
        (0 — не вышло). Зовётся из потока: правит только своё задание."""
        if self.stopped():
            return 0
        data, ext = self._poster_bytes(job)
        if not data:
            if not job.note:
                job.note = f"Обложка «{job.title}» не нашлась, пропускаю."
            return 0
        raw = os.path.join(_temp_dir(), f"siqposter_{uuid.uuid4().hex}{ext}")
        try:
            with open(raw, "wb") as f:
                f.write(data)
            if not self._to_avif(raw, job.out, IMAGE_LIMIT_KB):
                _drop(job.out)      # ffmpeg мог оставить недописанный файл
                job.note = f"Постер «{job.title}» не закодировался, пропускаю."
                return 0
            job.size = int(os.path.getsize(job.out))
        except Exception as e:  # noqa: BLE001 — одна картинка не повод падать
            job.note = f"Постер «{job.title}»: {e}"
            return 0
        finally:
            _drop(raw)
        return job.size

    def _finish_posters(self, result) -> None:
        """Дожидается постеров и разбирается с теми, что не дались: ссылку из
        вопроса убираем, строку из отчёта тоже — иначе пак ссылался бы на файл,
        которого в нём нет."""
        pool, self._pool = self._pool, None
        if pool is None:
            return
        jobs = [j for j in self._posters.values() if j is not None]
        if self.stopped():
            for job in jobs:
                if job.future is not None:
                    job.future.cancel()
        pool.shutdown(wait=True)
        dead: set = set()
        for job in jobs:
            self._poster_temps.append(job.out)
            if job.size > 0:
                # Имя ASCII — percent-кодировать нечего, ссылка и запись
                # совпадают.
                self._extra[f"{POSTER_DIR}/{job.ref}"] = job.out
                for _q, change in job.uses:
                    change.after = f"постер, {fmt_size(job.size)}"
                continue
            if job.note and not self.stopped():
                self.log(job.note)
            for q, change in job.uses:
                remove_poster(q, job.ref)
                dead.add(id(change))
        if dead:
            result.posters = [ch for ch in result.posters if id(ch) not in dead]

    def _free_poster_name(self, want: str) -> str:
        """Имя, которого в паке ещё нет (в архиве уже может лежать одноимённый
        файл — подменять чужую картинку нельзя)."""
        if not self._taken_names:
            try:
                with zipfile.ZipFile(self.path) as zf:
                    self._taken_names = {
                        unquote(n.replace("\\", "/")).rsplit("/", 1)[-1].lower()
                        for n in zf.namelist()}
            except (OSError, zipfile.BadZipFile):  # pragma: no cover
                self._taken_names = {""}
        base, ext = os.path.splitext(want)
        name = want
        for n in range(2, 1000):
            if name.lower() not in self._taken_names:
                break
            name = f"{base} ({n}){ext}"
        return name

    @staticmethod
    def _url_ext(url: str, default: str = ".jpg") -> str:
        ext = os.path.splitext(str(url or "").split("?")[0])[1].lower()
        return ext if ext in (".jpg", ".jpeg", ".png", ".webp") else default

    def _fetch(self, url: str) -> bytes:
        """Байты картинки. Сессия — общая с клиентом Shikimori (там уже стоят
        заголовки и таймауты), своя заводится только без него."""
        session = getattr(self._api, "session", None) if self._api else None
        if session is None:
            session = getattr(self.api, "session", None)
        if session is None:  # pragma: no cover — клиент всегда с сессией
            import requests
            session = requests.Session()
        resp = session.get(url, timeout=(10, 60))
        resp.raise_for_status()
        return resp.content

    # ── картинки ──────────────────────────────────────────────────────────
    def _heavy_images(self) -> list[tuple[str, int]]:
        """Записи архива с картинками тяжелее порога: [(имя в архиве, байт)]."""
        limit = int(max(0.1, float(self.s.image_min_mb)) * 1024 * 1024)
        heavy: list[tuple[str, int]] = []
        try:
            with zipfile.ZipFile(self.path) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.file_size <= limit:
                        continue
                    name = unquote(info.filename.replace("\\", "/"))
                    if os.path.splitext(name)[1].lower() in COMPRESS_EXTS:
                        heavy.append((info.filename, info.file_size))
        except (OSError, zipfile.BadZipFile) as e:
            raise UpgradeError(f"Файл не читается как .siq: {e}") from e
        return heavy

    def _plans(self, heavy, new_ext: str) -> list[_MediaPlan]:
        """Что с чем делать: имена новых файлов раздаём ЗАРАНЕЕ и по порядку.

        Само кодирование идёт потом и в несколько потоков, а имена должны
        получаться те же самые, в каком бы порядке кодировки ни закончились."""
        plans: list[_MediaPlan] = []
        try:
            with zipfile.ZipFile(self.path) as zf:
                # Занятые ИМЕНА файлов, без папок: ссылка в content.xml зовёт
                # файл по имени, и одноимённые в разных папках — это уже спор.
                taken = {unquote(n.replace("\\", "/")).rsplit("/", 1)[-1].lower()
                         for n in zf.namelist()}
                # Постеры и уже пережатые картинки кладутся раньше, и в архиве
                # их ещё нет — но имена уже заняты.
                taken |= {n.rsplit("/", 1)[-1].lower() for n in self._extra}
                taken |= set(self._new_names)
        except (OSError, zipfile.BadZipFile) as e:
            raise UpgradeError(f"Файл не читается как .siq: {e}") from e
        for name, size in heavy:
            folder, _, raw_base = name.replace("\\", "/").rpartition("/")
            decoded = unquote(raw_base)
            base, ext = os.path.splitext(decoded)
            # Имя может быть занято: в паках рядом с «кадр.webp» лежит
            # «кадр.avif» (вопрос и ответ одного тайтла). Подменять чужой файл
            # нельзя — берём соседнее свободное имя, ссылка всё равно
            # переписывается на него.
            new_decoded = f"{base}{new_ext}"
            for n in range(2, 100):
                if new_decoded.lower() not in taken:
                    break
                new_decoded = f"{base} ({n}){new_ext}"
            else:  # pragma: no cover — сотня одноимённых файлов в одном паке
                self.log(f"«{decoded}»: свободного имени не нашлось, пропускаю.")
                continue
            taken.add(new_decoded.lower())
            self._new_names.add(new_decoded.lower())
            plans.append(_MediaPlan(
                name=name, size=size, decoded=decoded, ext=ext,
                new_decoded=new_decoded, folder=folder,
                percent=(raw_base != decoded)))
        return plans

    def _run_jobs(self, plans: list, work, base_step: int, steps: int,
                  label: str, jobs: int) -> list:
        """Гоняет work(plan) по нескольким потокам и отдаёт ответы В ПОРЯДКЕ
        plans: отчёт и имена файлов не должны зависеть от того, какое
        кодирование закончилось первым.

        Работа тут — внешний ffmpeg, поэтому потоки Python ему не мешают: они
        только ждут процессы (GIL на это время отпущен)."""
        total = len(plans)
        out: list = [None] * total
        jobs = max(1, min(int(jobs), total))
        if jobs == 1:
            for j, plan in enumerate(plans):
                self._progress(base_step + j + 1, steps, f"{label} {j + 1}/{total}")
                out[j] = work(plan)
            return out
        with ThreadPoolExecutor(max_workers=jobs,
                                thread_name_prefix="siqmedia") as pool:
            futures = {pool.submit(work, plan): j for j, plan in enumerate(plans)}
            for done, fut in enumerate(as_completed(futures), start=1):
                out[futures[fut]] = fut.result()
                self._progress(base_step + done, steps, f"{label} {done}/{total}")
        return out

    def _extract(self, plan: _MediaPlan, prefix: str) -> str:
        """Достаёт запись из архива во временный файл (свой архив на поток:
        один объект ZipFile на несколько потоков не рассчитан)."""
        raw = os.path.join(_temp_dir(),
                           f"{prefix}_{uuid.uuid4().hex}{plan.ext}")
        with zipfile.ZipFile(self.path) as zf, open(raw, "wb") as f:
            f.write(zf.read(plan.name))
        return raw

    def _do_images(self, heavy, root, result, base_step: int,
                   steps: int) -> dict:
        """Пережимает тяжёлые картинки и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому AVIF)} —
        сам архив собирается позже, в _write."""
        self.log(f"Картинок тяжелее {self.s.image_min_mb:g} МБ: {len(heavy)}.")
        plans = self._plans(heavy, ".avif")
        made = self._run_jobs(plans, self._compress_one, base_step, steps,
                              "картинка", media_jobs(IMAGE_JOBS))
        done: dict[str, tuple[str, str]] = {}
        for plan, got in zip(plans, made):
            if got is None or not got.out:
                if got is not None and got.note and not self.stopped():
                    self.log(got.note)
                continue
            result.saved_bytes += plan.size - got.size
            result.images.append(Change(
                kind="image", theme_name=plan.decoded, price=0,
                before=f"{plan.ext.lstrip('.') or '?'}, {fmt_size(plan.size)}",
                after=f"avif, {fmt_size(got.size)}",
                title=plan.new_decoded,
                # Картинки идут после всех вопросов — так они и стоят в таблице.
                order=result.questions + len(result.images)))
            done[plan.name] = (plan.new_name, got.out)
        if self.stopped():
            result.cancelled = True
        if done:
            # Ссылка в content.xml зовёт файл по имени, и после переименования
            # её надо перевести на .avif — иначе пак останется без картинок.
            retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                                 if p.name in done})
        return done

    def _compress_one(self, plan: _MediaPlan) -> Optional[_MediaDone]:
        """Одна картинка: AVIF под лимит. Пустой out — оставляем как было.

        Зовётся из потока: ничего общего с соседями не трогает, всё нужное уже
        разложено по plan, а сообщение для лога отдаётся ответом."""
        if self.stopped():
            return None
        raw = ""
        out = os.path.join(_temp_dir(), f"siqimg_{uuid.uuid4().hex}.avif")
        try:
            raw = self._extract(plan, "siqimg")
            if not self._to_avif(raw, out):
                _drop(out)          # ffmpeg мог оставить недописанный файл
                return _MediaDone(note=f"«{plan.decoded}»: сжать не вышло, "
                                       f"оставляю как есть.")
            new_size = os.path.getsize(out)
            if new_size >= plan.size:
                # Так бывает с крошечными PNG-скриншотами: пережатие только
                # прибавило бы весу.
                _drop(out)
                return _MediaDone(note=f"«{plan.decoded}»: после сжатия не "
                                       f"легче, оставляю.")
        except (OSError, zipfile.BadZipFile) as e:
            _drop(out)
            return _MediaDone(note=f"«{plan.decoded}»: {e}")
        finally:
            _drop(raw)
        return _MediaDone(out=out, size=new_size)

    def _to_avif(self, raw: str, out: str, limit_kb: Optional[int] = None) -> bool:
        """Кодирование — общее с генератором паков и «Обработкой» (avif_fit:
        libaom, tune=iq, подбор CQ под лимит, при нужде ужимание разрешения).
        Настройки те же «быстрые»: cpu-used 8, четыре прохода, сторона 1280.

        limit_kb — под сколько ужимать; по умолчанию это настройка сжатия
        картинок пака, у постера свой лимит (тот же, что у генератора)."""
        from avif_fit import fit_to_limit, start_cq_guess
        limit = max(10, int(limit_kb if limit_kb else self.s.image_limit_kb))
        start = None
        try:
            from config import Image
            with Image.open(raw) as im:
                w, h = im.size
            if max(w, h) > IMAGE_MAX_SIDE:
                k = IMAGE_MAX_SIDE / float(max(w, h))
                w, h = max(1, int(w * k)), max(1, int(h * k))
            start = start_cq_guess(w, h, limit)
        except Exception:  # noqa: BLE001 — без Pillow просто идём с CQ=0
            start = None
        return fit_to_limit(raw, out, limit,
                            speed=max(0, min(8, int(self.s.image_speed))),
                            passes=IMAGE_FIT_PASSES, start_cq=start,
                            max_side=IMAGE_MAX_SIDE,
                            should_stop=self._should_stop)

    # ── аудио ─────────────────────────────────────────────────────────────
    def _heavy_audio(self) -> list[tuple[str, int]]:
        """Записи архива со звуком тяжелее порога: [(имя в архиве, байт)]."""
        limit = int(max(0.1, float(self.s.audio_min_mb)) * 1024 * 1024)
        heavy: list[tuple[str, int]] = []
        try:
            with zipfile.ZipFile(self.path) as zf:
                for info in zf.infolist():
                    if info.is_dir() or info.file_size <= limit:
                        continue
                    name = unquote(info.filename.replace("\\", "/"))
                    if os.path.splitext(name)[1].lower() in AUDIO_EXTS:
                        heavy.append((info.filename, info.file_size))
        except (OSError, zipfile.BadZipFile) as e:
            raise UpgradeError(f"Файл не читается как .siq: {e}") from e
        return heavy

    def _do_audio(self, heavy, root, result, base_step: int,
                  steps: int) -> dict:
        """Перекодирует тяжёлые дорожки в opus и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому opus)} — в
        том же виде, что и картинки: архив собирается позже, в _write."""
        self.log(f"Аудио тяжелее {self.s.audio_min_mb:g} МБ: {len(heavy)}.")
        target = nearest_bitrate(self.s.audio_kbps)
        plans = self._plans(heavy, ".opus")
        made = self._run_jobs(plans, self._compress_audio_one, base_step, steps,
                              "аудио", media_jobs(AUDIO_JOBS))
        done: dict[str, tuple[str, str]] = {}
        for plan, got in zip(plans, made):
            if got is None or not got.out:
                if got is not None and got.note and not self.stopped():
                    self.log(got.note)
                continue
            result.saved_audio_bytes += plan.size - got.size
            result.audios.append(Change(
                kind="audio", theme_name=plan.decoded, price=0,
                before=f"{plan.ext.lstrip('.') or '?'}"
                       + (f", {got.was} кбит" if got.was else "")
                       + f", {fmt_size(plan.size)}",
                after=f"opus {target} кбит, {fmt_size(got.size)}",
                title=plan.new_decoded,
                # Медиа идёт в таблице после вопросов, следом за картинками.
                order=result.questions + result.heavy_images
                + len(result.audios)))
            done[plan.name] = (plan.new_name, got.out)
        if self.stopped():
            result.cancelled = True
        if done:
            retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                                 if p.name in done})
        return done

    def _compress_audio_one(self, plan: _MediaPlan) -> Optional[_MediaDone]:
        """Одна дорожка: opus на заданном битрейте. Пустой out — оставляем как
        было. Зовётся из потока, как и _compress_one."""
        if self.stopped():
            return None
        target = nearest_bitrate(self.s.audio_kbps)
        raw, was = "", 0
        out = os.path.join(_temp_dir(), f"siqaud_{uuid.uuid4().hex}.opus")
        try:
            raw = self._extract(plan, "siqaud")
            was = self._audio_kbps(raw, plan.size)
            # С включённой нормализацией обе оговорки «не трогаю» снимаются:
            # ради неё дорожку и перекодируют, а пропущенная дорожка осталась бы
            # с прежней громкостью — то есть громче или тише всех соседних.
            norm = bool(self.s.audio_norm)
            if was and was <= target and not norm:
                # Перекод тут только испортил бы звук: opus на 192 из mp3 на 128
                # весит примерно столько же, а качества уже не вернуть.
                _drop(out)
                return _MediaDone(note=f"«{plan.decoded}»: и так {was} кбит — "
                                       f"не трогаю.")
            if not self._to_opus(raw, out):
                _drop(out)          # ffmpeg мог оставить недописанный файл
                return _MediaDone(note=f"«{plan.decoded}»: перекодировать не "
                                       f"вышло, оставляю как есть.")
            new_size = os.path.getsize(out)
            if new_size >= plan.size and not norm:
                _drop(out)
                return _MediaDone(note=f"«{plan.decoded}»: после перекода не "
                                       f"легче, оставляю.")
        except (OSError, zipfile.BadZipFile) as e:
            _drop(out)
            return _MediaDone(note=f"«{plan.decoded}»: {e}")
        finally:
            _drop(raw)
        return _MediaDone(out=out, size=new_size, was=was)

    def _audio_kbps(self, raw: str, size: int = 0) -> int:
        """Битрейт исходной дорожки в килобитах (0 — узнать не вышло).

        Спрашиваем ffprobe: перекодировать дорожку, которая и так не богаче
        целевого битрейта, — значит просто испортить звук, ничего не выиграв."""
        code, out = run_hidden(
            [FFPROBE, "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate:format=bit_rate,duration",
             "-of", "default=noprint_wrappers=1", raw],
            self._should_stop, timeout=60.0, capture=True)
        if code != 0:
            return 0
        return parse_probe_kbps(out, size)

    def _to_opus(self, raw: str, out: str) -> bool:
        """Кодирование звука — то же, что в генераторе паков и «Обработке»:
        libopus с переменным битрейтом и фиксом раскладки каналов (libopus не
        берёт «боковые» раскладки). Громкость трогаем, только если это включено
        настройкой: в готовом паке её уже выставил автор, и двигать её вслепую
        нельзя.

        Картинки внутри файла (обложка альбома в mp3) отбрасываются: в opus им
        всё равно не лечь, а ffmpeg на них спотыкается."""
        kbps = nearest_bitrate(self.s.audio_kbps)
        code, _out = run_hidden(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
             "-vn", "-af", audio_filter_chain(self.s), "-c:a", "libopus",
             "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio", out],
            self._should_stop)
        return code == 0 and os.path.exists(out) and os.path.getsize(out) > 0

    # ── видео ─────────────────────────────────────────────────────────────
    def _video_entries(self) -> list[tuple[str, int]]:
        """Записи архива с видео, которые надо посмотреть: [(имя, байт)].

        С галочкой «кодек не AV1» сюда идут ВСЕ ролики, сколько бы они ни
        весили: тяжёлый он или нет, решается по кодеку, а кодек виден только
        после распаковки (ffprobe читает файл, а не запись архива). Без неё —
        только те, что тяжелее порога, и лишнего никто не распаковывает."""
        limit = int(max(0.1, float(self.s.video_min_mb)) * 1024 * 1024)
        take_all = bool(self.s.video_non_av1)
        heavy: list[tuple[str, int]] = []
        try:
            with zipfile.ZipFile(self.path) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    if not take_all and info.file_size <= limit:
                        continue
                    name = unquote(info.filename.replace("\\", "/"))
                    if os.path.splitext(name)[1].lower() in VIDEO_EXTS:
                        heavy.append((info.filename, info.file_size))
        except (OSError, zipfile.BadZipFile) as e:
            raise UpgradeError(f"Файл не читается как .siq: {e}") from e
        return heavy

    def _do_video(self, heavy, root, result, base_step: int,
                  steps: int) -> dict:
        """Перекодирует ролики в AV1 и переписывает ссылки на них.

        Возвращает {имя записи в архиве: (новое имя, путь к готовому mp4)} — в
        том же виде, что картинки и аудио: архив собирается позже, в _write."""
        why = f"тяжелее {self.s.video_min_mb:g} МБ"
        if self.s.video_non_av1:
            why += " или не в AV1"
        self.log(f"Роликов под перекод ({why}): {len(heavy)}.")
        plans = self._plans(heavy, ".mp4")
        made = self._run_jobs(plans, self._compress_video_one, base_step, steps,
                              "видео", media_jobs(VIDEO_JOBS))
        done: dict[str, tuple[str, str]] = {}
        for plan, got in zip(plans, made):
            if got is None or not got.out:
                if got is not None and got.note and not self.stopped():
                    self.log(got.note)
                continue
            result.saved_video_bytes += plan.size - got.size
            height = nearest_height(self.s.video_height)
            result.videos.append(Change(
                kind="video", theme_name=plan.decoded, price=0,
                before=f"{plan.ext.lstrip('.') or '?'}"
                       + (f", {got.codec}" if got.codec else "")
                       + f", {fmt_size(plan.size)}",
                after=f"av1 crf {max(0, min(63, int(self.s.video_crf)))}"
                      + (f", {height}p" if height else "")
                      + f", {fmt_size(got.size)}",
                title=plan.new_decoded,
                # Медиа идёт в таблице после вопросов: картинки, дорожки, ролики.
                order=result.questions + result.heavy_images
                + len(result.audios) + len(result.videos)))
            done[plan.name] = (plan.new_name, got.out)
        if self.stopped():
            result.cancelled = True
        if done:
            retarget_refs(root, {p.decoded: p.new_decoded for p in plans
                                 if p.name in done})
        return done

    def _compress_video_one(self, plan: _MediaPlan) -> Optional[_MediaDone]:
        """Один ролик: AV1 + opus. Пустой out — оставляем как было.

        Зовётся из потока, как и картинки с дорожками. Решение «трогать или
        нет» принимается уже здесь: тяжёлый файл берём всегда, лёгкий — только
        если он не в AV1 и это разрешено настройкой."""
        if self.stopped():
            return None
        limit = int(max(0.1, float(self.s.video_min_mb)) * 1024 * 1024)
        raw, codec = "", ""
        out = os.path.join(_temp_dir(), f"siqvid_{uuid.uuid4().hex}.mp4")
        try:
            raw = self._extract(plan, "siqvid")
            if plan.size <= limit:
                codec = self._video_codec(raw)
                if not codec:
                    return _MediaDone(note=f"«{plan.decoded}»: кодек не "
                                           f"опознан, не трогаю.")
                if codec == VIDEO_TARGET_CODEC:
                    return _MediaDone(note=f"«{plan.decoded}»: и так AV1, "
                                           f"легче порога — не трогаю.")
            else:
                codec = self._video_codec(raw)
            if not self._to_av1(raw, out):
                _drop(out)          # ffmpeg мог оставить недописанный файл
                return _MediaDone(note=f"«{plan.decoded}»: перекодировать не "
                                       f"вышло, оставляю как есть.")
            new_size = os.path.getsize(out)
            if new_size >= plan.size:
                _drop(out)
                return _MediaDone(note=f"«{plan.decoded}»: после перекода не "
                                       f"легче, оставляю.")
        except (OSError, zipfile.BadZipFile) as e:
            _drop(out)
            return _MediaDone(note=f"«{plan.decoded}»: {e}")
        finally:
            _drop(raw)
        return _MediaDone(out=out, size=new_size, codec=codec)

    def _video_codec(self, raw: str) -> str:
        """Кодек первой видеодорожки файла («» — узнать не вышло)."""
        code, out = run_hidden(
            [FFPROBE, "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name",
             "-of", "default=noprint_wrappers=1", raw],
            self._should_stop, timeout=60.0, capture=True)
        if code != 0:
            return ""
        return parse_probe_codec(out)

    def _video_filter(self) -> list[str]:
        """`-vf` под выбранную высоту (пусто — разрешение не трогаем).

        Ролик только уменьшается: min с высотой источника не даст растянуть
        480p до «тысячи восьмидесяти» — это был бы вес без единого лишнего
        пикселя. Ширина считается сама и остаётся чётной (-2), иначе libsvtav1
        откажется кодировать."""
        height = nearest_height(self.s.video_height)
        if not height:
            return []
        return ["-vf", f"scale=-2:'min({height},ih)':flags=bicubic"]

    def _to_av1(self, raw: str, out: str) -> bool:
        """Перекод ролика — те же флаги, что во вкладке «Обработка»
        (workers.ProcessWorker._av1_encoder_args) и в генераторе паков:
        libsvtav1, keyint=-1 и scd=1 (ключевые кадры только на сменах сцены),
        crf и пресет из настроек. Звук — тот же opus и с той же нормализацией,
        что у дорожек пака, иначе ролик звучал бы громче соседних вопросов."""
        crf = max(0, min(63, int(self.s.video_crf)))
        preset = max(0, min(13, int(self.s.video_preset)))
        kbps = nearest_bitrate(self.s.audio_kbps)
        cmd = ([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", raw,
                # 0:V? — только настоящее видео: обложки и вложения в av1 не
                # переложить, а ffmpeg на них спотыкается (то же, что
                # workers._map_av_args).
                "-map", "0:V?", "-map", "0:a?",
                "-c:v", "libsvtav1", "-crf", str(crf), "-preset", str(preset),
                "-svtav1-params", f"tune={VIDEO_TUNE}:keyint=-1:scd=1",
                "-pix_fmt", VIDEO_PIX_FMT]
               + self._video_filter()
               + ["-af", audio_filter_chain(self.s), "-c:a", "libopus",
                  "-b:a", f"{kbps}k", "-vbr", "on", "-application", "audio",
                  "-movflags", "+faststart", out])
        code, _out = run_hidden(cmd, self._should_stop, timeout=VIDEO_TIMEOUT)
        return code == 0 and os.path.exists(out) and os.path.getsize(out) > 0

    # ── неиспользуемые файлы ──────────────────────────────────────────────
    def _do_unused(self, root, result, media: dict) -> set:
        """Находит медиа, на которое в паке нет ни одной ссылки, и возвращает
        имена записей, которые в новый архив писать не надо.

        Зовётся ПОСЛЕ всех правок content.xml: ссылки к этому моменту уже
        переписаны на пережатые файлы, а постеры уже вписаны в ответы. media —
        то, что пережато: старое имя записи там сменилось на новое, и по
        старому её, конечно, никто не зовёт."""
        refs = referenced_names(root)
        # Имена, которые пак получит взамен пережатых, тоже считаются занятыми:
        # ссылка на них есть, просто зовут они другой файл.
        try:
            with zipfile.ZipFile(self.path) as zf:
                names = [i.filename for i in zf.infolist() if not i.is_dir()]
                sizes = {i.filename: int(i.file_size) for i in zf.infolist()}
        except (OSError, zipfile.BadZipFile) as e:
            raise UpgradeError(f"Файл не читается как .siq: {e}") from e
        doomed = unused_entries(names, refs, keep=set(media or {}))
        if not doomed:
            self.log("Неиспользуемых файлов в паке нет.")
            return set()
        # Весь пак разом не сносим никогда: если «неиспользуемым» вышло всё
        # медиа, значит ссылки записаны как-то иначе, а не пак из одного мусора.
        media_total = sum(1 for n in names if is_media_entry(n))
        if media_total and len(doomed) >= media_total:
            self.log(f"Неиспользуемыми выглядят все {media_total} файл(ов) "
                     f"медиа — не трогаю ни одного: так не бывает.")
            return set()
        for name in doomed:
            size = sizes.get(name, 0)
            result.saved_unused_bytes += size
            result.unused.append(Change(
                kind="unused", theme_name=entry_basename(name), price=0,
                before=fmt_size(size), after="файл удалён (ссылок на него нет)",
                title=name,
                order=result.questions + result.heavy_images
                + len(result.audios) + len(result.videos) + len(result.unused)))
        self.log(f"Неиспользуемых файлов удалено: {len(doomed)} "
                 f"({fmt_size(result.saved_unused_bytes)}).")
        return set(doomed)

    # ── запись ────────────────────────────────────────────────────────────
    def _out_path(self, out_path: Optional[str]) -> str:
        if out_path:
            target = out_path
        else:
            folder = (self.s.out_dir or "").strip() or os.path.dirname(self.path)
            base = os.path.splitext(os.path.basename(self.path))[0]
            name = safe_filename(f"{base}{OUT_SUFFIX}", "Пак") + ".siq"
            target = os.path.join(folder, name)
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        return str(unique_path(target))

    def _write(self, root, ns: str, cname: str, out_path: Optional[str],
               images: Optional[dict] = None,
               dropped: Optional[set] = None) -> str:
        """Пишет новый .siq: правленый content.xml плюс все прочие записи как
        есть. Исходный файл не трогается — на случай, если правка не понравится.

        images — {имя записи: (новое имя, путь к готовому файлу)}: такие записи
        подменяются пережатыми, остальные копируются байт в байт. dropped —
        имена записей, которые в новый пак не идут вовсе (мусор без ссылок)."""
        images = images or {}
        dropped = dropped or set()
        if ns:
            # Иначе ElementTree расставит по всему файлу префиксы ns0:, и пак
            # перестанет открываться в SIGame.
            ET.register_namespace("", ns)
        xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        target = self._out_path(out_path)
        try:
            with zipfile.ZipFile(self.path) as src, \
                    zipfile.ZipFile(target, "w") as dst:
                dst.writestr(cname, xml, zipfile.ZIP_DEFLATED)
                for info in src.infolist():
                    if (info.filename == cname or info.is_dir()
                            or info.filename in dropped):
                        continue
                    made = images.get(info.filename)
                    if made:
                        # Сжатая картинка: имя новое (.avif), сжимать её ещё и
                        # архиватором незачем — AVIF уже сжат.
                        with open(made[1], "rb") as f:
                            dst.writestr(made[0], f.read(), zipfile.ZIP_STORED)
                        continue
                    # Копируем запись КАК ЕСТЬ, вместе с её способом сжатия:
                    # медиа в паках лежит уже сжатым (opus/avif/mp4), и разжимать
                    # его, чтобы тут же сжать обратно, — чистая трата времени.
                    if not copy_zip_entry(src, dst, info):
                        dst.writestr(copy.copy(info), src.read(info.filename))
                # Файлы, которых в исходном паке не было (постеры из ответов).
                for name, tmp in (self._extra or {}).items():
                    if not os.path.exists(tmp):
                        continue
                    with open(tmp, "rb") as f:
                        dst.writestr(name, f.read(), zipfile.ZIP_STORED)
        except (OSError, zipfile.BadZipFile) as e:
            raise UpgradeError(f"Не удалось записать пак: {e}") from e
        return target


# ─────────────────────────────────────────────────────────────────────────────
# Примеры изменений («покажи по три с каждой функции»)
# ─────────────────────────────────────────────────────────────────────────────
def _shorten(text: str, limit: int = 70) -> str:
    line = " ".join(str(text or "").split())
    return line if len(line) <= limit else line[:limit - 1] + "…"


def example_lines(result: UpgradeResult, limit: int = 3) -> list[str]:
    """Готовые строки отчёта: по нескольку примеров с каждой функции.

    Пустая функция тоже отчитывается — «ничего не нашлось» это ответ, а не
    повод промолчать."""
    lines: list[str] = []

    lines.append(f"Спецвопросов расколдовано: {len(result.specials)}.")
    for change in result.specials[:limit]:
        lines.append(f"  • {change.place}: «{change.before}» → {change.after}")
    if not result.specials:
        lines.append("  • примеров нет: спецвопросов в паке не нашлось.")
    if result.skipped_specials:
        lines.append(f"  • пропущено {len(result.skipped_specials)}: "
                     f"{_shorten(result.skipped_specials[0].after)}.")

    lines.append(f"Ответов дополнено названиями: {len(result.titles)}.")
    for change in result.titles[:limit]:
        added = ", ".join(change.added)
        lines.append(f"  • {change.place}: «{_shorten(change.before)}» "
                     f"+ {len(change.added)} вариант(ов) — {_shorten(added, 90)}")
    if not result.titles:
        lines.append("  • примеров нет: названий аниме в ответах не опознано.")
    elif result.not_found:
        lines.append(f"  • не нашлось на Shikimori: {result.not_found} из "
                     f"{result.checked_answers} проверенных ответов.")
    if getattr(result, "typo_titles", 0):
        lines.append(f"  • опознано с опечаткой в ответе: {result.typo_titles} "
                     f"(в паке название написано с ошибкой).")
    if result.skipped_titles:
        first = result.skipped_titles[0]
        lines.append(f"  • пропущено как имена персонажей: "
                     f"{len(result.skipped_titles)} (например «{first.before}» "
                     f"— {_shorten(first.after, 60)})")

    lines.append(f"Названий переписано как на Shikimori: {len(result.recased)}.")
    for change in result.recased[:limit]:
        lines.append(f"  • {change.place}: «{_shorten(change.before)}» → "
                     f"«{_shorten(change.after)}»")
    if not result.recased:
        lines.append("  • примеров нет: написание везде и так совпадает.")

    lines.append(f"Постеров поставлено в ответ: {len(result.posters)}"
                 + (f" (пак тяжелее на {fmt_size(result.added_bytes)})."
                    if result.added_bytes > 0 else "."))
    for change in result.posters[:limit]:
        lines.append(f"  • {change.place}: «{_shorten(change.title)}» — "
                     f"{change.after}")
    if not result.posters:
        lines.append("  • примеров нет: точных совпадений названия не было."
                     if not result.exact_titles else
                     "  • примеров нет: в ответах уже стояли свои картинки "
                     "либо постера у тайтла на Shikimori нет.")

    repeats = list(getattr(result, "repeats", []))
    lines.append(f"Повторяющихся подписей убрано: {len(repeats)}.")
    for change in repeats[:limit]:
        lines.append(f"  • {change.place}: «{_shorten(change.before)}» — убран")
    if not repeats:
        lines.append("  • примеров нет: одинакового текста во всех вопросах "
                     "темы не нашлось.")

    merged = list(getattr(result, "merged", []))
    lines.append(f"Текстов, включённых вместе со звуком: {len(merged)}.")
    for change in merged[:limit]:
        lines.append(f"  • {change.place}: «{_shorten(change.before)}» — "
                     f"{change.after}")
    if not merged:
        lines.append("  • примеров нет: текста прямо перед отрывком в паке нет "
                     "(или он уже играл одновременно).")

    empties = list(getattr(result, "empties", []))
    lines.append(f"Пустых вопросов удалено: {len(empties)}"
                 + (f" (и {result.dropped_themes} тем(ы) без вопросов)."
                    if result.dropped_themes else "."))
    for change in empties[:limit]:
        lines.append(f"  • {change.place}: {_shorten(change.before)}")
    if not empties:
        lines.append("  • примеров нет: вопросов без содержимого в паке нет.")

    lines.append(f"Картинок сжато: {len(result.images)}"
                 + (f" (пак легче на {fmt_size(result.saved_bytes)})."
                    if result.saved_bytes > 0 else "."))
    for change in result.images[:limit]:
        lines.append(f"  • {_shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not result.images:
        lines.append("  • примеров нет: картинок тяжелее порога в паке нет."
                     if not result.heavy_images else
                     f"  • примеров нет: ни одну из {result.heavy_images} "
                     f"тяжёлых картинок сжать не вышло.")

    audios = list(getattr(result, "audios", []))
    lines.append(f"Дорожек перекодировано в opus: {len(audios)}"
                 + (f" (пак легче на {fmt_size(result.saved_audio_bytes)})."
                    if result.saved_audio_bytes > 0 else "."))
    for change in audios[:limit]:
        lines.append(f"  • {_shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not audios:
        lines.append("  • примеров нет: аудио тяжелее порога в паке нет."
                     if not getattr(result, "heavy_audio", 0) else
                     f"  • примеров нет: ни одну из {result.heavy_audio} "
                     f"тяжёлых дорожек перекодировать не пришлось.")

    videos = list(getattr(result, "videos", []))
    lines.append(f"Роликов перекодировано в AV1: {len(videos)}"
                 + (f" (пак легче на {fmt_size(result.saved_video_bytes)})."
                    if result.saved_video_bytes > 0 else "."))
    for change in videos[:limit]:
        lines.append(f"  • {_shorten(change.theme_name)}: {change.before} → "
                     f"{change.after}")
    if not videos:
        lines.append("  • примеров нет: видео под перекод в паке нет."
                     if not getattr(result, "heavy_video", 0) else
                     f"  • примеров нет: ни один из {result.heavy_video} "
                     f"роликов перекодировать не пришлось.")

    unused = list(getattr(result, "unused", []))
    lines.append(f"Неиспользуемых файлов удалено: {len(unused)}"
                 + (f" (пак легче на {fmt_size(result.saved_unused_bytes)})."
                    if result.saved_unused_bytes > 0 else "."))
    for change in unused[:limit]:
        lines.append(f"  • {_shorten(change.theme_name)}: {change.before} — "
                     f"ссылок нет")
    if not unused:
        lines.append("  • примеров нет: на каждый файл в паке есть ссылка.")
    return lines
