"""ResultPage — the per-package round/theme/question board."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from .qt import (
    _collections, _dt, _logger, _time, copy, ET, json, os, Path, QApplication,
    QByteArray, QCheckBox, QDrag, QEasingCurve, QFrame, QGraphicsOpacityEffect,
    QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMimeData, QPropertyAnimation,
    QPushButton, QSplitter, Qt, QTimer, QVBoxLayout, QWidget
)
from .constants import (
    _AlignC, _DH_SS_HIDDEN, _DH_SS_SHOWN, _Fixed, _MEDIA_EXTS, _ON_BTN_ANALYZE,
    _ON_BTN_COMPARE, _ON_BTN_DEL, _ON_BTN_SORT, _Pref, _SS_DARK_BASE, _SS_TRANSPARENT,
    _THEME_MIME
)
from .persistence import _notif_reset, _schedule_save
from .siq_package import SiqPackage
from .stats import stats_pct
from .util import _find_mw, _lbl, _q_idx, _screen_scale, fmt_dur
from .widgets_common import (
    _OutsideClickFilter, _QProgressWidget, AnimatedButton, GameProgressBar,
    msgbox_warning, SmoothScrollArea
)
from .widgets_editors import QuestionEditorDialog
from .widgets_question import QuestionViewer
from .widgets_tiles import _TileDropArea, PackageInfoDialog

from si_hyx_parts.siquester.result_page.result_page import ResultPage

__all__ = [
    'ResultPage',
]
