# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: распространяется/изменяется на условиях GNU General Public
# License v3 (или новее) от Free Software Foundation. БЕЗ ВСЯКИХ ГАРАНТИЙ.
# Полный текст — в файле LICENSE (https://www.gnu.org/licenses/gpl-3.0.txt).
# widgets.py — кастомные виджеты, делегаты, превью, info-подсказки
# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import hashlib
import io
import os
import re
import subprocess
import uuid
from pathlib import Path
from config import (
    ALLOWED_AUDIO, ALLOWED_IMG, ALLOWED_MEDIA, COLOR_DONE, COLOR_ERR,
    COLOR_PROC, CONFIG_DIR, CREATE_NO_WINDOW, DEFAULT_TAG, FFMPEG, FFPROBE,
    ITEM_AUDIO_ROLE, ITEM_COMPARE_ROLE, ITEM_STATUS_ROLE, Image, ImageOps,
    QAbstractItemView, QAbstractSpinBox, QApplication, QBrush, QByteArray,
    QColor, QComboBox, QDialog, QEvent, QFileDialog, QFont, QFrame,
    QHBoxLayout, QHeaderView, QIcon, QInputDialog, QKeySequence,
    QKeySequenceEdit, QLabel, QMenu, QObject, QPainter, QPen, QPixmap,
    QPoint, QPointF, QPushButton, QRect, QRectF, QRunnable, QScrollArea,
    QSize, QSlider, QSpinBox, QStyle, QStyledItemDelegate, QThread,
    QThreadPool, QTimer, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget, Qt, RIBBON_IMG, TEMP_DIR, USER_AGENT, get_icon,
    get_icon_pixmap, http_get, icon_html, pyqtSignal
)
from utils import (
    csv_first, default_download_dir, human_size, load_pixmap_any, load_settings,
    move_to_trash, pil_to_qicon, rasterize_svg, save_settings
)
from msgbox import msgbox_warning
from PyQt6.QtWidgets import (QAbstractScrollArea, QSizePolicy, QAbstractButton,
                             QLineEdit, QScrollBar, QStyleOptionSlider)
from PyQt6.QtCore import QUrl

from si_hyx_parts.widgets.status_color_delegate import (
    StatusColorDelegate,
    PreviewNameDelegate,
    LatinKeySequenceEdit,
    InvertedWheelComboBox,
    ZeroSpinBox,
    SpeedSpinBox,
)

from si_hyx_parts.widgets.info_tip_popup import (
    _InfoTipPopup,
    _enable_clear_button,
    HoverTipManager,
    install_hover_tips,
)

from si_hyx_parts.widgets.info_badge import (
    _InfoBadge,
    info_badge,
    WheelBlocker,
    combo_set_value,
    label_with_info,
    row_with_info,
    LocalThumbnailRunnable,
    RemoteThumbnailRunnable,
)


# ── Кэш миниатюр ленты «последние файлы» ─────────────────────────────────────
# Лента показывает до 30 карточек, и на КАЖДУЮ раньше запускалось два процесса
# (ffmpeg за кадром + ffprobe за длительностью) — до 60 запусков 215-мегабайтных
# бинарников при каждом старте программы. На SSD это фон, на жёстком диске —
# главная причина, по которой окно долго «оживает»: десяток параллельных ffmpeg
# рвёт головку между своими образами, исходными видео и Qt-библиотеками, которые
# в это же время грузит главный поток.
#
# Со второго запуска этих процессов нет вовсе. Ключ записи включает mtime и
# размер файла: изменённый (или подменённый другим) файл получает новый ключ и
# пересчитывается, устаревшую картинку показать невозможно. Одна запись — один
# файл: первая строка «длительность\n», дальше байты картинки. Любая ошибка
# кэша означает лишь «считаем как раньше», поэтому здесь всё под try/except.
_THUMB_CACHE_DIR = os.path.join(CONFIG_DIR, "thumb_cache")
_THUMB_CACHE_LIMIT = 600       # записей; лишние (самые старые) удаляются
_thumb_cache_trimmed = False   # уборку делаем один раз за запуск

from si_hyx_parts.widgets.thumb_cache_key import (
    _thumb_cache_key,
    _thumb_cache_read,
    _thumb_cache_write,
    _thumb_cache_trim,
)


_FFMPEG_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d\d):(\d\d(?:\.\d+)?)")

from si_hyx_parts.widgets.duration_from_ffmpeg_log import (
    _duration_from_ffmpeg_log,
    _fmt_duration,
    _RecentThumbWorker,
)

from si_hyx_parts.widgets.recent_file_thumb import RecentFileThumb

from si_hyx_parts.widgets.recent_files_strip import RecentFilesStrip

from si_hyx_parts.widgets.draggable_tree_widget import DraggableTreeWidget, PhotoDragList

from si_hyx_parts.widgets.paint_checkerboard import (
    _paint_checkerboard,
    _ZoomImageLabel,
    ImageFullscreenViewer,
    _CompareView,
)

from si_hyx_parts.widgets.image_compare_viewer import (
    ImageCompareViewer,
    _add_close_hint,
    _present_fullscreen,
    show_image_fullscreen,
    show_image_compare,
)


# Мультимедиа PyQt6 может отсутствовать в урезанных сборках — деградируем мягко,
# как это уже сделано в edit_tab.py (видеоредактор). QGraphicsVideoItem (а не
# QVideoWidget) — принципиально: QVideoWidget рендерит через нативную
# оверлей-поверхность, которая на Windows всегда рисуется ПОВЕРХ обычных
# Qt-виджетов независимо от raise()/stacking — из-за этого плавающая кнопка
# закрытия оказывалась перекрыта видео. QGraphicsVideoItem рисуется внутри
# QGraphicsView как обычный виджет (без этой проблемы) и вдобавок легко
# зумится/панорамируется через трансформацию вида.
try:
    from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
    from PyQt6.QtMultimediaWidgets import QGraphicsVideoItem
    from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene
    from PyQt6.QtCore import QSizeF
    _HAS_MULTIMEDIA_CMP = True
except Exception:
    _HAS_MULTIMEDIA_CMP = False

from si_hyx_parts.widgets.probe_video_codec import _probe_video_codec


# Живые прокси-воркеры держим здесь, а не только в self._proxy_workers диалога:
# если диалог сравнения закрыт до готовности прокси, поток должен спокойно
# доработать (ffmpeg нельзя безопасно прервать) без риска, что Qt попытается
# уничтожить ещё бегущий QThread вместе с закрытым (WA_DeleteOnClose) диалогом.
_ACTIVE_COMPARE_PROXIES = set()

from si_hyx_parts.widgets.compare_proxy_worker import _CompareProxyWorker, _ZoomVideoView

from si_hyx_parts.widgets.video_compare_viewer import VideoCompareViewer

from si_hyx_parts.widgets.show_video_compare import (
    show_video_compare,
    TabScrollArrows,
    install_tab_scroll_arrows,
    _icon_btn,
    _JumpSlider,
)
