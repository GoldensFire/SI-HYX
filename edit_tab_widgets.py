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
    make_icon_btn, s_to_clock, s_to_time
)
from edit_tab_overlay import (MIN_SIZE_NORM)
from edit_tab_workers import (_SeekThumbnailer, overlay_top_left, track_box_at)
from PyQt6.QtCore import (QObject, QRect, QUrl)
from PyQt6.QtGui import (QBitmap, QBrush, QImage, QLinearGradient, QPainterPath,
                         QRegion, QTransform)
from PyQt6.QtMultimedia import QVideoFrame
from PyQt6.QtWidgets import (QSizePolicy, QStyle, QStyleOptionSlider, QToolTip)

from si_hyx_parts.edit_tab_widgets.waveform_widget import WaveformWidget

from si_hyx_parts.edit_tab_widgets.subtitle_timeline import _SubtitleTimeline, slider_value_at

from si_hyx_parts.edit_tab_widgets.player_widgets import (
    VolumeSlider,
    VolumeLabel,
    TimecodeLabel,
    InfoCard,
    AudioMeter,
    SubtitleOverlay,
)

from si_hyx_parts.edit_tab_widgets.painted_video_canvas import _PaintedVideoCanvas

from si_hyx_parts.edit_tab_widgets.project_timeline import ProjectTimeline


# ─── Холст видео на GPU: окно Qt Quick + QML VideoOutput ─────────────────────
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
# Сцена живёт в СОБСТВЕННОМ нативном окне (QQuickWindow), встроенном в холст
# через QWidget.createWindowContainer, и рисуется потоком рендера Qt Quick.
# Раньше она была QQuickWidget, и это стоило дорого: QQuickWidget рендерит в
# GUI-потоке и переводит ВСЁ верхнее окно на RHI-композицию — после этого
# любая перерисовка любого виджета вкладки (метка времени, плейхед, шкала)
# ждала GPU. Пока GPU свободен, это почти незаметно, но стоит его занять
# чему-то ещё (игра, другой редактор) — и GUI-поток простаивает. Замер
# опозданием 5-мс таймера в настоящей вкладке, 1080p24, GPU занят игрой на
# 99%: GUI-поток занят на 85–89%, и даже без кадров, плейхеда и шкалы уровня —
# на 54% (тот же экран без QQuickWidget — 0%). Теперь верхнее окно остаётся
# растровым, а кадр GUI-поток лишь передаёт сцене, когда поток рендера свободен
# (см. VideoCanvas._present_frame). Под синтетической нагрузкой GPU 96%:
# QQuickWidget — 64–81%, своё окно сцены — 17–28% (медиана ~19%); при свободном
# GPU — около 5% у обоих. Подача кадров по флагу «ждём frameSwapped» под
# нагрузкой то и дело сбивалась в фазу, где каждый кадр ждал рендера
# предыдущего (прогоны то 1–3%, то 30–50%); счёт синхронизаций, ожидание GPU в
# Present вместо beginFrame (QT_D3D_MAX_FRAME_LATENCY=0, edit_tab_base) и отказ
# от копий аппаратных кадров дают 1–7% (12 с от старта воспроизведения,
# синтетика ~100% GPU; прежняя подача в тех же условиях — 46–67%).
#
# Ввод. Окну сцены выставлен WindowTransparentForInput: мышь, колесо и бросок
# файла плагин Qt для Windows отдаёт его родителю — верхнему окну, где их, как
# и прежде, разбирает сам холст (кадрирование, накладки, зум, панорама,
# двойной клик). Кнопки «Применить/Отмена» кадрирования — нативные окна:
# обычный дочерний виджет нативная сцена перекрыла бы.
#
# Оверлеи (субтитры, рамка кропа, накладки, трек-превью) рисует тот же
# QPainter-код, что и раньше (_paint_overlays), в QImage в GUI-потоке, а сцена
# показывает эту картинку слоем Image поверх кадра (через провайдер картинок).
# Рисовать их в QQuickPaintedItem, как раньше, больше нельзя: его paint()
# вызывается в потоке рендера, пока GUI-поток ждёт синхронизацию, — Python-код
# там требует GIL, а GUI-поток держит его внутри show()/setGeometry(), и
# программа намертво встаёт.
#
# Почему не QVideoWidget и не QGraphicsVideoItem: первый не пускает поверх себя
# ни виджет-оверлей, ни что-либо ещё (проверено на экране), второй в этом
# бэкенде идёт через ЦП и стоит дороже текущего пути (79% ЦП).
try:
    from PyQt6.QtQml import QQmlComponent, QQmlEngine
    from PyQt6.QtQuick import QQuickImageProvider, QQuickWindow
    _QUICK_AVAILABLE = True
except Exception:                      # Qt Quick не собран/не установлен
    QQmlComponent = QQmlEngine = QQuickWindow = None
    QQuickImageProvider = object
    _QUICK_AVAILABLE = False


_QML_CANVAS_SOURCE = """import QtQuick
import QtMultimedia

Window {
    color: "__BG__"
    property alias sink: vo.videoSink

    // При зуме кадр намеренно вылезает за границы холста — режем по ним.
    Item {
        anchors.fill: parent
        clip: true

        // Геометрию задаёт Python (VideoCanvas.video_rect): letterbox, зум и
        // панорама считаются там же, где координаты оверлеев, — иначе кадр и
        // рамка кадрирования разъезжаются.
        VideoOutput {
            id: vo
            objectName: "videoOutput"
            fillMode: VideoOutput.PreserveAspectFit
        }

        // Оверлеи — готовая картинка из GUI-потока (VideoCanvas._refresh_overlay),
        // ровно в размер холста. Пока рисовать нечего, слой скрыт и не стоит GPU
        // ничего.
        Image {
            objectName: "overlay"
            anchors.fill: parent
            visible: false
            cache: false
            asynchronous: false
            smooth: false
            fillMode: Image.Stretch
        }
    }
}
"""

from si_hyx_parts.edit_tab_widgets.canvas_scene import (
    _OVERLAY_PROVIDER, _CanvasOverlayProvider, _create_canvas_window,
    _make_native_alone, _round_mask)

from si_hyx_parts.edit_tab_widgets.video_canvas import VideoCanvas

from si_hyx_parts.edit_tab_widgets.seek_slider import SeekSlider, SeekPreview

from si_hyx_parts.edit_tab_widgets.fullscreen_video import FullscreenVideo

from si_hyx_parts.edit_tab_widgets.styled_subtitle_overlay import (
    _StyledSubtitleOverlay,
    _TrackSelectCanvas,
)

from si_hyx_parts.edit_tab_widgets.subtitle_preview import _SubtitlePreview
