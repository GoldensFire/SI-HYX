# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# config.py — импорты, пути, константы, стили, FORMAT_OPTIONS


import sys


import os


import base64


import traceback


import subprocess


import threading


import uuid


import tempfile


import urllib.parse


import io


import time


import re


import shutil


import json


import random


import functools


import requests


from pathlib import Path


from collections import deque


# Аппаратное декодирование видео в QtMultimedia (бэкенд ffmpeg) настраивается
# ниже, ПОСЛЕ определения SETTINGS_FILE (нужно прочитать настройку
# video_hw_decode). См. блок «Аппаратное декодирование видео».


# PyQt6 imports
def fail_and_exit(msg, exc=None):
    print(msg)
    if exc is not None:
        traceback.print_exception(type(exc), exc, exc.__traceback__)
    sys.exit(1)


try:
    from PyQt6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QTabWidget, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
        QFileDialog, QSpinBox, QDoubleSpinBox, QCheckBox, QProgressBar,
        QMessageBox, QTextEdit, QPlainTextEdit, QSlider, QGroupBox, QFormLayout, QComboBox,
        QLineEdit, QMenu, QScrollArea, QAbstractSpinBox, QAbstractItemView,
        QTreeWidgetItemIterator, QHeaderView, QToolButton, QDialog,
        QStyledItemDelegate, QStyle, QSplashScreen, QToolTip, QFrame,
        QInputDialog, QKeySequenceEdit, QListWidget, QListWidgetItem,
        QStackedWidget
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


# ╔══════════════════════════════════════════════════════════════════════════╗
# ║  ВНИМАНИЕ РАЗРАБОТЧИКА: В этом приложении категорически запрещено          ║
# ║  использовать эмодзи. Все новые иконки добавлять строго через метод/       ║
# ║  функцию get_icon() из библиотеки qtawesome!                              ║
# ╚══════════════════════════════════════════════════════════════════════════╝
def get_icon(name, color='#cdd6f4'):
    """Единая точка создания иконок интерфейса. У приложения ТОЛЬКО тёмная тема,
    поэтому по умолчанию иконки светлые — но не «жёсткий» белый, а мягкий
    Catppuccin text (#cdd6f4): лучше смотрится на тёмном фоне. На кнопках со
    СВЕТЛОЙ заливкой (accent/green/red) передавайте тёмный цвет (#11111b/#1e1e2e).
    scale_factor<1 даёт глифу поля внутри иконки — он не упирается в края кнопки.
    name — имя иконки из паков Font Awesome 5 Solid (fa5s.*) или Material Design (mdi6.*)."""
    return qta.icon(name, color=color, scale_factor=0.8)


def get_icon_pixmap(name, size=16, color='white'):
    """Иконка как QPixmap — для QLabel.setPixmap() (значки без интерактивности)."""
    return get_icon(name, color=color).pixmap(QSize(size, size))


def icon_html(name, size=16, color='white'):
    """Иконка как <img …> для вставки в rich-text (QLabel/HTML), где нельзя
    использовать setIcon(). Заменяет инлайновые эмодзи в HTML-подписях."""
    from PyQt6.QtCore import QBuffer
    pm = get_icon_pixmap(name, size, color)
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QBuffer.OpenModeFlag.WriteOnly)
    pm.save(buf, 'PNG')
    buf.close()
    b64 = bytes(ba.toBase64()).decode('ascii')
    return (f"<img src='data:image/png;base64,{b64}' "
            f"width='{size}' height='{size}'>")


def status_html(icon_name, text, color='white', size=13):
    """Строка статуса «значок + текст» для QLabel.setText(): значок-эмодзи
    заменён на векторную иконку. Текст экранируется (html.escape), чтобы
    «<script>», «<...>» и т.п. в сообщениях не ломали rich-text рендеринг."""
    import html as _html
    return icon_html(icon_name, size, color) + " " + _html.escape(str(text))


# Optional libs
try:
    import yt_dlp
except Exception:
    yt_dlp = None


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


# requests сам поставляет certifi-бандл и проверяет сертификаты — это решает
# CERTIFICATE_VERIFY_FAILED в собранном .exe / Windows Sandbox без системных CA.
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass


class _Resp:
    """Минимальная обёртка над requests.Response для совместимости с кодом,
    который раньше работал с urllib: .read() / .read(n), .headers.get(),
    статус, и работа как контекст-менеджер (`with ... as r:`)."""
    def __init__(self, r):
        self._r = r
        self._it = None
        self.headers = r.headers
        self.status = r.status_code

    def read(self, amt=None):
        if amt is None:
            return self._r.content
        if self._it is None:
            self._it = self._r.iter_content(chunk_size=amt)
        try:
            return next(self._it)
        except StopIteration:
            return b""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        try: self._r.close()
        except Exception: pass


