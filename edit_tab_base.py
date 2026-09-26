# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab_base.py — база вкладки «Монтаж»: импорты, палитра, константы и
# чистые хелперы (ffprobe, время, субтитры/ASS, пикселизация).
#
# Выделено из edit_tab.py (исторически ~12,5к строк одним файлом) в 5 слоёв:
#   edit_tab_base → edit_tab_workers → edit_tab_widgets → edit_tab_dialogs → edit_tab
# Зависимости строго в одну сторону (проверено: обратных рёбер нет).
#
# ВАЖНО: этот модуль выставляет env-переменные Qt-бэкенда (QSG_RHI_BACKEND /
# QT_MEDIA_BACKEND) и определяет _HAS_MULTIMEDIA / LIBASS_AVAILABLE ДО создания
# QApplication — потому и стоит первым в цепочке импортов вкладки.
#
# Адаптировано из standalone-редактора Edit.py (JashaLava) под вкладку SI-HYX.

# Resolve deferred class annotations through the public namespace.
import sys as _sys
_api = _sys.modules[__name__]

import os
import json
import math
import subprocess

# Бэкенды Qt нужно выбрать ДО создания QMediaPlayer/QVideoWidget. Модуль
# импортируется в main.py до создания QApplication, поэтому setdefault ниже
# срабатывает вовремя и не перетирает значения, заданные пользователем извне.

# Графический бэкенд сцены Qt Quick (на нём работает холст видео «Монтажа» —
# см. VideoCanvas). Программный рендер отключён всегда (настройка убрана из UI),
# а из двух аппаратных на Windows берём РОДНОЙ D3D11: замер того же холста на
# одном файле (tools/bench_video_path.py, режим montage, 1080p60, окно
# 1100x640) — d3d11 ЦП 19.7%, GUI-поток 5.3%; opengl ЦП 50.5%, GUI-поток 12.9%.
# Здесь opengl остался с тех пор, когда единственной альтернативой был
# "software" (обходной путь для оверлея RivaTuner), и осознанным выбором против
# d3d11 никогда не был. setdefault сохраняет приоритет за переменной окружения:
# QSG_RHI_BACKEND=opengl снаружи по-прежнему всё переключает обратно.
os.environ.setdefault("QSG_RHI_BACKEND", "d3d11" if os.name == "nt" else "opengl")
# QT_FFMPEG_DECODING_HW_DEVICE_TYPES (HW-декодер H.264/HEVC) задаёт config.py,
# импортируемый выше, — он читает настройку video_hw_decode.
os.environ.setdefault("QT_MEDIA_BACKEND", "ffmpeg")

from PyQt6.QtCore import (Qt, QRect, QSize)
from PyQt6.QtWidgets import (QApplication, QPushButton, QFrame)
from PyQt6.QtGui import (QPainter, QColor, QPen, QFont, QPixmap, QIcon)

# Нативный рендер ASS/SSA для превью (libass). Если DLL нет/не загрузились —
# LIBASS_AVAILABLE=False, и субтитры показываются обычным текстовым оверлеем.
try:
    import libass_renderer as _libass
    LIBASS_AVAILABLE = bool(_libass.AVAILABLE)
except Exception:
    _libass = None
    LIBASS_AVAILABLE = False

# Мультимедиа PyQt6 поставляется вместе с основным wheel'ом, но на некоторых
# урезанных сборках его может не быть — деградируем мягко (заглушка во вкладке).
try:
    from PyQt6.QtMultimedia import (QAudioFormat, QAudioSink, QMediaPlayer,
                                    QAudioOutput, QVideoSink, QMediaDevices)
    from PyQt6.QtMultimediaWidgets import QVideoWidget
    _HAS_MULTIMEDIA = True
except Exception:
    # Имена обязаны СУЩЕСТВОВАТЬ даже без мультимедиа: верхние слои
    # (edit_tab_widgets / edit_tab.py) импортируют их отсюда на уровне модуля, и
    # без заглушек такой импорт падал бы ImportError — вкладка «Монтаж» роняла бы
    # всё приложение вместо мягкой деградации. Пока всё жило одним файлом, этой
    # проблемы не было (неопределённые имена просто не трогались под гардом
    # _HAS_MULTIMEDIA). Использовать их можно ТОЛЬКО при _HAS_MULTIMEDIA=True.
    QMediaPlayer = QAudioOutput = QVideoSink = QVideoWidget = None
    QMediaDevices = QAudioFormat = QAudioSink = None
    _HAS_MULTIMEDIA = False

