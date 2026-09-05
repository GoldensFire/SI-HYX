# -*- coding: utf-8 -*-
#
# SI-HYX — медиа-загрузчик и перекодировщик.
# Copyright (C) 2026 GoldensFire
#
# Свободное ПО: GNU GPL v3 (или новее). БЕЗ ВСЯКИХ ГАРАНТИЙ. См. LICENSE.
# edit_tab.py — вкладка «Монтаж»: класс EditTab (UI + логика резки/экспорта).
#
# Исторически вся вкладка была одним файлом на ~12,5к строк, что мешало навигации
# и правкам. Сейчас она разложена по слоям (зависимости строго в одну сторону):
#   edit_tab_base    — константы, палитра, чистые хелперы (время, ffprobe, ASS)
#   edit_tab_workers — фоновые QThread-воркеры (резка, прокси, волна, субтитры)
#   edit_tab_widgets — виджеты (волна, холст видео, полный экран, превью)
#   edit_tab_dialogs — диалоги (маска, редактор/конструктор субтитров, пикселизация)
#   edit_tab_frames  — покадровая сетка и предекодирование кадров вокруг плейхеда
#   edit_tab.py      — сам EditTab и standalone-entry main() (этот файл)
#
# ВАЖНО: edit_tab_base стоит первым в цепочке — он выставляет env-переменные
# Qt-бэкенда (QSG_RHI_BACKEND/QT_MEDIA_BACKEND) ДО создания QApplication, что
# критично для видео, и определяет флаги _HAS_MULTIMEDIA / LIBASS_AVAILABLE.
import errno
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections import deque
from functools import partial
from pathlib import Path
from config import (
    CONFIG_DIR, CREATE_NO_WINDOW, FFMPEG, FFPROBE, QAction, QApplication,
    QCheckBox, QComboBox, QCursor, QDialog, QEvent, QFileDialog, QFont,
    QFontMetrics, QFrame, QHBoxLayout, QKeySequence, QLabel, QLineEdit,
    QMenu, QMessageBox, QPoint, QProgressBar, QPushButton, QRectF, QScrollArea,
    QSize, QSlider, QSpinBox, QTimer, QVBoxLayout, QWidget, Qt, get_icon,
    icon_html
)
from widgets import (info_badge)
from utils import get_pix_fmt, save_json_atomic
from msgbox import (
    msgbox_critical, msgbox_information, msgbox_question, msgbox_warning
)
from edit_tab_base import (
    C, EDITOR_SETTINGS_PATH, LIBASS_AVAILABLE, QAudioFormat,
    QAudioOutput, QAudioSink, QMediaDevices, QMediaPlayer,
    QVideoWidget, install_audio_device_recovery,
    _HAS_MULTIMEDIA, _cues_to_ass, _fmt_channels, _fullscreen_icon,
    _libass, _parse_srt, _pixelize_block_sequence, _pixelize_filter,
    _unique_output,
    format_fps, make_divider, make_icon_btn, run_ffprobe, s_to_time,
    time_to_s
)
from edit_tab_workers import (
    AssExtractor, AudioSegmentWaveformLoader, AudioWaveformLoader,
    FfmpegWorker, ProxyWorker, ShareDeleteIODevice, SmartCutWorker,
    SubtitleExtractor, TrackOverlayWorker, TrackPathWorker, VideoInpaintWorker
)
from edit_tab_widgets import (
    AudioMeter, FullscreenVideo, InfoCard, SeekPreview, SeekSlider,
    SubtitleOverlay, VideoCanvas, VolumeLabel, VolumeSlider,
    WaveformWidget
)
from edit_tab_dialogs import (
    SubtitleCreatorDialog, SubtitleEditDialog, _PixelizeDialog,
    _TrackAttachDialog, _VideoMaskDialog
)
from edit_tab_frames import (AudioScrubber, FrameGrid, FramePrefetcher,
                             probe_frame_size)
from edit_tab_overlay import (
    ImageOverlay, OverlayCropDialog, OverlayLayersPanel, fit_rect_norm,
    load_overlay_image, overlay_chroma_format, overlay_filter_graph,
    qimage_to_bgra, render_overlays
)
from PyQt6.QtCore import (QUrl)
from PyQt6.QtGui import (QImage, QPainter, QShortcut)
from PyQt6.QtWidgets import (QScrollBar, QSizePolicy, QStyle, QToolTip)


def _is_attached_pic(stream):
    """True, если поток ffprobe — ОБЛОЖКА (attached_pic), а не видеоряд.

    Обложка альбома в mp3/flac/m4a лежит в контейнере как «видеопоток» (mjpeg
    1000×1000, r_frame_rate 90000/1) из одного кадра. Принимать её за видео
    нельзя: fps 90000 давал сетку кадров на 20 млн кадров, покадровый декодер
    гонял ffmpeg вхолостую (после -ss обложка не выдаётся вовсе), а метка
    времени начинала жить по «часам кадра», которых у такого файла нет. Плюс
    сам QtMultimedia обложку видеорядом НЕ считает (hasVideo=False) — то есть
    вкладка считала иначе, чем её собственный плеер. Такой файл — чистое аудио."""
    try:
        if int((stream.get('disposition') or {}).get('attached_pic', 0) or 0):
            return True
    except Exception:
        pass
    return False


# ─── Edit Tab ─────────────────────────────────────────────────────────────────
class EditTab(QWidget):
    # Боковая панель монтажа: кнопки масштабируются под ровно столько значков в высоту.
    _MSIDE_COUNT = 8
    _MSIDE_GAP = 6

    def __init__(self, main_window=None):
        super().__init__()
        self.main = main_window
        self._ready = False

        if not _HAS_MULTIMEDIA:
            self._build_unavailable_ui()
            return

        self.filepath = None
        self.actual_source_file = None
        self.is_proxy_active = False
        self._source_is_av1 = False
        self._pending_pb_seek = None   # (pos_ms, was_playing) для swap источника
        self._pb_restore = None
        self.duration = 0.0
        self.current_in = 0.0
        self.current_out = 0.0
        self.fps = None
        self.video_aspect = None          # ширина/высота кадра (для точного 16:9-бокса)
        self.video_stream_index = None
        self.audio_stream_index = None
        # Режим «картинка → видео-проявление»: монтаж загрузил still-картинку
        # (png/jpg/…), плеер/обрезка не применимы, активна только пикселизация
        # (и кадрирование). Экспорт собирает видео из картинки через -loop 1.
        self.is_still_image = False
        self.still_image_path = None
        self._still_w = 0; self._still_h = 0
        self._still_duration = 5.0
        self._still_fps = 25
        self.tmp_proxy_file = None
        # Дорожки контейнера (заполняются из ffprobe при загрузке файла)
        self._audio_streams = []
        self._sub_streams = []
        # Внешние дорожки (отдельные файлы рядом с видео / выбранные кнопкой
        # «найти»). _*_ext — список путей; _*_entries — карта пунктов комбобокса
        # на источник: ('emb', i) встроенная дорожка | ('ext', path) внешний файл.
        self._audio_ext = []
        self._sub_ext = []
        self._sub_ext_hidden = []   # отфильтровано _scan_external_subs, см. _expand_external_subs
        self._audio_entries = []
        self._sub_entries = []
        # Внешняя озвучка: отдельный аудиоплеер, синхронный с основным (звук видео
        # при этом глушится). Создаётся лениво при первом выборе внешнего аудио.
        self._ext_audio_player = None
        self._ext_audio_output = None
        self._ext_audio_active = False
        self.selected_audio_abs_index = None   # абсолютный индекс выбранной аудиодорожки (для экспорта)
        self.selected_audio_ext_path = None    # путь к выбранной внешней озвучке (для экспорта)
        self.selected_sub_ext_path = None      # путь к выбранному внешнему файлу субтитров
        self._loading_tracks = False
        # Субтитры в превью: для текстовых дорожек рисуем свой VLC-стиль оверлеем
        # (QtMultimedia рисует их с плашкой и стиль не настраивается). Битмап-
        # дорожки (PGS/DVD) показываем встроенным рендером.
        self._sub_cues = []
        self._sub_extractor = None
        self._sub_threads = []        # живые QThread'ы извлечения (чтобы не собрал GC)
        self._sub_token = 0           # защита от устаревших результатов извлечения
        self._sub_use_overlay = False
        self.sub_overlay = None       # окно-оверлей субтитров (ленивое)
        self._overlay_win = None      # верхнеуровневое окно, на чьи Move/Resize реагируем
        # ASS/SSA в превью: рендер через libass на оверлей (полный стиль + караоке).
        self._sub_use_ass = False
        self._ass = None              # libass_renderer.AssRenderer (ленивый)
        self._ass_extractor = None
        self._ass_path = None         # временный .ass-файл (удаляем при смене)
        self._ass_timer = None        # таймер перерисовки караоке во время игры
        # ── Покадровый движок (см. edit_tab_frames.py) ───────────────────────
        # Вся арифметика перемотки ведётся в НОМЕРАХ кадров, а не в миллисекундах:
        # плеер принимает мс, и при дробном fps (23.976/29.97) шаг «позиция ±
        # 1000/fps» копил ошибку округления (каждый ~60-й шаг терял кадр), а
        # попадание ровно на границу кадра давало то текущий, то соседний кадр.
        self._grid = FrameGrid(0.0, 0.0)
        # Номер кадра, на котором стоит монтаж НА ПАУЗЕ (во время игры — None:
        # там истина у самих кадров плеера, см. _current_frame_index).
        self._frame_idx = None
        # Предекодер соседних кадров: держит вокруг плейхеда буфер точных кадров,
        # поэтому шаг стрелкой рисуется мгновенно и ровно тем кадром, что просили.
        self._frames = None
        self._frames_src = None
        # Флаг «скраб кадрами»: во время покадрового шага плеер кратко play→pause,
        # чтобы отрисовать кадр; кнопку play/pause при этом НЕ переключаем (иначе
        # она дёргается). См. step_frame_scrub / on_playback_changed.
        self._scrubbing = False
        self._scrub_target = None     # последняя цель покадрового шага (мс)
        self._frame_seek_busy = False    # в полёте не больше одного player.setPosition()
        self._frame_seek_pending = None  # см. step_frame/_dispatch_frame_seek
        self._frame_seek_target_ms = None
        self._frame_seek_gen = 0
        # Флаг «прогрев аудио»: беззвучно поднимаем аудио-декодер в точке, где
        # встал плейхед, чтобы следующее «Воспроизвести» стартовало со звуком
        # без задержки (см. _preroll_at). ЖЕЛЕЗНОЕ правило: прогрев не имеет
        # права быть виден — пока он идёт, интерфейс заморожен на цели
        # (см. _ui_pinned_ms), кнопку/иконку он не трогает.
        self._prerolling = False
        self._preroll_prev_muted = False
        self._preroll_target_ms = None   # цель прогрева «с разбега» (см. _preroll_at)
        self._preroll_gen = 0
        # «Воспроизвести» нажато посреди разбега: доигрываем разбег под mute и
        # снимаем mute на цели, не трогая позицию (см. toggle_play).
        self._preroll_handoff = False
        self._preroll_watch_timer = None
        # Скраб-звук: при покадровом шаге (WASD/стрелки) играем короткий звуковой
        # блип в новой позиции — как в Filmora. В painted-режиме основной плеер
        # кадр доставляет setPosition'ом БЕЗ play() (иначе мерцает), поэтому звука
        # не было; даём его ОТДЕЛЬНЫМ лёгким аудиоплеером по оригиналу файла, не
        # трогая видео. Включается/выключается в Настройках → «Монтаж».
        self._scrub_audio_enabled = True
        # Позиция блипа (мс) = НАЧАЛО показанного кадра. Плееру мы отдаём
        # середину кадра (так он не промахивается мимо кадра), но звук обязан
        # начинаться там же, где кадр — иначе слышно не то, что видно.
        self._scrub_audio_ms = None
        # Звук шага играет НЕ второй QMediaPlayer (он перематывался по границе
        # аудиопакета и опаздывал на 140–160 мс — см. AudioScrubber), а точный
        # PCM-срез из фонового окна, записанный прямо в QAudioSink.
        self._audio_scrub = None      # AudioScrubber (окна PCM вокруг плейхеда)
        self._scrub_sink_obj = None   # QAudioSink (открыт, пока жива вкладка)
        self._scrub_sink_io = None
        self._scrub_fmt = None
        self._scrub_wait = None       # (время, когда) — шаг ждёт окно PCM
        # Громкость до выключения звука кликом по динамику (см. toggle_mute).
        self._vol_before_mute = 100
        # Режим «только звук» (кнопка наушников): видео снято с плеера, чтобы
        # тяжёлый файл не лагал. Живёт до перезапуска приложения и НЕ пишется в
        # настройки — иначе через месяц «пропало видео» было бы загадкой.
        self._audio_only_mode = False
        self._audio_only_prev_track = 0
        # Папка экспорта обрезки ("" = рядом с исходником)
        self.export_dir = ""
        self.undo_stack: deque = deque(maxlen=50)
        self.redo_stack: deque = deque(maxlen=50)

        # Настраиваемые сочетания обрезки до точки воспроизведения (Монтаж →
        # Настройки). Применяются в register_shortcuts / set_trim_shortcuts.
        self.trim_start_seq = "Shift+C"   # обрезать СТАРТ (IN) до плейхеда
        self.trim_end_seq   = "Shift+V"   # обрезать КОНЕЦ (OUT) до плейхеда

        self.player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.player.setAudioOutput(self.audio_output)
        # Отключили наушники / сменилось устройство вывода — переезжаем на
        # живое, иначе сеанс WASAPI аннулируется и звук пропадает до
        # перезапуска (см. install_audio_device_recovery).
        self._audio_dev_watch = install_audio_device_recovery(self.audio_output)
        # Метод субтитров: True (по умолчанию) — рендер ПРЯМО В КАДР (VideoCanvas,
        # как в VLC: субтитры обрезаются по видео и перекрываются окнами сверху);
        # False — старый метод (QVideoWidget + отдельное окно-оверлей). Значение
        # читаем из настроек редактора ДО создания виджета видео.
        self._subs_in_frame = self._read_subs_in_frame_pref()
        self.video_widget = None
        self._build_video_output()
        # Переключение активных дорожек применяем, когда плеер их обнаружит.
        try:
            self.player.tracksChanged.connect(self._apply_active_tracks)
        except Exception:
            pass

        self.sync_timer = QTimer(self)
        self.sync_timer.setInterval(80)
        self.sync_timer.timeout.connect(self.sync_ui)

        # Идле-таймер «активной перемотки» для VideoCanvas.set_scrub_active — см.
        # seek_to(). Пока идут seek'и (протяжка слайдера/волны), таймер постоянно
        # перезапускается; как только он ОТРАБОТАЛ (перемотка утихла) — возвращаем
        # сглаживание кадра.
        self._scrub_idle_timer = QTimer(self)
        self._scrub_idle_timer.setSingleShot(True)
        self._scrub_idle_timer.setInterval(150)
        self._scrub_idle_timer.timeout.connect(self._on_scrub_idle)

        self.ffmpeg_thread = None
        self.proxy_thread = None
        self.audio_worker = None
        self._audio_partial_worker = None   # быстрый предпросмотр волны выделения при смене дорожки
        self._waveform_gen = 0              # отбрасывает устаревшие ответы воркеров волны
        self._waveform_cache = {}   # (path, mtime, size, audio_index) -> (samples, duration, left, right)
        self._subtitle_fonts_cache = {}   # (path, mtime, size) -> fonts_dir

        self.init_ui()
        self.apply_theme()
        self.register_shortcuts()

        self.player.positionChanged.connect(self.on_position_changed)
        self.player.durationChanged.connect(self.on_player_duration_changed)
        self.player.playbackStateChanged.connect(self.on_playback_changed)
        # Конец воспроизведения: не оставляем чёрный кадр (QtMultimedia гасит
        # поверхность на EndOfMedia) — см. on_media_status_changed.
        self.player.mediaStatusChanged.connect(self.on_media_status_changed)

        self.setAcceptDrops(True)
        self.enable_global_drag_drop()
        self.load_settings()

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._ready = True

    def _build_unavailable_ui(self):
        lay = QVBoxLayout(self)
        lbl = QLabel(
            "Модуль мультимедиа PyQt6 недоступен.\n\n"
            "Видеоредактор требует QtMultimedia. Установите PyQt6 с поддержкой "
            "мультимедиа, чтобы пользоваться вкладкой «Монтаж».")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet("color:#a6adc8; font-size:13px;")
        lay.addStretch()
        lay.addWidget(lbl)
        lay.addStretch()

    # ── UI Construction ────────────────────────────────────────────────────
    # ── UI Construction ────────────────────────────────────────────────────
    def init_ui(self):
        """Сборка интерфейса вкладки.

        Раньше это был один метод на ~900 строк. Разбит на секции-строители
        по тем же границам, что были обозначены комментариями внутри; порядок
        вызовов и сами операции не изменились. Промежуточные контейнеры
        передаются явными параметрами (а не через self), чтобы было видно,
        какая секция что использует."""
        root = self._build_root_layout()
        sidebar, sb_outer, sb_scroll, sb_content, sb_layout = self._build_sidebar()
        pbq_card = self._build_quality_card()
        self._build_proxy_card(pbq_card, sb_content, sb_layout, sb_outer, sb_scroll)
        self._build_cut_summary(sb_outer)
        center = self._build_center_area()
        self._build_player_bar(center)
        self._build_timeline_panel(center, root, sidebar)

    def _build_root_layout(self):
        """Корневой горизонтальный layout вкладки. Возвращает root."""
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        return root

    def _build_sidebar(self):
        """Правая боковая панель (инфо/экспорт) внутри QScrollArea.
        Возвращает саму панель и её внутренние контейнеры — они нужны
        секциям «прокси» и «итог», которые дозаполняют ту же панель."""
        # ── Right sidebar (прокручиваемая) ────────────────────────────────
        # Содержимое (инфо/экспорт) живёт в QScrollArea — если по высоте не
        # умещается, появляется вертикальный скроллбар. Кнопки «Итог» и
        # «Обрезать» закреплены ВНЕ прокрутки, снизу (всегда видны).
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(264)
        sidebar.setStyleSheet(f"""
            #Sidebar {{
                background: {C['surface']};
                border-left: 1px solid {C['border']};
            }}
        """)
        sb_outer = QVBoxLayout(sidebar)
        sb_outer.setContentsMargins(0, 0, 0, 0)
        sb_outer.setSpacing(0)

        sb_scroll = QScrollArea()
        sb_scroll.setObjectName("SidebarScroll")
        sb_scroll.setWidgetResizable(True)
        sb_scroll.setFrameShape(QFrame.Shape.NoFrame)
        sb_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sb_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Никакого собственного стиля скроллбара — берём общий стиль приложения
        # (config.STYLESHEET), чтобы он совпадал со скроллбарами других вкладок.
        # Фон не задаём (глобальное правило делает контент прозрачным → виден
        # surface самого сайдбара; собственный фон давал серую «подложку»).
        sb_scroll.setStyleSheet("QScrollArea#SidebarScroll { border: none; }")
        sb_content = QWidget()
        sb_layout = QVBoxLayout(sb_content)
        # Правый отступ 14px — «дорожка» для вертикального скроллбара, чтобы он не
        # перекрывал содержимое (панель всегда видна полностью).
        sb_layout.setContentsMargins(16, 16, 14, 16)
        sb_layout.setSpacing(12)

        # File section
        self.lbl_file = QLabel("Нет файла")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet(f"""
            color: {C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {C['surface2']};
            border: 1px dashed {C['border2']};
            border-radius: 6px;
        """)
        self.lbl_file.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(self.lbl_file)

        # Кнопки работы с файлом в одну строку: «Открыть» занимает половину
        # ширины, рядом — «Очистить» (убирает текущий файл и сбрасывает редактор).
        file_btn_row = QHBoxLayout()
        file_btn_row.setSpacing(8)
        btn_open = make_icon_btn("Открыть", accent=True, icon='fa5s.folder-open')
        self._relax_width(btn_open)  # не заставляем панель расширяться под текст
        btn_open.clicked.connect(self.open_file)
        btn_clear = make_icon_btn("Очистить", icon='fa5s.trash')
        self._relax_width(btn_clear)
        btn_clear.setToolTip("Убрать текущий файл и очистить редактор")
        btn_clear.clicked.connect(self.clear_file)
        file_btn_row.addWidget(btn_open, 1)
        file_btn_row.addWidget(btn_clear, 1)
        sb_layout.addLayout(file_btn_row)

        sb_layout.addWidget(make_divider())

        # Media info card
        info_card = InfoCard("МЕДИА ИНФОРМАЦИЯ")
        self.lbl_duration = info_card.add_row("Длительность", "lbl_duration")
        self.lbl_fps      = info_card.add_row("FPS",          "lbl_fps")
        self.lbl_vstream  = info_card.add_row("Видео",        "lbl_vstream")
        self.lbl_astream  = info_card.add_row("Аудио",        "lbl_astream")
        self.lbl_abitrate = info_card.add_row("Битрейт аудио", "lbl_abitrate")
        sb_layout.addWidget(info_card)

        sb_layout.addWidget(make_divider())

        # Export settings card
        export_card = InfoCard("НАСТРОЙКИ ЭКСПОРТА")

        mode_lbl = QLabel("Режим обрезки")
        mode_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        export_card._body.addWidget(mode_lbl)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItems([
            "Быстро (без потерь)",
            "Перекодировать",
            "Только аудио (MP3)",
            "Smart Cut (умная)",
            "Перекодировать настройками «Обработки»",
            "(Аудио) Перекодировать настройками «Обработки»",
        ])
        # По умолчанию — «Перекодировать» (кадрово точная обрезка).
        self.cmb_mode.setCurrentIndex(1)
        self.cmb_mode.setToolTip(
            "Быстро — copy без перекодировки (начало прилипает к ключевому кадру).\n"
            "Перекодировать — кадрово точно, но медленно и с потерями.\n"
            "Smart Cut — точные границы реза перекодируются, середина копируется "
            "без потерь (быстро и с сохранением качества).\n"
            "Перекодировать настройками «Обработки» — точный рез и текущие настройки "
            "вкладки «Обработка» (кодек/CRF/скорость/громкость/fps) ОДНИМ проходом, "
            "без двойной перекодировки. Наложенные картинки вшиваются тем же "
            "проходом; кодировщик и «Вшить субтитры»/кадрирование/пикселизация "
            "в этом режиме не применяются.\n"
            "(Аудио) Перекодировать настройками «Обработки» — то же самое, но "
            "видеоряд отбрасывается: на выходе ТОЛЬКО звуковая дорожка (.opus) с "
            "текущими настройками звука «Обработки» (битрейт/громкость/фейды/"
            "скорость).")
        # Не даём комбобоксу диктовать ширину панели по длине пункта (иначе панель
        # переполняется и обрезается). Закрытый комбо подстраивается под N символов,
        # полный текст пунктов виден в выпадающем списке.
        self.cmb_mode.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_mode.setMinimumContentsLength(8)
        self._relax_width(self.cmb_mode)
        self.cmb_mode.setStyleSheet(f"""
            QComboBox {{
                background: {C['surface3']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {C['surface3']};
                color: {C['text']};
                selection-background-color: {C['accent']};
                border: 1px solid {C['border2']};
            }}
        """)
        export_card._body.addWidget(self.cmb_mode)

        # Кодировщик для перекодировки (режим «Перекодировать» и границы Smart Cut):
        # CPU (libx264) — лучшее качество/совместимость; GPU — быстрее, грузит
        # видеокарту. На «Быстро (без потерь)» не влияет (там copy без кодека).
        enc_lbl = QLabel("Кодировщик (перекодировка)")
        enc_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        export_card._body.addWidget(enc_lbl)

        self.cmb_encoder = QComboBox()
        self.cmb_encoder.addItems([
            "Авто",
            "Процессор (CPU)",
            "Видеокарта (GPU)",
        ])
        self.cmb_encoder.setToolTip(
            "Чем перекодировать видео при обрезке с перекодировкой и на границах "
            "Smart Cut.\n"
            "Процессор (CPU) — libx264, лучшее качество и совместимость, медленнее.\n"
            "Видеокарта (GPU) — аппаратный кодек (NVENC/QSV/AMF), быстрее, "
            "нагружает видеокарту.\n"
            "Если выбранного варианта нет в сборке — автоматический откат.")
        self.cmb_encoder.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_encoder.setMinimumContentsLength(8)
        self._relax_width(self.cmb_encoder)
        self.cmb_encoder.setStyleSheet(self.cmb_mode.styleSheet())
        export_card._body.addWidget(self.cmb_encoder)

        self.chk_overwrite = QCheckBox("Перезаписать файл")
        self.chk_overwrite.setChecked(True)
        self._relax_width(self.chk_overwrite)
        self.chk_overwrite.setStyleSheet(f"""
            QCheckBox {{
                color: {C['text2']};
                font-size: 12px;
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {C['border2']};
                border-radius: 3px;
                background: {C['surface3']};
            }}
            QCheckBox::indicator:checked {{
                background: {C['accent']};
                border-color: {C['accent']};
            }}
        """)
        export_card._body.addWidget(self.chk_overwrite)

        # Вшивание (hardsub) выбранных субтитров прямо в картинку. ВНИМАНИЕ:
        # это всегда требует ПЕРЕКОДИРОВКИ видео (пиксели субтитров рисуются на
        # кадрах) — без перекодировки можно лишь встроить субтитры отдельной
        # дорожкой, но не «вжечь» в изображение. Сам чекбокс размещаем НЕ здесь,
        # а в правой панели рядом с кнопками «Сохранить кадр»/«Удалить исходник»
        # (см. сборку side-панели ниже) — создаём заранее, добавим туда.
        self.chk_burn_subs = QCheckBox("Вшить субтитры")
        self.chk_burn_subs.setChecked(False)
        self._relax_width(self.chk_burn_subs)
        self.chk_burn_subs.setToolTip(
            "Жёстко впечатывает выбранную дорожку субтитров в кадр.\n"
            "Требует перекодировки видео (режим обрезки будет проигнорирован).\n"
            "Субтитры выбираются в панели справа от видео.")
        self.chk_burn_subs.setStyleSheet(self.chk_overwrite.styleSheet())

        # Папка сохранения результата ("" = рядом с исходником)
        dst_lbl = QLabel("Папка сохранения")
        dst_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        self._relax_width(dst_lbl)
        export_card._body.addWidget(dst_lbl)
        self.lbl_export_dir = QLabel("Рядом с исходником")
        # Без переноса (длинный путь не разрывается и распирал бы панель) — вместо
        # этого укорачиваем в середине в _update_export_dir_label; min width 0,
        # чтобы метка не диктовала ширину панели.
        self.lbl_export_dir.setWordWrap(False)
        self.lbl_export_dir.setMinimumWidth(0)
        self._relax_width(self.lbl_export_dir)
        self.lbl_export_dir.setStyleSheet(
            f"color: {C['text2']}; font-size: 11px; padding: 4px 6px; "
            f"background: {C['surface3']}; border: 1px solid {C['border2']}; border-radius: 5px;")
        export_card._body.addWidget(self.lbl_export_dir)
        dst_row = QHBoxLayout(); dst_row.setSpacing(6)
        btn_dst = make_icon_btn("Выбрать", icon='fa5s.folder')
        self._relax_width(btn_dst)
        btn_dst.clicked.connect(self._choose_export_dir)
        btn_dst_reset = make_icon_btn("", icon='fa5s.undo')
        # Узкая квадратная кнопка: убираем боковой паддинг make_icon_btn,
        # фиксируем размер.
        btn_dst_reset.setStyleSheet(btn_dst_reset.styleSheet()
                                    + "\nQPushButton { padding: 5px 0; }")
        btn_dst_reset.setFixedSize(34, 32)
        btn_dst_reset.setToolTip("Сбросить — сохранять рядом с исходником")
        btn_dst_reset.clicked.connect(self._reset_export_dir)
        dst_row.addWidget(btn_dst, 1); dst_row.addWidget(btn_dst_reset, 0)
        export_card._body.addLayout(dst_row)

        sb_layout.addWidget(export_card)

        return sidebar, sb_outer, sb_scroll, sb_content, sb_layout

    def _build_quality_card(self):
        """Карточка «Качество воспроизведения» в боковой панели. Возвращает карточку
        (следующая секция вставляет карточку прокси сразу после неё)."""
        # ── Качество воспроизведения (как в Filmora) ──────────────────────────
        # Понижает разрешение ТОЛЬКО предпросмотра (через прокси), чтобы плеер и
        # перемотка работали шустрее на слабом железе/тяжёлых файлах. На экспорт
        # не влияет — он всегда из оригинала.
        pbq_card = InfoCard("ВОСПРОИЗВЕДЕНИЕ")
        pbq_lbl = QLabel("Качество воспроизведения")
        pbq_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        self.cmb_pb_quality = QComboBox()
        self.cmb_pb_quality.addItems([
            "Полное качество",
            "1/2 — быстрее",
            "1/4 — ещё быстрее",
        ])
        self.cmb_pb_quality.setToolTip(
            "Качество предпросмотра (не влияет на экспорт).\n"
            "Полное — играет оригинал без прокси. Исключение — AV1: его "
            "QtMultimedia не тянет напрямую, поэтому для него прокси строится "
            "всегда (это единственный случай «не поддерживается»).\n"
            "1/2 и 1/4 — плеер всегда показывает уменьшенную копию (прокси): "
            "воспроизведение и перемотка работают быстрее на тяжёлых файлах.")
        self.cmb_pb_quality.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_pb_quality.setMinimumContentsLength(8)
        self._relax_width(self.cmb_pb_quality)
        self.cmb_pb_quality.setStyleSheet(self.cmb_mode.styleSheet())
        self.cmb_pb_quality.currentIndexChanged.connect(self._on_pb_quality_changed)
        pbq_card._body.addWidget(pbq_lbl)
        pbq_card._body.addWidget(self.cmb_pb_quality)

        return pbq_card

    def _build_proxy_card(self, pbq_card, sb_content, sb_layout, sb_outer, sb_scroll):
        """Карточка «Прокси только для части файла» — ставится под карточкой качества."""
        # ── Прокси только для части файла ─────────────────────────────────────
        # Сколько МИНУТ исходника превращать в прокси (0 = весь файл). Усечённый
        # прокси собирается быстрее на длинных/тяжёлых видео; предпросмотр тогда
        # ограничен этим отрезком, на экспорт/обрезку не влияет (она из оригинала).
        pmin_lbl = QLabel("Минут для прокси")
        pmin_lbl.setStyleSheet(f"color: {C['text3']}; font-size: 12px;")
        self.spin_proxy_min = QSpinBox()
        self.spin_proxy_min.setRange(0, 600)
        self.spin_proxy_min.setValue(0)
        self.spin_proxy_min.setSpecialValueText("Весь файл")
        self.spin_proxy_min.setSuffix(" мин")
        self.spin_proxy_min.setToolTip(
            "Создавать прокси только для первых N минут видео (0 — весь файл).\n"
            "Усечённый прокси собирается быстрее на длинных/тяжёлых файлах.\n"
            "Предпросмотр ограничится этим отрезком; на экспорт и обрезку не влияет.")
        self._relax_width(self.spin_proxy_min)
        self.spin_proxy_min.valueChanged.connect(lambda *_: self._on_pb_quality_changed())
        pbq_card._body.addWidget(pmin_lbl)
        pbq_card._body.addWidget(self.spin_proxy_min)
        sb_layout.addWidget(pbq_card)

        # Proxy badge
        self.lbl_proxy = QLabel("")
        self.lbl_proxy.setStyleSheet(f"""
            color: {C['yellow']};
            font-size: 11px;
            font-weight: 600;
            padding: 4px 8px;
            background: rgba(245,158,11,0.12);
            border: 1px solid rgba(245,158,11,0.3);
            border-radius: 4px;
        """)
        self.lbl_proxy.setVisible(False)
        sb_layout.addWidget(self.lbl_proxy)

        sb_layout.addStretch()

        # Прокручиваемая часть готова — вставляем её в сайдбар.
        sb_scroll.setWidget(sb_content)
        sb_outer.addWidget(sb_scroll, 1)

        # Колесо мыши над выпадающими списками правой панели прокручивает саму
        # панель, а не меняет значение поля. Иначе при включённой в Настройках
        # опции «колесо меняет значения» скролл «застревал» на блоке режима
        # обрезки — комбобокс съедал событие колеса.
        for _w in sb_content.findChildren(QComboBox):
            self._install_wheel_scroll(_w)

    def _build_cut_summary(self, sb_outer):
        """Итог обрезки и кнопка «Обрезать» — закреплены СНИЗУ, вне прокрутки."""
        # ── Итог + кнопка обрезки — закреплены СНИЗУ (вне прокрутки) ───────
        # Высота блока = высоте полосы таймлайна (BAND_H ниже) → «Итог»/«Обрезать»
        # визуально на одной строке с виджетом аудио-визуализации слева.
        sb_bottom = QFrame()
        sb_bottom.setObjectName("SidebarBottom")
        sb_bottom.setFixedHeight(116)
        sb_bottom.setStyleSheet(
            f"#SidebarBottom {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        bottom_l = QVBoxLayout(sb_bottom)
        bottom_l.setContentsMargins(16, 10, 16, 14)
        bottom_l.setSpacing(10)
        bottom_l.addStretch()

        self.lbl_selection = QLabel("Зона: —")
        self.lbl_selection.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_selection.setStyleSheet(f"""
            color: {C['text']};
            font-size: 13px;
            font-weight: 600;
            padding: 7px 10px;
            background: {C['surface2']};
            border: 1px solid {C['border']};
            border-radius: 6px;
        """)
        bottom_l.addWidget(self.lbl_selection)

        self.btn_cut = QPushButton("Обрезать")
        self.btn_cut.setIcon(get_icon('fa5s.cut', color='#1e1e2e'))
        self.btn_cut.setIconSize(QSize(20, 20))
        self.btn_cut.clicked.connect(self.start_cut)
        # Зелёная, как кнопка «НАЧАТЬ» во вкладке «Обработка» (#b_run в config.py).
        self.btn_cut.setStyleSheet(f"""
            QPushButton {{
                background: #a6e3a1;
                color: #1e1e2e;
                border: none;
                border-radius: 6px;
                padding: 9px 24px;
                font-weight: 700;
                font-size: 13px;
                letter-spacing: 0.3px;
            }}
            QPushButton:hover {{ background: #94e2d5; }}
            QPushButton:pressed {{ background: #74c7ec; }}
            QPushButton:disabled {{ background: {C['surface3']}; color: {C['text3']}; }}
        """)
        bottom_l.addWidget(self.btn_cut)
        bottom_l.addStretch()
        sb_outer.addWidget(sb_bottom, 0)

        # progress/log_label больше не показываются в интерфейсе (прогресс идёт в
        # общий прогрессбар окна). Оставлены скрытыми, чтобы существующий код,
        # дёргающий .setText()/.setValue(), не падал.
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.log_label = QLabel("")
        self.log_label.setVisible(False)

        # Сайдбар добавляется ПОСЛЕ центральной области (root.addWidget ниже),
        # чтобы видео и плеер были слева, а панель информации/экспорта — справа.

    def _build_center_area(self):
        """Центральная область: холст видео и его оверлеи. Возвращает layout center."""
        # ── Center area ───────────────────────────────────────────────────
        center = QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        # Video player area + правая панель (дорожки/субтитры/индикатор звука).
        # Панель занимает место, где раньше были чёрные поля сбоку от видео.
        video_row = QHBoxLayout()
        video_row.setContentsMargins(0, 0, 0, 0)
        video_row.setSpacing(0)

        self.video_container = QFrame()
        self.video_container.setObjectName("VideoContainer")
        # Фон — цвет интерфейса (а не чёрный): пустота вокруг кадра сливается с UI.
        self.video_container.setStyleSheet(f"#VideoContainer {{ background: {C['bg']}; }}")
        vc_layout = QHBoxLayout(self.video_container)
        self.vc_layout = vc_layout
        vc_layout.setContentsMargins(0, 0, 0, 0)
        # Видео центрировано (по горизонтали и вертикали); точный аспект кадра
        # задаётся в _adjust_video_height → внутри виджета полей нет, а свободное
        # место по бокам — это фон цвета интерфейса.
        vc_layout.addWidget(self.video_widget, 0, Qt.AlignmentFlag.AlignCenter)
        # Оверлей субтитров (VLC-стиль) создаётся лениво как отдельное окно поверх
        # видео — см. _ensure_overlay/_position_overlay (QVideoWidget нативный,
        # обычный дочерний виджет под ним не виден).
        video_row.addWidget(self.video_container, 1)

        # Правая панель
        side = QFrame()
        side.setObjectName("SidePanel")
        side.setFixedWidth(196)
        side.setStyleSheet(f"#SidePanel {{ background: {C['surface']}; border-left: 1px solid {C['border']}; }}")
        side_outer = QVBoxLayout(side)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.setSpacing(0)
        # Содержимое панели — в прокрутке, как в правом сайдбаре. Панель растёт
        # динамически (список слоёв появляется вместе с наложенными картинками),
        # и в невысоком окне Qt раньше ужимал виджеты НИЖЕ их минимума: список
        # слоёв сплющивался в синюю полоску, а подпись «Прозрачность» налезала
        # на кнопки слоя. Со скроллом каждый элемент держит свой размер, а при
        # высоком окне поведение прежнее — widgetResizable растягивает
        # содержимое на всю высоту (шкала уровня звука по-прежнему тянется).
        side_scroll = QScrollArea()
        side_scroll.setObjectName("SidePanelScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        side_scroll.setStyleSheet("QScrollArea#SidePanelScroll { border: none; }")
        side_content = QWidget()
        side_l = QVBoxLayout(side_content)
        # Правый отступ 4px — дорожка под вертикальный скроллбар, чтобы он не
        # наезжал на комбобоксы (общий стиль приложения даёт узкий ползунок).
        side_l.setContentsMargins(10, 10, 4, 10)
        side_l.setSpacing(6)
        side_scroll.setWidget(side_content)
        side_outer.addWidget(side_scroll)

        _combo_css = f"""
            QComboBox {{
                background: {C['surface3']}; color: {C['text']};
                border: 1px solid {C['border2']}; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {C['surface3']}; color: {C['text']};
                selection-background-color: {C['accent']};
                border: 1px solid {C['border2']};
            }}
        """
        def _find_btn(tip, slot):
            b = QPushButton()
            b.setIcon(get_icon('fa5s.folder-open'))
            b.setIconSize(QSize(20, 20))
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(30, 28)
            b.setStyleSheet(f"""
                QPushButton {{ background: {C['surface3']}; color: {C['text']};
                    border: 1px solid {C['border2']}; border-radius: 5px;
                    padding: 0; font-size: 13px; }}
                QPushButton:hover {{ background: {C['border2']};
                    border-color: {C['accent']}; }}
            """)
            b.clicked.connect(slot)
            return b

        lbl_at = QLabel("Аудиодорожка")
        lbl_at.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_at)
        at_row = QHBoxLayout(); at_row.setContentsMargins(0, 0, 0, 0); at_row.setSpacing(5)
        self.cmb_audio = QComboBox()
        self.cmb_audio.setStyleSheet(_combo_css)
        self.cmb_audio.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_audio.setMinimumContentsLength(6)
        self.cmb_audio.currentIndexChanged.connect(self.on_audio_track_changed)
        at_row.addWidget(self.cmb_audio, 1)
        self.btn_find_audio = _find_btn(
            "Найти внешний аудиофайл (озвучку) на ПК", self.find_external_audio)
        at_row.addWidget(self.btn_find_audio, 0)
        side_l.addLayout(at_row)

        # Заголовок «Субтитры» + кнопка-карандаш (правка текста субтитров прямо тут).
        st_hdr = QHBoxLayout(); st_hdr.setContentsMargins(0, 0, 0, 0); st_hdr.setSpacing(4)
        lbl_st = QLabel("Субтитры")
        lbl_st.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        st_hdr.addWidget(lbl_st)
        st_hdr.addStretch(1)
        self.btn_edit_subs = QPushButton()
        self.btn_edit_subs.setIcon(get_icon('fa5s.edit', color=C['text2']))
        self.btn_edit_subs.setIconSize(QSize(14, 14))
        self.btn_edit_subs.setFixedSize(24, 20)
        self.btn_edit_subs.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_edit_subs.setToolTip("Редактировать текст выбранных субтитров")
        self.btn_edit_subs.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background: {C['surface3']}; }}
            QPushButton:pressed {{ background: {C['border2']}; }}
        """)
        self.btn_edit_subs.clicked.connect(self.edit_subtitles)
        st_hdr.addWidget(self.btn_edit_subs)
        side_l.addLayout(st_hdr)
        st_row = QHBoxLayout(); st_row.setContentsMargins(0, 0, 0, 0); st_row.setSpacing(5)
        self.cmb_subs = QComboBox()
        self.cmb_subs.setStyleSheet(_combo_css)
        self.cmb_subs.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_subs.setMinimumContentsLength(6)
        self.cmb_subs.currentIndexChanged.connect(self.on_sub_track_changed)
        st_row.addWidget(self.cmb_subs, 1)
        self.btn_find_subs = _find_btn(
            "Найти внешний файл субтитров на ПК", self.find_external_subs)
        st_row.addWidget(self.btn_find_subs, 0)
        side_l.addLayout(st_row)

        # Стиль вшиваемых субтитров (hardsub): как в программе или как в оригинале.
        lbl_ss = QLabel("Стиль вшитых субтитров")
        lbl_ss.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_ss)
        self.cmb_sub_style = QComboBox()
        self.cmb_sub_style.addItems(["Авто", "Как в программе", "Как в оригинале"])
        # По умолчанию — «Как в оригинале» (стиль из самих субтитров, ничего не навязываем).
        self.cmb_sub_style.setCurrentIndex(2)
        self.cmb_sub_style.setToolTip(
            "Стиль субтитров при вшивании в кадр:\n"
            "Авто — стиль программы для SRT/VTT, у ASS/SSA остаётся собственный.\n"
            "Как в программе — крупный белый шрифт с обводкой даже поверх ASS/SSA.\n"
            "Как в оригинале — ничего не навязывать (стиль из самих субтитров).")
        self.cmb_sub_style.setStyleSheet(_combo_css)
        self.cmb_sub_style.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_sub_style.setMinimumContentsLength(6)
        side_l.addWidget(self.cmb_sub_style)

        # Чекбокс «Вшить субтитры» — НАД индикатором уровня звука (по просьбе
        # пользователя). Кнопки кадра/удаления переехали в самый низ панели.
        # Список наложенных картинок (появляется, только когда слои есть).
        self.overlay_panel = OverlayLayersPanel()
        self.overlay_panel.selected.connect(self._on_overlay_selected)
        self.overlay_panel.cropRequested.connect(self._crop_image_overlay)
        self.overlay_panel.deleteRequested.connect(self._delete_image_overlay)
        self.overlay_panel.opacityChanged.connect(self._set_overlay_opacity)
        self.overlay_panel.resetRequested.connect(self._reset_image_overlay)
        side_l.addSpacing(6)
        side_l.addWidget(self.overlay_panel)

        side_l.addSpacing(6)
        side_l.addWidget(self.chk_burn_subs)

        # Низ боковой панели: СЛЕВА — кнопки «Сохранить кадр»/«Удалить исходник»
        # (столбиком), СПРАВА — индикатор уровня звука. Прежде кнопки лежали ПОД
        # индикатором и перекрывали подписи каналов L/R (см. скрин); теперь они
        # сбоку, и шкала уровня занимает всю доступную высоту панели.
        # «Кадрировать видео» — значок над «Сохранить кадр»: включаешь, выделяешь
        # область прямо на видео, и при «Обрезать» итоговое ВИДЕО кадрируется по
        # этой рамке (а не только сохраняемый кадр). Повторное нажатие выключает и
        # сбрасывает рамку. Кадрирование требует перекодировки (copy не умеет
        # crop), поэтому при активной рамке быстрый режим переключается на
        # «Перекодировать» автоматически.
        self.btn_crop_frame = make_icon_btn("")
        self.btn_crop_frame.setIcon(get_icon('fa5s.crop-alt'))
        self.btn_crop_frame.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_crop_frame)
        self.btn_crop_frame.setCheckable(True)
        self.btn_crop_frame.setToolTip("Кадрировать видео: выделите область на видео — "
                                       "при «Обрезать» сохранится только она "
                                       "(требует перекодировки)")
        self.btn_crop_frame.toggled.connect(self._toggle_frame_crop)
        self.btn_crop_frame.setEnabled(False)
        # «Пикселизация — проявление»: видео стартует крупными блоками и постепенно
        # проясняется (для угадайки). Параметры задаются в диалоге, эффект
        # применяется при «Обрезать» (требует перекодировки, как и кадрирование).
        self._pixelize_active = False
        self._pixelize_steps = 6
        self._pixelize_block = 64
        self.btn_pixelize = make_icon_btn("")
        self.btn_pixelize.setIcon(get_icon('fa5s.th'))
        self.btn_pixelize.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_pixelize)
        self.btn_pixelize.setCheckable(True)
        self.btn_pixelize.setToolTip("Пикселизация: видео начнётся крупными «пикселями» "
                                     "и постепенно станет чётким (для угадайки). "
                                     "Применяется при «Обрезать» (перекодировка)")
        self.btn_pixelize.toggled.connect(self._toggle_pixelize)
        self.btn_pixelize.setEnabled(False)
        # ВИДИМОЕ состояние «включено»: make_icon_btn не стилизует :checked, и
        # армированная пикселизация выглядела как обычная кнопка (пользователь не
        # видел, что эффект активен). Подсвечиваем активную кнопку акцентом.
        self.btn_pixelize.setStyleSheet(self.btn_pixelize.styleSheet() + f"""
            QPushButton:checked {{
                background: {C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {C['accent2']}; }}
        """)
        self.btn_save_frame = make_icon_btn("")
        self.btn_save_frame.setIcon(get_icon('fa5s.save'))
        self.btn_save_frame.setIconSize(QSize(20, 20))
        self._relax_width(self.btn_save_frame)
        self.btn_save_frame.setToolTip("Сохранить текущий кадр в PNG (в папку сохранения)")
        self.btn_save_frame.clicked.connect(self.save_frame)
        self.btn_save_frame.setEnabled(False)   # активна только при загруженном видео
        # «Удалить объект» — покадровое удаление водяного знака/эмодзи с видео тем же
        # движком LaMa, что и в фоторедакторе (см. remove_object_from_video).
        self.btn_remove_object = make_icon_btn("")
        self.btn_remove_object.setIcon(get_icon('fa5s.magic'))
        self.btn_remove_object.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_remove_object)
        self.btn_remove_object.setToolTip(
            "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте его "
            "кистью на кадре — нейросеть LaMa уберёт его со всех кадров")
        self.btn_remove_object.clicked.connect(self.remove_object_from_video)
        self.btn_remove_object.setEnabled(False)
        # «Создать субтитры» — реплики (текст+тайминг) и позиция на экране задаются
        # в отдельном окне (SubtitleCreatorDialog), результат — новая .ass-дорожка.
        self.btn_create_subs = make_icon_btn("")
        self.btn_create_subs.setIcon(get_icon('fa5s.closed-captioning'))
        self.btn_create_subs.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_create_subs)
        self.btn_create_subs.setToolTip(
            "Создать субтитры: текст, тайминг и позиция на экране "
            "задаются в отдельном окне. Если сейчас выбрана дорожка "
            "субтитров — открывает её же на редактирование")
        self.btn_create_subs.clicked.connect(self.create_subtitles)
        self.btn_create_subs.setEnabled(False)
        # «Привязать к объекту» — отслеживание выбранной области (DyHiT/HiT, ONNX;
        # запасной трекер — CSRT из OpenCV) и накладка (текст/картинка), едущая
        # вместе с объектом. См. track_object_overlay.
        self.btn_track_object = make_icon_btn("")
        self.btn_track_object.setIcon(get_icon('fa5s.crosshairs'))
        self.btn_track_object.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_track_object)
        self.btn_track_object.setToolTip(
            "Привязать к объекту: обведите движущийся объект (руку, лицо, "
            "машину) — нейросеть проследит за ним, и выбранный текст или "
            "картинка поедут вместе с ним. Накладка сразу видна в плеере; "
            "в файл её вшивает «Обрезать», повторное нажатие — убирает")
        self.btn_track_object.clicked.connect(self.track_object_overlay)
        self.btn_track_object.setEnabled(False)
        # «Наложить картинку» — неподвижный логотип/водяной знак/рамка поверх
        # видео: картинка появляется прямо в плеере, её двигают/тянут/крутят
        # мышью, кадрируют отдельным окном, а «Обрезать» вшивает её в файл
        # (overlay=…, требует перекодировки — как кадрирование).
        self.btn_image_overlay = make_icon_btn("")
        self.btn_image_overlay.setIcon(get_icon('fa5s.image'))
        self.btn_image_overlay.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_image_overlay)
        self.btn_image_overlay.setToolTip(
            "Наложить картинку: выберите файл — он ляжет слоем поверх видео. "
            "Перетаскивайте мышью, тяните за уголки, крутите за «антенну» "
            "сверху (Shift — шаг 15°), Ctrl+стрелки — точная сдвижка, "
            "Delete — убрать слой; обрезать саму картинку и задать "
            "прозрачность — в списке слоёв справа. "
            "Вшивается при «Обрезать» (перекодировка)")
        self.btn_image_overlay.clicked.connect(self.add_image_overlay)
        self.btn_image_overlay.setEnabled(False)
        self.btn_delete_source = make_icon_btn("", danger=True)
        self.btn_delete_source.setIcon(get_icon('fa5s.trash-alt', color='#11111b'))
        self.btn_delete_source.setIconSize(QSize(18, 18))
        self._relax_width(self.btn_delete_source)
        self.btn_delete_source.setToolTip("Удалить исходный файл с диска (без возможности отмены)")
        self.btn_delete_source.clicked.connect(self.delete_source_file)
        self.btn_delete_source.setEnabled(False)

        # Две колонки по 4 квадратные кнопки (место под 8 штук) — левая и правая,
        # каждая прижата к низу (симметрично высоте шкалы уровня звука справа).
        # Правая колонка нарочно короче: «Удалить исходник» (опасная, красная)
        # держим самой нижней — как и раньше в одной колонке.
        self._montage_side_btns = [self.btn_crop_frame, self.btn_pixelize,
                                   self.btn_save_frame, self.btn_remove_object,
                                   self.btn_create_subs, self.btn_track_object,
                                   self.btn_image_overlay, self.btn_delete_source]
        col_l = QVBoxLayout(); col_l.setContentsMargins(0, 0, 0, 0)
        col_l.setSpacing(self._MSIDE_GAP)
        col_l.addStretch(1)
        for _b in (self.btn_crop_frame, self.btn_pixelize,
                   self.btn_save_frame, self.btn_remove_object):
            col_l.addWidget(_b)
        col_r = QVBoxLayout(); col_r.setContentsMargins(0, 0, 0, 0)
        col_r.setSpacing(self._MSIDE_GAP)
        col_r.addStretch(1)
        for _b in (self.btn_create_subs, self.btn_track_object,
                   self.btn_image_overlay, self.btn_delete_source):
            col_r.addWidget(_b)
        btn_col = QHBoxLayout(); btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(self._MSIDE_GAP)
        btn_col.addLayout(col_l)
        btn_col.addLayout(col_r)
        btn_col.addStretch(1)   # не растягивать колонки шире квадратных кнопок

        # Правая колонка — подпись + шкала, отцентрованная под текстом.
        vu_col = QVBoxLayout(); vu_col.setContentsMargins(0, 0, 0, 0); vu_col.setSpacing(3)
        lbl_vu = QLabel("Уровень звука")
        lbl_vu.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        lbl_vu.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        vu_col.addWidget(lbl_vu, 0)
        self.audio_meter = AudioMeter()
        self.audio_meter.setFixedWidth(54)
        meter_row = QHBoxLayout(); meter_row.setContentsMargins(0, 0, 0, 0)
        meter_row.addStretch(1)
        meter_row.addWidget(self.audio_meter)
        meter_row.addStretch(1)
        vu_col.addLayout(meter_row, 1)
        # Высота шкалы == высоте колонки кнопок → по её ресайзу пересчитываем кнопки.
        self.audio_meter.installEventFilter(self)

        bottom_row = QHBoxLayout(); bottom_row.setContentsMargins(0, 0, 0, 0)
        bottom_row.setSpacing(10)
        bottom_row.addLayout(btn_col, 1)
        bottom_row.addLayout(vu_col, 0)
        side_l.addLayout(bottom_row, 1)

        video_row.addWidget(side, 0)
        center.addLayout(video_row, stretch=1)

        return center

    def _build_player_bar(self, center):
        """Панель плеера под видео: play/pause, время, громкость, покадровый шаг."""
        # ── Player bar (прямо под видео) ──────────────────────────────────
        # Компактный плеер как в обычном видеоплеере: полоса воспроизведения,
        # тайминги (текущее/общее), кнопки и громкость — всё под самим видео.
        player_bar = QFrame()
        player_bar.setObjectName("PlayerBar")
        player_bar.setStyleSheet(f"#PlayerBar {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        pb_layout = QVBoxLayout(player_bar)
        pb_layout.setContentsMargins(12, 6, 12, 7)
        pb_layout.setSpacing(6)

        # Верхняя строка: полоса воспроизведения + тайминги (текущее / общее)
        seek_row = QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(10)

        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.setStyleSheet(self._slider_style(C["playhead"]))
        # Превью кадров при наведении на полосу (как на YouTube). Один контроллер
        # на обе полосы — в окне и в полноэкранном режиме (см. FullscreenVideo).
        self.seek_preview = SeekPreview(lambda: getattr(self, "duration", 0.0) or 0.0)
        self.slider.attach_preview(self.seek_preview)
        seek_row.addWidget(self.slider, 1)

        time_frame = QFrame()
        time_frame.setStyleSheet(f"""
            background: {C['bg']};
            border: 1px solid {C['border']};
            border-radius: 6px;
        """)
        time_fl = QHBoxLayout(time_frame)
        time_fl.setContentsMargins(8, 3, 8, 3)
        time_fl.setSpacing(3)
        _mono = QFont("Courier New" if os.name == 'nt' else "Courier")
        _mono.setBold(True); _mono.setPointSize(11)
        self.lbl_current_time = QLabel("00:00:00.000")
        self.lbl_current_time.setFont(_mono)
        self.lbl_current_time.setStyleSheet(f"color: {C['green2']}; background: transparent;")
        sep_time = QLabel("/")
        sep_time.setStyleSheet(f"color: {C['text3']}; background: transparent;")
        self.lbl_total_time = QLabel("00:00:00.000")
        self.lbl_total_time.setFont(_mono)
        self.lbl_total_time.setStyleSheet(f"color: {C['text3']}; background: transparent;")
        time_fl.addWidget(self.lbl_current_time)
        time_fl.addWidget(sep_time)
        time_fl.addWidget(self.lbl_total_time)
        seek_row.addWidget(time_frame)
        pb_layout.addLayout(seek_row)

        # Нижняя строка: кнопки управления + громкость
        pctrl_row = QHBoxLayout()
        pctrl_row.setContentsMargins(0, 0, 0, 0)
        pctrl_row.setSpacing(6)

        # Кнопки плеера — только иконки, без подписей (квадратные).
        self.btn_stop = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaStop)
        self.btn_stop.setFixedWidth(40)
        self.btn_stop.setToolTip("Стоп — к началу зоны")
        self.btn_stop.clicked.connect(self.stop_playback)
        pctrl_row.addWidget(self.btn_stop)

        self.btn_step_back = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSeekBackward)
        self.btn_step_back.setFixedWidth(40)
        self.btn_step_back.setToolTip("Кадр назад (←)")
        self.btn_step_back.clicked.connect(partial(self.step_frame_scrub, -1))
        pctrl_row.addWidget(self.btn_step_back)

        self.btn_play = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaPlay, accent=True)
        self.btn_play.setFixedWidth(48)
        self.btn_play.setToolTip("Воспроизвести / пауза (Пробел)")
        self.btn_play.clicked.connect(self.toggle_play)
        pctrl_row.addWidget(self.btn_play)

        self.btn_step_fwd = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSeekForward)
        self.btn_step_fwd.setFixedWidth(40)
        self.btn_step_fwd.setToolTip("Кадр вперёд (→)")
        self.btn_step_fwd.clicked.connect(partial(self.step_frame_scrub, 1))
        pctrl_row.addWidget(self.btn_step_fwd)

        self.btn_jump_end = make_icon_btn("", icon_std=QStyle.StandardPixmap.SP_MediaSkipForward)
        self.btn_jump_end.setFixedWidth(40)
        self.btn_jump_end.setToolTip("Перейти к концу зоны (OUT)")
        self.btn_jump_end.clicked.connect(lambda: self.seek_to(self.current_out))
        pctrl_row.addWidget(self.btn_jump_end)

        pctrl_row.addSpacing(14)

        # Поля ввода таймкода IN/OUT убраны по запросу — вместо них кнопки
        # «Обрезать старт/конец» (до плейхеда) и длительность выделения. Сами
        # объекты in_time_edit/out_time_edit/in_frame_spin/out_frame_spin остаются
        # СКРЫТЫМИ держателями: на них завязан остальной код (set_in_out и т.п.).
        io_holder = QWidget(player_bar)
        io_h = QHBoxLayout(io_holder); io_h.setContentsMargins(0, 0, 0, 0)
        self.in_time_edit = QLineEdit("00:00:00.000")
        self.in_time_edit.returnPressed.connect(self.set_in_point)
        self.in_frame_spin = QSpinBox(); self.in_frame_spin.setMaximum(100000000)
        self.in_frame_spin.valueChanged.connect(self.on_in_frame_changed)
        self.out_time_edit = QLineEdit("00:00:05.000")
        self.out_time_edit.returnPressed.connect(self.set_out_point)
        self.out_frame_spin = QSpinBox(); self.out_frame_spin.setMaximum(100000000)
        self.out_frame_spin.valueChanged.connect(self.on_out_frame_changed)
        for _w in (self.in_time_edit, self.in_frame_spin,
                   self.out_time_edit, self.out_frame_spin):
            io_h.addWidget(_w)
        io_holder.hide()

        _trim_btn_css = f"""
            QPushButton {{
                background: {C['surface3']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {C['surface2']}; border-color: {C['accent']}; }}
            QPushButton:pressed {{ background: {C['surface']}; }}
            QPushButton:disabled {{ color: {C['text3']}; }}
        """
        _ss = getattr(self, "trim_start_seq", "Shift+C")
        _es = getattr(self, "trim_end_seq", "Shift+V")
        self.btn_trim_start = QPushButton("Обрезать старт")
        self.btn_trim_start.setToolTip(
            f"Поставить начало (старт) на жёлтую полосу воспроизведения ({_ss})")
        self.btn_trim_start.setStyleSheet(_trim_btn_css)
        # NoFocus: иначе клик мыши уводил клавиатурный фокус на кнопку, и потом
        # Space/Ctrl+Z воспринимались как нажатие кнопки/уходили мимо вкладки
        # (баг «после кнопок Обрезать Ctrl+Z не работает»). Фокус оставляем на
        # вкладке монтажа — там висят все хоткеи (WidgetWithChildrenShortcut).
        self.btn_trim_start.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_trim_start.clicked.connect(self.trim_start_to_playhead)
        pctrl_row.addWidget(self.btn_trim_start)

        self.btn_trim_end = QPushButton("Обрезать конец")
        self.btn_trim_end.setToolTip(
            f"Поставить конец на жёлтую полосу воспроизведения ({_es})")
        self.btn_trim_end.setStyleSheet(_trim_btn_css)
        self.btn_trim_end.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_trim_end.clicked.connect(self.trim_end_to_playhead)
        pctrl_row.addWidget(self.btn_trim_end)

        # Длительность отрезка от старта (IN) до жёлтой полосы воспроизведения.
        seg_frame = QFrame()
        seg_frame.setObjectName("SegFrame")
        seg_frame.setStyleSheet(f"#SegFrame {{ background: {C['surface3']}; border: 1px solid {C['border2']}; border-radius: 6px; }}")
        seg_l = QHBoxLayout(seg_frame)
        seg_l.setContentsMargins(8, 4, 8, 4); seg_l.setSpacing(6)
        seg_cap = QLabel("⏱ старт→плейхед")
        seg_cap.setStyleSheet(f"color: {C['text3']}; font-size: 11px; font-weight: 700;")
        self.lbl_seg_dur = QLabel("00:00:00.000")
        self.lbl_seg_dur.setStyleSheet(f"color: {C['text']}; font-size: 12px; font-weight: 700;")
        self.lbl_seg_dur.setToolTip(
            "Длительность от начала (старта) до жёлтой полосы воспроизведения")
        seg_l.addWidget(seg_cap); seg_l.addWidget(self.lbl_seg_dur)
        pctrl_row.addWidget(seg_frame)

        pctrl_row.addStretch()

        # «Только звук» — снимает видеодорожку с ПЛЕЕРА. На тяжёлых исходниках
        # (AV1/HEVC 1080p60, ЦП-декод) отрисовка кадров съедает главный поток и
        # монтаж начинает лагать, а картинка нужна не всегда: половину работы
        # режут по волне и на слух. Кнопка убирает видео из превью целиком —
        # на РЕЗУЛЬТАТ обрезки это не влияет (её гонит отдельный ffmpeg).
        self.btn_audio_only = make_icon_btn("")
        self.btn_audio_only.setIcon(get_icon('fa5s.headphones'))
        self.btn_audio_only.setIconSize(QSize(18, 18))
        self.btn_audio_only.setFixedWidth(40)
        self.btn_audio_only.setCheckable(True)
        # NoFocus — иначе клик уводит фокус с вкладки и Пробел начинает жать
        # кнопку вместо воспроизведения (та же беда, что у «Обрезать старт»).
        self.btn_audio_only.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_audio_only.setToolTip(
            "Только звук: отключить видео в плеере, чтобы не лагало.\n"
            "На обрезку и экспорт не влияет — там видео остаётся.")
        # make_icon_btn не стилизует :checked — подсвечиваем включённый режим
        # акцентом, иначе не видно, что видео отключено намеренно.
        self.btn_audio_only.setStyleSheet(self.btn_audio_only.styleSheet() + f"""
            QPushButton:checked {{
                background: {C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {C['accent2']}; }}
        """)
        self.btn_audio_only.toggled.connect(self._toggle_audio_only)
        self.btn_audio_only.setEnabled(False)   # активна только при видео
        pctrl_row.addWidget(self.btn_audio_only)

        pctrl_row.addSpacing(8)

        # Регулятор громкости — у правого края, рядом с полноэкранным режимом.
        # (Кнопки «Сохранить кадр»/«Удалить исходник» — внизу боковой панели.)
        self.vol_lbl = VolumeLabel(lambda: getattr(self, "vol_slider", None))
        self.vol_lbl.setStyleSheet(f"color: {C['text2']}; font-size: 14px;")
        # Клик по динамику — mute/unmute с возвратом прежнего уровня.
        self.vol_lbl.clicked.connect(self.toggle_mute)
        pctrl_row.addWidget(self.vol_lbl)
        self.vol_slider = VolumeSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(96)
        self.vol_slider.setStyleSheet(self._slider_style(C["text2"], compact=True))
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        pctrl_row.addWidget(self.vol_slider)

        pctrl_row.addSpacing(8)
        self.btn_fullscreen = make_icon_btn("", accent=True)
        # Стартует без видео → disabled и приглушённая иконка (станет белой при
        # загрузке видео в _update_media_buttons).
        self.btn_fullscreen.setIcon(_fullscreen_icon(expand=True, color=C['text3']))
        self.btn_fullscreen.setIconSize(QSize(20, 20))
        self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        self.btn_fullscreen.setEnabled(False)   # активна только при загруженном видео
        pctrl_row.addWidget(self.btn_fullscreen)

        pb_layout.addLayout(pctrl_row)
        center.addWidget(player_bar)

        # Состояние полноэкранного режима (окно создаётся по запросу).
        self._fs_window = None

    def _build_timeline_panel(self, center, root, sidebar):
        """Нижняя панель таймлайна (волна, субтитры) и финальная сборка вкладки."""
        # ── Timeline panel ────────────────────────────────────────────────
        # Высота полосы таймлайна фиксирована и совпадает с нижним блоком правой
        # панели («Итог» + «Обрезать»), чтобы они визуально были одной строкой.
        # Панель ужата почти до высоты самой визуализации (волна + скроллбар +
        # небольшие отступы сверху/снизу) — остальное место отдаётся видео.
        BAND_H = 116
        timeline_panel = QFrame()
        timeline_panel.setObjectName("TimelinePanel")
        timeline_panel.setFixedHeight(BAND_H)
        timeline_panel.setStyleSheet(f"#TimelinePanel {{ background: {C['surface']}; border-top: 1px solid {C['border']}; }}")
        tp_layout = QVBoxLayout(timeline_panel)
        tp_layout.setContentsMargins(12, 6, 12, 6)
        tp_layout.setSpacing(3)

        # Горизонтальная прокрутка волны — над виджетом визуализации аудио.
        # Видна только когда волна увеличена (zoom>1) и есть что прокручивать;
        # двигает «окно обзора» (view_offset) по таймлайну.
        self.wave_scroll = QScrollBar(Qt.Orientation.Horizontal)
        self.wave_scroll.setObjectName("WaveScroll")
        self.wave_scroll.setRange(0, 0)
        self.wave_scroll.valueChanged.connect(self.on_wave_scroll)
        self.wave_scroll.setVisible(False)
        self.wave_scroll.setStyleSheet(f"""
            QScrollBar:horizontal {{
                background: {C['surface2']};
                height: 12px;
                border-radius: 6px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {C['border2']};
                border-radius: 5px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {C['accent']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
        """)
        tp_layout.addWidget(self.wave_scroll)

        # Waveform — невысокая полоса (амплитуда у обычного звука небольшая, при
        # большой высоте сверху/снизу остаётся пустота). Ограничиваем высоту и
        # оставляем небольшой отступ снизу (margin tp_layout).
        self.waveform = WaveformWidget()
        self.waveform.setMinimumHeight(54)
        self.waveform.setMaximumHeight(104)
        self.waveform.seekRequested.connect(self.on_wave_seek)
        self.waveform.playSeekRequested.connect(self.on_wave_playseek)
        # ВНИМАНИЕ: inSetRequested/outSetRequested НЕ подключаем — selectionChanged
        # уже синхронизирует state/поля/кадры (иначе двойной вызов, баг #10).
        self.waveform.selectionChanged.connect(self.on_wave_selection_changed)
        self.waveform.viewChanged.connect(self.on_wave_view_changed)
        self.waveform.interactionStarted.connect(self.push_undo)
        # ПКМ по аудио-визуализации → меню обрезки старт/конец до плейхеда.
        self.waveform.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.waveform.customContextMenuRequested.connect(self._trim_ctx_menu)
        tp_layout.addWidget(self.waveform, stretch=1)

        # Строка «ПРОКРУТКА» убрана по запросу. pan_slider оставлен как скрытый
        # объект (без родителя, никогда не показывается) — чтобы существующий код
        # update_pan_slider_values не падал; pan_row_w намеренно НЕ создаём
        # (getattr → None → строка панорамирования не отображается).
        self.pan_slider = QSlider(Qt.Orientation.Horizontal)
        self.pan_slider.setRange(0, 1000)
        self.pan_slider.setEnabled(False)
        self.pan_slider.sliderMoved.connect(self.on_pan_moved)

        # Полоса воспроизведения (self.slider) перенесена в player_bar под видео.

        # Таймлайн фиксированной (небольшой) высоты — лишнее место отдаётся видео
        # (video_row = stretch 1). Нижние панели (IN/OUT) тоже stretch=0, поэтому
        # на маленьком окне ужимается именно видео, а не интерфейс под ним.
        center.addWidget(timeline_panel, stretch=0)

        # (IN/OUT перенесены на строку с кнопками плеера в player_bar; отдельной
        #  панели IN/OUT больше нет. Панель управления плеером — в player_bar под
        #  видео; «Итог» и «Обрезать» — в правой панели.)

        root.addLayout(center, stretch=1)
        root.addWidget(sidebar)

    # ── Style helpers ──────────────────────────────────────────────────────
    def _slider_style(self, color, compact=False):
        h = "4px" if compact else "5px"
        return f"""
            QSlider::groove:horizontal {{
                background: {C['surface3']};
                border-radius: 3px;
                height: {h};
            }}
            QSlider::handle:horizontal {{
                background: {color};
                border: 2px solid {C['bg']};
                width: 13px; height: 13px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color};
                border-radius: 3px;
            }}
        """

    def _input_style(self):
        return f"""
            QLineEdit {{
                background: {C['bg']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 5px;
                padding: 5px 8px;
                font-size: 12px;
                font-family: Courier New, Courier;
            }}
            QLineEdit:focus {{ border-color: {C['accent']}; }}
        """

    def _spin_style(self):
        return f"""
            QSpinBox {{
                background: {C['bg']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 5px;
                padding: 5px 4px;
                font-size: 12px;
            }}
            QSpinBox:focus {{ border-color: {C['accent']}; }}
            QSpinBox::up-button, QSpinBox::down-button {{ width: 14px; }}
        """

    def apply_theme(self):
        # Тёмная тема редактора применяется к этому виджету и его потомкам,
        # переопределяя общий стиль приложения только в пределах вкладки.
        self.setStyleSheet(f"""
            QWidget {{
                background: {C['bg']};
                color: {C['text']};
                font-family: 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif;
                font-size: 13px;
            }}
            QToolTip {{
                background: {C['surface3']};
                color: {C['text']};
                border: 1px solid {C['border2']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QLabel {{ background: transparent; }}
            QMessageBox {{ background: {C['surface']}; }}
            QFileDialog {{ background: {C['surface']}; }}
        """)

    def _install_wheel_scroll(self, widget):
        """Заставляет виджет (комбобокс и т.п.) НЕ менять значение на колесо
        мыши, а прокручивать ближайшую QScrollArea-родителя — так колесо над
        полем прокручивает панель, как и над пустым местом."""
        def handler(event, _w=widget):
            sa = _w.parent()
            while sa is not None and not isinstance(sa, QScrollArea):
                sa = sa.parent()
            if isinstance(sa, QScrollArea):
                QApplication.sendEvent(sa.viewport(), event)
            else:
                event.ignore()
        widget.wheelEvent = handler

    def _on_cut_progress(self, p):
        self._cut_lastp = float(p)
        self._report_cut(self._cut_lastp)

    def _report_cut(self, p):
        """Строка прогресса обрезки с ETA. Пока ffmpeg не дал реального прогресса
        (p<1 — фаза подготовки/перемотки), показываем счётчик «прошло», чтобы не
        выглядело зависшим. Дублируем статус в крупную метку над кнопкой
        «Обрезать» (lbl_selection) — нижняя полоса окна легко теряется, а здесь
        пользователь смотрит прямо на кнопку (см. _set_cut_status)."""
        try:
            elapsed = time.time() - getattr(self, "_cut_t0", time.time())
            if p >= 1.0:
                eta = max(0.0, elapsed * (100.0 - p) / p)
                txt = f"Обрезка… {int(p)}%  •  ETA {self._fmt_mmss(eta)}"
                self._report_progress(int(p), txt)
                self._set_cut_status(f"Обрезка… {int(p)}%  •  ETA {self._fmt_mmss(eta)}",
                                     icon='fa5s.cut')
            else:
                # Фаза подготовки: при обрезке с перекодированием ffmpeg сначала
                # перематывает декодер до точки реза (выходной seek) и ещё не даёт
                # ни одного out_time — реального процента нет. Включаем пульсирующий
                # («busy») режим полосы, чтобы она не выглядела зависшей на 0%.
                txt = f"Обрезка… подготовка ({self._fmt_mmss(elapsed)})"
                self._report_progress(-1, txt)
                self._set_cut_status(f"Обрезка… подготовка {self._fmt_mmss(elapsed)}",
                                     icon='fa5s.hourglass-half')
        except Exception:
            pass

    def _set_cut_status(self, text, icon='fa5s.cut'):
        """Показывает текст прогресса обрезки в крупной метке над кнопкой
        «Обрезать» (вместо «Итог: …»). Видно прямо на месте действия, в отличие
        от полосы внизу окна. Снимается через _clear_cut_status → восстанавливает
        обычный «Итог: …»."""
        lbl = getattr(self, "lbl_selection", None)
        if lbl is None:
            return
        try:
            lbl.setText(f"{icon_html(icon, 13, C['accent'])}  {text}")
        except Exception:
            pass

    def _clear_cut_status(self):
        """Возвращает метку над кнопкой к обычному виду «Итог: …» после обрезки."""
        try:
            self.update_selection_label()
        except Exception:
            pass

    @staticmethod
    def _make_temp_out(final_out, suffix=None):
        """Создаёт временный файл для результата РЯДОМ с финальным путём, а не в
        системном %TEMP%. Две причины: (1) os.replace не умеет переносить файл
        между дисками (WinError 17 «cannot move the file to a different disk
        drive»), а сохранять на D:\\ при temp на C:\\ — обычный сценарий;
        (2) не гоняем гигабайты между дисками. Если каталог назначения недоступен
        на запись — откатываемся в системный temp (перенос вытянет _move_tolerant).
        Возвращает путь к пустому файлу."""
        if suffix is None:
            suffix = Path(final_out).suffix
        out_dir = os.path.dirname(os.path.abspath(final_out))
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix,
                                             prefix=".sihyx_tmp_", dir=out_dir)
            tf.close()
            return tf.name
        except OSError:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
            tf.close()
            return tf.name

    @staticmethod
    def _move_tolerant(temp, final):
        """os.replace, но с откатом на копирование, если temp и final лежат на
        РАЗНЫХ дисках: os.replace тогда падает с WinError 17 / EXDEV. shutil.move
        в этом случае копирует и удаляет источник. Все прочие ошибки (в т.ч.
        WinError 32 «занят») пробрасываются наверх — их разбирает
        _replace_tolerant."""
        try:
            os.replace(temp, final)
        except OSError as e:
            cross = (getattr(e, "winerror", None) == 17
                     or e.errno == getattr(errno, "EXDEV", 18))
            if not cross:
                raise
            # Цель может уже существовать — shutil.move на непустой файл ругается,
            # поэтому убираем её сами (занятую цель отловит WinError 32 выше).
            if os.path.exists(final):
                os.remove(final)
            shutil.move(temp, final)
        return final

    @staticmethod
    def _replace_tolerant(temp, final):
        """Переносит temp → final атомарным os.replace. Если файл назначения занят
        ДРУГИМ процессом (например, его прямо сейчас читает вкладка «Обработка»,
        перекодируя только что сделанную обрезку) — Windows возвращает
        WinError 32 и os.replace падает. Раньше это роняло всю обрезку с ошибкой
        «не может получить доступ к файлу». Теперь в таком случае сохраняем
        готовый результат под соседним свободным именем (foo_обрез_1.mkv, _2…),
        а не теряем работу. Перенос между дисками (temp в %TEMP% на C:, результат
        на D:) идёт копированием — см. _move_tolerant. Возвращает фактический путь
        сохранения."""
        candidate = final
        last_err = None
        for _ in range(128):
            try:
                return EditTab._move_tolerant(temp, candidate)
            except OSError as e:
                # WinError 32 (sharing violation) приходит как PermissionError или
                # OSError с winerror==32 — цель занята, пробуем соседнее имя.
                busy = isinstance(e, PermissionError) or getattr(e, "winerror", None) == 32
                if not busy:
                    raise
                last_err = e
                candidate = _unique_output(candidate)
        # Крайне маловероятно (128 занятых имён подряд) — пробрасываем ошибку.
        if last_err:
            raise last_err
        return candidate

    def _notify_busy_rename(self, wanted, saved):
        """Сообщает, что целевой файл был занят и обрезка сохранена под другим
        именем (а не потеряна с ошибкой WinError 32)."""
        msg = (f"Файл «{os.path.basename(wanted)}» был занят другим процессом "
               f"(скорее всего, его перекодирует вкладка «Обработка»).\n\n"
               f"Обрезка сохранена под именем «{os.path.basename(saved)}».")
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(msg.replace("\n\n", " "))
        except Exception:
            pass
        try:
            msgbox_information(self, "Файл был занят", msg)
        except Exception:
            pass

    @staticmethod
    def _fmt_mmss(sec):
        sec = int(max(0, sec))
        return f"{sec // 60:d}:{sec % 60:02d}"

    def _report_progress(self, pct, text=""):
        """Прогресс вкладки → общий прогрессбар окна (main.pbar). В standalone-
        режиме (без главного окна) обновляет собственный скрытый прогрессбар.
        pct < 0 → неопределённый («busy») режим — полоса пульсирует."""
        busy = (pct is not None and pct < 0)
        if not busy:
            pct = int(max(0, min(100, pct)))
        try:
            if self.main is not None and hasattr(self.main, 'update_global_progress'):
                self.main.update_global_progress(
                    -1 if busy else pct,
                    text or ("Монтаж" if busy else ("Готово" if pct >= 100 else "Монтаж")))
                return
        except Exception:
            pass
        try:
            if busy:
                self.progress.setRange(0, 0)
            else:
                if self.progress.maximum() == 0:
                    self.progress.setRange(0, 100)
                self.progress.setValue(pct)
        except Exception:
            pass

    # ── Видеовыход и метод субтитров ─────────────────────────────────────────
    def _read_subs_in_frame_pref(self):
        """Метод субтитров теперь зафиксирован значением по умолчанию (рендер
        прямо в кадр, как в VLC) — настройка убрана из UI по просьбе пользователя."""
        return True

    def _build_video_output(self):
        """Создаёт виджет видео под текущий метод субтитров и подключает плеер.
        frame-режим: VideoCanvas (рисуем кадр сами + субтитры в кадр).
        overlay-режим: QVideoWidget (нативная поверхность) + окно-оверлей."""
        if self._subs_in_frame:
            self.video_widget = VideoCanvas()
            try:
                self.player.setVideoSink(self.video_widget.videoSink())
            except Exception:
                pass
        else:
            self.video_widget = QVideoWidget()
            try:
                self.video_widget.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
            except Exception:
                pass
            self.player.setVideoOutput(self.video_widget)
        self.video_widget.setStyleSheet(f"background: {C['bg']};")
        # Анти-overshoot: VideoCanvas сам ловит кадр за OUT по PTS → просит паузу.
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.boundaryReached.connect(self._on_play_boundary)
            # Кадрирование завершено кнопкой на холсте — снимаем чек с «Кадрировать».
            self.video_widget.cropApplied.connect(self._on_crop_applied)
            self.video_widget.cropCancelled.connect(self._on_crop_cancelled)
            self.video_widget.overlaysChanged.connect(self._on_overlays_changed)
            self.video_widget.overlaySelected.connect(self._on_overlay_picked)
        try:
            self.video_widget.setAcceptDrops(True)
            self.video_widget.installEventFilter(self)
        except Exception:
            pass
        # Кадр выводит сцена Qt Quick (GPU). Если она не поднялась (нет модулей
        # в сборке, не создался графический контекст), холст молча переходит на
        # ЦП-отрисовку — она в разы дороже, и об этом надо знать, а не гадать,
        # почему «Монтаж вдруг лагает».
        if (isinstance(self.video_widget, VideoCanvas)
                and getattr(self.video_widget, "_quick", None) is None):
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Монтаж: сцена Qt Quick не поднялась — кадры "
                                  "рисуются на ЦП (заметно медленнее)")
            except Exception:
                pass

    def set_subs_in_frame(self, in_frame, save=True):
        """Переключает метод субтитров (Монтаж → Настройки). Применяется на лету:
        пересобирает виджет видео в layout, переносит позицию/воспроизведение и
        перенастраивает показ текущей дорожки субтитров."""
        in_frame = bool(in_frame)
        if not getattr(self, "_ready", False):
            self._subs_in_frame = in_frame
            if save:
                try: self.save_settings()
                except Exception: pass
            return
        if in_frame == self._subs_in_frame:
            if save:
                try: self.save_settings()
                except Exception: pass
            return
        if getattr(self, "_fs_window", None) is not None:
            self.exit_fullscreen()
        try:
            pos = self.player.position()
            playing = (self.player.playbackState()
                       == QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            pos, playing = 0, False
        # Гасим текущий показ субтитров и окно-оверлей (если было).
        self._hide_sub_display()
        if self.sub_overlay is not None:
            try: self.sub_overlay.close(); self.sub_overlay.deleteLater()
            except Exception: pass
            self.sub_overlay = None
        # Меняем виджет видео в layout.
        old = self.video_widget
        try: self.vc_layout.removeWidget(old)
        except Exception: pass
        try: self.player.setVideoOutput(None)
        except Exception: pass
        self._subs_in_frame = in_frame
        self._build_video_output()
        try:
            self.vc_layout.insertWidget(0, self.video_widget, 0,
                                        Qt.AlignmentFlag.AlignCenter)
        except Exception:
            pass
        try: old.setParent(None); old.deleteLater()
        except Exception: pass
        self._adjust_video_height()
        try:
            self.player.setPosition(pos)
            if playing: self.player.play()
        except Exception:
            pass
        # Перенастраиваем показ текущей дорожки субтитров.
        if self._sub_use_overlay or self._sub_use_ass:
            self._prepare_sub_display()
            try: self._update_subtitle(pos / 1000.0)
            except Exception: pass
        if save:
            try: self.save_settings()
            except Exception: pass

    def _prepare_sub_display(self):
        """Готовит цель для показа субтитров: окно-оверлей (overlay-режим) либо
        ничего (frame-режим — рисует сам холст)."""
        if self._subs_in_frame:
            return
        self._ensure_overlay()
        self._position_overlay()

    def _hide_sub_display(self):
        """Сбрасывает показанные субтитры в текущей цели."""
        if self._subs_in_frame:
            vw = self.video_widget
            if isinstance(vw, VideoCanvas):
                vw.clear_subtitle()
        else:
            ov = self.sub_overlay
            if ov is not None:
                ov.clear_subtitle(); ov.hide()

    def _adjust_video_height(self):
        """Подгоняет окно видео ровно под аспект кадра (без чёрных полей внутри
        QVideoWidget), вписывая его в доступную область. «Максимум 16:9»: если
        кадр шире 16:9, бокс не растягивается выше этого соотношения по высоте."""
        # В полноэкранном режиме видео живёт в отдельном окне — не навязываем ему
        # фиксированный размер контейнера вкладки.
        if getattr(self, "_fs_window", None) is not None:
            return
        try:
            cont = getattr(self, "video_container", None)
            cw = cont.width() if cont is not None else self.video_widget.width()
            ch = cont.height() if cont is not None else int(self.height() * 0.55)
            if cw <= 0:
                cw = max(320, int(self.width() * 0.55))
            if ch <= 0:
                ch = max(180, int(self.height() * 0.55))
            # Кадр не должен занимать слишком много по высоте на больших окнах.
            ch = min(ch, int(self.height() * 0.62)) or ch
            aspect = self.video_aspect if (self.video_aspect and self.video_aspect > 0) else (16.0 / 9.0)
            # «Не более 16:9»: ограничиваем минимальный аспект (для очень узких
            # вертикалок бокс не становится чрезмерно высоким — режется по ch).
            fit_w = cw
            fit_h = int(round(fit_w / aspect))
            if fit_h > ch:
                fit_h = ch
                fit_w = int(round(fit_h * aspect))
            fit_w = max(80, min(fit_w, cw))
            fit_h = max(60, min(fit_h, ch))
            self.video_widget.setMinimumSize(fit_w, fit_h)
            self.video_widget.setMaximumSize(fit_w, fit_h)
            # Оверлей субтитров подгоняем под экранную область видео.
            self._position_overlay()
        except Exception:
            pass

    # ── Resize ────────────────────────────────────────────────────────────
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self._ready:
            self._adjust_video_height()

    def showEvent(self, ev):
        super().showEvent(ev)
        # Пересчитать размер холста ДО отрисовки — иначе виджет мигает старым
        # размером и лишь на resizeEvent долетает до нужного (визуальный сдвиг).
        if self._ready:
            self._adjust_video_height()
        # Вкладку показали (вернулись на «Монтаж») — вернуть оверлей субтитров.
        QTimer.singleShot(0, self._position_overlay)
        # QTabWidget помнит, какой дочерний виджет был в фокусе на этой странице
        # в прошлый раз (например, кнопка «Открыть» или комбобокс «Режим
        # обрезки») и возвращает фокус ЕМУ при переключении на вкладку. Из-за
        # этого мгновенный Space сразу после переключения на «Монтаж» не играл
        # видео (шорткат Space зарегистрирован на self), а активировал
        # сфокусированный виджет — жал кнопку/раскрывал комбобокс. Перехватываем
        # фокус на себя при каждом показе вкладки, чтобы Space гарантированно
        # доставался toggle_play, а не случайному виджету боковой панели.
        if self._ready:
            QTimer.singleShot(0, self.setFocus)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        # Ушли с вкладки — прячем оверлей-окно, чтобы оно не висело поверх других.
        ov = getattr(self, "sub_overlay", None)
        if ov is not None:
            ov.hide()

    def _adjust_video_aspect_once(self):
        self._adjust_video_height()

    # ── Drag & Drop ───────────────────────────────────────────────────────
    def enable_global_drag_drop(self):
        for w in self.findChildren(QWidget):
            try:
                w.setAcceptDrops(True)
                w.installEventFilter(self)
            except Exception:
                pass
        self.installEventFilter(self)

    def eventFilter(self, watched, event):
        # Колесо мыши НЕ меняет значения полей (спинбоксы кадров, комбобоксы
        # дорожек/режима, ползунки громкости/позиции) — частая причина случайных
        # изменений. Виджет волны (WaveformWidget) не входит в эти типы → его
        # зум колесом сохраняется.
        # Шкала уровня звука изменила высоту → пересчёт размера кнопок (ровно 8).
        if (event.type() == QEvent.Type.Resize
                and watched is getattr(self, "audio_meter", None)):
            self._resize_montage_side_btns(watched.height())
        if event.type() == QEvent.Type.Wheel and isinstance(
                watched, (QSpinBox, QComboBox, QSlider)):
            # Виджеты с пометкой wheelAlways (ползунок громкости) — колесо меняет
            # значение ВСЕГДА: пропускаем событие к их собственному wheelEvent.
            if watched.property("wheelAlways"):
                return False
            return True
        # Двойной клик по видео → переключение полноэкранного режима.
        if (event.type() == QEvent.Type.MouseButtonDblClick
                and watched is self.video_widget):
            self.toggle_fullscreen()
            return True
        # Главное окно подвинули/изменили → ведём за ним оверлей субтитров.
        if (watched is self._overlay_win
                and event.type() in (QEvent.Type.Move, QEvent.Type.Resize,
                                     QEvent.Type.WindowStateChange)):
            self._position_overlay()
        if event.type() == QEvent.Type.DragEnter:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction(); return True
        if event.type() == QEvent.Type.DragMove:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction(); return True
        if event.type() == QEvent.Type.Drop:
            md = event.mimeData(); loaded = False
            try:
                urls = md.urls()
                if urls:
                    local = urls[0].toLocalFile()
                    if local and os.path.exists(local):
                        self.load_file(local); loaded = True
            except Exception:
                pass
            if not loaded:
                try:
                    txt = md.text()
                    if txt:
                        path = txt.strip()
                        if os.path.exists(path):
                            self.load_file(path); loaded = True
                except Exception:
                    pass
            if loaded:
                event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)

    # ── Папка экспорта ──────────────────────────────────────────────────────
    def _choose_export_dir(self):
        start = self.export_dir or (str(self.actual_source_file.parent)
                                    if self.actual_source_file else "")
        d = QFileDialog.getExistingDirectory(self, "Папка для сохранения обрезки", start)
        if d:
            self.export_dir = d
            self._update_export_dir_label()
            self.save_settings()

    def _reset_export_dir(self):
        self.export_dir = ""
        self._update_export_dir_label()
        self.save_settings()

    def _update_export_dir_label(self):
        lbl = getattr(self, "lbl_export_dir", None)
        if lbl is None:
            return
        if self.export_dir and os.path.isdir(self.export_dir):
            # Укорачиваем путь в середине, чтобы он не распирал панель; полный
            # путь — в подсказке.
            fm = QFontMetrics(lbl.font())
            elided = fm.elidedText(self.export_dir, Qt.TextElideMode.ElideMiddle, 210)
            lbl.setText(elided)
            lbl.setToolTip(self.export_dir)
        else:
            lbl.setText("Рядом с исходником")
            lbl.setToolTip("Файл сохраняется в папке исходника")

    # ── Аудио/субтитры: дорожки ─────────────────────────────────────────────
    @staticmethod
    def _fmt_bitrate(ainfo):
        raw = (ainfo or {}).get('bit_rate')
        if not raw:
            # Контейнеры mkvmerge (MKV) не пишут bit_rate в поток, а кладут его в
            # тег статистики — обычно «BPS-eng» (язык в суффиксе), реже «BPS».
            # Берём первый тег, чьё имя начинается на BPS (без учёта регистра).
            tags = (ainfo or {}).get('tags', {}) or {}
            raw = tags.get('BPS') or tags.get('BPS-eng')
            if not raw:
                for k, v in tags.items():
                    if k.upper().startswith('BPS'):
                        raw = v
                        break
        try:
            return f"{round(int(raw) / 1000)} кбит/с"
        except Exception:
            return "—"

    @staticmethod
    def _track_label(s, i, kind, total=1):
        tags = s.get('tags', {}) or {}
        lang = tags.get('language') or tags.get('LANGUAGE') or ''
        title = tags.get('title') or tags.get('TITLE') or ''
        codec = (s.get('codec_name') or '').upper()
        parts = [f"{i + 1}."]
        # Тег языка показываем ТОЛЬКО когда дорожек несколько — иначе выбирать
        # нечего, а тег часто врёт (YouTube помечает единственную/оригинальную
        # дорожку как "eng" независимо от реального языка озвучки).
        if lang and total > 1: parts.append(lang)
        if title: parts.append(title[:18])
        if codec and not title: parts.append(codec)
        return " ".join(parts) or f"Дорожка {i + 1}"

    def _populate_track_combos(self):
        self._loading_tracks = True
        # Новый файл → сбрасываем оверлей субтитров от предыдущего (combo
        # переустанавливается на «Выкл», но on_sub_track_changed под флагом молчит).
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()
        try:
            # ── Аудио: встроенные дорожки + внешние файлы (озвучка) ──
            self.cmb_audio.clear()
            self._audio_entries = []
            for i, s in enumerate(self._audio_streams):
                self.cmb_audio.addItem(self._track_label(s, i, "Аудио", total=len(self._audio_streams)))
                self._audio_entries.append(('emb', i))
            for p in self._audio_ext:
                self.cmb_audio.addItem(get_icon('fa5s.file'), os.path.basename(p))
                self._audio_entries.append(('ext', p))
            if not self._audio_entries:
                self.cmb_audio.addItem("— нет —")
            self.cmb_audio.setEnabled(len(self._audio_entries) > 1)

            # ── Субтитры: «Выкл» + встроенные + внешние файлы ──
            self.cmb_subs.clear()
            self.cmb_subs.addItem("Выкл")
            self._sub_entries = []
            for i, s in enumerate(self._sub_streams):
                self.cmb_subs.addItem(self._track_label(s, i, "Субтитры", total=len(self._sub_streams)))
                self._sub_entries.append(('emb', i))
            for p in self._sub_ext:
                self.cmb_subs.addItem(get_icon('fa5s.file'), os.path.basename(p))
                self._sub_entries.append(('ext', p))
            if getattr(self, "_sub_ext_hidden", None):
                self.cmb_subs.addItem(get_icon('fa5s.folder-open'),
                                       f"Показать другие файлы в папке… ({len(self._sub_ext_hidden)})")
                self._sub_entries.append(('more', None))
            self.cmb_subs.setEnabled(len(self._sub_entries) > 0)
        finally:
            self._loading_tracks = False
        self.selected_audio_abs_index = (
            self._audio_streams[0].get('index') if self._audio_streams else None)
        self.selected_audio_ext_path = None
        self.selected_sub_ext_path = None
        self._clear_external_audio()

    def on_audio_track_changed(self, idx):
        if self._loading_tracks or idx < 0 or idx >= len(self._audio_entries):
            return
        kind, ref = self._audio_entries[idx]
        if kind == 'emb':
            # Встроенная дорожка → возвращаем звук видео, гасим внешнюю озвучку.
            self.selected_audio_ext_path = None
            self._clear_external_audio()
            st = self._audio_streams[ref]
            self.selected_audio_abs_index = st.get('index')
            try:
                self.player.setActiveAudioTrack(ref)
            except Exception:
                pass
            # Инфо-метки (кодек/каналы/битрейт) и аудиоволна — под новую дорожку.
            # prioritize_selection: сперва быстро строим волну на выделенном
            # отрезке, полный файл досчитывается следом в фоне.
            self._update_audio_info_labels(st)
            self._start_waveform(self.actual_source_file, st.get('index'), prioritize_selection=True)
        else:
            # Внешний файл озвучки → играет отдельный синхронный плеер.
            self.selected_audio_abs_index = None
            self.selected_audio_ext_path = ref
            self._set_external_audio(ref)
            self._update_audio_info_labels(self._probe_audio_stream(ref))
            # Волну строим из самого файла озвучки (единственная дорожка).
            self._start_waveform(ref, None, prioritize_selection=True)

    def _update_audio_info_labels(self, ainfo):
        """Обновляет метки «кодек/каналы» и «битрейт» под выбранную аудиодорожку
        (встроенную или внешний файл озвучки)."""
        if ainfo:
            codec_a = (ainfo.get('codec_name') or '?').upper()
            self.lbl_astream.setText(f"{codec_a} {_fmt_channels(ainfo)}")
            self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
        else:
            self.lbl_astream.setText("—")
            self.lbl_abitrate.setText("—")

    def _probe_audio_stream(self, path):
        """Возвращает первую аудиодорожку внешнего файла озвучки (для инфо-меток).
        Лёгкий ffprobe; при ошибке — None (метки покажут «—»)."""
        try:
            cmd = [FFPROBE, "-v", "error", "-select_streams", "a:0",
                   "-show_entries", "stream=codec_name,channels,bit_rate,"
                   "channel_layout:stream_tags=BPS,BPS-eng",
                   "-of", "json", str(path)]
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=CREATE_NO_WINDOW, timeout=15)
            if r.returncode == 0:
                data = json.loads(r.stdout or "{}")
                streams = data.get('streams') or []
                if streams:
                    return streams[0]
        except Exception:
            pass
        return None

    # ── Внешняя озвучка (отдельный аудиофайл, синхронный с видео) ──────────────
    _SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')
    _AUDIO_EXTS = ('.mp3', '.aac', '.m4a', '.ac3', '.eac3', '.flac', '.wav',
                   '.opus', '.ogg', '.dts', '.mka', '.wma')

    def _ensure_ext_audio_player(self):
        if self._ext_audio_player is None:
            self._ext_audio_player = QMediaPlayer()
            self._ext_audio_output = QAudioOutput()
            self._ext_audio_player.setAudioOutput(self._ext_audio_output)
            self._ext_audio_player.mediaStatusChanged.connect(
                self._on_ext_audio_status)
        return self._ext_audio_player

    def _set_external_audio(self, path):
        if not path or not os.path.exists(path):
            return
        p = self._ensure_ext_audio_player()
        try:
            self.audio_output.setMuted(True)   # глушим звук видео
        except Exception:
            pass
        try:
            self._ext_audio_output.setVolume(self.vol_slider.value() / 100.0)
        except Exception:
            pass
        self._ext_audio_active = True
        p.setSource(QUrl.fromLocalFile(str(path)))
        # Точную синхронизацию делаем по событию загрузки (_on_ext_audio_status).

    def _on_ext_audio_status(self, status):
        if not self._ext_audio_active or self._ext_audio_player is None:
            return
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            try:
                self._ext_audio_player.setPosition(self.player.position())
                if (self.player.playbackState()
                        == QMediaPlayer.PlaybackState.PlayingState):
                    self._ext_audio_player.play()
                else:
                    self._ext_audio_player.pause()
            except Exception:
                pass

    def _ext_audio_seek(self, ms):
        if self._ext_audio_active and self._ext_audio_player is not None:
            try:
                self._ext_audio_player.setPosition(int(max(0, ms)))
            except Exception:
                pass

    def _ext_audio_set_state(self, playing):
        if not self._ext_audio_active or self._ext_audio_player is None:
            return
        try:
            self._ext_audio_player.setPosition(self.player.position())
            if playing:
                self._ext_audio_player.play()
            else:
                self._ext_audio_player.pause()
        except Exception:
            pass

    def _clear_external_audio(self):
        if not getattr(self, "_ext_audio_active", False):
            return
        self._ext_audio_active = False
        p = self._ext_audio_player
        if p is not None:
            try: p.pause()
            except Exception: pass
            try: p.setSource(QUrl())
            except Exception: pass
        try:
            self.audio_output.setMuted(False)
        except Exception:
            pass

    # Типовые названия папок с субтитрами — подпапка с таким именем считается
    # «своей» для видео даже если её имя не перекликается со стемом файла.
    _SUB_FOLDER_NAMES = {'subs', 'sub', 'subtitles', 'subtitle', 'ass', 'srt',
                          'субтитры', 'сабы'}

    @classmethod
    def _path_relates_to_stem(cls, rel_dir, stem):
        """True, если относительный путь подпапки (от папки видео) похож на
        подпапку ИМЕННО этого фильма/серии — по имени сегмента пути или по
        типовому названию папки субтитров. Не считаем «своей» произвольную
        подпапку общего каталога с раздачами — см. _scan_external_subs."""
        if not rel_dir:
            return True
        for seg in rel_dir.replace('\\', '/').split('/'):
            seg_l = seg.lower()
            if seg_l in cls._SUB_FOLDER_NAMES:
                return True
            if stem and (stem in seg_l or seg_l in stem):
                return True
        return False

    def _scan_external_subs(self, src, expanded=False):
        """Ищет внешние файлы субтитров рядом с видео и в подпапках (до 3
        уровней). По умолчанию (expanded=False) включает только «свои»:
        файлы прямо в папке видео + файлы в подпапках самого фильма/серии
        (см. _path_relates_to_stem) — иначе общая папка с чужими раздачами
        (шрифты/сабы десятков разных тайтлов лежат рядом) засоряла список
        посторонними файлами. Отфильтрованные складываются в
        self._sub_ext_hidden — доступны через пункт «Показать другие файлы»
        в списке дорожек (см. _expand_external_subs)."""
        found, hidden = [], []
        try:
            base = os.path.dirname(str(src))
            if not base or not os.path.isdir(base):
                self._sub_ext_hidden = []
                return []
            stem = os.path.splitext(os.path.basename(str(src)))[0].lower()
            for root, dirs, files in os.walk(base):
                rel_dir = root[len(base):].lstrip(os.sep)
                depth = rel_dir.count(os.sep) + (1 if rel_dir else 0)
                if depth >= 3:
                    dirs[:] = []
                related = expanded or self._path_relates_to_stem(rel_dir, stem)
                for fn in files:
                    if os.path.splitext(fn)[1].lower() in self._SUB_EXTS:
                        p = os.path.join(root, fn)
                        (found if related else hidden).append(p)
                        if len(found) + len(hidden) >= 500:
                            self._sub_ext_hidden = self._sort_external_subs(hidden, src)
                            return self._sort_external_subs(found, src)
        except Exception:
            pass
        self._sub_ext_hidden = self._sort_external_subs(hidden, src)
        return self._sort_external_subs(found, src)

    def _expand_external_subs(self):
        """«Показать другие файлы» — досыпает в cmb_subs файлы, отфильтрованные
        _scan_external_subs как не относящиеся к этому фильму/серии."""
        hidden = getattr(self, "_sub_ext_hidden", None)
        if not hidden:
            return
        self._sub_ext_hidden = []
        for p in hidden:
            if p not in self._sub_ext:
                self._sub_ext.append(p)
        self._populate_track_combos_subs_only()

    def _populate_track_combos_subs_only(self):
        """Перестраивает только cmb_subs (список дорожек субтитров), не трогая
        аудио/сброс текущего показа — используется _expand_external_subs, чтобы
        клик «Показать другие файлы» не гасил уже выбранную дорожку."""
        cur_kind_ref = (self._sub_entries[self.cmb_subs.currentIndex() - 1]
                        if self.cmb_subs.currentIndex() > 0 else None)
        self._loading_tracks = True
        try:
            self.cmb_subs.clear()
            self.cmb_subs.addItem("Выкл")
            self._sub_entries = []
            for i, s in enumerate(self._sub_streams):
                self.cmb_subs.addItem(self._track_label(s, i, "Субтитры", total=len(self._sub_streams)))
                self._sub_entries.append(('emb', i))
            for p in self._sub_ext:
                self.cmb_subs.addItem(get_icon('fa5s.file'), os.path.basename(p))
                self._sub_entries.append(('ext', p))
            if getattr(self, "_sub_ext_hidden", None):
                self.cmb_subs.addItem(get_icon('fa5s.folder-open'),
                                       f"Показать другие файлы в папке… ({len(self._sub_ext_hidden)})")
                self._sub_entries.append(('more', None))
            self.cmb_subs.setEnabled(len(self._sub_entries) > 0)
            if cur_kind_ref is not None and cur_kind_ref in self._sub_entries:
                self.cmb_subs.setCurrentIndex(self._sub_entries.index(cur_kind_ref) + 1)
        finally:
            self._loading_tracks = False

    @staticmethod
    def _sort_external_subs(paths, src):
        stem = os.path.splitext(os.path.basename(str(src)))[0].lower()

        def key(p):
            name = os.path.splitext(os.path.basename(p))[0].lower()
            match = 0 if (stem and (stem in name or name in stem)) else 1
            return (match, os.path.basename(p).lower())

        return sorted(dict.fromkeys(paths), key=key)

    # ── Кнопки «найти» (внешние аудио/субтитры с ПК) ──────────────────────────
    def find_external_subs(self):
        if not self.actual_source_file:
            return
        start = str(self.actual_source_file.parent)
        fname, _ = QFileDialog.getOpenFileName(
            self, "Выбрать файл субтитров", start,
            "Субтитры (*.srt *.ass *.ssa *.vtt *.sub);;Все файлы (*)")
        if fname:
            self._add_external_sub(os.path.normpath(fname))

    def find_external_audio(self):
        if not self.actual_source_file:
            return
        start = str(self.actual_source_file.parent)
        fname, _ = QFileDialog.getOpenFileName(
            self, "Выбрать аудиофайл (озвучку)", start,
            "Аудио (*.mp3 *.aac *.m4a *.ac3 *.eac3 *.flac *.wav *.opus *.ogg "
            "*.dts *.mka *.wma);;Все файлы (*)")
        if fname:
            self._add_external_audio(os.path.normpath(fname))

    def _add_external_sub(self, path):
        target = ('ext', path)
        if path not in self._sub_ext:
            self._sub_ext.append(path)
            self._loading_tracks = True
            # «Показать другие файлы…», если есть, всегда должен остаться
            # последним пунктом списка — новую дорожку вставляем ПЕРЕД ним,
            # а не просто в конец (иначе выбор «Показать другие» смещался бы).
            more_at = next((i for i, e in enumerate(self._sub_entries)
                            if e[0] == 'more'), None)
            if more_at is None:
                self._sub_entries.append(target)
                self.cmb_subs.addItem(get_icon('fa5s.file'), os.path.basename(path))
            else:
                self._sub_entries.insert(more_at, target)
                self.cmb_subs.insertItem(more_at + 1, get_icon('fa5s.file'),
                                          os.path.basename(path))
            self.cmb_subs.setEnabled(True)
            self._loading_tracks = False
        try:
            idx = self._sub_entries.index(target) + 1   # +1: пункт 0 = «Выкл»
        except ValueError:
            return
        if self.cmb_subs.currentIndex() == idx:
            self.on_sub_track_changed(idx)
        else:
            self.cmb_subs.setCurrentIndex(idx)

    # ── Правка текста субтитров ──────────────────────────────────────────────
    @staticmethod
    def _cues_to_srt(cues):
        def _ts(t):
            if t < 0:
                t = 0.0
            h = int(t // 3600); m = int((t % 3600) // 60); s = t - h * 3600 - m * 60
            return f"{h:02d}:{m:02d}:{s:06.3f}".replace('.', ',')
        out = []
        for i, (start, end, body) in enumerate(cues, 1):
            out.append(str(i))
            out.append(f"{_ts(start)} --> {_ts(end)}")
            out.append(body)
            out.append("")
        return "\n".join(out)

    def _current_subs_as_srt(self):
        """Текст активной дорожки субтитров в виде SRT для редактора. Если cues уже
        разобраны (текстовая дорожка) — берём их; иначе (ASS/ещё грузится) —
        извлекаем SRT из источника синхронно. None — текст недоступен (битмап)."""
        if getattr(self, "_sub_cues", None):
            return self._cues_to_srt(self._sub_cues)
        src = getattr(self, "_cur_sub_src", None)
        idx = getattr(self, "_cur_sub_index", -1)
        if getattr(self, "selected_sub_ext_path", None):
            src = self.selected_sub_ext_path; idx = 0
        if not src or idx is None or idx < 0:
            return None
        tmp = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
            kw = {'creationflags': CREATE_NO_WINDOW} if os.name == 'nt' else {}
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, **kw)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
        except Exception:
            return None
        finally:
            if tmp:
                try: os.remove(tmp)
                except Exception: pass
        return None

    def _extract_srt_for_entry(self, kind, ref):
        """Текст произвольной дорожки (self._sub_entries) в виде SRT — не
        трогает текущий выбор в cmb_subs/состояние плеера, в отличие от
        _current_subs_as_srt (та работает только с АКТИВНОЙ дорожкой). Нужен
        для «Создать субтитры» → «Редактировать существующую», где дорожка,
        которую правит пользователь, может отличаться от активной."""
        if kind == 'emb':
            src, idx = self.actual_source_file, ref
        else:
            src, idx = ref, 0
            if str(ref).lower().endswith('.srt'):
                try:
                    with open(ref, 'r', encoding='utf-8', errors='replace') as f:
                        return f.read()
                except Exception:
                    pass
        if not src:
            return None
        tmp = None
        try:
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".srt")
            tmp = tf.name; tf.close()
            cmd = [FFMPEG, "-y", "-i", str(src), "-map", f"0:s:{idx}", tmp]
            kw = {'creationflags': CREATE_NO_WINDOW} if os.name == 'nt' else {}
            subprocess.run(cmd, stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, timeout=60, **kw)
            if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                with open(tmp, 'r', encoding='utf-8', errors='replace') as f:
                    return f.read()
        except Exception:
            return None
        finally:
            if tmp:
                try: os.remove(tmp)
                except Exception: pass
        return None

    def edit_subtitles(self):
        if self.cmb_subs.currentIndex() <= 0:
            msgbox_information(self, "Субтитры",
                                    "Сначала выберите дорожку субтитров.")
            return
        srt = self._current_subs_as_srt()
        if not srt or not srt.strip():
            msgbox_information(
                self, "Субтитры",
                "Не удалось получить текст субтитров для редактирования "
                "(возможно, это субтитры-картинки).")
            return
        try:
            cur_t = self.player.position() / 1000.0
        except Exception:
            cur_t = None
        dlg = SubtitleEditDialog(srt, self, current_time_s=cur_t)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_text = dlg.text()
        if not _parse_srt(new_text):
            msgbox_warning(self, "Субтитры",
                                "После правки не осталось ни одной реплики.")
            return
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            base = self.actual_source_file.stem if self.actual_source_file else "subs"
            path = os.path.join(CONFIG_DIR, f"{base}_edited.srt")
            n = 1
            while os.path.exists(path) and os.path.normpath(path) not in self._sub_ext:
                path = os.path.join(CONFIG_DIR, f"{base}_edited_{n}.srt"); n += 1
            with open(path, 'w', encoding='utf-8') as f:
                f.write(new_text if new_text.endswith("\n") else new_text + "\n")
        except Exception as e:
            msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
            return
        path = os.path.normpath(path)
        # Делаем отредактированный файл активной дорожкой (превью + вшивание).
        if path in self._sub_ext:
            self._sub_cues = []
            try:
                idx = self._sub_entries.index(('ext', path)) + 1
            except ValueError:
                self._add_external_sub(path); return
            if self.cmb_subs.currentIndex() == idx:
                self.on_sub_track_changed(idx)
            else:
                self.cmb_subs.setCurrentIndex(idx)
        else:
            self._add_external_sub(path)

    def create_subtitles(self):
        """«Создать субтитры»: диалог с репликами (текст+тайминг) и позицией на
        экране. Если в Монтаже сейчас выбрана дорожка субтитров (cmb_subs) —
        сразу редактируем ЕЁ (без лишнего диалога-выбора — раньше он всплывал
        каждый раз и раздражал); если ничего не выбрано — начинаем с чистого
        листа. Результат — новый .ass, добавляется как внешняя дорожка (та же
        логика, что и для отредактированного файла в edit_subtitles)."""
        if not self.actual_source_file and not getattr(self, "is_still_image", False):
            msgbox_information(self, "Субтитры", "Сначала откройте видео.")
            return
        # Пока пересобирается прокси (смена качества предпросмотра), self.filepath
        # на мгновение указывает на уже удалённый временный файл (см.
        # _on_pb_quality_changed) — второй плеер диалога открыл бы то, чего нет.
        if self.proxy_thread and self.proxy_thread.isRunning():
            msgbox_information(self, "Субтитры",
                               "Дождитесь подготовки превью и повторите.")
            return
        cues_arg = None
        idx = self.cmb_subs.currentIndex()
        if 0 < idx <= len(self._sub_entries):
            kind, ref = self._sub_entries[idx - 1]
            if kind != 'more':
                srt = self._extract_srt_for_entry(kind, ref)
                cues_arg = _parse_srt(srt) if srt else None
                if not cues_arg:
                    msgbox_warning(
                        self, "Субтитры",
                        "Не удалось получить текст этой дорожки для "
                        "редактирования (возможно, это субтитры-картинки).")
                    return
        # Диапазон — ровно та обрезка, что выделена в Монтаже (current_in/
        # current_out), а не всё видео целиком: превью/таймлайн диалога
        # показывают только его.
        range_start = self.current_in
        range_end = self.current_out if self.current_out > range_start else None
        start_hint = range_start
        try:
            pos = self.player.position() / 1000.0
            if range_end is not None:
                start_hint = max(range_start, min(pos, range_end))
            else:
                start_hint = max(range_start, pos)
        except Exception:
            pass
        # self.filepath — РЕАЛЬНО проигрываемый файл (== actual_source_file, либо
        # H.264-прокси для AV1/пониженного качества, см. create_proxy_for_preview) —
        # тот же путь, что и в основном плеере Монтажа. Диалог держит СВОЙ, второй
        # независимый QMediaPlayer (см. _SubtitlePreview) — если скормить ему сырой
        # AV1-исходник напрямую, QtMultimedia молча не отдаёт ни одного кадра
        # (ровно то, ради чего в самом Монтаже и строится прокси).
        source_path = (self.filepath or self.actual_source_file
                       or getattr(self, "still_image_path", None))
        partial_proxy = bool(getattr(self, "is_proxy_active", False)
                             and getattr(self, "_proxy_partial", False))
        # Звук превью — та же дорожка, что выбрана в Монтаже (cmb_audio), а не
        # дефолтная первая дорожка файла (была жалоба на именно это).
        audio_track_index, audio_ext_path = None, None
        ext_path = getattr(self, "selected_audio_ext_path", None)
        if ext_path:
            audio_ext_path = ext_path
        else:
            aidx = self.cmb_audio.currentIndex()
            if 0 <= aidx < len(self._audio_entries):
                kind, ref = self._audio_entries[aidx]
                if kind == 'emb':
                    audio_track_index = ref
        dlg = SubtitleCreatorDialog(source_path=source_path, cues=cues_arg,
                                    start_hint=start_hint,
                                    range_start=range_start, range_end=range_end,
                                    ignore_media_duration=partial_proxy,
                                    default_style=getattr(self, '_last_subtitle_style', None),
                                    audio_track_index=audio_track_index,
                                    audio_ext_path=audio_ext_path,
                                    parent=self)
        # Диалог декодирует ТОТ ЖЕ файл вторым, независимым QMediaPlayer — на
        # некоторых GPU аппаратный декодер (d3d11va/dxva2, см. video_hw_decode)
        # держит лимит одновременных сессий на кодек, и второй сеанс тогда
        # молча не получает ни одного видеокадра (аудио/позиция при этом
        # тикают нормально — подтверждено логом watchdog'а: NoError, позиция и
        # BufferedMedia в порядке, а кадра нет). stop() освобождает декодер
        # плеера Монтажа на время диалога, не трогая источник/дорожки —
        # позиция и воспроизведение восстанавливаются простым seek()'ом после.
        was_playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        resume_pos_ms = self.player.position()
        self.player.stop()
        try:
            result = dlg.exec()
        finally:
            try:
                self.player.setPosition(resume_pos_ms)
                if was_playing:
                    self.player.play()
            except Exception:
                pass
        if result != QDialog.DialogCode.Accepted:
            return
        # Запоминаем стиль (шрифт/размер/цвет/…), которым закончил работу
        # пользователь — следующее открытие «Создать субтитры» стартует с него
        # (см. default_style выше и save_settings/load_settings).
        try:
            self._last_subtitle_style = dlg.last_style()
            self.save_settings()
        except Exception:
            pass
        cues = dlg.cues()
        if not cues:
            return
        ass_text = _cues_to_ass(cues)
        try:
            os.makedirs(CONFIG_DIR, exist_ok=True)
            base = self.actual_source_file.stem if self.actual_source_file else "subs"
            path = os.path.join(CONFIG_DIR, f"{base}_created.ass")
            n = 1
            while os.path.exists(path) and os.path.normpath(path) not in self._sub_ext:
                path = os.path.join(CONFIG_DIR, f"{base}_created_{n}.ass"); n += 1
            with open(path, 'w', encoding='utf-8') as f:
                f.write(ass_text)
        except Exception as e:
            msgbox_warning(self, "Субтитры", f"Не удалось сохранить: {e}")
            return
        self._add_external_sub(os.path.normpath(path))

    def _add_external_audio(self, path):
        target = ('ext', path)
        if path not in self._audio_ext:
            self._audio_ext.append(path)
            self._loading_tracks = True
            # Убираем плейсхолдер «— нет —», если до этого дорожек не было.
            if not self._audio_entries:
                self.cmb_audio.clear()
            self._audio_entries.append(target)
            self.cmb_audio.addItem(get_icon('fa5s.file'), os.path.basename(path))
            self.cmb_audio.setEnabled(len(self._audio_entries) > 1)
            self._loading_tracks = False
        try:
            idx = self._audio_entries.index(target)
        except ValueError:
            return
        if self.cmb_audio.currentIndex() == idx:
            self.on_audio_track_changed(idx)
        else:
            self.cmb_audio.setCurrentIndex(idx)

    # Битмап-субтитры (картинками) свой оверлей рисовать не умеет — для них
    # оставляем встроенный рендер QtMultimedia.
    _BITMAP_SUB_CODECS = {
        'hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub',
        'dvb_subtitle', 'dvbsub', 'xsub',
    }

    def _ensure_overlay(self):
        """Лениво создаёт окно-оверлей субтитров и подписывается на Move/Resize
        верхнеуровневого окна (чтобы оверлей следовал за видео)."""
        if self.sub_overlay is None:
            self.sub_overlay = SubtitleOverlay(self.window())
            win = self.window()
            if win is not None and win is not self._overlay_win:
                try:
                    win.installEventFilter(self)
                    self._overlay_win = win
                except Exception:
                    pass
            # Подписки на состояние приложения/фокус окна — ОДИН раз за жизнь
            # вкладки (оверлей может пересоздаваться при смене метода субтитров).
            if not getattr(self, "_overlay_signals_connected", False):
                self._overlay_signals_connected = True
                # Окно поверх всех → прячем, когда приложение неактивно, чтобы текст
                # субтитров не висел поверх других программ при Alt+Tab.
                try:
                    QApplication.instance().applicationStateChanged.connect(
                        self._on_app_state_changed)
                except Exception:
                    pass
                # …и когда активно другое окно приложения (диалог настроек/консоль
                # и т.п.) — иначе субтитры висят поверх него.
                try:
                    QApplication.instance().focusWindowChanged.connect(
                        self._on_focus_window_changed)
                except Exception:
                    pass
        return self.sub_overlay

    def _on_focus_window_changed(self, *args):
        self._position_overlay()

    def _on_app_state_changed(self, state):
        if self.sub_overlay is None:
            return
        if state == Qt.ApplicationState.ApplicationActive:
            self._position_overlay()
        else:
            self.sub_overlay.hide()

    def _position_overlay(self):
        """Подгоняет окно-оверлей под текущую область видео (в окне или в
        полноэкранном режиме) и показывает/прячет его.
        В frame-режиме окна-оверлея нет — субтитры рисует сам холст; здесь лишь
        перерисовываем кадр ASS при изменении геометрии."""
        if self._subs_in_frame:
            if self._sub_use_ass and self._ass is not None:
                try: self._update_subtitle(self.player.position() / 1000.0)
                except Exception: pass
            return
        ov = self.sub_overlay
        if ov is None:
            return
        fs = getattr(self, "_fs_window", None)
        if not self._sub_use_overlay or not self.isVisible():
            ov.hide()
            return
        # Если активно другое окно приложения (диалог настроек/консоль и т.п.) —
        # прячем оверлей, чтобы субтитры не висели поверх него.
        try:
            aw = QApplication.activeWindow()
            allowed = {self.window(), fs}
            if aw is not None and aw not in allowed:
                ov.hide()
                return
        except Exception:
            pass
        target = (fs._video if (fs is not None and getattr(fs, "_video", None) is not None)
                  else self.video_widget)
        # Оверлей субтитров — отдельное окно «поверх всех»; его владельцем должно
        # быть то окно, где сейчас видео. Иначе при показе оверлея в полноэкранном
        # режиме Windows вытягивает вперёд окно-владельца (главное окно) и его GUI
        # оказывается поверх видео. Привязываем владельца к текущему окну видео.
        self._reparent_overlay(target.window())
        ov.place_over(target)
        # ASS: подгоняем разрешение рендера под размер оверлея и перерисовываем.
        if self._sub_use_ass and self._ass is not None:
            try:
                self._ass.set_frame_size(ov.width(), ov.height())
                self._update_subtitle(self.player.position() / 1000.0)
            except Exception:
                pass
        if not ov.isVisible():
            ov.show()
        ov.raise_()

    def _reparent_overlay(self, owner):
        ov = self.sub_overlay
        if ov is None or owner is None or ov.parent() is owner:
            return
        try:
            flags = ov.windowFlags()
            vis = ov.isVisible()
            ov.setParent(owner, flags)
            ov.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
            ov.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
            ov.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
            ov.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
            if vis:
                ov.show()
        except Exception:
            pass

    def on_sub_track_changed(self, idx):
        if self._loading_tracks:
            return
        # Пункт «Показать другие файлы…» — не дорожка, а команда: досыпать
        # отфильтрованные файлы в список и остаться на прежнем выборе (см.
        # _expand_external_subs / _populate_track_combos_subs_only).
        if 0 < idx <= len(self._sub_entries) and self._sub_entries[idx - 1][0] == 'more':
            self._expand_external_subs()
            return
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()
        self.selected_sub_ext_path = None

        # Пункт 0 = «Выкл» → субтитры выключены.
        if idx <= 0 or (idx - 1) >= len(self._sub_entries):
            try: self.player.setActiveSubtitleTrack(-1)
            except Exception: pass
            return

        kind, ref = self._sub_entries[idx - 1]
        if kind == 'emb':
            sub_i = ref
            src = self.actual_source_file
            try:
                codec = (self._sub_streams[sub_i].get('codec_name') or '').lower()
            except Exception:
                codec = ''
        else:
            # Внешний файл субтитров: извлекаем/рендерим прямо из него (stream 0).
            self.selected_sub_ext_path = ref
            sub_i = 0
            src = ref
            codec = os.path.splitext(ref)[1].lower().lstrip('.')

        is_bitmap = codec in self._BITMAP_SUB_CODECS
        if is_bitmap or not src:
            # Битмап-дорожка (или нет источника) → встроенный рендер. Для внешних
            # файлов битмап-кодеков нет, поэтому это только встроенные дорожки.
            if kind == 'emb':
                try: self.player.setActiveSubtitleTrack(sub_i)
                except Exception: pass
            return

        # Текстовые субтитры → свой рендер; встроенный (с плашкой) гасим.
        try: self.player.setActiveSubtitleTrack(-1)
        except Exception: pass
        self._sub_use_overlay = True
        self._prepare_sub_display()
        self._sub_token += 1
        tok = self._sub_token
        # Запоминаем источник субтитров (для отката ASS→SRT в _on_ass_extracted).
        self._cur_sub_src = src
        self._cur_sub_index = sub_i

        if LIBASS_AVAILABLE and codec in ('ass', 'ssa'):
            # ASS/SSA → полный стиль и караоке через libass (рендер в фоне после
            # извлечения дорожки в .ass; при неудаче — откат на текстовый SRT).
            ex = AssExtractor(src, sub_i, tok)
            ex.done.connect(self._on_ass_extracted)
            ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                if e in self._sub_threads else None)
            self._sub_threads.append(ex)
            self._ass_extractor = ex
            ex.start()
            return

        # Прочие текстовые дорожки (srt/mov_text/webvtt) → чистый текст-оверлей.
        ex = SubtitleExtractor(src, sub_i, tok)
        ex.done.connect(self._on_sub_cues)
        ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                            if e in self._sub_threads else None)
        self._sub_threads.append(ex)
        self._sub_extractor = ex
        ex.start()

    def _stop_sub_extractor(self):
        ex = getattr(self, "_sub_extractor", None)
        if ex is not None:
            try:
                ex.done.disconnect()
            except Exception:
                pass
            self._sub_extractor = None

    def _stop_ass(self):
        """Останавливает ASS-рендер: таймер, libass, временный .ass и картинку."""
        self._sub_use_ass = False
        ex = getattr(self, "_ass_extractor", None)
        if ex is not None:
            try: ex.done.disconnect()
            except Exception: pass
            self._ass_extractor = None
        t = getattr(self, "_ass_timer", None)
        if t is not None:
            try: t.stop()
            except Exception: pass
        if getattr(self, "_ass", None) is not None:
            try: self._ass.close()
            except Exception: pass
            self._ass = None
        if getattr(self, "_ass_path", None):
            try: os.remove(self._ass_path)
            except Exception: pass
            self._ass_path = None
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_subtitle_image(None)
        ov = getattr(self, "sub_overlay", None)
        if ov is not None:
            ov.set_image(None)

    def _ensure_ass_timer(self):
        if self._ass_timer is None:
            t = QTimer(self)
            t.setInterval(60)   # ~16 к/с — достаточно для плавного караоке
            t.timeout.connect(self._on_ass_tick)
            self._ass_timer = t
        if not self._ass_timer.isActive():
            self._ass_timer.start()

    def _on_ass_tick(self):
        if not self._sub_use_ass or self._ass is None:
            return
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._update_subtitle(self.player.position() / 1000.0)
        except Exception:
            pass

    def _on_ass_extracted(self, token, path):
        if token != self._sub_token:
            if path:
                try: os.remove(path)
                except Exception: pass
            return
        if not path:
            # libass-извлечение не удалось → откат на текстовый SRT-оверлей.
            self._sub_use_ass = False
            src = getattr(self, "_cur_sub_src", None) or self.actual_source_file
            sub_i = getattr(self, "_cur_sub_index", -1)
            if sub_i >= 0 and src:
                ex = SubtitleExtractor(src, sub_i, token)
                ex.done.connect(self._on_sub_cues)
                ex.finished.connect(lambda e=ex: self._sub_threads.remove(e)
                                    if e in self._sub_threads else None)
                self._sub_threads.append(ex)
                self._sub_extractor = ex
                ex.start()
            return
        try:
            self._ass = _libass.AssRenderer()
            if not self._ass.load_ass_file(path):
                raise RuntimeError("load_ass_file failed")
            self._ass_path = path
            self._sub_use_ass = True
            self._prepare_sub_display()
            self._ensure_ass_timer()
            self._update_subtitle(self.player.position() / 1000.0)
        except Exception:
            self._sub_use_ass = False
            if self._ass is not None:
                try: self._ass.close()
                except Exception: pass
                self._ass = None
            try: os.remove(path)
            except Exception: pass

    def _on_sub_cues(self, token, cues):
        if token != self._sub_token:
            return   # пришёл результат от уже неактуального выбора — игнорируем
        self._sub_cues = cues or []
        try:
            self._update_subtitle(self.player.position() / 1000.0)
        except Exception:
            pass

    def _subtitle_at(self, pos_s):
        for start, end, body in self._sub_cues:
            if start <= pos_s <= end:
                return body
            if start > pos_s:
                break
        return ""

    def _update_subtitle(self, pos_s):
        # Цель показа: сам холст (frame-режим) или окно-оверлей (overlay-режим).
        tgt = self.video_widget if self._subs_in_frame else self.sub_overlay
        if tgt is None or not hasattr(tgt, "set_subtitle_text"):
            return
        if self._sub_use_ass and self._ass is not None:
            try:
                w, h = tgt.subtitle_area_size()
            except Exception:
                return
            if w <= 0 or h <= 0:
                return
            try:
                self._ass.set_frame_size(w, h)
                arr, ax, ay, changed = self._ass.render(pos_s * 1000.0)
            except Exception:
                arr = None
                changed = True
            # libass говорит, изменилась ли картинка с прошлого рендера — если нет,
            # то, что уже на экране, всё ещё актуально: не гоняем QImage-копию и
            # перерисовку виджета впустую на каждый тик sync_ui (12.5 раз/сек).
            if not changed:
                return
            if arr is None:
                tgt.clear_subtitle()
            else:
                ih, iw = int(arr.shape[0]), int(arr.shape[1])
                qimg = QImage(arr.data, iw, ih, iw * 4,
                              QImage.Format.Format_RGBA8888_Premultiplied).copy()
                tgt.set_subtitle_image(qimg, ax, ay)
            return
        if self._sub_use_overlay:
            tgt.set_subtitle_text(self._subtitle_at(pos_s))
        # Субтитры выключены — ничего не рисуем (очистка уже сделана при смене
        # дорожки через _hide_sub_display), чтобы не дёргать перерисовку.

    def _apply_active_tracks(self, *args):
        """tracksChanged: применяет выбор из комбобоксов, когда плеер обнаружил дорожки."""
        try:
            ai = self.cmb_audio.currentIndex()
            if ai is not None and ai >= 0:
                self.player.setActiveAudioTrack(ai)
        except Exception:
            pass
        try:
            si = self.cmb_subs.currentIndex()
            self.player.setActiveSubtitleTrack((si - 1) if si is not None else -1)
        except Exception:
            pass

    # ── File loading ──────────────────────────────────────────────────────
    def open_file(self):
        fname, _ = QFileDialog.getOpenFileName(
            self, "Открыть медиа файл", "",
            "Медиа файлы (*.mp4 *.mkv *.mov *.avi *.mp3 *.aac *.wav *.flac "
            "*.png *.jpg *.jpeg *.bmp *.webp *.gif);;Все файлы (*)")
        if fname:
            self.load_file(fname)

    def clear_file(self):
        """Убирает текущий файл и возвращает редактор в исходное «пустое»
        состояние (как при запуске без файла): останавливает плеер и фоновые
        воркеры, чистит временный proxy, сбрасывает инфо/волну/тайминги."""
        # Снимок для отмены «Очистить» через Ctrl+Z: файл + текущая обрезка.
        if self.filepath:
            self._cleared_snapshot = {
                'path': str(self.filepath),
                'in': self.current_in,
                'out': self.current_out,
            }
        # Останавливаем воспроизведение.
        try:
            self.player.stop()
        except Exception:
            pass
        # Воркер волны + его временный wav.
        if self.audio_worker and self.audio_worker.isRunning():
            self.audio_worker.stop(); self.audio_worker.wait()
        if self.audio_worker:
            try:
                if self.audio_worker.tmp_wav and os.path.exists(self.audio_worker.tmp_wav):
                    os.remove(self.audio_worker.tmp_wav)
            except Exception:
                pass
            self.audio_worker = None
        # Воркер быстрого предпросмотра волны выделения (см. _start_waveform).
        if self._audio_partial_worker and self._audio_partial_worker.isRunning():
            self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
        if self._audio_partial_worker:
            try:
                if self._audio_partial_worker.tmp_wav and os.path.exists(self._audio_partial_worker.tmp_wav):
                    os.remove(self._audio_partial_worker.tmp_wav)
            except Exception:
                pass
            self._audio_partial_worker = None
        # Proxy-воркер + его временный файл.
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        self.proxy_thread = None
        if self.tmp_proxy_file and os.path.exists(self.tmp_proxy_file):
            try:
                os.remove(self.tmp_proxy_file)
            except Exception:
                pass
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        # Выгружаем источник из плеера.
        try:
            self.player.setSource(QUrl())
        except Exception:
            pass
        # Очищаем последний кадр на холсте (frame-режим).
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.clear_frame()
        # …и отпускаем покадровый слой: буфер кадров прошлого файла больше не
        # нужен, а его ffmpeg нельзя оставлять работать по удалённому источнику.
        self._grid = FrameGrid(0.0, 0.0)
        self._frame_idx = None
        if getattr(self, '_frames', None) is not None:
            self._frames.set_source(None)
        self._frames_src = None

        # Сбрасываем субтитры.
        self._stop_sub_extractor()
        self._stop_ass()
        self._sub_cues = []
        self._sub_use_overlay = False
        self._hide_sub_display()

        # Сбрасываем состояние.
        self.filepath = None
        self.actual_source_file = None
        self.duration = 0.0
        self.current_in = 0.0
        self.current_out = 0.0
        self.fps = None
        self.video_aspect = None
        self.video_stream_index = None
        self.audio_stream_index = None
        # Сбрасываем режим картинки и возвращаем подпись кнопки экспорта.
        if getattr(self, "is_still_image", False):
            try:
                self.btn_cut.setText("Обрезать")
                self.btn_cut.setIcon(get_icon('fa5s.cut', color='#1e1e2e'))
            except Exception:
                pass
        self.is_still_image = False
        self.still_image_path = None
        # Снимаем пикселизацию вместе с очисткой файла.
        self._pixelize_active = False
        _pb = getattr(self, "btn_pixelize", None)
        if _pb is not None and _pb.isChecked():
            _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
        self._sync_pixelize_icon()
        # Наложенные картинки — тоже строго «на файл»: следующий клип начинается
        # без чужих слоёв (иначе экспорт молча вшил бы логотип с прошлого видео).
        self._clear_image_overlays()
        self.selected_audio_abs_index = None
        self._clear_external_audio()
        self._audio_streams = []
        self._sub_streams = []
        self._audio_ext = []
        self._sub_ext = []
        self.selected_audio_ext_path = None
        self.selected_sub_ext_path = None
        self.undo_stack.clear(); self.redo_stack.clear()

        # Инфо-карточка → прочерки.
        for lbl in (self.lbl_duration, self.lbl_fps, self.lbl_vstream,
                    self.lbl_astream, self.lbl_abitrate):
            lbl.setText("—")

        # Подпись файла → исходный «пустой» вид (пунктирная рамка).
        self.lbl_file.setText("Нет файла")
        self.lbl_file.setToolTip("")
        self.lbl_file.setStyleSheet(f"""
            color: {C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {C['surface2']};
            border: 1px dashed {C['border2']};
            border-radius: 6px;
        """)

        # Плашка proxy / строка лога.
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
        try:
            self.log_label.setText(""); self.log_label.setVisible(False)
        except Exception:
            pass

        # Дорожки (с пустыми списками → «— нет —» / «Выкл»).
        self._populate_track_combos()
        self._update_media_buttons()
        self._update_audio_only_placeholder()

        # Поля IN/OUT + кадры + позиция плеера.
        self.in_time_edit.setText(s_to_time(0.0))
        self.out_time_edit.setText(s_to_time(0.0))
        self._set_frame_spins(0.0, 0.0)
        lbl_cur = getattr(self, "lbl_current_time", None)
        if lbl_cur is not None:
            lbl_cur.setText(s_to_time(0.0))
        try:
            self.slider.blockSignals(True); self.slider.setValue(0); self.slider.blockSignals(False)
        except Exception:
            pass

        # Волна → пустое состояние с подсказкой «Перетащите видео…».
        self.waveform.set_data([], 0.0)
        self._update_total_time()
        self.update_selection_label()

    def accept_dropped_paths(self, paths):
        """Бросок файла на заголовок вкладки «Монтаж» (см. main.eventFilter):
        грузим первый существующий файл в редактор, как обычный drop в окно."""
        for p in (paths or []):
            if p and os.path.exists(p):
                self.load_file(p)
                break

    def load_file(self, path):
        # Останавливаем воркер волны и подчищаем его временный wav (баг #7).
        if self.audio_worker and self.audio_worker.isRunning():
            self.audio_worker.stop(); self.audio_worker.wait()
        if self.audio_worker:
            try:
                if self.audio_worker.tmp_wav and os.path.exists(self.audio_worker.tmp_wav):
                    os.remove(self.audio_worker.tmp_wav)
            except Exception:
                pass
            self.audio_worker = None
        if self._audio_partial_worker and self._audio_partial_worker.isRunning():
            self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
        if self._audio_partial_worker:
            try:
                if self._audio_partial_worker.tmp_wav and os.path.exists(self._audio_partial_worker.tmp_wav):
                    os.remove(self._audio_partial_worker.tmp_wav)
            except Exception:
                pass
            self._audio_partial_worker = None

        # Останавливаем фоновый proxy-воркер ДО удаления его файла (баг #2).
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        self.proxy_thread = None

        if self.tmp_proxy_file and os.path.exists(self.tmp_proxy_file):
            try:
                os.remove(self.tmp_proxy_file)
            except Exception:
                pass
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)

        # Сбрасываем визуальные границы/обзор волны СРАЗУ при загрузке нового
        # файла — иначе красная/зелёная полоски (и окно обзора) оставались от
        # предыдущего файла, пока не догрузится новая волна.
        self.current_in = 0.0
        self.current_out = 0.0
        if getattr(self, "is_still_image", False):
            # Возврат к обычному медиа — восстанавливаем подпись кнопки экспорта.
            try:
                self.btn_cut.setText("Обрезать")
                self.btn_cut.setIcon(get_icon('fa5s.cut', color='#1e1e2e'))
            except Exception:
                pass
        self.is_still_image = False   # сбрасываем; _load_still_image выставит заново
        # Сбрасываем пикселизацию при загрузке ЛЮБОГО файла — эффект НЕ должен
        # тянуться с прошлого клипа (иначе следующий экспорт молча пикселит, хотя
        # на этом файле его «не включали»). Каждый файл начинается чистым.
        self._pixelize_active = False
        _pb = getattr(self, "btn_pixelize", None)
        if _pb is not None and _pb.isChecked():
            _pb.blockSignals(True); _pb.setChecked(False); _pb.blockSignals(False)
        self._sync_pixelize_icon()
        # Наложенные картинки — тоже строго «на файл»: следующий клип начинается
        # без чужих слоёв (иначе экспорт молча вшил бы логотип с прошлого видео).
        self._clear_image_overlays()
        self.waveform.reset_markers()
        # …и «часы кадра» холста: pts последнего показанного кадра принадлежит
        # ПРОШЛОМУ файлу. Без сброса метка времени/жёлтая полоска нового файла
        # вставали по чужому времени (у аудиофайла с обложкой кадров нет вовсе —
        # полоска намертво прилипала к концу волны, а «обрезать старт до
        # плейхеда» ставило IN/OUT в самый конец).
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.clear_frame()

        self.actual_source_file = Path(path)
        self.filepath = self.actual_source_file

        # Источник кадров для превью полосы воспроизведения (берём из исходника).
        try:
            if getattr(self, "seek_preview", None) is not None:
                self.seek_preview.set_source(self.actual_source_file)
        except Exception:
            pass

        # Сбрасываем внешнюю озвучку и пере-сканируем внешние субтитры рядом
        # с новым файлом (в т.ч. в подпапках). Списки используются при построении
        # комбобоксов в finish_loading_file → _populate_track_combos.
        self._clear_external_audio()
        self._audio_ext = []
        self._sub_ext = self._scan_external_subs(self.actual_source_file)

        name = self.actual_source_file.name
        if len(name) > 30:
            name = "…" + name[-27:]
        self.lbl_file.setText(f"{icon_html('fa5s.file', 14, C['text'])}  {name}")
        self.lbl_file.setToolTip(str(self.actual_source_file))
        self.lbl_file.setStyleSheet(f"""
            color: {C['text']};
            font-size: 11px;
            padding: 8px;
            background: {C['surface3']};
            border: 1px solid {C['border2']};
            border-radius: 6px;
        """)

        self.undo_stack = deque(maxlen=50); self.redo_stack = deque(maxlen=50)

        # Still-картинка (png/jpg/…) — отдельный лёгкий режим «картинка → видео»:
        # ни плеер, ни прокси, ни обрезка не применимы. Показываем кадр статично и
        # включаем только пикселизацию/кадрирование. Экспорт собирает видео из
        # картинки (-loop 1) при «Обрезать».
        _ext = os.path.splitext(str(path))[1].lower()
        if _ext in (".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tif", ".tiff"):
            self._load_still_image()
            return

        self.waveform.set_loading("Ожидание метаданных...")

        metadata = run_ffprobe(self.actual_source_file)
        if not metadata:
            msgbox_critical(self, "Ошибка", "Не удалось получить метаданные (ffprobe недоступен).")
            self.waveform.set_data([], 0.0)
            return

        try:
            self.duration = float(metadata.get('format', {}).get('duration', 0.0))
            self.lbl_duration.setText(s_to_time(self.duration))
        except Exception:
            self.duration = 0.0; self.lbl_duration.setText("—")
        self._update_total_time()
        # Даём волне длительность СРАЗУ (не дожидаясь построения семплов) — иначе
        # клик по полосе во время «Создание превью…»/«Загрузка волны…» сикал в 0.
        self.waveform.prime_duration(self.duration)

        vinfo, ainfo = self._pick_av_streams(metadata.get('streams', []))

        # Все аудио- и субтитровые дорожки контейнера (для выбора в боковой панели)
        self._audio_streams = [s for s in metadata.get('streams', [])
                               if s.get('codec_type') == 'audio']
        self._sub_streams = [s for s in metadata.get('streams', [])
                             if s.get('codec_type') == 'subtitle']

        if vinfo:
            self.video_stream_index = vinfo.get('index')
            is_av1 = vinfo.get('codec_name', '').lower() == 'av1'
            self._source_is_av1 = is_av1
            # Размер/FPS источника нужны для «оптимизации» превью-прокси (см.
            # _proxy_scale_for) — сохраняем, чтобы ими же пользовалась смена качества.
            try: self._src_video_h = int(vinfo.get('height') or 0)
            except Exception: self._src_video_h = 0
            self._src_video_fps = self._parse_fps(vinfo)
            scale = self._proxy_scale_for(is_av1)
            # Прокси нужен если: исходник AV1 (QtMultimedia его не тянет плавно), ИЛИ
            # выбрано пониженное качество, ИЛИ тяжёлый источник ужат под painted-режим.
            if is_av1 or scale < 0.999:
                self.create_proxy_for_preview(vinfo, ainfo, scale=scale, is_av1=is_av1); return
            self.finish_loading_file(vinfo, ainfo)
        else:
            self.finish_loading_file(None, ainfo)

    def _load_still_image(self):
        """Лёгкий режим «картинка → видео»: грузим still-картинку, показываем её
        статично на холсте и включаем только пикселизацию/кадрирование. Плеер,
        прокси, волна и обрезка видео не задействованы — экспорт собирает ролик из
        картинки (-loop 1) в _export_still_pixelize."""
        path = self.actual_source_file
        # Останавливаем плеер и снимаем источник, чтобы он не держал прошлый файл.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(QUrl())
        except Exception: pass

        img = QImage(str(path))
        if img.isNull():
            msgbox_critical(self, "Ошибка", "Не удалось открыть картинку.")
            return
        self.is_still_image = True
        self.still_image_path = Path(path)
        self._still_w, self._still_h = img.width(), img.height()
        self.video_stream_index = None     # видеопотока-для-плеера нет
        self.audio_stream_index = None
        self._audio_streams = []; self._sub_streams = []
        self._source_is_av1 = False

        # Синтетическая длительность будущего ролика (правится в диалоге пикселизации).
        self.duration = float(self._still_duration)
        self.current_in = 0.0
        self.current_out = self.duration
        try:
            self.lbl_duration.setText(s_to_time(self.duration))
            self._update_total_time()
        except Exception:
            pass

        # Показываем картинку статично; волну заменяем подсказкой.
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_static_image(img)
        try:
            self.waveform.set_data([], 0.0)
            self.waveform.set_loading(
                f"Картинка {self._still_w}×{self._still_h} — включите «Пикселизацию» "
                f"и нажмите «Обрезать», чтобы сделать видео-проявление",
                animated=False)
        except Exception:
            pass

        # Плеер для картинки не нужен — играть нечего.
        try: self.btn_play.setEnabled(False)
        except Exception: pass
        try:
            self.btn_cut.setEnabled(True)
            self.btn_cut.setText("Создать видео")
            self.btn_cut.setIcon(get_icon('fa5s.film', color='#1e1e2e'))
        except Exception:
            pass
        self._report_progress(0, "")
        self.log_label.setText(
            icon_html('fa5s.image', 12, C['text2'])
            + " Картинка загружена — включите «Пикселизацию»")
        self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
        self._update_media_buttons()

    def _pb_quality_scale(self):
        """Коэффициент масштаба прокси для текущего «качества воспроизведения».
        0 → Полное (без прокси по этой причине), 1 → 1/2, 2 → 1/4."""
        try:
            return {0: 1.0, 1: 0.5, 2: 0.25}.get(self.cmb_pb_quality.currentIndex(), 1.0)
        except Exception:
            return 1.0

    @staticmethod
    def _pick_av_streams(streams):
        """(видеопоток, аудиопоток) для плеера — первые подходящие из ffprobe.

        Обложки (attached_pic) видеопотоком НЕ считаются: см. _is_attached_pic.
        Чистая функция."""
        vinfo = None; ainfo = None
        for s in streams or []:
            if (s.get('codec_type') == 'video' and vinfo is None
                    and not _is_attached_pic(s)):
                vinfo = s
            if s.get('codec_type') == 'audio' and ainfo is None:
                ainfo = s
        return vinfo, ainfo

    @staticmethod
    def _parse_fps(vinfo):
        """FPS видеодорожки из ffprobe-словаря ('avg_frame_rate'/'r_frame_rate'
        вида 'num/den'). 0.0 — если неизвестно."""
        for key in ('avg_frame_rate', 'r_frame_rate'):
            val = (vinfo or {}).get(key) or ''
            try:
                if '/' in str(val):
                    num, den = str(val).split('/', 1)
                    den = float(den)
                    if den:
                        f = float(num) / den
                        if f > 0:
                            return f
                elif val:
                    return float(val)
            except Exception:
                pass
        return 0.0

    def _proxy_scale_for(self, is_av1):
        """Масштаб превью-прокси. По умолчанию прокси НЕ строится вообще — плеер
        играет оригинал напрямую. Исключение — исходники, которые QtMultimedia не
        тянет напрямую (сейчас это AV1): для них прокси обязателен (конвертация в
        H.264), и заодно даунскейлим его под painted-режим (VideoCanvas.toImage()
        дешевле на уменьшенном кадре — иначе на 1080p60 воспроизведение проседает
        до слайд-шоу). Обычные «тяжёлые, но поддерживаемые» источники (1080p60,
        2K/4K H.264/VP9 и т.п.) больше НЕ ужимаются автоматически — это осознанный
        выбор пользователя (жалоба на потерю качества по умолчанию), доступен через
        ручной выбор «1/2»/«1/4» в «Качество воспроизведения»."""
        user = self._pb_quality_scale()          # 1.0 / 0.5 / 0.25
        src_h = int(getattr(self, '_src_video_h', 0) or 0)
        fps = float(getattr(self, '_src_video_fps', 0.0) or 0.0)
        # 60 fps = вдвое больше кадров/с (вдвое больше toImage) → целимся в 540p,
        # иначе 720p (чуть чётче, кадров меньше).
        target = 540 if fps >= 49 else 720
        cap = 1.0
        if is_av1 and src_h > target:
            cap = target / float(src_h)
        return min(user, cap)

    def _proxy_limit_sec(self):
        """Сколько секунд исходника класть в прокси (0 = весь файл).
        Берётся из спина «Минут для прокси» в правой панели."""
        try:
            return float(self.spin_proxy_min.value()) * 60.0
        except Exception:
            return 0.0

    def create_proxy_for_preview(self, vinfo, ainfo=None, scale=1.0, is_av1=False):
        if scale < 0.999 and is_av1:
            self.log_label.setText("Подготовка превью (AV1, пониженное качество)...")
        elif scale < 0.999:
            self.log_label.setText("Подготовка превью (пониженное качество)...")
        else:
            self.log_label.setText("Подготовка AV1...")
        self._report_progress(0, "Подготовка превью…")
        self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
        tf.close(); self.tmp_proxy_file = tf.name
        self.proxy_thread = ProxyWorker(self.actual_source_file, self.tmp_proxy_file,
                                        scale=scale, duration=getattr(self, 'duration', 0.0),
                                        limit_sec=self._proxy_limit_sec())
        self._proxy_is_av1 = is_av1; self._proxy_scale = scale
        self._proxy_partial = self._proxy_limit_sec() > 0
        # Проценты создания прокси — в волну, рядом с «Ожидание метаданных…»
        # (так же, как «Извлечение аудио… N%» для H.264).
        self.proxy_thread.progress.connect(self.waveform.set_loading)
        self.proxy_thread.finished.connect(lambda s, m, o: self.on_proxy_ready(s, m, o, vinfo, ainfo))
        self.proxy_thread.start()

    def on_proxy_ready(self, success, msg, output_path, vinfo, ainfo):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")
        # Файл очистили, пока строился прокси — не оживляем UI удалённым файлом.
        if self.actual_source_file is None:
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            return

        if success:
            self.is_proxy_active = True
            self.filepath = Path(output_path)
            scale = getattr(self, '_proxy_scale', 1.0)
            is_av1 = getattr(self, '_proxy_is_av1', False)
            q_txt = {0.5: " 1/2", 0.25: " 1/4"}.get(scale, "")
            if is_av1 and q_txt:
                badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264,{q_txt.strip()})"
            elif is_av1:
                badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
            else:
                badge = f" ПРЕВЬЮ РЕЖИМ (качество{q_txt})"
            lim = self._proxy_limit_sec()
            if lim > 0:
                badge += f" · первые {int(round(lim / 60))} мин"
            self.lbl_proxy.setText(icon_html('fa5s.bolt', 13, C['yellow']) + badge)
            self.lbl_proxy.setVisible(True)
        elif msg != "Отменено":
            msgbox_warning(self, "Ошибка прокси", f"Не удалось создать превью: {msg}")
        # «Аудио»/«Битрейт аудио» должны показывать РЕАЛЬНЫЙ кодек исходника (напр.
        # Opus), а не превью-прокси — прокси ВСЕГДА транскодирует звук в AAC (см.
        # ProxyWorker.run, -c:a aac) ради совместимости с QtMultimedia, поэтому
        # ainfo здесь — тот же объект, что пришёл из ffprobe исходника в load_file
        # (передан через create_proxy_for_preview), а не повторный probe self.filepath.
        self.finish_loading_file(vinfo, ainfo)

    def _on_pb_quality_changed(self, _idx=None):
        """Смена «качества воспроизведения» на лету: пересобираем прокси (или
        возвращаемся к оригиналу), сохраняя позицию и состояние плеера. На экспорт
        не влияет — он всегда из self.actual_source_file."""
        src = self.actual_source_file
        if not src or not os.path.exists(str(src)):
            return
        if getattr(self, 'video_stream_index', None) is None:
            return  # без видеодорожки качество воспроизведения не применимо
        # Если прокси уже строится — отменяем, начнём заново с новым качеством.
        if self.proxy_thread and self.proxy_thread.isRunning():
            self.proxy_thread.stop(); self.proxy_thread.wait()
        try: pos = int(self.player.position())
        except Exception: pos = 0
        try:
            was_playing = (self.player.playbackState()
                           == QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            was_playing = False
        self._pb_restore = (pos, was_playing)

        is_av1 = bool(getattr(self, '_source_is_av1', False))
        scale = self._proxy_scale_for(is_av1)
        need_proxy = is_av1 or scale < 0.999

        # Освобождаем плеер от старого прокси-файла (иначе Windows его не отдаст),
        # затем удаляем временный файл.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(QUrl())
        except Exception: pass
        old_proxy = self.tmp_proxy_file
        self.tmp_proxy_file = None
        self.is_proxy_active = False
        if old_proxy and os.path.exists(old_proxy):
            try: os.remove(old_proxy)
            except Exception: pass

        if need_proxy:
            self.log_label.setText("Смена качества предпросмотра…")
            self._report_progress(0, "Качество предпросмотра…")
            self.btn_play.setEnabled(False); self.btn_cut.setEnabled(False)
            tf = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4"); tf.close()
            self.tmp_proxy_file = tf.name
            self._proxy_is_av1 = is_av1; self._proxy_scale = scale
            self.proxy_thread = ProxyWorker(src, self.tmp_proxy_file, scale=scale,
                                            duration=getattr(self, 'duration', 0.0),
                                            limit_sec=self._proxy_limit_sec())
            self._proxy_partial = self._proxy_limit_sec() > 0
            # Здесь волна уже заполнена — set_loading её стёр бы; показываем
            # прогресс создания прокси в строке лога И в общем прогрессбаре окна.
            self.proxy_thread.progress.connect(self._on_pb_proxy_progress)
            self.proxy_thread.finished.connect(self._on_pb_proxy_ready)
            self.proxy_thread.start()
        else:
            # Полное качество и не-AV1 → играем оригинал.
            self._proxy_partial = False
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            self._swap_player_source(src)

    def _on_pb_proxy_progress(self, text):
        """Прогресс пересборки прокси при смене версии качества: пишем и в строку
        лога, и в общий прогрессбар окна (вытаскиваем проценты из «…N%»)."""
        self.log_label.setText(text)
        pct = None
        if '%' in text:
            try:
                pct = int(text.rsplit('%', 1)[0].split()[-1])
            except Exception:
                pct = None
        self._report_progress(pct if pct is not None else -1,
                              text or "Создание превью…")

    def _on_pb_proxy_ready(self, success, msg, output_path):
        self.btn_play.setEnabled(True); self.btn_cut.setEnabled(True)
        self._report_progress(100); self.log_label.setText("Готово")
        # Источник могли очистить, пока строился прокси (его finished-слот в этом
        # случае приходит уже после очистки) — показывать/переключать нечего.
        if self.actual_source_file is None:
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            return
        if success and output_path and os.path.exists(output_path):
            self.is_proxy_active = True
            scale = getattr(self, '_proxy_scale', 1.0)
            is_av1 = getattr(self, '_proxy_is_av1', False)
            q_txt = {0.5: "1/2", 0.25: "1/4"}.get(scale, "")
            if is_av1 and q_txt:
                badge = f" ПРЕВЬЮ РЕЖИМ (AV1 → H.264, {q_txt})"
            elif is_av1:
                badge = " ПРЕВЬЮ РЕЖИМ (AV1 → H.264)"
            else:
                badge = f" ПРЕВЬЮ РЕЖИМ (качество {q_txt})"
            lim = self._proxy_limit_sec()
            if lim > 0:
                badge += f" · первые {int(round(lim / 60))} мин"
            self.lbl_proxy.setText(icon_html('fa5s.bolt', 13, C['yellow']) + badge)
            self.lbl_proxy.setVisible(True)
            self._swap_player_source(output_path)
        else:
            if msg != "Отменено":
                msgbox_warning(self, "Ошибка прокси",
                                    f"Не удалось создать превью: {msg}")
            self.lbl_proxy.setText(""); self.lbl_proxy.setVisible(False)
            self._swap_player_source(self.actual_source_file)

    def _swap_player_source(self, path):
        """Переключает источник плеера, сохраняя позицию/состояние из _pb_restore
        (применяются после загрузки медиа в on_media_status_changed)."""
        if path is None:
            return  # файл очистили — переключать нечего
        self.filepath = Path(path)
        self._pending_pb_seek = getattr(self, '_pb_restore', None)
        self._set_player_file(path)
        # Точные кадры обязаны браться из ТОГО ЖЕ файла, что играет плеер:
        # иначе после смены качества превью стоп-кадр остался бы от прежнего
        # источника (другое разрешение — заметный «скачок» резкости на паузе).
        self._frames_set_source()

    def _set_player_file(self, path):
        """Грузит файл в плеер через девайс с FILE_SHARE_DELETE — тогда исходник
        можно удалить из Проводника прямо во время монтажа (плеер его не держит
        намертво). Если девайс открыть не удалось — обычная загрузка по URL."""
        path = str(path)
        old = getattr(self, '_play_device', None)
        dev = ShareDeleteIODevice(path)
        opened = False
        try:
            opened = dev.open()
        except Exception:
            opened = False
        try:
            if opened:
                self._play_device = dev
                self.player.setSourceDevice(dev, QUrl.fromLocalFile(path))
            else:
                self._play_device = None
                self.player.setSource(QUrl.fromLocalFile(path))
        except Exception:
            self._play_device = None
            try:
                self.player.setSource(QUrl.fromLocalFile(path))
            except Exception:
                pass
        # Старый девайс закрываем чуть позже — плеер уже переключился на новый.
        if old is not None and old is not dev:
            QTimer.singleShot(0, lambda d=old: self._close_play_device(d))

    def _close_play_device(self, dev):
        try:
            dev.close()
        except Exception:
            pass

    def finish_loading_file(self, vinfo, ainfo):
        if vinfo:
            r = vinfo.get('r_frame_rate') or vinfo.get('avg_frame_rate') or "0/1"
            try:
                num, den = r.split('/')
                fps = float(num) / float(den) if float(den) != 0 else 0.0
                self.fps = fps if fps > 0 else None
            except Exception:
                self.fps = None
            w = vinfo.get('width', '?'); h = vinfo.get('height', '?')
            codec = vinfo.get('codec_name', '?').upper()
            self.lbl_vstream.setText(f"{codec} {w}×{h}")
            try:
                wv = int(vinfo.get('width') or 0); hv = int(vinfo.get('height') or 0)
                self.video_aspect = (wv / hv) if (wv > 0 and hv > 0) else None
            except Exception:
                self.video_aspect = None
        else:
            self.video_stream_index = None; self.fps = None
            self.video_aspect = None
            self.lbl_vstream.setText("—")

        if ainfo:
            self.audio_stream_index = ainfo.get('index')
            codec_a = ainfo.get('codec_name', '?').upper()
            self.lbl_astream.setText(f"{codec_a} {_fmt_channels(ainfo)}")
            self.lbl_abitrate.setText(self._fmt_bitrate(ainfo))
        else:
            self.audio_stream_index = None
            self.lbl_astream.setText("—")
            self.lbl_abitrate.setText("—")

        self._populate_track_combos()
        self._update_media_buttons()
        self._update_audio_only_placeholder()
        self.lbl_fps.setText(format_fps(self.fps))
        # Покадровый слой перенастраиваем на новый клип: сетка кадров (fps +
        # длительность) и источник точных кадров — ТОТ ЖЕ файл, что уйдёт в
        # плеер (оригинал или превью-прокси, см. _frames_set_source).
        self._refresh_frame_grid()
        self._frame_idx = 0
        self._frames_set_source()

        self.undo_stack.clear(); self.redo_stack.clear()
        self.current_in = 0.0; self.current_out = max(0.001, self.duration)
        self.set_in_out(0.0, self.current_out, skip_undo=True)

        # Новый файл — сбрасываем зум/панораму превью (если активен холст-режим)
        # и снимаем предпросмотр привязки: он посчитан по ПРОШЛОМУ видео.
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.reset_view()
            self._clear_track_preview()

        self._set_player_file(self.filepath)
        self.player.setPosition(0); self.player.pause()

        self.start_waveform_loading()
        QTimer.singleShot(50, self._adjust_video_aspect_once)
        self.update_selection_label(); self.update_pan_slider_values()
        # После загрузки файла (в т.ч. через drag&drop) забираем фокус клавиатуры
        # на вкладку, чтобы Пробел/I/O/←→ работали сразу — без клика по видео.
        # singleShot(0): после того, как плеер/видеовиджет отработают своё событие.
        QTimer.singleShot(0, self._grab_kbd_focus)
        # Прогреваем отдельный плеер скраб-звука заранее (источник — оригинал).
        # Без прогрева ПЕРВЫЕ покадровые шаги часто шли без звука: плеер ещё
        # догружал медиа (а у AV1+Opus оригинала открытие/перемотка не мгновенны)
        # — отсюда баг «при av1 прокси звук при шаге по кадру появляется не всегда».
        QTimer.singleShot(0, self._prime_scrub_audio)

    def _prime_scrub_audio(self):
        """Заранее декодирует окно PCM вокруг текущей точки, чтобы ПЕРВЫЙ же
        покадровый шаг звучал сразу (окно готовится ~80 мс — на первом шаге это
        было бы слышно как «звук появляется не всегда»). Только подготовка —
        ничего не играем (тишина при загрузке файла)."""
        if not getattr(self, "_scrub_audio_enabled", True):
            return
        try:
            eng = self._sync_scrub_audio_source()
            if eng is not None:
                eng.request(max(0.0, self.player.position() / 1000.0))
            self._scrub_sink()          # поднять устройство заранее (~45 мс)
        except Exception:
            pass

    def _grab_kbd_focus(self):
        """Ставит фокус клавиатуры на вкладку «Монтаж». Хоткеи привязаны к ней с
        контекстом WidgetWithChildren — без фокуса на вкладке (или её потомке)
        Пробел и прочие не срабатывают, пока пользователь не кликнет по видео."""
        try:
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        except Exception:
            pass

    def start_waveform_loading(self):
        a_idx = self.audio_stream_index if not self.is_proxy_active else None
        self._start_waveform(self.filepath, a_idx)

    @staticmethod
    def _file_cache_stamp(path):
        """(mtime, size) файла — ключ инвалидации кэша по факту его изменения
        на диске (не просто по пути, который может указывать на подменённый файл)."""
        try:
            st = os.stat(path)
            return (st.st_mtime, st.st_size)
        except OSError:
            return None

    def _start_waveform(self, filepath, audio_index, prioritize_selection=False):
        """Запускает (или перезапускает) построение аудиоволны для конкретного
        файла и индекса дорожки. Используется и при загрузке файла, и при смене
        озвучки — тогда волна перестраивается под новую дорожку.
        prioritize_selection=True (смена аудиодорожки) — сперва запускает
        быстрый проход ТОЛЬКО по текущему выделению IN/OUT (обычно секунды),
        чтобы сразу показать/дать проверить нужный кусок, не дожидаясь полного
        прохода по всему файлу; полный проход всё равно идёт следом и
        подменяет собой предпросмотр, когда досчитается."""
        if not filepath:
            return
        self._waveform_gen = getattr(self, "_waveform_gen", 0) + 1
        gen = self._waveform_gen
        stamp = self._file_cache_stamp(filepath)
        cache_key = (str(filepath), audio_index, stamp) if stamp else None
        cached = self._waveform_cache.get(cache_key) if cache_key else None
        # Снимаем предыдущие воркеры (полный + быстрый предпросмотр выделения),
        # чтобы устаревшая волна старой дорожки не прилетела последней.
        if self.audio_worker and self.audio_worker.isRunning():
            try:
                self.audio_worker.stop(); self.audio_worker.wait()
            except Exception:
                pass
        if self._audio_partial_worker and self._audio_partial_worker.isRunning():
            try:
                self._audio_partial_worker.stop(); self._audio_partial_worker.wait()
            except Exception:
                pass
        if cached is not None:
            self._waveform_cache_key = None
            self.on_waveform_ready(gen, *cached)
            return
        self.waveform.set_loading("Загрузка волны...")
        self._waveform_cache_key = cache_key
        seg_in, seg_out = self.current_in, self.current_out
        if (prioritize_selection and self.duration > 0
                and 0 <= seg_in < seg_out <= self.duration
                and (seg_out - seg_in) < self.duration - 0.5):
            seg_worker = AudioSegmentWaveformLoader(str(filepath), audio_index,
                                                     seg_in, seg_out, self.duration)
            seg_worker.finished.connect(
                lambda samples, s_in, s_out, l, r, g=gen:
                    self.on_waveform_partial_ready(g, samples, s_in, s_out, l, r))
            self._audio_partial_worker = seg_worker
            seg_worker.start()
        self.audio_worker = AudioWaveformLoader(str(filepath), audio_index,
                                                self.duration)
        self.audio_worker.finished.connect(
            lambda samples, dur, l, r, g=gen: self.on_waveform_ready(g, samples, dur, l, r))
        self.audio_worker.progress.connect(self._on_waveform_progress)
        self.audio_worker.start()

    def _on_waveform_progress(self, text):
        # Если волна уже частично заполнена (быстрый предпросмотр выделения —
        # см. prioritize_selection), set_loading() её бы стёр; тогда прогресс
        # полного прохода пишем в строку лога вместо полосы волны.
        if self.waveform.samples:
            self.log_label.setText(text)
        else:
            self.waveform.set_loading(text)

    def on_waveform_partial_ready(self, gen, samples, seg_in, seg_out, left=None, right=None):
        if gen != getattr(self, "_waveform_gen", gen):
            return
        if not samples or self.duration <= 0:
            return
        self.waveform.set_partial_data(samples, seg_in, seg_out, self.duration, left, right)

    def on_waveform_ready(self, gen, samples, duration, left=None, right=None):
        if gen != getattr(self, "_waveform_gen", gen):
            return
        cache_key = getattr(self, "_waveform_cache_key", None)
        if cache_key is not None:
            self._waveform_cache_key = None
            self._waveform_cache[cache_key] = (samples, duration, left, right)
            if len(self._waveform_cache) > 8:
                self._waveform_cache.pop(next(iter(self._waveform_cache)))
        use_duration = self.duration if (self.duration and self.duration > 0) else duration
        if duration > 0 and use_duration < (duration - 0.05):
            use_duration = duration
        # Длительность из контейнера могла не определиться (format.duration пуст) —
        # тогда current_out осталась ~0.001, зона воспроизведения вырождена: плеер
        # сразу упирается в OUT (видео «не играется»), а в начале таймлайна слипаются
        # маркеры IN/OUT. Берём длительность из аудиоволны и раскрываем зону на всё.
        if use_duration > 0 and (self.duration <= 0 or self.current_out <= 0.002
                                 or (self.current_out - self.current_in) < 0.003):
            self.duration = use_duration
            self.lbl_duration.setText(s_to_time(self.duration))
            self.current_in = 0.0
            self.current_out = use_duration
        self._update_total_time()
        self.waveform.set_data(samples, use_duration, left, right)
        # Восстанавливаем выделение пользователя после загрузки волны
        # (waveform.set_in_out пошлёт selectionChanged → синхронизация полей/кадров).
        self.waveform.set_in_out(self.current_in, self.current_out)
        self.update_pan_slider_values()
        # Восстановление обрезки после отмены «Очистить» (Ctrl+Z) — применяем
        # ПОСЛЕ того, как длительность/волна устаканились (иначе перезатёрлась бы).
        pend = getattr(self, "_pending_restore_in_out", None)
        if pend is not None:
            self._pending_restore_in_out = None
            self.set_in_out(pend[0], pend[1], skip_undo=True)

    # ── Undo / Redo ───────────────────────────────────────────────────────
    def push_undo(self):
        state = (self.current_in, self.current_out)
        if self.undo_stack:
            li, lo = self.undo_stack[-1]
            if abs(li - state[0]) < 0.001 and abs(lo - state[1]) < 0.001:
                return
        self.undo_stack.append(state)   # deque auto-trims at maxlen=50
        self.redo_stack.clear()

    def undo(self):
        # Отмена «Очистить»: восстанавливаем выгруженный файл и его обрезку
        # (свой undo-стек был очищен вместе с файлом).
        snap = getattr(self, "_cleared_snapshot", None)
        if snap and not self.filepath:
            self._cleared_snapshot = None
            if os.path.exists(snap['path']):
                self.load_file(snap['path'])
                self._pending_restore_in_out = (snap['in'], snap['out'])
            return
        # Пропускаем «пустые» снимки, равные текущему состоянию: они появлялись,
        # когда действие не меняло in/out (напр. «Обрезать старт/конец» по кнопке,
        # когда плейхед уже стоит на границе) — push_undo всё равно клал снимок, и
        # из-за этого первый Ctrl+Z «не срабатывал» (отменял в то же состояние,
        # визуально ничего не происходило). Откатываемся до ПЕРВОГО отличающегося.
        cur = (self.current_in, self.current_out)
        while self.undo_stack:
            prev = self.undo_stack.pop()
            if abs(prev[0] - cur[0]) > 1e-4 or abs(prev[1] - cur[1]) > 1e-4:
                self.redo_stack.append(cur)
                self.set_in_out(prev[0], prev[1], skip_undo=True)
                return
            # prev == cur — это пустой снимок, отбрасываем и ищем дальше.

    def redo(self):
        cur = (self.current_in, self.current_out)
        while self.redo_stack:
            nxt = self.redo_stack.pop()
            if abs(nxt[0] - cur[0]) > 1e-4 or abs(nxt[1] - cur[1]) > 1e-4:
                self.undo_stack.append(cur)
                self.set_in_out(nxt[0], nxt[1], skip_undo=True)
                return

    # ── In / Out ──────────────────────────────────────────────────────────
    def _set_frame_spins(self, in_s, out_s):
        """Обновляет спинбоксы кадров, не вызывая valueChanged (защита от рекурсии)."""
        self.in_frame_spin.blockSignals(True)
        self.out_frame_spin.blockSignals(True)
        if self.fps and self.fps > 0:
            self.in_frame_spin.setValue(int(round(in_s * self.fps)))
            self.out_frame_spin.setValue(int(round(out_s * self.fps)))
        else:
            self.in_frame_spin.setValue(0); self.out_frame_spin.setValue(0)
        self.in_frame_spin.blockSignals(False)
        self.out_frame_spin.blockSignals(False)

    def set_in_out(self, in_s, out_s, skip_undo=False, keep_view=True):
        self.current_in  = max(0.0, min(in_s,  self.duration))
        self.current_out = max(0.0, min(out_s, self.duration))
        if self.current_out <= self.current_in:
            self.current_out = min(self.duration, self.current_in + 0.001)
        self.in_time_edit.setText(s_to_time(self.current_in))
        self.out_time_edit.setText(s_to_time(self.current_out))
        self._set_frame_spins(self.current_in, self.current_out)
        # keep_view=True по умолчанию: обрезка не перематывает окно таймлайна.
        self.waveform.set_in_out(self.current_in, self.current_out, keep_view=keep_view)
        self.update_selection_label(); self.update_pan_slider_values()
        self._update_seg_duration()

    def set_in_point(self):
        self.push_undo()
        try:
            t = time_to_s(self.in_time_edit.text())
        except Exception:
            t = self.player.position() / 1000.0
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - 0.04)
        self.set_in_out(new_in, self.current_out)

    def set_out_point(self):
        self.push_undo()
        try:
            t = time_to_s(self.out_time_edit.text())
        except Exception:
            t = self.player.position() / 1000.0
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + 0.04)
        self.set_in_out(self.current_in, new_out)

    def on_in_frame_changed(self, frame):
        if not (self.fps and self.fps > 0) or self.duration <= 0:
            return
        self.push_undo()
        t = frame / self.fps
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - (1.0 / self.fps))
        self.set_in_out(new_in, self.current_out)

    def on_out_frame_changed(self, frame):
        if not (self.fps and self.fps > 0) or self.duration <= 0:
            return
        self.push_undo()
        t = frame / self.fps
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + (1.0 / self.fps))
        self.set_in_out(self.current_in, new_out)

    def on_wave_seek(self, t):     self.seek_to(t)
    def on_wave_playseek(self, t): self.seek_to(t)

    def on_wave_selection_changed(self, new_in, new_out):
        self.current_in = new_in; self.current_out = new_out
        self.in_time_edit.setText(s_to_time(new_in))
        self.out_time_edit.setText(s_to_time(new_out))
        self._set_frame_spins(new_in, new_out)
        self.update_selection_label()
        # Двигаем красную/зелёную полоску ВО ВРЕМЯ воспроизведения → обновляем
        # границу авто-паузы painted-режима. Иначе VideoCanvas держит СТАРЫЙ OUT
        # и стопит/телепортит плеер на прежнем месте зелёной полоски (баг).
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self._set_play_bound(True)
        except Exception:
            pass

    def update_selection_label(self):
        # Показываем только итоговую длительность будущего ролика (без таймкодов
        # начала/конца — они и так есть в полях IN/OUT).
        dur = max(0.0, self.current_out - self.current_in)
        self.lbl_selection.setText(
            f"{icon_html('fa5s.stopwatch', 13, C['text'])}  Итог: {s_to_time(dur)}")

    def _resize_montage_side_btns(self, col_h):
        """Кнопки боковой панели монтажа — квадратные, в две колонки по 4 (место
        под 8 штук); сторона квадрата = высота колонки на ровно 4 ряда."""
        btns = getattr(self, "_montage_side_btns", None)
        if not btns or col_h <= 0:
            return
        rows = self._MSIDE_COUNT // 2
        avail = max(0, int(col_h) - self._MSIDE_GAP * (rows - 1))
        bh = max(24, min(40, avail // rows))
        isz = max(14, min(22, bh - 12))
        for b in btns:
            b.setFixedSize(bh, bh)
            b.setIconSize(QSize(isz, isz))

    @staticmethod
    def _relax_width(wdg):
        """Снимает минимальную «требуемую» ширину виджета (горизонтальная политика
        Ignored): он не распирает правую панель по длине своего текста, а тянется
        по доступному месту (текст при нехватке укорачивается). НЕ применять к
        меткам в строках инфо-карточек (там есть stretch — схлопнутся в 0)."""
        sp = wdg.sizePolicy()
        sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        wdg.setSizePolicy(sp)

    def _update_total_time(self):
        """Обновляет общее время в плеере (00:00 / ОБЩЕЕ под видео)."""
        lbl = getattr(self, "lbl_total_time", None)
        if lbl is not None:
            lbl.setText(s_to_time(self.duration if self.duration and self.duration > 0 else 0.0))

    # ── Playback ──────────────────────────────────────────────────────────
    def on_player_duration_changed(self, dur_ms):
        if dur_ms <= 0:
            return
        # Усечённый прокси (первые N минут) короче оригинала — НЕ даём его
        # длительности перетереть настоящую, иначе таймлайн/обрезка схлопнутся
        # до длины прокси (а резать-то надо весь файл). Истинную длительность
        # держим из ffprobe (load_file).
        if getattr(self, 'is_proxy_active', False) and getattr(self, '_proxy_partial', False):
            return
        new_dur = dur_ms / 1000.0
        # Выделение покрывало весь клип? Тогда тянем OUT к настоящей длительности.
        was_full = (self.current_out <= 0.001) or abs(self.current_out - self.duration) < 0.05
        self.duration = new_dur
        self.lbl_duration.setText(s_to_time(self.duration))
        self._update_total_time()
        # Синхронизируем current_out / waveform.out_s с новой длительностью (баг #4).
        self._refresh_frame_grid()   # у сетки кадров новый предел
        new_out = new_dur if was_full else min(self.current_out, new_dur)
        new_in  = min(self.current_in, max(0.0, new_out - 0.001))
        if abs(new_out - self.current_out) > 1e-4 or abs(new_in - self.current_in) > 1e-4:
            self.set_in_out(new_in, new_out, skip_undo=True)

    def _update_seg_duration(self, pos_s=None):
        """Обновляет метку «старт→плейхед»: длительность от IN до жёлтой полосы
        воспроизведения. Зовётся отовсюду, где двигается плейхед или меняется IN."""
        lbl = getattr(self, "lbl_seg_dur", None)
        if lbl is None:
            return
        try:
            if pos_s is None:
                pos_s = self.player.position() / 1000.0
            lbl.setText(s_to_time(max(0.0, pos_s - self.current_in)))
        except Exception:
            pass

    def on_position_changed(self, pos_ms):
        self._preroll_watch(pos_ms)        # см. _preroll_at (прогрев с разбега)
        if not getattr(self, "_prerolling", False):
            # Во время разбега позиция пробегает мимо любых целей покадрового
            # seek'а — «подтверждать» ими чужой seek нельзя.
            self._confirm_frame_seek(pos_ms)   # см. step_frame/_dispatch_frame_seek
        # Интерфейс — по мастер-часам (кадр на экране), а не по «сырой» позиции
        # плеера: иначе метка и картинка живут каждая своей жизнью, что и было
        # видно как рассинхрон метки с видео. Для аудиофайлов _clock_pos_s сам
        # возвращает позицию плеера.
        pinned_ms = self._ui_pinned_ms()
        pos_s = (pinned_ms / 1000.0) if pinned_ms is not None else self._clock_pos_s()
        self._paint_playhead(pos_s)
        self._update_meter(pos_s)
        self._update_subtitle(pos_s)

    def _update_meter(self, pos_s, force=False):
        """Кормит индикатор уровня значением аудиоволны на позиции плейхеда.
        При воспроизведении вызывается из sync_ui; `force=True` — при покадровой
        перемотке (скрабе), чтобы шкала «оживала» и на шаге, а не только на play.
        На паузе без force шкала плавно опадает сама."""
        meter = getattr(self, "audio_meter", None)
        if meter is None:
            return
        try:
            playing = (self.player.playbackState()
                       == QMediaPlayer.PlaybackState.PlayingState)
            if not playing and not force:
                return
            # level_at_lr уже нормирован по пику и перцептивен (см. WaveformWidget),
            # поэтому шкала живая и отражает реальное присутствие звука. L и R —
            # честно раздельные каналы (для моно совпадут).
            lvl_l, lvl_r = self.waveform.level_at_lr(pos_s)
            try:
                vol = max(0.0, min(1.0, float(self.audio_output.volume())))
            except Exception:
                vol = 1.0
            k = 0.25 + 0.75 * vol
            meter.set_levels(min(1.0, lvl_l * k), min(1.0, lvl_r * k))
        except Exception:
            pass

    def _effective_out_s(self):
        """Граница авто-паузы воспроизведения. Если OUT у самого конца клипа —
        останавливаемся на кадр раньше: иначе плеер доходит до EndOfMedia и
        QtMultimedia гасит поверхность в чёрный кадр (баг #9)."""
        frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
        guard = max(frame_s, 0.05)
        at_end = self.current_out >= (self.duration - 0.02)
        return (self.duration - guard) if at_end else self.current_out

    def _set_play_bound(self, active):
        """Вкл/выкл блокировку кадров за OUT в painted-режиме (анти-overshoot)."""
        vw = self.video_widget
        if not isinstance(vw, VideoCanvas):
            return
        if active and self.duration > 0:
            frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
            # граница = effective_out + полкадра: кадр НА границе ещё показываем,
            # а следующий (за ней) — блокируем и встаём на паузу.
            vw.set_play_bound(self._effective_out_s() + frame_s * 0.5)
        else:
            vw.set_play_bound(None)

    def _on_play_boundary(self):
        """Пришёл кадр за OUT (по PTS) — мгновенная пауза и снап на границу ДО
        показа кадра. Убирает проскок-и-отскок правой границы."""
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                self.player.pause()
            out_s = self._effective_out_s()
            # Кадр остановки задаём явно: иначе пауза «пришпилила» бы последний
            # ПОКАЗАННЫЙ кадр, и метка отскочила бы от границы на кадр назад.
            if self._grid.valid:
                self._frame_idx = self._grid.index_at(out_s)
            self.player.setPosition(int(out_s * 1000))
            self.lbl_current_time.setText(s_to_time(out_s))
            self.waveform.set_playhead(out_s)
            self._ext_audio_seek(int(out_s * 1000))
        except Exception:
            pass

    def sync_ui(self):
        if self.duration <= 0.1:
            return
        # Часы плеера (по сути аудио-часы) — ими проверяем границу OUT: она
        # обязана срабатывать по звуку, даже если видеокадры отстают.
        pos_s = self.player.position() / 1000.0
        # А интерфейс (метка времени, полоса, плейхед на волне, субтитры) ведём
        # по МАСТЕР-ЧАСАМ — времени кадра, который сейчас на экране. Пока плеер
        # занят служебным делом (разбег, транзиентный play скраба), часы стоят
        # на отметке пользователя — см. _ui_pinned_ms.
        pinned_ms = self._ui_pinned_ms()
        disp_s = (pinned_ms / 1000.0) if pinned_ms is not None else self._clock_pos_s()
        # Авто-пауза в конце воспроизводимого участка (резерв к покадровому
        # блоку VideoCanvas: ловит границу в overlay-режиме и как страховка).
        effective_out = self._effective_out_s()
        if effective_out > self.current_in and pos_s >= effective_out:
            self.player.pause()
            if self._grid.valid:
                self._frame_idx = self._grid.index_at(effective_out)
            self.player.setPosition(int(effective_out * 1000))
            self.lbl_current_time.setText(s_to_time(effective_out))
            self.waveform.set_playhead(effective_out)
            self._update_seg_duration(effective_out)
            return
        self._paint_playhead(disp_s)
        self._update_meter(disp_s)
        self._update_subtitle(disp_s)
        # Рассинхрон внешней озвучки. Порог опущен с 220 до 130 мс: 220 мс — это
        # уже отчётливо слышимое «эхо» относительно картинки (заметно от ~40 мс),
        # а ниже сотни ставить нельзя — каждая правка это setPosition, то есть
        # микро-заминка в звуке. Сверяемся с ЧАСАМИ ПЛЕЕРА (звук к звуку), а не с
        # часами кадра: рассинхрон двух звуковых дорожек между собой слышен, а
        # отставание рендера видео к нему отношения не имеет.
        if self._ext_audio_active and self._ext_audio_player is not None:
            try:
                if (self._ext_audio_player.playbackState()
                        == QMediaPlayer.PlaybackState.PlayingState):
                    drift = self._ext_audio_player.position() - self.player.position()
                    if abs(drift) > 130:
                        self._ext_audio_player.setPosition(self.player.position())
            except Exception:
                pass

    def on_slider_moved(self, value):
        if self.duration > 0:
            self.seek_to((value / 1000.0) * self.duration)

    def seek_to(self, t_s):
        try:
            ms = int(max(0.0, min(t_s, max(0.0, self.duration))) * 1000)
            # Идёт беззвучный разбег — гасим его ПЕРВЫМ делом. Иначе плеер
            # продолжил бы играть уже от новой отметки и уехал бы с неё.
            if getattr(self, "_prerolling", False):
                self._preroll_cancel()
            if isinstance(self.video_widget, VideoCanvas):
                self.video_widget.set_scrub_active(True)
                self._scrub_idle_timer.start()   # перезапуск — «перемотка ещё идёт»
            # Целевой кадр запоминаем сразу: от него пойдёт покадровый шаг.
            # Пин ПЕРЕВОДИМ на новый кадр тут же — без этого холст продолжал бы
            # считать «своим» кадр, где перемотка началась, и отбрасывал бы все
            # кадры плеера: картинка стояла бы всю протяжку. Точные кадры при
            # этом не заказываем (ffmpeg на каждый пиксель протяжки не нужен) —
            # но если нужный кадр уже лежит в буфере, показываем его мгновенно.
            if self._grid.valid:
                self._frame_idx = self._grid.index_at(ms / 1000.0)
                vw = getattr(self, "video_widget", None)
                if isinstance(vw, VideoCanvas):
                    span = self._grid.pts_span_us(self._frame_idx)
                    vw.arm_frame_pin(span)
                    eng = getattr(self, "_frames", None)
                    img = eng.frame(self._frame_idx) if eng is not None else None
                    if img is not None:
                        vw.set_exact_frame(
                            img, span,
                            int(self._grid.start_of(self._frame_idx) * 1_000_000))
            self.player.setPosition(ms)
            self.waveform.set_playhead(t_s)
            self._ext_audio_seek(ms)
        except Exception as e:
            self.main.log(f"seek_to error: {e}")

    def _on_scrub_idle(self):
        """Перемотка утихла (seek_to не вызывался _scrub_idle_timer.interval() мс) —
        возвращаем сглаженную отрисовку кадра в VideoCanvas."""
        if isinstance(self.video_widget, VideoCanvas):
            self.video_widget.set_scrub_active(False)
        prerolling = getattr(self, "_prerolling", False)
        playing = (self.player.playbackState()
                   == QMediaPlayer.PlaybackState.PlayingState)
        if not playing or prerolling:
            # Перемотка кончилась — ставим на холст ТОЧНЫЙ кадр этой позиции и
            # набиваем буфер соседями, чтобы первый же шаг стрелкой был мгновенным.
            # Во время прогрева («с разбега») плеер формально играет, но кадр всё
            # равно наш: пин прячет пробегающие кадры разбега.
            self._show_exact_frame(self._frame_idx)
        if not playing:
            # Окно PCM для скраб-звука — в новой точке (первый шаг после клика
            # по шкале обязан звучать сразу, см. AudioScrubber).
            self._prime_scrub_audio()
            # Греем аудио-конвейер в новой точке, пока стоим на паузе: иначе
            # первое «Воспроизвести» после перемотки начиналось с ~0.35 с тишины
            # и докрутить обрезку по слуху было нельзя (см. _preroll_at).
            self._preroll_at(self._playhead_target_s())

    def toggle_play(self):
        self._scrubbing = False   # явное play/pause не должно гаситься скрабом
        # Пользователь нажал Play в окне беззвучного прогрева: отменяем прогрев,
        # возвращаем mute и продолжаем уже как обычный запуск (плеер уже играет
        # под mute — достаточно снять mute, не дёргая позицию).
        if getattr(self, "_prerolling", False):
            self._prerolling = False
            tgt = getattr(self, "_preroll_target_ms", None)
            # Прогрев идёт «с разбега», то есть плеер сейчас может быть ЕЩЁ НЕ
            # доехавшим до отметки пользователя. Продолжить прямо отсюда значило
            # бы начать воспроизведение раньше плейхеда. Но и перематывать на
            # цель нельзя: перемотка кладёт аудио-конвейер, и звук появится
            # только через ~0.35 с (ровно тот баг, ради которого прогрев и
            # существует). Поэтому пока остаток разбега короткий — ДОИГРЫВАЕМ
            # его под mute и снимаем mute на цели (_preroll_handoff): и картинка
            # (пин точного кадра держится), и звук стартуют ровно на отметке.
            behind = 0
            try:
                behind = (int(tgt) - self.player.position()) if tgt is not None else 0
            except Exception:
                behind = 0
            if tgt is not None and 0 < behind <= self._PREROLL_HANDOFF_MS:
                self._preroll_handoff = True
                self._preroll_timer().start()
                # Страховка: разбег мог упереться в конец файла и не доехать.
                QTimer.singleShot(self._PREROLL_HANDOFF_MS + 300,
                                  self._preroll_handoff_finish)
                self.on_playback_changed(self.player.playbackState())
                return
            self._preroll_target_ms = None
            try:
                self._preroll_timer().stop()
            except Exception:
                pass
            try:
                self.audio_output.setMuted(self._preroll_prev_muted)
                # Остаток разбега длиннее порога — ждать дольше, чем стоит
                # перемотка; доводим позицию.
                if tgt is not None and behind > self._PREROLL_HANDOFF_MS:
                    self.player.setPosition(int(tgt))
            except Exception:
                pass
            self._release_frame_lock()
            self.on_playback_changed(self.player.playbackState())
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            pos_s = self.player.position() / 1000.0
            if abs(pos_s - self.current_out) < 0.15 and self.current_out > (self.current_in + 0.5):
                self.seek_to(self.current_in)
            # Пин снимаем ДО play(): иначе первые кадры воспроизведения (у них
            # уже другой pts) холст отбросил бы как «чужие», и картинка стояла бы
            # лишние доли секунды. Предекодер тоже глушим — во время игры
            # процессор нужен декодеру плеера, а не буферу стоп-кадров.
            self._release_frame_lock()
            self.player.play()

    def stop_playback(self):
        self.player.pause(); self.seek_to(self.current_in)
        # «Камера» идёт за плейхедом: если зум стоит не на начале зоны, докручиваем
        # окно обзора так, чтобы точка, куда прыгнула жёлтая полоска, была видна.
        try:
            self.waveform.ensure_view_contains(self.current_in, self.current_in)
            self.waveform.update()
        except Exception:
            pass
        # Точный кадр точки IN — на холст СРАЗУ (до прогрева): иначе кадры
        # «разбега» успели бы мелькнуть на экране.
        self._show_exact_frame(self._frame_idx)
        # Прогреваем конвейер в точке IN — следующее «Воспроизвести» стартует
        # без задержки (см. _preroll_at). Цель берём у КАДРА (seek_to уже
        # поставил на него _frame_idx), иначе прогрев целился бы мимо сетки.
        self._preroll_at(self._playhead_target_s())

    # Сколько миллисекунд играем ДО целевой точки при прогреве («разбег»).
    # Замерено на живых файлах: после перемотки QtMultimedia раскручивает
    # конвейер ~300 мс, и ВСЁ это время часы плеера стоят, а потом одним скачком
    # догоняют реальное время. С коротким разбегом (было 140 мс) этот скачок
    # перелетал цель на 240–540 мс, из-за чего прогрев всегда заканчивался
    # обратной перемоткой — то есть ровно тем, чего он и должен избегать
    # (см. _preroll_finish). 500 мс разбега скачок поглощают: промах падает до
    # ±40 мс, обратной перемотки не остаётся вовсе.
    _PREROLL_LEAD_MS = 500
    # Короче этого разбег бессмыслен и ОПАСЕН: play() и pause() попадают в один
    # такт, и пауза теряется (см. _preroll_at).
    _PREROLL_MIN_LEAD_MS = 120
    # Как часто щупаем позицию во время разбега. Сигнал positionChanged приходит
    # раз в ~50 мс — этого мало: за такт плеер успевал уехать за цель дальше, чем
    # на кадр, и снова включалась обратная перемотка. Свой таймер на 5 мс ловит
    # цель настолько рано, насколько плеер вообще о ней сообщает.
    _PREROLL_POLL_MS = 5
    # Упреждение: тормозим чуть РАНЬШЕ цели — промахнуться назад безопаснее
    # (ничего не теряется), чем вперёд.
    _PREROLL_GUARD_MS = 8
    # Промах больше этого правим перемоткой, меньше — оставляем как есть.
    # Цена перемотки — ~350 мс тишины на старте (аудио-конвейер после seek'а
    # поднимается только на play(), проверено: пауза любой длины его не греет).
    # Цена промаха — столько же миллисекунд, срезанных со старта отрезка, причём
    # на экране всё равно пришпилен точный кадр цели. 80 мс — верх реального
    # разброса с разбегом 500 мс.
    _PREROLL_SNAP_MS = 80
    # Нажали «Воспроизвести» ПОСРЕДИ разбега и до цели осталось не больше этого —
    # не перематываем (это остудило бы звук), а доигрываем разбег под mute и
    # снимаем mute ровно на цели. Дальше этого порога ждать дольше, чем стоит
    # перемотка, — тогда перематываем.
    _PREROLL_HANDOFF_MS = 250

    def _playhead_target_s(self):
        """Куда ЦЕЛИТСЯ плеер для текущего плейхеда, с.

        Это середина кадра, на котором стоит монтаж, — та же цель, что у шага
        (см. FrameGrid.center_of). Брать вместо неё player.position() нельзя:
        после перемотки плеер стоит где-то ВНУТРИ кадра (замерено — промах до
        3 кадров), а при удержании стрелки ещё и отстаёт от плейхеда на
        недоехавший seek. Кто считал прогрев от позиции плеера, тот утаскивал
        туда же и номер кадра, и метку — «шагнул вправо, а он пятится назад»."""
        if self._grid.valid and self._frame_idx is not None:
            return self._grid.center_of(self._frame_idx)
        try:
            return max(0.0, self.player.position() / 1000.0)
        except Exception:
            return 0.0

    def _ui_pinned_ms(self):
        """Позиция (мс), на которой ОБЯЗАН стоять интерфейс, или None.

        Плеер иногда играет НЕ для пользователя: беззвучный разбег прогрева и
        транзиентный play() покадрового шага в overlay-режиме. В обоих случаях
        его позиция уезжает и возвращается — и раньше это ехало прямо на шкалу:
        бегунок «разгонялся» к отметке, а шаг стрелкой на один кадр сначала
        сдвигал плейхед, а потом тащил его назад к точке разбега. Резать с таким
        поведением невозможно.

        Поэтому пока плеер занят собой, часы интерфейса стоят на ЗАКАЗАННОЙ
        точке: метка времени, бегунок, жёлтая полоса на волне, «старт→плейхед»
        и полноэкранная панель показывают ровно тот кадр, который выбрал
        пользователь. Наружу прогрева не существует."""
        busy = (getattr(self, "_prerolling", False)
                or getattr(self, "_preroll_handoff", False)
                or getattr(self, "_scrubbing", False))
        if not busy:
            return None
        # Истина у интерфейса одна — НАЧАЛО кадра, на котором стоит монтаж
        # (плееру мы отдаём середину кадра, чтобы он не промахнулся мимо него,
        # но метка обязана совпадать с картинкой). Раньше прогрев отдавал сюда
        # свою цель в миллисекундах, то есть СЕРЕДИНУ кадра, и метка времени
        # после каждого шага дёргалась на полкадра: 00:01:00.017 → .025 → .017.
        if self._grid.valid and self._frame_idx is not None:
            return int(round(self._grid.start_of(self._frame_idx) * 1000.0))
        if (getattr(self, "_prerolling", False)
                or getattr(self, "_preroll_handoff", False)):
            tgt = getattr(self, "_preroll_target_ms", None)
            if tgt is not None:
                return tgt
        ms = getattr(self, "_scrub_audio_ms", None)
        if ms is None:
            ms = getattr(self, "_scrub_target", None)
        return ms

    def _preroll_at(self, t_s):
        """Беззвучный прогрев конвейера «с разбега» перед точкой t_s.

        Зачем вообще: QtMultimedia (ffmpeg-бэкенд) поднимает декодер и аудио-
        устройство только на play(), поэтому первое воспроизведение после
        перемотки начиналось с заметной паузы — на длинных GOP (аниме-BDRip,
        250+ кадров между ключевыми) картинка «думала» до пары секунд.

        Как это делалось раньше и почему это же и мешало: играли 45 мс под mute,
        потом ПАУЗА и setPosition НАЗАД, на исходную точку. Обратный seek — это
        ещё одна полная раскрутка GOP, и попадала она ровно в момент, когда
        пользователь жал «Воспроизвести»: плеер сперва доигрывал этот seek и
        только потом стартовал. Прогрев лечил симптом и создавал его же.

        Теперь прогрев идёт С РАЗБЕГА: встаём на _PREROLL_LEAD_MS РАНЬШЕ цели,
        играем под mute и тормозим, когда позиция САМА дошла до t_s. Обратной
        перемотки нет вовсе (а если проскочили больше кадра — правим, но это
        редкость), декодер уже раскрутил цепочку через нужную точку, и реальный
        старт продолжает воспроизведение, а не начинает его заново.

        И главное: снаружи прогрева НЕ ВИДНО. На холсте пришпилен точный кадр
        цели (см. _show_exact_frame), кадры разбега холст отбрасывает, а часы
        интерфейса заморожены на цели (см. _ui_pinned_ms) — бегунок, метка и
        жёлтая полоса стоят там, куда встал пользователь, и никуда не едут."""
        if self.duration <= 0.1 or not self.filepath:
            return
        if getattr(self, "_prerolling", False):
            # Разбег уже идёт. Если греем ровно эту точку — не мешаем ему. А вот
            # если пользователь тем временем перемотал в другое место, старый
            # разбег обязан быть отменён: он ждёт СВОЮ цель, а плеер уже стоит на
            # новой, и, дождавшись, утащил бы позицию обратно к прежней отметке.
            if abs((getattr(self, "_preroll_target_ms", None) or -10 ** 9)
                   - int(max(0.0, t_s) * 1000)) <= self._PREROLL_GUARD_MS:
                return
            self._preroll_cancel()
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            return
        if getattr(self, "_scrubbing", False):
            return          # идёт серия покадровых шагов — не мешаем ей плеером
        try:
            ms = int(max(0.0, t_s) * 1000)
            lead = max(0, ms - self._PREROLL_LEAD_MS)
            if ms - lead < self._PREROLL_MIN_LEAD_MS:
                # У самого начала файла разбегаться негде: плеер получил бы
                # play() и pause() в одном такте, а такую пару ffmpeg-бэкенд
                # теряет — плеер оставался ИГРАТЬ, пин снимался устаревшим
                # playbackStateChanged, и монтаж уезжал со стартового кадра сам
                # (проверено вживую: шаг у нулевого кадра «уплывал» вперёд).
                # Греть тут всё равно нечего: до начала файла меньше 120 мс.
                return
            # prev_muted держим на self — если пользователь нажмёт «Воспроизвести»
            # прямо в окне прогрева, toggle_play восстановит mute и отменит прогрев.
            self._preroll_prev_muted = self.audio_output.isMuted()
            self._prerolling = True
            self._preroll_handoff = False
            self._preroll_target_ms = ms
            self._preroll_gen = getattr(self, "_preroll_gen", 0) + 1
            gen = self._preroll_gen
            self.audio_output.setMuted(True)
            # Номер кадра прогрев НЕ трогает: на нём стоит монтаж, и вычислять
            # его заново из миллисекунд цели — способ потерять кадр на границе.
            if self._grid.valid and self._frame_idx is None:
                self._frame_idx = self._grid.index_at(ms / 1000.0)
            # Пин цели ДО старта разбега — экран остаётся на нужном кадре.
            self._show_exact_frame(self._frame_idx)
            if lead < ms:
                self.player.setPosition(lead)
            self.player.play()
            # Тормозим по СВОЕМУ таймеру (5 мс), а не по positionChanged (50 мс):
            # см. _PREROLL_POLL_MS.
            self._preroll_timer().start()
            # Страховка: если позиция почему-то не дойдёт до цели (короткий
            # клип, упёрлись в конец, seek не отработал) — заканчиваем сами.
            # Запас считаем от разбега: 500 мс разбега + ~300 мс раскрутки
            # конвейера + запас.
            QTimer.singleShot(self._PREROLL_LEAD_MS + 1500,
                              lambda g=gen: self._preroll_finish(g, forced=True))
        except Exception:
            self._prerolling = False
            self._preroll_target_ms = None
            try:
                self.audio_output.setMuted(False)
            except Exception:
                pass

    def _preroll_cancel(self):
        """Гасит разбег БЕЗ доводки позиции: цель устарела (пользователь перемотал
        в другое место или шагнул кадром), поэтому ни тормозить «на цели», ни
        возвращаться к ней не нужно — тот, кто отменил, сам поставит позицию."""
        if not getattr(self, "_prerolling", False):
            return
        self._prerolling = False
        self._preroll_target_ms = None
        # Новое поколение — чтобы хвосты старого (страховочный singleShot,
        # positionChanged) прошли мимо.
        self._preroll_gen = getattr(self, "_preroll_gen", 0) + 1
        try:
            self._preroll_timer().stop()
        except Exception:
            pass
        try:
            self.player.pause()
        except Exception:
            pass
        try:
            self.audio_output.setMuted(self._preroll_prev_muted)
        except Exception:
            pass

    def _preroll_timer(self):
        """Таймер-сторож разбега (создаётся один раз, см. _PREROLL_POLL_MS)."""
        t = getattr(self, "_preroll_watch_timer", None)
        if t is None:
            t = QTimer(self)
            t.setInterval(self._PREROLL_POLL_MS)
            t.timeout.connect(self._preroll_tick)
            self._preroll_watch_timer = t
        return t

    def _preroll_tick(self):
        """Позиция дошла до цели — тормозим разбег (или, если пользователь уже
        нажал «Воспроизвести», снимаем mute и отдаём ему воспроизведение)."""
        tgt = getattr(self, "_preroll_target_ms", None)
        handoff = getattr(self, "_preroll_handoff", False)
        if tgt is None or not (handoff or getattr(self, "_prerolling", False)):
            self._preroll_timer().stop()
            return
        try:
            pos = self.player.position()
            # Пока play() не отработал, тормозить нечего: pause() в одном такте
            # с play() ffmpeg-бэкенд теряет, и плеер уезжает играть дальше.
            if (self.player.playbackState()
                    != QMediaPlayer.PlaybackState.PlayingState):
                return
        except Exception:
            return
        if pos < tgt - self._PREROLL_GUARD_MS:
            return
        if handoff:
            self._preroll_handoff_finish()
        else:
            self._preroll_finish(getattr(self, "_preroll_gen", 0))

    def _preroll_watch(self, pos_ms):
        """Резервный сторож разбега по positionChanged: сигнал приходит раз в
        ~50 мс, поэтому обычно первым срабатывает _preroll_tick (5 мс). Оставлен
        на случай, если таймер не успел (загруженный интерфейс)."""
        if not (getattr(self, "_prerolling", False)
                or getattr(self, "_preroll_handoff", False)):
            return
        tgt = getattr(self, "_preroll_target_ms", None)
        if tgt is None:
            return
        if pos_ms >= tgt - self._PREROLL_GUARD_MS:
            if getattr(self, "_preroll_handoff", False):
                self._preroll_handoff_finish()
            else:
                self._preroll_finish(getattr(self, "_preroll_gen", 0))

    def _preroll_handoff_finish(self):
        """Разбег доигран до цели, а «Воспроизвести» уже нажато: просто снимаем
        mute и отпускаем покадровый слой. Ни паузы, ни перемотки — конвейер как
        играл, так и играет, поэтому звук появляется ровно на цели и мгновенно."""
        if not getattr(self, "_preroll_handoff", False):
            return
        self._preroll_handoff = False
        self._preroll_target_ms = None
        try:
            self._preroll_timer().stop()
        except Exception:
            pass
        try:
            self.audio_output.setMuted(self._preroll_prev_muted)
        except Exception:
            pass
        # Воспроизведение успели остановить (Пробел ещё раз, СТОП, граница OUT) —
        # тогда мы просто возвращаем mute: пин точного кадра там уже поставлен
        # паузой, и снимать его нельзя.
        try:
            if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                return
        except Exception:
            return
        self._release_frame_lock()

    def _preroll_finish(self, gen=None, forced=False):
        if not getattr(self, "_prerolling", False):
            return
        if gen is not None and gen != getattr(self, "_preroll_gen", 0):
            return          # это хвост от ПРЕДЫДУЩЕГО прогрева
        self._prerolling = False
        try:
            self._preroll_timer().stop()
        except Exception:
            pass
        tgt = getattr(self, "_preroll_target_ms", None)
        self._preroll_target_ms = None
        try:
            self.player.pause()
            if tgt is not None:
                # Возвращаемся назад ТОЛЬКО при ГРУБОМ промахе: лишний seek — это
                # та самая раскрутка конвейера, ради избавления от которой прогрев
                # и переделан (см. докстроку _preroll_at). Порог не «кадр», как
                # было: с кадровым порогом перемотка срабатывала практически
                # всегда (часы плеера меняются шагами по ~40–60 мс), и каждое
                # воспроизведение после перемотки начиналось с ~0.35 с тишины.
                tol = max(self._PREROLL_SNAP_MS,
                          int(1000.0 / self.fps) if (self.fps and self.fps > 0) else 40)
                if abs(self.player.position() - tgt) > tol:
                    self.player.setPosition(tgt)
                t_s = tgt / 1000.0
                if self._grid.valid:
                    if self._frame_idx is None:
                        self._frame_idx = self._grid.index_at(t_s)
                    # Метка и волна показывают НАЧАЛО кадра — ровно то, что
                    # на экране; цель прогрева (середина кадра) сюда не идёт.
                    t_s = self._grid.start_of(self._frame_idx)
                    self._show_exact_frame(self._frame_idx)
                self.waveform.set_playhead(t_s)
                self.lbl_current_time.setText(s_to_time(t_s))
            # Восстанавливаем прежнее состояние mute (могло быть включено
            # внешней озвучкой — тогда звук видео должен остаться немым).
            self.audio_output.setMuted(self._preroll_prev_muted)
        except Exception:
            pass

    def _release_frame_lock(self):
        """Отпускает покадровый слой перед воспроизведением: снимает пин с холста
        и отменяет фоновое декодирование кадров."""
        self._frame_idx = None
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.clear_frame_pin()
        eng = getattr(self, "_frames", None)
        if eng is not None:
            eng.cancel()

    def on_playback_changed(self, state):
        # Во время покадрового скраба play→pause транзиентны — не трогаем кнопку,
        # чтобы иконка/текст не дёргались (меняются только по явному действию).
        # То же во время беззвучного прогрева аудио (_preroll_at): кнопка/иконка
        # и внешняя озвучка не должны мигать на транзиентный play→pause.
        if self._scrubbing or getattr(self, "_prerolling", False):
            return
        playing = (state == QMediaPlayer.PlaybackState.PlayingState)
        # Сигнал приходит с задержкой: «играю» могло прилететь уже ПОСЛЕ того,
        # как прогрев остановил плеер. Верим текущему состоянию, а не почтальону:
        # иначе устаревший сигнал снимал пин с холста и отпускал буфер кадров —
        # картинка уезжала с кадра, на котором стоял монтаж.
        try:
            if playing and (self.player.playbackState()
                            != QMediaPlayer.PlaybackState.PlayingState):
                return
        except Exception:
            pass
        # Painted-режим: во время игры ресайзим кадр быстрым методом (экономим ЦП).
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_playing(playing)
        # Покадровый слой: во время игры главные — кадры плеера (пин снят,
        # предекодер молчит); на паузе, наоборот, пришпиливаем к холсту точный
        # кадр остановки и греем соседей — тогда первый же шаг стрелкой
        # мгновенный и ровно тем кадром, что просили.
        if playing:
            # Исключение — «передача» разбега (см. toggle_play): пока доигрывается
            # немой остаток до отметки, пин точного кадра ОБЯЗАН держаться, иначе
            # на экране мелькнёт кусочек до отметки. Снимет его
            # _preroll_handoff_finish ровно на цели.
            if not getattr(self, "_preroll_handoff", False):
                self._release_frame_lock()
        elif self._grid.valid and self.video_stream_index is not None:
            # Сбрасываем ПЕРЕД вычислением: иначе _current_frame_index вернул бы
            # прежний номер (он на паузе доверяет _frame_idx), а нам нужен кадр,
            # на котором воспроизведение реально остановилось.
            self._frame_idx = None
            self._frame_idx = self._current_frame_index()
            self._show_exact_frame(self._frame_idx)
        if playing:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPause))
            self.sync_timer.start()
        else:
            self.btn_play.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay))
            self.sync_timer.stop()
        self._set_play_bound(playing)   # painted-режим: блокировка кадров за OUT
        # Внешняя озвучка следует за состоянием основного плеера.
        self._ext_audio_set_state(playing)
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.update_play_icon(state == QMediaPlayer.PlaybackState.PlayingState)
            except Exception:
                pass

    def on_media_status_changed(self, status):
        # Дорожки известны только у загруженного медиа — поэтому режим «только
        # звук» доводим до плеера здесь же, а не в момент нажатия кнопки (иначе
        # у нового файла видео возвращалось само).
        if status in (QMediaPlayer.MediaStatus.LoadedMedia,
                      QMediaPlayer.MediaStatus.BufferedMedia):
            if getattr(self, "_audio_only_mode", False):
                self._apply_audio_only_to_player()
        # После смены качества воспроизведения (swap источника) восстанавливаем
        # позицию и состояние, как только медиа загрузилось.
        if (status in (QMediaPlayer.MediaStatus.LoadedMedia,
                       QMediaPlayer.MediaStatus.BufferedMedia)
                and getattr(self, '_pending_pb_seek', None) is not None):
            pos, was_playing = self._pending_pb_seek
            self._pending_pb_seek = None
            try:
                self.player.setPosition(int(max(0, pos)))
                if was_playing:
                    self.player.play()
                else:
                    self.player.pause()
            except Exception:
                pass
        # Подстраховка от чёрного кадра в конце: если воспроизведение всё же
        # дошло до EndOfMedia (таймер sync_ui не успел поставить паузу на кадр
        # раньше), возвращаемся на последний реальный кадр и держим паузу.
        try:
            if status == QMediaPlayer.MediaStatus.EndOfMedia and self.duration > 0:
                frame_s = (1.0 / self.fps) if (self.fps and self.fps > 0) else 0.04
                last = max(self.current_in, self.duration - max(frame_s, 0.05))
                self.player.pause()
                self.player.setPosition(int(last * 1000))
                self.waveform.set_playhead(last)
                self.lbl_current_time.setText(s_to_time(last))
        except Exception:
            pass

    def toggle_mute(self):
        """Клик по значку динамика: выключает звук и включает обратно, возвращая
        ПРЕЖНИЙ уровень громкости.

        Через сам ползунок (а не audio_output.setMuted): его valueChanged уже
        разводит громкость по всем трём выходам — видео, внешняя озвучка и
        скраб-звук покадрового шага, — обновляет значок динамика и полноэкранную
        панель. Плюс setMuted тут занят: им глушится звук видео, когда выбрана
        внешняя озвучка (см. _set_external_audio), и mute «поверх» него оставил
        бы пользователя без способа вернуть звук."""
        sl = getattr(self, "vol_slider", None)
        if sl is None:
            return
        cur = int(sl.value())
        if cur > 0:
            self._vol_before_mute = cur
            sl.setValue(0)
        else:
            # Прежний уровень мог быть нулевым (ползунок утащили в 0 руками) —
            # тогда возвращаем разумную громкость, а не «включаем в тишину».
            prev = int(getattr(self, "_vol_before_mute", 0) or 0)
            sl.setValue(prev if prev > 0 else 100)

    def _on_volume_changed(self, v):
        try:
            self.audio_output.setVolume(v / 100.0)
        except Exception:
            pass
        # Та же громкость — для внешней озвучки (отдельный аудиовыход).
        if self._ext_audio_output is not None:
            try:
                self._ext_audio_output.setVolume(v / 100.0)
            except Exception:
                pass
        # …и для скраб-звука покадровой перемотки.
        if getattr(self, "_scrub_sink_obj", None) is not None:
            try:
                self._scrub_sink_obj.setVolume(max(0.0, min(1.0, v / 100.0)))
            except Exception:
                pass
        try:
            self.vol_lbl.update_glyph(v)
        except Exception:
            pass
        # Полноэкранный ползунок громкости держим в курсе.
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_volume()
            except Exception:
                pass

    def _update_media_buttons(self):
        """Кнопки «полноэкранный режим» и «сохранить кадр» активны только когда
        загружено видео (есть видеопоток и длительность)."""
        has_video = (getattr(self, "video_stream_index", None) is not None
                     and getattr(self, "duration", 0) > 0.1)
        is_image = bool(getattr(self, "is_still_image", False))
        # Для still-картинки доступны кадрирование/пикселизация/сохранение кадра
        # (полноэкранный режим — нет, он завязан на плеер).
        has_visual = has_video or is_image
        audio_only_mode = bool(getattr(self, "_audio_only_mode", False))
        _fsb = getattr(self, "btn_fullscreen", None)
        if _fsb is not None:
            # В режиме «только звук» смотреть в полный экран нечего.
            _fsb.setEnabled(has_video and not audio_only_mode)
        _aob = getattr(self, "btn_audio_only", None)
        if _aob is not None:
            _aob.setEnabled(has_video)
            if not has_video and _aob.isChecked():
                # Загрузили аудиофайл — режим сам себя выключает: у плеера и так
                # нет видео, а подсвеченная кнопка сбивала бы с толку.
                _aob.setChecked(False)
        for name in ("btn_save_frame", "btn_crop_frame", "btn_pixelize",
                     "btn_create_subs", "btn_image_overlay"):
            b = getattr(self, name, None)
            if b is not None:
                b.setEnabled(has_visual)
        # «Удалить объект» — только для видео (для одиночной картинки есть
        # фоторедактор) и только если не идёт уже обработка.
        b = getattr(self, "btn_remove_object", None)
        if b is not None and not getattr(self, "_vinp_running", False):
            b.setEnabled(has_video)
        # «Привязать к объекту» — тоже только для видео (нужно движение).
        b = getattr(self, "btn_track_object", None)
        if b is not None and not getattr(self, "_trk_running", False):
            b.setEnabled(has_video)
        # Нет визуала (ни видео, ни картинки) — выходим из режима кадрирования рамки.
        if not has_visual:
            b = getattr(self, "btn_crop_frame", None)
            if b is not None and b.isChecked():
                b.setChecked(False)
            # …и сбрасываем пикселизацию.
            if getattr(self, "_pixelize_active", False) or (
                    getattr(self, "btn_pixelize", None) is not None
                    and self.btn_pixelize.isChecked()):
                self._pixelize_active = False
                b = getattr(self, "btn_pixelize", None)
                if b is not None and b.isChecked():
                    b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
                self._sync_pixelize_icon()
            self._clear_image_overlays()
        # «Удалить исходник» активна при любом загруженном файле (видео/аудио).
        try:
            src = getattr(self, "actual_source_file", None)
            b = getattr(self, "btn_delete_source", None)
            if b is not None:
                b.setEnabled(bool(src) and os.path.exists(str(src)))
        except Exception:
            pass
        # Режимы обрезки, неприменимые к аудио, отключаем (см. ниже).
        self._update_mode_combo_for_media(has_video)
        # Иконка полноэкранного режима белая поверх accent-заливки; на сером
        # disabled-фоне белый значок «не выглядел» выключенным. Перекрашиваем его
        # в приглушённый цвет, когда видео нет, и обратно в белый, когда есть.
        try:
            if getattr(self, "btn_fullscreen", None) is not None \
                    and getattr(self, "_fs_window", None) is None:
                self.btn_fullscreen.setIcon(_fullscreen_icon(
                    expand=True, color="#ffffff" if has_video else C['text3']))
        except Exception:
            pass

    def _toggle_audio_only(self, on):
        """Кнопка «Только звук»: снимает/возвращает видеодорожку у плеера.

        Декодирование видео прекращается на уровне QMediaPlayer (активный
        видеотрек = -1), предекодер точных кадров глушится, на холсте вместо
        картинки — надпись. Звук, волна, покадровый шаг, прогрев конвейера и
        обрезка работают как обычно: резать по волне и на слух можно ровно так
        же, а экспорт идёт отдельным ffmpeg по исходнику и видео сохраняет."""
        on = bool(on)
        if on == getattr(self, "_audio_only_mode", False):
            return
        self._audio_only_mode = on
        # Разбег греет звук — но он играет плеером, а мы сейчас плееру меняем
        # набор дорожек. Гасим, чтобы не столкнулись.
        if getattr(self, "_prerolling", False):
            self._preroll_cancel()
        self._apply_audio_only_to_player()
        eng = getattr(self, "_frames", None)
        if eng is not None:
            eng.cancel()          # ffmpeg больше не декодирует кадры впустую
        self._update_audio_only_placeholder()
        if not on:
            # Вернули видео — сразу возвращаем и точный кадр под плейхедом.
            self._show_exact_frame(self._frame_idx)
        self._update_media_buttons()

    def _apply_audio_only_to_player(self):
        """Переключает видеодорожку плеера под текущий режим.

        Смена активного трека у ffmpeg-бэкенда может сбросить позицию, поэтому
        запоминаем её и возвращаем: плейхед обязан остаться там же, где стоял
        (см. _ui_pinned_ms — позиция в Монтаже священна)."""
        player = getattr(self, "player", None)
        if player is None:
            return
        on = getattr(self, "_audio_only_mode", False)
        try:
            pos = player.position()
        except Exception:
            pos = None
        try:
            if on:
                cur = player.activeVideoTrack()
                if cur is not None and cur >= 0:
                    self._audio_only_prev_track = cur
                player.setActiveVideoTrack(-1)
            else:
                prev = getattr(self, "_audio_only_prev_track", 0)
                player.setActiveVideoTrack(prev if (prev is not None and prev >= 0) else 0)
        except Exception as e:
            self.main.log(f"audio-only: не удалось переключить видеодорожку: {e}")
            return
        try:
            if pos is not None and player.position() != pos:
                player.setPosition(int(pos))
        except Exception:
            pass

    def _update_audio_only_placeholder(self):
        """В области видео показываем поясняющий текст, когда у загруженного файла
        нет видеоряда (редактируется чистое аудио). При наличии видео или без файла
        — обычный режим (показ кадров)."""
        vw = getattr(self, "video_widget", None)
        if vw is None or not hasattr(vw, "set_audio_only_message"):
            return
        src = getattr(self, "actual_source_file", None)
        # Still-картинка показывается на холсте как кадр — это НЕ «аудио без видео».
        audio_only = (bool(src)
                      and not getattr(self, "is_still_image", False)
                      and getattr(self, "video_stream_index", None) is None
                      and getattr(self, "duration", 0) > 0.1)
        if audio_only:
            vw.set_audio_only_message("Вы редактируете аудиофайл — видеоряд отсутствует")
        elif getattr(self, "_audio_only_mode", False) and bool(src):
            # Видео у файла есть, но пользователь сам отключил его кнопкой —
            # прямо говорим об этом и как вернуть, иначе пустой холст читается
            # как поломка.
            vw.set_audio_only_message(
                "Только звук — видео отключено кнопкой 🎧 в панели плеера.\n"
                "Нажмите её ещё раз, чтобы вернуть картинку. "
                "На обрезку и экспорт это не влияет.")
        else:
            vw.set_audio_only_message("")

    def _update_mode_combo_for_media(self, has_video):
        """Для аудиофайла оставляем только применимые режимы обрезки: «Быстро
        (без потерь)» (0) и «Только аудио (MP3)» (2). «Перекодировать» (1, гонит
        видеокодек) и «Smart Cut» (3, работает по ключевым кадрам ВИДЕО) к аудио
        неприменимы — гасим их в списке, чтобы их нельзя было выбрать. Индексы
        режимов фиксированы (их читает start_cut), поэтому пункты не удаляем, а
        отключаем через модель комбобокса."""
        cmb = getattr(self, "cmb_mode", None)
        if cmb is None:
            return
        try:
            # Гасим режимы только когда РЕАЛЬНО загружено аудио без видео; без
            # файла (или с видео) — все режимы доступны.
            src = getattr(self, "actual_source_file", None)
            audio_only = (bool(src) and not has_video
                          and getattr(self, "duration", 0) > 0.1)
            model = cmb.model()
            # 4 («настройками «Обработки»») и 5 («(Аудио) …») аудио НЕ ломают:
            # ProcessWorker сам умеет аудио-онли (Pass-1 в opus), а 5 в него же
            # и целится, поэтому их не гасим.
            audio_invalid = (1, 3)   # «Перекодировать», «Smart Cut»
            for i in range(cmb.count()):
                item = model.item(i)
                if item is None:
                    continue
                item.setEnabled((not audio_only) or i not in audio_invalid)
            # Если для аудио выбран теперь недоступный режим — переводим на
            # «Быстро (без потерь)» (точная lossless-обрезка по времени).
            if audio_only and cmb.currentIndex() in audio_invalid:
                cmb.setCurrentIndex(0)
        except Exception:
            pass

    def _toggle_frame_crop(self, on):
        """Вкл/выкл режим правки рамки кадрирования на холсте (как в «Редактировании
        фото»): появляется рамка с ручками и кнопки «Применить/Отмена»."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.set_crop_mode(bool(on))
        if on:
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Кадрирование видео: правьте рамку ручками "
                                  "(углы/стороны), затем «Применить» (Enter) или "
                                  "«Отмена» (Esc). Применится при «Обрезать» "
                                  "(перекодирование).")
            except Exception:
                pass

    def _toggle_pixelize(self, on):
        """Вкл/выкл эффект «проявление из пикселей». При включении открывается
        диалог с параметрами (число шагов, стартовый блок); отмена снимает чек.
        Эффект применяется при «Обрезать» и виден только в итоговом файле (живого
        превью нет — мозаика считается при перекодировке)."""
        if on:
            is_image = bool(getattr(self, "is_still_image", False))
            dlg = _PixelizeDialog(self._pixelize_steps, self._pixelize_block, self,
                                  image_mode=is_image, duration=self._still_duration,
                                  fps=self._still_fps)
            if dlg.exec():
                self._pixelize_steps, self._pixelize_block = dlg.values()
                self._pixelize_active = True
                if is_image:
                    self._still_duration, self._still_fps = dlg.image_values()
                    # Длительность ролика обновилась — отражаем в таймингах.
                    self.duration = float(self._still_duration)
                    self.current_out = self.duration
                    try:
                        self.lbl_duration.setText(s_to_time(self.duration))
                        self._update_total_time()
                    except Exception:
                        pass
                try:
                    if self.main is not None and hasattr(self.main, "log"):
                        seq = _pixelize_block_sequence(self._pixelize_block, self._pixelize_steps)
                        extra = (f", {self._still_duration}с @ {self._still_fps}fps"
                                 if is_image else "")
                        self.main.log(
                            f"Пикселизация задана ({self._pixelize_steps} шаг(ов), "
                            f"старт {self._pixelize_block}px{extra}) — применится при "
                            f"«Обрезать». Блоки: "
                            + " → ".join(f"{b}px" if b > 1 else "чётко" for b in seq))
                except Exception:
                    pass
            else:
                # Отмена диалога — снимаем чек, не трогая прежнее состояние.
                self._pixelize_active = False
                b = self.btn_pixelize
                b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        else:
            self._pixelize_active = False
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Пикселизация отключена.")
            except Exception:
                pass
        self._sync_pixelize_icon()

    def _sync_pixelize_icon(self):
        """Цвет значка кнопки пикселизации по состоянию: тёмный на акцентной
        заливке (включено), обычный — выключено. Иначе светлый значок на светло-
        голубом фоне «included» сливался."""
        b = getattr(self, "btn_pixelize", None)
        if b is None:
            return
        try:
            b.setIcon(get_icon('fa5s.th', color='#11111b' if b.isChecked() else C['text']))
        except Exception:
            pass

    def _video_pixelize_filter(self, dur, offset=0.0):
        """Цепочка ffmpeg-фильтров «проявление из пикселей» для клипа длительностью
        `dur` секунд, либо None если эффект выключен/нечего применять. Делит клип на
        N равных окон; в каждом окне `pixelize` с уменьшающимся блоком (через
        enable='between(t,…)'), пока картинка не станет чёткой.

        ВАЖНО про `offset`: фильтрграф видит ВРЕМЯ ИСХОДНИКА, а не время обрезанного
        клипа (setpts на таймлайн `enable` не влияет — проверено). Поэтому окна
        смещаются на `offset` — время фильтрграфа, на котором начинается клип:
          • выходной seek (-ss после -i): offset = начало реза in_s;
          • входной seek (-ss до -i):       offset = 0;
          • входной pre-seek + выходной -ss: offset = величина выходного -ss.
        """
        if not getattr(self, "_pixelize_active", False) or dur is None or dur <= 0:
            return None
        # Сама цепочка собирается общим модулем pixelize (им же пользуется
        # генератор аниме-паков) — эффект в обеих вкладках один и тот же.
        return _pixelize_filter(dur,
                                max(1, int(getattr(self, "_pixelize_steps", 6))),
                                max(2, int(getattr(self, "_pixelize_block", 64))),
                                offset)

    def _on_crop_applied(self):
        """Холст: нажата «Применить» — снимаем чек с кнопки (режим правки закрыт),
        рамка остаётся «вооружённой» для «Обрезать»."""
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)
        armed = self._video_crop_filter() is not None
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Кадрирование задано — применится при «Обрезать»."
                              if armed else "Кадрирование снято (рамка = весь кадр).")
        except Exception:
            pass

    def _on_crop_cancelled(self):
        """Холст: нажата «Отмена»/Esc — снимаем чек с кнопки, рамка сброшена."""
        b = getattr(self, "btn_crop_frame", None)
        if b is not None and b.isChecked():
            b.blockSignals(True); b.setChecked(False); b.blockSignals(False)

    def _video_crop_filter(self):
        """ffmpeg-фильтр crop=… по рамке кадрирования на холсте, либо None, если
        рамка не задана/слишком мелкая. Координаты — выражения от iw/ih (не
        зависят от прокси-превью), размеры/смещения чётные (требование кодеков)."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, VideoCanvas):
            return None
        n = vw.crop_norm()
        if n is None:
            return None
        x = max(0.0, min(1.0, n.left()))
        y = max(0.0, min(1.0, n.top()))
        w = max(0.0, min(1.0 - x, n.width()))
        h = max(0.0, min(1.0 - y, n.height()))
        if w < 0.02 or h < 0.02:
            return None
        return (f"crop=trunc(iw*{w:.6f}/2)*2:trunc(ih*{h:.6f}/2)*2:"
                f"trunc(iw*{x:.6f}/2)*2:trunc(ih*{y:.6f}/2)*2")

    # ── Наложение картинки поверх видео ──────────────────────────────────────
    #
    # Слои живут на холсте (VideoCanvas), правятся мышью, а в файл попадают
    # фильтром overlay=… при «Обрезать». Порядок фильтров: НАКЛАДКИ → кадрирование
    # → субтитры → пикселизация (см. edit_tab_overlay.overlay_filter_graph) —
    # ровно как это видно в плеере.
    def _overlay_frame_size(self):
        """Размер кадра в пикселях ИСХОДНИКА (в плеере может идти прокси меньшего
        разрешения — по нему координаты считать нельзя). Для картинки-исходника
        берём её собственный размер, для видео — ffprobe, а если не вышло —
        размер кадра на холсте."""
        if getattr(self, "is_still_image", False) and self.still_image_path:
            img = QImage(str(self.still_image_path))
            if not img.isNull():
                return (img.width(), img.height())
        src = self.actual_source_file or self.filepath
        if src and os.path.exists(str(src)):
            w, h = probe_frame_size(str(src))
            if w > 0 and h > 0:
                return (w, h)
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            img = vw.current_frame_image()
            if img is not None and not img.isNull():
                return (img.width(), img.height())
        return (0, 0)

    def image_overlays(self):
        """Список наложенных картинок (пустой, если холст без них)."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, VideoCanvas):
            return []
        return vw.image_overlays()

    def has_image_overlays(self):
        return bool(self.image_overlays())

    def add_image_overlay(self):
        """Кнопка «Наложить картинку»: выбор файла → новый слой поверх кадра."""
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, VideoCanvas):
            msgbox_information(
                self, "Недоступно",
                "Наложение картинки работает только с собственным холстом видео "
                "(Настройки → Монтаж → метод субтитров «в кадр»).")
            return
        if not (getattr(self, "video_stream_index", None) is not None
                or getattr(self, "is_still_image", False)):
            msgbox_information(self, "Нет видео",
                               "Сначала загрузите видео или картинку.")
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Выберите картинку для наложения", "",
            "Изображения (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.avif);;"
            "Все файлы (*.*)")
        if not path:
            return
        img = load_overlay_image(path)
        if img is None:
            msgbox_warning(self, "Не удалось открыть",
                           "Файл не похож на картинку или формат не поддерживается.")
            return
        fw, fh = self._overlay_frame_size()
        if fw <= 0 or fh <= 0:
            msgbox_warning(self, "Не удалось определить кадр",
                           "Не получилось узнать размер кадра видео — "
                           "перезагрузите файл и попробуйте снова.")
            return
        vw.add_image_overlay(ImageOverlay(path, img, fw, fh))
        self._refresh_overlay_panel()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(
                    f"Наложена картинка {os.path.basename(path)}: двигайте мышью, "
                    "тяните за уголки, крутите за кружок сверху (Shift — шаг 15°), "
                    "Ctrl+стрелки — точная сдвижка, Delete — убрать. "
                    "Вшивается при «Обрезать» (перекодировка).")
        except Exception:
            pass

    def _refresh_overlay_panel(self, current=None):
        """Пересобирает список слоёв в боковой панели по состоянию холста."""
        panel = getattr(self, "overlay_panel", None)
        if panel is None:
            return
        vw = getattr(self, "video_widget", None)
        items = vw.image_overlays() if isinstance(vw, VideoCanvas) else []
        if current is None:
            current = (vw.selected_overlay_index()
                       if isinstance(vw, VideoCanvas) else -1)
        panel.refresh(items, int(current))

    def _on_overlays_changed(self):
        """Холст: слой подвинули/растянули/удалили — обновляем список."""
        self._refresh_overlay_panel()

    def _on_overlay_picked(self, idx):
        """Холст: слой выбрали мышью — подсвечиваем строку в списке."""
        panel = getattr(self, "overlay_panel", None)
        if panel is not None:
            panel.list.setCurrentRow(int(idx))

    def _on_overlay_selected(self, idx):
        """Список: выбрана строка — тот же слой выделяем на холсте."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas) and idx >= 0:
            vw.set_selected_overlay(int(idx))
            vw.set_overlay_edit(True)

    def _delete_image_overlay(self, idx):
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.remove_image_overlay(int(idx))
            self._refresh_overlay_panel()

    def _set_overlay_opacity(self, idx, value):
        items = self.image_overlays()
        if 0 <= idx < len(items):
            items[idx].opacity = max(0.05, min(1.0, float(value)))
            self.video_widget.update()

    def _reset_image_overlay(self, idx):
        """Сброс слоя к исходному виду: без поворота, без обрезки, стандартный
        размер/место (удобно, когда картинку «закрутили» и потеряли)."""
        items = self.image_overlays()
        if not (0 <= idx < len(items)):
            return
        it = items[idx]
        it.angle = 0.0
        it.set_crop(QRectF(0.0, 0.0, 1.0, 1.0), keep_width=False)
        cw, ch = it.cropped_size()
        it.rect = fit_rect_norm(cw, ch, it.frame_w, it.frame_h)
        self.video_widget.update()
        self._refresh_overlay_panel(idx)

    def _crop_image_overlay(self, idx):
        """Кадрирование самой картинки (отдельное окно с рамкой обрезки)."""
        items = self.image_overlays()
        if not (0 <= idx < len(items)):
            return
        it = items[idx]
        dlg = OverlayCropDialog(it, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        if it.set_crop(dlg.crop_norm()):
            self.video_widget.update()
            self._refresh_overlay_panel(idx)

    def _clear_image_overlays(self):
        """Убирает все слои (новый файл начинается чистым, как и пикселизация)."""
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            vw.clear_image_overlays()
        self._refresh_overlay_panel()

    def _render_export_overlays(self):
        """Готовит PNG всех накладок под размер ИСХОДНОГО кадра. Возвращает
        список (путь, x, y) для overlay_filter_graph (пустой — накладок нет).

        PNG кладутся во временную папку вкладки и переписываются на каждом
        экспорте; папку убирает shutdown()."""
        items = self.image_overlays()
        if not items:
            return []
        fw, fh = self._overlay_frame_size()
        if fw <= 0 or fh <= 0:
            return []
        d = getattr(self, "_overlay_tmp_dir", None)
        if not d or not os.path.isdir(d):
            d = tempfile.mkdtemp(prefix="sihyx_overlay_")
            self._overlay_tmp_dir = d
        return render_overlays(items, d, fw, fh)

    def _paint_overlays_on_image(self, img):
        """Впечатывает наложенные картинки в готовый кадр (QImage) — тем же
        порядком и в тех же долях, что и экспорт. Возвращает новый QImage (или
        исходный, если накладок нет)."""
        items = self.image_overlays()
        if not items or img is None or img.isNull():
            return img
        out = img.convertToFormat(QImage.Format.Format_ARGB32)
        p = QPainter(out)
        try:
            for it in items:
                ovl, x, y = it.rendered(out.width(), out.height())
                if ovl is not None:
                    p.drawImage(int(x), int(y), ovl)
        finally:
            p.end()
        return out

    def _static_overlays_bgra(self, frame_w, frame_h):
        """Наложенные картинки в виде (BGRA, x, y) под размер кадра — для путей,
        которые правят кадры сами (TrackOverlayWorker), а не через -vf."""
        out = []
        for it in self.image_overlays():
            img, x, y = it.rendered(frame_w, frame_h)
            if img is None:
                continue
            bgra = qimage_to_bgra(img)
            if bgra is not None:
                out.append((bgra, int(x), int(y)))
        return out

    def _wrap_vf(self, chain, src=None):
        """Оборачивает готовую цепочку -vf графом с накладками (если они есть).
        `chain` — строка фильтров Монтажа (может быть пустой), `src` — файл, из
        которого идёт кодирование (по умолчанию открытый в Монтаже).

        Формат работы overlay берём ПО ИСХОДНИКУ (см. overlay_chroma_format):
        при `format=auto` граф с RGBA-накладкой уводил ВЕСЬ кадр в RGB, libx264
        писал gbrp — и итог получался кислотно-зелёным/малиновым."""
        rendered = self._render_export_overlays()
        if not rendered:
            return chain or ""
        return overlay_filter_graph(chain or "", rendered,
                                    self._escape_filter_path,
                                    pix_fmt=self._overlay_pix_fmt(src))

    def _overlay_pix_fmt(self, src=None):
        """Значение `format=` для overlay под pix_fmt исходника (кэшируется на
        файл: ffprobe на каждый экспорт тут ни к чему)."""
        path = str(src or getattr(self, "actual_source_file", "") or "")
        if not path or not os.path.exists(path):
            return "yuv420"
        cache = getattr(self, "_ovl_fmt_cache", None)
        if cache is None:
            cache = self._ovl_fmt_cache = {}
        stamp = self._file_cache_stamp(path)
        key = (path, stamp)
        got = cache.get(key)
        if got is None:
            got = cache[key] = overlay_chroma_format(get_pix_fmt(path))
        return got

    @staticmethod
    def _apply_frame_crop(img, n):
        """Обрезает QImage по нормализованной рамке n (QRectF 0..1). Координаты
        зажимаются в границы изображения."""
        if img is None or img.isNull() or n is None:
            return img
        w, h = img.width(), img.height()
        x = max(0, min(w - 1, int(round(n.left() * w))))
        y = max(0, min(h - 1, int(round(n.top() * h))))
        cw = max(1, min(w - x, int(round(n.width() * w))))
        ch = max(1, min(h - y, int(round(n.height() * h))))
        return img.copy(x, y, cw, ch)

    # ── Сохранение текущего кадра ────────────────────────────────────────────
    def save_frame(self):
        """Сохраняет кадр на текущей позиции воспроизведения в PNG (полное
        разрешение, извлекается из исходника через ffmpeg). Без диалога —
        файл сразу кладётся в папку сохранения (или рядом с исходником)."""
        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(src) or self.duration <= 0:
            return
        # Рамка кадрирования (если задана на холсте) — сохраняем только её.
        crop_n = None
        _vw = getattr(self, "video_widget", None)
        if isinstance(_vw, VideoCanvas):
            crop_n = _vw.crop_norm()
        # Время кадра, который на экране (см. _clock_pos_s) — им же назван файл,
        # и по нему же идёт резервное извлечение через ffmpeg.
        pos = max(0.0, self._clock_pos_s())
        base = os.path.splitext(os.path.basename(src))[0]
        stamp = s_to_time(pos).replace(':', '-').replace('.', '_')
        save_dir = (self.export_dir if (self.export_dir and os.path.isdir(self.export_dir))
                    else os.path.dirname(src))
        fname = _unique_output(os.path.join(save_dir, f"{base}_{stamp}.png"))
        ok = False
        # 1) В painted-режиме (VideoCanvas) сохраняем РОВНО тот кадр, что показан
        #    на холсте — без пере-извлечения через ffmpeg. Иначе seek по позиции
        #    на HEVC отдавал следующий кадр (out_time приходился между кадрами →
        #    ffmpeg брал первый PTS ≥ позиции = следующий).
        # (Если активен превью-прокси, кадр на холсте уменьшён — тогда лучше
        #  полноразмерный кадр из оригинала через ffmpeg, см. ниже.)
        if isinstance(self.video_widget, VideoCanvas) and not self.is_proxy_active:
            try:
                img = self.video_widget.current_frame_image()
                if img is not None and not img.isNull():
                    img = self._paint_overlays_on_image(img)
                    if crop_n is not None:
                        img = self._apply_frame_crop(img, crop_n)
                    ok = bool(img.save(fname, "PNG"))
            except Exception:
                ok = False
        # 2) Резерв (overlay-режим / нет кадра на холсте): извлекаем через ffmpeg.
        #    -ss перед -i точен, но позиция может прийтись между кадрами; вычитаем
        #    половину интервала кадра, чтобы попасть в текущий, а не следующий.
        if not ok:
            # Целимся четвертью кадра НИЖЕ его pts: ffmpeg отдаёт первый кадр с
            # pts ≥ -ss, значит это ровно наш кадр (см. FrameGrid.seek_of).
            if self._grid.valid:
                seek = self._grid.seek_of(self._grid.index_at(pos))
            else:
                seek = max(0.0, pos - 0.02)
            cmd = [FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
                   "-frames:v", "1", "-update", "1", fname]
            kw = {}
            if os.name == 'nt':
                kw['creationflags'] = CREATE_NO_WINDOW
            try:
                r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=60, **kw)
                ok = (r.returncode == 0 and os.path.exists(fname)
                      and os.path.getsize(fname) > 0)
            except Exception:
                ok = False
            # Полноразмерный кадр из ffmpeg обрезаем под рамку кадрирования.
            if ok and (crop_n is not None or self.has_image_overlays()):
                try:
                    _qi = QImage(fname)
                    if not _qi.isNull():
                        _qi = self._paint_overlays_on_image(_qi)
                        if crop_n is not None:
                            _qi = self._apply_frame_crop(_qi, crop_n)
                        _qi.save(fname, "PNG")
                except Exception:
                    pass
        msg = (f"🖼 Кадр сохранён: {os.path.basename(fname)}" if ok
               else "Не удалось сохранить кадр")
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(msg)
        except Exception:
            pass
        try:
            gp = self.btn_save_frame.mapToGlobal(
                QPoint(0, -self.btn_save_frame.height()))
            QToolTip.showText(gp, msg, self.btn_save_frame)
        except Exception:
            pass

    # ── Удаление объекта с видео (LaMa, покадрово) ───────────────────────────
    def _ensure_inpainter(self):
        """Лениво создаёт движок LaMa (ТОТ ЖЕ, что в фоторедакторе) и
        переиспользует его между запусками. Сессия живёт в дочернем процессе
        (см. lama_inpaint.py), поэтому загрузка 200-МБ модели не морозит UI."""
        inp = getattr(self, "_inpainter", None)
        if inp is not None:
            return inp
        try:
            from lama_inpaint import LaMaProcessInpainter
        except Exception:
            return None
        self._inpainter = LaMaProcessInpainter()
        return self._inpainter

    def _grab_source_frame_bgr(self, src):
        """Извлекает кадр оригинала на текущей позиции воспроизведения в ПОЛНОМ
        разрешении (через ffmpeg) и возвращает numpy BGR. Способ совпадает с тем,
        как VideoInpaintWorker позже извлечёт все кадры, поэтому нарисованная маска
        попадает в кадры попиксельно (то же разрешение и дисплейная ориентация)."""
        pos = max(0.0, self._clock_pos_s())
        # -ss перед -i точен, но позиция может прийтись между кадрами — целимся
        # четвертью кадра ниже pts нужного кадра (см. FrameGrid.seek_of), иначе
        # ffmpeg отдаст СЛЕДУЮЩИЙ кадр и маска ляжет не на тот кадр.
        if self._grid.valid:
            seek = self._grid.seek_of(self._grid.index_at(pos))
        else:
            seek = max(0.0, pos - 0.02)
        tmp = os.path.join(tempfile.gettempdir(),
                           f"sihyx_vmask_{os.getpid()}_{int(time.time() * 1000)}.png")
        cmd = [FFMPEG, "-y", "-ss", f"{seek:.3f}", "-i", src,
               "-frames:v", "1", "-update", "1", tmp]
        kw = {}
        if os.name == 'nt':
            kw['creationflags'] = CREATE_NO_WINDOW
        try:
            r = subprocess.run(cmd, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60, **kw)
            if r.returncode != 0 or not os.path.exists(tmp):
                return None
            from lama_inpaint import load_bgr
            return load_bgr(tmp)
        except Exception:
            return None
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def remove_object_from_video(self):
        """Удаляет объект (водяной знак/эмодзи/логотип) со ВСЕГО видео: пользователь
        закрашивает объект кистью на текущем кадре, затем ТЕМ ЖЕ движком LaMa, что и
        в фоторедакторе, объект убирается с каждого кадра, и видео собирается
        обратно с исходными FPS/разрешением/ориентацией/аудио. Тяжёлая работа — в
        отдельном потоке (VideoInpaintWorker) с возможностью отмены.

        Поведение для одиночного изображения НЕ меняется: эта кнопка активна только
        при загруженном видео (см. _update_media_buttons)."""
        # Пока идёт обработка — кнопка работает как «Отмена».
        if getattr(self, "_vinp_running", False):
            self._cancel_video_inpaint()
            return

        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(str(src)) or self.duration <= 0:
            return
        if getattr(self, "video_stream_index", None) is None:
            msgbox_information(
                self, "Только для видео",
                "Удаление объекта доступно для видео. Для одиночного изображения "
                "используйте вкладку «Фото».")
            return
        src = str(src)

        # Доступность движка LaMa (numpy/opencv/модель).
        inp = self._ensure_inpainter()
        if inp is None or not inp.is_available():
            msgbox_warning(
                self, "Удаление объекта недоступно",
                "Не найдены необходимые компоненты (numpy/opencv или файл модели "
                "LaMa). Удаление объекта с видео недоступно в этой сборке.")
            return

        # Кадр для рисования маски — из оригинала на текущей позиции, полный размер.
        frame = self._grab_source_frame_bgr(src)
        if frame is None:
            msgbox_warning(
                self, "Ошибка",
                "Не удалось получить кадр видео для рисования маски.")
            return

        dlg = _VideoMaskDialog(frame, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mask = dlg.get_mask()
        if mask is None or int(mask.max()) == 0:
            return

        # Имя результата — в папке сохранения/рядом с исходником; контейнер
        # исходника, если он поддерживает H.264, иначе .mp4 (h264 в webm недопустим).
        base = Path(src)
        out_dir = (Path(self.export_dir)
                   if (self.export_dir and os.path.isdir(self.export_dir))
                   else base.parent)
        suffix = base.suffix.lower()
        if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
            suffix = ".mp4"
        out_path = str(out_dir / f"{base.stem}_без_объекта{suffix}")
        if os.path.exists(out_path):
            out_path = _unique_output(out_path)

        has_audio = getattr(self, "audio_stream_index", None) is not None
        venc = self._video_encoder_args(hardsub=False)

        # Запуск фоновой обработки + перевод кнопки в режим «Отмена».
        self._vinp_running = True
        self.btn_cut.setEnabled(False)
        self._set_remove_btn_cancel(True)
        self._report_progress(-1, "Удаление объекта…")
        self._set_cut_status("Удаление объекта… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Удаление объекта с видео…")

        self._vinp_worker = VideoInpaintWorker(
            inp, src, mask, self.fps, out_path, venc, has_audio)
        self._vinp_worker.progress.connect(self._on_vinp_progress)
        self._vinp_worker.done.connect(self._on_vinp_done)
        self._vinp_worker.failed.connect(self._on_vinp_failed)
        self._vinp_worker.start()

    def _set_remove_btn_cancel(self, cancel_mode):
        """Переключает кнопку «Удалить объект» между обычным видом и «Отмена» на
        время обработки видео."""
        b = getattr(self, "btn_remove_object", None)
        if b is None:
            return
        if cancel_mode:
            b.setIcon(get_icon('fa5s.times'))
            b.setToolTip("Отменить удаление объекта")
            b.setEnabled(True)
        else:
            b.setIcon(get_icon('fa5s.magic'))
            b.setToolTip(
                "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте "
                "его кистью на кадре — нейросеть LaMa уберёт его со всех кадров")

    def _set_cut_btn_cancel(self, cancel_mode, cancel_handler=None):
        """Переключает btn_cut («Обрезать») между обычным видом и «Отмена» на
        время перекодировки/обрезки — тот же приём, что _set_remove_btn_cancel
        для «Удалить объект», но с сохранением исходных текста/иконки/стиля:
        у btn_cut они меняются по режиму («Обрезать» / «Создать видео» для
        картинки), и вернуть нужно РОВНО то, что было до переключения."""
        b = self.btn_cut
        try:
            b.clicked.disconnect()
        except Exception:
            pass
        if cancel_mode:
            self._cut_btn_saved = (b.text(), b.icon(), b.styleSheet())
            b.setText("Отмена")
            b.setIcon(get_icon('fa5s.times', color='#1e1e2e'))
            b.setStyleSheet(f"""
                QPushButton {{
                    background: {C['red']};
                    color: #1e1e2e;
                    border: none;
                    border-radius: 6px;
                    padding: 9px 24px;
                    font-weight: 700;
                    font-size: 13px;
                    letter-spacing: 0.3px;
                }}
                QPushButton:hover {{ background: {C['red2']}; }}
                QPushButton:pressed {{ background: {C['red2']}; }}
                QPushButton:disabled {{ background: {C['surface3']}; color: {C['text3']}; }}
            """)
            b.setEnabled(True)
            b.clicked.connect(cancel_handler or self._cancel_cut)
        else:
            saved = getattr(self, '_cut_btn_saved', None)
            if saved:
                b.setText(saved[0]); b.setIcon(saved[1]); b.setStyleSheet(saved[2])
            b.setEnabled(True)
            b.clicked.connect(self.start_cut)

    def _cancel_cut(self):
        """Отменяет текущую обрезку/перекодировку/Smart Cut (self.ffmpeg_thread)."""
        th = getattr(self, "ffmpeg_thread", None)
        if th is not None and th.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            self.btn_cut.setEnabled(False)
            th.stop()

    def _cancel_cut_and_process(self, tab_media):
        """Отменяет «Обрезать и обработать» (worker вкладки «Обработка»)."""
        w = getattr(tab_media, 'worker', None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            self.btn_cut.setEnabled(False)
            w.stop()

    def _cancel_video_inpaint(self):
        """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
        w = getattr(self, "_vinp_worker", None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            if getattr(self, "btn_remove_object", None) is not None:
                self.btn_remove_object.setEnabled(False)
            w.cancel()

    def _on_vinp_progress(self, pct, text):
        self._report_progress(pct, text)
        self._set_cut_status(text, icon='fa5s.magic' if pct >= 0
                             else 'fa5s.hourglass-half')

    def _finish_video_inpaint(self):
        """Общая уборка состояния UI после завершения/отмены/ошибки обработки."""
        self._vinp_running = False
        self._vinp_worker = None
        self._set_remove_btn_cancel(False)
        self.btn_cut.setEnabled(True)
        self._update_media_buttons()

    def _on_vinp_done(self, final_path):
        self._finish_video_inpaint()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Объект удалён с видео: {final_path}")
        except Exception:
            pass
        # Переиспользуем стандартное завершение «Монтажа» (статус «Готово»,
        # обновление верхней ленты файлов и т.п.).
        self.on_ffmpeg_finished(True, "Готово")

    def _on_vinp_failed(self, message):
        self._finish_video_inpaint()
        self.on_ffmpeg_finished(False, message)

    # ── Привязка текста/картинки к движущемуся объекту ───────────────────────
    def track_object_overlay(self):
        """Привязывает текст или картинку к ДВИЖУЩЕМУСЯ объекту: пользователь
        обводит объект рамкой на текущем кадре, трекер DyHiT (нейросеть, ONNX;
        без модели — запасной CSRT из OpenCV) находит его на каждом следующем
        кадре, и накладка едет вместе с ним. Результат — новый файл; исходник не
        трогаем. Вся тяжёлая работа в TrackOverlayWorker, с отменой.

        Доступно только для видео: у одиночной картинки нечему двигаться."""
        # Пока идёт обработка — кнопка работает как «Отмена».
        if getattr(self, "_trk_running", False):
            self._cancel_track_overlay()
            return
        # Накладка уже висит в плеере — второе нажатие её снимает (отдельной
        # кнопки «Отмена» на холсте нет, экспортом занимается «Обрезать»).
        if self.has_track_preview():
            self._clear_track_preview()
            return
        self._clear_track_preview()

        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(str(src)) or self.duration <= 0:
            return
        if getattr(self, "video_stream_index", None) is None:
            msgbox_information(
                self, "Только для видео",
                "Привязка к объекту работает с видео: нужно движение, за которым "
                "можно следить.")
            return
        src = str(src)

        try:
            import dyhit_tracker
        except Exception as e:
            msgbox_warning(
                self, "Отслеживание недоступно",
                f"Не удалось загрузить движок отслеживания (нужны numpy/opencv):\n{e}")
            return
        if not (dyhit_tracker.dyhit_available()
                or dyhit_tracker.opencv_tracker_available()):
            msgbox_warning(
                self, "Отслеживание недоступно",
                "Не найден ни один трекер. Для нейросетевого варианта положите "
                "файл модели DyHiT/HiT (.onnx) в папку models — ожидается "
                f"{dyhit_tracker.expected_model_path()} — либо установите "
                "opencv-python с трекерами (CSRT).")
            return

        # Кадр для выбора области — из оригинала на текущей позиции, полный размер
        # (тот же способ, что у маски удаления объекта, поэтому рамка попадает в
        # кадры воркера попиксельно).
        frame = self._grab_source_frame_bgr(src)
        if frame is None:
            msgbox_warning(self, "Ошибка",
                           "Не удалось получить кадр видео для выбора объекта.")
            return

        fps = float(self.fps) if getattr(self, "fps", None) else 25.0
        pos = max(0.0, self.player.position() / 1000.0)
        start_s = max(0.0, pos - 0.5 / fps)
        zone_end = float(self.current_out) if getattr(self, "current_out", 0) else 0.0

        dlg = _TrackAttachDialog(frame, self, start_s=start_s,
                                 end_s=float(self.duration), zone_end_s=zone_end)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        spec = dlg.values()
        if not spec.get("box") or spec.get("overlay_bgra") is None:
            return

        h, w = frame.shape[:2]
        self._trk_spec = dict(spec)
        self._trk_spec.update({"src": src, "fps": fps, "src_w": w, "src_h": h})

        # Шаг 1 — только путь объекта, без кодирования: он считается в разы
        # быстрее полного рендера, и по нему сразу показываем предпросмотр.
        self._trk_running = True
        self._set_track_export_busy(True)
        self._report_progress(-1, "Привязка к объекту…")
        self._set_cut_status("Привязка к объекту… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Отслеживание объекта на видео…")

        self._trk_worker = TrackPathWorker(
            src, fps, (w, h), spec["box"], spec["start_s"], spec["end_s"],
            smooth=spec["smooth"])
        self._trk_worker.progress.connect(self._on_trk_progress)
        self._trk_worker.done.connect(self._on_track_path_ready)
        self._trk_worker.failed.connect(self._on_trk_failed)
        self._trk_worker.start()

    def _on_track_path_ready(self, boxes):
        """Путь объекта посчитан — показываем накладку прямо в плеере. Ничего
        никуда не записано: в файл накладка попадёт обычным экспортом, то есть
        кнопкой «Обрезать» (см. start_cut)."""
        self._finish_track_overlay()
        spec = getattr(self, "_trk_spec", None)
        if not spec or not boxes:
            return
        spec["boxes"] = boxes
        canvas = self.video_widget
        if not isinstance(canvas, VideoCanvas):
            # Классический QVideoWidget не умеет рисовать поверх кадра — там
            # предпросмотра нет, сразу рендерим (как раньше).
            self._render_track_overlay()
            return

        from photo_tab import np_bgra_to_qimage
        qimg = np_bgra_to_qimage(spec["overlay_bgra"])
        canvas.set_track_preview({
            "overlay": qimg, "boxes": boxes,
            "src_w": spec["src_w"], "src_h": spec["src_h"], "fps": spec["fps"],
            "start_s": spec["start_s"], "end_s": spec["end_s"],
            "anchor": spec["anchor"], "off": (spec["off_x"], spec["off_y"]),
            "scale_with_box": spec["scale_with_box"],
        })
        canvas.set_track_time(max(0.0, self.player.position() / 1000.0))
        self._connect_track_preview_signals(canvas)
        self._set_cut_status("Накладка привязана — сохранит её «Обрезать»",
                             icon='fa5s.crosshairs')
        self.log_label.setText(
            "Смотрите, как накладка едет за объектом. «Обрезать» сохранит видео "
            "с накладкой, кнопка привязки — уберёт её.")

    def _connect_track_preview_signals(self, canvas):
        """Подключает сигналы предпросмотра ровно один раз на КАЖДЫЙ холст (при
        смене способа показа видео в настройках виджет пересоздаётся)."""
        if getattr(self, "_trk_signals_canvas", None) is canvas:
            return
        canvas.trackCancelled.connect(self._clear_track_preview)
        self._trk_signals_canvas = canvas

    def has_track_preview(self):
        """Есть ли посчитанная накладка, ждущая экспорта («Обрезать»)."""
        spec = getattr(self, "_trk_spec", None)
        return bool(spec and spec.get("boxes"))

    def _clear_track_preview(self):
        """Убирает накладку из плеера (Esc, повторное нажатие кнопки привязки,
        новый файл)."""
        canvas = getattr(self, "video_widget", None)
        if isinstance(canvas, VideoCanvas) and canvas.has_track_preview():
            canvas.set_track_preview(None)
            self._set_cut_status("")
            self.log_label.setText("Готово")
        self._trk_spec = None

    def _render_track_overlay(self, trim_in=None, trim_out=None):
        """Экспорт видео с накладкой по УЖЕ посчитанной траектории (отслеживать
        заново нечего, этап только кодирующий). trim_in/trim_out — выделенный в
        Монтаже отрезок: «Обрезать» с активной накладкой и режет, и вшивает."""
        spec = getattr(self, "_trk_spec", None)
        if not spec or getattr(self, "_trk_running", False):
            return
        src = spec["src"]
        if not os.path.exists(src):
            return
        base = Path(src)
        out_dir = (Path(self.export_dir)
                   if (self.export_dir and os.path.isdir(self.export_dir))
                   else base.parent)
        suffix = base.suffix.lower()
        if suffix not in (".mp4", ".mkv", ".mov", ".m4v"):
            suffix = ".mp4"
        out_path = str(out_dir / f"{base.stem}_привязка{suffix}")
        if os.path.exists(out_path):
            out_path = _unique_output(out_path)

        has_audio = getattr(self, "audio_stream_index", None) is not None
        # hardsub-профиль: у текста и краёв картинки резкие границы, на «fast»/
        # высоком CRF они мылятся — берём тот же профиль, что при вшивании субтитров.
        venc = self._video_encoder_args(hardsub=True)
        # Экспорт накладки идёт своим путём (кадры собираются в python), поэтому
        # фильтры обычной обрезки к нему не применяются — честно предупреждаем,
        # а не делаем вид, что кадрирование/пикселизация учтены.
        if (self._video_crop_filter() is not None
                or getattr(self, "_pixelize_active", False)):
            msgbox_information(
                self, "Только накладка",
                "Сейчас в файл уйдёт видео с привязанной накладкой — "
                "кадрирование и пикселизация в этот экспорт не попадут. "
                "Сначала сохраните их обычной обрезкой, а привязку сделайте "
                "уже по готовому файлу.")

        self._trk_running = True
        self._set_track_export_busy(True)
        self._report_progress(-1, "Привязка к объекту…")
        self._set_cut_status("Привязка к объекту… подготовка",
                             icon='fa5s.hourglass-half')
        self.log_label.setText("Наложение на кадры…")

        self._trk_worker = TrackOverlayWorker(
            src, out_path, venc, has_audio, spec["fps"],
            (spec["src_w"], spec["src_h"]), float(self.duration),
            spec["box"], spec["start_s"], spec["end_s"], spec["overlay_bgra"],
            anchor=spec["anchor"], off_x=spec["off_x"], off_y=spec["off_y"],
            scale_with_box=spec["scale_with_box"], smooth=spec["smooth"],
            boxes=spec.get("boxes"), trim_in=trim_in, trim_out=trim_out,
            static_overlays=self._static_overlays_bgra(spec["src_w"],
                                                       spec["src_h"]))
        self._trk_worker.progress.connect(self._on_trk_progress)
        self._trk_worker.done.connect(self._on_trk_done)
        self._trk_worker.failed.connect(self._on_trk_failed)
        self._trk_worker.start()

    def _cancel_track_overlay(self):
        """Просит фоновый воркер прерваться (временные файлы он уберёт сам)."""
        w = getattr(self, "_trk_worker", None)
        if w is not None and w.isRunning():
            self._set_cut_status("Отмена…", icon='fa5s.hourglass-half')
            if getattr(self, "btn_track_object", None) is not None:
                self.btn_track_object.setEnabled(False)
            w.cancel()

    def _on_trk_progress(self, pct, text):
        self._report_progress(pct, text)
        self._set_cut_status(text, icon='fa5s.crosshairs' if pct >= 0
                             else 'fa5s.hourglass-half')

    def _set_track_export_busy(self, busy):
        """На время отслеживания/рендера «Обрезать» превращается в «Отмена» (как
        при обычном экспорте), а кнопка привязки выключается."""
        b = getattr(self, "btn_track_object", None)
        if b is not None:
            b.setEnabled(not busy)
        self._set_cut_btn_cancel(busy, self._cancel_track_overlay)

    def _finish_track_overlay(self):
        self._trk_running = False
        self._trk_worker = None
        self._set_track_export_busy(False)
        self._update_media_buttons()

    def _on_trk_done(self, final_path):
        self._finish_track_overlay()
        # Файл готов — накладка-предпросмотр больше не нужна.
        self._clear_track_preview()
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"Накладка привязана к объекту: {final_path}")
        except Exception:
            pass
        self.on_ffmpeg_finished(True, "Готово")

    def _on_trk_failed(self, message):
        self._finish_track_overlay()
        self.on_ffmpeg_finished(False, message)

    # ── Удаление исходного файла ─────────────────────────────────────────────
    def delete_source_file(self):
        """Удаляет загруженный исходный файл с диска (с подтверждением). Перед
        удалением освобождает файл (останавливает плеер и снимает источник),
        иначе Windows не даст удалить открытый файл."""
        src = self.actual_source_file or self.filepath
        if not src or not os.path.exists(str(src)):
            return
        src = str(src)
        name = os.path.basename(src)
        reply = msgbox_question(
            self, "Удалить исходный файл?",
            "Файл будет удалён с диска без возможности восстановления:\n\n"
            f"{name}\n\nПродолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        # Останавливаем фоновую сборку прокси (если идёт): иначе её ffmpeg будет
        # держать temp-файл, а finished-слот выстрелит уже после очистки. Сам слот
        # дополнительно защищён проверкой actual_source_file is None.
        try:
            if self.proxy_thread and self.proxy_thread.isRunning():
                self.proxy_thread.stop(); self.proxy_thread.wait()
        except Exception: pass
        self.proxy_thread = None
        # Освобождаем файл: останавливаем воспроизведение и снимаем источник.
        try: self.player.stop()
        except Exception: pass
        try: self.player.setSource(QUrl())
        except Exception: pass
        try:
            if getattr(self, "seek_preview", None) is not None:
                self.seek_preview.set_source(None)
        except Exception: pass
        try: QApplication.processEvents()
        except Exception: pass
        try:
            os.remove(src)
        except Exception as e:
            msgbox_critical(self, "Ошибка", f"Не удалось удалить файл:\n{e}")
            return
        # Сбрасываем состояние редактора (файл больше не загружен).
        self.actual_source_file = None
        self.filepath = None
        self.duration = 0.0
        try:
            if hasattr(self.video_widget, "clear_frame"):
                self.video_widget.clear_frame()
        except Exception: pass
        try: self.waveform.set_data([], 0.0)
        except Exception: pass
        try: self._update_media_buttons()
        except Exception: pass
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(f"🗑 Исходный файл удалён: {name}")
        except Exception: pass

    # ── Полноэкранный режим ─────────────────────────────────────────────────
    def toggle_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            self.exit_fullscreen()
        else:
            self.enter_fullscreen()

    def enter_fullscreen(self):
        if getattr(self, "_fs_window", None) is not None:
            return
        if self.duration <= 0.1:   # нет загруженного видео
            return
        try:
            fs = FullscreenVideo(self)
            # fs — самостоятельное окно без родителя (иначе showFullScreen на
            # дочернем виджете ведёт себя иначе), поэтому Qt может открыть его
            # fullscreen'ом на ПЕРВИЧНОМ мониторе, даже если само приложение
            # (и мышь пользователя) сейчас на другом. Явно ставим тот же экран,
            # где сейчас окно приложения — заодно фиксирует QScreen ДО первого
            # show(), от чего зависит и корректный клэмп tooltip'ов панели
            # управления (см. FullscreenVideo._relayout).
            try:
                src_screen = self.window().windowHandle().screen()
            except Exception:
                src_screen = None
            if src_screen is not None:
                fs.winId()   # форсирует создание нативного хэндла ДО setScreen
                wh = fs.windowHandle()
                if wh is not None:
                    wh.setScreen(src_screen)
            # Снимаем фиксированные размеры с видео и переносим его в окно.
            self.video_widget.setMinimumSize(0, 0)
            self.video_widget.setMaximumSize(16777215, 16777215)
            fs.attach_video(self.video_widget)
            self._fs_window = fs
            self.btn_fullscreen.setIcon(_fullscreen_icon(expand=False))
            self.btn_fullscreen.setToolTip("Свернуть (Esc / двойной клик по видео)")
            fs.showFullScreen()
            # Без этого клавиши (F/Esc/Space/стрелки) не доходили до окна: после
            # showFullScreen() фокус клавиатуры мог оставаться на виджете, у
            # которого он был ДО входа в полноэкранный режим (например, на
            # волне/поле ссылки в основном окне) — F там ничего не делал.
            fs.activateWindow()
            fs.setFocus(Qt.FocusReason.OtherFocusReason)
            fs.sync_from_player()
            fs.sync_volume()
            fs.update_play_icon(
                self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
            # Холст переехал в другое окно, а с ним и его сцена Qt Quick:
            # графический контекст пересоздан, и показанный кадр в нём не
            # переживает переезд. На паузе кадров от плеера больше не будет —
            # ставим точный кадр заново (на воспроизведении метод сам ничего не
            # делает: там следующий кадр приедет через ~16 мс).
            QTimer.singleShot(0, self._restore_canvas_frame)
            try:
                self._update_subtitle(self.player.position() / 1000.0)
                QTimer.singleShot(0, self._position_overlay)
            except Exception:
                pass
        except Exception as e:
            self.main.log(f"enter_fullscreen error: {e}")
            self._fs_window = None

    def exit_fullscreen(self):
        fs = getattr(self, "_fs_window", None)
        if fs is None:
            return
        self._fs_window = None
        try:
            # Возвращаем видео обратно в контейнер вкладки.
            self.vc_layout.insertWidget(0, self.video_widget, 0, Qt.AlignmentFlag.AlignCenter)
            self.video_widget.show()
        except Exception:
            pass
        # Оверлей субтитров мог стать дочерним к окну fs — вернём его главному
        # окну ДО удаления fs, иначе Qt удалит оверлей вместе с fs.
        try:
            if self.sub_overlay is not None:
                self._reparent_overlay(self.window())
        except Exception:
            pass
        try:
            fs.close(); fs.deleteLater()
        except Exception:
            pass
        try:
            self.btn_fullscreen.setIcon(_fullscreen_icon(expand=True))
            self.btn_fullscreen.setToolTip("Полноэкранный режим (F / двойной клик по видео)")
            self._adjust_video_height()
            QTimer.singleShot(0, self._position_overlay)
            # Обратный переезд — та же история, что и при входе (см. там).
            QTimer.singleShot(0, self._restore_canvas_frame)
        except Exception:
            pass

    def _restore_canvas_frame(self):
        """Возвращает кадр на холст после переезда в другое окно.

        Нужен только на паузе: сцена холста теряет показанный кадр вместе с
        графическим контекстом, а новых кадров плеер на паузе не шлёт. Точный
        кадр берётся из того же предекодера, что и при покадровом шаге, так что
        на экране оказывается ровно тот кадр, на котором стояли."""
        try:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                return
        except Exception:
            return
        try:
            self._show_exact_frame(self._frame_idx)
        except Exception:
            pass

    def _fs_sync_position(self):
        """Обновляет полосу/тайминги в полноэкранном окне (вызывается из sync_ui
        и on_position_changed, когда оно открыто)."""
        fs = getattr(self, "_fs_window", None)
        if fs is not None:
            try:
                fs.sync_from_player()
            except Exception:
                pass

    # ── Покадровый движок: кадры, часы, буфер ────────────────────────────────
    def _frames_engine(self):
        """Ленивая инициализация предекодера кадров (поток создаётся при первом
        файле с видео, а не при запуске приложения)."""
        eng = getattr(self, "_frames", None)
        if eng is None:
            eng = FramePrefetcher(self)
            eng.ready.connect(self._on_exact_frame)
            eng.start()
            self._frames = eng
        return eng

    def _frames_set_source(self):
        """Переводит предекодер на ТОТ ЖЕ файл, что играет плеер (оригинал или
        превью-прокси): стоп-кадр обязан выглядеть ровно так же, как
        воспроизведение, иначе на паузе картинка «дёргалась» бы в резкость."""
        src = str(self.filepath) if self.filepath else None
        has_video = (self.video_stream_index is not None
                     and not getattr(self, "is_still_image", False))
        if not has_video or not src:
            eng = getattr(self, "_frames", None)
            if eng is not None:
                eng.set_source(None)
            self._frames_src = None
            return
        eng = self._frames_engine()
        eng.set_source(src, self.fps or 0.0)
        self._frames_src = src

    def _refresh_frame_grid(self):
        """Пересобирает сетку кадров (fps/длительность могли измениться)."""
        self._grid = FrameGrid(self.fps or 0.0, self.duration or 0.0)

    def _current_frame_index(self):
        """Номер кадра, на котором СЕЙЧАС стоит монтаж.

        На паузе истина — _frame_idx (его ведут seek/шаг/остановка): позиция
        плеера после seek'а может отличаться от запрошенной на доли кадра, и
        считать шаг от неё значило бы копить ту же ошибку, что и раньше.
        Во время воспроизведения истина — pts ПОКАЗАННОГО кадра (часы кадра),
        и только если их нет (аудиофайл, overlay-режим) — позиция плеера."""
        grid = self._grid
        if not grid.valid:
            return 0
        try:
            playing = (self.player.playbackState()
                       == QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        if not playing and self._frame_idx is not None:
            return grid.clamp(self._frame_idx)
        vw = getattr(self, "video_widget", None)
        if isinstance(vw, VideoCanvas):
            pts = vw.last_frame_pts()
            if pts is not None:
                return grid.index_of_pts(pts)
        try:
            return grid.index_at(self.player.position() / 1000.0)
        except Exception:
            return 0

    def _clock_pos_s(self):
        """Время монтажа для ИНТЕРФЕЙСА — то, что реально видно на экране.

        Мастер-часы: во время игры это pts последнего показанного кадра (Qt
        рендерит кадры по аудио-часам, так что метка идёт за звуком, но при этом
        гарантированно совпадает с картинкой); на паузе — начало кадра, который
        пришпилен к холсту. Раньше метка жила по player.position(), который
        опрашивался таймером раз в 80 мс и к картинке отношения не имел — отсюда
        и ощущение, что видео, звук и метка разъезжаются."""
        try:
            pos_s = self.player.position() / 1000.0
        except Exception:
            pos_s = 0.0
        vw = getattr(self, "video_widget", None)
        if (not isinstance(vw, VideoCanvas) or self.video_stream_index is None
                # «Только звук»: кадров нет вовсе, часы кадра застыли бы на
                # последнем показанном — ведём время по плееру, как для аудио.
                or getattr(self, "_audio_only_mode", False)):
            return pos_s
        pts = vw.last_frame_pts()
        if pts is None:
            return pos_s
        age = vw.frame_clock_age()
        try:
            playing = (self.player.playbackState()
                       == QMediaPlayer.PlaybackState.PlayingState)
        except Exception:
            playing = False
        if playing:
            # Часы кадра «живые» — берём их. Если кадры перестали приходить
            # (декодер захлебнулся/нет видео) — возвращаемся к часам плеера,
            # иначе метка замерла бы вместе с картинкой.
            if age is not None and age < 0.35:
                return pts
            return pos_s
        # На паузе показанный кадр и есть текущее время — но только если он
        # действительно наш (пин с картинкой, часы в его диапазоне), а не
        # случайный кадр после смены источника: заявленный, но не приехавший пин
        # раньше отдавал pts ПРОШЛОГО кадра, и метка «замерзала» на нём.
        pinned = vw.pinned_frame_pts()
        if pinned is not None:
            return pinned
        return pos_s

    def _show_exact_frame(self, idx=None, direction=1):
        """Ставит на холст ТОЧНЫЙ кадр idx и заказывает соседние в буфер.

        Кадр из буфера рисуется мгновенно (0 мс, без ожидания плеера), чего от
        QMediaPlayer добиться нельзя в принципе; если кадра ещё нет — «пин»
        просто объявляет, какой кадр сейчас правильный, и холст перестаёт
        показывать чужие кадры, как только точный доедет."""
        grid = self._grid
        vw = getattr(self, "video_widget", None)
        if (not grid.valid or not isinstance(vw, VideoCanvas)
                or self.video_stream_index is None
                or getattr(self, "is_still_image", False)
                # «Только звук»: картинки нет — гонять ffmpeg за кадрами незачем
                # (ровно от этой работы пользователь и уходит, включая режим).
                or getattr(self, "_audio_only_mode", False)):
            return
        # Во время НАСТОЯЩЕГО воспроизведения пин не ставим ни при каких
        # обстоятельствах (например, стрелка нажата на ходу): иначе холст начал
        # бы отбрасывать кадры плеера как чужие и картинка бы встала. Прогрев
        # («с разбега») — исключение: там играем мы сами и как раз прячем разбег.
        try:
            if (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                    and not getattr(self, "_prerolling", False)):
                return
        except Exception:
            pass
        idx = self._current_frame_index() if idx is None else grid.clamp(idx)
        span = grid.pts_span_us(idx)
        vw.arm_frame_pin(span)
        eng = self._frames_engine()
        if self._frames_src != (str(self.filepath) if self.filepath else None):
            self._frames_set_source()
        img = eng.frame(idx)
        if img is not None:
            vw.set_exact_frame(img, span, int(grid.start_of(idx) * 1_000_000))
        # Буфер вокруг плейхеда: шагаем вперёд — греем кадры впереди, назад —
        # позади. Сам кадр idx всегда декодируется первым (см. FramePrefetcher).
        if direction >= 0:
            eng.request(idx, ahead=8, behind=3)
        else:
            eng.request(idx, ahead=2, behind=8)

    def _paint_playhead(self, t_s):
        """Рисует положение плейхеда: метка времени, полоса, жёлтая линия на
        волне, «старт→плейхед» и полноэкранная панель. Одно место на все
        источники времени (кадр, позиция плеера, точный кадр из буфера)."""
        self.lbl_current_time.setText(s_to_time(t_s))
        if self.duration and self.duration > 0 and not self.slider.is_user_seeking():
            self.slider.blockSignals(True)
            self.slider.setValue(int((t_s / self.duration) * 1000))
            self.slider.blockSignals(False)
        self.waveform.set_playhead(t_s)
        self._update_seg_duration(t_s)
        self._fs_sync_position()

    def _on_exact_frame(self, idx, img):
        """Точный кадр доехал из предекодера — показываем, если монтаж всё ещё
        стоит на нём (иначе это устаревший результат прошлого шага)."""
        try:
            # Прогрев — не воспроизведение: там играем мы сами, под mute, и кадр
            # цели на холсте нужен именно наш (иначе, пока идёт разбег, экран
            # остался бы на старом кадре — а пользователь его уже перемотал).
            if (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
                    and not getattr(self, "_prerolling", False)):
                return
        except Exception:
            return
        if self._frame_idx is None or int(idx) != int(self._frame_idx):
            return
        vw = getattr(self, "video_widget", None)
        if not isinstance(vw, VideoCanvas) or not self._grid.valid:
            return
        vw.set_exact_frame(img, self._grid.pts_span_us(idx),
                           int(self._grid.start_of(idx) * 1_000_000))
        # Кадр сменился — метка/полоса/волна обязаны показать ЕГО время.
        self._paint_playhead(self._grid.start_of(idx))

    def step_frame(self, step):
        if not self.duration:
            return
        grid = self._grid
        if not grid.valid:
            # fps неизвестен (битые метаданные) — старое поведение по времени.
            ms = (self._scrub_target if (getattr(self, "_scrubbing", False)
                                         and self._scrub_target is not None)
                  else self.player.position())
            new_ms = max(0, min(int(self.duration * 1000), ms + int(step * 40)))
            self._scrub_target = new_ms
            self._scrub_audio_ms = new_ms
            self._dispatch_frame_seek(new_ms)
            return
        # Шаг считаем в КАДРАХ от текущего кадра — не в миллисекундах от позиции
        # плеера. Так серия шагов (удержание ←/→) детерминирована и не копит
        # ошибку округления, а «туда-обратно» возвращает ровно тот же кадр.
        idx = grid.clamp(self._current_frame_index() + int(step))
        self._frame_idx = idx
        # Плееру отдаём СЕРЕДИНУ кадра: она дальше полукадра от границ, поэтому
        # округление до миллисекунд не может перекинуть его на соседний кадр.
        new_ms = grid.ms_of(idx)
        self._scrub_target = new_ms
        # А звук скраба начинается с НАЧАЛА кадра — там же, где картинка.
        self._scrub_audio_ms = int(round(grid.start_of(idx) * 1000.0))
        # Кадр на холст — сразу из буфера (не ждём плеер).
        self._show_exact_frame(idx, direction=step)
        # Реальный player.setPosition() диспетчеризуем через _dispatch_frame_seek:
        # держать ←/→ = автоповтор ОС шлёт events быстрее, чем плеер успевает
        # довести seek до кадра, и они раньше просто копились в очереди — отсюда
        # «догоняющий» скачок на несколько секунд ПОСЛЕ отпускания клавиши.
        # Теперь в полёте не больше одного seek'а: новая цель ЗАМЕНЯЕТ предыдущую
        # отложенную, и в итоге всегда доезжаем ровно до последней зажатой цели.
        self._dispatch_frame_seek(new_ms)

    def _dispatch_frame_seek(self, new_ms):
        if getattr(self, "_frame_seek_busy", False):
            self._frame_seek_pending = new_ms   # копим только САМУЮ СВЕЖУЮ цель
            return
        self._frame_seek_busy = True
        self._frame_seek_target_ms = new_ms
        self._frame_seek_gen = getattr(self, "_frame_seek_gen", 0) + 1
        gen = self._frame_seek_gen
        self.player.setPosition(new_ms)
        self._ext_audio_seek(new_ms)
        # Запасной выход — ТОЛЬКО если on_position_changed сам не подтвердит
        # доезд до цели (см. _confirm_frame_seek). Окно щедрое (не 100-200мс):
        # на тяжёлом HEVC без ближайшего кейфрейма один seek может декодировать
        # секунду и дольше, а слишком короткий запасной таймер сам стал бы
        # источником бага — «отпускал» бы busy раньше, чем предыдущий seek
        # реально доехал, и держащаяся стрелка перебивала бы декодирование
        # снова и снова, так и не давая ни одному кадру долистать до конца
        # (ровно то поведение — «зажал на 10с, показали 1 кадр» — которое
        # чиним). gen — чтобы устаревший запасной таймер не «отпустил» уже
        # ДРУГОЙ, более поздний seek.
        QTimer.singleShot(2500, lambda: self._release_frame_seek(gen))

    def _confirm_frame_seek(self, pos_ms):
        """Вызывается из on_position_changed на каждое реальное изменение позиции:
        как только плеер довёл её до запрошенной цели — освобождаем «в полёте»
        сразу, не дожидаясь запасного таймера (и шлём накопившуюся свежую цель,
        если пользователь всё ещё держит стрелку)."""
        if not getattr(self, "_frame_seek_busy", False):
            return
        target = getattr(self, "_frame_seek_target_ms", None)
        if target is None:
            return
        tol_ms = max(20, int(1000.0 / self.fps)) if (self.fps and self.fps > 0) else 40
        if abs(pos_ms - target) <= tol_ms:
            self._release_frame_seek(self._frame_seek_gen)

    def _release_frame_seek(self, gen=None):
        if gen is not None and gen != getattr(self, "_frame_seek_gen", None):
            return   # устаревший вызов — «в полёте» уже другая, более поздняя цель
        self._frame_seek_busy = False
        self._frame_seek_target_ms = None
        pending = getattr(self, "_frame_seek_pending", None)
        if pending is not None:
            self._frame_seek_pending = None
            self._dispatch_frame_seek(pending)

    def step_frame_scrub(self, step):
        # Идёт беззвучный прогрев — гасим его ДО шага: иначе плеер играет (пусть
        # и под mute), а мы тут же дёргаем ему позицию, и они мешают друг другу.
        # Именно cancel, а не finish: доводить позицию до УСТАРЕВШЕЙ цели незачем,
        # шаг сейчас поставит свою — лишний seek только съел бы кадр времени.
        # Прогрев вернётся, когда серия шагов утихнет (см. _end_scrub_painted).
        if getattr(self, "_prerolling", False):
            self._preroll_cancel()
        playing = (self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState)
        painted = isinstance(self.video_widget, VideoCanvas)
        # Серия шагов: при удержании ←/→ считаем от _scrub_target (детерминизм),
        # а на ПЕРВОМ шаге серии — от живой позиции плеера.
        if not playing and not getattr(self, "_scrubbing", False):
            self._scrub_target = None
        if not playing:
            self._scrubbing = True
        self.step_frame(step)
        if playing:
            return
        # Скраб-звук (как в Filmora): короткий звуковой блип в новой позиции.
        # В painted-режиме видео уже доставлено setPosition'ом — звук добавляем,
        # не трогая кадр (см. _scrub_audio_blip).
        self._scrub_audio_blip(painted)
        # Оживляем индикатор уровня и на покадровом шаге (на паузе он иначе молчит,
        # из-за чего казалось, что звука нет).
        tgt_ms = getattr(self, "_scrub_audio_ms", None)
        if tgt_ms is None:
            tgt_ms = (self._scrub_target if self._scrub_target is not None
                      else self.player.position())
        self._update_meter((tgt_ms or 0) / 1000.0, force=True)
        if painted:
            # painted-режим (VideoCanvas + QVideoSink): пауза + setPosition сама
            # доставляет новый кадр в сink — короткий play() НЕ нужен (именно он
            # давал мерцание/скачок назад-вперёд). Флаг скраба снимаем таймером,
            # перезапускаемым на каждом шаге (серия удержания не рвётся).
            if not hasattr(self, "_scrub_reset_timer"):
                self._scrub_reset_timer = QTimer(self)
                self._scrub_reset_timer.setSingleShot(True)
                self._scrub_reset_timer.timeout.connect(self._end_scrub_painted)
            self._scrub_reset_timer.start(160)
            return
        # overlay-режим (QVideoWidget): нативная поверхность без play() кадр не
        # перерисовывает — прежний приём с коротким play() и возвратом на цель.
        self._scrubbing = True
        self.player.play()
        QTimer.singleShot(60, self._end_scrub)

    def _end_scrub_painted(self):
        self._scrubbing = False
        # Серия покадровых шагов закончилась — прогреваем конвейер там, где
        # встали. Обычный сценарий монтажа «долистал кадрами → Пробел» после
        # этого стартует без заминки (см. _preroll_at). Ни звука (mute), ни
        # движения на шкале (часы заморожены на цели) прогрев не даёт.
        try:
            if (self.player.playbackState()
                    != QMediaPlayer.PlaybackState.PlayingState):
                self._preroll_at(self._playhead_target_s())
        except Exception:
            pass

    # ── Скраб-звук при покадровой перемотке ─────────────────────────────────
    # Длина «блипа»: кадр, но не короче — на 60 fps один кадр (16.7 мс) на слух
    # почти щелчок. При удержании клавиши срезы идут подряд и складываются в
    # непрерывную перемотку по звуку, как в монтажках.
    _SCRUB_BLIP_MIN_S = 0.045
    _SCRUB_BLIP_MAX_S = 0.120

    def _scrub_audio_engine(self):
        """Лениво поднимает фоновый декодер PCM вокруг плейхеда."""
        eng = getattr(self, "_audio_scrub", None)
        if eng is None:
            eng = AudioScrubber(self)
            eng.ready.connect(self._on_scrub_audio_window)
            eng.start()
            self._audio_scrub = eng
        return eng

    def _scrub_audio_source(self):
        """(файл, поток) для скраб-звука: внешняя озвучка, если выбрана, иначе
        ОРИГИНАЛ (не прокси: у прокси звук пережат в AAC, а дорожка может быть
        и не одна). Поток — абсолютный индекс выбранной дорожки, чтобы звук шага
        совпадал с тем, что играет плеер."""
        ext = getattr(self, "selected_audio_ext_path", None)
        if ext:
            return (str(ext), "a:0")
        src = getattr(self, "actual_source_file", None)
        if not src:
            return (None, "a:0")
        idx = getattr(self, "selected_audio_abs_index", None)
        return (str(src), str(int(idx)) if idx is not None else "a:0")

    def _sync_scrub_audio_source(self):
        """Держит источник скраб-звука в согласии с выбранной дорожкой."""
        src, stream = self._scrub_audio_source()
        if not src:
            return None
        eng = self._scrub_audio_engine()
        if eng.source() != (src, stream):
            fmt = self._scrub_sink_format()
            if fmt is not None:
                eng.configure(fmt.sampleRate(), fmt.channelCount(),
                              4 if fmt.sampleFormat() == QAudioFormat.SampleFormat.Float else 2)
            eng.set_source(src, stream)
        return eng

    def _scrub_sink_format(self):
        """Формат вывода для скраб-звука (создаётся один раз под устройство)."""
        fmt = getattr(self, "_scrub_fmt", None)
        if fmt is not None:
            return fmt
        if QAudioFormat is None or QMediaDevices is None:
            return None
        try:
            dev = QMediaDevices.defaultAudioOutput()
            if dev is None or dev.isNull():
                return None
            fmt = QAudioFormat()
            fmt.setSampleRate(48000)
            fmt.setChannelCount(2)
            fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            if not dev.isFormatSupported(fmt):
                # Устройство не тянет 48 кГц/16 бит — берём его собственный
                # формат и просим ffmpeg отдавать PCM ровно в нём.
                fmt = dev.preferredFormat()
            self._scrub_fmt = fmt
            return fmt
        except Exception:
            return None

    def _scrub_sink(self):
        """QAudioSink для блипов (push-режим). Открывается один раз и живёт:
        pause/play у QMediaPlayer заново открывали бы аудиоустройство, а это на
        Windows заметная задержка — здесь же запись в устройство слышна через
        1–9 мс (замерено)."""
        sink = getattr(self, "_scrub_sink_obj", None)
        if sink is not None:
            return sink
        if QAudioSink is None:
            return None
        fmt = self._scrub_sink_format()
        if fmt is None:
            return None
        try:
            dev = QMediaDevices.defaultAudioOutput()
            sink = QAudioSink(dev, fmt, self)
            # Буфер с запасом на пару срезов: сама задержка звука от него не
            # зависит (устройство играет то, что в очереди, а очередь мы держим
            # короткой — см. _play_scrub_slice), зато длинный срез влезает
            # целиком и не режется.
            bytes_per_s = fmt.sampleRate() * fmt.channelCount() * fmt.bytesPerSample()
            sink.setBufferSize(max(4096, int(bytes_per_s * 0.25)))
            sink.setVolume(self._scrub_volume())
            self._scrub_sink_obj = sink
            # start() стоит ~45 мс (поднимается сеанс WASAPI) — поэтому делаем
            # его РОВНО ОДИН РАЗ, при первом обращении, а дальше только пишем в
            # устройство (запись — 0 мс). Именно поэтому здесь нет ни stop(), ни
            # reset() на каждый шаг: они убивают QIODevice, и следующий шаг
            # платил бы за start() те же 45 мс задержки перед звуком.
            self._scrub_sink_io = sink.start()
            return sink
        except Exception:
            self._scrub_sink_obj = None
            self._scrub_sink_io = None
            return None

    def _scrub_volume(self):
        try:
            return max(0.0, min(1.0, self.vol_slider.value() / 100.0))
        except Exception:
            return 1.0

    def _scrub_blip_seconds(self):
        """Длина блипа: ровно кадр, но в разумных пределах слышимости."""
        fps = float(self.fps or 0.0)
        one = (1.0 / fps) if fps > 0 else self._SCRUB_BLIP_MIN_S
        return max(self._SCRUB_BLIP_MIN_S, min(self._SCRUB_BLIP_MAX_S, one))

    def _scrub_audio_time_s(self):
        """Время, с которого обязан звучать шаг, — НАЧАЛО показанного кадра
        (плееру мы отдаём середину кадра, но слышно должно быть то же, что
        видно). Берём его из НОМЕРА кадра, а не из округлённых миллисекунд."""
        if self._grid.valid and self._frame_idx is not None:
            return self._grid.start_of(self._frame_idx)
        ms = getattr(self, "_scrub_audio_ms", None)
        if ms is None:
            ms = getattr(self, "_scrub_target", None)
        if ms is None:
            try:
                ms = self.player.position()
            except Exception:
                return None
        return max(0.0, ms / 1000.0)

    def _scrub_audio_blip(self, painted=True):
        """Короткий звук нового кадра: точный PCM-срез с pts кадра в устройство.

        В overlay-режиме (QVideoWidget) кадр доставляется коротким play()
        основного плеера, который несёт и звук, — там мы молчим. Исключение —
        выбранная внешняя озвучка: звук видео тогда заглушён, и слышно только
        то, что сыграем здесь."""
        if not getattr(self, "_scrub_audio_enabled", True):
            return
        if not painted and not getattr(self, "_ext_audio_active", False):
            return
        t_s = self._scrub_audio_time_s()
        if t_s is None:
            return
        eng = self._sync_scrub_audio_source()
        if eng is None:
            return
        eng.request(t_s)                    # окно вокруг плейхеда — заранее
        data = eng.slice_at(t_s, self._scrub_blip_seconds())
        if data:
            self._play_scrub_slice(data)
            self._scrub_wait = None
            return
        # Окна ещё нет (первый шаг после загрузки/перемотки) — доиграем, как
        # только фоновый декодер его принесёт (см. _on_scrub_audio_window).
        # Раньше в этом месте звука просто не было — жалоба «при AV1 звук на
        # шаге появляется не всегда».
        self._scrub_wait = (t_s, time.monotonic())

    def _on_scrub_audio_window(self):
        """Окно PCM доехало: если шаг был только что и с тех пор никуда не
        ушли — играем его звук с опозданием, а не молчим."""
        pending = getattr(self, "_scrub_wait", None)
        self._scrub_wait = None
        if not pending or not getattr(self, "_scrub_audio_enabled", True):
            return
        t_s, at = pending
        if time.monotonic() - at > 0.4:
            return                          # поздно, звук был бы «из прошлого»
        cur = self._scrub_audio_time_s()
        if cur is None or abs(cur - t_s) > 0.001:
            return                          # плейхед уже ушёл — играть нечего
        eng = getattr(self, "_audio_scrub", None)
        data = eng.slice_at(t_s, self._scrub_blip_seconds()) if eng else None
        if data:
            self._play_scrub_slice(data)

    def _play_scrub_slice(self, data):
        """Пишет срез в аудиоустройство, НЕ давая очереди расти.

        Очередь длиннее одного среза — это и есть «звук уехал вперёд»: при
        удержании клавиши шаги идут чаще, чем звук успевает проигрываться, и
        хвост копится, а следующий шаг слышится уже с опозданием. Поэтому
        пишем ровно столько, сколько успело проиграться: одиночный шаг звучит
        целиком, а удержание даёт непрерывную перемотку по звуку, отстающую от
        картинки не больше чем на срез."""
        sink = self._scrub_sink()
        io = getattr(self, "_scrub_sink_io", None)
        if sink is None or io is None:
            return
        try:
            sink.setVolume(self._scrub_volume())
            free = int(sink.bytesFree())
            pending = max(0, int(sink.bufferSize()) - free)
            budget = min(free, len(data) - pending)
            if budget <= 0:
                return              # предыдущий срез ещё звучит — не наслаиваем
            io.write(data[:budget])
        except Exception:
            # Устройство могло пропасть (наушники выдернули) — пересоберём.
            self._release_scrub_sink()

    def _release_scrub_sink(self):
        sink = getattr(self, "_scrub_sink_obj", None)
        self._scrub_sink_obj = None
        self._scrub_sink_io = None
        self._scrub_fmt = None
        if sink is not None:
            try:
                sink.stop()
            except Exception:
                pass
            try:
                sink.deleteLater()
            except Exception:
                pass

    def _stop_scrub_audio_blip(self):
        """Обрывает звучащий срез (выключение скраб-звука в Настройках).
        reset() уничтожает QIODevice устройства, поэтому сразу берём новый —
        иначе следующий блип писал бы в мёртвый объект."""
        sink = getattr(self, "_scrub_sink_obj", None)
        if sink is None:
            return
        try:
            sink.reset()
            self._scrub_sink_io = sink.start()
        except Exception:
            self._release_scrub_sink()

    def set_scrub_audio(self, enabled, save=True):
        """Вкл/выкл скраб-звук при покадровой перемотке (из Настроек)."""
        self._scrub_audio_enabled = bool(enabled)
        if not enabled:
            self._stop_scrub_audio_blip()
        if save:
            try:
                self.save_settings()
            except Exception:
                pass

    def _end_scrub(self):
        self.player.pause()
        # play() ушёл вперёд на ~2 кадра — возвращаем плеер РОВНО на целевой кадр,
        # иначе шаг назад визуально «отскакивал» вперёд (баг).
        tgt = getattr(self, "_scrub_target", None)
        if tgt is not None:
            self.player.setPosition(int(tgt))
            self._ext_audio_seek(int(tgt))
        # Сбрасываем флаг после того, как событие паузы будет обработано.
        QTimer.singleShot(40, lambda: setattr(self, "_scrubbing", False))

    # ── Export / Cut ──────────────────────────────────────────────────────
    def _available_encoders(self):
        """Строка `ffmpeg -encoders` (детект один раз, кэшируется). Пустая строка
        трактуется как «всё доступно» (не смогли опросить сборку)."""
        cache = getattr(self, "_encoders_str", None)
        if cache is not None:
            return cache
        encoders = ""
        try:
            p = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=CREATE_NO_WINDOW)
            encoders = p.stdout or ""
        except Exception:
            encoders = ""
        self._encoders_str = encoders
        return encoders

    def _gpu_encoder_args(self, encoders, hardsub=False):
        """Первый доступный аппаратный (GPU) H.264-кодировщик, иначе None.
        При hardsub (вшивание субтитров) поджимаем качество, чтобы края текста
        не мылились."""
        q = 18 if hardsub else 20
        if "h264_nvenc" in encoders:
            return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", str(q)]
        if "h264_qsv" in encoders:
            return ["-c:v", "h264_qsv", "-global_quality", str(q)]
        if "h264_amf" in encoders:
            return ["-c:v", "h264_amf", "-quality", "balanced", "-rc", "cqp",
                    "-qp_i", str(q), "-qp_p", str(q)]
        if "h264_mf" in encoders:
            qual = 80 if hardsub else 70
            return ["-c:v", "h264_mf", "-rate_control", "quality", "-quality", str(qual)]
        return None

    def _video_encoder_args(self, hardsub=False):
        """Подбирает H.264-кодировщик в bundled ffmpeg с учётом выбора
        пользователя (combo «Кодировщик»): «Видеокарта (GPU)» — аппаратный
        кодек; «Процессор (CPU)» / «Авто» — libx264. Если выбранного варианта в
        сборке нет — мягкий откат (GPU↔CPU↔mpeg4), чтобы перекодировка всегда
        состоялась.

        hardsub=True (вшивание субтитров): берём чуть более качественный профиль —
        у текста резкие края, и на «fast»/высоком CRF они мылятся. CPU: preset
        medium + crf 17; добавляем -pix_fmt yuv420p для чёткого 8-битного вывода и
        совместимости. Аппаратные кодеки тоже поджимаем по качеству."""
        encoders = self._available_encoders()
        # 0 = Авто, 1 = Процессор (CPU), 2 = Видеокарта (GPU)
        try:
            choice = int(self.cmb_encoder.currentIndex())
        except Exception:
            choice = 0

        cpu_args = (["-c:v", "libx264", "-preset", "medium", "-crf", "17"]
                    if hardsub else ["-c:v", "libx264", "-preset", "fast", "-crf", "18"])
        cpu = cpu_args if ("libx264" in encoders or encoders == "") else None
        gpu = self._gpu_encoder_args(encoders, hardsub=hardsub)

        if choice == 2:                      # GPU — с откатом на CPU
            args = gpu or cpu
        elif choice == 1:                    # CPU — с откатом на GPU
            args = cpu or gpu
        else:                                # Авто: CPU (качество/совместимость)
            args = cpu or gpu
        if args is None:
            args = ["-c:v", "mpeg4", "-q:v", "3"]
        args = list(args)
        if hardsub and "-pix_fmt" not in args:
            args += ["-pix_fmt", "yuv420p"]
        return args

    def _subs_present_in_range(self, src, ext_sub, rel_idx, in_s, out_s):
        """True, если хотя бы одно событие субтитров видно в диапазоне [in_s, out_s].

        Через ffprobe читаем тайминги пакетов выбранной дорожки субтитров и
        проверяем пересечение [start, start+duration] с [in_s, out_s]. Если в
        отрезке субтитров нет, вшивать нечего → можно резать без перекодировки.
        При ошибке probe (или неизвестной длительности событий) возвращаем True —
        безопасный путь: вшиваем как обычно, чтобы не потерять субтитры."""
        if ext_sub:
            target, sel = str(ext_sub), "s:0"
        else:
            target, sel = str(src), f"s:{rel_idx}"
        cmd = [FFPROBE, "-v", "error", "-select_streams", sel,
               "-show_entries", "packet=pts_time,duration_time",
               "-of", "csv=p=0", target]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True,
                               encoding="utf-8", errors="replace",
                               creationflags=CREATE_NO_WINDOW, timeout=30)
        except Exception:
            return True
        if r.returncode != 0:
            return True
        for line in r.stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split(",")
            try:
                start = float(parts[0])
            except Exception:
                continue
            # Неизвестная длительность (N/A — напр. у битмап-субтитров) → берём
            # запас 10 с, чтобы скорее «оставить вшивание», чем ошибочно пропустить.
            try:
                dur = float(parts[1]) if len(parts) > 1 and parts[1] not in ("", "N/A") else 10.0
            except Exception:
                dur = 10.0
            if (start + dur) >= in_s and start <= out_s:
                return True
        return False

    def start_cut(self):
        if not self.actual_source_file or not self.actual_source_file.exists():
            msgbox_warning(self, "Внимание", "Файл не загружен.")
            return
        # Не запускаем вторую обрезку поверх уже идущей: иначе ссылка на прежний
        # рабочий поток терялась бы (его перетирал новый), и поток мог «висеть» —
        # отсюда баг «следующая обрезка не работает, надо перезапускать». Кнопка
        # на время обрезки и так выключена, но Ctrl+S мог обойти эту блокировку.
        # И быстрая обрезка (FfmpegWorker), и Smart Cut (SmartCutWorker) кладутся
        # в self.ffmpeg_thread — одной проверки достаточно.
        th = getattr(self, "ffmpeg_thread", None)
        if th is not None and th.isRunning():
            return

        # Режим картинки: «Обрезать» = собрать видео-проявление из картинки.
        if getattr(self, "is_still_image", False):
            self._export_still_pixelize()
            return

        in_s  = self.current_in
        out_s = self.current_out
        try:
            manual_in  = time_to_s(self.in_time_edit.text())
            manual_out = time_to_s(self.out_time_edit.text())
            in_s  = max(0.0, min(manual_in,  self.duration))
            out_s = max(0.0, min(manual_out, self.duration))
        except Exception:
            pass

        # Точку старта привязываем ВНИЗ к сетке кадров. Плеер (QtMultimedia) на
        # позиции IN показывает кадр, который «на экране» в этот момент — т.е.
        # кадр с pts ≤ IN (округление ВНИЗ). А ffmpeg-рез (-ss IN) оставляет
        # первый кадр с pts ≥ IN (округление ВВЕРХ). Если IN стоит между кадрами
        # (обычный случай — плейхед по звуку/мышью почти никогда не попадает ровно
        # на кадр), экспорт начинался бы на ОДИН кадр позже того, что видно в
        # превью — отсюда баг «первое слово/кадр срезается, а в монтаже он есть».
        # Пол к кадру делает export-seek WYSIWYG с превью: ffmpeg берёт ровно тот
        # кадр, что показан. Только для видео с известным fps; аудио режем как есть
        # (кадров нет — точное время верно). eps=1e-3 кадра гасит float-дрожь у
        # самой границы, не перескакивая на кадр раньше.
        if self.video_stream_index is not None and self.fps and self.fps > 0:
            frame_idx = math.floor(in_s * self.fps + 1e-3)
            # Целимся на четверть кадра НИЖЕ границы кадра: ffmpeg-seek оставляет
            # первый кадр с pts ≥ ss, а при дробном fps (23.976/29.97) pts кадра
            # не ложится ровно в миллисекунды и округление строки времени (.3f)
            # могло бы перескочить на кадр ВПЕРЁД. Смещение −0.25 кадра держит ss
            # заведомо ниже pts нужного кадра (но выше предыдущего), поэтому ffmpeg
            # берёт ровно тот кадр, что показан в превью, на ЛЮБОМ fps.
            snapped = (frame_idx - 0.25) / self.fps
            in_s = max(0.0, min(snapped, self.duration))

        if out_s <= in_s:
            msgbox_warning(self, "Внимание", "Конечная точка должна быть позже начальной.")
            return

        # Висит предпросмотр привязки к объекту — «Обрезать» и есть его экспорт:
        # режем выбранный отрезок и вшиваем накладку по уже посчитанному пути.
        if self.has_track_preview():
            self._render_track_overlay(in_s, out_s)
            return

        mode = self.cmb_mode.currentIndex()
        # Субтитры можно вшить, если выбрана любая дорожка (встроенная или внешний
        # файл) — пункт 0 = «Выкл».
        burn_subs = (self.chk_burn_subs.isChecked() and mode != 2
                     and self.cmb_subs.currentIndex() > 0)
        # Оптимизация: если субтитры просят вшить, но в выбранном отрезке по факту
        # нет ни одного события субтитров — вшивать нечего. Отключаем hardsub, и
        # тогда в режиме «Быстро» обрезка пойдёт без перекодировки (lossless).
        if burn_subs and not self._subs_present_in_range(
                self.actual_source_file, self.selected_sub_ext_path,
                self.cmb_subs.currentIndex() - 1, in_s, out_s):
            burn_subs = False
            self.log_label.setText(
                icon_html('fa5s.info-circle', 12, C['text2'])
                + " В отрезке нет субтитров — вшивание пропущено")
            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log("Монтаж: в выбранном отрезке нет субтитров — "
                              "вшивание пропущено, обрезка без перекодировки.")
        # Кадрирование видео несовместимо с copy-путями (Smart Cut копирует
        # середину, «Быстро» копирует поток целиком) — crop требует перекодировки.
        # При активной рамке принудительно переходим на полную перекодировку.
        crop_active = self._video_crop_filter() is not None
        # Пикселизация (эффект -vf) тоже несовместима с copy/Smart Cut — требует
        # перекодировки, как и кадрирование.
        pix_active = getattr(self, "_pixelize_active", False)
        # Наложенные картинки — такой же «фильтровый» эффект: copy/Smart Cut их
        # не умеют (путь «настройками Обработки» умеет — см. ниже).
        ovl_active = self.has_image_overlays()
        # Smart Cut несовместим с вшиванием субтитров (середина копируется): при
        # запросе hardsub откатываемся на полную перекодировку (mode 1).
        if mode in (4, 5):
            # 4 — «Перекодировать настройками «Обработки»», 5 — то же самое, но
            # ТОЛЬКО звук: точный рез + текущие настройки вкладки «Обработка»
            # одним проходом ProcessWorker (тот же путь, что кнопка «Обрезать и
            # обработать» в диалоге точности реза).
            audio_only = (mode == 5)
            # Наложенные картинки этот путь ТЕПЕРЬ умеет: их PNG уезжают в
            # item['overlays'] и вшиваются тем же единственным проходом
            # ProcessWorker (см. _execute_cut_and_process). Но только когда
            # «Обработка» реально перекодирует видео: с выключенной галочкой
            # «Перекодировать видео» поток копируется (-c:v copy), а к копии
            # никакие видеофильтры неприменимы. В аудио-режиме видеоряда нет
            # вовсе — там накладки теряются по определению режима.
            ovl_lost = ovl_active and (audio_only
                                       or not self._process_tab_encodes_video())
            # Остальных своих видеофильтров путь не знает — если что-то из них
            # включено, спрашиваем, а не выкидываем молча. В аудио-режиме
            # спрашивать нечего: видеоряда на выходе нет по определению самого
            # режима — просто честно пишем в лог, что эффекты картинки к нему
            # не применяются.
            if burn_subs or crop_active or pix_active or ovl_lost:
                what = ", ".join(n for n, on in (
                    ("вшивание субтитров", burn_subs), ("кадрирование", crop_active),
                    ("пикселизация", pix_active),
                    ("наложенные картинки", ovl_lost)) if on)
                if audio_only:
                    self.log_label.setText(
                        icon_html('fa5s.info-circle', 12, C['text2'])
                        + " Аудио-режим: эффекты картинки не применяются")
                    self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
                    if self.main is not None and hasattr(self.main, "log"):
                        self.main.log("Монтаж: аудио-режим «Обработки» — на выходе "
                                      f"только звук, поэтому не применяются: {what}.")
                else:
                    ans = msgbox_question(
                        self, "Настройки «Обработки»",
                        f"В режиме «Перекодировать настройками «Обработки»» не применяется: "
                        f"{what}.\n\nОбрезать настройками «Обработки» без этого?\n"
                        "«Нет» — обычная перекодировка средствами Монтажа (со всеми эффектами).")
                    if ans != QMessageBox.StandardButton.Yes:
                        self._execute_cut(in_s, out_s, 1, burn_subs)
                        return
            self._execute_cut_and_process(in_s, out_s, audio_only=audio_only)
            return
        if mode == 3:
            if burn_subs or crop_active or pix_active or ovl_active:
                self._execute_cut(in_s, out_s, 1, burn_subs)
            else:
                self._execute_smartcut(in_s, out_s)
            return
        if (crop_active or pix_active or ovl_active) and mode == 0:
            mode = 1  # быстрый copy не умеет crop/pixelize/накладки → перекодируем
        self._execute_cut(in_s, out_s, mode, burn_subs)

    def _export_still_pixelize(self):
        """Собирает ВИДЕО-проявление из загруженной картинки: кадр зацикливается
        (-loop 1) на заданную длительность, по нему идёт цепочка пикселизации
        (offset=0 — фильтрграф стартует с нуля) и, при наличии, кадрирование.
        Требует включённой пикселизации — в этом весь смысл режима картинки."""
        src = self.still_image_path or self.actual_source_file
        if not src or not os.path.exists(str(src)):
            msgbox_warning(self, "Внимание", "Картинка не загружена.")
            return
        if not getattr(self, "_pixelize_active", False):
            msgbox_information(
                self, "Пикселизация",
                "Включите «Пикселизацию» (кнопка с сеткой) — для картинки именно она "
                "и создаёт видео-проявление.")
            return
        src = Path(src)
        dur = max(1.0, float(self._still_duration))
        fps = max(1, int(self._still_fps))
        # Цепочка: кадрирование (если есть) → пикселизация (offset=0) → чётные
        # размеры под yuv420p/h264.
        crop_vf = self._video_crop_filter()
        pix_vf = self._video_pixelize_filter(dur, 0.0)
        chain = [p for p in (crop_vf, pix_vf) if p]
        chain.append("scale=trunc(iw/2)*2:trunc(ih/2)*2")
        vf = self._wrap_vf(",".join(chain), src)

        out_dir = (Path(self.export_dir) if (self.export_dir and os.path.isdir(self.export_dir))
                   else src.parent)
        final_out = str(out_dir / f"{src.stem}_пиксель.mp4")
        if os.path.exists(final_out):
            final_out = _unique_output(final_out)

        venc = self._video_encoder_args(hardsub=False)
        cmd = [FFMPEG, "-y", "-loop", "1", "-framerate", str(fps), "-i", str(src),
               "-t", s_to_time(dur), "-vf", vf] + venc \
              + ["-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", final_out]

        self._report_progress(0, "Создание видео…")
        self.log_label.setText("Создание видео из картинки…")
        self._set_cut_status("Пикселизация… подготовка", icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True)
        self._cut_t0 = time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        self.ffmpeg_thread = FfmpegWorker(cmd, duration=dur)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _on_finished(success, message, _final=final_out):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            if success and os.path.exists(_final):
                try:
                    if self.main is not None and hasattr(self.main, "log"):
                        self.main.log(f"Видео-проявление из картинки готово: {_final}")
                except Exception:
                    pass
                self.on_ffmpeg_finished(True, message)
            else:
                if _final and os.path.exists(_final) and not success:
                    try: os.remove(_final)
                    except Exception: pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _execute_cut(self, in_s, out_s, mode, burn_subs,
                     src=None, force_overwrite=False, out_path=None):
        """Собирает и запускает ffmpeg-обрезку для диапазона [in_s, out_s].
        `src` позволяет перекодировать из ОРИГИНАЛА (для предложения «перекодировать
        с потерями» после неточной copy-обрезки), `force_overwrite` — перезаписать
        результат принудительно. `out_path` — точный путь вывода: пере-рез после
        неточной быстрой обрезки переиспользует имя ИМЕННО того файла, который он
        заменяет (его уже удалил _discard_temp_cut), а не пересобирает базовое имя
        `{stem}_обрез` — иначе перекодировка затёрла бы ДРУГУЮ, более раннюю обрезку
        того же исходника, занявшую это базовое имя."""
        src = Path(src) if src else self.actual_source_file
        if not src or not src.exists():
            msgbox_warning(self, "Внимание", "Файл не загружен.")
            return

        stem = src.stem; suffix = src.suffix
        if self.export_dir and os.path.isdir(self.export_dir):
            out_dir = Path(self.export_dir)
        else:
            out_dir = src.parent

        if out_path:
            final_out = str(out_path)
        elif mode == 2:
            final_out = str(out_dir / f"{stem}_обрез.mp3")
        else:
            final_out = str(out_dir / f"{stem}_обрез{suffix}")

        replace_original = force_overwrite or self.chk_overwrite.isChecked()
        # Повторная обрезка того же исходника НЕ затирает предыдущий клип: 2-й
        # файл сохраняется под именем с суффиксом (foo_обрез.mp4 → foo_обрез_1.mp4,
        # _2, …). Перезапись остаётся только для внутренней пере-обрезки
        # (force_overwrite / явный out_path) и правки «на месте» (цель == открытый файл).
        if os.path.exists(final_out) and not force_overwrite and not out_path:
            loaded = str(self.actual_source_file) if self.actual_source_file else ""
            in_place = bool(loaded) and os.path.normpath(loaded) == os.path.normpath(final_out)
            if not (self.chk_overwrite.isChecked() and in_place):
                final_out = _unique_output(final_out)

        temp_out = self._make_temp_out(final_out)

        dur_cut = out_s - in_s
        in_str  = s_to_time(in_s)
        out_str = s_to_time(out_s)
        dur_str = s_to_time(dur_cut)

        # Внешняя озвучка (отдельный аудиофайл): подмешиваем её вторым входом и
        # берём звук из него. Применяется только если она выбрана и существует.
        ext_audio = self.selected_audio_ext_path
        if ext_audio and not os.path.exists(ext_audio):
            ext_audio = None

        # Если в контейнере несколько аудиодорожек и выбрана конкретная —
        # сохраняем именно её (видео + выбранная аудиодорожка). Иначе поведение
        # по умолчанию (ffmpeg сам берёт по одной дорожке каждого типа).
        sel_a = self.selected_audio_abs_index
        pick_audio = (sel_a is not None and len(self._audio_streams) > 1)
        amap = ["-map", "0:v:0", "-map", f"0:{sel_a}"] if pick_audio else []

        # Внешняя дорожка субтитров (файл рядом) — отдельный путь, иначе индекс
        # встроенной дорожки.
        ext_sub = self.selected_sub_ext_path
        burn_idx = self.cmb_subs.currentIndex() - 1
        # Кадрово-точной осталась только перекодировка; в режиме copy отслеживаем,
        # удалось ли обрезать без потерь по кадрам (для уведомления пользователю).
        exact_copy = (mode == 0 and not burn_subs and not ext_audio)
        venc = self._video_encoder_args(hardsub=burn_subs)
        # Кадрирование видео (рамка на холсте). crop умеет только перекодировка,
        # поэтому при активной рамке start_cut уже перевёл mode на 1. Здесь
        # фильтр добавляется к видеоцепочке (отдельным -vf либо в начало цепочки
        # субтитров, если идёт вшивание).
        crop_vf = self._video_crop_filter()
        # Пикселизация-проявление (эффект по времени клипа). Требует перекодировки;
        # если внутренний пере-рез вызвал _execute_cut с mode 0 при активном
        # эффекте — поднимаем до перекодировки. `pix_on` — будет ли эффект вообще
        # добавлять фильтр (от offset это не зависит), а сам фильтр строится с
        # правильным смещением времени отдельно в каждой ветке (см. _vf_args ниже).
        pix_on = self._video_pixelize_filter(dur_cut, 0.0) is not None
        # Наложенные картинки (логотип/водяной знак) — тоже фильтр: copy их не
        # умеет, поэтому при активных слоях идём перекодировкой, как с crop.
        ovl_on = self.has_image_overlays()
        if (pix_on or ovl_on) and mode == 0:
            mode = 1
        # Любой видеофильтр (crop/pixelize/накладка) — это перекодировка, а не
        # lossless-copy: не вводим в заблуждение уведомитель точности реза.
        if crop_vf or pix_on or ovl_on:
            exact_copy = False

        def _vf_args(offset):
            """Аргументы -vf для текущей ветки: наложенные картинки + crop (без
            времени) + пикселизация со смещением `offset` (время фильтрграфа в
            начале клипа — зависит от способа seek в ветке). Пустой список, если
            фильтровать нечего."""
            chain = [p for p in (crop_vf, self._video_pixelize_filter(dur_cut, offset)) if p]
            vf = self._wrap_vf(",".join(chain), src)
            return ["-vf", vf] if vf else []

        fonts_dir = None
        if burn_subs:
            # Hardsub всегда требует перекодировки. Используем ВЫХОДНОЙ seek
            # (-ss после -i), чтобы субтитры не разъехались по времени с кадрами.
            # libass рендерит ASS со всеми стилями; для родных ШРИФТОВ извлекаем
            # вложенные attachments контейнера и отдаём их через :fontsdir.
            if ext_sub:
                esc = self._escape_filter_path(ext_sub)
                vf = f"subtitles='{esc}'"
                sub_codec = os.path.splitext(ext_sub)[1].lower().lstrip('.')
            else:
                esc = self._escape_filter_path(src)
                vf = f"subtitles='{esc}':si={burn_idx}"
                try:
                    sub_codec = (self._sub_streams[burn_idx].get('codec_name') or '').lower()
                except Exception:
                    sub_codec = ''
            # Стиль вшиваемых субтитров — по выбору пользователя (cmb_sub_style):
            #   0 Авто      — стиль программы для SRT/VTT/mov_text, у ASS/SSA свой;
            #   1 Программа — насильно стиль программы даже поверх ASS/SSA;
            #   2 Оригинал  — ничего не навязываем (ASS/SSA — свой стиль, SRT/VTT —
            #                 стиль libass по умолчанию).
            try:
                style_choice = int(self.cmb_sub_style.currentIndex())
            except Exception:
                style_choice = 0
            native_styled = sub_codec in ('ass', 'ssa')
            if style_choice == 1:
                apply_prog_style = True
            elif style_choice == 2:
                apply_prog_style = False
            else:
                apply_prog_style = not native_styled
            if apply_prog_style:
                # Белый жирный шрифт с чёрной обводкой — РОВНО как в превью монтажа.
                # Превью рисует текст высотой 5.2% кадра (см. VideoCanvas.paintEvent
                # px=...*0.052). Текстовые субтитры libass рендерит в скрипте 384×288
                # (дефолт libav) и масштабирует до кадра, поэтому Fontsize=15 даёт
                # 15/288 ≈ 5.2% высоты кадра НА ЛЮБОМ разрешении. Прежний Fontsize=28
                # давал ~2× (на FullHD субтитры «огромные» — это и был баг).
                style = ("FontName=Arial,Fontsize=15,Bold=1,"
                         "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
                         "BorderStyle=1,Outline=1,Shadow=0,MarginV=14")
                vf += f":force_style='{style}'"
            fonts_dir = self._extract_subtitle_fonts(src)
            if fonts_dir:
                fesc = self._escape_filter_path(fonts_dir)
                vf += f":fontsdir='{fesc}'"
            # Кадрируем ДО субтитров: libass рисует на уже обрезанном кадре, и
            # текст не уезжает за пределы кадрированной области.
            if crop_vf:
                vf = f"{crop_vf},{vf}"
            # Пикселизацию применяем ПОСЛЕ субтитров — иначе текст тоже размоется
            # в мозаику и станет нечитаемым. Обе ветки вшивания используют ВЫХОДНОЙ
            # seek, поэтому смещение времени = in_s.
            _pix = self._video_pixelize_filter(dur_cut, in_s)
            if _pix:
                vf = f"{vf},{_pix}"
            # Наложенные картинки идут ПЕРЕД кадрированием и субтитрами (см.
            # overlay_filter_graph) — так же, как их видно в плеере.
            vf = self._wrap_vf(vf, src)
            if ext_audio:
                # Видео+субтитры из исходника (вход 0), звук — из внешнего файла
                # (вход 1). Выходной seek (-ss/-t как опции вывода) равно режет оба.
                # -sn: субтитры ВШИТЫ в кадр (-vf subtitles), отдельная мягкая
                # дорожка не нужна — и, что важнее, при выходном seek её копия
                # тащит длительность всего эпизода (см. -sn ниже).
                cmd = [FFMPEG, "-y", "-i", str(src), "-i", ext_audio,
                       "-ss", in_str, "-t", dur_str,
                       "-map", "0:v:0", "-map", "1:a:0", "-vf", vf] \
                      + venc + ["-c:a", "aac", "-b:a", "192k", "-sn", temp_out]
            else:
                # Аудио НЕ перекодируем (контейнер тот же → совместимо).
                # -sn ОБЯЗАТЕЛЕН: без явного -map ffmpeg авто-включает в вывод и
                # субтитровый поток исходника; при выходном seek его копия не
                # режется и сообщает длительность ВСЕГО эпизода (~11 мин вместо
                # 7 сек) — отсюда баг «обрезка с сабами даёт 11 минут». Субтитры
                # уже вшиты в кадр (-vf subtitles), мягкая дорожка не нужна.
                cmd = [FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + ["-vf", vf] + venc + ["-c:a", "copy", "-sn", temp_out]
        elif ext_audio and mode != 2:
            # Внешняя озвучка без вшивания субтитров. Видео берём по режиму
            # (copy/перекодировка), звук — из внешнего файла (перекодируем в AAC,
            # т.к. контейнер/кодек могут не совпадать).
            vargs = (["-c:v", "copy"]
                     if (mode == 0 and not crop_vf and not pix_on and not ovl_on)
                     else venc)
            # ВХОДНОЙ seek по видео (-ss до -i src) → фильтрграф стартует с 0.
            cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                   "-ss", in_str, "-i", ext_audio, "-t", dur_str,
                   "-map", "0:v:0", "-map", "1:a:0"] \
                  + _vf_args(0.0) + vargs + ["-c:a", "aac", "-b:a", "192k", temp_out]
        elif mode == 0:
            # Быстрая обрезка (copy) — ВХОДНОЙ seek к точке реза (-ss ДО -i).
            #
            # РАНЬШЕ резали ВЫХОДНЫМ seek (-ss ПОСЛЕ -i): он давал верную
            # длительность, НО видео при copy «прилипало» к СЛЕДУЮЩЕМУ ключевому
            # кадру (за точкой реза), и его PTS оставался > 0, тогда как звук
            # стартовал с 0. На AV1/MP4 это давало баг «первый кадр застывает на
            # несколько секунд в начале» (video start_time 5.7с против audio 0):
            # плеер держал первый кадр, пока звук играл в пустоту до прихода видео.
            #
            # Входной seek встаёт на ближайший ключевой кадр ≤ in_s, поэтому видео
            # И звук стартуют с НУЛЯ (выровнены) — дырки/застывания нет. На MP4
            # ffmpeg к тому же пишет edit-list и кадрово-точно показывает с in_s;
            # на MKV (edit-list нет) начало прилипает к ключевому кадру — это
            # нормальное поведение lossless-copy, его ловит _notify_cut_accuracy и
            # предлагает Smart Cut.
            #   • -fflags +genpts — демуксер генерит недостающие PTS (без него
            #     mpeg4/DivX в MKV падали с -22 «unknown timestamp», ошибка
            #     4294967274). Это и был реальный фикс -22, а не выходной seek.
            #   • рез по ДЛИТЕЛЬНОСТИ -t (НЕ входной -to: тот на mpeg4 давал 12с
            #     вместо 7с; -t считается от точки seek и надёжен).
            cmd = [FFMPEG, "-y", "-fflags", "+genpts",
                   "-ss", in_str, "-i", str(src), "-t", dur_str] \
                  + amap + ["-c", "copy", temp_out]
        elif mode == 1:
            # Перекодировка с КАДРОВОЙ точностью. Точность реза целиком даёт
            # ВЫХОДНОЙ seek (-ss/-t ПОСЛЕ -i): ffmpeg режет ровно по кадру, не
            # «прилипая» к ключевому кадру и не сбиваясь на контейнерах со
            # смещённым start_time (MKV/WEB-DL); копируемый звук режется тем же
            # выходным -ss ровно до in_s.
            #
            # Раньше выходной seek шёл ОТ НАЧАЛА файла (-i src -ss in): чтобы
            # вырезать 6 c у конца 23-мин эпизода, ffmpeg сперва ~23 мин
            # декодировал «вхолостую» — медленно, и прогресс всё это время висел
            # в фазе «подготовка» (ffmpeg не шлёт time=, пока не дойдёт до реза).
            #
            # Ускорение: добавляем БЫСТРЫЙ входной pre-seek к точке за PRESEEK
            # секунд до реза — ffmpeg сам встаёт на ближайший ключевой кадр
            # ≤ pre_ss и декодирует только оттуда (секунды вместо минут, прогресс
            # сразу идёт 0→100%). ТОЧНЫЙ рез по-прежнему делает выходной -ss.
            # Проверено покадрово (framemd5 видео + md5 аудио идентичны старому
            # пути на mp4/mkv/WEB-DL +10c/edit-list, h264/hevc, у границ и в конце):
            #   • выходной -ss отсчитывается от ЗАПРОШЕННОГО pre_ss (а не от того,
            #     куда «прилип» seek) → подстройка по кадру не зависит от GOP,
            #     детектировать ключевые кадры не нужно;
            #   • выходной -ss режет и КОПИРУЕМЫЙ звук ровно до in_s — без него
            #     (чистый входной seek) звук «съезжает» на ~PRESEEK раньше видео;
            #   • входной -ss задаётся в контентной шкале (ffmpeg прибавляет
            #     start_time) → смещённый start_time рез не ломает.
            # out_ss считаем от фактической (округлённой до мс) точки pre-seek,
            # чтобы итоговая точка реза совпала с round_ms(in_s) старого пути.
            # При in_s ≤ 2*PRESEEK старый путь и так быстр (декод ≤ пары секунд) и
            # обходит особенность входного seek к самому нулю на контейнерах со
            # смещением — оставляем выходной seek от начала.
            # -sn ОБЯЗАТЕЛЕН: без явного -map ffmpeg авто-включает субтитровый
            # поток, который при выходном seek не режется и сообщает длительность
            # всего эпизода (~11 мин). Этот режим запускается в т.ч. как fallback
            # после неточной copy-обрезки (_notify_cut_accuracy) — поэтому баг
            # «11 минут» всплывал и без явного вшивания субтитров.
            PRESEEK = 3.0
            if in_s > 2 * PRESEEK:
                pre_str = s_to_time(in_s - PRESEEK)
                out_ss = s_to_time(in_s - time_to_s(pre_str))
                # ВХОДНОЙ pre-seek (pre_str) + ВЫХОДНОЙ -ss (out_ss): клип в шкале
                # фильтрграфа начинается на t = out_ss.
                cmd = [FFMPEG, "-y", "-ss", pre_str, "-i", str(src),
                       "-ss", out_ss, "-t", dur_str] \
                      + amap + _vf_args(time_to_s(out_ss)) + venc + ["-c:a", "copy", "-sn", temp_out]
            else:
                # Чистый ВЫХОДНОЙ seek → фильтрграф видит исходное время, offset = in_s.
                cmd = [FFMPEG, "-y", "-i", str(src), "-ss", in_str, "-t", dur_str] \
                      + amap + _vf_args(in_s) + venc + ["-c:a", "copy", "-sn", temp_out]
        elif ext_audio:
            # Только аудио (MP3) из внешней озвучки.
            cmd = [FFMPEG, "-y", "-ss", in_str, "-i", ext_audio,
                   "-t", dur_str, "-map", "0:a:0",
                   "-c:a", "libmp3lame", "-q:a", "2", temp_out]
        else:
            astream = sel_a if sel_a is not None else self.audio_stream_index
            if astream is not None:
                cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                       "-t", dur_str, "-map", f"0:{astream}",
                       "-c:a", "libmp3lame", "-q:a", "2", temp_out]
            else:
                cmd = [FFMPEG, "-y", "-ss", in_str, "-i", str(src),
                       "-t", dur_str, "-vn", "-c:a", "libmp3lame", "-q:a", "2", temp_out]

        self._report_progress(0, "Обрезка…")
        self.log_label.setText("Обрезка...")
        self._set_cut_status("Обрезка… подготовка", icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True)

        # Прогресс с ETA. Тикер раз в 0.5с обновляет «прошло/ETA», чтобы строка
        # не выглядела зависшей, даже если ffmpeg редко шлёт time= (короткие
        # отрезки или фаза перемотки декодером до точки реза).
        self._cut_t0 = time.time()
        self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self)
            self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        self.ffmpeg_thread = FfmpegWorker(cmd, duration=dur_cut)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)

        def _on_finished(success, message, _temp=temp_out, _final=final_out,
                         _exact=exact_copy, _reqdur=dur_cut, _burn=burn_subs,
                         _in=in_s, _out=out_s, _src=src):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            # Папка извлечённых шрифтов больше не удаляется сразу — она в
            # _subtitle_fonts_cache и живёт до закрытия вкладки (см. shutdown()),
            # чтобы повторный экспорт того же источника не гонял ffmpeg заново.
            if success and _temp:
                try:
                    is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                 os.path.normpath(_final))
                    if replace_original and os.path.exists(_final):
                        try:
                            os.remove(_final)
                        except OSError:
                            # Цель занята другим процессом (её читает «Обработка») —
                            # не падаем: _replace_tolerant ниже уведёт результат на
                            # свободное имя.
                            pass
                    if os.path.exists(_final) and not replace_original:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    saved_final = self._replace_tolerant(_temp, _final)
                    if os.path.normpath(saved_final) != os.path.normpath(_final):
                        # Имя сменилось: целевой файл был занят (его читала другая
                        # вкладка). Сообщаем и дальше работаем с фактическим путём.
                        self._notify_busy_rename(_final, saved_final)
                        _final = saved_final
                        is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                     os.path.normpath(_final))
                    # Точность обрезки проверяем ДО перезагрузки. Если copy-обрезка
                    # вышла не кадрово-точной — спрашиваем, что делать с фрагментом.
                    action = self._notify_cut_accuracy(_final, _reqdur, _exact, _burn,
                                                       _in, _out, _src)
                    if action == 'encode':
                        # Пользователь выбрал переделать перекодировкой — неточный
                        # файл быстрой обрезки больше не нужен, удаляем его (иначе
                        # при выключенной перезаписи останется осиротевший дубль,
                        # а результат уедет в «…_обрез_1»).
                        self._discard_temp_cut(_final, is_loaded)
                        QTimer.singleShot(0, lambda: self._execute_cut(
                            _in, _out, 1, _burn, src=_src,
                            force_overwrite=True, out_path=_final))
                        return
                    if action == 'smartcut':
                        # То же и для Smart Cut: создаст точный файл под тем же
                        # именем — неточный результат быстрой обрезки удаляем.
                        self._discard_temp_cut(_final, is_loaded)
                        QTimer.singleShot(0, lambda: self._execute_smartcut(
                            _in, _out, out_path=_final))
                        return
                    if action == 'process':
                        # Точный рез + «Обработка» текущими настройками одним
                        # проходом (см. _execute_cut_and_process) — неточный
                        # результат быстрой обрезки больше не нужен.
                        self._discard_temp_cut(_final, is_loaded)
                        QTimer.singleShot(0, lambda: self._execute_cut_and_process(
                            _in, _out, out_path=_final, src=_src))
                        return
                    if action == 'delete':
                        # Удаляем созданный неточный файл по просьбе пользователя.
                        # Если он сейчас открыт в плеере — сперва освобождаем источник.
                        try:
                            if is_loaded:
                                # Освобождаем файл: останавливаем плеер и снимаем источник.
                                try: self.player.stop()
                                except Exception: pass
                                try: self.player.setSource(QUrl())
                                except Exception: pass
                            if os.path.exists(_final):
                                os.remove(_final)
                            self.log_label.setText(
                                icon_html('fa5s.trash', 12, C['text2']) + " Файл удалён")
                            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
                            self._report_progress(0, "Файл удалён")
                        except Exception as e:
                            msgbox_warning(self, "Не удалось удалить",
                                                f"Не удалось удалить файл:\n{e}")
                        return
                    if is_loaded:
                        self.load_file(_final)
                    self.on_ffmpeg_finished(True, message)
                except Exception as e:
                    try:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                    except Exception:
                        pass
                    self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
            else:
                if _temp and os.path.exists(_temp):
                    try:
                        os.remove(_temp)
                    except Exception:
                        pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _smartcut_status(self, s):
        try:
            self.log_label.setText(s)
            self._set_cut_status(s, icon='fa5s.cut')
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(s)
        except Exception:
            pass

    def _execute_smartcut(self, in_s, out_s, out_path=None):
        """Запускает умную обрезку (SmartCutWorker): граничные участки от точек
        реза до ближайших ключевых кадров перекодируются, середина копируется без
        потерь. Контейнер вывода = контейнер исходника (нужно для copy-склейки).
        `out_path` — точный путь вывода (пере-рез после неточной быстрой обрезки
        переиспользует имя заменяемого файла, а не пересобирает `{stem}_обрез`;
        см. _execute_cut)."""
        src = self.actual_source_file
        if not src or not src.exists():
            msgbox_warning(self, "Внимание", "Файл не загружен.")
            return
        stem = src.stem; suffix = src.suffix
        out_dir = (Path(self.export_dir)
                   if (self.export_dir and os.path.isdir(self.export_dir)) else src.parent)
        final_out = str(out_path) if out_path else str(out_dir / f"{stem}_обрез{suffix}")
        replace_original = self.chk_overwrite.isChecked() or bool(out_path)
        # Как и в _execute_cut: повторная Smart Cut обрезка того же файла не
        # затирает прошлый клип, а уходит под именем с суффиксом. Явный out_path
        # (пере-рез) указывает на уже освобождённый файл — его не переименовываем.
        if os.path.exists(final_out) and not out_path:
            loaded = str(self.actual_source_file) if self.actual_source_file else ""
            in_place = bool(loaded) and os.path.normpath(loaded) == os.path.normpath(final_out)
            if not (replace_original and in_place):
                final_out = _unique_output(final_out)
        temp_out = self._make_temp_out(final_out, suffix)

        self._report_progress(0, "Smart Cut…")
        self.log_label.setText("Smart Cut…")
        self._set_cut_status("Smart Cut… подготовка", icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True)
        self._cut_t0 = time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        venc = self._video_encoder_args()
        # Выбранная аудиодорожка (если в контейнере их несколько). None → первая.
        sc_audio = (self.selected_audio_abs_index
                    if (self.selected_audio_abs_index is not None
                        and len(self._audio_streams) > 1) else None)
        self.ffmpeg_thread = SmartCutWorker(src, in_s, out_s, temp_out, venc,
                                            audio_index=sc_audio)
        self.ffmpeg_thread.progress.connect(self._on_cut_progress)
        self.ffmpeg_thread.status.connect(self._smartcut_status)

        def _on_finished(success, message, _temp=temp_out, _final=final_out):
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            if success and _temp and os.path.exists(_temp) and os.path.getsize(_temp) > 0:
                try:
                    is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                 os.path.normpath(_final))
                    if replace_original and os.path.exists(_final):
                        try:
                            os.remove(_final)
                        except OSError:
                            pass  # занят другим процессом — уйдём на свободное имя
                    if os.path.exists(_final) and not replace_original:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                        self.on_ffmpeg_finished(False, "Файл уже существует (логическая ошибка)")
                        return
                    saved_final = self._replace_tolerant(_temp, _final)
                    if os.path.normpath(saved_final) != os.path.normpath(_final):
                        self._notify_busy_rename(_final, saved_final)
                        _final = saved_final
                        is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                     os.path.normpath(_final))
                    if is_loaded:
                        self.load_file(_final)
                    self.on_ffmpeg_finished(True, message)
                except Exception as e:
                    try:
                        if os.path.exists(_temp):
                            os.remove(_temp)
                    except Exception:
                        pass
                    self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")
            else:
                if _temp and os.path.exists(_temp):
                    try:
                        os.remove(_temp)
                    except Exception:
                        pass
                self.on_ffmpeg_finished(success, message)

        self.ffmpeg_thread.finished.connect(_on_finished)
        self.ffmpeg_thread.start()

    def _process_tab_encodes_video(self):
        """Перекодирует ли «Обработка» видео прямо сейчас (её галочка
        «Перекодировать видео»). При выключенной видеопоток копируется
        (-c:v copy), и никакие видеофильтры — в том числе наложенные картинки —
        к нему не применимы. Вкладка недоступна → считаем, что перекодирует
        (обычная настройка по умолчанию)."""
        tm = getattr(self.main, 'tab_media', None) if self.main is not None else None
        try:
            return bool(tm.chk_enable_video.isChecked())
        except Exception:
            return True

    def _execute_cut_and_process(self, in_s, out_s, out_path=None, src=None,
                                 audio_only=False):
        """Кнопка «Обрезать и обработать»: режет диапазон [in_s,out_s) И сразу
        применяет вкладку «Обработка» ЕЁ ТЕКУЩИМИ настройками (CRF/preset/
        скорость/loudnorm/fps/…) — одним ffmpeg-проходом внутри
        ProcessWorker.process_media (item['trim']), без отдельного x264-реэнкода
        в Монтаже, который иначе перекодировался бы ЕЩЁ РАЗ при последующем
        прогоне через «Обработку» (двойное поколение потерь).

        audio_only=True (режим обрезки «(Аудио) Перекодировать настройками
        «Обработки»») — то же самое, но видеоряд отбрасывается и на выходе
        остаётся ТОЛЬКО звуковая дорожка (.opus) с текущими настройками звука
        «Обработки». Технически это item['audio_only'] — process_media гонит
        такой элемент своей аудио-онли веткой, той же, что и для файлов без
        видео (см. workers.py).

        Настройки НЕ копируем — вызываем тот же MediaTab._run_items(), что и
        кнопка «НАЧАТЬ» на вкладке «Обработка», поэтому любые настройки,
        добавленные туда в будущем, подхватятся автоматически.

        Имя итогового файла собираем ПОСЛЕ обработки (см. _on_finished_all), а
        не заранее фиксированным «{stem}_обрез{исходное_расширение}» — иначе
        (а) из имени пропадали суффиксы реально применённых настроек (crf/
        speed/norm/fade/noaudio — ровно то, что показывает суффикс в обычной
        «Обработке»), и (б) для источников не-.mp4 (mkv/…) итог process_media
        (всегда .mp4 для AV1) переименовывался под ЧУЖОЕ расширение источника —
        файл с mp4-содержимым получал имя «*.mkv», что вводило в заблуждение.

        Два РАЗНЫХ отрезка одного исходника получают разные файлы: имя занято —
        уходим на «…_обрез_1» (см. _unique_output), а не затираем предыдущий
        клип. Перезапись остаётся только для внутреннего пере-реза (out_path)
        и правки «на месте»."""
        src = Path(src) if src else self.actual_source_file
        if not src or not src.exists():
            msgbox_warning(self, "Внимание", "Файл не загружен.")
            return
        tm = getattr(self.main, 'tab_media', None)
        if tm is None:
            msgbox_warning(self, "Внимание", "Вкладка «Обработка» недоступна.")
            return
        try:
            busy = bool(getattr(tm, 'worker', None) is not None and tm.worker.isRunning())
        except Exception:
            busy = False
        if busy:
            msgbox_information(
                self, "«Обработка» занята",
                "Во вкладке «Обработка» уже идёт очередь — дождитесь её "
                "завершения и повторите обрезку.")
            return

        stem = src.stem
        out_dir = (Path(self.export_dir)
                   if (self.export_dir and os.path.isdir(self.export_dir)) else src.parent)
        # out_path приходит только от ВНУТРЕННЕГО пере-реза (предложение
        # «переделать точно» после быстрой обрезки — там неточный файл уже
        # удалён _discard_temp_cut, и его имя законно занять снова). Само имя
        # не берём: расширение результата «Обработки» может отличаться от
        # исходного (AV1 всегда .mp4), поэтому имя по-прежнему собираем по
        # факту — см. ниже. Флаг разрешает перезапись, и только её.
        force_overwrite = bool(out_path)

        self._report_progress(0, "Обработка…")
        self.log_label.setText("Отправлено в «Обработку»…"
                               + (" (только звук)" if audio_only else ""))
        self._set_cut_status(
            ("Обработка звука… подготовка" if audio_only else "Обработка… подготовка"),
            icon='fa5s.hourglass-half')
        self._set_cut_btn_cancel(True, cancel_handler=lambda: self._cancel_cut_and_process(tm))
        self._cut_t0 = time.time(); self._cut_lastp = 0.0
        if getattr(self, "_cut_ticker", None) is None:
            self._cut_ticker = QTimer(self); self._cut_ticker.setInterval(500)
            self._cut_ticker.timeout.connect(lambda: self._report_cut(self._cut_lastp))
        self._cut_ticker.start()

        iid = uuid.uuid4().hex
        # Выбранная аудиодорожка (если в контейнере их несколько) — иначе
        # process_media брал первую по умолчанию, игнорируя выбор в Монтаже.
        sel_a = (self.selected_audio_abs_index
                 if (self.selected_audio_abs_index is not None
                     and len(self._audio_streams) > 1) else None)
        item = {'iid': iid, 'path': str(src), 'type': 'MEDIA',
                'dur': max(0.0, out_s - in_s), 'is_done': False,
                'trim': (in_s, out_s), 'audio_index': sel_a,
                'audio_only': bool(audio_only)}
        # Наложенные картинки едут в «Обработку» готовыми PNG (уже отрисованы
        # под размер ИСХОДНОГО кадра, координаты — в его пикселях). process_media
        # подмешивает их фильтром overlay ПЕРЕД своей цепочкой (crop чёрных
        # полос/scale/fade), поэтому кадрирование и масштаб применяются уже к
        # кадру с картинкой — ровно как это видно в плеере Монтажа. Аудио-режим
        # видеоряда не выводит, поэтому там накладки не рендерим вовсе.
        if not audio_only:
            ovl = self._render_export_overlays()
            if ovl:
                item['overlays'] = ovl
                item['overlay_format'] = self._overlay_pix_fmt(src)
        # _run_items сама собирает настройки со всех виджетов «Обработки» и
        # запускает ProcessWorker (тот же путь, что кнопка «НАЧАТЬ»); в очереди —
        # только наш синтетический элемент, чужие файлы не затрагиваются.
        tm._run_items([item])
        proc_worker = getattr(tm, 'worker', None)
        if proc_worker is None:
            self._set_cut_btn_cancel(False)
            self.on_ffmpeg_finished(False, "Не удалось запустить «Обработку»")
            return

        def _on_progress(p_iid, pct, _iid=iid):
            if p_iid == _iid:
                self._on_cut_progress(pct)

        def _on_status(s_iid, txt, code, _iid=iid):
            if s_iid == _iid:
                self._smartcut_status(txt)

        def _on_finished_all(_item=item):
            for sig, slot in ((proc_worker.progress, _on_progress),
                              (proc_worker.status, _on_status),
                              (proc_worker.finished_all, _on_finished_all)):
                try: sig.disconnect(slot)
                except Exception: pass
            try:
                if getattr(self, "_cut_ticker", None) is not None:
                    self._cut_ticker.stop()
            except Exception:
                pass
            self._set_cut_btn_cancel(False)
            temp_out = _item.get('out_path')
            if not _item.get('is_done') or not temp_out or not os.path.exists(temp_out):
                self.on_ffmpeg_finished(
                    False, "«Обработка» не создала результат (см. лог вкладки «Обработка»)")
                return
            try:
                # process_media сам собрал имя с суффиксами применённых настроек
                # (crf/speed/norm/fade/noaudio — см. process_media в workers.py) —
                # переносим ТОЛЬКО хвост после исходного stem, добавляя «_обрез»
                # перед ним, и берём РЕАЛЬНОЕ расширение результата (для AV1 —
                # всегда .mp4, даже если источник .mkv).
                temp_stem, temp_ext = os.path.splitext(os.path.basename(temp_out))
                tail = temp_stem[len(stem):] if temp_stem.startswith(stem) else ("_" + temp_stem)
                final_out = str(out_dir / f"{stem}_обрез{tail}{temp_ext}")
                # Второй отрезок ИЗ ТОГО ЖЕ файла с теми же настройками даёт
                # ровно то же имя — и раньше «Перезаписать файл» (галочка
                # включена по умолчанию) молча стирала первый клип. Правило
                # здесь теперь такое же, как у обычной обрезки (_execute_cut):
                # перезаписываем ТОЛЬКО внутренний пере-рез (force_overwrite)
                # либо правку «на месте», когда цель — сам открытый файл.
                # Во всех остальных случаях уходим на «…_обрез_1», «_2», …
                loaded = str(self.actual_source_file) if self.actual_source_file else ""
                in_place = bool(loaded) and (os.path.normpath(loaded) ==
                                             os.path.normpath(final_out))
                replace_original = force_overwrite or (self.chk_overwrite.isChecked()
                                                       and in_place)
                if os.path.exists(final_out) and not replace_original:
                    final_out = _unique_output(final_out)

                is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                             os.path.normpath(final_out))
                if replace_original and os.path.exists(final_out):
                    try:
                        os.remove(final_out)
                    except OSError:
                        pass  # занят другим процессом — уйдём на свободное имя
                saved_final = self._replace_tolerant(temp_out, final_out)
                if os.path.normpath(saved_final) != os.path.normpath(final_out):
                    self._notify_busy_rename(final_out, saved_final)
                    final_out = saved_final
                    is_loaded = (os.path.normpath(str(self.actual_source_file)) ==
                                 os.path.normpath(final_out))
                if is_loaded:
                    self.load_file(final_out)
                self.on_ffmpeg_finished(True, "Готово (Обработка)")
            except Exception as e:
                self.on_ffmpeg_finished(False, f"Ошибка при сохранении: {e}")

        proc_worker.progress.connect(_on_progress)
        proc_worker.status.connect(_on_status)
        proc_worker.finished_all.connect(_on_finished_all)

    def on_ffmpeg_finished(self, success, message):
        if success:
            self.log_label.setText(icon_html('fa5s.check', 12, C['green2']) + " Готово")
            self.log_label.setStyleSheet(f"color: {C['green2']}; font-size: 12px; font-weight: 600;")
            self._report_progress(100, "Готово")
            # Кратко показываем «Готово» над кнопкой, затем возвращаем «Итог: …».
            self._set_cut_status("Готово", icon='fa5s.check')
            QTimer.singleShot(1800, self._clear_cut_status)
            # Сразу обновляем верхнюю ленту файлов: если результат перезаписал файл
            # по тому же пути (напр. «…_обрез.mp4» переэкспортирован перекодировкой
            # и стал короче/легче), карточка иначе висела бы со старым превью.
            try:
                strip = getattr(self.main, "recent_strip", None)
                if strip is not None:
                    strip.force_refresh()
            except Exception:
                pass
        elif message == "Отменено":
            self.log_label.setText("Отменено")
            self.log_label.setStyleSheet(f"color: {C['text2']}; font-size: 12px;")
            self._report_progress(0, "Отменено")
            self._clear_cut_status()
        else:
            self.log_label.setText(icon_html('fa5s.times', 12, C['red2']) + " Ошибка")
            self.log_label.setStyleSheet(f"color: {C['red2']}; font-size: 12px; font-weight: 600;")
            try:
                from error_report import ErrorReportDialog
                ErrorReportDialog(
                    "Ошибка", "Обрезка завершилась с ошибкой.",
                    detail=str(message), where="Монтаж: обрезка", parent=self).exec()
            except Exception:
                msgbox_critical(self, "Ошибка", f"Обрезка завершилась с ошибкой:\n{message}")
            self._report_progress(0, "Ошибка")
            self._clear_cut_status()

    @staticmethod
    def _escape_filter_path(p):
        """Экранирует путь для libavfilter (subtitles/fontsdir): прямые слэши +
        экранированное двоеточие диска (`C\\:`) + экранированная кавычка. Без
        экранирования двоеточия на Windows фильтр не инициализируется."""
        return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")

    def _extract_subtitle_fonts(self, src):
        """Извлекает вложенные шрифты (font attachments) контейнера во временную
        папку, чтобы при вшивании субтитров libass рендерил их РОДНЫМИ шрифтами
        (полная поддержка ASS-стилей). Возвращает путь к папке или None.

        Результат кешируется по (путь, mtime, размер) — повторный экспорт того же
        источника не гоняет ffmpeg заново. Папка живёт до закрытия вкладки
        (см. shutdown()), а не удаляется сразу после экспорта, как раньше."""
        stamp = self._file_cache_stamp(src)
        cache_key = (str(src), stamp) if stamp else None
        if cache_key is not None:
            cached = self._subtitle_fonts_cache.get(cache_key)
            if cached is not None and os.path.isdir(cached):
                return cached
        try:
            d = tempfile.mkdtemp(prefix="sihyx_fonts_")
            # -dump_attachment:t "" выгружает все attachments в текущую папку.
            # ffmpeg при этом завершается с ненулевым кодом (нет выходного файла) —
            # это ожидаемо, нас интересуют только извлечённые файлы.
            subprocess.run([FFMPEG, "-y", "-dump_attachment:t", "", "-i", str(src)],
                           cwd=d, capture_output=True, creationflags=CREATE_NO_WINDOW)
            if os.listdir(d):
                if cache_key is not None:
                    self._subtitle_fonts_cache[cache_key] = d
                    if len(self._subtitle_fonts_cache) > 8:
                        old_key = next(iter(self._subtitle_fonts_cache))
                        old_dir = self._subtitle_fonts_cache.pop(old_key)
                        try:
                            import shutil
                            shutil.rmtree(old_dir, ignore_errors=True)
                        except Exception:
                            pass
                return d
            os.rmdir(d)
        except Exception:
            pass
        return None

    def _discard_temp_cut(self, path, is_loaded):
        """Удаляет неточный файл быстрой обрезки, когда пользователь решил
        переделать его (перекодировкой или Smart Cut). Если файл открыт в плеере —
        сперва освобождаем источник, иначе на Windows он залочен и не удалится.
        Ошибки глушим: переделка обрезки важнее уборки дубля."""
        try:
            if is_loaded:
                try: self.player.stop()
                except Exception: pass
                try: self.player.setSource(QUrl())
                except Exception: pass
            if path and os.path.exists(path):
                os.remove(path)
        except Exception:
            pass

    def _show_cut_choice_dialog(self, title, text, buttons):
        """Диалог выбора при неточной обрезке без перекодирования — кнопки
        СВЕРХУ ВНИЗ (а не в ряд, как у стандартного QMessageBox), у каждой
        значок ⓘ с объяснением, что она делает (вариантов до 5 — в ряд не
        помещались и было неясно, чем они отличаются).

        buttons — список (key, label, tip, destructive); первая кнопка — она
        же дефолтная (Enter). Возвращает key нажатой кнопки или None (Esc/крестик)."""
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        dlg.setMinimumWidth(440)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(14)

        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(lbl)

        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        result = {'key': None}

        def _pick(key):
            result['key'] = key
            dlg.accept()

        for i, (key, label, tip, destructive) in enumerate(buttons):
            row = QHBoxLayout()
            row.setSpacing(6)
            b = QPushButton(label)
            b.setMinimumHeight(34)
            if destructive:
                b.setStyleSheet(f"QPushButton {{ color: {C['red']}; }}")
            if i == 0:
                b.setDefault(True)
                b.setAutoDefault(True)
            b.clicked.connect(lambda _=False, k=key: _pick(k))
            row.addWidget(b, 1)
            row.addWidget(info_badge(tip))
            btn_col.addLayout(row)
        lay.addLayout(btn_col)

        dlg.exec()
        return result['key']

    def _notify_cut_accuracy(self, final_path, requested_dur, exact_copy, burn_subs,
                             in_s=None, out_s=None, src=None):
        """Сообщает, удалось ли обрезать БЕЗ перекодировки точно по кадрам.

        В режиме «Быстро (копирование потоков)» начало прилипает к ближайшему
        ключевому кадру, поэтому итоговая длительность может оказаться больше
        запрошенной. Сравниваем фактическую длительность результата с заданной.

        Возвращает строку с выбором пользователя:
          'encode'   — перекодировать диапазон заново (точно, с потерями);
          'smartcut' — умная обрезка (точные границы + lossless-середина);
          'delete'   — удалить созданный неточный файл;
          None       — оставить файл как есть."""
        try:
            if burn_subs:
                msgbox_information(
                    self, "Готово",
                    "Субтитры вшиты в видео (с перекодировкой).")
                return None
            if not exact_copy:
                # Режимы перекодировки/MP3 — всегда кадрово-точные, отдельное
                # уведомление не нужно.
                return None
            meta = run_ffprobe(final_path)
            actual = 0.0
            try:
                actual = float((meta or {}).get('format', {}).get('duration', 0.0))
            except Exception:
                actual = 0.0
            # У аудиофайла кадров нет — точность меряем/формулируем по времени.
            audio_only = (self.video_stream_index is None)
            # Допуск ~1 кадр (или 0.05 c, если FPS неизвестен / это аудио).
            tol = (1.5 / self.fps) if (self.fps and self.fps > 0
                                       and not audio_only) else 0.05
            diff = abs(actual - requested_dur) if actual > 0 else 0.0
            if actual <= 0 or diff <= tol:
                msgbox_information(
                    self, "Готово — точная обрезка",
                    "Обрезано без перекодировки, точно по заданным меткам времени."
                    if audio_only else
                    "Обрезано без перекодировки, точно по заданным кадрам.")
                return None
            keep_btn = ("keep", "Оставить как есть",
                        "Оставить уже готовый файл с небольшим расхождением от "
                        "заданных меток времени — обрезка быстрая и без потери "
                        "качества.", False)
            del_btn = ("delete", "Удалить файл",
                       "Удалить с диска уже созданный неточный файл — если "
                       "результат не нужен.", True)
            if audio_only:
                # Для аудио Smart Cut неприменим (он про ключевые кадры видео).
                # Предлагаем только перекодировку, удаление или «оставить как есть».
                text = (
                    "Быстрая обрезка (копирование) НЕ попала точно по времени: "
                    "начало сдвинулось к ближайшей границе аудиокадра.\n\n"
                    f"Запрошено: {s_to_time(requested_dur)}\n"
                    f"Получилось: {s_to_time(actual)}\n"
                    f"Расхождение: {s_to_time(diff)}\n\n"
                    "Что сделать с фрагментом?")
                buttons = [keep_btn]
                if in_s is not None and out_s is not None:
                    buttons.append(("encode", "Перекодировать (точно)",
                                    "Вырезать фрагмент заново с перекодировкой — точно "
                                    "по заданному времени, но с потерей качества "
                                    "(повторное сжатие аудио).", False))
                buttons.append(del_btn)
                key = self._show_cut_choice_dialog(
                    "Не получилось точно без потерь", text, buttons)
                return key if key != "keep" else None
            # Не кадрово-точно → предлагаем варианты: Smart Cut (точно + почти без
            # потерь), полную перекодировку (точно, с потерями), удалить файл или
            # оставить как есть.
            can_retry = (in_s is not None and out_s is not None)
            text = (
                "Обрезка без перекодировки (быстро) НЕ кадрово-точная: начало "
                "сдвинулось к ближайшему ключевому кадру.\n\n"
                f"Запрошено: {s_to_time(requested_dur)}\n"
                f"Получилось: {s_to_time(actual)}\n"
                f"Расхождение: {s_to_time(diff)}\n\n"
                "Что сделать с фрагментом?")
            buttons = []
            if can_retry:
                buttons.append(("smartcut", "Smart Cut (точно, почти без потерь)",
                                "Точно нарезать по заданным меткам: копирует потоки "
                                "везде, где можно, и перекодирует только короткий "
                                "кусочек у точек реза. Почти без потери качества, "
                                "быстрее полной перекодировки.", False))
                buttons.append(("encode", "Перекодировать (точно, с потерями)",
                                "Перекодировать весь вырезанный фрагмент заново — точно "
                                "по заданным меткам времени, но с повторным сжатием "
                                "(заметнее теряется качество).", False))
                # Режет диапазон И сразу применяет «Обработку» (её текущие настройки
                # CRF/скорость/loudnorm/…) ОДНИМ проходом — без промежуточного x264-
                # реэнкода, который иначе перекодировался бы ещё раз при последующем
                # прогоне через «Обработку» (двойное поколение потерь). См.
                # EditTab._execute_cut_and_process.
                if hasattr(self.main, 'tab_media'):
                    buttons.append(("process", "Обрезать и обработать",
                                    "Точно вырезать диапазон и сразу применить текущие "
                                    "настройки вкладки «Обработка» (CRF/скорость/"
                                    "громкость) одним проходом — без двойной "
                                    "перекодировки.", False))
            if not can_retry:
                buttons.append(keep_btn)   # без смещения меток — дефолт безопасный, не «Удалить»
            buttons.append(del_btn)
            if can_retry:
                buttons.append(keep_btn)
            key = self._show_cut_choice_dialog(
                "Не получилось точно без потерь", text, buttons)
            return key if key != "keep" else None
        except Exception:
            pass
        return None

    # ── Shortcuts ─────────────────────────────────────────────────────────
    def register_shortcuts(self):
        # Контекст WidgetWithChildren: хоткеи работают только когда вкладка
        # «Монтаж» в фокусе — не перехватывают Space/I/O на других вкладках.
        ctx = Qt.ShortcutContext.WidgetWithChildrenShortcut

        def add_shortcut(seq, handler):
            act = QAction(self)
            act.setShortcut(QKeySequence(seq))
            act.setShortcutContext(ctx)
            act.triggered.connect(handler)
            self.addAction(act)

        try:
            add_shortcut(Qt.Key.Key_Space, self.toggle_play)
            add_shortcut(Qt.Key.Key_Left,  partial(self.step_frame_scrub, -1))
            add_shortcut(Qt.Key.Key_Right, partial(self.step_frame_scrub,  1))
            # F/I/O/WASD/Ctrl+S НЕ регистрируем через QKeySequence-строку — на
            # кириллической раскладке физическая клавиша шлёт Qt переведённый
            # код кириллической буквы (Ф/Ш/Щ/Ц/Ы/В/Ы), а не Key_F/I/O/A/S/D/W,
            # и такой QShortcut на ней молча не срабатывает вовсе (та же
            # природа бага, что и с Ctrl+Z/Ctrl+Y — см. keyPressEvent ниже и
            # _pan_dir_from_event в tabs.py). Обрабатываем их там же, через
            # nativeVirtualKey — независимо от раскладки.
            # Обрезка до точки воспроизведения (настраиваемые сочетания) —
            # храним QShortcut, чтобы можно было переназначить в Настройках.
            self._sc_trim_start = QShortcut(QKeySequence(self.trim_start_seq), self)
            self._sc_trim_start.setContext(ctx)
            self._sc_trim_start.activated.connect(self.trim_start_to_playhead)
            self._sc_trim_end = QShortcut(QKeySequence(self.trim_end_seq), self)
            self._sc_trim_end.setContext(ctx)
            self._sc_trim_end.activated.connect(self.trim_end_to_playhead)
            # Undo/redo: ВСЕ сочетания вешаем на ОДНО действие каждого типа через
            # setShortcuts([...]). Раньше StandardKey.Redo и явный "Ctrl+Y" были
            # ДВУМЯ разными QAction с одинаковым сочетанием (на Windows
            # StandardKey.Redo == Ctrl+Y) — Qt считал это «неоднозначным
            # сочетанием» и не срабатывал НИ ОДИН из них: Ctrl+Z работал, а
            # Ctrl+Y — нет. Один QAction с несколькими сочетаниями неоднозначности
            # не создаёт (после дедупликации ниже).
            #
            # РАСКЛАДОЧНЫЕ ЛИТЕРАЛЫ "Ctrl+Я"/"Ctrl+Н" (рус. Я=Z, Н=Y по месту
            # клавиши) СЮДА НЕ ДОБАВЛЯЕМ — повторный баг-репорт ("Ambiguous
            # shortcut overload: Ctrl+Z"/"Ctrl+?") показал, что именно они и
            # ЛОМАЮТ act_undo/act_redo: физическое нажатие Ctrl+Z на кириллице
            # Qt внутренне сопоставляет С ОБОИМИ кандидатами сразу (и с
            # "Ctrl+Z" через ASCII-фолбэк Windows для Ctrl+буква, и с
            # "Ctrl+Я"/"Ctrl+Н" через переведённый раскладкой символ) — два
            # разных QKeySequence в списке ОДНОГО QAction, оба совпавшие с
            # одним и тем же событием, Qt тоже считает неоднозначностью и не
            # срабатывает вообще. Кириллицу целиком закрывает keyPressEvent
            # ниже через nativeVirtualKey (не зависит от раскладки в принципе).
            def _dedup_seqs(seqs):
                seen = set(); out = []
                for s in seqs:
                    key = s.toString()
                    if key and key not in seen:
                        seen.add(key); out.append(s)
                return out

            act_undo = QAction(self)
            act_undo.setShortcuts(_dedup_seqs([QKeySequence(QKeySequence.StandardKey.Undo),
                                   QKeySequence("Ctrl+Z")]))
            act_undo.setShortcutContext(ctx)
            act_undo.triggered.connect(self.undo)
            self.addAction(act_undo)
            act_redo = QAction(self)
            act_redo.setShortcuts(_dedup_seqs([QKeySequence(QKeySequence.StandardKey.Redo),
                                   QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")]))
            act_redo.setShortcutContext(ctx)
            act_redo.triggered.connect(self.redo)
            self.addAction(act_redo)
            # Раньше тут ещё висела «подстраховка» — те же Ctrl+Z/Ctrl+Y вторым
            # QShortcut'ом WidgetShortcut прямо на self.waveform (на случай, если
            # после перетаскивания маркеров IN/OUT фокус остаётся на волне, а
            # WidgetWithChildrenShortcut выше по дереву почему-то не срабатывает).
            # На самом деле причиной был дубль сочетания ВНУТРИ act_undo/act_redo
            # (см. выше) — Qt считал его неоднозначным и не срабатывал act_undo/
            # act_redo вообще, независимо от фокуса. После дедупликации
            # WidgetWithChildrenShortcut сам покрывает фокус на волне (она —
            # дочерний виджет self), а второй QShortcut с тем же сочетанием на
            # самой волне лишь СОЗДАВАЛ неоднозначность — убран.
        except Exception as e:
            self.main.log(f"shortcuts error: {e}")

    # Кириллица: QKeySequence-строкой ("Ctrl+Я"/"Ctrl+Н") её ловить нельзя —
    # QShortcut сопоставляет события по УЖЕ переведённому раскладкой Qt-коду
    # клавиши, а не по физической клавише, и вдобавок такая строка сама
    # ломала act_undo/act_redo неоднозначностью (см. комментарий выше). Единый
    # надёжный способ — как WASD-пан в фоторедакторе (tabs.py,
    # _pan_dir_from_event): читать ФИЗИЧЕСКУЮ клавишу через nativeVirtualKey
    # (Windows VK_Z=0x5A, VK_Y=0x59) — не зависит от раскладки. Событие сюда
    # доходит только если ни один QAction/QShortcut/дочерний виджет его не
    # поглотил раньше — для латиницы Ctrl+Z уже работает через act_undo выше,
    # это лишь докрывает случай, когда переведённый код клавиши не совпал.
    _VK_Z = 0x5A
    _VK_Y = 0x59
    _VK_W = 0x57
    _VK_A = 0x41
    _VK_S = 0x53
    _VK_D = 0x44
    _VK_F = 0x46
    _VK_I = 0x49
    _VK_O = 0x4F

    def keyPressEvent(self, event):
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            try:
                vk = event.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk == self._VK_Z:
                self.redo() if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier) else self.undo()
                event.accept()
                return
            if vk == self._VK_Y:
                self.redo()
                event.accept()
                return
            # Ctrl+S («Обрезать») — тот же баг, что и Ctrl+Z/Y на кириллице:
            # QShortcut("Ctrl+S") на переведённом коде клавиши не срабатывает.
            if vk == self._VK_S or event.key() == Qt.Key.Key_S:
                self.start_cut()
                event.accept()
                return
        elif not (event.modifiers() & (Qt.KeyboardModifier.AltModifier
                                        | Qt.KeyboardModifier.ShiftModifier)):
            # WASD покадрового шага + F/I/O — по физической клавише
            # (nativeVirtualKey), с фолбэком на event.key() для латиницы (см.
            # register_shortcuts выше и _pan_dir_from_event в tabs.py — тот же приём).
            try:
                vk = event.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk in (self._VK_A, self._VK_S) or event.key() in (Qt.Key.Key_A, Qt.Key.Key_S):
                self.step_frame_scrub(-1)
                event.accept()
                return
            if vk in (self._VK_D, self._VK_W) or event.key() in (Qt.Key.Key_D, Qt.Key.Key_W):
                self.step_frame_scrub(1)
                event.accept()
                return
            if vk == self._VK_F or event.key() == Qt.Key.Key_F:
                self.toggle_fullscreen()
                event.accept()
                return
            if vk == self._VK_I or event.key() == Qt.Key.Key_I:
                self.set_in_point()
                event.accept()
                return
            if vk == self._VK_O or event.key() == Qt.Key.Key_O:
                self.set_out_point()
                event.accept()
                return
        super().keyPressEvent(event)

    def compute_step(self, fast=False):
        step = 1.0 / self.fps if (self.fps and self.fps > 0) else 0.04
        return step * (5 if fast else 1)

    def move_in(self, dir_sign=1):
        self.push_undo()
        fast = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.compute_step(fast)
        new_in = max(0.0, min(self.duration, self.current_in + dir_sign * step))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - step)
        self.set_in_out(new_in, self.current_out)

    def move_out(self, dir_sign=1):
        self.push_undo()
        fast = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
        step = self.compute_step(fast)
        new_out = max(0.0, min(self.duration, self.current_out + dir_sign * step))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + step)
        self.set_in_out(self.current_in, new_out)

    # ── Обрезка до точки воспроизведения (плейхеда) ─────────────────────────
    def trim_start_to_playhead(self):
        """Ставит точку IN на текущую позицию воспроизведения (обрезает старт)."""
        if self.duration <= 0:
            return
        self.push_undo()
        # Берём время ПОКАЗАННОГО кадра, а не «сырую» позицию плеера: они могут
        # отличаться на доли кадра, а рез обязан совпадать с тем, что видно.
        t = self._clock_pos_s()
        new_in = max(0.0, min(t, self.duration))
        if new_in >= self.current_out:
            new_in = max(0.0, self.current_out - 0.04)
        self.set_in_out(new_in, self.current_out)
        # Возвращаем фокус на вкладку: если он был на нативной видео-поверхности
        # (overlay-режим, исключена из WidgetWithChildrenShortcut), Ctrl+Z после
        # обрезки иначе не доходил до undo. Кнопка с NoFocus фокус не перехватит.
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def trim_end_to_playhead(self):
        """Ставит точку OUT на текущую позицию воспроизведения (обрезает конец)."""
        if self.duration <= 0:
            return
        self.push_undo()
        t = self._clock_pos_s()
        new_out = max(0.0, min(t, self.duration))
        if new_out <= self.current_in:
            new_out = min(self.duration, self.current_in + 0.04)
        self.set_in_out(self.current_in, new_out)
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def _trim_ctx_menu(self, pos=None):
        """Контекстное меню аудио-визуализации (ПКМ): обрезка старт/конец до
        плейхеда. Сочетания показываются справа как подсказка (через \\t), но НЕ
        регистрируются повторно — настоящие хоткеи висят на QShortcut."""
        if self.duration <= 0:
            return
        menu = QMenu(self)
        a_start = menu.addAction(
            f"Обрезать старт до точки воспроизведения\t{self.trim_start_seq}")
        a_start.triggered.connect(self.trim_start_to_playhead)
        a_end = menu.addAction(
            f"Обрезать конец до точки воспроизведения\t{self.trim_end_seq}")
        a_end.triggered.connect(self.trim_end_to_playhead)
        menu.exec(QCursor.pos())

    def get_trim_shortcuts(self):
        """(start_seq, end_seq) — для отображения/редактирования в Настройках."""
        return (self.trim_start_seq, self.trim_end_seq)

    def set_trim_shortcuts(self, start_seq, end_seq, save=True):
        """Переназначает сочетания обрезки. Пустое значение → дефолт."""
        self.trim_start_seq = (start_seq or "Shift+C").strip() or "Shift+C"
        self.trim_end_seq   = (end_seq or "Shift+V").strip() or "Shift+V"
        try:
            if getattr(self, "_sc_trim_start", None) is not None:
                self._sc_trim_start.setKey(QKeySequence(self.trim_start_seq))
            if getattr(self, "_sc_trim_end", None) is not None:
                self._sc_trim_end.setKey(QKeySequence(self.trim_end_seq))
        except Exception:
            pass
        if save:
            self.save_settings()

    # ── Pan slider ────────────────────────────────────────────────────────
    def on_wave_view_changed(self, view_offset, visible_duration):
        self.update_pan_slider_values()
        self.update_wave_scroll()

    # ── Horizontal scrollbar over the waveform ─────────────────────────────
    def on_wave_scroll(self, value):
        """Пользователь двигает горизонтальную прокрутку → смещаем окно обзора волны."""
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            return
        self.waveform.set_view_offset(value / 1000.0)

    def update_wave_scroll(self):
        """Синхронизирует горизонтальную прокрутку с масштабом/положением волны.
        Прячется, когда прокручивать нечего (волна целиком помещается)."""
        sb = getattr(self, "wave_scroll", None)
        if sb is None:
            return
        duration = self.waveform.duration or self.duration or 0.0
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        if duration <= 0 or pan_range <= 1e-6:
            sb.setVisible(False)
            return
        sb.setVisible(True)
        sb.blockSignals(True)
        sb.setMinimum(0)
        sb.setMaximum(int(pan_range * 1000))
        sb.setPageStep(max(1, int(visible * 1000)))
        sb.setSingleStep(max(1, int(visible * 100)))
        sb.setValue(int(self.waveform.view_offset * 1000))
        sb.blockSignals(False)

    def update_pan_slider_values(self):
        pan_row = getattr(self, 'pan_row_w', None)
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            self.pan_slider.setEnabled(False)
            if pan_row is not None:
                pan_row.setVisible(False)
            return
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        if pan_range <= 0.0:
            self.pan_slider.setEnabled(False); self.pan_slider.setValue(0)
            if pan_row is not None:
                pan_row.setVisible(False)
            return
        self.pan_slider.setEnabled(True)
        if pan_row is not None:
            pan_row.setVisible(True)
        val = int((self.waveform.view_offset / pan_range) * 1000) if pan_range > 0 else 0
        self.pan_slider.blockSignals(True)
        self.pan_slider.setValue(max(0, min(1000, val)))
        self.pan_slider.blockSignals(False)

    def on_pan_moved(self, value):
        duration = self.waveform.duration or self.duration or 0.0
        if duration <= 0:
            return
        visible = max(0.001, duration / self.waveform.zoom)
        pan_range = max(0.0, duration - visible)
        offset = (value / 1000.0) * pan_range if pan_range > 0 else 0.0
        self.waveform.set_view_offset(offset)

    # ── Settings ──────────────────────────────────────────────────────────
    def save_settings(self):
        try:
            settings = {
                'mode_index': int(self.cmb_mode.currentIndex()),
                'encoder_index': int(self.cmb_encoder.currentIndex()),
                'sub_style_index': int(self.cmb_sub_style.currentIndex()),
                'overwrite':  bool(self.chk_overwrite.isChecked()),
                'burn_subs':  bool(self.chk_burn_subs.isChecked()),
                'zoom':       float(self.waveform.zoom),
                'view_offset': float(self.waveform.view_offset),
                'volume':     int(self.vol_slider.value()),   # громкость теперь сохраняется (пункт B)
                'trim_start_seq': self.trim_start_seq,
                'trim_end_seq':   self.trim_end_seq,
                'export_dir':     self.export_dir or "",
                'subs_in_frame':  bool(getattr(self, '_subs_in_frame', True)),
                'scrub_audio':    bool(getattr(self, '_scrub_audio_enabled', True)),
                'pb_quality_index': int(self.cmb_pb_quality.currentIndex())
                    if hasattr(self, 'cmb_pb_quality') else 0,
                'proxy_min': int(self.spin_proxy_min.value())
                    if hasattr(self, 'spin_proxy_min') else 0,
                'subtitle_style': dict(getattr(self, '_last_subtitle_style', None) or {}) or None,
            }
            # Атомарно (временный файл + подмена): прямая запись обрезала файл
            # ДО того, как в него ляжет новое содержимое, и жёсткое завершение
            # процесса в этот момент теряло настройки Монтажа целиком.
            save_json_atomic(EDITOR_SETTINGS_PATH, settings)
        except Exception:
            pass

    def load_settings(self):
        if not os.path.exists(EDITOR_SETTINGS_PATH):
            return
        try:
            with open(EDITOR_SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = json.load(f)
            self.cmb_mode.setCurrentIndex(int(settings.get('mode_index', 1)))
            self.cmb_encoder.setCurrentIndex(int(settings.get('encoder_index', 0)))
            if hasattr(self, 'cmb_pb_quality'):
                # Без сигнала: файла ещё нет, применится при загрузке.
                self.cmb_pb_quality.blockSignals(True)
                self.cmb_pb_quality.setCurrentIndex(int(settings.get('pb_quality_index', 0)))
                self.cmb_pb_quality.blockSignals(False)
            if hasattr(self, 'spin_proxy_min'):
                self.spin_proxy_min.blockSignals(True)
                self.spin_proxy_min.setValue(int(settings.get('proxy_min', 0)))
                self.spin_proxy_min.blockSignals(False)
            self.cmb_sub_style.setCurrentIndex(int(settings.get('sub_style_index', 2)))
            self.chk_overwrite.setChecked(bool(settings.get('overwrite', True)))
            self.chk_burn_subs.setChecked(bool(settings.get('burn_subs', False)))
            self.waveform.zoom        = max(0.25, min(200.0, float(settings.get('zoom', 1.0))))
            self.waveform.view_offset = max(0.0, float(settings.get('view_offset', 0.0)))
            vol = max(0, min(100, int(settings.get('volume', 100))))
            self.vol_slider.setValue(vol)
            self.audio_output.setVolume(vol / 100.0)
            self.set_trim_shortcuts(
                settings.get('trim_start_seq', self.trim_start_seq),
                settings.get('trim_end_seq', self.trim_end_seq),
                save=False)
            self.export_dir = settings.get('export_dir', "") or ""
            self._update_export_dir_label()
            # Покадровый скраб-звук теперь всегда включён (настройка убрана из UI).
            self._scrub_audio_enabled = True
            # Последние настройки стиля «Создать субтитры» (шрифт/размер/цвет/…) —
            # см. create_subtitles/SubtitleCreatorDialog.default_style.
            self._last_subtitle_style = settings.get('subtitle_style') or None
        except Exception:
            pass

    # ── Cleanup (вызывается из главного окна при закрытии) ──────────────────
    def shutdown(self):
        if not self._ready:
            return
        try:
            self.save_settings()
        except Exception:
            pass
        try:
            self.sync_timer.stop()
        except Exception:
            pass
        try:
            self.player.stop()
        except Exception:
            pass
        # Останавливаем звук покадровой перемотки: устройство вывода и фоновый
        # декодер окон PCM (он держит запущенный ffmpeg).
        try:
            self._release_scrub_sink()
        except Exception:
            pass
        try:
            eng = getattr(self, "_audio_scrub", None)
            if eng is not None:
                eng.stop()
                eng.wait(1500)
                self._audio_scrub = None
        except Exception:
            pass
        # Останавливаем фоновый поток превью кадров полосы воспроизведения.
        try:
            if getattr(self, 'seek_preview', None) is not None:
                self.seek_preview.shutdown()
        except Exception:
            pass
        # …и поток предекодера точных кадров (он держит запущенный ffmpeg).
        try:
            eng = getattr(self, '_frames', None)
            if eng is not None:
                eng.stop(); eng.wait(1500)
        except Exception:
            pass
        # Убиваем все фоновые ffmpeg-процессы, чтобы не остались зомби (баг #3).
        for attr in ('ffmpeg_thread', 'proxy_thread', 'audio_worker',
                     '_vinp_worker', '_trk_worker'):
            w = getattr(self, attr, None)
            if w is None:
                continue
            try:
                if hasattr(w, 'stop'):
                    w.stop()
                if w.isRunning():
                    if not w.wait(2000):
                        w.terminate(); w.wait()
            except Exception:
                pass
        try:
            if getattr(self, 'audio_worker', None) and self.audio_worker.tmp_wav \
                    and os.path.exists(self.audio_worker.tmp_wav):
                os.remove(self.audio_worker.tmp_wav)
        except Exception:
            pass
        try:
            if self.tmp_proxy_file and os.path.exists(self.tmp_proxy_file):
                os.remove(self.tmp_proxy_file)
        except Exception:
            pass
        # Дожидаемся фоновых извлечений субтитров.
        for ex in list(getattr(self, '_sub_threads', [])):
            try:
                if ex.isRunning():
                    if not ex.wait(2000):
                        ex.terminate(); ex.wait()
            except Exception:
                pass
        # Останавливаем ASS-рендер (таймер + libass + временный файл).
        try:
            self._stop_ass()
        except Exception:
            pass
        # Закрываем полноэкранное окно, если открыто.
        try:
            if getattr(self, '_fs_window', None) is not None:
                self.exit_fullscreen()
        except Exception:
            pass
        # Закрываем окно-оверлей субтитров.
        try:
            if self.sub_overlay is not None:
                self.sub_overlay.close()
                self.sub_overlay.deleteLater()
                self.sub_overlay = None
        except Exception:
            pass
        # Чистим временные папки извлечённых шрифтов, накопленные кэшем (см.
        # _extract_subtitle_fonts) — они больше не удаляются сразу после экспорта.
        try:
            import shutil
            for d in self._subtitle_fonts_cache.values():
                shutil.rmtree(d, ignore_errors=True)
            self._subtitle_fonts_cache.clear()
        except Exception:
            pass
        # …и временные PNG наложенных картинок (см. _render_export_overlays).
        try:
            import shutil
            d = getattr(self, "_overlay_tmp_dir", None)
            if d:
                shutil.rmtree(d, ignore_errors=True)
            self._overlay_tmp_dir = None
        except Exception:
            pass

    def closeEvent(self, ev):
        # На случай использования вкладки как самостоятельного окна.
        self.shutdown()
        super().closeEvent(ev)


# ─── Standalone test entry point ───────────────────────────────────────────────
def main():
    app = QApplication(sys.argv)
    app.setApplicationName("SI-HYX — Монтаж")
    app.setStyle("Fusion")
    w = EditTab()
    w.resize(1400, 900)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
