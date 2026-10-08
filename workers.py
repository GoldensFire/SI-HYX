# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# workers.py — фоновые потоки: загрузка (yt-dlp) и обработка (ffmpeg)
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import json
import os
import random
import re
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from config import (
    COOKIE_PATHS, CREATE_NO_WINDOW, FFMPEG, FFMPEG7_DIR, FFPROBE, IS_WIN,
    Image, ImageOps, QRunnable, QThread, QThreadPool, TEMP_DIR,
    USER_AGENT, cpu_thread_count, deno_available, pyqtSignal,
    subprocess_env, ytdlp_base_cmd
)
from utils import (
    clean_ansi, clean_url, detect_ffmpeg_encoders, download_cdn_direct,
    fmt_bitrate_with_codec, get_cookies_path, get_fps_float,
    get_media_info, get_video_codec, get_video_codec_label, host_matches,
    human_size, is_animego_site, is_direct_cdn_video, is_embed_candidate,
    measure_loudness, require_svt, resolve_kodik
)
from utils import _cookie_matches_domain, _RE_DIGITS
from utils import get_pix_fmt, overlay_chroma_format, overlay_filter_graph
from utils import csv_fields
from avif_fit import (avif_encode_cmd, avif_pix_fmt, downscale_side,
                      strip_allintra)
import re as _re_eta
import math


# Регэксп кадра из stderr ffmpeg ("frame=  123 fps= 45 ...").
_RE_FFMPEG_FRAME = _re_eta.compile(r"frame=\s*(\d+)")

# Нормализация раскладки каналов перед libopus: кодер отвергает «боковые»/
# нестандартные раскладки (5.1(side) у AC3-дорожек) с "Invalid channel
# layout … (exit -22)". На stereo/mono — no-op, downmix не делается.
# Ставится последним фильтром КАЖДОГО кодирования в libopus (см. _af_arg).
OPUS_LAYOUT_FIX = "aformat=channel_layouts=mono|stereo|3.0|4.0|quad|5.0|5.1|6.1|7.1"

from si_hyx_parts.workers.real_eta_calculator import RealETACalculator
from si_hyx_parts.workers.info_worker import InfoWorker
from si_hyx_parts.workers.ytdlp_worker import YtdlpWorker

from si_hyx_parts.workers.process_worker import _build_atempo_chain, _ImgRunnable, ProcessWorker
