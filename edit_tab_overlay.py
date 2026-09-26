# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_overlay.py — наложение НЕПОДВИЖНОЙ картинки (логотип, водяной знак,
# рамка) поверх видео во вкладке «Монтаж».
#
# Слой стоит между edit_tab_base и edit_tab_widgets: холст (VideoCanvas) рисует
# и правит накладки, EditTab собирает по ним ffmpeg-фильтр экспорта, а список
# слоёв (OverlayLayersPanel) даёт удалить/кадрировать/подкрутить прозрачность.
#
# Одна накладка = ImageOverlay: исходная картинка + рамка кадрирования (в долях
# самой картинки) + прямоугольник на кадре (в долях КАДРА) + прозрачность и
# поворот. Доли, а не пиксели, потому что в плеере может идти прокси меньшего
# разрешения (см. ProxyWorker), а в файл пишется полный кадр — одни и те же
# доли одинаково ложатся и туда, и туда.
#
# ВАЖНО про порядок фильтров: накладка подмешивается ДО кадрирования видео
# (crop=…) и до вшивания субтитров — ровно как её видно в плеере, где рамка
# кадрирования лежит поверх кадра с картинкой. Значит, кадрирование может
# «отрезать» часть накладки — это и есть WYSIWYG, а не ошибка.

# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import os

from config import (
    QColor, QDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPainter, QPen, QPointF, QRectF, QSize, QSlider, QVBoxLayout,
    QWidget, Qt, get_icon, pyqtSignal
)
from edit_tab_base import C, make_icon_btn
from PyQt6.QtGui import QIcon, QImage, QPixmap, QTransform
from PyQt6.QtWidgets import QDialogButtonBox, QPushButton, QSizePolicy
# Сам ffmpeg-граф накладок живёт в utils: его собирает не только Монтаж, но и
# ProcessWorker (режим обрезки «Перекодировать настройками «Обработки»»), а тому
# нельзя тянуть за собой edit_tab_base — тот выставляет env Qt-бэкендов и обязан
# импортироваться ДО создания QApplication.
from utils import (  # noqa: F401  (re-export: исторический адрес функции)
    overlay_chroma_format, overlay_filter_graph
)

# Минимальный размер накладки на кадре (доля кадра) — иначе её не поймать мышью.
MIN_SIZE_NORM = 0.02
# Ручки рамки (в пикселях экрана).
HANDLE_PX = 8

from si_hyx_parts.edit_tab_overlay.load_overlay_image import (
    load_overlay_image,
    qimage_to_bgra,
    fit_rect_norm,
    ImageOverlay,
    render_overlays,
)

from si_hyx_parts.edit_tab_overlay.crop_canvas import _CropCanvas, OverlayCropDialog

from si_hyx_parts.edit_tab_overlay.overlay_layers_panel import OverlayLayersPanel
