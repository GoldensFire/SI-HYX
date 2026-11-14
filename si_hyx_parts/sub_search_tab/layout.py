# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""«Поиск по сабам»: построение интерфейса и стили."""
import sub_search_tab as _api


class SubSearchLayoutMixin:
    """«Поиск по сабам»: построение интерфейса и стили."""

    def _build_ui(self):
        root = _api.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Строка поиска ────────────────────────────────────────────────────
        top = _api.QHBoxLayout(); top.setSpacing(8)
        self.ed_phrase = _api.QLineEdit("six seven")
        self.ed_phrase.setPlaceholderText("Фраза на английском, например: six seven")
        self.ed_phrase.setClearButtonEnabled(True)
        self.ed_phrase.addAction(_api.get_icon("fa5s.closed-captioning"),
                                 _api.QLineEdit.ActionPosition.LeadingPosition)
        self.ed_phrase.returnPressed.connect(self.start_search)
        self.btn_search = _api.QPushButton("Искать")
        self.btn_search.setObjectName("b_primary")
        self.btn_search.setIcon(_api.get_icon("fa5s.search", color="#11111b"))
        self.btn_search.setIconSize(_api.QSize(16, 16))
        self.btn_search.clicked.connect(self.start_search)
        self.btn_stop = _api.QPushButton("Стоп")
        self.btn_stop.setIcon(_api.get_icon("fa5s.stop"))
        self.btn_stop.setToolTip("Остановить поиск — найденное останется, скачанное — в кэше.")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_search)
        self.btn_clear = _api.QPushButton("Очистить")
        self.btn_clear.setIcon(_api.get_icon("fa5s.trash"))
        self.btn_clear.setToolTip("Очистить список найденного")
        self.btn_clear.clicked.connect(self.clear_results)
        top.addWidget(self.ed_phrase, 1)
        top.addWidget(self.btn_search)
        top.addWidget(self.btn_stop)
        top.addWidget(self.btn_clear)
        root.addLayout(top)

        body = _api.QHBoxLayout(); body.setSpacing(12)
        root.addLayout(body, 1)

        # ── Слева: найденное, состояние, журнал ─────────────────────────────
        left = _api.QVBoxLayout(); left.setSpacing(6)
        self.list = _api.QListWidget()
        self.list.setObjectName("subsearch_results")
        self.list.setVerticalScrollMode(_api.QListWidget.ScrollMode.ScrollPerPixel)
        # Карточки во всю ширину, высота — по ширине (_fit_row_item).
        self.list.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.viewport().installEventFilter(self)
        self.list.setSelectionMode(_api.QListWidget.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._row_menu)
        self.list.itemDoubleClicked.connect(self._open_item)
        left.addWidget(self.list, 1)

        self.lbl_empty = _api.QLabel(
            "Здесь появятся тайтлы, в субтитрах которых звучит фраза.\n"
            "Порядок обхода и источники — справа.")
        self.lbl_empty.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty.setStyleSheet(f"color:{_api.C['text3']}; font-size:12px;")
        left.addWidget(self.lbl_empty)

        status_row = _api.QHBoxLayout(); status_row.setSpacing(8)
        self.lbl_status = _api.QLabel("Готово к поиску.")
        self.lbl_status.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        self.lbl_status.setSizePolicy(_api.QSizePolicy.Policy.Ignored,
                                      _api.QSizePolicy.Policy.Preferred)
        self.progress = _api.QProgressBar()
        self.progress.setFixedWidth(180)
        self.progress.setFixedHeight(14)
        self.progress.setTextVisible(False)
        self.progress.setVisible(False)
        self.btn_log = _api.QToolButton()
        self.btn_log.setText("Журнал")
        self.btn_log.setCheckable(True)
        self.btn_log.setToolTip("Показать журнал поиска")
        self.btn_log.toggled.connect(lambda on: self.log_box.setVisible(on))
        status_row.addWidget(self.lbl_status, 1)
        status_row.addWidget(self.progress)
        status_row.addWidget(self.btn_log)
        left.addLayout(status_row)
        self.log_box = _api.QPlainTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMaximumBlockCount(500)
        self.log_box.setFixedHeight(120)
        self.log_box.setVisible(False)
        left.addWidget(self.log_box)
        body.addLayout(left, 1)

        self._build_settings_panel(body)
        self._apply_styles()

    def _build_settings_panel(self, body):
        scroll = _api.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        panel = _api.QWidget()
        pv = _api.QVBoxLayout(panel)
        pv.setContentsMargins(2, 2, 8, 2)
        pv.setSpacing(12)

        def lab(text):
            lbl = _api.QLabel(text)
            lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
            lbl.setWordWrap(True)
            return lbl

        def hint(text):
            lbl = _api.QLabel(text)
            lbl.setWordWrap(True)
            lbl.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
            return lbl

        # ── Что искать ────────────────────────────────────────────────────────
        grp = _api.QGroupBox("Тайтлы")
        g = _api.QGridLayout(grp)
        g.setHorizontalSpacing(8); g.setVerticalSpacing(6)
        g.addWidget(lab("Найти тайтлов"), 0, 0)
        self.sp_count = _api.QSpinBox()
        self.sp_count.setRange(0, 1000)
        self.sp_count.setValue(5)
        self.sp_count.setSpecialValueText("все")
        self.sp_count.setToolTip("Поиск останавливается, когда найдено столько тайтлов. "
                                 "0 — пройти весь список.")
        g.addWidget(self.sp_count, 0, 1, 1, 3)
        g.addWidget(lab("Порядок"), 1, 0)
        self.cb_order = _api.QComboBox()
        for key, label in _api.engine.ORDER_LABELS.items():
            self.cb_order.addItem(label, key)
        self.cb_order.setToolTip("По уровню из базы ShikimoriHYX (1 — самый узнаваемый); "
                                 "внутри уровня — по просмотрам.")
        g.addWidget(self.cb_order, 1, 1, 1, 3)
        g.addWidget(lab("Уровень"), 2, 0)
        self.sp_lvl_min = _api.QSpinBox(); self.sp_lvl_min.setRange(1, 15)
        self.sp_lvl_max = _api.QSpinBox(); self.sp_lvl_max.setRange(1, 15)
        self.sp_lvl_max.setValue(15)
        self.sp_lvl_min.setPrefix("от ")
        self.sp_lvl_max.setPrefix("до ")
        g.addWidget(self.sp_lvl_min, 2, 1)
        g.addWidget(self.sp_lvl_max, 2, 2, 1, 2)
        self.chk_kinds = {}
        kinds_box = _api.QGridLayout(); kinds_box.setSpacing(4)
        for n, (key, label) in enumerate(_api.engine.KIND_GROUP_LABELS.items()):
            cb = _api.QCheckBox(label)
            cb.setChecked(True)
            self.chk_kinds[key] = cb
            kinds_box.addWidget(cb, n // 2, n % 2)
        g.addLayout(kinds_box, 3, 0, 1, 4)
        g.setColumnStretch(1, 1); g.setColumnStretch(2, 1)
        pv.addWidget(grp)

        # ── Источники ────────────────────────────────────────────────────────
        grp_src = _api.QGroupBox("Источники субтитров")
        sl = _api.QVBoxLayout(grp_src); sl.setSpacing(4)
        self.chk_src = {}
        self.lbl_src = {}
        for key, label, tip in (
                ("subdl", "SubDL",
                 "Английские субтитры по точному TMDB/IMDb id тайтла, сезонными архивами. "
                 "Ключ SubDL — тот же, что для «Диалогов из аниме»."),
                ("subsource", "SubSource",
                 "Английские субтитры по IMDb id тайтла (без него — по названию и году). "
                 "Нужен бесплатный ключ SubSource: 60 запросов в минуту, 7200 в сутки."),
                ("tsdb", "TSDB",
                 "The Subtitle Database: английские сабы по TMDB id тайтла, деревом сезона. "
                 "Ключ не нужен (1000 скачиваний в час); с ключом — 100 000 в сутки."),
                ("opensubtitles", "OpenSubtitles",
                 "Нужны ключ API, логин и пароль. Скачивания ограничены суточной квотой "
                 "аккаунта (у бесплатного — единицы), поэтому по умолчанию выключен.")):
            cb = _api.QCheckBox(label)
            cb.setToolTip(tip)
            cb.setChecked(key != "opensubtitles")
            st = _api.QLabel()
            st.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
            line = _api.QHBoxLayout(); line.setSpacing(6)
            line.addWidget(cb); line.addStretch(1); line.addWidget(st)
            sl.addLayout(line)
            self.chk_src[key], self.lbl_src[key] = cb, st
        self.btn_keys = _api.QPushButton("Ключи API…")
        self.btn_keys.setIcon(_api.get_icon("fa5s.key"))
        self.btn_keys.setToolTip("Ключи общие для всей программы: Настройки → «Ключи API».")
        self.btn_keys.clicked.connect(self._open_keys)
        sl.addWidget(self.btn_keys)
        pv.addWidget(grp_src)

        # ── Точность и скорость ──────────────────────────────────────────────
        grp_acc = _api.QGroupBox("Поиск")
        al = _api.QGridLayout(grp_acc)
        al.setHorizontalSpacing(8); al.setVerticalSpacing(6)
        self.chk_first = _api.QCheckBox("Хватит одного совпадения на тайтл")
        self.chk_first.setChecked(True)
        self.chk_first.setToolTip("Вкл — как только фраза нашлась, остальные серии тайтла "
                                  "не качаются (быстрее). Выкл — собрать все совпадения "
                                  "(до 30 на тайтл).")
        al.addWidget(self.chk_first, 0, 0, 1, 2)
        self.chk_one_fr = _api.QCheckBox("От франшизы — один тайтл")
        self.chk_one_fr.setChecked(True)
        self.chk_one_fr.setToolTip("Нашлось в «Атаке титанов» — остальные её сезоны и "
                                   "фильмы дальше не проверяются.")
        al.addWidget(self.chk_one_fr, 1, 0, 1, 2)
        self.chk_cache_only = _api.QCheckBox("Только кэш (без сети)")
        self.chk_cache_only.setToolTip("Искать только по уже скачанным субтитрам — "
                                       "мгновенно и без запросов к источникам.")
        al.addWidget(self.chk_cache_only, 2, 0, 1, 2)
        al.addWidget(lab("Пауза между репликами, с"), 3, 0)
        self.sp_gap = _api.QDoubleSpinBox()
        self.sp_gap.setRange(0.0, 15.0); self.sp_gap.setSingleStep(0.5)
        self.sp_gap.setValue(3.0)
        self.sp_gap.setToolTip("Фраза может разорваться между соседними репликами "
                               "(«Six?» — «Seven!»), если пауза между ними не больше этой.")
        al.addWidget(self.sp_gap, 3, 1)
        al.addWidget(lab("Новых файлов на тайтл"), 4, 0)
        self.sp_files = _api.QSpinBox()
        self.sp_files.setRange(0, 2000)
        self.sp_files.setSpecialValueText("все")
        self.sp_files.setToolTip("Сколько файлов тайтла можно скачать за один поиск. "
                                 "0 — все. Уже скачанное в кэше проверяется всегда.")
        al.addWidget(self.sp_files, 4, 1)
        al.setColumnStretch(1, 1)
        pv.addWidget(grp_acc)

        # ── Исключить паки (как в ShikimoriHYX) ──────────────────────────────
        grp_packs = _api.QGroupBox("Исключить паки")
        pl = _api.QVBoxLayout(grp_packs); pl.setSpacing(6)
        pl.addWidget(hint("Не брать тайтлы из ответов и текста вопросов выбранных "
                          ".siq-паков — как в ShikimoriHYX."))
        self.chk_excl_fr = _api.QCheckBox("Вместе с их франшизами")
        self.chk_excl_fr.setChecked(True)
        self.chk_excl_fr.setToolTip("Пак с «Наруто» исключает и «Наруто: Ураганные "
                                    "хроники», и фильмы той же франшизы Shikimori.")
        self.chk_excl_fr.toggled.connect(self._on_excl_fr_toggled)
        pl.addWidget(self.chk_excl_fr)
        btns = _api.QHBoxLayout(); btns.setSpacing(6)
        self.btn_packs = _api.QPushButton("Выбрать паки…")
        self.btn_packs.setIcon(_api.get_icon("fa5s.layer-group"))
        self.btn_packs.setToolTip("Паки, открытые в SiQuesterHYX, и/или любые .siq с диска.")
        self.btn_packs.clicked.connect(self._choose_packs)
        self.btn_packs_shiki = _api.QPushButton("Как в ShikimoriHYX")
        self.btn_packs_shiki.setIcon(_api.get_icon("fa5s.tv"))
        self.btn_packs_shiki.setToolTip("Взять тот же набор паков, что выбран в ShikimoriHYX.")
        self.btn_packs_shiki.clicked.connect(self._packs_from_shikimori)
        btns.addWidget(self.btn_packs)
        btns.addWidget(self.btn_packs_shiki)
        pl.addLayout(btns)
        self.lbl_packs = _api.QLabel("Паки не выбраны.")
        self.lbl_packs.setWordWrap(True)
        self.lbl_packs.setStyleSheet(f"color:{_api.C['text2']}; font-size:11px;")
        pl.addWidget(self.lbl_packs)
        pv.addWidget(grp_packs)

        # ── Кэш ──────────────────────────────────────────────────────────────
        grp_cache = _api.QGroupBox("Кэш субтитров")
        cl = _api.QVBoxLayout(grp_cache); cl.setSpacing(6)
        self.lbl_cache = _api.QLabel("…")
        self.lbl_cache.setWordWrap(True)
        self.lbl_cache.setStyleSheet(f"color:{_api.C['text2']}; font-size:11px;")
        cl.addWidget(self.lbl_cache)
        cl.addWidget(hint("Хранятся только реплики (не файлы целиком): любая новая фраза "
                          "ищется по скачанному без сети. Реплики живут 120 дней, списки "
                          "файлов источников — неделю."))
        self.btn_clear_cache = _api.QPushButton("Очистить кэш")
        self.btn_clear_cache.setIcon(_api.get_icon("fa5s.broom"))
        self.btn_clear_cache.clicked.connect(self._clear_cache)
        cl.addWidget(self.btn_clear_cache)
        pv.addWidget(grp_cache)

        # ── Результат ────────────────────────────────────────────────────────
        grp_res = _api.QGroupBox("Результат")
        rl = _api.QVBoxLayout(grp_res); rl.setSpacing(6)
        self.btn_copy_all = _api.QPushButton("Копировать список")
        self.btn_copy_all.setIcon(_api.get_icon("fa5s.copy"))
        self.btn_copy_all.setToolTip("Все найденные тайтлы с репликой — в буфер обмена.")
        self.btn_copy_all.clicked.connect(self._copy_all)
        self.btn_export = _api.QPushButton("Экспорт CSV")
        self.btn_export.setIcon(_api.get_icon("fa5s.file-csv"))
        self.btn_export.clicked.connect(self._export_csv)
        for b in (self.btn_copy_all, self.btn_export):
            b.setEnabled(False)
            rl.addWidget(b)
        pv.addWidget(grp_res)

        pv.addStretch(1)
        scroll.setWidget(panel)
        need = max(panel.minimumSizeHint().width(), 330)
        sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
        scroll.setFixedWidth(need + sb + 12)
        body.addWidget(scroll)

    def _apply_styles(self):
        c = _api.C
        self.setStyleSheet(f"""
            QWidget {{ color: {c['text']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {c['surface3']}; border: 1px solid {c['border']};
                border-radius: 5px; padding: 5px 7px; color: {c['text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {c['accent']};
            }}
            QPushButton {{
                background: {c['surface3']}; border: 1px solid {c['border']};
                border-radius: 5px; padding: 6px 12px; color: {c['text']};
            }}
            QPushButton:hover {{ background: {c['surface2']}; }}
            QPushButton:disabled {{ color: {c['text3']}; }}
            QPushButton#b_primary {{
                background: {c['accent']}; color: #11111b; border: none; font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {c['accent2']}; }}
            QPushButton#subsearch_more {{
                background: transparent; border: none; padding: 2px 6px;
                color: {c['accent']}; font-size: 11px; text-align: left;
            }}
            QToolButton {{ border: none; border-radius: 4px; padding: 2px; }}
            QToolButton:hover {{ background: {c['surface3']}; }}
            QToolButton:checked {{ background: {c['surface3']}; color: {c['accent']}; }}
            QGroupBox {{
                border: 1px solid {c['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold; color: {c['accent']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QListWidget#subsearch_results {{
                background: {c['surface']}; border: 1px solid {c['border']};
                border-radius: 6px; outline: none;
            }}
            QListWidget#subsearch_results::item {{ border-radius: 6px; margin: 2px; }}
            QListWidget#subsearch_results::item:selected {{ background: {c['surface3']}; }}
            QListWidget#subsearch_results::item:hover:!selected {{ background: {c['surface2']}; }}
            QFrame#subsearch_row {{ background: transparent; }}
            /* Подпись со своим стилем иначе заливает прямоугольник цветом окна
               из глобального QWidget{{background}} — серые полосы в карточке. */
            QFrame#subsearch_row QLabel {{ background: transparent; }}
            QFrame#subsearch_quote {{
                background: {c['bg']}; border-left: 3px solid {c['accent']};
                border-radius: 4px;
            }}
            QPlainTextEdit {{
                background: {c['surface']}; border: 1px solid {c['border']};
                border-radius: 6px; font-size: 11px; color: {c['text2']};
            }}
            QProgressBar {{
                background: {c['surface3']}; border: none; border-radius: 4px;
            }}
            QProgressBar::chunk {{ background: {c['accent']}; border-radius: 4px; }}
        """)
