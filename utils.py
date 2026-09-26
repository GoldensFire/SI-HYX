# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# utils.py — вспомогательные функции (ffmpeg/ffprobe, cookies, deno, и т.п.)
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import base64
import functools
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from config import (
    COOKIE_PATHS, CREATE_NO_WINDOW, FFMPEG, FFPROBE, IS_WIN, Image,
    ImageOps, QByteArray, QIcon, QPainter, QPixmap, QtGuiImage,
    SETTINGS_FILE, TEMP_DIR, USER_AGENT, _requests, http_get
)

from si_hyx_parts.utils.getattr import __getattr__


# ── Маскировка JS в HTML под VK ──────────────────────────────────────────────
# VK отклоняет .siq с читаемым JS: ловит тег <script> и литерал function/Function.
# Но JS в атрибуте-обработчике (onload=...) пропускает, ЕСЛИ в нём нет слова
# function — проверенный рабочий приём (файл oden.html) прячет «Function» через
# склейку 'Fun'+'ction' и не содержит ни <script>, ни function.
#
# Стратегия (прирост веса ≈ +33%, одинарный base64):
#   • видимая часть = точный паттерн oden: onload="const launch='Fun'+'ction';
#     window[launch](atob('<LOADER>'))();" — VK видит только это;
#   • <LOADER> (base64) — крошечный фиксированный загрузчик: читает payload из
#     data-si и пересоздаёт <script> (createElement, function, 'script' — внутри
#     base64, VK их не читает). Двойное кодирование тут дёшево: загрузчик мал;
#   • сам код игры лежит в data-si одинарным base64 ("b:<base64>"|"s:<url>",
#     разделитель '|'). Для VK это безопасная base64-каша, БОЛЬШОЙ код повторно
#     НЕ кодируется → нет раздувания вдвое.
# Пересозданные <script> исполняются в ГЛОБАЛЬНОЙ области, поэтому существующие
# инлайн onclick=... работают. Внешние <script src> грузятся по цепочке (onload)
# перед инлайн-кодом — порядок сохраняется.
# Закрывающий тег матчим как </script…> с любыми пробелами/мусором до '>'
# (браузеры принимают </script >, </script foo="bar"> и т.п.) — иначе
# часть скриптов осталась бы незакодированной (CodeQL py/bad-tag-filter).
_B64_SCRIPT_RX = re.compile(r'(?is)<script\b([^>]*)>(.*?)</script\b[^>]*>')
_B64_SRC_RX    = re.compile(r'(?i)src\s*=\s*[\'"]([^\'"]+)[\'"]')
# 1×1 прозрачный gif — носитель onload-триггера
_B64_GIF = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7'
# Максимум символов в одном непрерывном куске base64. VK режет файл, если
# встречает длинную НЕПРЕРЫВНУЮ base64-строку (порог опытно между 184 и 612).
# 120 — с запасом ниже 184. Дробится и payload (data-si), и сам загрузчик (onload).
_B64_CHUNK = 120

from si_hyx_parts.utils.mask_html_js import mask_html_js


# ── Лёгкая маскировка (доп-режим) ────────────────────────────────────────────
# ЧТО РЕЖЕТ VK (установлено эмпирически): фильтр «исполняемый файл» ловит
# ЛИТЕРАЛЬНЫЕ <script>, eval, function/Function в открытой части документа. Не
# длину base64, не MIME, не canvas/svg. Заведомо проходящий вывод = старый метод
# (mask_html_js): в открытом HTML НЕТ ни одного <script>/eval/function — всё тело
# и скрипты лежат в data-si одним base64, а запуск идёт через
# `window['Fun'+'ction'](atob(<loader>))()` в onload скрытой картинки (в onload
# нет слова Function — оно склеено 'Fun'+'ction'; loader/движок VK не видит,
# они в base64). Ранние lite-версии оставляли `<script>…(0,eval)…</script>`
# в открытую и потому отклонялись — этот подход в корне непригоден.
#
# Поэтому lite = ТОЧНО envelope старого метода (та же скрытность), но с одной
# оптимизацией размера: крупные ассеты (аудио/картинки как длинные base64/data:
# литералы в скриптах) НЕ попадают в base64 повторно. Старый метод кодирует их
# внутри скрипта → они шифруются вторым слоем (+33% на мегабайтах). Здесь такой
# ассет-литерал ВЫНОСИТСЯ из скрипта, кладётся в data-si ОДИН раз как отдельный
# элемент `r:<idx>:<сам base64>` (без повторного кодирования), а на его месте в
# коде — ссылка `__SI_Ak`. Loader объявляет `window.__SI_Ak` (реассемблирует,
# НЕ декодируя) ДО запуска скриптов, движок читает их из глобальной области.
# Всё остальное (разметка тела, обычные скрипты) прячется как в старом методе.
_LITE_STRIP_RX = re.compile(
    r'(?s)/\*.*?\*/'                       # блочные комментарии
    r'|//[^\n]*'                           # строчные комментарии
    r'|"(?:[^"\\]|\\.)*"'                  # "строки"
    r"|'(?:[^'\\]|\\.)*'"                  # 'строки'
    r'|`(?:[^`\\]|\\.)*`')                 # `шаблоны`
