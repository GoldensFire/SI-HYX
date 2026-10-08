# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# Логика генерации портирована с разрешения автора из проекта ASPG (Anime Songs
# SiGame Pack Generator), Copyright (c) Leleath, лицензия MIT —
# https://github.com/Leleath/aspg
#
# animepack_tab.py — вкладка «Генерация аниме-пака». Раскладка как у
# ShikimoriHYX: слева контент (состав пака + лог + прогресс), справа
# прокручиваемая панель настроек. Вся работа идёт в QThreadPool, интерфейс не
# виснет; сеть и сборка живут в animepack_api.py / animepack.py.
from __future__ import annotations
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


import os
import time
from typing import Optional

from PyQt6.QtCore import (Qt, QObject, QRect, QRunnable, QThreadPool, QSize,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QToolButton, QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox,
    QGroupBox, QScrollArea, QFrame, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QFileDialog, QMenu, QAbstractItemView,
    QDialog, QListWidget, QListWidgetItem, QSlider, QWIDGETSIZE_MAX,
)

from msgbox import msgbox_critical, msgbox_information, msgbox_warning

try:
    from config import get_icon
except Exception:  # pragma: no cover
    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon
        return QIcon()

try:
    from animepack import (ANAGRAM_CHARS_PER_SEC, ANAGRAM_CPS_MAX,
                           AI_ART_KIND, ANAGRAM_KIND, ANAGRAM_LANG_LABELS, ANAGRAM_LANGS,
                           ANAGRAM_MAX_CHARS, ANAGRAM_MIN_SECONDS,
                           ANIME_KINDS, ANSWER_IMAGE_MAX, CATEGORY_LABELS,
                           CHAR_KIND, CHAR_ROLES, DESCRIPTION_AUDIO_KIND, DIALOGUE_KIND,
                           CHAR_ROLE_LABELS, FRAME_KIND,
                           KIND_LABELS, KIND_TITLES, MANGA_KIND,
                           MANGA_LANG_LABELS, MANGA_LANGS,
                           MAX_PACK_MB, PIXIV_ART_KIND, PIXEL_BLOCK, PIXEL_FPS, PIXEL_KIND,
                           PIXEL_SECONDS, PIXEL_STEPS,
                           PIXIV_MIN_LIKES, PLOT_KIND, PLOT_MODES,
                           PLOT_MODE_LABELS, SAKUGA_CUT, SAKUGA_KIND, EPISODE_KIND,
                           SAKUGA_MAX_CUT, MAX_LEVEL,
                           STUDIO_FRAMES,
                           STUDIO_FRAME_SECONDS, STUDIO_KIND,
                           STUDIO_SECONDS_MAX,
                           SILENT_KINDS, SONG_CATEGORIES,
                           VIDEO_CRF, VIDEO_CUT, VIDEO_KIND, VIDEO_PRESET,
                           AnimePackError,
                           AnimePackGenerator, PackSettings, UserList,
                           DB_PART_NAMES, arrange_questions,
                           db_refresh_parts, fmt_elapsed)
    from animepack_api import (LIST_SOURCES, LIST_STATUSES,
                               MANGA_KINDS, MANGA_KIND_LABELS, SOURCE_LABELS,
                               STATUS_LABELS, TARGET_LABELS, ShikimoriApi)
    from gemini_api import DEFAULT_MODEL as GEMINI_DEFAULT_MODEL
    from gemini_api import MODELS as GEMINI_MODELS
    from gemini_api import THINKING_LEVEL as GEMINI_THINKING_LEVEL
    from gemini_api import THINKING_LEVELS as GEMINI_THINKING_LEVELS
    # Общая с «Апгрейдом аниме-пака» кладовая обложек плюс отдельная кладовая
    # тяжёлых переиспользуемых исходников и результатов кодирования.
    import media_cache
    from media_cache import MEDIA_CACHE_MB
    import poster_cache
    from poster_cache import POSTER_CACHE_MB
    _HAS_CORE, _IMPORT_ERROR = True, ""
except Exception as e:  # pragma: no cover — нет requests и т.п.
    _HAS_CORE, _IMPORT_ERROR = False, str(e)

# Уровни «размышления» Gemini по-русски. Ключи — то, что уходит в запрос
# (см. gemini_api.THINKING_LEVELS), подписи — то, что видит человек.
GEMINI_THINKING_LABELS = {
    "minimal": "Минимальный", "low": "Низкий",
    "medium": "Средний", "high": "Высокий",
}

# Палитра — та же, что во вкладке ShikimoriHYX (Catppuccin Mocha).
C = {
    "bg": "#1e1e2e", "surface": "#181825", "surface2": "#24273a",
    "surface3": "#313244", "border": "#45475a", "accent": "#89b4fa",
    "accent2": "#b4befe", "text": "#cdd6f4", "text2": "#a6adc8",
    "text3": "#6c7086", "green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8",
}

# Короткие имена сайтов для карточки списка. Полные («MyAnimeList», «Shikimori»)
# съедали две трети её ширины, и ник в поле не помещался — а сайтов всего три и
# в лицо они узнаются (полные имена остались в подсказке и в окне сохранённых).
SOURCE_SHORT = {"myanimelist": "MAL", "shikimori": "Shiki", "anilist": "AniList"}

from si_hyx_parts.animepack_tab.settings_box import (SettingsBox,
                                                     needed_height)

from si_hyx_parts.animepack_tab.no_wheel import _no_wheel, _ShareBar

from si_hyx_parts.animepack_tab.mix_slider import _MixSlider, _NumItem
from si_hyx_parts.animepack_tab.background_tasks import (
    _GenSignals,
    _GenTask,
    _RefreshDbSignals,
    _RefreshDbTask,
    _GenresSignals,
    _GenresTask,
)

from si_hyx_parts.animepack_tab.user_card import _UserCard

from si_hyx_parts.animepack_tab.saved_users_dialog import _SavedUsersDialog
from si_hyx_parts.animepack_tab.anime_pack_tab import AnimePackTab