def http_get(url, headers=None, timeout=30, stream=True, allow_insecure=True):
    """GET через requests с проверкой сертификата.
    allow_insecure=True: при SSL-ошибке повторяет без проверки (verify=False) —
    нужно для превью/картинок на машинах без системных CA.
    allow_insecure=False: повтора НЕТ, нужен валидный сертификат. Критично для
    автообновления: иначе MITM мог бы подсунуть вредоносный .exe (повтор без
    проверки = установка непроверенного кода = RCE).
    Возвращает _Resp (совместим со старым urllib-кодом)."""
    h = headers or {}
    try:
        r = requests.get(url, headers=h, timeout=timeout, stream=stream)
        r.raise_for_status()
        return _Resp(r)
    except requests.exceptions.SSLError:
        if not allow_insecure:
            raise
        r = requests.get(url, headers=h, timeout=timeout, stream=stream, verify=False)
        r.raise_for_status()
        return _Resp(r)


# Config
IS_WIN = sys.platform.startswith("win")


if IS_WIN:
    CONFIG_DIR = os.path.join(os.getenv('APPDATA') or str(Path.home()), "unified_media_tool") 
else:
    CONFIG_DIR = os.path.join(str(Path.home()), ".unified_media_tool")


os.makedirs(CONFIG_DIR, exist_ok=True)


SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")


# ── Аппаратное декодирование видео (H.264 / HEVC) в QtMultimedia ─────────────
# По умолчанию ВКЛЮЧЕНО: H.264/HEVC декодируются на GPU (D3D11VA/DXVA2) — тяжёлые
# файлы в «Монтаже» играют плавно (как в Filmora), а не упираются в ЦП.
# AV1 в «Монтаже» ВСЕГДА перегоняется в H.264-прокси ДО плеера, поэтому ускорение
# его не ломает. ОДНАКО на iGPU без аппаратного AV1-декодера (напр. Vega у
# Ryzen 5600H) ПРЯМОЕ воспроизведение AV1 (вкладка SiQuesterHYX) при включённом
# ускорении может дать чёрный экран — тогда снимите галку «Аппаратное ускорение
# видео» в Настройках. Программный рендер видео несовместим с HW-декодером —
# при нём ускорение тоже выключается.
# Qt читает переменную один раз на процесс при первом декодировании, поэтому
# ставим её здесь — config.py импортируется раньше любого QtMultimedia-плеера
# (и вкладки «Монтаж», и вкладки SiQuesterHYX).
def _hw_decode_device_types():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as _f:
            _s = json.load(_f)
        if _s.get("video_software_render", False):
            return ""                       # программный рендер → только ЦП
        if not _s.get("video_hw_decode", True):
            return ""                       # пользователь выключил ускорение
    except Exception:
        pass
    return "d3d11va,dxva2"

os.environ.setdefault("QT_FFMPEG_DECODING_HW_DEVICE_TYPES", _hw_decode_device_types())

# Раз аппаратный AV1-декодер отсутствует на многих GPU (см. коммент выше),
# FFmpeg-бэкенд QtMultimedia на КАЖДЫЙ кадр AV1 пишет в консоль "Failed setup
# for format d3d11: hwaccel initialisation returned error" (сам кадр при этом
# успешно докодируется программно — это просто спам, не ошибка воспроизведения).
# ВАЖНО: это НЕ идёт через QLoggingCategory (QT_LOGGING_RULES тут бессилен) —
# это сырой av_log() из libavutil/libavcodec, который FFmpeg печатает в stderr
# напрямую. Единственный способ заглушить именно эти строки — вызвать
# av_log_set_level(AV_LOG_QUIET) в той же avutil-*.dll, что уже загружена в
# процесс вместе с Qt6Multimedia (ctypes.CDLL находит УЖЕ загруженный модуль
# по пути и просто увеличивает refcount — глобальный уровень логирования общий
# для всего процесса, включая FFmpeg-бэкенд Qt). Не трогает отдельные
# субпроцессы ffmpeg.exe (у них свой -loglevel).
def _quiet_bundled_ffmpeg_logging():
    try:
        import ctypes, glob
        import PyQt6
        bin_dir = os.path.join(os.path.dirname(PyQt6.__file__), "Qt6", "bin")
        dlls = glob.glob(os.path.join(bin_dir, "avutil-*.dll"))
        if not dlls:
            return
        avutil = ctypes.CDLL(dlls[0])
        avutil.av_log_set_level(-8)   # AV_LOG_QUIET
    except Exception:
        pass