# Крупный ассет: строковый литерал из ЧИСТОГО base64 (опц. с data:-префиксом)
# длиной ≥ порога. Внутри такого литерала нет кавычек/скобок — выносится как есть.
_LITE_HOIST_MIN = 512
_LITE_ASSET_INNER_RX = re.compile(
    r'(?:data:[\w.+/;=-]*?base64,)?[A-Za-z0-9+/=]+')

from si_hyx_parts.utils.lite_hoist_assets import _lite_hoist_assets


# Loader lite: как в mask_html_js плюс тип элемента 'r' — сырой ассет, который
# объявляется глобальной переменной window.__SI_Ak БЕЗ base64-декодирования
# (только снимаем переносы строк через R). Порядок в data-si гарантирует, что
# все 'r' идут до 'b'-скриптов, поэтому ссылки __SI_Ak уже определены.
_LITE_LOADER = (
    r"var im=document.querySelector('img[data-si]');"
    r"var q=im.getAttribute('data-si').split('|');"
    r"var td=new TextDecoder();"
    r"function D(v){return td.decode(Uint8Array.from("
    r"atob(v.replace(/[^A-Za-z0-9+\/=]/g,'')),"
    r"function(c){return c.charCodeAt(0);}));}"
    r"function R(v){return v.replace(/\s/g,'');}"
    r"var i=0;function n(){if(i>=q.length)return;"
    r"var it=q[i++],k=it.charAt(0),v=it.slice(2);"
    r"if(k=='m'){document.body.innerHTML=D(v);n();}"
    r"else if(k=='r'){var p=v.indexOf(':');"
    r"window['__SI_A'+v.slice(0,p)]=R(v.slice(p+1));n();}"
    r"else if(k=='s'){var s=document.createElement('script');"
    r"s.src=v;s.onload=n;document.body.appendChild(s);}"
    r"else{var s=document.createElement('script');"
    r"s.textContent=D(v);document.body.appendChild(s);n();}}n();")

from si_hyx_parts.utils.mask_html_js_lite import mask_html_js_lite, ensure_deno_on_path


# Включаем Deno в PATH при старте — нужно для скачивания с YouTube
ensure_deno_on_path()


# Helpers
# Предкомпилированные регулярные выражения — не пересоздаются при каждом вызове
_RE_ANSI    = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')


_RE_LUFS    = re.compile(r'\{[\s\S]*?\}')  # нежадный — не захватывает лишние блоки


_RE_DIGITS  = re.compile(r'(\d+)')

from si_hyx_parts.utils.clean_ansi import clean_ansi


# ── Настройки: чтение и запись, переживающие любой сбой ──────────────────────
# История потерь (см. также main.py::_load_settings): «все настройки слетели»
# случалось, когда load_settings() отдавал {} при ЖИВОМ файле на диске, а первое
# же авто-сохранение писало поверх дефолты — вместе с .bak, то есть насовсем.
# Поэтому здесь три независимых рубежа:
#   1) чтение НЕ считает «пусто» ответом: занятый файл (антивирус, второй
#      экземпляр программы, индексатор) перечитывается, а не признаётся утраченным;
#   2) в .bak уходит только ФАКТИЧЕСКИ ВАЛИДНЫЙ прежний файл — битый/обрезанный
#      settings.json больше не может вытеснить последнюю рабочую копию;
#   3) сверх .bak ведётся история из нескольких снимков (settings.json.1…5),
#      так что даже две подряд неудачные записи не уничтожают настройки.
_SETTINGS_HISTORY = 5            # сколько снимков храним сверх .bak
_SETTINGS_SNAPSHOT_INTERVAL = 600.0   # не чаще одного снимка в 10 минут

