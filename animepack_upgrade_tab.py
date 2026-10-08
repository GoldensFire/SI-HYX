# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# animepack_upgrade_tab.py — вкладка «Апгрейд пака». Раскладка та же, что
# у «Генерации аниме-пака»: слева таблица изменений, справа прокручиваемая
# панель настроек, под ней — неподвижная полоса кнопок. Работа идёт в
# QThreadPool, интерфейс не виснет; вся логика правки живёт в
# animepack_upgrade.py (там нет Qt и её проверяют тесты).
#
# Вкладка держит одну страницу (_UpgradePage): тайтлы ищутся на Shikimori.
# Раньше рядом была ещё подвкладка «Кино-пак» (Wikidata) — её убрали, и
# видимой полосы вкладок над формой больше нет. Наружу вкладка остаётся одним
# виджетом: AnimePackUpgradeTab раздаёт вызовы (set_siq, get_settings,
# cleanup) странице внутри.
from __future__ import annotations
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


import os
import time
from typing import Optional

from PyQt6.QtCore import (Qt, QObject, QRunnable, QThreadPool, QSize, pyqtSignal)
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QCheckBox, QGroupBox, QScrollArea,
    QTableWidget, QTableWidgetItem, QHeaderView, QFileDialog,
    QAbstractItemView, QStackedWidget,
)

from msgbox import msgbox_critical, msgbox_information, msgbox_warning

try:
    from config import get_icon
except Exception:  # pragma: no cover
    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon
        return QIcon()

try:
    from animepack_upgrade import (AUDIO_BITRATES, PROFILE_ANIME,
                                   PROFILE_LABELS, VIDEO_HEIGHTS,
                                   PackUpgrader, UpgradeError, UpgradeSettings,
                                   example_lines, nearest_bitrate,
                                   nearest_height, normalize_profile,
                                   read_pack_info)
    from animepack import fmt_elapsed
    _HAS_CORE, _IMPORT_ERROR = True, ""
except Exception as e:  # pragma: no cover — нет requests и т.п.
    _HAS_CORE, _IMPORT_ERROR = False, str(e)
    # Ядро не загрузилось — страница всё равно нужна одна: она покажет, что
    # именно не импортировалось. Имя профиля нужно и тогда, поэтому строкой.
    PROFILE_ANIME = "anime"

# Палитра — та же, что во вкладках ShikimoriHYX и «Генерация аниме-пака».
C = {
    "bg": "#1e1e2e", "surface": "#181825", "surface2": "#24273a",
    "surface3": "#313244", "border": "#45475a", "accent": "#89b4fa",
    "accent2": "#b4befe", "text": "#cdd6f4", "text2": "#a6adc8",
    "text3": "#6c7086", "green": "#a6e3a1", "yellow": "#f9e2af", "red": "#f38ba8",
}

from si_hyx_parts.animepack_upgrade_tab.upgrade_tab import (
    _no_wheel,
    _UpgradeSignals,
    _UpgradeTask,
    AnimePackUpgradeTab,
)
from si_hyx_parts.animepack_upgrade_tab.upgrade_page import _UpgradePage