_quiet_bundled_ffmpeg_logging()


COOKIE_PATHS = {
    'youtube':   os.path.join(CONFIG_DIR, "cookies_youtube.txt"),
    'instagram': os.path.join(CONFIG_DIR, "cookies_instagram.txt"),
    'tiktok':    os.path.join(CONFIG_DIR, "cookies_tiktok.txt"),
    'bilibili':  os.path.join(CONFIG_DIR, "cookies_bilibili.txt"),
    'default':   os.path.join(CONFIG_DIR, "cookies.txt"),
}


USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"


def _resolve_tool(name):
    """Ищет ffmpeg/ffprobe рядом с программой (для сборки в .exe с bundled-ffmpeg).
    Порядок: _MEIPASS (PyInstaller) → папка exe/скрипта → подпапка bin → PATH.
    Если ничего не найдено — возвращает имя для поиска в системном PATH.
    """
    exe = name + (".exe" if IS_WIN else "")
    roots = []
    base = getattr(sys, "_MEIPASS", None)        # распакованные данные PyInstaller
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))  # папка exe
    roots.append(os.path.dirname(os.path.abspath(__file__)))            # папка скрипта
    for r in roots:
        for cand in (os.path.join(r, exe), os.path.join(r, "bin", exe)):
            if os.path.isfile(cand):
                return cand
    return name  # из системного PATH


FFMPEG = _resolve_tool("ffmpeg")


FFPROBE = _resolve_tool("ffprobe")


def _resolve_ffmpeg7_dir():
    """Каталог с отдельным ffmpeg 7.x — ИСКЛЮЧИТЕЛЬНО для yt-dlp `--download-sections`.
    Основной ffmpeg в bin — 8.x, а он ломает нарезку по таймингам (внешний баг
    ffmpeg 8.1, yt-dlp issue #16546: битый/audio-only отрезок). ffmpeg 7.x режет
    секцию корректно. Кладём его в подпапку bin/ffmpeg7. Если её нет — возвращаем
    None, и нарезка откатывается на обычный ffmpeg (лучше кривой отрезок, чем краш)."""
    roots = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    for r in roots:
        for cand in (os.path.join(r, "ffmpeg7"), os.path.join(r, "bin", "ffmpeg7")):
            if os.path.isfile(os.path.join(cand, "ffmpeg" + (".exe" if IS_WIN else ""))):
                return cand
    return None


FFMPEG7_DIR = _resolve_ffmpeg7_dir()


def _resolve_asset(name):
    """Ищет файл-ресурс (иконку и т.п.) рядом с программой.
    Порядок: _MEIPASS (PyInstaller) → папка exe/скрипта → их подпапка bin.
    Возвращает абсолютный путь или None, если не найден."""
    roots = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        roots.append(base)
    roots.append(os.path.dirname(os.path.abspath(sys.argv[0] or ".")))
    roots.append(os.path.dirname(os.path.abspath(__file__)))
    for r in roots:
        for cand in (os.path.join(r, name), os.path.join(r, "bin", name)):
            if os.path.isfile(cand):
                return cand
    return None


APP_ICON = _resolve_asset("icon.ico")


def ytdlp_base_cmd():
    """База для запуска yt-dlp как процесса.
    Приоритет: bin/yt-dlp.exe (bundled, обновляемый) → системный yt-dlp в PATH →
    `python -m yt_dlp` (только в dev, не во frozen-сборке).
    Возвращает список аргументов или None, если yt-dlp нигде не найден.
    """
    exe = _resolve_tool("yt-dlp")
    if os.path.isfile(exe):
        return [exe]
    w = shutil.which("yt-dlp")
    if w:
        return [w]
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "yt_dlp"]
    return None


def _bin_dirs():
    """Каталоги, где лежат bundled-бинарники (ffmpeg/yt-dlp/deno)."""
    dirs = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        dirs += [base, os.path.join(base, "bin")]
    d1 = os.path.dirname(os.path.abspath(sys.argv[0] or "."))
    dirs += [d1, os.path.join(d1, "bin")]
    d2 = os.path.dirname(os.path.abspath(__file__))
    dirs += [d2, os.path.join(d2, "bin")]
    # Уникальные существующие каталоги, порядок сохраняется
    seen, out = set(), []
    for d in dirs:
        if d and d not in seen and os.path.isdir(d):
            seen.add(d); out.append(d)
    return out