# Пути к ffmpeg/ffprobe и флаг скрытия консоли берём из общей конфигурации SI-HYX,
# чтобы редактор работал и в собранном .exe с bundled-ffmpeg.
from config import (FFPROBE, CREATE_NO_WINDOW, CONFIG_DIR, get_icon)

EDITOR_SETTINGS_PATH = os.path.join(CONFIG_DIR, "editor_settings.json")


# ─── Color Palette ───────────────────────────────────────────────────────────
# Палитра вкладки приведена к общему стилю приложения (Catppuccin Mocha,
# см. STYLESHEET в config.py), чтобы «Монтаж» не выбивался из остальных вкладок.
C = {
    "bg":        "#1e1e2e",   # base
    "surface":   "#181825",   # mantle
    "surface2":  "#24273a",   # surface0-ish (панели)
    "surface3":  "#313244",   # surface0 (поля/кнопки)
    "border":    "#45475a",   # surface1
    "border2":   "#585b70",   # surface2
    "accent":    "#89b4fa",   # blue
    "accent2":   "#b4befe",   # lavender (hover)
    "green":     "#a6e3a1",   # green
    "green2":    "#94e2d5",   # teal
    "red":       "#f38ba8",   # red
    "red2":      "#eba0ac",   # maroon
    "yellow":    "#f9e2af",   # yellow
    "text":      "#cdd6f4",   # text
    "text2":     "#a6adc8",   # subtext0
    "text3":     "#6c7086",   # overlay0
    "playhead":  "#f9e2af",   # yellow
    "wave_bg":   "#45475a",
    "wave_sel":  "#89b4fa",
}

from si_hyx_parts.edit_tab_base.run_ffprobe import (
    run_ffprobe,
    time_to_s,
    s_to_time,
    format_fps,
    _fmt_channels,
    install_audio_device_recovery,
    _unique_output,
    make_divider,
    make_icon_btn,
    _fullscreen_icon,
    _parse_srt,
    _paint_subtitle,
)

from si_hyx_parts.edit_tab_base.paint_subtitle_styled import (
    _paint_subtitle_styled,
    _ass_timestamp,
    _hex_to_ass_color,
)


# Стиль субтитров по умолчанию (используется, пока у реплики нет собственного
# переопределения — см. SubtitleCreatorDialog._effective_style).
DEFAULT_SUBTITLE_STYLE = {
    'font': 'Arial', 'size': 20, 'bold': True, 'italic': False, 'underline': False,
    'align': 2, 'spacing': 0, 'color': '#FFFFFF', 'outline_color': '#000000',
    'animation': 'none',
}
_ASS_PLAYRES_X, _ASS_PLAYRES_Y = 384, 288
_ASS_MARGIN_L, _ASS_MARGIN_R, _ASS_MARGIN_V = 10, 10, 20

from si_hyx_parts.edit_tab_base.animation_override_tags import (
    _animation_override_tags,
    _style_line,
)


_ASS_TEMPLATE = (
    "[Script Info]\n"
    "ScriptType: v4.00+\n"
    f"PlayResX: {_ASS_PLAYRES_X}\n"
    f"PlayResY: {_ASS_PLAYRES_Y}\n"
    "WrapStyle: 0\n"
    "ScaledBorderAndShadow: yes\n\n"
    "[V4+ Styles]\n"
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
    "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, "
    "ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
    "MarginL, MarginR, MarginV, Encoding\n"
    "{styles}\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "{events}\n"
)

from si_hyx_parts.edit_tab_base.cues_to_ass import _cues_to_ass


_SUBTITLE_PRESETS_PATH = os.path.join(CONFIG_DIR, "subtitle_presets.json")

from si_hyx_parts.edit_tab_base.load_subtitle_presets import (
    _load_subtitle_presets,
    _save_subtitle_presets,
)


# Пикселизация («проявление из пикселей») живёт в общем модуле pixelize.py:
# тем же эффектом с теми же блоками пользуется генератор аниме-паков (вопрос-
# кадр, который проявляется). Здесь — только привычные имена, чтобы вкладка
# «Монтаж» и её диалоги импортировали их как раньше.
from pixelize import (block_sequence as _pixelize_block_sequence,
                      pixelize_filter as _pixelize_filter)
