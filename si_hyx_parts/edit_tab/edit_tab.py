# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab. Public namespace: edit_tab."""
import edit_tab as _api
from si_hyx_parts.edit_tab.layout import EditTabLayoutMixin
from si_hyx_parts.edit_tab.tracks import EditTabTracksMixin
from si_hyx_parts.edit_tab.playback import EditTabPlaybackMixin
from si_hyx_parts.edit_tab.timeline import EditTabTimelineMixin
from si_hyx_parts.edit_tab.effects import EditTabEffectsMixin
from si_hyx_parts.edit_tab.export import EditTabExportMixin
from si_hyx_parts.edit_tab.entrance_actions import EditTabEntranceMixin


# ─── Edit Tab ─────────────────────────────────────────────────────────────────
class EditTab(
    EditTabLayoutMixin,
    EditTabTracksMixin,
    EditTabPlaybackMixin,
    EditTabTimelineMixin,
    EditTabEffectsMixin,
    EditTabExportMixin,
    EditTabEntranceMixin,
    _api.QWidget,
):
    # Боковая панель монтажа: кнопки масштабируются под ровно столько значков в высоту.
    _MSIDE_COUNT = 8
    _MSIDE_GAP = 6

    def __init__(self, main_window=None):
        super().__init__()
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

    def _notify_busy_rename(self, wanted, saved):
        """Сообщает, что целевой файл был занят и обрезка сохранена под другим
        именем (а не потеряна с ошибкой WinError 32)."""
        msg = (f"Файл «{_api.os.path.basename(wanted)}» был занят другим процессом "
               f"(скорее всего, его перекодирует вкладка «Обработка»).\n\n"
               f"Обрезка сохранена под именем «{_api.os.path.basename(saved)}».")
        try:
            if self.main is not None and hasattr(self.main, "log"):
                self.main.log(msg.replace("\n\n", " "))
        except Exception:
            pass
        try:
            _api.msgbox_information(self, "Файл был занят", msg)
        except Exception:
            pass

    def eventFilter(self, watched, event):
        # Колесо мыши НЕ меняет значения полей (спинбоксы кадров, комбобоксы
        # дорожек/режима, ползунки громкости/позиции) — частая причина случайных
        # изменений. Виджет волны (WaveformWidget) не входит в эти типы → его
        # зум колесом сохраняется.
        # Шкала уровня звука изменила высоту → пересчёт размера кнопок (ровно 8).
        if (event.type() == _api.QEvent.Type.Resize
                and watched is getattr(self, "audio_meter", None)):
            self._resize_montage_side_btns(watched.height())
        if event.type() == _api.QEvent.Type.Wheel and isinstance(
                watched, (_api.QSpinBox, _api.QComboBox, _api.QSlider)):
            # Виджеты с пометкой wheelAlways (ползунок громкости) — колесо меняет
            # значение ВСЕГДА: пропускаем событие к их собственному wheelEvent.
            if watched.property("wheelAlways"):
                return False
            return True
        # Двойной клик по видео → переключение полноэкранного режима.
        if (event.type() == _api.QEvent.Type.MouseButtonDblClick
                and watched is self.video_widget):
            self.toggle_fullscreen()
            return True
        # Главное окно подвинули/изменили → ведём за ним оверлей субтитров.
        if (watched is self._overlay_win
                and event.type() in (_api.QEvent.Type.Move, _api.QEvent.Type.Resize,
                                     _api.QEvent.Type.WindowStateChange)):
            self._position_overlay()
        if event.type() == _api.QEvent.Type.DragEnter:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction(); return True
        if event.type() == _api.QEvent.Type.DragMove:
            md = event.mimeData()
            if md.hasUrls() or md.hasText():
                event.acceptProposedAction(); return True
        if event.type() == _api.QEvent.Type.Drop:
            md = event.mimeData(); loaded = False
            try:
                urls = md.urls()
                if urls:
                    local = urls[0].toLocalFile()
                    if local and _api.os.path.exists(local):
                        self.load_file(local); loaded = True
            except Exception:
                pass
            if not loaded:
                try:
                    txt = md.text()
                    if txt:
                        path = txt.strip()
                        if _api.os.path.exists(path):
                            self.load_file(path); loaded = True
                except Exception:
                    pass
            if loaded:
                event.acceptProposedAction()
                return True
        return super().eventFilter(watched, event)

    # ── Внешняя озвучка (отдельный аудиофайл, синхронный с видео) ──────────────
    _SUB_EXTS = ('.srt', '.ass', '.ssa', '.vtt', '.sub')
    _AUDIO_EXTS = ('.mp3', '.aac', '.m4a', '.ac3', '.eac3', '.flac', '.wav',
                   '.opus', '.ogg', '.dts', '.mka', '.wma')

    # Типовые названия папок с субтитрами — подпапка с таким именем считается
    # «своей» для видео даже если её имя не перекликается со стемом файла.
    _SUB_FOLDER_NAMES = {'subs', 'sub', 'subtitles', 'subtitle', 'ass', 'srt',
                          'субтитры', 'сабы'}

    # Битмап-субтитры (картинками) свой оверлей рисовать не умеет — для них
    # оставляем встроенный рендер QtMultimedia.
    _BITMAP_SUB_CODECS = {
        'hdmv_pgs_subtitle', 'pgssub', 'dvd_subtitle', 'dvdsub',
        'dvb_subtitle', 'dvbsub', 'xsub',
    }

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
    # Через сколько после pause() возвращать звук. Пауза останавливает подачу
    # сэмплов, но устройство доигрывает уже принятую очередь, а mute у
    # ffmpeg-бэкенда гасит выход сессии, а не её вход: снятый сразу mute
    # открывал этот хвост, и покадровый шаг звучал дважды. Замер щупом WASAPI
    # (пик аудиосессии процесса): хвост держится до +200 мс после pause,
    # с задержкой 250 мс слышимых замеров не остаётся вовсе.
    _PREROLL_UNMUTE_MS = 260
    # Как часто во время серии покадровых шагов подтягивать ПЛЕЕР к выбранному
    # кадру. Картинку на шаге даёт предекодер, звук — скраббер, поэтому плееру
    # каждый шаг не нужен, а его setPosition на тяжёлом источнике — полная
    # раскрутка GOP (см. _dispatch_frame_seek). Итоговую позицию серии досылает
    # _flush_frame_seek, так что «Воспроизвести» стартует там, где стоит монтаж.
    _SCRUB_SEEK_MS = 250

    # ── Скраб-звук при покадровой перемотке ─────────────────────────────────
    # Длина «блипа»: кадр, но не короче — на 60 fps один кадр (16.7 мс) на слух
    # почти щелчок. При удержании клавиши срезы идут подряд и складываются в
    # непрерывную перемотку по звуку, как в монтажках.
    _SCRUB_BLIP_MIN_S = 0.045
    _SCRUB_BLIP_MAX_S = 0.120

    # ── Shortcuts ─────────────────────────────────────────────────────────
    def register_shortcuts(self, target=None):
        """Один набор команд для вкладки, полноэкранного окна и его панели."""
        if target is None:
            target = self
        # Контекст WidgetWithChildren: хоткеи работают только когда вкладка
        # «Монтаж» в фокусе — не перехватывают Space/I/O на других вкладках.
        ctx = _api.Qt.ShortcutContext.WidgetWithChildrenShortcut

        def add_shortcut(seq, handler):
            act = _api.QAction(target)
            act.setShortcut(_api.QKeySequence(seq))
            act.setShortcutContext(ctx)
            act.triggered.connect(handler)
            target.addAction(act)

        try:
            add_shortcut(_api.Qt.Key.Key_Space, self.toggle_play)
            add_shortcut(_api.Qt.Key.Key_Left,  _api.partial(self.step_frame_scrub, -1))
            add_shortcut(_api.Qt.Key.Key_Right, _api.partial(self.step_frame_scrub,  1))
            # F/I/O/WASD/Ctrl+S НЕ регистрируем через QKeySequence-строку — на
            # кириллической раскладке физическая клавиша шлёт Qt переведённый
            # код кириллической буквы (Ф/Ш/Щ/Ц/Ы/В/Ы), а не Key_F/I/O/A/S/D/W,
            # и такой QShortcut на ней молча не срабатывает вовсе (та же
            # природа бага, что и с Ctrl+Z/Ctrl+Y — см. keyPressEvent ниже и
            # _pan_dir_from_event в tabs.py). Обрабатываем их там же, через
            # nativeVirtualKey — независимо от раскладки.
            # Обрезка до точки воспроизведения (настраиваемые сочетания) —
            # храним QShortcut, чтобы можно было переназначить в Настройках.
            target._sc_trim_start = _api.QShortcut(_api.QKeySequence(self.trim_start_seq), target)
            target._sc_trim_start.setContext(ctx)
            target._sc_trim_start.activated.connect(self.trim_start_to_playhead)
            target._sc_trim_end = _api.QShortcut(_api.QKeySequence(self.trim_end_seq), target)
            target._sc_trim_end.setContext(ctx)
            target._sc_trim_end.activated.connect(self.trim_end_to_playhead)
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

            act_undo = _api.QAction(target)
            act_undo.setShortcuts(_dedup_seqs([_api.QKeySequence(_api.QKeySequence.StandardKey.Undo),
                                   _api.QKeySequence("Ctrl+Z")]))
            act_undo.setShortcutContext(ctx)
            act_undo.triggered.connect(self.undo)
            target.addAction(act_undo)
            act_redo = _api.QAction(target)
            act_redo.setShortcuts(_dedup_seqs([_api.QKeySequence(_api.QKeySequence.StandardKey.Redo),
                                   _api.QKeySequence("Ctrl+Y"), _api.QKeySequence("Ctrl+Shift+Z")]))
            act_redo.setShortcutContext(ctx)
            act_redo.triggered.connect(self.redo)
            target.addAction(act_redo)
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
        if event.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
            try:
                vk = event.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk == self._VK_Z:
                self.redo() if (event.modifiers() & _api.Qt.KeyboardModifier.ShiftModifier) else self.undo()
                event.accept()
                return
            if vk == self._VK_Y:
                self.redo()
                event.accept()
                return
            # Ctrl+S («Обрезать») — тот же баг, что и Ctrl+Z/Y на кириллице:
            # QShortcut("Ctrl+S") на переведённом коде клавиши не срабатывает.
            if vk == self._VK_S or event.key() == _api.Qt.Key.Key_S:
                self.start_cut()
                event.accept()
                return
        elif not (event.modifiers() & (_api.Qt.KeyboardModifier.AltModifier
                                        | _api.Qt.KeyboardModifier.ShiftModifier)):
            # WASD покадрового шага + F/I/O — по физической клавише
            # (nativeVirtualKey), с фолбэком на event.key() для латиницы (см.
            # register_shortcuts выше и _pan_dir_from_event в tabs.py — тот же приём).
            try:
                vk = event.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk in (self._VK_A, self._VK_S) or event.key() in (_api.Qt.Key.Key_A, _api.Qt.Key.Key_S):
                self.step_frame_scrub(-1)
                event.accept()
                return
            if vk in (self._VK_D, self._VK_W) or event.key() in (_api.Qt.Key.Key_D, _api.Qt.Key.Key_W):
                self.step_frame_scrub(1)
                event.accept()
                return
            if vk == self._VK_F or event.key() == _api.Qt.Key.Key_F:
                self.toggle_fullscreen()
                event.accept()
                return
            if vk == self._VK_I or event.key() == _api.Qt.Key.Key_I:
                self.set_in_point()
                event.accept()
                return
            if vk == self._VK_O or event.key() == _api.Qt.Key.Key_O:
                self.set_out_point()
                event.accept()
                return
        super().keyPressEvent(event)

    def get_trim_shortcuts(self):
        """(start_seq, end_seq) — для отображения/редактирования в Настройках."""
        return (self.trim_start_seq, self.trim_end_seq)

    def set_trim_shortcuts(self, start_seq, end_seq, save=True):
        """Переназначает сочетания обрезки. Пустое значение → дефолт."""
        self.trim_start_seq = (start_seq or "Shift+C").strip() or "Shift+C"
        self.trim_end_seq   = (end_seq or "Shift+V").strip() or "Shift+V"
        try:
            fs = getattr(self, "_fs_window", None)
            for target in (self, fs, getattr(fs, "bar", None)):
                if getattr(target, "_sc_trim_start", None) is not None:
                    target._sc_trim_start.setKey(_api.QKeySequence(self.trim_start_seq))
                if getattr(target, "_sc_trim_end", None) is not None:
                    target._sc_trim_end.setKey(_api.QKeySequence(self.trim_end_seq))
        except Exception:
            pass
        if save:
            self.save_settings()

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
            _api.save_json_atomic(_api.EDITOR_SETTINGS_PATH, settings)
        except Exception:
            pass

    def load_settings(self):
        if not _api.os.path.exists(_api.EDITOR_SETTINGS_PATH):
            return
        try:
            with open(_api.EDITOR_SETTINGS_PATH, "r", encoding="utf-8") as f:
                settings = _api.json.load(f)
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
                     '_vinp_worker', '_trk_worker', '_entrance_worker'):
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
                    and _api.os.path.exists(self.audio_worker.tmp_wav):
                _api.os.remove(self.audio_worker.tmp_wav)
        except Exception:
            pass
        try:
            if self.tmp_proxy_file and _api.os.path.exists(self.tmp_proxy_file):
                _api.os.remove(self.tmp_proxy_file)
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


EditTab.__module__ = _api.__name__
_api.EditTab = EditTab
