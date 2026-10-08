# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# photo_tab.py — вкладка «Редактирование фото»: холст с кистью/фигурами/текстом,
# кадрирование, удаление объектов (LaMa) и удаление фона (RMBG-2.0), объединение
# фото. Выделено из tabs.py — тот разросся до ~6,7к строк и мешал в одном файле
# несвязанные фичи (загрузчик, обработка, Base64). Общие мелкие виджеты
# (_icon_btn, _JumpSlider) живут в widgets.py, чтобы tabs.py и photo_tab.py не
# зависели друг от друга.
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import os
import random
import time
from config import (
    Image, QByteArray, QCheckBox, QColor, QComboBox, QCursor, QEvent,
    QFileDialog, QFont, QFontMetrics, QFrame, QGroupBox, QHBoxLayout,
    QInputDialog, QKeySequence, QLabel, QPainter, QPen, QPixmap, QPoint,
    QPointF, QProgressBar, QPushButton, QRectF, QScrollArea, QShortcut,
    QSize, QSpinBox, QThread, QTimer, QToolButton, QVBoxLayout, QWidget,
    Qt, QtGuiImage, get_icon, pyqtSignal, qta, status_html
)
from utils import (open_image_any, play_done_sound)
from widgets import (
    PhotoDragList, _JumpSlider, _icon_btn, info_badge, msgbox_warning,
    show_image_fullscreen
)
from PyQt6.QtGui import (QPainterPath)
from PyQt6.QtWidgets import (
    QButtonGroup, QColorDialog, QFontComboBox, QScrollBar, QSizePolicy,
    QTabWidget
)

# ── Опциональные зависимости подвкладки «Удаление объектов» (LaMa/ONNX) ──────
# Нужны numpy + opencv; саму onnxruntime подтягивает lama_inpaint лениво (при
# первом запуске модели). Если чего-то нет — подвкладка покажет понятную
# заглушку, остальное приложение работает как обычно.
import importlib.util as _ilu
try:
    import numpy as _np
    import cv2 as _cv2
    from lama_inpaint import (LaMaInpainter, LaMaProcessInpainter,
                              load_bgr, save_bgr)
    _HAS_INPAINT = True
    _INPAINT_ERR = ""
    _HAS_ORT = _ilu.find_spec("onnxruntime") is not None
except Exception as _e:           # pragma: no cover
    _np = None; _cv2 = None
    LaMaInpainter = LaMaProcessInpainter = load_bgr = save_bgr = None
    _HAS_INPAINT = False
    _INPAINT_ERR = str(_e)
    _HAS_ORT = False

# Удаление фона (RMBG-2.0 / BiRefNet) — отдельная модель models/model_uint8.onnx.
# Доступно только если есть onnxruntime И файл модели на месте.
try:
    from rmbg_bg import RMBGProcessRemover, default_model_path as _rmbg_path
    _HAS_RMBG = _HAS_ORT and _np is not None and os.path.exists(_rmbg_path())
except Exception:                 # pragma: no cover
    RMBGProcessRemover = None
    _HAS_RMBG = False

from si_hyx_parts.photo_tab.image_convert import (
    np_bgr_to_qimage,
    qimage_to_np_bgr,
    np_bgra_to_qimage,
    _load_image_alpha,
)


_EYEDROPPER_CURSOR = None

from si_hyx_parts.photo_tab.eyedropper_cursor import eyedropper_cursor


_WASD_VK = {0x57: (0, 1), 0x53: (0, -1), 0x41: (1, 0), 0x44: (-1, 0)}
_ARROW_PAN = {Qt.Key.Key_Left: (1, 0), Qt.Key.Key_Right: (-1, 0),
              Qt.Key.Key_Up: (0, 1), Qt.Key.Key_Down: (0, -1)}
_WASD_KEY = {Qt.Key.Key_A: (1, 0), Qt.Key.Key_D: (-1, 0),
             Qt.Key.Key_W: (0, 1), Qt.Key.Key_S: (0, -1)}

from si_hyx_parts.photo_tab.pan_dir_from_event import _pan_dir_from_event

from si_hyx_parts.photo_tab.photo_merger_tab import PhotoMergerTab

from si_hyx_parts.photo_tab.inpaint_canvas import InpaintCanvas
from si_hyx_parts.photo_tab.workers import _WarmupWorker, InpaintWorker, BgRemoveWorker

from si_hyx_parts.photo_tab.inpaint_tab import InpaintTab
from si_hyx_parts.photo_tab.photo_tab import _PhotoModeSwitch, PhotoTab
