# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab.py — публичный API вкладки «Монтаж» и standalone-entry main().
#
# Реализация каждого слоя разложена на небольшие модули в si_hyx_parts/;
# навигация — CODE_MAP.md. Публичные модули сохраняют общее состояние и импорты:
#   edit_tab_base    — константы, палитра, чистые хелперы (время, ffprobe, ASS)
#   edit_tab_workers — фоновые QThread-воркеры (резка, прокси, волна, субтитры)
#   edit_tab_widgets — виджеты (волна, холст видео, полный экран, превью)
#   edit_tab_dialogs — диалоги (маска, редактор/конструктор субтитров, пикселизация)
#   edit_tab_frames  — покадровая сетка и предекодирование кадров вокруг плейхеда
#   edit_tab.py      — экспорт EditTab и main(); реализация — si_hyx_parts/edit_tab/
#
# ВАЖНО: edit_tab_base стоит первым в цепочке — он выставляет env-переменные
# Qt-бэкенда (QSG_RHI_BACKEND/QT_MEDIA_BACKEND) ДО создания QApplication, что
# критично для видео, и определяет флаги _HAS_MULTIMEDIA / LIBASS_AVAILABLE.
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import errno
import json
import math
import os
import shutil
import subprocess
import sys
if __name__ in ("__main__", "__mp_main__"):
    sys.modules["edit_tab"] = sys.modules[__name__]
import tempfile
import time
import uuid
from collections import deque
from functools import partial
from pathlib import Path
from config import (
    CONFIG_DIR, CREATE_NO_WINDOW, FFMPEG, FFPROBE, QAction, QApplication,
    QCheckBox, QComboBox, QCursor, QDialog, QEvent, QFileDialog, QFont,
    QFontMetrics, QFrame, QHBoxLayout, QKeySequence, QLabel, QLineEdit,
    QMenu, QMessageBox, QPoint, QProgressBar, QPushButton, QRectF, QScrollArea,
    QSize, QSlider, QSpinBox, QTimer, QVBoxLayout, QWidget, Qt, get_icon,
    icon_html
)
from widgets import (info_badge)
from utils import get_pix_fmt, save_json_atomic
from msgbox import (
    msgbox_critical, msgbox_information, msgbox_question, msgbox_warning
)
from edit_tab_base import (
    C, EDITOR_SETTINGS_PATH, LIBASS_AVAILABLE, QAudioFormat,
    QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer,
    QVideoWidget, install_audio_device_recovery,
    _HAS_MULTIMEDIA, _cues_to_ass, _fmt_channels, _fullscreen_icon,
    _libass, _parse_srt, _pixelize_block_sequence, _pixelize_filter,
    _unique_output,
    format_fps, make_divider, make_icon_btn, run_ffprobe, s_to_time,
    time_to_s
)
from edit_tab_workers import (
    AssExtractor, AudioSegmentWaveformLoader, AudioWaveformLoader,
    FfmpegWorker, ProxyWorker, ShareDeleteIODevice, SmartCutWorker,
    SubtitleExtractor, TrackOverlayWorker, TrackPathWorker, VideoInpaintWorker
)
from edit_tab_widgets import (
    AudioMeter, FullscreenVideo, InfoCard, SeekPreview, SeekSlider,
    SubtitleOverlay, VideoCanvas, VolumeLabel, VolumeSlider,
    WaveformWidget
)
from edit_tab_dialogs import (
    SubtitleCreatorDialog, SubtitleEditDialog, _PixelizeDialog,
    _TrackAttachDialog, _VideoMaskDialog
)
from edit_tab_frames import (AudioScrubber, FrameGrid, FramePrefetcher,
                             probe_frame_size)
from edit_tab_overlay import (
    ImageOverlay, OverlayCropDialog, OverlayLayersPanel, fit_rect_norm,
    load_overlay_image, overlay_chroma_format, overlay_filter_graph,
    qimage_to_bgra, render_overlays
)
from PyQt6.QtCore import (QUrl)
from PyQt6.QtGui import (QImage, QPainter, QShortcut)
from PyQt6.QtWidgets import (QScrollBar, QSizePolicy, QStyle, QToolTip)

from si_hyx_parts.edit_tab.is_attached_pic import _is_attached_pic

from si_hyx_parts.edit_tab.edit_tab import EditTab

from si_hyx_parts.edit_tab.main import main


if __name__ == "__main__":
    main()
