# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# shikimori_tab.py — экспериментальная вкладка «ShikimoriHYX»: поиск аниме/манги
# через Shikimori API с фильтрами по оценке/типу/статусу/году/эпизодам/жанру и
# экспортом результата в JSON/CSV. Сетевые запросы идут в фоне (QThreadPool +
# QRunnable), GUI обновляется только через сигналы/слоты — интерфейс не виснет.
#
# Раскладка: СЛЕВА — список найденных тайтлов с обложками; СПРАВА — панель
# настроек (фильтры, исключение паков SiQuesterHYX, экспорт). Обложки грузятся
# асинхронно и кешируются. Нижние прогрессбар/консоль главного окна на этой
# вкладке скрыты (см. _sync_console_visibility в main.py).
#
# Слой API/фильтрации вынесен в shikimori_api.py (без Qt). Здесь — только GUI и
# оркестровка фоновых задач. Вкладка по умолчанию ВЫКЛЮЧЕНА (включается в
# Настройках, как SiQuesterHYX).
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import csv
import json
import os
import re
import time
import webbrowser
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # только для аннотаций в кавычках — на рантайме не нужен
    from typing import Optional

from PyQt6.QtCore import (
    Qt, QObject, QRunnable, QThreadPool, pyqtSignal, QSize, QRect, QEvent, QTimer,
)
from PyQt6.QtGui import QColor, QIcon, QPixmap, QValidator, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem, QFileDialog, QScrollArea, QGroupBox,
    QDialog, QCheckBox, QDialogButtonBox, QFrame, QStyledItemDelegate,
    QStyleOptionViewItem, QStyle, QApplication,
)
from msgbox import msgbox_critical, msgbox_warning, msgbox_information

try:
    from config import get_icon, APP_NAME, APP_VERSION
except Exception:  # pragma: no cover
    APP_NAME, APP_VERSION = "SI-HYX", "0.0"

    def get_icon(name, color="#cdd6f4"):  # минимальная заглушка
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

# Фирменный тёмный попап-подсказка (тот же, что у значков ⓘ и подсказки
# «Схлопывать франшизы» через HoverTipManager). НЕ системный QToolTip с синей
# рамкой: его и просил пользователь для подсказки индекса.
try:
    from widgets import _InfoTipPopup
except Exception:  # pragma: no cover
    _InfoTipPopup = None

# Просмотры и «индекс популярности» берутся из базы Shikimori генератора
# аниме-паков (si_hyx_parts/shikimori_tab/pack_index.py) — своего кеша нет.
try:
    from config import CONFIG_DIR
    _COVERS_CACHE_DIR = os.path.join(CONFIG_DIR, "shikimori_covers")
except Exception:  # pragma: no cover
    _COVERS_CACHE_DIR = ""
# Обложки на диске (по просьбе пользователя — не тянуть их заново по сети при
# каждом запуске: за день афиши не меняются). Без TTL (постеры почти не
# меняются), но число файлов ограничено — при переполнении трём самые старые
# (по времени изменения) удаляются.
_COVERS_CACHE_MAX = 8000

# Слой API/фильтрации. Если requests недоступен — вкладка покажет заглушку.
_IMPORT_ERROR = ""
try:
    from shikimori_api import (
        ShikimoriApiClient, AnimeFilter, Anime, ShikimoriError, find_anime,
        ORDERS, DEFAULT_BASE_URL, CONTENT_ANIME, CONTENT_MANGA,
        kinds_for, statuses_for, kind_label, status_label, views_from_card,
        index_base_from_card, index_components_from_card,
        index_factors as _index_factors,
        popularity_index as _popularity_index,
        genre_group, GENRE_GROUP_LABELS, GENRE_GROUP_ORDER,
    )
    _HAS_API = True
except Exception as _e:  # pragma: no cover
    _HAS_API = False
    _IMPORT_ERROR = str(_e)

from si_hyx_parts.shikimori_tab.clearable_double_spin_box import ClearableDoubleSpinBox


# Палитра (Catppuccin Mocha) — локальная копия, чтобы не тянуть QtMultimedia из
# edit_tab. Совпадает с темой остального приложения.
C = {
    "bg": "#1e1e2e", "surface": "#181825", "surface2": "#24273a",
    "surface3": "#313244", "border": "#45475a", "accent": "#89b4fa",
    "accent2": "#b4befe", "text": "#cdd6f4", "text2": "#a6adc8",
    "text3": "#6c7086", "green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8",
}

# Локальная (не серверная) сортировка по «просмотрам» — completed+watching+dropped
# из карточки каждого тайтла. По умолчанию выбрана именно она (просьба пользователя).
ORDER_VIEWS = "views"
# «Индекс популярности» — тот же, что у генератора аниме-паков (SongCandidate.index:
# серия, «в избранном», свежесть, оценка). Тоже локальная сортировка.
ORDER_INDEX = "popindex"

ORDER_LABELS = {
    ORDER_VIEWS: "По просмотрам",
    ORDER_INDEX: "По индексу популярности",
    "ranked": "По рейтингу", "popularity": "По популярности", "name": "По имени",
    "aired_on": "По дате выхода", "episodes": "По эпизодам", "kind": "По типу",
    "id": "По id", "random": "Случайно",
}

