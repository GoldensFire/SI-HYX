# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# config.py — импорты, пути, константы, стили, FORMAT_OPTIONS


# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import sys


import os


import traceback


import subprocess


import tempfile


import shutil


import json


import functools


# requests подключается лениво — см. _requests() ниже


from pathlib import Path

from si_hyx_parts.config.fail_and_exit import fail_and_exit


try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
        QFileDialog, QSpinBox, QDoubleSpinBox, QCheckBox, QProgressBar,
        QMessageBox, QTextEdit, QPlainTextEdit, QSlider, QGroupBox, QFormLayout, QComboBox,
        QLineEdit, QMenu, QScrollArea, QAbstractSpinBox, QAbstractItemView,
        QHeaderView, QToolButton, QDialog,
        QStyledItemDelegate, QStyle, QFrame,
        QInputDialog, QKeySequenceEdit, QListWidget, QListWidgetItem
    )
    from PyQt6.QtCore import (
        Qt, QThread, pyqtSignal, QSize, QRect, QRectF, QPoint, QPointF,
        QRunnable, QThreadPool, QByteArray, QTimer, QObject, QEvent
    )
    from PyQt6.QtGui import (
        QAction, QColor, QFont, QIcon, QPixmap, QBrush, QImage as QtGuiImage,
        QKeySequence, QShortcut, QPainter, QPen, QCursor, QTextCursor,
        QFontMetrics
    )
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
except Exception as e:
    fail_and_exit("Не удалось импортировать PyQt6. Убедитесь, что установлено: pip install PyQt6", e)

# Векторные иконки интерфейса (Font Awesome / Material Design через qtawesome).
import qtawesome as qta

from si_hyx_parts.config.get_icon import get_icon, get_icon_pixmap, icon_html, status_html


# Optional libs
# yt-dlp НЕ импортируется как модуль: программа всегда зовёт его отдельным
# процессом (bin\yt-dlp.exe, системный yt-dlp или `python -m yt_dlp` в dev —
# см. ytdlp_base_cmd ниже), а ни одного обращения к API пакета в коде нет.
# Импорт стоил ~340 мс на каждом запуске и тянул за собой Cryptodome, curl_cffi,
# chardet и websockets — всё это ради переменной, которую никто не читал.
# Если когда-нибудь понадобится API — импортируйте его ЛЕНИВО, внутри функции.


try:
    from PIL import Image, ImageFile, ImageOps
    ImageFile.LOAD_TRUNCATED_IMAGES = True
except Exception:
    Image = None
    ImageOps = None


try:
    import pillow_heif
    pillow_heif.register_heif_opener()
    if hasattr(pillow_heif, "register_avif_opener"):
        pillow_heif.register_avif_opener()
except Exception:
    pillow_heif = None


# ── Сеть: requests подключается ЛЕНИВО ──────────────────────────────────────
# requests сам поставляет certifi-бандл и проверяет сертификаты — это решает
# CERTIFICATE_VERIFY_FAILED в собранном .exe / Windows Sandbox без системных CA.
#
# Но импортировать его на старте незачем: первым в сеть выходит автообновление
# через 2.5 секунды после показа окна, и делает это из ФОНОВОГО потока. Импорт
# на уровне модуля стоил ~240 мс перед появлением окна (сам requests + urllib3 +
# ssl + charset_normalizer), поэтому он перенесён внутрь _requests().
#
# Модульный __getattr__ ниже оставляет привычным `config.requests` — им
# пользуются тесты, подменяя requests.get/Session.
_requests_mod = None

from si_hyx_parts.config.requests import _requests, __getattr__, _Resp, http_get


# Config
IS_WIN = sys.platform.startswith("win")


if IS_WIN:
    CONFIG_DIR = os.path.join(os.getenv('APPDATA') or str(Path.home()), "unified_media_tool") 
else:
    CONFIG_DIR = os.path.join(str(Path.home()), ".unified_media_tool")


os.makedirs(CONFIG_DIR, exist_ok=True)


SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")

from si_hyx_parts.config.hw_decode_device_types import _hw_decode_device_types

os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", _hw_decode_device_types())

from si_hyx_parts.config.quiet_bundled_ffmpeg_logging import _quiet_bundled_ffmpeg_logging

_quiet_bundled_ffmpeg_logging()


COOKIE_PATHS = {
    'youtube':   os.path.join(CONFIG_DIR, "cookies_youtube.txt"),
    'instagram': os.path.join(CONFIG_DIR, "cookies_instagram.txt"),
    'tiktok':    os.path.join(CONFIG_DIR, "cookies_tiktok.txt"),
    'bilibili':  os.path.join(CONFIG_DIR, "cookies_bilibili.txt"),
    'default':   os.path.join(CONFIG_DIR, "cookies.txt"),
}


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"

from si_hyx_parts.config.resolve_tool import _resolve_tool


FFMPEG = _resolve_tool("ffmpeg")


FFPROBE = _resolve_tool("ffprobe")

from si_hyx_parts.config.resolve_ffmpeg7_dir import _resolve_ffmpeg7_dir


