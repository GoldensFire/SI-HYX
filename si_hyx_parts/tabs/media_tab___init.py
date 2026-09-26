# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab: __init__. Public namespace: tabs."""
import tabs as _api


def __init__(self, main_win):
    super(_api.MediaTab, self).__init__()
    self.main = main_win
    self.items = []
    self._item_map: dict = {}
    self._item_data_map: dict = {}
    # iid'ы, удалённые из очереди пользователем — та же живая ссылка
    # передаётся ProcessWorker'у, чтобы он мог прервать УЖЕ идущую обработку
    # конкретного файла, а не только не начинать ещё не стартовавшие.
    self._removed_ids: set = set()
    self.pool = _api.QThreadPool()
    self.export_dir = ""  # пусто = экспортировать рядом с исходником
    self.setAcceptDrops(True)
    # Колонка «Время» (7): сколько длится перекодирование каждого файла.
    # _proc_started: iid → момент старта (time.monotonic); _proc_running —
    # iid'ы, которые сейчас кодируются (таймер тикает их время вверх).
    self._proc_started: dict = {}
    self._proc_running: set = set()
    self._item_pass: dict = {}   # iid → «N/total» текущего прохода подбора картинки
    self._elapsed_timer = _api.QTimer(self)
    self._elapsed_timer.setInterval(500)
    self._elapsed_timer.timeout.connect(self._tick_elapsed)
    # Пока воркер работает, каждые 500мс подсовываем ему АКТУАЛЬНЫЕ настройки
    # с виджетов (см. _settings_sync_tick) — иначе файл, добавленный в очередь
    # уже во время обработки, кодировался бы с настройками, замороженными в
    # момент нажатия «НАЧАТЬ» (та же проблема, что и с CRF/скоростью/etc.,
    # изменёнными на лету).
    self._settings_sync_timer = _api.QTimer(self)
    self._settings_sync_timer.setInterval(500)
    self._settings_sync_timer.timeout.connect(self._settings_sync_tick)
    self.setup_ui()
    self.thumb_sig.connect(self.set_thumb)
    self.media_info_sig.connect(self._apply_media_info)
    self.media_lufs_sig.connect(self._apply_media_lufs)
    self.worker = None

def _find_item(self, iid) -> '_api.QTreeWidgetItem | None':
    """Возвращает QTreeWidgetItem по iid за O(1)."""
    return self._item_map.get(iid)

def setup_ui(self):
    """Сборка интерфейса вкладки «Обработка».

        Раньше — один метод на ~560 строк. Разбит по границам групп настроек:
        каждая группа сама себя создаёт, наполняет и добавляет в rv_inner,
        поэтому секции независимы. Порядок вызовов и сами операции не менялись."""
    l, right_container, right_layout, rv_inner, rw, w = self._build_queue_and_panel()
    self._build_audio_group(rv_inner)
    self._build_video_group(rv_inner)
    self._build_images_group(rv_inner)
    self._build_footer(l, right_container, right_layout, rv_inner, rw, w)

