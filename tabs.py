# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# tabs.py — вкладки интерфейса
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import base64
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from config import (
    ALLOWED_AUDIO, ALLOWED_IMG, ALLOWED_MEDIA, AUDIO_BITRATES,
    CREATE_NO_WINDOW, DEFAULT_TAG, FFMPEG, FORMAT_OPTIONS, IS_WIN,
    ITEM_AUDIO_ROLE, ITEM_COMPARE_ROLE, ITEM_STATUS_ROLE, Image, ImageOps,
    MERGE_OPTIONS, QAbstractItemView, QAbstractSpinBox, QAction,
    QApplication, QByteArray, QCheckBox, QComboBox, QDoubleSpinBox,
    QFileDialog, QFont, QFormLayout, QFrame, QGroupBox, QHBoxLayout,
    QHeaderView, QIcon, QKeySequence, QLabel, QLineEdit, QMenu, QPixmap,
    QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QShortcut,
    QSize, QSlider, QSpinBox, QThreadPool, QTimer, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget, Qt, cpu_thread_count, get_icon,
    icon_html, pyqtSignal, status_html, strip_default_tag
)
from utils import (
    default_download_dir, fmt_bitrate_with_codec, get_media_info,
    get_video_codec_label, human_size, is_embed_candidate, kodik_get_info,
    load_settings, mask_html_js, mask_html_js_lite, measure_loudness,
    parse_youtube_start_seconds, play_done_sound, save_settings
)
from widgets import (
    DraggableTreeWidget, InvertedWheelComboBox, LocalThumbnailRunnable,
    PreviewNameDelegate, RemoteThumbnailRunnable, SpeedSpinBox,
    StatusColorDelegate, ZeroSpinBox, _JumpSlider, _icon_btn, info_badge,
    label_with_info, row_with_info, show_image_compare,
    show_image_fullscreen, show_video_compare
)
from workers import (InfoWorker, ProcessWorker, YtdlpWorker)

from si_hyx_parts.tabs.ytdlp_tab import YtdlpTab, MediaTab, Base64Tab

from si_hyx_parts.tabs.prompt_tab import PromptTab
