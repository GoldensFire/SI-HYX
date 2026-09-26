# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: __init__. Public namespace: edit_tab."""
import edit_tab as _api


def __init__(self, main_window=None):
    super(_api.EditTab, self).__init__()
    self.main = main_window
    self._ready = False

    if not _api._HAS_MULTIMEDIA:
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
    self._sub_sel_entry = None  # последняя РЕАЛЬНО выбранная дорожка субтитров
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
    self._grid = _api.FrameGrid(0.0, 0.0)
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
    # Позиция, накопленная серией шагов и ещё не отданная плееру, и время
    # последней отдачи: во время удержания стрелки плеер получает позицию не
    # чаще _SCRUB_SEEK_MS (см. _dispatch_frame_seek / _flush_frame_seek).
    self._frame_seek_deferred_ms = None
    self._frame_seek_last_at = 0.0
    # Отложенный возврат звука после прогрева (см. _restore_preroll_mute).
    self._preroll_unmute_pending = False
    self._preroll_unmute_gen = 0
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
    self.undo_stack: _api.deque = _api.deque(maxlen=50)
    self.redo_stack: _api.deque = _api.deque(maxlen=50)

    # Настраиваемые сочетания обрезки до точки воспроизведения (Монтаж →
    # Настройки). Применяются в register_shortcuts / set_trim_shortcuts.
    self.trim_start_seq = "Shift+C"   # обрезать СТАРТ (IN) до плейхеда
    self.trim_end_seq   = "Shift+V"   # обрезать КОНЕЦ (OUT) до плейхеда

    self.player = _api.QMediaPlayer()
    self.audio_output = _api.QAudioOutput()
    self.player.setAudioOutput(self.audio_output)
    # Отключили наушники / сменилось устройство вывода — переезжаем на
    # живое, иначе сеанс WASAPI аннулируется и звук пропадает до
    # перезапуска (см. install_audio_device_recovery).
    self._audio_dev_watch = _api.install_audio_device_recovery(self.audio_output)
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

    self.sync_timer = _api.QTimer(self)
    self.sync_timer.setInterval(80)
    self.sync_timer.timeout.connect(self.sync_ui)

    # Идле-таймер «активной перемотки» для VideoCanvas.set_scrub_active — см.
    # seek_to(). Пока идут seek'и (протяжка слайдера/волны), таймер постоянно
    # перезапускается; как только он ОТРАБОТАЛ (перемотка утихла) — возвращаем
    # сглаживание кадра.
    self._scrub_idle_timer = _api.QTimer(self)
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

    self.setFocusPolicy(_api.Qt.FocusPolicy.StrongFocus)
    self._ready = True

def _build_unavailable_ui(self):
    lay = _api.QVBoxLayout(self)
    lbl = _api.QLabel(
        "Модуль мультимедиа PyQt6 недоступен.\n\n"
        "Видеоредактор требует QtMultimedia. Установите PyQt6 с поддержкой "
        "мультимедиа, чтобы пользоваться вкладкой «Монтаж».")
    lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
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
    root = _api.QHBoxLayout(self)
    root.setContentsMargins(0, 0, 0, 0)
    root.setSpacing(0)

    return root
