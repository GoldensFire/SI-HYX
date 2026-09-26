# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# main.py — главное окно, HTTP-сервер расширения, точка входа
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import json
import os
import re
import shutil
import subprocess
import sys
if __name__ in ("__main__", "__mp_main__"):
    sys.modules["main"] = sys.modules[__name__]
import tempfile
import threading
import time
from pathlib import Path
from config import (
    APP_ICON, APP_NAME, APP_TITLE, APP_VERSION, CONFIG_DIR, OPEN_FILE_ICON,
    CREATE_NO_WINDOW, DISCORD_URL, GITHUB_OWNER, GITHUB_REPO, GITHUB_URL,
    GUIDE_URL, HTTP_PORT, IS_WIN, QAbstractSpinBox, QApplication,
    QCheckBox, QComboBox, QDialog, QEvent, QGroupBox, QHBoxLayout, QIcon,
    QKeySequence, QLabel, QLineEdit, QListWidget, QLocalServer,
    QLocalSocket, QMainWindow, QMenu, QProgressBar, QPushButton,
    QScrollArea, QSlider, QTabWidget, QTextCursor, QTextEdit, QThreadPool,
    QTimer, QToolButton, QVBoxLayout, QWidget, Qt, STYLESHEET, USER_AGENT,
    get_icon, http_get, icon_html, pyqtSignal, strip_default_tag,
    ytdlp_base_cmd
)
from utils import (check_ffmpeg, load_settings_ex, parse_version,
                   save_settings, settings_files_exist)
from widgets import (
    LatinKeySequenceEdit, RecentFilesStrip, WheelBlocker, combo_set_value,
    info_badge, install_hover_tips
)
from msgbox import msgbox_critical
from tabs import (Base64Tab, MediaTab, PromptTab, YtdlpTab)
from photo_tab import PhotoTab
from edit_tab import EditTab
from taskbar import TaskbarProgress
from PyQt6.QtCore import qInstallMessageHandler, QSize, QTranslator, QLibraryInfo, QLocale
from PyQt6.QtWidgets import QTabBar
import hashlib


# QtMultimedia с FFmpeg-бэкендом (плеер вкладки «Монтаж») при каждой смене
# состояния (play/pause/seek) пересобирает декодер и сыпет безобидными
# «QObject::disconnect: wildcard call disconnects from destroyed signal of
# QFFmpeg::…» в stderr. Глушим ТОЛЬКО этот шум, остальное пропускаем дальше.
_QT_LOG_NOISE = (
    "disconnects from destroyed signal",
    # Безобидное предупреждение opus-декодера ffmpeg-бэкенда при паузе/возобновлении
    # воспроизведения во вкладке «Монтаж» — глушим, чтобы не пугать пользователя.
    "Could not update timestamps for skipped samples",
    # MKV с прикреплёнными шрифтами (Attachment-потоки): ffmpeg-бэкенд QtMultimedia
    # не знает кодек шрифта и сыпет «Could not find codec parameters for stream N
    # (Attachment: none): unknown codec» + совет про analyzeduration/probesize.
    # Это безобидно (шрифты не нужны для воспроизведения видео/аудио) — глушим,
    # в т.ч. когда тот же файл открывает вкладка «SiQuesterHYX».
    "Could not find codec parameters for stream",
    "Consider increasing the value for the 'analyzeduration'",
    # Лента последних файлов при drag&drop ненадолго получает нативное дочернее
    # окно — Qt пишет «must be a top level window». Безобидно (удаление в Корзину
    # уже берёт top-level winId владельцем, см. utils.move_to_trash) — глушим.
    "must be a top level window",
)

from si_hyx_parts.main.qt_message_filter import (
    _qt_message_filter,
    UnifiedWindow,
    _install_crash_handler,
)


# Строка НАМЕРЕННО отличается от прежней «GoldensFire.SI-HYX»: Windows кэширует
# значок панели задач по AppUserModelID, и на машинах, где кнопка уже успела
# нарисоваться пустой (см. _set_taskbar_identity), кэш продолжал отдавать пустой
# значок даже после починки. Новый идентификатор = новая запись кэша. Менять
# строку просто так нельзя — с ней слетает закрепление кнопки на панели задач.
_AUMID = "GoldensFire.SI-HYX.3"

from si_hyx_parts.main.set_taskbar_identity import _set_taskbar_identity, main


if __name__ == "__main__":
    # ОБЯЗАТЕЛЬНО до любого порождения процессов: иначе в собранном (PyInstaller,
    # spawn) приложении дочерний процесс заново запустит весь main(). Нужно для
    # процессного прокси LaMa («Фото → Удаление объектов»).
    import multiprocessing
    multiprocessing.freeze_support()
    main()
