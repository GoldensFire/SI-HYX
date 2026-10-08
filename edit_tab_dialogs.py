# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_dialogs.py — диалоги вкладки «Монтаж»: маска для удаления объектов с
# видео, редактор и конструктор субтитров, пикселизация-проявление.
# Верхний слой: использует базу, воркеры и виджеты.

# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import copy
import os
from functools import partial
from config import (
    QCheckBox, QColor, QComboBox, QDialog, QFileDialog, QFont, QHBoxLayout,
    QKeySequence, QLabel, QLineEdit, QPushButton, QSlider, QSpinBox,
    QVBoxLayout, QWidget, Qt, get_icon
)
from msgbox import (msgbox_information, msgbox_warning)
from edit_tab_base import (
    C, DEFAULT_SUBTITLE_STYLE, _load_subtitle_presets,
    _pixelize_block_sequence, _save_subtitle_presets, make_divider,
    make_icon_btn, s_to_time
)
from edit_tab_widgets import (_SubtitlePreview, _SubtitleTimeline)
from PyQt6.QtGui import (QShortcut)
from PyQt6.QtWidgets import (
    QButtonGroup, QColorDialog, QDialogButtonBox, QFontComboBox, QGridLayout,
    QInputDialog, QListWidget, QListWidgetItem, QPlainTextEdit, QRadioButton,
    QScrollBar, QTabWidget, QToolButton
)

from si_hyx_parts.edit_tab_dialogs.video_mask_dialog import _VideoMaskDialog

from si_hyx_parts.edit_tab_dialogs.track_attach_dialog import _TrackAttachDialog

from si_hyx_parts.edit_tab_dialogs.subtitle_edit_dialog import SubtitleEditDialog
from si_hyx_parts.edit_tab_dialogs.subtitle_creator_dialog import SubtitleCreatorDialog
from si_hyx_parts.edit_tab_dialogs.pixelize_dialog import _PixelizeDialog
