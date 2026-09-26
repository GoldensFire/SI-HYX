"""Top-level pages (EmptyPage) and the MainWindow."""
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]


from .qt import (
    _dt, _logger, _threading, os, pyqtSignal, QApplication, QCheckBox, QComboBox,
    QEasingCurve, QEvent, QFileDialog, QFrame, QHBoxLayout, QImageReader, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPixmap, QPropertyAnimation,
    QPushButton, QScrollArea, QStackedWidget, Qt, QTextEdit, QTimer, QVBoxLayout,
    QWidget, sys
)
from .constants import (
    _AlignC, _Expand, _ON_BTN_DEL, _Pref, _SS_DROP_ZONE_LG, _SS_INPUT_LARGE,
    _SS_LABEL_DIM, _SS_PANEL_BRD2, _SS_TOPBAR, _WASD_MAP
)
from .media import _get_ui_bridge
from .persistence import load_datasets, load_settings, save_datasets, save_settings
from .result_page import ResultPage
from .sidebar import Sidebar
from .siq_package import SiqPackage
from .util import _find_mw, _lbl, _unquote, fmt_dur
from .widgets_common import AnimatedButton, msgbox_warning
from . import auto_stats

from si_hyx_parts.siquester.main_window.empty_page import EmptyPage, MainWindow

__all__ = [
    'EmptyPage',
    'MainWindow',
]
