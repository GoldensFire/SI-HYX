"""Inline text editors, the point-on-image widget and the question/compare dialogs."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from .qt import (
    _logger, ET, os, Path, pyqtSignal, QBrush, QCheckBox, QColor, QComboBox, QDialog,
    QFileDialog, QGroupBox, QHBoxLayout, QImage, QImageReader, QInputDialog, QLabel,
    QLineEdit, QMenu, QPainter, QPixmap, QPushButton, QScrollArea, QSize,
    QStackedWidget, Qt, QTextEdit, QTextOption, QVBoxLayout, QWidget
)
from .constants import (
    _AlignC, _C_BG2, _C_RED, _C_TEXT4, _Expand, _MEDIA_EXTS, _ON_BTN_ANALYZE,
    _ON_BTN_COMPARE, _ON_BTN_DEL, _Pref, _SS_TRANSPARENT
)
from .util import _lbl, _q_idx, _style_cb
from .widgets_common import AnimatedButton, msgbox_information, msgbox_warning

from typing import TYPE_CHECKING
if TYPE_CHECKING:  # только для аннотаций — на рантайме не импортируется
    from .siq_package import SiqPackage

from si_hyx_parts.siquester.widgets_editors.editor_context_menu import (
    _editor_context_menu,
    _InlineTextEdit,
    _AnsEdit,
)

from si_hyx_parts.siquester.widgets_editors.point_on_image_widget import (
    PointOnImageWidget,
    _PointCanvas,
)

from si_hyx_parts.siquester.widgets_editors.question_editor_dialog import QuestionEditorDialog

__all__ = [
    'PointOnImageWidget',
    'QuestionEditorDialog',
    '_AnsEdit',
    '_InlineTextEdit',
    '_PointCanvas',
    '_editor_context_menu',
]
