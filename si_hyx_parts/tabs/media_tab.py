# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""MediaTab. Public namespace: tabs."""
import tabs as _api
from si_hyx_parts.tabs.media_tab_settings import MediaTabSettingsMixin


class MediaTab(MediaTabSettingsMixin, _api.QWidget):
    thumb_sig = _api.pyqtSignal(str, _api.QIcon)
    media_info_sig = _api.pyqtSignal(str, str, str, float)  # iid, размер, битрейт, длительность(с)
    media_lufs_sig = _api.pyqtSignal(str, object)           # iid, LUFS до (или None)

    def __init__(self, main_win):
        super().__init__()
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

    def ctx(self, pos):
        m = _api.QMenu()
        sel = self.tree.itemAt(pos)
        if sel:
            iid = sel.data(0, _api.Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid, {})
            out_path = entry.get('out_path', '')
            if out_path and _api.os.path.exists(out_path):
                m.addAction(_api.get_icon('fa5s.play'), "Открыть файл", lambda checked=False, p=out_path: self.open_output_file(p))
            m.addAction(_api.get_icon('fa5s.folder-open'), "Перейти к файлу", lambda checked=False, it=sel: self.open_file_location(it))
            m.addAction(_api.get_icon('fa5s.undo'), "Сбросить статус", lambda checked=False: self.reset_status())
            m.addSeparator()
            m.addAction(_api.get_icon('fa5s.times'), "Удалить", lambda checked=False: self.rem())
        m.addAction(_api.get_icon('fa5s.paste'), "Вставить файлы", lambda checked=False: self.paste_files())
        m.addAction(_api.get_icon('fa5s.trash'), "Очистить всё", lambda checked=False: self.clear())
        m.exec(self.tree.mapToGlobal(pos))

    def open_file_location(self, item):
        try:
            path = item.toolTip(0) or item.data(0, _api.Qt.ItemDataRole.ToolTipRole)
            if not path: return
            from utils import reveal_in_explorer
            reveal_in_explorer(path)
        except Exception as e:
            self.main.log(f"open_file_location error: {e}")

    def paste_files(self):
        try:
            mime = _api.QApplication.clipboard().mimeData()
            if mime.hasUrls():
                self.add_paths([u.toLocalFile() for u in mime.urls() if u.toLocalFile()])
        except Exception as e:
            self.main.log(f"paste_files error: {e}")

    _VK_V = 0x56

    def keyPressEvent(self, ev):
        # Резерв Ctrl+V для кириллической раскладки: физическая V шлёт Qt-код
        # кириллической буквы (М), и self.shortcut_paste (QShortcut("Ctrl+V"))
        # на ней молча не срабатывает — та же природа бага, что и Ctrl+Z/Y в
        # Монтаже (edit_tab.py) и WASD в редакторе фото (см. _pan_dir_from_event).
        # Доходит сюда, только если QShortcut его не поймал (для латиницы уже
        # сработал он — двойной вставки нет).
        if ev.modifiers() & _api.Qt.KeyboardModifier.ControlModifier:
            try:
                vk = ev.nativeVirtualKey()
            except Exception:
                vk = 0
            if vk == self._VK_V or ev.key() == _api.Qt.Key.Key_V:
                self.paste_files()
                ev.accept()
                return
        super().keyPressEvent(ev)

    def add(self):
        p, _ = _api.QFileDialog.getOpenFileNames(self, "Файлы")
        if p: self.add_paths(p)

    def add_paths(self, paths):
        for p in paths:
            try:
                if not _api.os.path.exists(p): continue

                # Не добавляем файлы, которые сами являются результатом обработки
                stem = _api.Path(p).stem
                if stem.endswith("_Сжатый") or stem.endswith("_Compressed"):
                    continue

                ext = _api.Path(p).suffix.lower()
                if ext in _api.ALLOWED_MEDIA: ft = "MEDIA"
                elif ext in _api.ALLOWED_IMG: ft = "IMG"
                else: continue

                iid = _api.uuid.uuid4().hex
                # Только быстрый getsize — ffprobe уйдёт в фоновый поток
                try: size = _api.os.path.getsize(p)
                except Exception: size = 0

                item_data = {'iid': iid, 'path': p, 'type': ft, 'dur': 0, 'is_done': False}
                self.items.append(item_data)
                self._item_data_map[iid] = item_data

                it = _api.QTreeWidgetItem(self.tree)
                name = _api.os.path.basename(p)
                # Колонка 0 (Превью): миниатюра + имя файла под ней (рисует
                # PreviewNameDelegate, длинное имя обрезается многоточием).
                # Полное имя — в тултипе.
                it.setText(0, name)
                # Тултип превью — только путь; полное имя показывается при
                # наведении на строку имени под превью (см. DraggableTreeWidget).
                it.setToolTip(0, p)
                # Колонка 1: метки Было/Стало. 2 строки [было, стало] —
                # центрируются по высоте строки как имя файла и статус (пустая
                # 1-я строка раньше сдвигала пару вниз от центра).
                it.setText(1, "Было\nСтало")
                it.setText(2, f"{_api.human_size(size)}\n—")     # Размер: было(исх) / стало
                it.setText(3, "—\n—")                       # Битрейт: исх / итог
                it.setText(4, "—\n—")                       # LUFS: до / после
                it.setText(5, "—\n—")                       # Длительность: исх / итог
                it.setText(6, "Ожидание")                   # Статус (одна строка)
                it.setText(7, "—")                          # Время перекодирования (мм:сс)
                it.setToolTip(7, "Время, потраченное на перекодирование")
                it.setText(8, "—")                          # Оценка XPSNR (заполняется после видео-кодирования)
                it.setToolTip(8, "Оценка качества результата (XPSNR, дБ) — выше значит ближе к оригиналу.\n"
                                 "Только для перекодированного видео (AV1); при копировании/аудио — «—».")
                it.setData(0, _api.Qt.ItemDataRole.UserRole, iid)
                # Аудио (без видеоряда) → компактная строка без места под превью.
                if ext in _api.ALLOWED_AUDIO:
                    it.setData(0, _api.ITEM_AUDIO_ROLE, True)
                self._item_map[iid] = it
                self.tree.scrollToItem(it)
                self.pool.start(_api.LocalThumbnailRunnable(p, iid, self.thumb_sig))

                if ft == "MEDIA":
                    def _bg(path_local, iid_local):
                        # ffprobe + loudness — всё в фоне, UI не блокируем.
                        # Результат отдаём в GUI-поток через сигналы: QTimer.singleShot
                        # из обычного threading.Thread (без Qt event loop) НЕ
                        # срабатывает — из-за этого битрейт и длительность не
                        # появлялись при добавлении файла.
                        try:
                            dur_r, br_r, size_r, a_br_r, a_codec_r = _api.get_media_info(path_local)
                            v_r = _api.get_video_codec_label(path_local)
                            size_label_r = f"{v_r} {_api.human_size(size_r)}" if v_r else _api.human_size(size_r)
                            self.media_info_sig.emit(
                                iid_local, size_label_r,
                                _api.fmt_bitrate_with_codec(a_codec_r, a_br_r or br_r),
                                float(dur_r or 0.0))
                        except Exception: pass
                        try:
                            val = _api.measure_loudness(path_local)
                        except Exception: val = None
                        self.media_lufs_sig.emit(iid_local, val)
                    _api.threading.Thread(target=_bg, args=(p, iid), daemon=True).start()

            except Exception as e:
                self.main.log(f"add_paths error: {e}")

    def set_thumb(self, iid, icon):
        try:
            item = self._find_item(iid)
            if item:
                item.setIcon(0, icon)
        except Exception: pass

    def _apply_media_info(self, iid, size_str, bitrate, dur):
        """GUI-поток: исходные размер/битрейт/длительность из ffprobe (верхняя
        строка «Было»). Вызывается через media_info_sig из фонового потока."""
        try:
            d = self._item_data_map.get(iid)
            if d: d['dur'] = dur
            item = self._find_item(iid)
            if item:
                if size_str:
                    self._set_pair(item, 2, top=size_str)
                self._set_pair(item, 3, top=(bitrate if bitrate and bitrate != "-" else "—"))
                self._set_pair(item, 5, top=self._fmt_dur(dur))
        except Exception: pass

    def _apply_media_lufs(self, iid, val):
        """GUI-поток: исходный LUFS (через media_lufs_sig из фонового потока)."""
        self.update_lufs_columns(iid, val, None)

    @staticmethod
    def _set_pair(item, col, top=None, bottom=None):
        """Ячейка из 2 строк: [было, стало]. Меняет только было/стало
        (top/bottom), сохраняя другую строку. Пара центрируется по высоте
        строки (как имя файла и статус)."""
        cur = (item.text(col) or "").split("\n")
        # Легаси-формат из 3 строк ([пусто, было, стало]) — отбрасываем пустую.
        if len(cur) >= 3:
            cur = cur[1:]
        t = cur[0] if len(cur) > 0 and cur[0] else "—"
        b = cur[1] if len(cur) > 1 and cur[1] else "—"
        if top is not None: t = top
        if bottom is not None: b = bottom
        item.setText(col, f"{t}\n{b}")

    @staticmethod
    def _fmt_dur(sec):
        """Длительность для колонки: «5.72 с» (<1 мин) или «M:SS.ss»."""
        try: sec = float(sec)
        except Exception: return "—"
        if sec <= 0: return "—"
        if sec < 60: return f"{sec:.2f} с"
        m = int(sec // 60); s = sec - m * 60
        return f"{m}:{s:05.2f}"

    def update_item_info(self, iid, size_new, bitrate_result):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 2, bottom=size_new)          # Размер: стало
                self._set_pair(item, 3, bottom=bitrate_result)    # Битрейт: итог
                item.setData(0, _api.ITEM_STATUS_ROLE, 'done')
                # Для обработанной картинки/видео включаем значок «сравнить» на превью
                # (аудио без видеоряда сравнивать нечем — там значок не нужен).
                entry = self._item_data_map.get(iid)
                is_video = entry and entry.get('type') == 'MEDIA' and _api.Path(entry.get('path', '')).suffix.lower() not in _api.ALLOWED_AUDIO
                if entry and (entry.get('type') == 'IMG' or is_video):
                    item.setData(0, _api.ITEM_COMPARE_ROLE, True)
                    item.setToolTip(0, (item.toolTip(0) or "")
                                    + "\n\nЗначок в углу превью — сравнить исходник и результат.")
                self.tree.viewport().update()
        except Exception: pass

    def _on_compare_clicked(self, index):
        """Клик по значку «сравнить» на превью обработанного файла: открывает
        полноэкранное сравнение исходника и результата (картинка — по форме,
        видео — плеер слева/справа с синхронной перемоткой). Если оригинал/
        результат недоступны — показывает то, что есть."""
        try:
            iid = index.data(_api.Qt.ItemDataRole.UserRole)
            entry = self._item_data_map.get(iid)
            if not entry:
                return
            src = entry.get('path', '')
            out = entry.get('out_path', '')
            src_ok = bool(src) and _api.os.path.exists(src)
            out_ok = bool(out) and _api.os.path.exists(out)
            is_video = entry.get('type') == 'MEDIA' and _api.Path(src or out).suffix.lower() not in _api.ALLOWED_AUDIO
            if src_ok and out_ok and _api.os.path.abspath(src) != _api.os.path.abspath(out):
                if is_video:
                    _api.show_video_compare(src, out, self)
                else:
                    _api.show_image_compare(src, out, self)
            elif out_ok:
                if is_video:
                    _api.show_video_compare(out, out, self)
                else:
                    _api.show_image_fullscreen(out, self)
            elif src_ok:
                if is_video:
                    _api.show_video_compare(src, src, self)
                else:
                    _api.show_image_fullscreen(src, self)
        except Exception as e:
            self.main.log(f"Сравнение: {e}")

    def _compare_any_files(self):
        """Кнопка «Сравнить» в тулбаре списка — сравнение ЛЮБЫХ двух файлов с
        диска, а не только пары исходник/результат из очереди обработки. Тип
        (картинка или видео) определяется по расширению первого файла. Можно
        выбрать всего один файл — окно сравнения откроется сразу с ним (слева),
        а второй добавляется прямо в окне значком папки (тот же интерфейс,
        что и при обычном сравнении)."""
        try:
            video_exts = _api.ALLOWED_MEDIA - _api.ALLOWED_AUDIO
            exts = " ".join(f"*{e}" for e in sorted(_api.ALLOWED_IMG | video_exts))
            paths, _ = _api.QFileDialog.getOpenFileNames(
                self, "Выберите файл(ы) для сравнения (можно один — второй добавите в окне)", "",
                f"Изображения и видео ({exts});;Все файлы (*)")
            if not paths:
                return
            a = paths[0]
            b = paths[1] if len(paths) > 1 else None
            ext_a = _api.Path(a).suffix.lower()
            if ext_a in _api.ALLOWED_IMG:
                _api.show_image_compare(a, b, self, use_filenames=True)
            elif ext_a in video_exts:
                _api.show_video_compare(a, b, self, use_filenames=True)
            else:
                self.main.log(f"Сравнение: неподдерживаемый тип файла «{ext_a}»")
        except Exception as e:
            self.main.log(f"Сравнение: {e}")

    def update_item_dur(self, iid, dur_str):
        """Длительность итогового файла (после перекодирования) — нижняя строка."""
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 5, bottom=self._fmt_dur(dur_str))
        except Exception: pass

    def update_item_xpsnr(self, iid, score):
        """Оценка качества результата (XPSNR, дБ) — заполняется после видео-
        кодирования (см. xpsnr_sig в workers.py). score=None — не измерялась
        (не видео, копия без перекодирования, или замер не удался)."""
        try:
            item = self._find_item(iid)
            if item:
                item.setText(8, "—" if score is None else f"{score:.1f} дБ")
        except Exception: pass

    def update_lufs_columns(self, iid, before, after):
        try:
            item = self._find_item(iid)
            if item:
                self._set_pair(item, 4, top=("—" if before is None else f"{before:.2f}"))
                self._set_pair(item, 4, bottom=("—" if after is None else f"{after:.2f}"))
        except Exception: pass

    def rem(self):
        try:
            for i in self.tree.selectedItems():
                iid = i.data(0, _api.Qt.ItemDataRole.UserRole)
                # Мутируем СПИСОК НА МЕСТЕ (не self.items = [...]) — ProcessWorker
                # держит ссылку на этот же объект-список как «живую» очередь
                # (см. queue_ref в _run_items); переприсваивание отвязывало бы
                # воркер от изменений, и удалённый файл всё равно обрабатывался
                # бы до конца, а не только до нажатия «СТОП».
                self.items[:] = [x for x in self.items if x['iid'] != iid]
                self._item_map.pop(iid, None)
                self._item_data_map.pop(iid, None)
                self._removed_ids.add(iid)
                self.tree.invisibleRootItem().removeChild(i)
        except Exception: pass

    def clear(self):
        try:
            self.items.clear()
            self._item_map.clear()
            self._item_data_map.clear()
            self.tree.clear()
        except Exception: pass

    def run(self):
        """Кнопка «НАЧАТЬ» — обрабатывает всю очередь."""
        self._run_items(self.items)

    def _collect_settings(self):
        """Собирает АКТУАЛЬНОЕ состояние всех настроек «Обработки» с виджетов —
        единственное место сборки, чтобы кнопка «НАЧАТЬ» и фоновая пере-синхронизация
        настроек уже идущего воркера (_settings_sync_tick) всегда читали одно и то же
        и любая новая настройка, добавленная сюда в будущем, подхватывалась обоими
        путями сама собой."""
        try: ab = self.c_abitrate.currentText() or "128"
        except Exception: ab = "128"
        try: spd = self.s_spd.value()
        except Exception: spd = 100
        return {
            'audio': {
                'remove': bool(self.ck_no_audio.isChecked()),
                'norm': bool(self.ck_norm.isChecked()),
                'tgt': float(self.s_tgt.value()), 'lra': float(self.s_lra.value()), 'tp': float(self.s_tp.value()),
                'fade': bool(self.ck_fade.isChecked()), 'fade_d': float(self.s_fade.value()),
                'fade_in': bool(self.ck_fade_in.isChecked()), 'fade_in_d': float(self.s_fade_in.value()),
                'deg': bool(self.ck_deg.isChecked()), 'hz': int(self.s_hz.value()), 'u8': bool(self.ck_u8.isChecked()),
                'lp': int(self.s_lp.value()), 'hp': int(self.s_hp.value()), 'deg_gain_db': float(self.s_deg_gain.value()),
                'bitrate': ab
            },
            'video': {
                'enabled': bool(self.chk_enable_video.isChecked()), 'speed': int(spd), 'crf': int(self.s_crf.value()),
                'pre': int(self.s_pre.value()), 'res': _api.strip_default_tag(self.c_res.currentText()), 'fps': self.c_fps.currentText().strip().replace(',', '.'),
                'preset_mode': 'dark' if self.btn_mode_dark.isChecked() else 'std',
                'tune': self._video_tune_value(),
                'metric': self._video_metric_value(), 'target_metric': float(self.s_target_metric.value()),
                # Видна ли колонка «Оценка XPSNR»: пока она скрыта (по умолчанию),
                # ProcessWorker не тратит пробное кодирование на её заполнение —
                # см. _wants_metric_score в workers.py.
                'show_metric_col': bool(getattr(self, '_show_advanced_encode', False)),
                'vfade_in': bool(self.ck_vfade_in.isChecked()), 'vfade_in_d': float(self.s_vfade_in.value()),
                'vfade_out': bool(self.ck_vfade_out.isChecked()), 'vfade_out_d': float(self.s_vfade_out.value()),
                'crop_black': bool(self.ck_crop_black.isChecked())
            },
            'avif': {
                'limit': int(self.s_lim.value()) if self.ck_lim.isChecked() else 0,
                'adim': int(self.s_dim.value()) if self.ck_dim.isChecked() else 0,
                'awidth': int(self.s_width.value()) if self.ck_width.isChecked() else 0,
                'aheight': int(self.s_height.value()) if self.ck_height.isChecked() else 0,
                'aspd': int(self.sl_aspd.value()),
                'cq': int(self.s_cq.value()),
                'overwrite_src': bool(self.ck_overwrite_src.isChecked()),
                'fit_passes': int(self.s_passes.value()),
                'img_fmt': _api.strip_default_tag(self.c_img_fmt.currentText()),
                'chroma': _api.strip_default_tag(self.c_chroma.currentText()).replace(':', '')
            },
            'export_dir': self.export_dir or '',
            'priority': {'Низкий': 'low', 'Обычный': 'normal', 'Высокий': 'high'}.get(
                self.c_priority.currentText(), 'normal')
        }

    def _settings_sync_tick(self):
        """Пока воркер работает — подсовывает ему свежий словарь настроек (см.
        _collect_settings). ProcessWorker читает self.settings заново для КАЖДОГО
        файла (self.settings.get(...) внутри process_media), поэтому уже начатый
        файл фоновым перезапросом не затрагивается — досрочно подхватывают
        изменение только ещё не стартовавшие (в т.ч. добавленные во время работы)."""
        w = getattr(self, 'worker', None)
        if w is None or not w.isRunning():
            self._settings_sync_timer.stop()
            return
        try:
            w.settings = self._collect_settings()
        except Exception:
            pass

    def _run_items(self, target):
        if not target: return
        # Не запускаем второй воркер поверх активного (двойной клик во время работы)
        if getattr(self, 'worker', None) is not None:
            try:
                if self.worker.isRunning():
                    self.main.log("Дождитесь завершения текущей обработки.")
                    return
            except Exception: pass
        s = self._collect_settings()
        if hasattr(self.main, "clear_global_result"):
            self.main.clear_global_result()
        self.worker = _api.ProcessWorker(target, s, removed_ids=self._removed_ids)
        self.worker.status.connect(self.on_stat); self.worker.progress.connect(self.on_prog)
        self.worker.log.connect(self.main.log); self.worker.finished_all.connect(self.done)
        self.worker.global_progress.connect(self.main.update_global_progress)
        self.worker.update_item_sig.connect(self.update_item_info); self.worker.update_lufs_sig.connect(self.update_lufs_columns)
        self.worker.update_dur_sig.connect(self.update_item_dur)
        self.worker.xpsnr_sig.connect(self.update_item_xpsnr)
        self.worker.active_threads.connect(self._on_active_threads)

        try:
            for itdata in target:
                if itdata.get('is_done'): continue
                iid = itdata.get('iid')
                item = self._find_item(iid)
                if item:
                    item.setData(0, _api.ITEM_STATUS_ROLE, 'proc')
                    item.setText(6, "Ожидание")   # сброс прошлого «Готово»/«Ошибка»
                    item.setText(7, "—")
                # Сбрасываем прошлый замер времени — новый запуск считает с нуля.
                self._proc_started.pop(iid, None)
                self._proc_running.discard(iid)
            self.tree.viewport().update()
        except Exception: pass

        self.b_run.setEnabled(False); self.b_stop.setEnabled(True)
        self.main.update_global_progress(0, "Подготовка…", started_at=_api.time.monotonic(),
                                         running=True)
        self.worker.start()
        self._settings_sync_timer.start()

    def stop(self):
        if self.worker:
            try: self.worker.stop()
            except Exception: pass

    _RE_IMG_PASS = _api.re.compile(r"картинки (\d+)/(\d+)")

    def on_stat(self, iid, txt, code):
        try:
            i = self._find_item(iid)
            if i:
                i.setData(0, _api.ITEM_STATUS_ROLE, code)
                # Не показываем промежуточные подписи «Обработка.»/«Конвертация
                # картинки» — в колонке «Статус» сразу идут проценты (on_prog)
                # и финальные «Готово»/«Ошибка»/«Остановлено».
                if code != 'proc':
                    i.setText(6, txt)
                self.tree.viewport().update()
            # Подбор AVIF/WebP под лимит размера идёт несколькими проходами —
            # текст вида «Конвертация картинки N/total» несёт номер прохода,
            # который показываем рядом с временем (колонка «Время»).
            if code == 'proc':
                m = self._RE_IMG_PASS.search(txt or "")
                if m:
                    self._item_pass[iid] = f"{m.group(1)}/{m.group(2)}"
                    self._update_elapsed_text(iid)
            # Учёт времени перекодирования (колонка «Время»):
            #   proc      → засекаем старт (единожды) и запускаем тик-таймер;
            #   done/err  → фиксируем итог и больше не тикаем этот файл.
            if code == 'proc':
                self._start_elapsed(iid)
            elif code in ('done', 'err'):
                self._item_pass.pop(iid, None)
                self._freeze_elapsed(iid)
            if code == 'done':
                entry = self._item_data_map.get(iid)
                out_path = entry.get('out_path', '') if entry else ''
                if out_path and hasattr(self.main, "set_global_result"):
                    self.main.set_global_result(out_path)
        except Exception: pass

    def on_prog(self, iid, val):
        try:
            i = self._find_item(iid)
            if i:
                i.setText(6, "Готово" if val >= 100 else f"{val}%")
            if val >= 100:
                self._freeze_elapsed(iid)
        except Exception: pass

    # ── Время перекодирования (колонка 7) ──────────────────────────────────────
    @staticmethod
    def _fmt_elapsed(sec) -> str:
        """Секунды → «мм:сс» (минуты и секунды через двоеточие)."""
        sec = max(0, int(sec))
        m, s = divmod(sec, 60)
        return f"{m:02d}:{s:02d}"

    def _elapsed_text_for(self, iid, elapsed_sec) -> str:
        """мм:сс + «(x/y)» прохода подбора картинки, если он сейчас идёт."""
        txt = self._fmt_elapsed(elapsed_sec)
        p = self._item_pass.get(iid)
        return f"{txt} ({p})" if p else txt

    def _update_elapsed_text(self, iid):
        """Перерисовывает колонку «Время» текущего файла (напр. когда сменился
        номер прохода, а не только тик таймера)."""
        start = self._proc_started.get(iid)
        if start is None:
            return
        i = self._find_item(iid)
        if i:
            i.setText(7, self._elapsed_text_for(iid, _api.time.monotonic() - start))

    def _start_elapsed(self, iid):
        """Засекает старт перекодирования файла (если ещё не засечён) и
        включает таймер, который тикает время вверх до завершения."""
        if iid not in self._proc_started:
            self._proc_started[iid] = _api.time.monotonic()
        self._proc_running.add(iid)
        i = self._find_item(iid)
        if i:
            i.setText(7, self._elapsed_text_for(iid, _api.time.monotonic() - self._proc_started[iid]))
        if not self._elapsed_timer.isActive():
            self._elapsed_timer.start()

    def _tick_elapsed(self):
        """Раз в 0.5 с обновляет время у всех кодирующихся сейчас файлов."""
        now = _api.time.monotonic()
        for iid in list(self._proc_running):
            i = self._find_item(iid)
            if i is None:
                self._proc_running.discard(iid)
                continue
            start = self._proc_started.get(iid)
            if start is not None:
                i.setText(7, self._elapsed_text_for(iid, now - start))
        if not self._proc_running:
            self._elapsed_timer.stop()

    def _freeze_elapsed(self, iid):
        """Фиксирует итоговое время файла и снимает его с тиканья (идемпотентно —
        повторные сигналы done/100% не пересчитывают и не сдвигают итог)."""
        self._proc_running.discard(iid)
        self._item_pass.pop(iid, None)
        start = self._proc_started.pop(iid, None)
        if start is not None:
            i = self._find_item(iid)
            if i:
                i.setText(7, self._fmt_elapsed(_api.time.monotonic() - start))
        if not self._proc_running:
            self._elapsed_timer.stop()

    def _on_active_threads(self, n, m):
        try:
            # В простое показываем 0 из всех потоков ЦП машины (а не 0/0).
            total = m if m > 0 else self._cpu_threads
            self.lbl_threads.setText(f"Параллельных задач: {n}/{total}")
        except Exception: pass

    def done(self):
        self.b_run.setEnabled(True); self.b_stop.setEnabled(False)
        self._removed_ids.clear()
        # Страховка: фиксируем итоговое время по всем ещё «тикающим» файлам и
        # останавливаем таймер (на случай, если кто-то не прислал done/err).
        for iid in list(self._proc_running):
            self._freeze_elapsed(iid)
        self._elapsed_timer.stop()
        try: self.lbl_threads.setText(f"Параллельных задач: 0/{self._cpu_threads}")
        except Exception: pass
        self.main.log("Готово")
        try: _api.play_done_sound()
        except Exception: pass


MediaTab.__module__ = _api.__name__
_api.MediaTab = MediaTab
