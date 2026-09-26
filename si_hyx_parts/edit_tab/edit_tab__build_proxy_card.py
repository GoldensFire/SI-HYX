# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""EditTab: _build_proxy_card. Public namespace: edit_tab."""
import edit_tab as _api


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
