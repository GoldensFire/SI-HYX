# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# sub_search_tab.py — вкладка «Поиск по сабам»: тайтлы, в английских субтитрах
# которых звучит фраза (по умолчанию «six seven»). Порядок обхода — по уровню
# из базы ShikimoriHYX (от лёгкого к сложному и наоборот), исключение паков —
# то же, что у ShikimoriHYX (PackExclusionMixin), постеры — общий кэш обложек.
# Поиск идёт в фоне (sub_search.SearchEngine), интерфейс обновляется сигналами.
# Вкладка по умолчанию ВЫКЛЮЧЕНА (Настройки → «Экспериментально»).
#
# Реализация — si_hyx_parts/sub_search_tab/; движок без Qt — sub_search.py.
"""Вкладка «Поиск по сабам»."""
import sys as _sys
_api = _sys.modules[__name__]

import csv
import os
import threading
import time
import webbrowser

from PyQt6.QtCore import Qt, QEvent, QObject, QSize, QThreadPool, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QGuiApplication
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QListWidgetItem, QScrollArea,
    QGroupBox, QCheckBox, QFrame, QToolButton, QProgressBar, QPlainTextEdit,
    QFileDialog, QMenu, QSizePolicy,
)

from config import get_icon
from msgbox import msgbox_warning, msgbox_question

import sub_search as engine
from shikimori_tab import (
    C, _ThumbTask, _load_cover_from_disk, _save_cover_to_disk, _THUMB_W, _THUMB_H,
)

# Постер в строке результата (7:10).
POSTER_W, POSTER_H = 84, 120
COPY_FEEDBACK_MS = 1500

from si_hyx_parts.sub_search_tab.result_row import ResultRow, level_color  # noqa: E402
from si_hyx_parts.sub_search_tab.worker import SearchWorker  # noqa: E402
from si_hyx_parts.sub_search_tab.sub_search_tab import SubSearchTab  # noqa: E402

__all__ = ["SubSearchTab", "ResultRow", "SearchWorker", "level_color"]
