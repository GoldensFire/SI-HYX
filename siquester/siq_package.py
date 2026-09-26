"""The SiqPackage model: parse / edit / repack a .siq archive (incl. the robust _safe_replace save)."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from .qt import (
    _ctypes, _et_fromstring, _ET_IS_LXML, _logger, _shutil, _stat, _time, ET, os, re,
    shutil, tempfile, zipfile
)
from .constants import _AUDIO_EXTS, _HTML_EXTS, _IMG_EXTS, _VIDEO_EXTS
from .media import mp3_duration, mp4_duration
from .util import _make_tag_fn, _qs_price_map, _unquote
import siq_duration

from si_hyx_parts.siquester.siq_package.safe_replace import _safe_replace, SiqPackage

__all__ = [
    'SiqPackage',
    '_safe_replace',
]