def _build_queue_and_panel(self):
    """Левая часть (очередь файлов, кнопки) и каркас правой панели настроек.
        Возвращает контейнеры каркаса: rv_inner — вертикальный layout, в который
        три следующих метода добавляют свои группы, остальные нужны футеру,
        который собирает панель уже после наполнения групп."""
    l = _api.QHBoxLayout(self)
    l.setContentsMargins(6, 6, 6, 6); l.setSpacing(8)
    lw = _api.QWidget(); lv = _api.QVBoxLayout(lw)
    lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(6)

    # Строка быстрой загрузки сделана 1-в-1 как на вкладке «Загрузчик»
    # (YtdlpTab): подпись «Ссылка для скачивания:» над строкой + поле и три
    # кнопки в один ряд, без обрамляющего блока «Быстрая загрузка».
    lv.addWidget(_api.QLabel("Ссылка для скачивания:"))
    qdl_h = _api.QHBoxLayout()
    self.url_edit = _api.QLineEdit()
    self.url_edit.setPlaceholderText("Вставьте ссылку.")
    self.url_edit.setClearButtonEnabled(True)
    self.url_edit.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
    self.url_edit.customContextMenuRequested.connect(self.on_url_ctx)

    btn_qdl_video = _api._icon_btn("Скачать", 'fa5s.download'); btn_qdl_video.clicked.connect(lambda: self.download_url(False))
    btn_qdl_audio = _api._icon_btn("Скачать (аудио)", 'fa5s.music'); btn_qdl_audio.clicked.connect(lambda: self.download_url(True))
    # Кнопка СТОП — как в строке загрузки на вкладке «Загрузчик» (YtdlpTab):
    # быстрые загрузки идут через тот же воркер-пул вкладки «Загрузчик», поэтому
    # СТОП останавливает их там же. Активна только при активных загрузках —
    # состояние ведёт YtdlpTab._update_stop_btn.
    self.btn_qdl_stop = _api._icon_btn("СТОП", 'fa5s.stop', color='#1e1e2e')
    self.btn_qdl_stop.setObjectName("b_stop")
    self.btn_qdl_stop.clicked.connect(self._quick_dl_stop)
    self.btn_qdl_stop.setEnabled(False)

    qdl_h.addWidget(self.url_edit); qdl_h.addWidget(btn_qdl_video); qdl_h.addWidget(btn_qdl_audio); qdl_h.addWidget(self.btn_qdl_stop)
    lv.addLayout(qdl_h)

    self.tree = _api.DraggableTreeWidget()
    self.tree.setAcceptDrops(True)
    self.tree.setPlaceholderText(
        "Добавляйте файлы сюда\n\n"
        "Перетащите видео, аудио или изображения в это окно\n"
        "или нажмите «Добавить файлы»")
    self.tree.setHeaderLabels(["Превью", "", "Размер", "Битрейт", "LUFS", "Длительность", "Статус", "Время", "Оценка XPSNR"])
    self.tree.setRootIsDecorated(False)
    self.tree.setItemDelegate(_api.StatusColorDelegate(self.tree))  # цветовая подсветка строк
    # 0-я колонка: миниатюра + имя файла под ней (одной строкой, с многоточием).
    self._preview_delegate = _api.PreviewNameDelegate(self.tree)
    self._preview_delegate.compare_clicked.connect(self._on_compare_clicked)
    self.tree.setItemDelegateForColumn(0, self._preview_delegate)
    self.tree.setIconSize(_api.QSize(160,90)); self.tree.setSelectionMode(_api.QTreeWidget.SelectionMode.ExtendedSelection)
    self.tree.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
    self.tree.customContextMenuRequested.connect(self.ctx)
    self.tree.setWordWrap(True)
    # Плавная прокрутка: по умолчанию список «прыгает» на целую строку (а строки
    # тут высокие — с превью 160×90), отчего колесо/скроллбар двигаются рывками.
    # Попиксельный режим прокручивает гладко, а шаг колеса задаём вручную (иначе
    # в попиксельном режиме одно деление колеса = 1 px, и крутить пришлось бы вечно).
    self.tree.setVerticalScrollMode(_api.QAbstractItemView.ScrollMode.ScrollPerPixel)
    self.tree.setHorizontalScrollMode(_api.QAbstractItemView.ScrollMode.ScrollPerPixel)
    self.tree.verticalScrollBar().setSingleStep(24)
    self.tree.header().setSectionResizeMode(0, _api.QHeaderView.ResizeMode.Interactive)
    self.tree.header().resizeSection(0, 180)
    for i in range(1, 9): self.tree.header().setSectionResizeMode(i, _api.QHeaderView.ResizeMode.ResizeToContents)
    # Колонка 1 — только метки «Было/Стало» (имя файла переехало под превью),
    # поэтому ширину отдаём по содержимому (ResizeToContents выше).
    # «Длительность» (5) и «Время» (7) — при ResizeToContents ширину диктует
    # длинное слово в заголовке, а не сам текст ячейки («22.75 с», «01:38»),
    # из-за чего колонки заметно шире содержимого. Фиксируем уже (но оставляем
    # Interactive — можно растянуть руками при необходимости).
    self.tree.header().setSectionResizeMode(5, _api.QHeaderView.ResizeMode.Interactive)
    self.tree.header().resizeSection(5, 90)
    self.tree.header().setSectionResizeMode(7, _api.QHeaderView.ResizeMode.Interactive)
    self.tree.header().resizeSection(7, 78)

    h = _api.QHBoxLayout()
    b1 = _api._icon_btn("Добавить файлы", 'fa5s.plus'); b1.clicked.connect(self.add)
    b2 = _api._icon_btn("Удалить", 'fa5s.times'); b2.clicked.connect(self.rem)
    b3 = _api._icon_btn("Очистить", 'fa5s.trash'); b3.clicked.connect(self.clear)
    for b in (b1, b2, b3): b.setMaximumWidth(120)
    b4 = _api._icon_btn("", 'fa5s.columns')
    b4.setFixedWidth(36)
    b4.setToolTip("Сравнить любые два файла с диска (картинки или видео)")
    b4.clicked.connect(self._compare_any_files)
    self.btn_export_dir = _api._icon_btn("", 'fa5s.folder-open')  # выбор папки экспорта
    self.btn_export_dir.setFixedWidth(36)
    self.btn_export_dir.setToolTip("Выбрать папку экспорта. По умолчанию — рядом с исходным файлом.")
    self.btn_export_dir.clicked.connect(self._choose_export_dir)
    self.btn_export_reset = _api._icon_btn("", 'fa5s.undo')
    self.btn_export_reset.setFixedWidth(36)
    self.btn_export_reset.setToolTip("Сбросить — экспортировать в папку исходника")
    self.btn_export_reset.clicked.connect(self._reset_export_dir)
    self.btn_export_reset.setEnabled(False)
    self.lbl_export_dir = _api.QLabel("По умолчанию экспорт в папку исходника")
    self.lbl_export_dir.setStyleSheet("color:#a6adc8; font-size:11px;")
    h.addWidget(b1); h.addWidget(b2); h.addWidget(b3); h.addWidget(b4); h.addWidget(self.btn_export_dir); h.addWidget(self.btn_export_reset); h.addWidget(self.lbl_export_dir)
    h.addStretch()

    # Левая часть может ужиматься (растяжимая, маленький минимум),
    # чтобы правая панель всегда полностью помещалась по горизонтали.
    lw.setMinimumWidth(140)
    lv.addWidget(self.tree); lv.addLayout(h)
    l.addWidget(lw, 1)

    RIGHT_W = 460  # фиксированная ширина правой панели — всегда видна целиком
    right_container = _api.QWidget(); right_layout = _api.QVBoxLayout(right_container)
    right_layout.setContentsMargins(0, 0, 0, 0); right_layout.setSpacing(6)
    right_container.setFixedWidth(RIGHT_W)
    rw = _api.QScrollArea(); rw.setWidgetResizable(True)
    rw.setFrameShape(_api.QFrame.Shape.NoFrame)
    # Горизонтальная скрыта (панель фикс. ширины), вертикальная — по необходимости
    rw.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    rw.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
    w = _api.QWidget(); rv_inner = _api.QVBoxLayout(w)
    rv_inner.setContentsMargins(6, 4, 6, 4); rv_inner.setSpacing(8)

    return l, right_container, right_layout, rv_inner, rw, w

