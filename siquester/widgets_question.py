"""QuestionViewer — the main question display/edit surface."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from PyQt6.QtGui import QDesktopServices

from .qt import (
    _logger, _shutil, _threading, ET, os, Path, pyqtSignal, QApplication, QByteArray,
    QDrag, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QMimeData, QPainter, QPixmap, QPushButton, QRect, QScrollArea, QSizePolicy, Qt,
    QTextEdit, QTextOption, QTimer, QUrl, QVBoxLayout, QWidget, zipfile
)
from .constants import (
    _AlignC, _AlignVC, _DEL_SS_HIDDEN, _DEL_SS_SHOWN, _DH_SS_HIDDEN, _DH_SS_SHOWN,
    _ITEM_JOIN_SS, _MEDIA_EXTS, _MIME_ANS, _MIME_BLOCK, _ON_BTN_ANALYZE,
    _ON_BTN_COMPARE, _ON_BTN_DEL, _ON_BTN_SORT, _ON_BTN_UPDATE, _Pref, _RB_ACTIVE,
    _RB_HOV, _RB_OFF, _SB_HOV, _SB_OFF, _SB_ON, _SS_BADGE_MUTED, _SS_TOPBAR_LABEL,
    _SS_TRANSPARENT, _TB_HOV, _TB_OFF, _TB_ON
)
from .media import _get_ui_bridge, _img_size_from_path, _load_qimage
from .persistence import _notif_reset
from .siq_package import _safe_replace, SiqPackage
from .util import (
    _find_mw, _lbl, _parse_hms, _q_idx, _screen_scale, _unquote, _xml_nav_q, fmt_dur
)
from .widgets_common import (
    _HoverFilter, _install_wheel_filter, AnimatedButton, msgbox_information,
    msgbox_warning
)
from .widgets_editors import _AnsEdit, _InlineTextEdit, PointOnImageWidget
from .widgets_players import AudioPlayerWidget, MpvVideoPlayerWidget

from si_hyx_parts.siquester.widgets_question.question_viewer import QuestionViewer

__all__ = [
    'QuestionViewer',
]
