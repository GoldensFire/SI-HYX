# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
#
# coop_tab.py — экспериментальная вкладка «Collab»: совместная работа над
# одним .siq-паком SIGame. Показывает список тем, текстовых вопросов и ответов
# (медиа — только маркером «[фото]/[видео]/[аудио]», сам файл не передаётся),
# синхронизируясь в near-realtime с напарником через общую «комнату» на
# Cloudflare Worker. Видно, кто какую тему/вопрос уже сделал — и где вы
# пересеклись (дубли), чтобы не делать одно и то же дважды.
#
# Вкладка по умолчанию ВЫКЛЮЧЕНА (включается в Настройках). Из зависимостей —
# только стандартная библиотека (urllib) + уже парсящий .siq SiqPackage.

# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import datetime
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

from PyQt6.QtCore import Qt, QObject, pyqtSignal, QFileSystemWatcher, QTimer
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QCheckBox, QTreeWidget, QTreeWidgetItem, QFileDialog,
    QHeaderView, QAbstractItemView,
)
from msgbox import msgbox_information

try:
    from config import get_icon, APP_VERSION, COOP_SYNC_URL
except Exception:  # pragma: no cover — на случай частичной сборки
    APP_VERSION = "?"
    COOP_SYNC_URL = ""

    def get_icon(name, color="#cdd6f4"):
        from PyQt6.QtGui import QIcon as _QIcon
        return _QIcon()

# ── Цвета (в тон общему catppuccin-стилю приложения) ──────────────────────────
_C_MINE   = "#a6e3a1"   # зелёный — есть только у меня
_C_OTHER  = "#89b4fa"   # синий — есть только у напарника
_C_DUP    = "#f9e2af"   # жёлтый — есть у обоих (пересечение / возможный дубль)
_C_WARN   = "#f38ba8"   # красный — точный дубль (совпал ответ)
_C_MUTED  = "#a6adc8"
_C_TEXT   = "#cdd6f4"

# Палитра для >2 авторов (мой цвет всегда зелёный, остальным раздаём по кругу).
_AUTHOR_PALETTE = ["#89b4fa", "#fab387", "#cba6f7", "#94e2d5", "#f5c2e7", "#f9e2af"]

_MEDIA_KINDS = ("image", "audio", "video")
_MEDIA_LABEL = {"image": "фото", "audio": "аудио", "video": "видео"}

from si_hyx_parts.coop_tab.q_summary import _q_summary


_OPT_PREFIXES = ("вариант", "ответ", "буква", "вар.")
_OPT_SPLIT = re.compile(r"[,;/+&]|\bи\b|\bили\b|\s+")
_OPT_STRIP = " .)(»«\"'`-–—:"

from si_hyx_parts.coop_tab.is_option_answer import (
    _is_option_answer,
    _q_is_filled,
    pack_to_outline,
    normalize_room,
    normalize_url,
    outline_from_siq,
    _CoopSync,
)

from si_hyx_parts.coop_tab.coop_tab import CoopTab