def _build_audio_group(self, rv_inner):
    """Группа «Аудио эффекты» (нормализация, фейды, деградация) + строка скорости."""
    ga = _api.QGroupBox("Аудио эффекты"); fa = _api.QFormLayout()
    self.ck_norm = _api.QCheckBox("Loudnorm"); self.ck_norm.setChecked(True)
    self.s_tgt = _api.QDoubleSpinBox(); self.s_tgt.setValue(-20.0); self.s_tgt.setRange(-60.0, 20.0); self.s_tgt.setSingleStep(0.1)
    self.s_lra = _api.QDoubleSpinBox(); self.s_lra.setValue(11.0); self.s_lra.setRange(0.0, 50.0); self.s_lra.setSingleStep(0.1)
    self.s_tp = _api.QDoubleSpinBox(); self.s_tp.setValue(-1.5); self.s_tp.setRange(-60.0, 10.0); self.s_tp.setSingleStep(0.1)
    self.ck_fade = _api.QCheckBox("Затухание (Fade Out)"); self.ck_fade.setChecked(False)
    self.s_fade = _api.QDoubleSpinBox(); self.s_fade.setValue(1.0); self.s_fade.setRange(0.0, 60.0); self.s_fade.setSingleStep(0.1)
    self.s_fade.setMaximumWidth(110)
    self.ck_fade_in = _api.QCheckBox("Нарастание (Fade In)"); self.ck_fade_in.setChecked(False)
    self.s_fade_in = _api.QDoubleSpinBox(); self.s_fade_in.setValue(1.0); self.s_fade_in.setRange(0.0, 60.0); self.s_fade_in.setSingleStep(0.1)
    self.s_fade_in.setMaximumWidth(110)
    self.ck_deg = _api.QCheckBox("Ухудшить звук (Degrade)")
    self.s_hz = _api.QSpinBox(); self.s_hz.setValue(8000); self.s_hz.setRange(1000, 48000)
    self.ck_u8 = _api.QCheckBox("8-bit")
    self.s_lp = _api.QSpinBox(); self.s_lp.setRange(0, 24000); self.s_lp.setValue(3000)
    self.s_hp = _api.QSpinBox(); self.s_hp.setRange(0, 24000); self.s_hp.setValue(200)
    self.s_deg_gain = _api.QDoubleSpinBox(); self.s_deg_gain.setRange(-60, 0); self.s_deg_gain.setValue(0.0)
    for _sb in (self.s_tgt, self.s_lra, self.s_tp):
        _sb.setMaximumWidth(70)
    fa.addRow(_api.row_with_info(self.ck_norm, "Нормализация уровня громкости, рекомендуется все видео/аудио кодировать с этой опцией"))
    hn = _api.QHBoxLayout()
    hn.addWidget(_api.QLabel("LUFS:")); hn.addWidget(self.s_tgt)
    hn.addWidget(_api.QLabel("LRA:")); hn.addWidget(self.s_lra)
    hn.addWidget(_api.QLabel("TP:")); hn.addWidget(self.s_tp)
    hn.addStretch()
    fa.addRow(hn)
    fa.addRow(_api.row_with_info(self.ck_fade_in, "Плавное нарастание звука в начале ролика (секунды)"), self.s_fade_in)
    fa.addRow(_api.row_with_info(self.ck_fade, "Плавное затухание звука в конце ролика в секундах"), self.s_fade)

    # Битрейт аудио — ПЕРЕД секцией degrade
    hbr = _api.QHBoxLayout(); hbr.addWidget(_api.QLabel("Битрейт аудио:"))
    self.c_abitrate = _api.InvertedWheelComboBox(); self.c_abitrate.addItems(_api.AUDIO_BITRATES); self.c_abitrate.setCurrentText("128")
    hbr.addWidget(self.c_abitrate)
    hbr.addWidget(_api.info_badge("Кодируется в OPUS. 128 кбит - стандартное качество аудио в Youtube"))
    hbr.addStretch()
    fa.addRow(hbr)

    fa.addRow(_api.row_with_info(self.ck_deg, "Намеренное ухудшение звука (эффект «телефон/радио»). Открывает дополнительные параметры ниже."))

    # Degrade-виджеты: скрываются/показываются по галочке
    for _sb in (self.s_hz, self.s_lp, self.s_hp):
        _sb.setMaximumWidth(95)
    self._lbl_samplebit = _api.QLabel("Sample/Bit:")
    hd = _api.QHBoxLayout(); hd.addWidget(_api.QLabel("Hz:")); hd.addWidget(self.s_hz)
    hd.addWidget(_api.info_badge("Частота дискретизации (Гц). Ниже = грубее звук. 8000 Гц ≈ телефонное качество."))
    hd.addWidget(self.ck_u8)
    hd.addWidget(_api.info_badge("8-битный звук (u8) — сильное огрубление, шумный ретро-эффект."))
    hd.addStretch()
    fa.addRow(self._lbl_samplebit, hd)

    # Lowpass и Highpass — отдельными строками, чтобы умещались на узких экранах
    hlp = _api.QHBoxLayout(); hlp.addWidget(_api.QLabel("Lowpass:")); hlp.addWidget(self.s_lp)
    hlp.addWidget(_api.info_badge("Срезает частоты ВЫШЕ указанной (Гц) — убирает «верха», звук становится глуше."))
    hlp.addStretch()
    self._lbl_lowpass = _api.QLabel("")
    fa.addRow(self._lbl_lowpass, hlp)

    hhp = _api.QHBoxLayout(); hhp.addWidget(_api.QLabel("Highpass:")); hhp.addWidget(self.s_hp)
    hhp.addWidget(_api.info_badge("Срезает частоты НИЖЕ указанной (Гц) — убирает «низы»/гул."))
    hhp.addStretch()
    self._lbl_highpass = _api.QLabel("")
    fa.addRow(self._lbl_highpass, hhp)

    self._lbl_degvol = _api.QLabel("Degrade vol (dB):")
    hdv = _api.QHBoxLayout(); hdv.addWidget(self.s_deg_gain)
    self._badge_degvol = _api.info_badge("Громкость degrade-звука в дБ. 0 = без изменений, отрицательное значение = тише.")
    hdv.addWidget(self._badge_degvol); hdv.addStretch()
    fa.addRow(self._lbl_degvol, hdv)

    self.ck_no_audio = _api.QCheckBox("Удалить аудио"); self.ck_no_audio.setChecked(False)
    fa.addRow(_api.row_with_info(self.ck_no_audio, "Полностью вырезает звуковую дорожку из видео (-an). Остальные настройки звука выше становятся неактуальны."))

    self._deg_group = [self._lbl_samplebit, self.s_hz, self.ck_u8,
                       self._lbl_lowpass, self.s_lp,
                       self._lbl_highpass, self.s_hp,
                       self._lbl_degvol, self.s_deg_gain, self._badge_degvol]

    def _update_deg_vis(checked):
        for w in self._deg_group:
            w.setVisible(checked)
        # Скрываем layout-строки полностью через содержимое
        for layout_item in [hd, hlp, hhp]:
            for i in range(layout_item.count()):
                wi = layout_item.itemAt(i).widget()
                if wi: wi.setVisible(checked)
    self.ck_deg.toggled.connect(_update_deg_vis)
    _update_deg_vis(self.ck_deg.isChecked())

    # «Удалить аудио» гасит остальные настройки звука (они бы всё равно
    # игнорировались в process_media, но серым фоном честнее показать это в UI).
    self._audio_effect_widgets = [self.ck_norm, self.s_tgt, self.s_lra, self.s_tp,
                                  self.ck_fade_in, self.s_fade_in, self.ck_fade, self.s_fade,
                                  self.c_abitrate, self.ck_deg] + self._deg_group

    def _update_no_audio_vis(checked):
        for wdg in self._audio_effect_widgets:
            wdg.setEnabled(not checked)
        if checked:
            _update_deg_vis(False)   # скрыть под-настройки degrade, если были открыты
        else:
            _update_deg_vis(self.ck_deg.isChecked())
    self.ck_no_audio.toggled.connect(_update_no_audio_vis)
    _update_no_audio_vis(self.ck_no_audio.isChecked())

    ga.setLayout(fa); rv_inner.addWidget(ga)

    # --- Скорость: отдельный блок между аудио и видео (без названия группы) ---
    self.s_spd = _api.SpeedSpinBox(); self.s_spd.setValue(100); self.s_spd.setSuffix("%")
    self.s_spd.setMaximumWidth(110)
    speed_w = _api.QWidget(); speed_h = _api.QHBoxLayout(speed_w)
    speed_h.setContentsMargins(8, 2, 8, 2); speed_h.setSpacing(6)
    speed_h.addWidget(_api.QLabel("Скорость:"))
    speed_h.addWidget(self.s_spd)
    speed_h.addWidget(_api.info_badge("Изменение скорости видео и звука. 100% = без изменений"))
    speed_h.addStretch()
    rv_inner.addWidget(speed_w)