# Сама формула «индекса популярности» (возраст → свежесть, оценка, веса
# статусов) живёт в shikimori_api — оттуда её берёт и генератор аниме-паков,
# чтобы цены вопросов считались ровно по тому же правилу, что и сортировка
# здесь. Имена _index_factors/_popularity_index импортированы выше.

# Размер обложки в списке (постер 7:10). Покрупнее — постеры хорошо видно.
_THUMB_W, _THUMB_H = 96, 136


# Просмотры и индекс берутся из базы генератора аниме-паков; тайтлы, которых
# там нет, дозапрашиваются пачками GraphQL по 50 (pack_index). Поиск идёт по
# ПОПУЛЯРНОСТИ, а по сети дозапрашивается только верхушка выдачи.
_VIEWS_SORT_MAX = 100

# Автостоп поиска по достижению числа тайтлов ПОСЛЕ фильтрации (паки/франшизы/
# оценка и т.д.) — по просьбе пользователя, чтобы не гонять поиск по всей базе,
# если нужного числа уже достаточно. 0 = без лимита.
_STOP_LIMIT_DEFAULT = 500

from si_hyx_parts.shikimori_tab.user_agent import _user_agent, _client_factory


# Расхождения систем транслитерации (Хепбёрн ↔ Поливанов) дробят один тайтл на
# два разных написания: «Кобаяши» (shi) и «Кобаяси» (си) — это одно имя. Сводим
# обе формы к одной канонической, чтобы пак с «Кобаяши» прятал из выдачи
# «Кобаяси». Берём только дифтонги, которые в русском почти не встречаются вне
# японской транслитерации (низкий риск ложного слияния): «дж»→«дз», «ши»→«си».
_TRANSLIT_FOLDS = (
    ("дж", "дз"),   # ji/ja/jo… по Хепбёрну: «Фуджи»→«Фудзи», «Джоджо»→«Дзодзо»
    ("ши", "си"),   # shi по Хепбёрну: «Кобаяши»→«Кобаяси», «Аниме»? — нет, «ши»
)

from si_hyx_parts.shikimori_tab.translit_fold import _translit_fold, _norm_title


# Хвостовой «сезонный» маркер: отдельный токен в конце названия — число (1–2
# цифры), римская цифра, либо слово «сезон/season/часть/part/tv/тв/cour» с/без
# числа, либо «финальный сезон». ОБЯЗАТЕЛЬНО с разделителем перед собой ([\s:.\-]+),
# чтобы не отрезать буквы у обычных названий («matrix» → не «matri», «86» цел,
# «mob psycho 100» цел — 3 цифры не матчатся). Нужно, чтобы пак с «Ванпанчмен»
# скрывал из выдачи и «Ванпанчмен 2/3», и наоборот (все сезоны одного тайтла).
_SEASON_TAIL_RX = re.compile(
    r"[\s:.\-–—]+(?:"
    r"(?:the\s+)?(?:final\s+)?(?:season|сезон[а-я]*|часть|части|part|cour|кор|tv|тв"
    r"|фильм|movie|спэшл|спешл|special|ova|ona|oad|ова|она)"
    r"\s*-?\s*\d{0,2}"
    r"|\d{1,2}(?:\s*-?\s*(?:nd|rd|th|st|й|ый|ой|ая|я)?\s*"
    r"(?:season|сезон[а-я]*|часть|part|cour))?"
    r"|i{1,3}|iv|vi{0,3}|ix|xi{0,2}|x"
    r")$",
    re.IGNORECASE,
)

from si_hyx_parts.shikimori_tab.base_title import _base_title


# Подзаголовок после двоеточия/«!»/«?»/«…» С ПРОБЕЛОМ («Наруто: Ураганные
# хроники» → «Наруто», «Этот замечательный мир! Багровая легенда» → «Этот
# замечательный мир»). Разделитель без пробела НЕ режем, чтобы не ломать
# «Re:Zero», «Steins;Gate» и т.п. После «!/?» обязателен непробельный символ —
# чтобы голый хвостовой «!» (его _norm_title уже срезал) ничего не отрезал.
_SUBTITLE_RX = re.compile(r"\s*[:：!?…]+\s+\S.*$")

from si_hyx_parts.shikimori_tab.franchise import (
    _franchise_key,
    _title_words,
    _same_franchise_prefix,
)
from si_hyx_parts.shikimori_tab.background_tasks import (
    _SearchSignals,
    _SearchTask,
    _GenresSignals,
    _GenresTask,
    _ThumbSignals,
    _ThumbTask,
    _ViewsSignals,
    _ViewsTask,
)
from si_hyx_parts.shikimori_tab.cover_cache import (
    _cover_cache_path,
    _load_cover_from_disk,
    _save_cover_to_disk,
    _prune_covers_cache,
)


# ─── Делегат: значок «глаз» с числом просмотров ──────────────────────────────
_COPY_ICON_SZ = 16       # размер кнопки «копировать»
_COPY_TITLE_GAP = 6      # отступ кнопки от конца названия
_COPY_FEEDBACK_MS = 1500  # сколько держать «галочку» после копирования
_RANK_W = 30             # ширина левого отступа строки под номер места тайтла

from si_hyx_parts.shikimori_tab.views_badge_delegate import _ViewsBadgeDelegate, _TriStateGenre

from si_hyx_parts.shikimori_tab.genre_picker_dialog import _GenrePickerDialog
from si_hyx_parts.shikimori_tab.shikimori_tab import ShikimoriTab