from si_hyx_parts.utils.settings_history_paths import (
    _settings_history_paths,
    _settings_candidates,
    _read_settings_file,
    load_settings_ex,
    load_settings,
    settings_files_exist,
    _replace_with_retry,
    _snapshot_settings_history,
    save_settings,
    save_json_atomic,
    human_size,
    url_host,
    host_matches,
    parse_youtube_start_seconds,
    get_cookies_path,
)

from si_hyx_parts.utils.cookie_matches_domain import (
    _cookie_matches_domain,
    is_direct_cdn_video,
    download_cdn_direct,
)


# ──────────────────────────────────────────────────────────────────────────
#  Kodik resolver — извлечение прямого m3u8 из встроенного плеера Kodik.
#  Работает для animego.online и других сайтов, использующих Kodik
#  (yt-dlp его не поддерживает напрямую).
# ──────────────────────────────────────────────────────────────────────────

# Сайты, которые yt-dlp и так качает напрямую — для них Kodik-резолвер не нужен.
KNOWN_DIRECT_SITES = (
    "youtube.com", "youtu.be", "tiktok.com", "instagram.com", "vk.com", "vk.ru",
    "vkvideo.ru", "vimeo.com", "twitch.tv", "twitter.com", "x.com", "dailymotion.com",
    "reddit.com", "soundcloud.com", "facebook.com", "fb.watch", "ok.ru", "rutube.ru",
    "bilibili.com", "coub.com", "yandex.ru", "pinterest.",
)

# Домены плеера Kodik (меняются со временем — список основных)
_KODIK_HOST_RE = re.compile(
    r'(?:https?:)?//[\w.-]*(?:kodik|aniqit|anivod|kodikplayer)[\w.-]*'
    r'/(?:seria|serial|video|episode)/[^\s"\'<>\\]+', re.I)

from si_hyx_parts.utils.kodik_decode import (
    _kodik_decode,
    is_embed_candidate,
    _find_kodik_iframe,
    _attr,
    _parse_kodik_selects,
    _selected_option,
    _is_animego,
    is_animego_site,
    _animego_base,
    _animego_anime_id,
    _animego_player_content,
    _animego_parse,
    _animego_kodik_players,
    animego_get_info,
    _animego_resolve_kodik_url,
    kodik_get_info,
)

from si_hyx_parts.utils.resolve_kodik import (
    resolve_kodik,
    parse_version,
    default_download_dir,
    clean_url,
    check_ffmpeg,
    pretty_audio_codec,
    fmt_bitrate_with_codec,
)

from si_hyx_parts.utils.get_media_info import (
    get_media_info,
    csv_fields,
    csv_first,
    get_fps_float,
    get_video_codec,
)


_CODEC_LABELS = {
    'h264': 'H.264', 'avc': 'H.264', 'avc1': 'H.264',
    'hevc': 'H.265', 'h265': 'H.265',
    'av1': 'AV1', 'av01': 'AV1',
    'vp9': 'VP9', 'vp8': 'VP8',
    'mpeg4': 'MPEG-4', 'mpeg2video': 'MPEG-2',
}

from si_hyx_parts.utils.codec_label import (
    codec_label,
    get_video_codec_label,
    get_pix_fmt,
    overlay_chroma_format,
    escape_filter_path,
    overlay_filter_graph,
    measure_loudness,
    play_done_sound,
    rasterize_svg,
    open_image_any,
    load_pixmap_any,
)

from si_hyx_parts.utils.pil_to_qicon import (
    pil_to_qicon,
    reveal_in_explorer,
    move_to_trash,
    detect_ffmpeg_encoders,
    require_svt,
)
