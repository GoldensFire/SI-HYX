# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""Монтаж: построение интерфейса, прогресс и подгонка видеовыхода."""
import edit_tab as _api


class EditTabLayoutMixin:
    """Монтаж: построение интерфейса, прогресс и подгонка видеовыхода."""

    def _build_sidebar(self):
        """Правая боковая панель (инфо/экспорт) внутри QScrollArea.
        Возвращает саму панель и её внутренние контейнеры — они нужны
        секциям «прокси» и «итог», которые дозаполняют ту же панель."""
        # ── Right sidebar (прокручиваемая) ────────────────────────────────
        # Содержимое (инфо/экспорт) живёт в QScrollArea — если по высоте не
        # умещается, появляется вертикальный скроллбар. Кнопки «Итог» и
        # «Обрезать» закреплены ВНЕ прокрутки, снизу (всегда видны).
        sidebar = _api.QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(264)
        sidebar.setStyleSheet(f"""
            #Sidebar {{
                background: {_api.C['surface']};
                border-left: 1px solid {_api.C['border']};
            }}
        """)
        sb_outer = _api.QVBoxLayout(sidebar)
        sb_outer.setContentsMargins(0, 0, 0, 0)
        sb_outer.setSpacing(0)

        sb_scroll = _api.QScrollArea()
        sb_scroll.setObjectName("SidebarScroll")
        sb_scroll.setWidgetResizable(True)
        sb_scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
        sb_scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sb_scroll.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        # Никакого собственного стиля скроллбара — берём общий стиль приложения
        # (config.STYLESHEET), чтобы он совпадал со скроллбарами других вкладок.
        # Фон не задаём (глобальное правило делает контент прозрачным → виден
        # surface самого сайдбара; собственный фон давал серую «подложку»).
        sb_scroll.setStyleSheet("QScrollArea#SidebarScroll { border: none; }")
        sb_content = _api.QWidget()
        sb_layout = _api.QVBoxLayout(sb_content)
        # Правый отступ 14px — «дорожка» для вертикального скроллбара, чтобы он не
        # перекрывал содержимое (панель всегда видна полностью).
        sb_layout.setContentsMargins(16, 16, 14, 16)
        sb_layout.setSpacing(12)

        # File section
        self.lbl_file = _api.QLabel("Нет файла")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet(f"""
            color: {_api.C['text3']};
            font-size: 11px;
            padding: 8px;
            background: {_api.C['surface2']};
            border: 1px dashed {_api.C['border2']};
            border-radius: 6px;
        """)
        self.lbl_file.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        sb_layout.addWidget(self.lbl_file)

        # Кнопки работы с файлом в одну строку: «Открыть» занимает половину
        # ширины, рядом — «Очистить» (убирает текущий файл и сбрасывает редактор).
        file_btn_row = _api.QHBoxLayout()
        file_btn_row.setSpacing(8)
        btn_open = _api.make_icon_btn("Открыть", accent=True, icon='fa5s.folder-open')
        self._relax_width(btn_open)  # не заставляем панель расширяться под текст
        btn_open.clicked.connect(self.open_file)
        btn_clear = _api.make_icon_btn("Очистить", icon='fa5s.trash')
        self._relax_width(btn_clear)
        btn_clear.setToolTip("Убрать текущий файл и очистить редактор")
        btn_clear.clicked.connect(self.clear_file)
        file_btn_row.addWidget(btn_open, 1)
        file_btn_row.addWidget(btn_clear, 1)
        sb_layout.addLayout(file_btn_row)

        sb_layout.addWidget(_api.make_divider())

        # Media info card
        info_card = _api.InfoCard("МЕДИА ИНФОРМАЦИЯ")
        self.lbl_duration = info_card.add_row("Длительность", "lbl_duration")
        self.lbl_fps      = info_card.add_row("FPS",          "lbl_fps")
        self.lbl_vstream  = info_card.add_row("Видео",        "lbl_vstream")
        self.lbl_astream  = info_card.add_row("Аудио",        "lbl_astream")
        self.lbl_abitrate = info_card.add_row("Битрейт аудио", "lbl_abitrate")
        sb_layout.addWidget(info_card)

        sb_layout.addWidget(_api.make_divider())

        # Export settings card
        export_card = _api.InfoCard("НАСТРОЙКИ ЭКСПОРТА")

        mode_lbl = _api.QLabel("Режим обрезки")
        mode_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        export_card._body.addWidget(mode_lbl)

        self.cmb_mode = _api.QComboBox()
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
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_mode.setMinimumContentsLength(8)
        self._relax_width(self.cmb_mode)
        self.cmb_mode.setStyleSheet(f"""
            QComboBox {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                border: 1px solid {_api.C['border2']};
                border-radius: 5px;
                padding: 6px 10px;
                font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 20px; }}
            QComboBox QAbstractItemView {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                selection-background-color: {_api.C['accent']};
                border: 1px solid {_api.C['border2']};
            }}
        """)
        export_card._body.addWidget(self.cmb_mode)

        # Кодировщик для перекодировки (режим «Перекодировать» и границы Smart Cut):
        # CPU (libx264) — лучшее качество/совместимость; GPU — быстрее, грузит
        # видеокарту. На «Быстро (без потерь)» не влияет (там copy без кодека).
        enc_lbl = _api.QLabel("Кодировщик (перекодировка)")
        enc_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        export_card._body.addWidget(enc_lbl)

        self.cmb_encoder = _api.QComboBox()
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
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_encoder.setMinimumContentsLength(8)
        self._relax_width(self.cmb_encoder)
        self.cmb_encoder.setStyleSheet(self.cmb_mode.styleSheet())
        export_card._body.addWidget(self.cmb_encoder)

        self.chk_overwrite = _api.QCheckBox("Перезаписать файл")
        self.chk_overwrite.setChecked(True)
        self._relax_width(self.chk_overwrite)
        self.chk_overwrite.setStyleSheet(f"""
            QCheckBox {{
                color: {_api.C['text2']};
                font-size: 12px;
                spacing: 6px;
                /* Своя таблица стилей иначе красит строку цветом окна —
                   тёмная полоса поперёк карточки. */
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {_api.C['border2']};
                border-radius: 3px;
                background: {_api.C['surface3']};
            }}
            QCheckBox::indicator:checked {{
                background: {_api.C['accent']};
                border-color: {_api.C['accent']};
            }}
        """)
        export_card._body.addWidget(self.chk_overwrite)

        # Вшивание (hardsub) выбранных субтитров прямо в картинку. ВНИМАНИЕ:
        # это всегда требует ПЕРЕКОДИРОВКИ видео (пиксели субтитров рисуются на
        # кадрах) — без перекодировки можно лишь встроить субтитры отдельной
        # дорожкой, но не «вжечь» в изображение. Сам чекбокс размещаем НЕ здесь,
        # а в правой панели рядом с кнопками «Сохранить кадр»/«Удалить исходник»
        # (см. сборку side-панели ниже) — создаём заранее, добавим туда.
        self.chk_burn_subs = _api.QCheckBox("Вшить субтитры")
        self.chk_burn_subs.setChecked(False)
        self._relax_width(self.chk_burn_subs)
        self.chk_burn_subs.setToolTip(
            "Жёстко впечатывает выбранную дорожку субтитров в кадр.\n"
            "Требует перекодировки видео (режим обрезки будет проигнорирован).\n"
            "Субтитры выбираются в панели справа от видео.")
        self.chk_burn_subs.setStyleSheet(self.chk_overwrite.styleSheet())

        # Папка сохранения результата ("" = рядом с исходником)
        dst_lbl = _api.QLabel("Папка сохранения")
        dst_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        self._relax_width(dst_lbl)
        export_card._body.addWidget(dst_lbl)
        self.lbl_export_dir = _api.QLabel("Рядом с исходником")
        # Без переноса (длинный путь не разрывается и распирал бы панель) — вместо
        # этого укорачиваем в середине в _update_export_dir_label; min width 0,
        # чтобы метка не диктовала ширину панели.
        self.lbl_export_dir.setWordWrap(False)
        self.lbl_export_dir.setMinimumWidth(0)
        self._relax_width(self.lbl_export_dir)
        self.lbl_export_dir.setStyleSheet(
            f"color: {_api.C['text2']}; font-size: 11px; padding: 4px 6px; "
            f"background: {_api.C['surface3']}; border: 1px solid {_api.C['border2']}; border-radius: 5px;")
        export_card._body.addWidget(self.lbl_export_dir)
        dst_row = _api.QHBoxLayout(); dst_row.setSpacing(6)
        btn_dst = _api.make_icon_btn("Выбрать", icon='fa5s.folder')
        self._relax_width(btn_dst)
        btn_dst.clicked.connect(self._choose_export_dir)
        btn_dst_reset = _api.make_icon_btn("", icon='fa5s.undo')
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
        pbq_card = _api.InfoCard("ВОСПРОИЗВЕДЕНИЕ")
        pbq_lbl = _api.QLabel("Качество воспроизведения")
        pbq_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        self.cmb_pb_quality = _api.QComboBox()
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
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
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
        pmin_lbl = _api.QLabel("Минут для прокси")
        pmin_lbl.setStyleSheet(f"color: {_api.C['text3']}; font-size: 12px;")
        self.spin_proxy_min = _api.QSpinBox()
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
        self.lbl_proxy = _api.QLabel("")
        self.lbl_proxy.setStyleSheet(f"""
            color: {_api.C['yellow']};
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
        for _w in sb_content.findChildren(_api.QComboBox):
            self._install_wheel_scroll(_w)

    def _build_cut_summary(self, sb_outer):
        """Итог обрезки и кнопка «Обрезать» — закреплены СНИЗУ, вне прокрутки."""
        # ── Итог + кнопка обрезки — закреплены СНИЗУ (вне прокрутки) ───────
        # Высота блока = высоте полосы таймлайна (BAND_H ниже) → «Итог»/«Обрезать»
        # визуально на одной строке с виджетом аудио-визуализации слева.
        sb_bottom = _api.QFrame()
        sb_bottom.setObjectName("SidebarBottom")
        sb_bottom.setFixedHeight(116)
        sb_bottom.setStyleSheet(
            f"#SidebarBottom {{ background: {_api.C['surface']}; border-top: 1px solid {_api.C['border']}; }}")
        bottom_l = _api.QVBoxLayout(sb_bottom)
        bottom_l.setContentsMargins(16, 10, 16, 14)
        bottom_l.setSpacing(10)
        bottom_l.addStretch()

        self.lbl_selection = _api.QLabel("Зона: —")
        self.lbl_selection.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        self.lbl_selection.setStyleSheet(f"""
            color: {_api.C['text']};
            font-size: 13px;
            font-weight: 600;
            padding: 7px 10px;
            background: {_api.C['surface2']};
            border: 1px solid {_api.C['border']};
            border-radius: 6px;
        """)
        bottom_l.addWidget(self.lbl_selection)

        self.btn_cut = _api.QPushButton("Обрезать")
        self.btn_cut.setIcon(_api.get_icon('fa5s.cut', color='#1e1e2e'))
        self.btn_cut.setIconSize(_api.QSize(20, 20))
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
            QPushButton:disabled {{ background: {_api.C['surface3']}; color: {_api.C['text3']}; }}
        """)
        bottom_l.addWidget(self.btn_cut)
        bottom_l.addStretch()
        sb_outer.addWidget(sb_bottom, 0)

        # progress/log_label больше не показываются в интерфейсе (прогресс идёт в
        # общий прогрессбар окна). Оставлены скрытыми, чтобы существующий код,
        # дёргающий .setText()/.setValue(), не падал.
        self.progress = _api.QProgressBar()
        self.progress.setValue(0)
        self.progress.setVisible(False)
        self.log_label = _api.QLabel("")
        self.log_label.setVisible(False)

        # Сайдбар добавляется ПОСЛЕ центральной области (root.addWidget ниже),
        # чтобы видео и плеер были слева, а панель информации/экспорта — справа.

    def _build_center_area(self):
        """Центральная область: холст видео и его оверлеи. Возвращает layout center."""
        # ── Center area ───────────────────────────────────────────────────
        center = _api.QVBoxLayout()
        center.setContentsMargins(0, 0, 0, 0)
        center.setSpacing(0)

        # Video player area + правая панель (дорожки/субтитры/индикатор звука).
        # Панель занимает место, где раньше были чёрные поля сбоку от видео.
        video_row = _api.QHBoxLayout()
        video_row.setContentsMargins(0, 0, 0, 0)
        video_row.setSpacing(0)

        self.video_container = _api.QFrame()
        self.video_container.setObjectName("VideoContainer")
        # Фон — цвет интерфейса (а не чёрный): пустота вокруг кадра сливается с UI.
        self.video_container.setStyleSheet(f"#VideoContainer {{ background: {_api.C['bg']}; }}")
        vc_layout = _api.QHBoxLayout(self.video_container)
        self.vc_layout = vc_layout
        vc_layout.setContentsMargins(0, 0, 0, 0)
        # Видео центрировано (по горизонтали и вертикали); точный аспект кадра
        # задаётся в _adjust_video_height → внутри виджета полей нет, а свободное
        # место по бокам — это фон цвета интерфейса.
        vc_layout.addWidget(self.video_widget, 0, _api.Qt.AlignmentFlag.AlignCenter)
        # Оверлей субтитров (VLC-стиль) создаётся лениво как отдельное окно поверх
        # видео — см. _ensure_overlay/_position_overlay (QVideoWidget нативный,
        # обычный дочерний виджет под ним не виден).
        video_row.addWidget(self.video_container, 1)

        # Правая панель
        side = _api.QFrame()
        side.setObjectName("SidePanel")
        side.setFixedWidth(196)
        side.setStyleSheet(f"#SidePanel {{ background: {_api.C['surface']}; border-left: 1px solid {_api.C['border']}; }}")
        side_outer = _api.QVBoxLayout(side)
        side_outer.setContentsMargins(0, 0, 0, 0)
        side_outer.setSpacing(0)
        # Содержимое панели — в прокрутке, как в правом сайдбаре. Панель растёт
        # динамически (список слоёв появляется вместе с наложенными картинками),
        # и в невысоком окне Qt раньше ужимал виджеты НИЖЕ их минимума: список
        # слоёв сплющивался в синюю полоску, а подпись «Прозрачность» налезала
        # на кнопки слоя. Со скроллом каждый элемент держит свой размер, а при
        # высоком окне поведение прежнее — widgetResizable растягивает
        # содержимое на всю высоту (шкала уровня звука по-прежнему тянется).
        side_scroll = _api.QScrollArea()
        side_scroll.setObjectName("SidePanelScroll")
        side_scroll.setWidgetResizable(True)
        side_scroll.setFrameShape(_api.QFrame.Shape.NoFrame)
        side_scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_scroll.setVerticalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        side_scroll.setStyleSheet("QScrollArea#SidePanelScroll { border: none; }")
        side_content = _api.QWidget()
        side_l = _api.QVBoxLayout(side_content)
        # Правый отступ 4px — дорожка под вертикальный скроллбар, чтобы он не
        # наезжал на комбобоксы (общий стиль приложения даёт узкий ползунок).
        side_l.setContentsMargins(10, 10, 4, 10)
        side_l.setSpacing(6)
        side_scroll.setWidget(side_content)
        side_outer.addWidget(side_scroll)

        _combo_css = f"""
            QComboBox {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                border: 1px solid {_api.C['border2']}; border-radius: 5px;
                padding: 5px 8px; font-size: 12px;
            }}
            QComboBox::drop-down {{ border: none; width: 18px; }}
            QComboBox QAbstractItemView {{
                background: {_api.C['surface3']}; color: {_api.C['text']};
                selection-background-color: {_api.C['accent']};
                border: 1px solid {_api.C['border2']};
            }}
        """
        def _find_btn(tip, slot):
            b = _api.QPushButton()
            b.setIcon(_api.get_icon('fa5s.folder-open'))
            b.setIconSize(_api.QSize(20, 20))
            b.setToolTip(tip)
            b.setCursor(_api.Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(30, 28)
            b.setStyleSheet(f"""
                QPushButton {{ background: {_api.C['surface3']}; color: {_api.C['text']};
                    border: 1px solid {_api.C['border2']}; border-radius: 5px;
                    padding: 0; font-size: 13px; }}
                QPushButton:hover {{ background: {_api.C['border2']};
                    border-color: {_api.C['accent']}; }}
            """)
            b.clicked.connect(slot)
            return b

        lbl_at = _api.QLabel("Аудиодорожка")
        lbl_at.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_at)
        at_row = _api.QHBoxLayout(); at_row.setContentsMargins(0, 0, 0, 0); at_row.setSpacing(5)
        self.cmb_audio = _api.QComboBox()
        self.cmb_audio.setStyleSheet(_combo_css)
        self.cmb_audio.setSizeAdjustPolicy(
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_audio.setMinimumContentsLength(6)
        self.cmb_audio.currentIndexChanged.connect(self.on_audio_track_changed)
        at_row.addWidget(self.cmb_audio, 1)
        self.btn_find_audio = _find_btn(
            "Найти внешний аудиофайл (озвучку) на ПК", self.find_external_audio)
        at_row.addWidget(self.btn_find_audio, 0)
        side_l.addLayout(at_row)

        # Заголовок «Субтитры» + кнопка-карандаш (правка текста субтитров прямо тут).
        st_hdr = _api.QHBoxLayout(); st_hdr.setContentsMargins(0, 0, 0, 0); st_hdr.setSpacing(4)
        lbl_st = _api.QLabel("Субтитры")
        lbl_st.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        st_hdr.addWidget(lbl_st)
        st_hdr.addStretch(1)
        self.btn_edit_subs = _api.QPushButton()
        self.btn_edit_subs.setIcon(_api.get_icon('fa5s.edit', color=_api.C['text2']))
        self.btn_edit_subs.setIconSize(_api.QSize(14, 14))
        self.btn_edit_subs.setFixedSize(24, 20)
        self.btn_edit_subs.setCursor(_api.Qt.CursorShape.PointingHandCursor)
        self.btn_edit_subs.setToolTip("Редактировать текст выбранных субтитров")
        self.btn_edit_subs.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none; border-radius: 4px; }}
            QPushButton:hover {{ background: {_api.C['surface3']}; }}
            QPushButton:pressed {{ background: {_api.C['border2']}; }}
        """)
        self.btn_edit_subs.clicked.connect(self.edit_subtitles)
        st_hdr.addWidget(self.btn_edit_subs)
        side_l.addLayout(st_hdr)
        st_row = _api.QHBoxLayout(); st_row.setContentsMargins(0, 0, 0, 0); st_row.setSpacing(5)
        self.cmb_subs = _api.QComboBox()
        self.cmb_subs.setStyleSheet(_combo_css)
        self.cmb_subs.setSizeAdjustPolicy(
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_subs.setMinimumContentsLength(6)
        self.cmb_subs.currentIndexChanged.connect(self.on_sub_track_changed)
        st_row.addWidget(self.cmb_subs, 1)
        self.btn_find_subs = _find_btn(
            "Найти внешний файл субтитров на ПК", self.find_external_subs)
        st_row.addWidget(self.btn_find_subs, 0)
        side_l.addLayout(st_row)

        # Стиль вшиваемых субтитров (hardsub): как в программе или как в оригинале.
        lbl_ss = _api.QLabel("Стиль вшитых субтитров")
        lbl_ss.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        side_l.addWidget(lbl_ss)
        self.cmb_sub_style = _api.QComboBox()
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
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_sub_style.setMinimumContentsLength(6)
        side_l.addWidget(self.cmb_sub_style)

        # Чекбокс «Вшить субтитры» — НАД индикатором уровня звука (по просьбе
        # пользователя). Кнопки кадра/удаления переехали в самый низ панели.
        # Список наложенных картинок (появляется, только когда слои есть).
        self.overlay_panel = _api.OverlayLayersPanel()
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
        self.btn_crop_frame = _api.make_icon_btn("")
        self.btn_crop_frame.setIcon(_api.get_icon('fa5s.crop-alt'))
        self.btn_crop_frame.setIconSize(_api.QSize(18, 18))
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
        self.btn_pixelize = _api.make_icon_btn("")
        self.btn_pixelize.setIcon(_api.get_icon('fa5s.th'))
        self.btn_pixelize.setIconSize(_api.QSize(18, 18))
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
                background: {_api.C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {_api.C['accent2']}; }}
        """)
        self.btn_save_frame = _api.make_icon_btn("")
        self.btn_save_frame.setIcon(_api.get_icon('fa5s.save'))
        self.btn_save_frame.setIconSize(_api.QSize(20, 20))
        self._relax_width(self.btn_save_frame)
        self.btn_save_frame.setToolTip("Сохранить текущий кадр в PNG (в папку сохранения)")
        self.btn_save_frame.clicked.connect(self.save_frame)
        self.btn_save_frame.setEnabled(False)   # активна только при загруженном видео
        # «Удалить объект» — покадровое удаление водяного знака/эмодзи с видео тем же
        # движком LaMa, что и в фоторедакторе (см. remove_object_from_video).
        self.btn_remove_object = _api.make_icon_btn("")
        self.btn_remove_object.setIcon(_api.get_icon('fa5s.magic'))
        self.btn_remove_object.setIconSize(_api.QSize(18, 18))
        self._relax_width(self.btn_remove_object)
        self.btn_remove_object.setToolTip(
            "Удалить объект с видео (водяной знак, эмодзи, логотип): закрасьте его "
            "кистью на кадре — нейросеть LaMa уберёт его со всех кадров")
        self.btn_remove_object.clicked.connect(self.remove_object_from_video)
        self.btn_remove_object.setEnabled(False)
        # «Создать субтитры» — реплики (текст+тайминг) и позиция на экране задаются
        # в отдельном окне (SubtitleCreatorDialog), результат — новая .ass-дорожка.
        self.btn_create_subs = _api.make_icon_btn("")
        self.btn_create_subs.setIcon(_api.get_icon('fa5s.closed-captioning'))
        self.btn_create_subs.setIconSize(_api.QSize(18, 18))
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
        self.btn_track_object = _api.make_icon_btn("")
        self.btn_track_object.setIcon(_api.get_icon('fa5s.crosshairs'))
        self.btn_track_object.setIconSize(_api.QSize(18, 18))
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
        self.btn_image_overlay = _api.make_icon_btn("")
        self.btn_image_overlay.setIcon(_api.get_icon('fa5s.image'))
        self.btn_image_overlay.setIconSize(_api.QSize(18, 18))
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
        self._build_more_actions()

        # Две колонки по 4 квадратные кнопки (место под 8 штук) — левая и правая,
        # каждая прижата к низу (симметрично высоте шкалы уровня звука справа).
        # Дополнительные действия собраны в нижней кнопке с тремя точками.
        self._montage_side_btns = [self.btn_crop_frame, self.btn_pixelize,
                                   self.btn_save_frame, self.btn_remove_object,
                                   self.btn_create_subs, self.btn_track_object,
                                   self.btn_image_overlay, self.btn_more_actions]
        col_l = _api.QVBoxLayout(); col_l.setContentsMargins(0, 0, 0, 0)
        col_l.setSpacing(self._MSIDE_GAP)
        col_l.addStretch(1)
        for _b in (self.btn_crop_frame, self.btn_pixelize,
                   self.btn_save_frame, self.btn_remove_object):
            col_l.addWidget(_b)
        col_r = _api.QVBoxLayout(); col_r.setContentsMargins(0, 0, 0, 0)
        col_r.setSpacing(self._MSIDE_GAP)
        col_r.addStretch(1)
        for _b in (self.btn_create_subs, self.btn_track_object,
                   self.btn_image_overlay, self.btn_more_actions):
            col_r.addWidget(_b)
        btn_col = _api.QHBoxLayout(); btn_col.setContentsMargins(0, 0, 0, 0)
        btn_col.setSpacing(self._MSIDE_GAP)
        btn_col.addLayout(col_l)
        btn_col.addLayout(col_r)
        btn_col.addStretch(1)   # не растягивать колонки шире квадратных кнопок

        # Правая колонка — подпись + шкала, отцентрованная под текстом.
        vu_col = _api.QVBoxLayout(); vu_col.setContentsMargins(0, 0, 0, 0); vu_col.setSpacing(3)
        lbl_vu = _api.QLabel("Уровень звука")
        lbl_vu.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        lbl_vu.setAlignment(_api.Qt.AlignmentFlag.AlignHCenter)
        vu_col.addWidget(lbl_vu, 0)
        self.audio_meter = _api.AudioMeter()
        self.audio_meter.setFixedWidth(54)
        meter_row = _api.QHBoxLayout(); meter_row.setContentsMargins(0, 0, 0, 0)
        meter_row.addStretch(1)
        meter_row.addWidget(self.audio_meter)
        meter_row.addStretch(1)
        vu_col.addLayout(meter_row, 1)
        # Высота шкалы == высоте колонки кнопок → по её ресайзу пересчитываем кнопки.
        self.audio_meter.installEventFilter(self)

        bottom_row = _api.QHBoxLayout(); bottom_row.setContentsMargins(0, 0, 0, 0)
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
        player_bar = _api.QFrame()
        player_bar.setObjectName("PlayerBar")
        player_bar.setStyleSheet(f"#PlayerBar {{ background: {_api.C['surface']}; border-top: 1px solid {_api.C['border']}; }}")
        pb_layout = _api.QVBoxLayout(player_bar)
        pb_layout.setContentsMargins(12, 6, 12, 7)
        pb_layout.setSpacing(6)

        # Верхняя строка: полоса воспроизведения + тайминги (текущее / общее)
        seek_row = _api.QHBoxLayout()
        seek_row.setContentsMargins(0, 0, 0, 0)
        seek_row.setSpacing(10)

        self.slider = _api.SeekSlider(_api.Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        self.slider.setStyleSheet(self._slider_style(_api.C["playhead"]))
        # Превью кадров при наведении на полосу (как на YouTube). Один контроллер
        # на обе полосы — в окне и в полноэкранном режиме (см. FullscreenVideo).
        self.seek_preview = _api.SeekPreview(lambda: getattr(self, "duration", 0.0) or 0.0)
        self.slider.attach_preview(self.seek_preview)
        seek_row.addWidget(self.slider, 1)

        time_frame = _api.QFrame()
        time_frame.setStyleSheet(f"""
            background: {_api.C['bg']};
            border: 1px solid {_api.C['border']};
            border-radius: 6px;
        """)
        time_fl = _api.QHBoxLayout(time_frame)
        time_fl.setContentsMargins(8, 3, 8, 3)
        time_fl.setSpacing(3)
        _mono = _api.QFont("Courier New" if _api.os.name == 'nt' else "Courier")
        _mono.setBold(True); _mono.setPointSize(11)
        self.lbl_current_time = _api.QLabel("00:00:00.000")
        self.lbl_current_time.setFont(_mono)
        self.lbl_current_time.setStyleSheet(f"color: {_api.C['green2']}; background: transparent;")
        sep_time = _api.QLabel("/")
        sep_time.setStyleSheet(f"color: {_api.C['text3']}; background: transparent;")
        self.lbl_total_time = _api.QLabel("00:00:00.000")
        self.lbl_total_time.setFont(_mono)
        self.lbl_total_time.setStyleSheet(f"color: {_api.C['text3']}; background: transparent;")
        time_fl.addWidget(self.lbl_current_time)
        time_fl.addWidget(sep_time)
        time_fl.addWidget(self.lbl_total_time)
        seek_row.addWidget(time_frame)
        pb_layout.addLayout(seek_row)

        # Нижняя строка: кнопки управления + громкость
        pctrl_row = _api.QHBoxLayout()
        pctrl_row.setContentsMargins(0, 0, 0, 0)
        pctrl_row.setSpacing(6)

        # Кнопки плеера — только иконки, без подписей (квадратные).
        self.btn_stop = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaStop)
        self.btn_stop.setFixedWidth(40)
        self.btn_stop.setToolTip("Стоп — к началу зоны")
        self.btn_stop.clicked.connect(self.stop_playback)
        pctrl_row.addWidget(self.btn_stop)

        self.btn_step_back = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSeekBackward)
        self.btn_step_back.setFixedWidth(40)
        self.btn_step_back.setToolTip("Кадр назад (←)")
        self.btn_step_back.clicked.connect(_api.partial(self.step_frame_scrub, -1))
        pctrl_row.addWidget(self.btn_step_back)

        self.btn_play = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaPlay, accent=True)
        self.btn_play.setFixedWidth(48)
        self.btn_play.setToolTip("Воспроизвести / пауза (Пробел)")
        self.btn_play.clicked.connect(self.toggle_play)
        pctrl_row.addWidget(self.btn_play)

        self.btn_step_fwd = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSeekForward)
        self.btn_step_fwd.setFixedWidth(40)
        self.btn_step_fwd.setToolTip("Кадр вперёд (→)")
        self.btn_step_fwd.clicked.connect(_api.partial(self.step_frame_scrub, 1))
        pctrl_row.addWidget(self.btn_step_fwd)

        self.btn_jump_end = _api.make_icon_btn("", icon_std=_api.QStyle.StandardPixmap.SP_MediaSkipForward)
        self.btn_jump_end.setFixedWidth(40)
        self.btn_jump_end.setToolTip("Перейти к концу зоны (OUT)")
        self.btn_jump_end.clicked.connect(lambda: self.seek_to(self.current_out))
        pctrl_row.addWidget(self.btn_jump_end)

        pctrl_row.addSpacing(14)

        # Поля ввода таймкода IN/OUT убраны по запросу — вместо них кнопки
        # «Обрезать старт/конец» (до плейхеда) и длительность выделения. Сами
        # объекты in_time_edit/out_time_edit/in_frame_spin/out_frame_spin остаются
        # СКРЫТЫМИ держателями: на них завязан остальной код (set_in_out и т.п.).
        io_holder = _api.QWidget(player_bar)
        io_h = _api.QHBoxLayout(io_holder); io_h.setContentsMargins(0, 0, 0, 0)
        self.in_time_edit = _api.QLineEdit("00:00:00.000")
        self.in_time_edit.returnPressed.connect(self.set_in_point)
        self.in_frame_spin = _api.QSpinBox(); self.in_frame_spin.setMaximum(100000000)
        self.in_frame_spin.valueChanged.connect(self.on_in_frame_changed)
        self.out_time_edit = _api.QLineEdit("00:00:05.000")
        self.out_time_edit.returnPressed.connect(self.set_out_point)
        self.out_frame_spin = _api.QSpinBox(); self.out_frame_spin.setMaximum(100000000)
        self.out_frame_spin.valueChanged.connect(self.on_out_frame_changed)
        for _w in (self.in_time_edit, self.in_frame_spin,
                   self.out_time_edit, self.out_frame_spin):
            io_h.addWidget(_w)
        io_holder.hide()

        _trim_btn_css = f"""
            QPushButton {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                border: 1px solid {_api.C['border2']};
                border-radius: 6px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {_api.C['surface2']}; border-color: {_api.C['accent']}; }}
            QPushButton:pressed {{ background: {_api.C['surface']}; }}
            QPushButton:disabled {{ color: {_api.C['text3']}; }}
        """
        _ss = getattr(self, "trim_start_seq", "Shift+C")
        _es = getattr(self, "trim_end_seq", "Shift+V")
        self.btn_trim_start = _api.QPushButton("Обрезать старт")
        self.btn_trim_start.setToolTip(
            f"Поставить начало (старт) на жёлтую полосу воспроизведения ({_ss})")
        self.btn_trim_start.setStyleSheet(_trim_btn_css)
        # NoFocus: иначе клик мыши уводил клавиатурный фокус на кнопку, и потом
        # Space/Ctrl+Z воспринимались как нажатие кнопки/уходили мимо вкладки
        # (баг «после кнопок Обрезать Ctrl+Z не работает»). Фокус оставляем на
        # вкладке монтажа — там висят все хоткеи (WidgetWithChildrenShortcut).
        self.btn_trim_start.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_trim_start.clicked.connect(self.trim_start_to_playhead)
        pctrl_row.addWidget(self.btn_trim_start)

        self.btn_trim_end = _api.QPushButton("Обрезать конец")
        self.btn_trim_end.setToolTip(
            f"Поставить конец на жёлтую полосу воспроизведения ({_es})")
        self.btn_trim_end.setStyleSheet(_trim_btn_css)
        self.btn_trim_end.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_trim_end.clicked.connect(self.trim_end_to_playhead)
        pctrl_row.addWidget(self.btn_trim_end)

        # Длительность отрезка от старта (IN) до жёлтой полосы воспроизведения.
        seg_frame = _api.QFrame()
        seg_frame.setObjectName("SegFrame")
        seg_frame.setStyleSheet(f"#SegFrame {{ background: {_api.C['surface3']}; border: 1px solid {_api.C['border2']}; border-radius: 6px; }}")
        seg_l = _api.QHBoxLayout(seg_frame)
        seg_l.setContentsMargins(8, 4, 8, 4); seg_l.setSpacing(6)
        seg_cap = _api.QLabel("⏱ старт→плейхед")
        seg_cap.setStyleSheet(f"color: {_api.C['text3']}; font-size: 11px; font-weight: 700;")
        self.lbl_seg_dur = _api.QLabel("00:00:00.000")
        self.lbl_seg_dur.setStyleSheet(f"color: {_api.C['text']}; font-size: 12px; font-weight: 700;")
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
        self.btn_audio_only = _api.make_icon_btn("")
        self.btn_audio_only.setIcon(_api.get_icon('fa5s.headphones'))
        self.btn_audio_only.setIconSize(_api.QSize(18, 18))
        self.btn_audio_only.setFixedWidth(40)
        self.btn_audio_only.setCheckable(True)
        # NoFocus — иначе клик уводит фокус с вкладки и Пробел начинает жать
        # кнопку вместо воспроизведения (та же беда, что у «Обрезать старт»).
        self.btn_audio_only.setFocusPolicy(_api.Qt.FocusPolicy.NoFocus)
        self.btn_audio_only.setToolTip(
            "Только звук: отключить видео в плеере, чтобы не лагало.\n"
            "На обрезку и экспорт не влияет — там видео остаётся.")
        # make_icon_btn не стилизует :checked — подсвечиваем включённый режим
        # акцентом, иначе не видно, что видео отключено намеренно.
        self.btn_audio_only.setStyleSheet(self.btn_audio_only.styleSheet() + f"""
            QPushButton:checked {{
                background: {_api.C['accent']}; color: #11111b;
                border: 1px solid transparent;
            }}
            QPushButton:checked:hover {{ background: {_api.C['accent2']}; }}
        """)
        self.btn_audio_only.toggled.connect(self._toggle_audio_only)
        self.btn_audio_only.setEnabled(False)   # активна только при видео
        pctrl_row.addWidget(self.btn_audio_only)

        pctrl_row.addSpacing(8)

        # Регулятор громкости — у правого края, рядом с полноэкранным режимом.
        # (Кнопки «Сохранить кадр»/«Удалить исходник» — внизу боковой панели.)
        self.vol_lbl = _api.VolumeLabel(lambda: getattr(self, "vol_slider", None))
        self.vol_lbl.setStyleSheet(f"color: {_api.C['text2']}; font-size: 14px;")
        # Клик по динамику — mute/unmute с возвратом прежнего уровня.
        self.vol_lbl.clicked.connect(self.toggle_mute)
        pctrl_row.addWidget(self.vol_lbl)
        self.vol_slider = _api.VolumeSlider(_api.Qt.Orientation.Horizontal)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(100)
        self.vol_slider.setFixedWidth(96)
        self.vol_slider.setStyleSheet(self._slider_style(_api.C["text2"], compact=True))
        self.vol_slider.valueChanged.connect(self._on_volume_changed)
        pctrl_row.addWidget(self.vol_slider)

        pctrl_row.addSpacing(8)
        self.btn_fullscreen = _api.make_icon_btn("", accent=True)
        # Стартует без видео → disabled и приглушённая иконка (станет белой при
        # загрузке видео в _update_media_buttons).
        self.btn_fullscreen.setIcon(_api._fullscreen_icon(expand=True, color=_api.C['text3']))
        self.btn_fullscreen.setIconSize(_api.QSize(20, 20))
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
        timeline_panel = _api.QFrame()
        timeline_panel.setObjectName("TimelinePanel")
        timeline_panel.setFixedHeight(BAND_H)
        timeline_panel.setStyleSheet(f"#TimelinePanel {{ background: {_api.C['surface']}; border-top: 1px solid {_api.C['border']}; }}")
        tp_layout = _api.QVBoxLayout(timeline_panel)
        tp_layout.setContentsMargins(12, 6, 12, 6)
        tp_layout.setSpacing(3)

        # Горизонтальная прокрутка волны — над виджетом визуализации аудио.
        # Видна только когда волна увеличена (zoom>1) и есть что прокручивать;
        # двигает «окно обзора» (view_offset) по таймлайну.
        self.wave_scroll = _api.QScrollBar(_api.Qt.Orientation.Horizontal)
        self.wave_scroll.setObjectName("WaveScroll")
        self.wave_scroll.setRange(0, 0)
        self.wave_scroll.valueChanged.connect(self.on_wave_scroll)
        self.wave_scroll.setVisible(False)
        self.wave_scroll.setStyleSheet(f"""
            QScrollBar:horizontal {{
                background: {_api.C['surface2']};
                height: 12px;
                border-radius: 6px;
                margin: 0;
            }}
            QScrollBar::handle:horizontal {{
                background: {_api.C['border2']};
                border-radius: 5px;
                min-width: 28px;
            }}
            QScrollBar::handle:horizontal:hover {{ background: {_api.C['accent']}; }}
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
            QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{ background: transparent; }}
        """)
        tp_layout.addWidget(self.wave_scroll)

        # Waveform — невысокая полоса (амплитуда у обычного звука небольшая, при
        # большой высоте сверху/снизу остаётся пустота). Ограничиваем высоту и
        # оставляем небольшой отступ снизу (margin tp_layout).
        self.waveform = _api.WaveformWidget()
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
        self.waveform.setContextMenuPolicy(_api.Qt.ContextMenuPolicy.CustomContextMenu)
        self.waveform.customContextMenuRequested.connect(self._trim_ctx_menu)
        tp_layout.addWidget(self.waveform, stretch=1)

        # Строка «ПРОКРУТКА» убрана по запросу. pan_slider оставлен как скрытый
        # объект (без родителя, никогда не показывается) — чтобы существующий код
        # update_pan_slider_values не падал; pan_row_w намеренно НЕ создаём
        # (getattr → None → строка панорамирования не отображается).
        self.pan_slider = _api.QSlider(_api.Qt.Orientation.Horizontal)
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
                background: {_api.C['surface3']};
                border-radius: 3px;
                height: {h};
            }}
            QSlider::handle:horizontal {{
                background: {color};
                border: 2px solid {_api.C['bg']};
                width: 13px; height: 13px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::sub-page:horizontal {{
                background: {color};
                border-radius: 3px;
            }}
        """

    def apply_theme(self):
        # Тёмная тема редактора применяется к этому виджету и его потомкам,
        # переопределяя общий стиль приложения только в пределах вкладки.
        self.setStyleSheet(f"""
            QWidget {{
                background: {_api.C['bg']};
                color: {_api.C['text']};
                font-family: 'Segoe UI', 'SF Pro Display', 'Helvetica Neue', Arial, sans-serif;
                font-size: 13px;
            }}
            QToolTip {{
                background: {_api.C['surface3']};
                color: {_api.C['text']};
                border: 1px solid {_api.C['border2']};
                border-radius: 4px;
                padding: 4px 8px;
                font-size: 12px;
            }}
            QLabel {{ background: transparent; }}
            QMessageBox {{ background: {_api.C['surface']}; }}
            QFileDialog {{ background: {_api.C['surface']}; }}
        """)

    def _install_wheel_scroll(self, widget):
        """Заставляет виджет (комбобокс и т.п.) НЕ менять значение на колесо
        мыши, а прокручивать ближайшую QScrollArea-родителя — так колесо над
        полем прокручивает панель, как и над пустым местом."""
        def handler(event, _w=widget):
            sa = _w.parent()
            while sa is not None and not isinstance(sa, _api.QScrollArea):
                sa = sa.parent()
            if isinstance(sa, _api.QScrollArea):
                _api.QApplication.sendEvent(sa.viewport(), event)
            else:
                event.ignore()
        widget.wheelEvent = handler

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
                if not busy and pct <= 0 and hasattr(self.main, 'clear_global_result'):
                    self.main.clear_global_result()
                self.main.update_global_progress(
                    -1 if busy else pct,
                    text or ("Монтаж" if busy or 0 < pct < 100 else
                             ("Готово" if pct >= 100 else "Ожидание")))
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
            self.video_widget = _api.VideoCanvas()
            try:
                self.player.setVideoSink(self.video_widget.videoSink())
            except Exception:
                pass
        else:
            self.video_widget = _api.QVideoWidget()
            try:
                self.video_widget.setAspectRatioMode(_api.Qt.AspectRatioMode.KeepAspectRatio)
            except Exception:
                pass
            self.player.setVideoOutput(self.video_widget)
        self.video_widget.setStyleSheet(f"background: {_api.C['bg']};")
        # Анти-overshoot: VideoCanvas сам ловит кадр за OUT по PTS → просит паузу.
        if isinstance(self.video_widget, _api.VideoCanvas):
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
        if (isinstance(self.video_widget, _api.VideoCanvas)
                and getattr(self.video_widget, "_quick", None) is None):
            try:
                if self.main is not None and hasattr(self.main, "log"):
                    self.main.log("Монтаж: сцена Qt Quick не поднялась — кадры "
                                  "рисуются на ЦП (заметно медленнее)")
            except Exception:
                pass

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
            if isinstance(vw, _api.VideoCanvas):
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
        _api.QTimer.singleShot(0, self._position_overlay)
        # QTabWidget помнит, какой дочерний виджет был в фокусе на этой странице
        # в прошлый раз (например, кнопка «Открыть» или комбобокс «Режим
        # обрезки») и возвращает фокус ЕМУ при переключении на вкладку. Из-за
        # этого мгновенный Space сразу после переключения на «Монтаж» не играл
        # видео (шорткат Space зарегистрирован на self), а активировал
        # сфокусированный виджет — жал кнопку/раскрывал комбобокс. Перехватываем
        # фокус на себя при каждом показе вкладки, чтобы Space гарантированно
        # доставался toggle_play, а не случайному виджету боковой панели.
        if self._ready:
            _api.QTimer.singleShot(0, self.setFocus)

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
        for w in self.findChildren(_api.QWidget):
            try:
                w.setAcceptDrops(True)
                w.installEventFilter(self)
            except Exception:
                pass
        self.installEventFilter(self)

    # ── Папка экспорта ──────────────────────────────────────────────────────
    def _choose_export_dir(self):
        start = self.export_dir or (str(self.actual_source_file.parent)
                                    if self.actual_source_file else "")
        d = _api.QFileDialog.getExistingDirectory(self, "Папка для сохранения обрезки", start)
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
        if self.export_dir and _api.os.path.isdir(self.export_dir):
            # Укорачиваем путь в середине, чтобы он не распирал панель; полный
            # путь — в подсказке.
            fm = _api.QFontMetrics(lbl.font())
            elided = fm.elidedText(self.export_dir, _api.Qt.TextElideMode.ElideMiddle, 210)
            lbl.setText(elided)
            lbl.setToolTip(self.export_dir)
        else:
            lbl.setText("Рядом с исходником")
            lbl.setToolTip("Файл сохраняется в папке исходника")
