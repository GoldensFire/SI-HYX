# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriTab: _build_settings_panel. Public namespace: shikimori_tab."""
import shikimori_tab as _api


def _build_settings_panel(self, body):
    scroll = _api.QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setHorizontalScrollBarPolicy(_api.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
    # Фиксированную ширину задаём в КОНЦЕ метода — по реальной потребности
    # содержимого + место под вертикальный скроллбар, чтобы панель ВСЕГДА была
    # видна по горизонтали целиком (см. ниже scroll.setFixedWidth).
    panel = _api.QWidget()
    pv = _api.QVBoxLayout(panel)
    pv.setContentsMargins(2, 2, 8, 2)
    pv.setSpacing(12)

    def lab(text):
        l = _api.QLabel(text)
        l.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        # Перенос по словам: длинные подписи (напр. «Проверять просмотров у»)
        # иначе задают огромную ширину 0-й колонки сетки и раздувают панель.
        l.setWordWrap(True)
        return l

    # ── Группа «Фильтры» ──────────────────────────────────────────────
    grp = _api.QGroupBox("Фильтры")
    filt = _api.QGridLayout(grp)
    filt.setHorizontalSpacing(8)
    filt.setVerticalSpacing(8)

    self.sp_score_min = _api.ClearableDoubleSpinBox()
    self.sp_score_min.setRange(0.0, 10.0); self.sp_score_min.setSingleStep(0.5)
    self.sp_score_min.setDecimals(1)
    self.sp_score_min.setSpecialValueText("любая")
    self.sp_score_max = _api.ClearableDoubleSpinBox()
    self.sp_score_max.setRange(0.0, 10.0); self.sp_score_max.setSingleStep(0.5)
    self.sp_score_max.setDecimals(1)
    # Минимум (0) показываем как «любая» = без верхней границы; так очистка
    # поля Backspace'ом осмысленна (сброс фильтра, а не «оценка ≤ 0»).
    self.sp_score_max.setSpecialValueText("любая")
    self.sp_score_max.setValue(10.0)

    self.cb_kind = _api.QComboBox()
    self.cb_status = _api.QComboBox()
    self.cb_order = _api.QComboBox()
    # «По просмотрам» — локальная сортировка, по умолчанию (первый пункт).
    # «По индексу популярности» — тоже локальная (просмотры × свежесть).
    self.cb_order.addItem(_api.ORDER_LABELS[_api.ORDER_VIEWS], _api.ORDER_VIEWS)
    self.cb_order.addItem(_api.ORDER_LABELS[_api.ORDER_INDEX], _api.ORDER_INDEX)
    for o in _api.ORDERS:
        self.cb_order.addItem(_api.ORDER_LABELS.get(o, o), o)
    # Сколько верхних тайтлов проверять на число просмотров при сортировке
    # «По просмотрам» (раньше было жёстко зашито _VIEWS_SORT_MAX=100).
    self.sp_views_max = _api.QSpinBox()
    self.sp_views_max.setRange(10, 2000)
    self.sp_views_max.setSingleStep(10)
    self.sp_views_max.setValue(_api._VIEWS_SORT_MAX)
    self.sp_views_max.setToolTip(
        "Сколько верхних тайтлов проверять на число просмотров при сортировке "
        "«По просмотрам». Больше — точнее порядок, но дольше дозагрузка "
        "(≈0.7 с на тайтл; лимит Shikimori ~90 запросов/мин).")
    self.cb_order.currentIndexChanged.connect(self._update_views_max_enabled)

    # Автостоп поиска по достижению числа тайтлов ПОСЛЕ фильтрации (паки/
    # франшизы/оценка и пр.) — не гонять поиск по всей базе, если нужного
    # числа уже хватает. 0 = без лимита.
    self.sp_stop_limit = _api.QSpinBox()
    self.sp_stop_limit.setRange(0, 100000)
    self.sp_stop_limit.setSingleStep(50)
    self.sp_stop_limit.setSpecialValueText("без лимита")
    self.sp_stop_limit.setValue(_api._STOP_LIMIT_DEFAULT)
    self.sp_stop_limit.setToolTip(
        "Останавливать поиск автоматически, как только ПОСЛЕ фильтрации "
        "(паки/франшизы/оценка и т.д.) наберётся столько тайтлов. "
        "0 — без лимита.")

    self.sp_year_from = _api.QSpinBox(); self.sp_year_from.setRange(0, 2099)
    self.sp_year_from.setSpecialValueText("—")
    self.sp_year_to = _api.QSpinBox(); self.sp_year_to.setRange(0, 2099)
    self.sp_year_to.setSpecialValueText("—")

    self.sp_ep_min = _api.QSpinBox(); self.sp_ep_min.setRange(0, 10000)
    self.sp_ep_min.setSpecialValueText("—")
    self.sp_ep_max = _api.QSpinBox(); self.sp_ep_max.setRange(0, 10000)
    self.sp_ep_max.setSpecialValueText("—")

    # Жанры/темы — множественный выбор через диалог (как фильтры Shikimori),
    # потому что одиночный список не давал комбинировать жанр+тему. Кнопка
    # показывает, что выбрано; сам список грузится асинхронно.
    self.btn_genres = _api.QPushButton("Любые")
    self.btn_genres.setToolTip("Выбрать жанры и темы (можно несколько)")
    self.btn_genres.clicked.connect(self._open_genre_picker)

    # Комбобоксы по умолчанию растягиваются под самый длинный пункт (напр.
    # «По просмотрам», длинные жанры) и раздували панель так, что её правый
    # край обрезался. Ограничиваем ширину: ~12 символов минимум, длиннее —
    # эллипсис. Колонки 1/3 имеют stretch, поэтому в доступной ширине панели
    # комбобоксы всё равно растянутся и обычные подписи видны полностью.
    for _c in (self.cb_kind, self.cb_status, self.cb_order):
        _c.setSizeAdjustPolicy(
            _api.QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        _c.setMinimumContentsLength(10)
    # Спинбоксы тоже ограничиваем по минимуму, иначе их «минимальная» ширина
    # (под спецтекст «любая» + стрелки) держит панель широкой. С stretch колонок
    # 1/3 в доступной ширине они всё равно растянутся.
    for _s in (self.sp_score_min, self.sp_score_max, self.sp_views_max,
               self.sp_stop_limit,
               self.sp_year_from, self.sp_year_to, self.sp_ep_min, self.sp_ep_max):
        _s.setMinimumWidth(58)

    r = 0
    filt.addWidget(lab("Оценка от"), r, 0); filt.addWidget(self.sp_score_min, r, 1)
    filt.addWidget(lab("до"), r, 2); filt.addWidget(self.sp_score_max, r, 3)
    r += 1
    filt.addWidget(lab("Сортировка"), r, 0)
    filt.addWidget(self.cb_order, r, 1, 1, 3)
    r += 1
    self.lbl_views_max = lab("Проверять просмотров у")
    filt.addWidget(self.lbl_views_max, r, 0)
    filt.addWidget(self.sp_views_max, r, 1, 1, 3)
    r += 1
    filt.addWidget(lab("Остановиться после"), r, 0)
    filt.addWidget(self.sp_stop_limit, r, 1, 1, 3)
    r += 1
    filt.addWidget(lab("Тип"), r, 0)
    filt.addWidget(self.cb_kind, r, 1, 1, 3)
    r += 1
    filt.addWidget(lab("Статус"), r, 0)
    filt.addWidget(self.cb_status, r, 1, 1, 3)
    r += 1
    filt.addWidget(lab("Жанры/темы"), r, 0)
    filt.addWidget(self.btn_genres, r, 1, 1, 3)
    r += 1
    self.lbl_eps = lab("Эпизоды от")
    filt.addWidget(self.lbl_eps, r, 0); filt.addWidget(self.sp_ep_min, r, 1)
    filt.addWidget(lab("до"), r, 2); filt.addWidget(self.sp_ep_max, r, 3)
    r += 1
    filt.addWidget(lab("Год с"), r, 0); filt.addWidget(self.sp_year_from, r, 1)
    filt.addWidget(lab("по"), r, 2); filt.addWidget(self.sp_year_to, r, 3)
    for col in (1, 3):
        filt.setColumnStretch(col, 1)
    pv.addWidget(grp)

    self.btn_reset = _api.QPushButton("Сбросить настройки")
    self.btn_reset.setIcon(_api.get_icon('fa5s.undo'))
    self.btn_reset.setToolTip("Сбросить все фильтры и выбранные паки к значениям по умолчанию")
    self.btn_reset.clicked.connect(self.reset_settings)
    pv.addWidget(self.btn_reset)

    # ── Схлопывание франшиз (сезоны/части → один тайтл) ───────────────
    # Текст короткий (без «(один сезон/часть)») — иначе чекбокс не переносится
    # и задаёт минимальную ширину панели ~460 px. Подробности — в подсказке.
    self.chk_collapse_fr = _api.QCheckBox("Схлопывать франшизы")
    self.chk_collapse_fr.setChecked(self._collapse_franchise)
    self.chk_collapse_fr.setToolTip(
        "Скрывать из выдачи прочие сезоны/части той же франшизы — достаточно "
        "одного тайтла.\nНапр. «Атака титанов 2», «Бездомный бог: Арагото», "
        "«Наруто: Ураганные хроники» прячутся, если уже показан первый.\n"
        "Также пак с «Наруто» спрячет и «Наруто: Ураганные хроники».")
    self.chk_collapse_fr.toggled.connect(self._on_collapse_toggled)
    pv.addWidget(self.chk_collapse_fr)

    # ── Группа «Исключить паки SiQuesterHYX» ──────────────────────────
    grp_packs = _api.QGroupBox("Исключить паки SiQuesterHYX")
    pl = _api.QVBoxLayout(grp_packs)
    pl.setSpacing(6)
    info = _api.QLabel("Спрятать из выдачи тайтлы, которые уже есть в ответах "
                  "выбранных .siq-паков.")
    info.setWordWrap(True)
    info.setStyleSheet(f"color:{_api.C['text3']}; font-size:11px;")
    pl.addWidget(info)
    self.btn_packs = _api.QPushButton("Выбрать паки…")
    self.btn_packs.setIcon(_api.get_icon('fa5s.layer-group'))
    self.btn_packs.clicked.connect(self._choose_packs)
    pl.addWidget(self.btn_packs)
    self.lbl_packs = _api.QLabel("Паки не выбраны.")
    self.lbl_packs.setWordWrap(True)
    self.lbl_packs.setStyleSheet(f"color:{_api.C['text2']}; font-size:11px;")
    pl.addWidget(self.lbl_packs)
    pv.addWidget(grp_packs)

    # ── Действия (открыть/экспорт) ────────────────────────────────────
    grp_act = _api.QGroupBox("Результат")
    al = _api.QVBoxLayout(grp_act)
    al.setSpacing(6)
    self.btn_open = _api.QPushButton("Открыть на Shikimori")
    self.btn_open.setIcon(_api.get_icon('fa5s.external-link-alt'))
    self.btn_open.clicked.connect(self._open_selected_in_browser)
    self.btn_export_json = _api.QPushButton("Экспорт JSON")
    self.btn_export_json.setIcon(_api.get_icon('fa5s.file-code'))
    self.btn_export_json.clicked.connect(lambda: self._export("json"))
    self.btn_export_csv = _api.QPushButton("Экспорт CSV")
    self.btn_export_csv.setIcon(_api.get_icon('fa5s.file-csv'))
    self.btn_export_csv.clicked.connect(lambda: self._export("csv"))
    for b in (self.btn_open, self.btn_export_json, self.btn_export_csv):
        b.setEnabled(False)
        al.addWidget(b)
    pv.addWidget(grp_act)

    pv.addStretch(1)
    scroll.setWidget(panel)
    # Ширина = реальная потребность содержимого + место под вертикальный
    # скроллбар. Комбобоксы выше ограничены по ширине, поэтому асинхронная
    # загрузка длинных жанров/типов панель НЕ раздувает → она всегда видна
    # по горизонтали целиком при любом размере окна.
    # По МИНИМАЛЬНОЙ потребности (не preferred — иначе панель неоправданно
    # широкая) + запас и место под скроллбар. Колонки 1/3 со stretch растянут
    # комбобоксы/спинбоксы в этой ширине, поэтому подписи видны полностью.
    _need = max(panel.minimumSizeHint().width(), 320)
    _sb = max(scroll.verticalScrollBar().sizeHint().width(), 14)
    scroll.setFixedWidth(_need + _sb + 12)
    body.addWidget(scroll)

def eventFilter(self, obj, ev):
    # Над кнопкой «копировать» в строке списка показываем курсор-«руку».
    if obj is self.list.viewport() and ev.type() == _api.QEvent.Type.MouseMove:
        try:
            pos = ev.position().toPoint()
        except AttributeError:           # старые сборки Qt
            pos = ev.pos()
        over = False
        idx = self.list.indexAt(pos)
        if idx.isValid():
            # Берём ТОЧНЫЕ прямоугольники, сохранённые делегатом в paint()
            # (реальной опцией Qt). Ручная реконструкция опции теряла фичи
            # декорации → зона «руки» уезжала от видимой иконки.
            try:
                aid = idx.data(_api.Qt.ItemDataRole.UserRole + 1)
                main_r = self._views_delegate._copy_rects.get(aid)
                orig_r = self._views_delegate._copy_orig_rects.get(aid)
                over = (bool(main_r) and main_r.contains(pos)) or (
                    bool(orig_r) and not orig_r.isNull() and orig_r.contains(pos))
            except Exception:
                over = False
        if over != self._copy_hover:
            self._copy_hover = over
            self.list.viewport().setCursor(
                _api.Qt.CursorShape.PointingHandCursor if over
                else _api.Qt.CursorShape.ArrowCursor)
    return super(_api.ShikimoriTab, self).eventFilter(obj, ev)

def _apply_styles(self):
    self.setStyleSheet(f"""
            QWidget {{ color: {_api.C['text']}; }}
            QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 5px 7px; color: {_api.C['text']};
            }}
            QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
                border: 1px solid {_api.C['accent']};
            }}
            QPushButton {{
                background: {_api.C['surface3']}; border: 1px solid {_api.C['border']};
                border-radius: 5px; padding: 6px 12px; color: {_api.C['text']};
            }}
            QPushButton:hover {{ background: {_api.C['surface2']}; }}
            QPushButton:disabled {{ color: {_api.C['text3']}; }}
            QPushButton#b_primary {{
                background: {_api.C['accent']}; color: #11111b; border: none; font-weight: 700;
            }}
            QPushButton#b_primary:hover {{ background: {_api.C['accent2']}; }}
            QGroupBox {{
                border: 1px solid {_api.C['border']}; border-radius: 6px;
                margin-top: 10px; padding-top: 8px; font-weight: bold;
                color: {_api.C['accent']};
            }}
            QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
            QListWidget {{
                background: {_api.C['surface']}; border: 1px solid {_api.C['border']};
                border-radius: 6px; outline: none;
            }}
            QListWidget::item {{
                padding: 4px 4px 4px {_api._RANK_W}px; border-radius: 5px; color: {_api.C['text']};
            }}
            QListWidget::item:selected {{ background: {_api.C['surface3']}; color: {_api.C['text']}; }}
            QListWidget::item:hover:!selected {{ background: {_api.C['surface2']}; }}
        """)

# ── Тип контента (Аниме/Манга) ────────────────────────────────────────────
def _content_type(self) -> str:
    return self.cb_content.currentData() or _api.CONTENT_ANIME

def _on_content_changed(self, *_):
    ct = self._content_type()
    self._rebuild_kind_status()
    # Эпизоды → главы для манги (подпись поля).
    self.lbl_eps.setText("Главы от" if ct == _api.CONTENT_MANGA else "Эпизоды от")
    # Жанры/темы различаются между аниме и мангой — сбрасываем выбор и (при
    # необходимости) подгружаем список под новый тип.
    self._sel_genres = []
    self._pending_genres = []
    self._excl_genres = []
    self._pending_excl = []
    self._update_genres_btn()
    if ct not in self._genres_cache:
        self._load_genres_async(ct)
    # Старые результаты больше не релевантны.
    self.list.clear()
    self._raw_results = []; self._results = []
    self._set_actions_enabled(False)
    self.lbl_status.setText("Готово к поиску.")