def subprocess_env():
    """os.environ с добавленными в PATH каталогами bin — чтобы yt-dlp находил
    deno (нужен для n-challenge YouTube, иначе отдаёт только 360p) и ffmpeg."""
    env = os.environ.copy()
    extra = _bin_dirs()
    if extra:
        env["PATH"] = os.pathsep.join(extra) + os.pathsep + env.get("PATH", "")
    return env


def deno_available():
    """True, если deno найден (в bin рядом с программой или в системном PATH)."""
    exe = _resolve_tool("deno")
    if os.path.isfile(exe):
        return True
    return shutil.which("deno") is not None


def cpu_thread_count():
    """Надёжное число логических потоков ЦП.
    os.cpu_count() в части frozen/песочница-окружений (PyInstaller windowed,
    Windows Sandbox с ограниченным affinity) возвращает None → счётчик «потоков»
    падал до 1/1. Фолбэк: NUMBER_OF_PROCESSORS → разумный дефолт 4."""
    n = os.cpu_count()
    if n and n > 0:
        return n
    try:
        n = int(os.environ.get("NUMBER_OF_PROCESSORS", "") or 0)
        if n > 0:
            return n
    except Exception:
        pass
    return 4


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


SUB_OPTIONS = ["Выкл", "all", "en", "ru", "es", "fr", "de"]


AUDIO_OPTIONS = ["Original", "en", "ru", "es", "fr", "de"]


AUDIO_BITRATES = ["auto", "8", "16", "24", "32", "48", "64", "96", "128", "160", "192", "256"]

# --- Идентификация приложения ---
APP_NAME = "SI-HYX"
APP_VERSION = "0.5.4"
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
ERROR_REPORT_URL = "https://bold-shadow-2a11.longld342.workers.dev/"
# База синхронизации вкладки Collab: Cloudflare Worker + KV,
# который принимает/отдаёт текстовый обзор пака по коду комнаты. Пусто →
# в самой вкладке можно вписать адрес вручную (поле «Сервер»). См. coop_worker.js.
COOP_SYNC_URL = ""
HTTP_PORT = 7432  # порт локального сервера для браузерного расширения

# Метка для пунктов выпадающих списков, которые являются значением по умолчанию.
# В UI показывается " (по умолчанию)", но в логику (ffmpeg и т.п.) уходит чистое значение.
DEFAULT_TAG = " (по умолчанию)"


def strip_default_tag(s):
    """Убирает пометку ' (по умолчанию)' из текста пункта списка."""
    if isinstance(s, str):
        return s.replace(DEFAULT_TAG, "").strip()
    return s