FFMPEG7_DIR = _resolve_ffmpeg7_dir()

from si_hyx_parts.config.resolve_asset import _resolve_asset


APP_ICON = _resolve_asset("icon.ico")
OPEN_FILE_ICON = _resolve_asset("open-file.svg")

from si_hyx_parts.config.ytdlp_base_cmd import (
    ytdlp_base_cmd,
    _bin_dirs,
    subprocess_env,
    deno_available,
    cpu_thread_count,
)


TEMP_DIR = tempfile.gettempdir()


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


# Исправлена альфа (прозрачность) цветов для большей заметности
COLOR_PROC = QColor(30, 144, 255, 210)   # Синий — обрабатывается


COLOR_DONE = QColor(46, 204, 113, 210)   # Зелёный — готово


COLOR_ERR  = QColor(231, 76,  60,  210)  # Красный — ошибка


# Кастомная роль для хранения статуса строки
ITEM_STATUS_ROLE = Qt.ItemDataRole.UserRole + 10
# Кастомная роль: на странице обработки помечает обработанную картинку, у которой
# можно сравнить исходник и результат (значок-«сравнение» на превью).
ITEM_COMPARE_ROLE = Qt.ItemDataRole.UserRole + 11
# Кастомная роль: помечает строку как аудио (без видеоряда) — для неё в колонке
# «Превью» не резервируется место под миниатюру, строка компактнее, имя по центру.
ITEM_AUDIO_ROLE = Qt.ItemDataRole.UserRole + 12


ALLOWED_IMG = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp', '.gif', '.avif'}


# Изображения для ленты последних файлов (сверху). SVG показываем в ленте
# (растеризуется через QtSvg), но в очередь обработки он не попадает — pipeline
# на Pillow его не открывает, поэтому ALLOWED_IMG расширять нельзя.
RIBBON_IMG = ALLOWED_IMG | {'.svg'}


ALLOWED_MEDIA = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.opus', '.wma'}


# Аудио-форматы (подмножество ALLOWED_MEDIA без видеоряда) — у них в очереди
# обработки нет превью-кадра, строку рисуем компактнее (см. PreviewNameDelegate).
ALLOWED_AUDIO = {'.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.opus', '.wma'}


FORMAT_OPTIONS = {
    "2160p (4K)": 'bestvideo[height<=2160]+bestaudio/best[height<=2160]/best',
    "1080p": 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best',
    "720p": 'bestvideo[height<=720]+bestaudio/best[height<=720]/best',
    "480p": 'bestvideo[height<=480]+bestaudio/best[height<=480]/best',
    "360p": 'bestvideo[height<=360]+bestaudio/best[height<=360]/best',
}


MERGE_OPTIONS = ["mp4", "mkv", "webm"]


AUDIO_BITRATES = ["auto", "8", "16", "24", "32", "48", "64", "96", "128", "160", "192", "256"]

# --- Идентификация приложения ---
APP_NAME = "SI-HYX"
APP_VERSION = "0.6.0"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"
# Необязательное обновление: перед сборкой (build.bat) поставь True, если этот
# релиз НЕ должен всплывать плашкой у уже установленных пользователей — сам
# релиз на GitHub при этом остаётся обычным (не draft, не pre-release), новые
# скачивания получают именно его. Узнать о таком обновлении можно только
# вручную, кнопкой «Проверить обновления» (см. _check_updates в main.py). Не
# забудь вернуть False перед следующим обычным (обязательным) релизом.
SILENT_UPDATE = True
# Репозиторий для автообновления (GitHub Releases)
GITHUB_OWNER = "GoldensFire"
GITHUB_REPO = "SI-HYX"
DISCORD_URL = "https://discord.gg/EPCE3rMfFa"
GITHUB_URL = "https://github.com/GoldensFire/SI-HYX"
GUIDE_URL = "https://steamcommunity.com/sharedfiles/filedetails/?id=3744506167"
# Приём отчётов об ошибках (кнопка «Сообщить об ошибке» в диалогах ошибки).
# Cloudflare Worker, который принимает JSON POST и пересылает его (напр. в Discord).
# Пусто → кнопка отчёта в диалоге будет неактивна.
ERROR_REPORT_URL = "https://bold-shadow-2a11.sigame.workers.dev/"
# База синхронизации вкладки Collab: Cloudflare Worker + KV,
# который принимает/отдаёт текстовый обзор пака по коду комнаты. Пусто →
# в самой вкладке можно вписать адрес вручную (поле «Сервер»). См. coop_worker.js.
COOP_SYNC_URL = ""
HTTP_PORT = 7432  # порт локального сервера для браузерного расширения

# Метка для пунктов выпадающих списков, которые являются значением по умолчанию.
# В UI показывается " (по умолчанию)", но в логику (ffmpeg и т.п.) уходит чистое значение.
DEFAULT_TAG = " (по умолчанию)"

from si_hyx_parts.config.strip_default_tag import strip_default_tag


# --- Modern Dark Stylesheet (Catppuccin Mocha inspired) ---
from si_hyx_parts.config.stylesheet import STYLESHEET
