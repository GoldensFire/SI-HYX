# -*- coding: utf-8 -*-
# config.py — импорты, пути, константы, стили, FORMAT_OPTIONS


import sys


import os


import base64


import traceback


import subprocess


import threading


import uuid


import tempfile


import urllib.request


import io


import time


import re


import shutil


import json


import random


import functools


from pathlib import Path


from collections import deque


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
        QStyledItemDelegate, QStyle, QSplashScreen
    )
    from PyQt6.QtCore import (
        Qt, QThread, pyqtSignal, QSize, QRunnable, QThreadPool, QByteArray, QTimer
    )
    from PyQt6.QtGui import (
        QAction, QColor, QFont, QIcon, QPixmap, QBrush, QImage as QtGuiImage,
        QKeySequence, QShortcut, QPainter, QPen
    )
    from PyQt6.QtNetwork import QLocalServer, QLocalSocket
except Exception as e:
    fail_and_exit("Не удалось импортировать PyQt6. Убедитесь, что установлено: pip install PyQt6", e)


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


# Config
IS_WIN = sys.platform.startswith("win")


if IS_WIN:
    CONFIG_DIR = os.path.join(os.getenv('APPDATA') or str(Path.home()), "unified_media_tool") 
else:
    CONFIG_DIR = os.path.join(str(Path.home()), ".unified_media_tool")


os.makedirs(CONFIG_DIR, exist_ok=True)


SETTINGS_FILE = os.path.join(CONFIG_DIR, "settings.json")


COOKIE_PATHS = {
    'youtube':   os.path.join(CONFIG_DIR, "cookies_youtube.txt"),
    'instagram': os.path.join(CONFIG_DIR, "cookies_instagram.txt"),
    'tiktok':    os.path.join(CONFIG_DIR, "cookies_tiktok.txt"),
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


TEMP_DIR = tempfile.gettempdir()


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if IS_WIN else 0


# Исправлена альфа (прозрачность) цветов для большей заметности
COLOR_PROC = QColor(30, 144, 255, 210)   # Синий — обрабатывается


COLOR_DONE = QColor(46, 204, 113, 210)   # Зелёный — готово


COLOR_ERR  = QColor(231, 76,  60,  210)  # Красный — ошибка


# Кастомная роль для хранения статуса строки
ITEM_STATUS_ROLE = Qt.ItemDataRole.UserRole + 10


ALLOWED_IMG = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp', '.gif', '.avif'}


ALLOWED_MEDIA = {'.mp4', '.mkv', '.avi', '.mov', '.webm', '.flv', '.mp3', '.wav', '.aac', '.m4a', '.flac', '.ogg', '.opus', '.wma'}


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
APP_VERSION = "0.1 BETA"
APP_TITLE = f"{APP_NAME} {APP_VERSION}"
DISCORD_URL = "https://discord.gg/EPCE3rMfFa"
HTTP_PORT = 7432  # порт локального сервера для браузерного расширения


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
    padding: 7px 22px;
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