# --- Modern Dark Stylesheet (Catppuccin Mocha inspired) ---
STYLESHEET = """
QMainWindow, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', Arial, sans-serif;
    font-size: 13px;
}
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 10px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 5px 14px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}
QPushButton:pressed {
    background-color: #585b70;
}
QPushButton:disabled {
    background-color: #1e1e2e;
    color: #585b70;
    border-color: #313244;
}
QPushButton:checked {
    background-color: #89b4fa;
    color: #1e1e2e;
    font-weight: bold;
    border-color: #89b4fa;
}
QPushButton#b_run {
    background-color: #a6e3a1;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    min-height: 30px;
    padding: 6px 20px;
}
QPushButton#b_run:hover { background-color: #94e2d5; }
QPushButton#b_run:disabled { background-color: #585b70; color: #1e1e2e; }
QPushButton#b_stop {
    background-color: #f38ba8;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    min-height: 30px;
}
QPushButton#b_stop:hover { background-color: #eba0ac; }
QPushButton#b_stop:disabled { background-color: #585b70; color: #1e1e2e; }
QPushButton#b_restart {
    background-color: #fab387;
    color: #1e1e2e;
    font-weight: bold;
    border: none;
    min-height: 30px;
}
QPushButton#b_restart:hover { background-color: #f9e2af; }
QToolButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    padding: 4px 8px;
    min-height: 24px;
}
QToolButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}
/* Встроенная кнопка очистки (✕) внутри QLineEdit/QComboBox — без рамки,
   паддинга и min-height, иначе она наследует стиль QToolButton и смещается. */
QLineEdit QToolButton, QComboBox QToolButton {
    background: transparent;
    border: none;
    border-radius: 0px;
    padding: 0px;
    margin: 0px;
    min-width: 0px;
    min-height: 0px;
}
QLineEdit QToolButton:hover, QComboBox QToolButton:hover {
    background: transparent;
    border: none;
}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    padding: 4px 7px;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
    min-height: 22px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #89b4fa;
}
QSpinBox::up-button, QDoubleSpinBox::up-button,
QSpinBox::down-button, QDoubleSpinBox::down-button {
    background-color: #45475a;
    border: none;
    width: 16px;
    border-radius: 2px;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
    background-color: #585b70;
}
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-bottom: 5px solid #89b4fa;
    width: 0;
    height: 0;
}
QSpinBox::up-arrow:disabled, QDoubleSpinBox::up-arrow:disabled {
    border-bottom-color: #585b70;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #89b4fa;
    width: 0;
    height: 0;
}
QSpinBox::down-arrow:disabled, QDoubleSpinBox::down-arrow:disabled {
    border-top-color: #585b70;
}
QComboBox::drop-down {
    border: none;
    background: transparent;
    width: 22px;
}
QComboBox::down-arrow {
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid #89b4fa;
    width: 0;
    height: 0;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 4px;
    selection-background-color: #45475a;
    outline: none;
}
QTreeWidget {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    alternate-background-color: #1e1e2e;
    show-decoration-selected: 1;
    outline: none;
}
QTreeWidget::item {
    padding: 3px 2px;
    border: none;
}
QTreeWidget::item:hover {
    background-color: transparent;
}
QTreeWidget::item:selected {
    background-color: transparent;
    color: #cdd6f4;
}
QTableWidget {
    background-color: #181825;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 5px;
    alternate-background-color: #1e1e2e;
    gridline-color: #313244;
    outline: none;
}
QTableWidget::item {
    padding: 3px 2px;
    border: none;
}
QTableWidget::item:hover {
    background-color: #313244;
}
QTableWidget::item:selected {
    background-color: #45475a;
    color: #cdd6f4;
}
QTableWidget::item:selected:active {
    background-color: #585b70;
}
QHeaderView::section {
    background-color: #24273a;
    color: #89b4fa;
    border: none;
    border-right: 1px solid #45475a;
    border-bottom: 1px solid #45475a;
    padding: 5px 8px;
    font-weight: bold;
    font-size: 12px;
}
QHeaderView::section:last { border-right: none; }
QTextEdit {
    background-color: #181825;
    color: #a6e3a1;
    border: 1px solid #45475a;
    border-radius: 4px;
    font-family: 'Consolas', 'Cascadia Code', 'Courier New', monospace;
    font-size: 12px;
    padding: 2px;
}
QProgressBar {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 5px;
    text-align: center;
    color: #cdd6f4;
    font-weight: bold;
    min-height: 20px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #89b4fa, stop:1 #cba6f7);
    border-radius: 4px;
}
QTabWidget::pane {
    border: 1px solid #45475a;
    border-top: none;
    border-bottom-left-radius: 5px;
    border-bottom-right-radius: 5px;
}
QTabBar::tab {
    background-color: #24273a;
    color: #a6adc8;
    border: 1px solid #45475a;
    border-bottom: none;
    padding: 5px 12px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
    font-weight: bold;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
}
QTabBar::tab:hover:!selected {
    background-color: #313244;
    color: #cdd6f4;
}
QCheckBox {
    color: #cdd6f4;
    spacing: 7px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #585b70;
    border-radius: 4px;
    background-color: #313244;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}
QCheckBox::indicator:hover { border-color: #89b4fa; }
QSlider::groove:horizontal {
    height: 5px;
    background: #45475a;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #89b4fa;
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    border: 2px solid #1e1e2e;
}
QSlider::handle:horizontal:hover { background: #cba6f7; }
QSlider::sub-page:horizontal {
    background: #89b4fa;
    border-radius: 3px;
}
QScrollBar:vertical {
    background: #181825;
    width: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 5px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover { background: #585b70; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal {
    background: #181825;
    height: 10px;
    margin: 0;
    border-radius: 5px;
}
QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 5px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover { background: #585b70; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QMenu {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item {
    padding: 5px 20px;
    border-radius: 4px;
}
QMenu::item:selected { background-color: #45475a; }
QMenu::separator {
    height: 1px;
    background: #45475a;
    margin: 4px 8px;
}
QLabel { color: #cdd6f4; }
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea > QWidget > QWidget { background: transparent; }
QDialog {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
QMessageBox { background-color: #1e1e2e; color: #cdd6f4; }
QMessageBox QLabel { color: #cdd6f4; }
QToolTip {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #89b4fa;
    border-radius: 5px;
    padding: 5px 8px;
    font-size: 12px;
}
QLabel#infoBadge {
    color: #89b4fa;
    font-weight: bold;
    font-size: 13px;
    border-radius: 9px;
    background: transparent;
}
QLabel#infoBadge:hover {
    color: #cba6f7;
    background: rgba(137,180,250,0.18);
}
"""
