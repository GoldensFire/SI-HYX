# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_widgets.py — виджеты вкладки «Монтаж»: звуковая волна, таймлайн
# субтитров, холст видео, полноэкранный режим, превью перемотки, индикаторы.
# Слой поверх edit_tab_base / edit_tab_workers.

# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import math
import os
import tempfile
import time
from functools import partial
from config import (
    QApplication, QColor, QEvent, QFont, QFontMetrics, QFrame,
    QHBoxLayout, QLabel, QPainter, QPen, QPixmap, QPoint, QPointF,
    QPushButton, QRectF, QSize, QSlider, QTimer, QVBoxLayout, QWidget, Qt,
    get_icon, get_icon_pixmap, pyqtSignal
)
from edit_tab_base import (
    C, QAudioOutput, QMediaPlayer, QVideoSink, _fullscreen_icon,
    _paint_subtitle, _paint_subtitle_styled, install_audio_device_recovery,
    make_icon_btn, s_to_time
)
from edit_tab_overlay import (MIN_SIZE_NORM)
from edit_tab_workers import (_SeekThumbnailer, overlay_top_left, track_box_at)
from PyQt6.QtCore import (QObject, QRect, QUrl)
from PyQt6.QtGui import (QBrush, QImage, QLinearGradient, QPainterPath,
                         QTransform)
from PyQt6.QtMultimedia import QVideoFrame
from PyQt6.QtWidgets import (QSizePolicy, QStyle, QStyleOptionSlider, QToolTip)

from si_hyx_parts.edit_tab_widgets.waveform_widget import WaveformWidget

from si_hyx_parts.edit_tab_widgets.subtitle_timeline import _SubtitleTimeline, slider_value_at

from si_hyx_parts.edit_tab_widgets.player_widgets import (
    VolumeSlider,
    VolumeLabel,
    InfoCard,
    AudioMeter,
    SubtitleOverlay,
)

from si_hyx_parts.edit_tab_widgets.painted_video_canvas import _PaintedVideoCanvas


# ─── Холст видео на GPU: QQuickWidget + QML VideoOutput ──────────────────────
#
# Зачем. ЦП-холст (_PaintedVideoCanvas) на каждый кадр делал frame.toImage()
# (NV12 → RGBA) и drawImage со скейлом — всё в ГЛАВНОМ потоке. На 1080p60 это
# 8-9 мс при бюджете кадра 16.7 мс: главный поток занят третью своего времени и
# не успевает ни мышь обработать, ни плейхед подвинуть — это и есть «Монтаж
# лагает». Замер tools/bench_video_path.py (1080p60 H.264, окно 1100x640):
#   canvas (ЦП-путь)  ЦП 54.7%  GUI-поток 29.3%  toImage 8.2 мс  нарисовано 57.2/60
#   qml    (GPU-путь) ЦП 11.5%  GUI-поток  1.2%  кадр через ЦП не идёт вовсе
#
# Как устроено. Кадр от плеера НЕ конвертируется: QML VideoOutput получает
# QVideoFrame как есть. Но между плеером и сценой стоит наш QVideoSink (его и
# отдаёт videoSink()) — без него не выжили бы пин кадра, граница OUT и часы
# кадра: они решают ПО PTS, показывать кадр или нет, и решение обязано быть
# принято ДО показа. Проброс через Python-слот стоит около 4 п.п. ЦП (замер:
# 15.9% против 11.5% у голого QML) и почти ничего — главному потоку.
#
# Оверлеи (субтитры, рамка кропа, накладки, трек-превью) рисует тот же
# QPainter-код, что и раньше (_paint_overlays), но внутри QQuickPaintedItem в
# той же сцене — поэтому они ложатся ПОВЕРХ кадра с правильной альфой (у
# QVideoWidget так не выходит: видео композитится последним). Quick держит их в
# текстуре, так что paint() зовётся не на каждый кадр, а только когда оверлей
# реально изменился.
#
# Почему не QVideoWidget и не QGraphicsVideoItem: первый не пускает поверх себя
# ни виджет-оверлей, ни что-либо ещё (проверено на экране), второй в этом
# бэкенде идёт через ЦП и стоит дороже текущего пути (79% ЦП).
try:
    from PyQt6.QtQuick import QQuickPaintedItem
    from PyQt6.QtQuickWidgets import QQuickWidget
    _QUICK_AVAILABLE = True
except Exception:                      # Qt Quick не собран/не установлен
    QQuickPaintedItem = object
    QQuickWidget = None
    _QUICK_AVAILABLE = False


_QML_CANVAS_SOURCE = """import QtQuick
import QtMultimedia

Item {
    id: root
    // При зуме кадр намеренно вылезает за границы виджета — режем по ним.
    clip: true
    property alias sink: vo.videoSink

    Rectangle { anchors.fill: parent; color: "__BG__" }

    // Геометрию задаёт Python (VideoCanvas.video_rect): letterbox, зум и
    // панорама считаются там же, где координаты оверлеев, — иначе кадр и
    // рамка кадрирования разъезжаются.
    VideoOutput {
        id: vo
        objectName: "videoOutput"
        fillMode: VideoOutput.PreserveAspectFit
    }
}
"""

from si_hyx_parts.edit_tab_widgets.canvas_qml_path import _canvas_qml_path, _CanvasOverlayItem

from si_hyx_parts.edit_tab_widgets.video_canvas import VideoCanvas

from si_hyx_parts.edit_tab_widgets.seek_slider import SeekSlider, SeekPreview

from si_hyx_parts.edit_tab_widgets.fullscreen_video import FullscreenVideo

from si_hyx_parts.edit_tab_widgets.styled_subtitle_overlay import (
    _StyledSubtitleOverlay,
    _TrackSelectCanvas,
)

from si_hyx_parts.edit_tab_widgets.subtitle_preview import _SubtitlePreview
