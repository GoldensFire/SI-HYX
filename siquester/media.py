"""Pure-python media probing (durations, bitrates, waveform, LUFS), image cache and the UI thread bridge."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from .qt import (
    _logger, _subprocess, json, math, os, pyqtSignal, QImage, QImageReader, QObject,
    QPixmap, Qt, random, struct
)

_MP4_PROBE_SIZE = 1 << 15   # 32 KB — enough for moov header at start of well-formed MP4

from si_hyx_parts.siquester.media.find_mvhd import _find_mvhd, mp4_duration, _mp4_scan_bytes


_MP3_BR_V1 = [0,32,40,48,56,64,80,96,112,128,160,192,224,256,320,0]  # MPEG1 L3 kbps


_MP3_BR_V2 = [0, 8,16,24,32,40,48,56, 64, 80, 96,112,128,144,160,0]  # MPEG2/2.5 L3 kbps


_MP3_PROBE_SIZE = 4096   # sync word is always within the first 4 KB

from si_hyx_parts.siquester.media.mp3_duration import mp3_duration, _extract_waveform_bars


_WAVEFORM_CACHE: dict = {}


_WAVEFORM_CACHE_MAX = 64   # max cached waveforms (~64 unique audio files)

from si_hyx_parts.siquester.media.extract_waveform_bars_compute import (
    _extract_waveform_bars_compute,
    _measure_lufs,
    _mp4_video_size,
    _mp3_bitrate_kbps,
    _m4a_audio_bitrate_kbps,
)

from si_hyx_parts.siquester.media.get_media_info import _get_media_info, _ThreadBridge


_UI_BRIDGE: "_ThreadBridge | None" = None

from si_hyx_parts.siquester.media.get_ui_bridge import _get_ui_bridge


_IMAGE_CACHE: dict[tuple, "QImage"] = {}   # (path, width) → scaled QImage


_IMAGE_CACHE_MAX = 64


try:
    from pillow_heif import register_heif_opener as _reg_heif
    _reg_heif()
    _HEIF_AVAILABLE = True
except ImportError:
    _HEIF_AVAILABLE = False

from si_hyx_parts.siquester.media.load_qimage import _load_qimage, _img_size_from_path

__all__ = [
    '_HEIF_AVAILABLE',
    '_IMAGE_CACHE',
    '_IMAGE_CACHE_MAX',
    '_MP3_BR_V1',
    '_MP3_BR_V2',
    '_MP3_PROBE_SIZE',
    '_MP4_PROBE_SIZE',
    '_ThreadBridge',
    '_UI_BRIDGE',
    '_WAVEFORM_CACHE',
    '_WAVEFORM_CACHE_MAX',
    '_extract_waveform_bars',
    '_extract_waveform_bars_compute',
    '_find_mvhd',
    '_get_media_info',
    '_get_ui_bridge',
    '_img_size_from_path',
    '_load_qimage',
    '_m4a_audio_bitrate_kbps',
    '_measure_lufs',
    '_mp3_bitrate_kbps',
    '_mp4_scan_bytes',
    '_mp4_video_size',
    '_reg_heif',
    'mp3_duration',
    'mp4_duration',
]
