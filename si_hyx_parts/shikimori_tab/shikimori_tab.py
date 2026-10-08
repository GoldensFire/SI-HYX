# -*- coding: utf-8 -*-
# SI-HYX — Copyright (C) 2026 GoldensFire; GNU GPL v3 or later.
# See LICENSE and the public module for attribution and API.
"""ShikimoriTab. Public namespace: shikimori_tab."""
import shikimori_tab as _api
from si_hyx_parts.shikimori_tab.search_results import ShikimoriSearchMixin


# ─── Вкладка ─────────────────────────────────────────────────────────────────
class ShikimoriTab(ShikimoriSearchMixin, _api.QWidget):
    """Экспериментальная вкладка поиска аниме/манги через Shikimori API.

    Включается/выключается в Настройках (по умолчанию выключена). Не зависит от
    QtMultimedia и тяжёлых модулей — грузится быстро.
    """

    def __init__(self, main_window=None):
        super().__init__()
        self.main = main_window
        self._pool = _api.QThreadPool.globalInstance()
        self._task = None          # текущая поисковая задача (ссылка, чтобы жила)
        self._cache_only = False   # True — «Найти по кэшу»: без дозагрузки просмотров
        self._genres_task = None
        self._results: list = []   # последние найденные Anime (после исключений)
        self._raw_results: list = []   # до применения исключения паков
        self._genres_cache: dict = {}  # content_type -> [(id, label, group)]
        self._thumb_cache: dict = {}   # anime_id -> QIcon
        self._thumb_pending: set = set()  # anime_id с уже запущенной загрузкой обложки
        self._placeholder = None       # серая заглушка-обложка
        self._excluded: set = set()    # нормализованные названия из паков
        self._excluded_bases: set = set()  # их «базовые» формы (без сезонов)
        self._excluded_franchises: set = set()  # их «ключи франшиз» (без подзаголовков)
        self._excluded_packs: list = []  # имена выбранных паков
        self._collapse_franchise = True   # схлопывать сезоны/части одной франшизы
        self._seen_franchises: set = set()  # уже показанные франшизы (для схлопывания)
        # Просмотры и индекс берутся из базы генератора аниме-паков (pack_index):
        # здесь только то, что уже узнали в этом сеансе.
        self._views_cache: dict = {}   # anime_id -> просмотры (для сортировки)
        self._index_cache: dict = {}   # anime_id -> индекс популярности генератора
        self._index_rows: dict = {}    # anime_id -> строка базы генератора (подсказка)
        # Подчистка дискового кеша обложек — с задержкой, чтобы не тормозить старт.
        _api.QTimer.singleShot(3000, _api._prune_covers_cache)
        self._views_task = None        # текущая задача дозагрузки просмотров
        self._anime_by_id: dict = {}   # anime_id -> Anime (для live-обновления строк)
        self._sel_genres: list = []    # выбранные id жанров/тем (текущий тип контента)
        self._pending_genres: list = []  # id для восстановления после async-загрузки
        self._excl_genres: list = []   # исключаемые id жанров/тем
        self._pending_excl: list = []  # исключаемые id для восстановления после async
        self._initial_settings = dict(getattr(main_window, "_shikimori_settings", {}) or {})

        if not _api._HAS_API:
            self._build_unavailable()
            return
        self._build_ui()
        # Восстанавливаем сохранённые настройки (если есть) ДО загрузки жанров,
        # чтобы корректно подтянуть жанры под нужный тип контента.
        if self._initial_settings:
            try:
                self.apply_settings(self._initial_settings)
            except Exception:
                pass
        self._load_genres_async(self._content_type())

    # ── Построение UI ───────────────────────────────────────────────────────
    def _build_unavailable(self):
        lay = _api.QVBoxLayout(self)
        msg = ("Не удалось загрузить вкладку «ShikimoriHYX».\n\n"
               "Нужен пакет «requests» (pip install requests).")
        if _api._IMPORT_ERROR:
            msg += f"\n\n{_api._IMPORT_ERROR}"
        lbl = _api.QLabel(msg)
        lbl.setAlignment(_api.Qt.AlignmentFlag.AlignCenter)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{_api.C['text2']}; font-size:13px;")
        lay.addStretch(); lay.addWidget(lbl); lay.addStretch()

    def _build_ui(self):
        root = _api.QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Строка поиска: тип контента + запрос + кнопки ─────────────────
        search_row = _api.QHBoxLayout()
        search_row.setSpacing(8)
        self.cb_content = _api.QComboBox()
        self.cb_content.addItem("Аниме", _api.CONTENT_ANIME)
        self.cb_content.addItem("Манга", _api.CONTENT_MANGA)
        self.cb_content.setFixedWidth(110)
        self.cb_content.currentIndexChanged.connect(self._on_content_changed)
        self.ed_query = _api.QLineEdit()
        self.ed_query.setPlaceholderText("Название (можно пусто — тогда фильтры)…")
        self.ed_query.setClearButtonEnabled(True)
        self.ed_query.returnPressed.connect(lambda: self.start_search(False))
        self.ed_query.addAction(_api.get_icon('fa5s.search'),
                                _api.QLineEdit.ActionPosition.LeadingPosition)
        self.btn_search = _api.QPushButton("Найти")
        self.btn_search.setIcon(_api.get_icon('fa5s.search', color='#11111b'))
        self.btn_search.setIconSize(_api.QSize(16, 16))
        self.btn_search.setObjectName("b_primary")
        self.btn_search.clicked.connect(lambda: self.start_search(False))
        self.btn_search_cache = _api.QPushButton("По кэшу")
        self.btn_search_cache.setIcon(_api.get_icon('fa5s.database'))
        self.btn_search_cache.setToolTip(
            "Тот же поиск, но БЕЗ дозагрузки просмотров по сети для сортировки —\n"
            "используются только уже закешированные ранее числа (за один день "
            "просмотры почти не меняются).\nБыстрее, но новые/незнакомые тайтлы "
            "могут остаться внизу списка (без данных).")
        self.btn_search_cache.clicked.connect(lambda: self.start_search(True))
        self.btn_cancel = _api.QPushButton("Стоп")
        self.btn_cancel.setIcon(_api.get_icon('fa5s.stop'))
        self.btn_cancel.setToolTip("Остановить поиск (накопленные результаты останутся)")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self.cancel_search)
        self.btn_clear = _api.QPushButton("Очистить")
        self.btn_clear.setIcon(_api.get_icon('fa5s.trash'))
        self.btn_clear.setToolTip("Очистить список результатов")
        self.btn_clear.clicked.connect(self.clear_results)
        search_row.addWidget(self.cb_content)
        search_row.addWidget(self.ed_query, 1)
        search_row.addWidget(self.btn_search)
        search_row.addWidget(self.btn_search_cache)
        search_row.addWidget(self.btn_cancel)
        search_row.addWidget(self.btn_clear)
        root.addLayout(search_row)

        # ── Тело: слева список с обложками, справа панель настроек ─────────
        body = _api.QHBoxLayout()
        body.setSpacing(12)
        root.addLayout(body, 1)

        # Левая колонка — список результатов.
        left = _api.QVBoxLayout(); left.setSpacing(6)
        self.list = _api.QListWidget()
        self.list.setIconSize(_api.QSize(_api._THUMB_W, _api._THUMB_H))
        self.list.setSpacing(2)
        self.list.setUniformItemSizes(False)
        self.list.setWordWrap(True)
        self.list.itemDoubleClicked.connect(self._open_selected_in_browser)
        self.list.itemSelectionChanged.connect(self._on_selection_changed)
        # Значок «глаз» + просмотры рисует делегат (qtawesome SVG, не emoji).
        self._views_delegate = _api._ViewsBadgeDelegate(self)
        self.list.setItemDelegate(self._views_delegate)
        # Курсор-«рука» при наведении на кнопку «копировать» (видно, что кликабельно).
        self.list.setMouseTracking(True)
        self.list.viewport().setMouseTracking(True)
        self.list.viewport().installEventFilter(self)
        self._copy_hover = False
        # Обложки грузим ЛЕНИВО — только для видимых строк (иначе при широком
        # поиске сотни параллельных запросов к Shikimori упираются в лимит → 429).
        self.list.verticalScrollBar().valueChanged.connect(
            lambda *_: self._load_visible_thumbs())
        left.addWidget(self.list, 1)
        self.lbl_status = _api.QLabel("Готово к поиску.")
        self.lbl_status.setStyleSheet(f"color:{_api.C['text2']}; font-size:12px;")
        left.addWidget(self.lbl_status)
        body.addLayout(left, 1)

        # Правая колонка — прокручиваемая панель настроек.
        self._build_settings_panel(body)

        self._apply_styles()
        self._rebuild_kind_status()

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
        return super().eventFilter(obj, ev)

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

    def _load_visible_thumbs(self):
        """Запускает загрузку обложек ТОЛЬКО для строк, попадающих в видимую
        область списка. Уже загруженные (кеш) и уже запрошенные (pending) —
        пропускаем. Вызывается при наполнении списка и при прокрутке."""
        n = self.list.count()
        if not n:
            return
        vp = self.list.viewport().rect()
        for i in range(n):
            it = self.list.item(i)
            if it is None:
                continue
            r = self.list.visualItemRect(it)
            if r.bottom() < vp.top() or r.top() > vp.bottom():
                continue
            aid = it.data(_api.Qt.ItemDataRole.UserRole + 1)
            if aid in self._thumb_cache or aid in self._thumb_pending:
                continue
            # Сперва — дисковый кеш (мгновенно, без сети): постеры за день не
            # меняются, повторно качать их незачем.
            pm = _api._load_cover_from_disk(aid)
            if pm is not None:
                icon = _api.QIcon(pm)
                self._thumb_cache[aid] = icon
                it.setIcon(icon)
                continue
            a = self._anime_by_id.get(aid)
            if a is None or not a.image_url:
                continue
            self._thumb_pending.add(aid)
            task = _api._ThumbTask(aid, a.image_url)
            task.signals.done.connect(self._on_thumb_loaded)
            self._pool.start(task)

    def _on_thumb_loaded(self, anime_id: int, data: bytes):
        self._thumb_pending.discard(anime_id)
        pm = _api.QPixmap()
        if not pm.loadFromData(data):
            return
        pm = pm.scaled(_api._THUMB_W, _api._THUMB_H, _api.Qt.AspectRatioMode.KeepAspectRatio,
                       _api.Qt.TransformationMode.SmoothTransformation)
        icon = _api.QIcon(pm)
        self._thumb_cache[anime_id] = icon
        _api._save_cover_to_disk(anime_id, pm)
        # Находим строку с этим id и ставим иконку (список мог быть перестроен).
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(_api.Qt.ItemDataRole.UserRole + 1) == anime_id:
                it.setIcon(icon)
                break

    def _on_selection_changed(self):
        has_sel = self.list.currentItem() is not None
        self.btn_open.setEnabled(has_sel and bool(self._results))

    def _open_selected_in_browser(self, *_):
        it = self.list.currentItem()
        if it is None:
            return
        url = it.data(_api.Qt.ItemDataRole.UserRole)
        if url:
            try:
                _api.webbrowser.open(url)
            except Exception:
                pass

    # ── Исключение паков SiQuesterHYX ──────────────────────────────────────────
    def _siq_datasets(self):
        """Список загруженных в SiQuesterHYX датасетов или [] если вкладки нет."""
        tsq = getattr(self.main, "tab_siquester", None) if self.main else None
        inner = getattr(tsq, "inner", None) if tsq else None
        return list(getattr(inner, "datasets", []) or []) if inner else []

    @staticmethod
    def _pack_answers(ds) -> set:
        """Собирает нормализованные ответы из одного .siq-пака."""
        out = set()
        w = ds.get("widget")
        siq = getattr(w, "_siq", None) if w else None
        rounds = getattr(siq, "rounds", []) if siq else []
        for rd in rounds:
            for th in rd.get("themes", []):
                for q in th.get("questions", []):
                    answers = list(q.get("answers", []) or [])
                    for it in q.get("items", []):
                        if (it.get("param") == "answer"
                                and it.get("type") == "text"
                                and not it.get("is_ref")):
                            answers.append(it.get("text", ""))
                    for ans in answers:
                        # Один ответ нередко содержит несколько вариантов тайтла
                        # через « / » или « | » («Охотник x Охотник / Hunter x
                        # Hunter (1999)») — разбиваем, чтобы в исключения попал и
                        # русский, и ромадзи-вариант по отдельности. Делим только
                        # по разделителю С ПРОБЕЛАМИ, чтобы не рвать «Fate/stay».
                        for part in _api.re.split(r"\s+[/|]\s+", ans or ""):
                            n = _api._norm_title(part)
                            if n:
                                out.add(n)
        return out

    def _choose_packs(self):
        datasets = self._siq_datasets()
        if not datasets:
            _api.msgbox_information(
                self, "Паки SiQuesterHYX",
                "Нет загруженных паков.\n\nВключите вкладку «SiQuesterHYX» в "
                "Настройках и откройте в ней .siq-пак(и), затем повторите.")
            return
        dlg = _api.QDialog(self)
        dlg.setWindowTitle("Выбор паков для исключения")
        dlg.setMinimumWidth(380)
        lay = _api.QVBoxLayout(dlg)
        lay.addWidget(_api.QLabel("Тайтлы из ответов отмеченных паков будут скрыты "
                             "из выдачи поиска:"))
        checks = []
        for idx, ds in enumerate(datasets):
            name = ds.get("pkg_name") or f"Пак {idx + 1}"
            cb = _api.QCheckBox(name)
            cb.setChecked(name in self._excluded_packs)
            lay.addWidget(cb)
            checks.append((cb, ds, name))
        line = _api.QFrame(); line.setFrameShape(_api.QFrame.Shape.HLine)
        line.setStyleSheet(f"color:{_api.C['border']};")
        lay.addWidget(line)
        bb = _api.QDialogButtonBox(_api.QDialogButtonBox.StandardButton.Ok
                              | _api.QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        lay.addWidget(bb)
        if dlg.exec() != _api.QDialog.DialogCode.Accepted:
            return
        excluded = set()
        chosen_names = []
        for cb, ds, name in checks:
            if cb.isChecked():
                chosen_names.append(name)
                excluded |= self._pack_answers(ds)
        self._excluded = excluded
        self._rebuild_excluded_bases()
        self._excluded_packs = chosen_names
        if chosen_names:
            self.lbl_packs.setText(
                f"Выбрано паков: {len(chosen_names)} "
                f"({len(excluded)} ответов).\n" + ", ".join(chosen_names))
        else:
            self.lbl_packs.setText("Паки не выбраны.")
        # Переприменяем к уже найденному (без нового запроса).
        if self._raw_results:
            self._apply_exclusions()

    # ── Жанры (асинхронно) ───────────────────────────────────────────────────
    def _load_genres_async(self, content_type: str):
        if self._genres_task is not None:
            return
        task = _api._GenresTask(content_type)
        task.signals.finished.connect(self._on_genres_loaded)
        task.signals.failed.connect(lambda *_: setattr(self, "_genres_task", None))
        self._genres_task = task
        self._pool.start(task)

    def _on_genres_loaded(self, content_type: str, genres: list):
        self._genres_task = None
        items = []
        for g in genres:
            gid = g.get("id")
            if gid is None:
                continue
            label = g.get("russian") or g.get("name") or str(gid)
            items.append((int(gid), label, _api.genre_group(g)))
        items.sort(key=lambda x: x[1].lower())
        self._genres_cache[content_type] = items
        # Применяем отложенный (восстановленный из настроек) выбор — только те id,
        # что реально есть в списке этого типа контента.
        if content_type == self._content_type():
            valid = {gid for gid, _, _ in items}
            if self._pending_genres:
                self._sel_genres = [g for g in self._pending_genres if g in valid]
                self._pending_genres = []
            if self._pending_excl:
                self._excl_genres = [g for g in self._pending_excl if g in valid]
                self._pending_excl = []
            self._update_genres_btn()

    def _open_genre_picker(self):
        ct = self._content_type()
        items = self._genres_cache.get(ct)
        if not items:
            # Список ещё не пришёл — подгрузим и попросим повторить чуть позже.
            self._load_genres_async(ct)
            _api.msgbox_information(
                self, "Жанры и темы",
                "Список жанров ещё загружается — повторите через секунду.")
            return
        dlg = _api._GenrePickerDialog(items, self._sel_genres, self._excl_genres, self)
        if dlg.exec():
            self._sel_genres = dlg.selected_ids()
            self._excl_genres = dlg.excluded_ids()
            self._update_genres_btn()

    def _update_genres_btn(self):
        """Подпись кнопки выбора жанров/тем: «Любые», сами названия (если выбран/
        исключён 1–2) или «Выбрано: N, исключено: M»."""
        inc = len(self._sel_genres)
        exc = len(self._excl_genres)
        if inc == 0 and exc == 0:
            self.btn_genres.setText("Любые")
            return
        lookup = {gid: label
                  for gid, label, _ in self._genres_cache.get(
                      self._content_type(), [])}
        if inc + exc <= 2:
            parts = [lookup.get(g, str(g)) for g in self._sel_genres]
            parts += [f"−{lookup.get(g, str(g))}" for g in self._excl_genres]
            self.btn_genres.setText(", ".join(parts))
        else:
            bits = []
            if inc:
                bits.append(f"выбрано: {inc}")
            if exc:
                bits.append(f"искл.: {exc}")
            self.btn_genres.setText(", ".join(bits))

    # ── Сохранение / восстановление / сброс настроек ───────────────────────────
    def get_settings(self) -> dict:
        """Текущие настройки вкладки (для сохранения в settings.json)."""
        if not _api._HAS_API:
            return dict(self._initial_settings)
        return {
            "content_type": self._content_type(),
            "query": self.ed_query.text().strip(),
            "score_min": self.sp_score_min.value(),
            "score_max": self.sp_score_max.value(),
            "order": self.cb_order.currentData() or "ranked",
            "views_max": int(self.sp_views_max.value()),
            "stop_limit": int(self.sp_stop_limit.value()),
            "kind": self.cb_kind.currentData() or "",
            "status": self.cb_status.currentData() or "",
            "genres": list(self._sel_genres),
            "excl_genres": list(self._excl_genres),
            "year_from": self.sp_year_from.value(),
            "year_to": self.sp_year_to.value(),
            "ep_min": self.sp_ep_min.value(),
            "ep_max": self.sp_ep_max.value(),
            "excluded_packs": list(self._excluded_packs),
            "collapse_franchise": bool(self._collapse_franchise),
        }

    def apply_settings(self, s: dict):
        """Восстанавливает настройки из словаря (вызывается при создании вкладки)."""
        if not _api._HAS_API or not isinstance(s, dict):
            return
        ct = s.get("content_type", _api.CONTENT_ANIME)
        idx = self.cb_content.findData(ct)
        if idx >= 0:
            self.cb_content.blockSignals(True)
            self.cb_content.setCurrentIndex(idx)
            self.cb_content.blockSignals(False)
            self._rebuild_kind_status()
            self.lbl_eps.setText("Главы от" if ct == _api.CONTENT_MANGA else "Эпизоды от")
        self.ed_query.setText(str(s.get("query", "")))
        self._collapse_franchise = bool(s.get("collapse_franchise", True))
        self.chk_collapse_fr.blockSignals(True)
        self.chk_collapse_fr.setChecked(self._collapse_franchise)
        self.chk_collapse_fr.blockSignals(False)
        self.sp_score_min.setValue(float(s.get("score_min", 0.0) or 0.0))
        self.sp_score_max.setValue(float(s.get("score_max", 10.0) or 10.0))
        oi = self.cb_order.findData(s.get("order", _api.ORDER_VIEWS))
        if oi >= 0:
            self.cb_order.setCurrentIndex(oi)
        self.sp_views_max.setValue(
            int(s.get("views_max", _api._VIEWS_SORT_MAX) or _api._VIEWS_SORT_MAX))
        self._update_views_max_enabled()
        self.sp_stop_limit.setValue(
            int(s.get("stop_limit", _api._STOP_LIMIT_DEFAULT) or 0))
        ki = self.cb_kind.findData(s.get("kind", ""))
        if ki >= 0:
            self.cb_kind.setCurrentIndex(ki)
        si = self.cb_status.findData(s.get("status", ""))
        if si >= 0:
            self.cb_status.setCurrentIndex(si)
        self.sp_year_from.setValue(int(s.get("year_from", 0) or 0))
        self.sp_year_to.setValue(int(s.get("year_to", 0) or 0))
        self.sp_ep_min.setValue(int(s.get("ep_min", 0) or 0))
        self.sp_ep_max.setValue(int(s.get("ep_max", 0) or 0))
        # Жанры/темы подтянутся после загрузки списка (см. _on_genres_loaded).
        # Поддерживаем и старый формат настроек (один «genre»: int).
        gids = s.get("genres")
        if gids is None:
            one = int(s.get("genre", 0) or 0)
            gids = [one] if one else []
        self._pending_genres = [int(x) for x in gids if x]
        self._pending_excl = [int(x) for x in (s.get("excl_genres") or []) if x]
        ct = self._content_type()
        if ct in self._genres_cache:
            valid = {gid for gid, _, _ in self._genres_cache[ct]}
            self._sel_genres = [g for g in self._pending_genres if g in valid]
            self._pending_genres = []
            self._excl_genres = [g for g in self._pending_excl if g in valid]
            self._pending_excl = []
        self._update_genres_btn()
        # Выбранные паки восстанавливаем (если SiQuesterHYX уже загрузил их).
        names = list(s.get("excluded_packs", []) or [])
        if names:
            self._restore_packs(names)

    def _restore_packs(self, names: list):
        """Восстанавливает исключаемые паки по именам (если они уже загружены)."""
        wanted = set(names)
        excluded = set()
        found = []
        for idx, ds in enumerate(self._siq_datasets()):
            name = ds.get("pkg_name") or f"Пак {idx + 1}"
            if name in wanted:
                found.append(name)
                excluded |= self._pack_answers(ds)
        # Имена помним даже если паки ещё не открыты — попадут при следующем выборе.
        self._excluded_packs = found or list(names)
        self._excluded = excluded
        self._rebuild_excluded_bases()
        if found:
            self.lbl_packs.setText(
                f"Выбрано паков: {len(found)} ({len(excluded)} ответов).\n"
                + ", ".join(found))
        elif names:
            self.lbl_packs.setText(
                "Сохранённые паки не загружены в SiQuesterHYX — откройте их там.")

    def reset_settings(self):
        """Сбрасывает все фильтры и выбранные паки к значениям по умолчанию."""
        if not _api._HAS_API:
            return
        self.cb_content.setCurrentIndex(0)   # Аниме (вызовет _on_content_changed)
        self.ed_query.clear()
        self.sp_score_min.setValue(0.0)
        self.sp_score_max.setValue(10.0)
        self.cb_order.setCurrentIndex(0)
        self.sp_views_max.setValue(_api._VIEWS_SORT_MAX)
        self._update_views_max_enabled()
        self.sp_stop_limit.setValue(_api._STOP_LIMIT_DEFAULT)
        self.cb_kind.setCurrentIndex(0)
        self.cb_status.setCurrentIndex(0)
        self._sel_genres = []
        self._pending_genres = []
        self._excl_genres = []
        self._pending_excl = []
        self._update_genres_btn()
        self.sp_year_from.setValue(0)
        self.sp_year_to.setValue(0)
        self.sp_ep_min.setValue(0)
        self.sp_ep_max.setValue(0)
        self._excluded = set()
        self._excluded_bases = set()
        self._excluded_franchises = set()
        self._excluded_packs = []
        self._collapse_franchise = True
        self.chk_collapse_fr.blockSignals(True)
        self.chk_collapse_fr.setChecked(True)
        self.chk_collapse_fr.blockSignals(False)
        self.lbl_packs.setText("Паки не выбраны.")
        self.lbl_status.setText("Настройки сброшены.")

    # ── Экспорт ──────────────────────────────────────────────────────────────
    def _export(self, fmt: str):
        if not self._results:
            return
        if fmt == "json":
            path, _ = _api.QFileDialog.getSaveFileName(
                self, "Сохранить как JSON", "shikimori.json", "JSON (*.json)")
        else:
            path, _ = _api.QFileDialog.getSaveFileName(
                self, "Сохранить как CSV", "shikimori.csv", "CSV (*.csv)")
        if not path:
            return
        rows = [a.as_row() for a in self._results]
        try:
            if fmt == "json":
                with open(path, "w", encoding="utf-8") as f:
                    _api.json.dump(rows, f, ensure_ascii=False, indent=2)
            else:
                with open(path, "w", encoding="utf-8-sig", newline="") as f:
                    w = _api.csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
        except Exception as e:
            _api.msgbox_critical(self, "Экспорт", f"Не удалось сохранить файл:\n{e}")
            return
        self.lbl_status.setText(f"Сохранено: {_api.os.path.basename(path)} ({len(rows)})")
        if self.main is not None and hasattr(self.main, "log"):
            try:
                self.main.log(f"ShikimoriHYX: экспортировано {len(rows)} → {path}")
            except Exception:
                pass

    # ── Очистка (вызывается главным окном при закрытии/выключении вкладки) ────
    def cleanup(self):
        if self._task is not None:
            try:
                self._task.stop()
            except Exception:
                pass
            self._task = None
        self._stop_views_task()
        if self._genres_task is not None:
            try:
                self._genres_task.signals.finished.disconnect()
            except Exception:
                pass
            self._genres_task = None


ShikimoriTab.__module__ = _api.__name__
_api.ShikimoriTab = ShikimoriTab
