# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_workers.py — фоновые воркеры вкладки «Монтаж»: резка (ffmpeg/Smart Cut),
# прокси-превью, загрузка звуковой волны, извлечение субтитров, удаление объектов.
# Слой поверх edit_tab_base.

# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import math
import os
import subprocess
import sys
import tempfile
import threading
import wave
from config import (CREATE_NO_WINDOW, FFMPEG, FFPROBE, QThread, pyqtSignal)
from edit_tab_base import (_parse_srt, time_to_s)
from utils import csv_first
from PyQt6.QtCore import (QIODevice)
from PyQt6.QtGui import (QImage)

from si_hyx_parts.edit_tab_workers.share_delete_iodevice import (
    ShareDeleteIODevice,
    start_share_delete_feeder,
    FfmpegWorker,
)

from si_hyx_parts.edit_tab_workers.smart_cut_worker import SmartCutWorker

from si_hyx_parts.edit_tab_workers.video_inpaint_worker import (
    VideoInpaintWorker,
    overlay_top_left,
    blend_bgra,
    track_box_at,
)

from si_hyx_parts.edit_tab_workers.track_path_worker import TrackPathWorker

from si_hyx_parts.edit_tab_workers.track_overlay_worker import TrackOverlayWorker

from si_hyx_parts.edit_tab_workers.proxy_worker import ProxyWorker

from si_hyx_parts.edit_tab_workers.audio_waveform_loader import (
    AudioWaveformLoader,
    AudioSegmentWaveformLoader,
    SubtitleExtractor,
)

from si_hyx_parts.edit_tab_workers.ass_extractor import AssExtractor, _SeekThumbnailer
